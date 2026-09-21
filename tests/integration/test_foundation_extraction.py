"""Integration test: collect -> clone -> enumerate -> parse -> extract foundation candidates.

Extends the Reference Flow (see `tests/integration/test_reference_flow.py`, frozen as a
milestone and intentionally not imported from here) with one additional `MapStep`, proving
`StructuralFoundationExtractor` -- the first concrete `FoundationExtractor` implementation --
consumes real `ParseResult`s produced by the real flow and yields real `FoundationCandidate`
data: a documented, exported class and function, private counterparts, preserved duplicate
candidates, and Go's known lack of parser docstring data. This file defines its own local
helpers rather than importing `test_reference_flow.py`'s or any other integration module's,
matching this repository's own convention of self-contained test modules.

Like the Reference Flow's own end-to-end test, this clones a real, local (no-network) git
repository, so it needs the real `git` executable and is skipped, not failed, if one is
unavailable.
"""

import os
import shutil
import subprocess
from collections.abc import Awaitable, Callable
from pathlib import Path

import pytest
from src.bootstrap.wiring import bootstrap, build_repository_client, build_workspace_manager
from src.core.config import AppConfig
from src.domain.entities import SourceLanguage, SourceRepository
from src.extractors.foundation.base import FoundationCandidate, FoundationCandidateKind
from src.extractors.foundation.structural import StructuralFoundationExtractor
from src.parsers.base import Parser, ParseResult
from src.parsers.cpp.parser import CppParser
from src.parsers.go.parser import GoParser
from src.parsers.python.parser import PythonParser
from src.parsers.rust.parser import RustParser
from src.parsers.typescript.parser import TypeScriptParser
from src.pipeline.base import Step
from src.pipeline.steps import CallableStep, MapStep
from src.repository.base import RepositoryClient, WorkspaceManager


def _config(raw: dict[str, object]) -> AppConfig:
    """Build an `AppConfig` directly from a raw mapping, bypassing `load_config`/YAML/env."""
    return AppConfig(raw=raw)


def _all_parsers() -> tuple[Parser, ...]:
    """The five existing concrete `Parser` implementations, freshly constructed."""
    return (PythonParser(), RustParser(), GoParser(), TypeScriptParser(), CppParser())


def _clone_repository_func(
    repository_client: RepositoryClient, workspace_manager: WorkspaceManager
) -> Callable[[SourceRepository], Awaitable[Path]]:
    """Bind `repository_client`/`workspace_manager` into a single-item callable for `MapStep`."""

    async def _clone(repository: SourceRepository) -> Path:
        destination = workspace_manager.allocate(repository.id)
        await repository_client.clone(repository, destination)
        return destination

    return _clone


def _enumerate_files(workspaces: tuple[Path, ...]) -> tuple[tuple[str, str], ...]:
    """List every regular, text-decodable file under each workspace, `.git` excluded."""
    files: list[tuple[str, str]] = []
    for workspace in workspaces:
        for dirpath, dirnames, filenames in os.walk(workspace, topdown=True):
            dirnames[:] = sorted(name for name in dirnames if not name.startswith("."))
            current = Path(dirpath)
            for filename in sorted(filenames):
                absolute = current / filename
                try:
                    content = absolute.read_text(encoding="utf-8")
                except (UnicodeDecodeError, OSError):
                    continue
                files.append((str(absolute.relative_to(workspace)), content))
    return tuple(files)


def _parse_files_func(
    parsers: tuple[Parser, ...],
) -> Callable[[tuple[str, str]], ParseResult]:
    """Bind `parsers` into a single-item callable for `MapStep`; dispatch via `.supports()`."""

    def _parse_one(item: tuple[str, str]) -> ParseResult:
        relative_path, content = item
        parser = next(
            (candidate for candidate in parsers if candidate.supports(relative_path)), None
        )
        if parser is None:
            return ParseResult.failed(
                relative_path=relative_path,
                language=SourceLanguage.UNKNOWN,
                error_message=f"no parser supports '{relative_path}'",
            )
        return parser.parse(relative_path=relative_path, content=content)

    return _parse_one


def _run_git(*args: str, cwd: Path) -> None:
    """Run a `git` subcommand in `cwd`, raising if it fails."""
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _candidate(
    name: str,
    kind: FoundationCandidateKind,
    relative_path: str,
    line_number: int,
    *,
    public: bool,
    documented: bool,
) -> FoundationCandidate:
    """Build the exact `FoundationCandidate` the locked mapping is expected to produce."""
    return FoundationCandidate(
        name=name,
        kind=kind,
        relative_path=relative_path,
        is_public=public,
        has_docstring=documented,
        signals=(),
        line_number=line_number,
    )


@pytest.mark.asyncio
async def test_foundation_candidates_are_extracted_from_a_real_local_repository(
    tmp_path: Path,
) -> None:
    """The Reference Flow, extended with one `extract_foundation` step, produces real
    `FoundationCandidate` data from a real, local git repository -- a Python module with an
    exported/documented class and function plus private counterparts and a method that must
    not be emitted, a Python module with duplicate declarations that must all be preserved, and
    a Go file whose `//` doc comments the Go parser never surfaces."""
    if shutil.which("git") is None:
        pytest.skip("git executable not found on PATH")

    source_repo = tmp_path / "source_repo"
    source_repo.mkdir()
    _run_git("init", cwd=source_repo)
    _run_git("checkout", "-b", "main", cwd=source_repo)
    _run_git("config", "user.email", "foundation-extraction@example.com", cwd=source_repo)
    _run_git("config", "user.name", "Foundation Extraction Test", cwd=source_repo)
    (source_repo / "shapes.py").write_text(
        '"""Shapes."""\n'
        '__all__ = ["Shape", "build_shape"]\n'
        "\n"
        "\n"
        "class Shape:\n"
        '    """A shape."""\n'
        "\n"
        "    def area(self):\n"
        "        return 0\n"
        "\n"
        "\n"
        "class _Scratch:\n"
        "    pass\n"
        "\n"
        "\n"
        "def build_shape():\n"
        '    """Build a shape."""\n'
        "    return Shape()\n"
        "\n"
        "\n"
        "def _helper():\n"
        "    return 1\n",
        encoding="utf-8",
    )
    (source_repo / "duplicates.py").write_text(
        'def render():\n    pass\n\n\ndef render():\n    """Second render."""\n',
        encoding="utf-8",
    )
    (source_repo / "greeter.go").write_text(
        "package main\n"
        "\n"
        "// Greeter is exported and documented.\n"
        "type Greeter struct{}\n"
        "\n"
        "// Greet is exported and documented.\n"
        "func Greet() {}\n",
        encoding="utf-8",
    )
    _run_git("add", "-A", cwd=source_repo)
    _run_git("commit", "-m", "initial commit", cwd=source_repo)

    config = _config(
        {
            "collectors": {"backend": "filesystem", "source": str(source_repo)},
            "storage": {
                "backend": "filesystem",
                "filesystem": {"root": str(tmp_path / "storage")},
            },
            "repository": {"workspace_root": str(tmp_path / "workspaces")},
        }
    )
    repository_client = build_repository_client(config)
    workspace_manager = build_workspace_manager(config)
    parsers = _all_parsers()

    clone_step: Step = MapStep(
        "clone_repositories",
        _clone_repository_func(repository_client, workspace_manager),
        input_key="repositories",
        output_key="workspaces",
        is_async=True,
    )
    enumerate_step: Step = CallableStep(
        "enumerate_files",
        _enumerate_files,
        input_keys=("workspaces",),
        output_key="files_to_parse",
    )
    parse_step: Step = MapStep(
        "parse_files",
        _parse_files_func(parsers),
        input_key="files_to_parse",
        output_key="parse_results",
    )
    extract_foundation_step: Step = MapStep(
        "extract_foundation",
        StructuralFoundationExtractor().extract,
        input_key="parse_results",
        output_key="foundation_results",
    )

    result = await bootstrap(
        config,
        extra_steps=[clone_step, enumerate_step, parse_step, extract_foundation_step],
    )

    assert result.step_names() == (
        "collect",
        "unpack_repositories",
        "persist_repositories",
        "clone_repositories",
        "enumerate_files",
        "parse_files",
        "extract_foundation",
    )

    foundation_results = result.context.require("foundation_results")
    assert len(foundation_results) == 3
    assert all(r.succeeded is True for r in foundation_results)

    klass = FoundationCandidateKind.CLASS
    function = FoundationCandidateKind.FUNCTION

    shapes_result = next(r for r in foundation_results if r.relative_path == "shapes.py")
    assert shapes_result.candidates == (
        _candidate("Shape", klass, "shapes.py", 5, public=True, documented=True),
        _candidate("_Scratch", klass, "shapes.py", 12, public=False, documented=False),
        _candidate("build_shape", function, "shapes.py", 16, public=True, documented=True),
        _candidate("_helper", function, "shapes.py", 21, public=False, documented=False),
    )
    assert "area" not in [c.name for c in shapes_result.candidates]

    duplicates_result = next(r for r in foundation_results if r.relative_path == "duplicates.py")
    assert duplicates_result.candidates == (
        _candidate("render", function, "duplicates.py", 1, public=False, documented=False),
        _candidate("render", function, "duplicates.py", 5, public=False, documented=True),
    )

    go_result = next(r for r in foundation_results if r.relative_path == "greeter.go")
    assert go_result.candidates == (
        _candidate("Greeter", klass, "greeter.go", 4, public=True, documented=False),
        _candidate("Greet", function, "greeter.go", 7, public=True, documented=False),
    )
