"""Unit tests for `src.bootstrap.analysis_steps`.

Every fake here is a real Port implementation, never a `unittest.mock` double, matching this
repository's own established testing convention (see e.g. `tests/integration/test_reference_flow.
py`'s own `_RecordingRepositoryClient`). No test in this file performs real clone I/O, network
access, or filesystem-tree walking against a real git repository -- see
`tests/integration/test_real_repository_analysis.py` for that.
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest
from src.bootstrap.analysis_steps import (
    _all_parsers,
    _clone_repository_func,
    _enumerate_files,
    _parse_files_func,
    _require_single_repository,
    _select_successful_parse_results,
    build_analysis_steps,
)
from src.bootstrap.errors import BootstrapError
from src.core.config import AppConfig
from src.domain.entities import RepositoryProvider, SourceLanguage, SourceRepository
from src.parsers.base import FileMetadata, ParseResult, compute_content_hash
from src.parsers.cpp.parser import CppParser
from src.parsers.go.parser import GoParser
from src.parsers.python.parser import PythonParser
from src.parsers.rust.parser import RustParser
from src.parsers.typescript.parser import TypeScriptParser
from src.pipeline.steps import CallableStep, MapStep
from src.repository.base import RepositoryClient, WorkspaceManager


def _config(raw: dict[str, object]) -> AppConfig:
    """Build an `AppConfig` directly from a raw mapping, bypassing `load_config`/YAML/env."""
    return AppConfig(raw=raw)


def _repository(name: str = "repo") -> SourceRepository:
    """Build a minimal valid `SourceRepository` for use as test input."""
    return SourceRepository(
        name=name, source_uri=f"/tmp/{name}", provider=RepositoryProvider.FILESYSTEM
    )


def _parsed(relative_path: str, *, succeeded: bool = True) -> ParseResult:
    """Build a minimal valid `ParseResult`, successful unless `succeeded=False`."""
    if not succeeded:
        return ParseResult.failed(
            relative_path=relative_path,
            language=SourceLanguage.UNKNOWN,
            error_message="no parser supports this file",
        )
    metadata = FileMetadata(
        relative_path=relative_path,
        language=SourceLanguage.PYTHON,
        size_bytes=0,
        line_count=0,
        content_hash=compute_content_hash(""),
    )
    return ParseResult.ok(
        relative_path=relative_path, language=SourceLanguage.PYTHON, metadata=metadata
    )


class _RecordingRepositoryClient(RepositoryClient):
    """A real `RepositoryClient` implementation that records every `clone` call instead of
    invoking `git`."""

    def __init__(self) -> None:
        self.cloned: list[tuple[SourceRepository, Path]] = []

    async def clone(
        self, repository: SourceRepository, destination: Path, *, shallow: bool = True
    ) -> None:
        self.cloned.append((repository, destination))

    async def fetch(self, workspace_path: Path) -> None:
        pass

    async def checkout(self, workspace_path: Path, ref: str) -> None:
        pass

    async def current_commit(self, workspace_path: Path) -> str:
        return "0" * 40

    async def default_branch(self, workspace_path: Path) -> str:
        return "main"


class _FixedWorkspaceManager(WorkspaceManager):
    """A real `WorkspaceManager` implementation allocating a fixed, predictable path per
    repository id, under a `tmp_path`-rooted directory."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def allocate(self, repository_id: UUID) -> Path:
        path = self._root / str(repository_id)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def resolve(self, repository_id: UUID) -> Path | None:
        path = self._root / str(repository_id)
        return path if path.is_dir() else None

    def exists(self, repository_id: UUID) -> bool:
        return (self._root / str(repository_id)).is_dir()

    def remove(self, repository_id: UUID) -> None:
        pass


# --- 1-4: _require_single_repository ---------------------------------------------------------


def test_require_single_repository_accepts_zero() -> None:
    """Zero repositories is not an error; the empty tuple is returned unchanged."""
    assert _require_single_repository(()) == ()


def test_require_single_repository_accepts_one() -> None:
    """Exactly one repository is returned unchanged."""
    repository = _repository()
    assert _require_single_repository((repository,)) == (repository,)


def test_require_single_repository_rejects_multiple() -> None:
    """More than one repository raises `BootstrapError`."""
    repositories = (_repository("a"), _repository("b"))
    with pytest.raises(BootstrapError):
        _require_single_repository(repositories)


def test_require_single_repository_error_details() -> None:
    """The raised `BootstrapError` carries the exact repository count and names."""
    repositories = (_repository("a"), _repository("b"))
    with pytest.raises(BootstrapError) as exc_info:
        _require_single_repository(repositories)
    assert exc_info.value.details == {
        "repository_count": 2,
        "repository_names": ["a", "b"],
    }


# --- 5: _clone_repository_func --------------------------------------------------------------


@pytest.mark.asyncio
async def test_clone_repository_func_allocates_and_clones(tmp_path: Path) -> None:
    """The bound closure allocates a workspace and clones the exact repository into it."""
    repository_client = _RecordingRepositoryClient()
    workspace_manager = _FixedWorkspaceManager(tmp_path)
    repository = _repository()

    clone = _clone_repository_func(repository_client, workspace_manager)
    destination = await clone(repository)

    assert destination == tmp_path / str(repository.id)
    assert repository_client.cloned == [(repository, destination)]


# --- 6-11: _enumerate_files -------------------------------------------------------------------


def test_enumerate_files_is_deterministic(tmp_path: Path) -> None:
    """Enumerating the same workspace twice produces identical, ordered output."""
    (tmp_path / "b.py").write_text("b", encoding="utf-8")
    (tmp_path / "a.py").write_text("a", encoding="utf-8")
    first = _enumerate_files((tmp_path,))
    second = _enumerate_files((tmp_path,))
    assert first == second
    assert first == (("a.py", "a"), ("b.py", "b"))


def test_enumerate_files_excludes_dot_directories(tmp_path: Path) -> None:
    """A directory whose name starts with `.` (e.g. `.git`) is never descended into."""
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("secret", encoding="utf-8")
    (tmp_path / "app.py").write_text("app", encoding="utf-8")
    files = _enumerate_files((tmp_path,))
    assert files == (("app.py", "app"),)


def test_enumerate_files_sorts_directories(tmp_path: Path) -> None:
    """Subdirectories are visited in sorted order, so output order is deterministic regardless
    of filesystem iteration order."""
    (tmp_path / "z").mkdir()
    (tmp_path / "z" / "f.py").write_text("z", encoding="utf-8")
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "f.py").write_text("a", encoding="utf-8")
    files = _enumerate_files((tmp_path,))
    assert [path for path, _ in files] == [
        str(Path("a") / "f.py"),
        str(Path("z") / "f.py"),
    ]


def test_enumerate_files_sorts_filenames(tmp_path: Path) -> None:
    """Files within one directory are visited in sorted order."""
    (tmp_path / "z.py").write_text("z", encoding="utf-8")
    (tmp_path / "a.py").write_text("a", encoding="utf-8")
    files = _enumerate_files((tmp_path,))
    assert [path for path, _ in files] == ["a.py", "z.py"]


def test_enumerate_files_decodes_utf8(tmp_path: Path) -> None:
    """File content is read back exactly, decoded as UTF-8, including non-ASCII text."""
    (tmp_path / "greeting.py").write_text("# héllo", encoding="utf-8")
    files = _enumerate_files((tmp_path,))
    assert files == (("greeting.py", "# héllo"),)


def test_enumerate_files_skips_undecodable_files(tmp_path: Path) -> None:
    """A file that cannot be decoded as UTF-8 text is silently skipped, not raised."""
    (tmp_path / "good.py").write_text("good", encoding="utf-8")
    (tmp_path / "bad.bin").write_bytes(b"\x00\x01\xff\xfe")
    files = _enumerate_files((tmp_path,))
    assert files == (("good.py", "good"),)


# --- 12-14: _all_parsers / _parse_files_func --------------------------------------------------


def test_all_parsers_returns_all_five() -> None:
    """`_all_parsers` returns exactly the five existing concrete `Parser` implementations."""
    parsers = _all_parsers()
    assert [type(parser) for parser in parsers] == [
        PythonParser,
        RustParser,
        GoParser,
        TypeScriptParser,
        CppParser,
    ]


def test_parse_files_dispatches_by_supports() -> None:
    """A supported file is routed to the first parser whose `supports()` returns True."""
    parse = _parse_files_func(_all_parsers())
    result = parse(("a.py", "def f():\n    pass\n"))
    assert result.succeeded is True
    assert result.language == SourceLanguage.PYTHON


def test_parse_files_reports_unsupported_file_as_failed() -> None:
    """A file no parser supports produces a failed `ParseResult`, not a raised exception."""
    parse = _parse_files_func(_all_parsers())
    result = parse(("README.md", "# readme"))
    assert result.succeeded is False
    assert result.error_message is not None


# --- 15-17: _select_successful_parse_results ---------------------------------------------------


def test_select_successful_parse_results_preserves_order() -> None:
    """Successful results are kept in their original relative order."""
    ok_a = _parsed("a.py")
    ok_b = _parsed("b.py")
    parse_results = (ok_a, _parsed("x.md", succeeded=False), ok_b)
    assert _select_successful_parse_results(parse_results) == (ok_a, ok_b)


def test_select_successful_parse_results_excludes_failures() -> None:
    """Failed results are excluded entirely from the filtered tuple."""
    failed = _parsed("x.md", succeeded=False)
    filtered = _select_successful_parse_results((failed,))
    assert filtered == ()


def test_select_successful_parse_results_does_not_mutate_input() -> None:
    """The original `parse_results` tuple is untouched -- filtering returns a new tuple."""
    ok = _parsed("a.py")
    failed = _parsed("x.md", succeeded=False)
    parse_results = (ok, failed)
    _select_successful_parse_results(parse_results)
    assert parse_results == (ok, failed)


# --- 18-21: build_analysis_steps shape ---------------------------------------------------------


_EXPECTED_STEP_NAMES = [
    "require_single_repository",
    "clone_repositories",
    "enumerate_files",
    "parse_files",
    "select_successful_parse_results",
    "extract_imports",
    "extract_ast",
    "extract_symbols",
    "extract_architecture",
    "extract_interfaces",
    "extract_foundation",
]


def test_build_analysis_steps_exact_names(tmp_path: Path) -> None:
    """The eleven returned steps carry exactly these names -- no more, no fewer, none renamed."""
    config = _config({"repository": {"workspace_root": str(tmp_path)}})
    steps = build_analysis_steps(config)
    assert sorted(step.name for step in steps) == sorted(_EXPECTED_STEP_NAMES)


def test_build_analysis_steps_exact_order(tmp_path: Path) -> None:
    """The eleven returned steps appear in this exact, fixed order."""
    config = _config({"repository": {"workspace_root": str(tmp_path)}})
    steps = build_analysis_steps(config)
    assert [step.name for step in steps] == _EXPECTED_STEP_NAMES


def test_build_analysis_steps_exact_is_async(tmp_path: Path) -> None:
    """Only `clone_repositories` is asynchronous; every other step is synchronous."""
    config = _config({"repository": {"workspace_root": str(tmp_path)}})
    steps = build_analysis_steps(config)
    is_async_by_name = {step.name: step._is_async for step in steps}  # type: ignore[attr-defined]
    assert is_async_by_name == {
        "require_single_repository": False,
        "clone_repositories": True,
        "enumerate_files": False,
        "parse_files": False,
        "select_successful_parse_results": False,
        "extract_imports": False,
        "extract_ast": False,
        "extract_symbols": False,
        "extract_architecture": False,
        "extract_interfaces": False,
        "extract_foundation": False,
    }


def test_build_analysis_steps_extractor_output_keys(tmp_path: Path) -> None:
    """Each extractor step writes to its own already-established output key, unrenamed."""
    config = _config({"repository": {"workspace_root": str(tmp_path)}})
    steps = build_analysis_steps(config)
    output_key_by_name = {
        step.name: step._output_key  # type: ignore[attr-defined]
        for step in steps
        if isinstance(step, (CallableStep, MapStep))
    }
    assert output_key_by_name["extract_imports"] == "import_results"
    assert output_key_by_name["extract_ast"] == "ast_results"
    assert output_key_by_name["extract_symbols"] == "symbol_results"
    assert output_key_by_name["extract_architecture"] == "architecture_results"
    assert output_key_by_name["extract_interfaces"] == "interface_results"
    assert output_key_by_name["extract_foundation"] == "foundation_results"


def test_build_analysis_steps_returns_exactly_eleven(tmp_path: Path) -> None:
    """`build_analysis_steps` returns exactly eleven `Step`s -- no more, no fewer."""
    config = _config({"repository": {"workspace_root": str(tmp_path)}})
    steps = build_analysis_steps(config)
    assert len(steps) == 11
