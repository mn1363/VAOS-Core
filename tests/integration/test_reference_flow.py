"""Integration tests for the Reference Flow: collect -> clone -> enumerate files -> parse.

Proves the Reference Flow milestone (see `docs/reference_flow_summary.md`) can be composed
entirely from already-frozen Ports -- `Collector`, `RepositoryClient`, `WorkspaceManager`,
`Parser`, `CallableStep`/`MapStep`, and `bootstrap.wiring.bootstrap`'s own `extra_steps` hook --
with no change to any file under `src/`. Every closure and helper below is test-local
composition, not production code; see `bootstrap.wiring`'s own module docstring for why this
flow does not live there.

Tests 1-4 isolate one part of the flow each, using hand-written fakes that subclass the real
frozen Ports -- never a mock -- matching this repository's own established testing convention
(see `tests/unit/pipeline/test_integration.py`). Test 5 is the one true end-to-end proof: a real,
local (no-network) git repository, the real `git` executable, and the real five parsers. Cloning
a local filesystem path is ordinary `git` behavior, so this requires no network access, matching
this repository's own established "tests must not require ... network access" convention -- it
does require the real `git` executable, and is skipped, not failed, when one is not on `PATH`.
"""

import os
import shutil
import subprocess
from collections.abc import Awaitable, Callable
from pathlib import Path

import pytest
from src.bootstrap.wiring import bootstrap, build_repository_client, build_workspace_manager
from src.collectors.base import CollectionResult
from src.collectors.filesystem import FilesystemCollector
from src.core.config import AppConfig
from src.domain.entities import SourceLanguage, SourceRepository
from src.parsers.base import Parser, ParseResult
from src.parsers.cpp.parser import CppParser
from src.parsers.go.parser import GoParser
from src.parsers.python.parser import PythonParser
from src.parsers.rust.parser import RustParser
from src.parsers.typescript.parser import TypeScriptParser
from src.pipeline.base import Step
from src.pipeline.context import PipelineContext
from src.pipeline.pipeline import Pipeline
from src.pipeline.steps import CallableStep, MapStep
from src.repository.base import RepositoryClient, WorkspaceManager
from src.repository.workspace import FilesystemWorkspaceManager

# --- test-local composition helpers -------------------------------------------------------
#
# Each of these binds an already-existing, already-frozen Port into the shape `CallableStep`/
# `MapStep` expects, exactly mirroring `bootstrap.wiring._persist_repository_func`'s own
# closure-factory pattern. None of them constructs a Port itself, and none introduces a new
# abstraction, DTO, or exception type -- see this module's own docstring.


def _config(raw: dict[str, object]) -> AppConfig:
    """Build an `AppConfig` directly from a raw mapping, bypassing `load_config`/YAML/env."""
    return AppConfig(raw=raw)


def _all_parsers() -> tuple[Parser, ...]:
    """The five existing concrete `Parser` implementations, freshly constructed."""
    return (PythonParser(), RustParser(), GoParser(), TypeScriptParser(), CppParser())


def _unpack_repositories(result: CollectionResult) -> tuple[SourceRepository, ...]:
    """Extract the collected repositories from a `CollectionResult`."""
    return result.repositories


def _clone_repository_func(
    repository_client: RepositoryClient, workspace_manager: WorkspaceManager
) -> Callable[[SourceRepository], Awaitable[Path]]:
    """Bind `repository_client`/`workspace_manager` into a single-item callable for `MapStep`.

    Args:
        repository_client: Already-constructed `RepositoryClient` each mapped repository is
            cloned through.
        workspace_manager: Already-constructed `WorkspaceManager` each mapped repository's
            destination directory is allocated from.

    Returns:
        An async callable suitable for `MapStep`: allocates a workspace for one repository,
        clones into it, and returns the resulting path.
    """

    async def _clone(repository: SourceRepository) -> Path:
        destination = workspace_manager.allocate(repository.id)
        await repository_client.clone(repository, destination)
        return destination

    return _clone


def _enumerate_files(workspaces: tuple[Path, ...]) -> tuple[tuple[str, str], ...]:
    """List every regular, text-decodable file under each workspace, `.git` excluded.

    Mirrors `collectors.local.LocalCollector._scan`'s own established convention: `os.walk`
    with `topdown=True`, pruning any directory whose name starts with `.` by clearing it from
    `dirnames` in place. Traversal is sorted at each level for deterministic output.

    Args:
        workspaces: Root directories to walk, typically one per cloned repository.

    Returns:
        `(relative_path, content)` pairs, in sorted directory-walk order. A file that cannot be
        decoded as UTF-8 text is silently skipped rather than raising -- the same "one item's
        failure is not exceptional for the whole scan" convention `Collector.collect`/
        `Parser.parse` already use for their own per-item failures.
    """
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
    """Bind `parsers` into a single-item callable for `MapStep`.

    Dispatch is exactly `Parser.supports()`, already part of the frozen `Parser` Port -- no
    registry or dispatcher of any kind is introduced.

    Args:
        parsers: Already-constructed `Parser` instances, tried in order.

    Returns:
        A sync callable suitable for `MapStep`: parses one `(relative_path, content)` pair with
        the first parser that supports it, or reports a failed `ParseResult` if none does.
    """

    def _parse_one(item: tuple[str, str]) -> ParseResult:
        relative_path, content = item
        parser = next((candidate for candidate in parsers if candidate.supports(relative_path)), None)
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


# --- fakes ----------------------------------------------------------------------------------


class _RecordingRepositoryClient(RepositoryClient):
    """A real `RepositoryClient` implementation that records every `clone` call instead of
    invoking `git` -- used to isolate step-to-step data flow from real clone I/O in test 1."""

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


# --- 1. collector output reaches clone -------------------------------------------------------


@pytest.mark.asyncio
async def test_collector_output_reaches_clone(tmp_path: Path) -> None:
    """The exact `SourceRepository` entities `Collector.collect` produces are the ones the
    clone step's closure receives -- proving `collect -> unpack_repositories ->
    clone_repositories` genuinely chains through `PipelineContext`, not just that each step
    works correctly in isolation."""
    source_dir = tmp_path / "project"
    source_dir.mkdir()
    collector = FilesystemCollector()
    recording_client = _RecordingRepositoryClient()
    workspace_manager = FilesystemWorkspaceManager(tmp_path / "workspaces")

    collect_step: Step = CallableStep(
        "collect",
        collector.collect,
        input_keys=("source",),
        output_key="collection_result",
        is_async=True,
    )
    unpack_step: Step = CallableStep(
        "unpack_repositories",
        _unpack_repositories,
        input_keys=("collection_result",),
        output_key="repositories",
    )
    clone_step: Step = MapStep(
        "clone_repositories",
        _clone_repository_func(recording_client, workspace_manager),
        input_key="repositories",
        output_key="workspaces",
        is_async=True,
    )

    pipeline = Pipeline("collect_and_clone", [collect_step, unpack_step, clone_step])
    result = await pipeline.run(PipelineContext(values={"source": str(source_dir)}))

    repositories = result.context.require("repositories")
    assert len(repositories) == 1
    assert len(recording_client.cloned) == 1
    cloned_repository, destination = recording_client.cloned[0]
    assert cloned_repository is repositories[0]
    assert destination == workspace_manager.allocate(repositories[0].id)


# --- 2. file enumeration -----------------------------------------------------------------


def test_enumerate_files_lists_expected_paths(tmp_path: Path) -> None:
    """Enumeration lists every regular file under a workspace, descends into nested
    directories, skips `.git` entirely, and reads real content back for each file."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "main.py").write_text("x = 1\n", encoding="utf-8")
    nested = workspace / "pkg"
    nested.mkdir()
    (nested / "helper.py").write_text("y = 2\n", encoding="utf-8")
    git_dir = workspace / ".git"
    git_dir.mkdir()
    (git_dir / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")

    files = _enumerate_files((workspace,))

    relative_paths = {relative_path for relative_path, _content in files}
    assert relative_paths == {"main.py", str(Path("pkg") / "helper.py")}
    contents = dict(files)
    assert contents["main.py"] == "x = 1\n"
    assert contents[str(Path("pkg") / "helper.py")] == "y = 2\n"


# --- 3. parser dispatch ------------------------------------------------------------------


def test_parser_dispatch_selects_correct_parser() -> None:
    """`Parser.supports()` alone -- no registry, no dispatcher -- correctly routes each
    extension to its own parser, and an unsupported extension produces a failed `ParseResult`
    instead of raising."""
    parse_one = _parse_files_func(_all_parsers())

    python_result = parse_one(("main.py", "x = 1\n"))
    assert python_result.language == SourceLanguage.PYTHON
    assert python_result.succeeded is True

    go_result = parse_one(("main.go", "package main\n"))
    assert go_result.language == SourceLanguage.GO
    assert go_result.succeeded is True

    rust_result = parse_one(("main.rs", "fn main() {}\n"))
    assert rust_result.language == SourceLanguage.RUST
    assert rust_result.succeeded is True

    unsupported_result = parse_one(("notes.xyz", "hello\n"))
    assert unsupported_result.succeeded is False
    assert unsupported_result.language == SourceLanguage.UNKNOWN
    assert unsupported_result.error_message is not None


# --- 4. parse results carry real structural content -----------------------------------------


def test_parse_results_are_real() -> None:
    """A parsed file's `ParseResult` carries genuine structural content -- a real function the
    real parser found -- not just `succeeded=True` with nothing else in it."""
    parse_one = _parse_files_func(_all_parsers())
    result = parse_one(("greeter.py", "def greet(name):\n    return f'hello {name}'\n"))
    assert result.succeeded is True
    assert any(function.name == "greet" for function in result.functions)


# --- 5. end-to-end against one real local repository -----------------------------------------


@pytest.mark.asyncio
async def test_reference_flow_executes_against_one_real_local_repository(
    tmp_path: Path,
) -> None:
    """The full Reference Flow, run through `bootstrap(..., extra_steps=...)` against one real,
    local git repository, produces real `ParseResult` data -- the milestone's own minimum bar.
    Cloning a local filesystem path is ordinary `git` behavior, so this needs no network access;
    it does need the real `git` executable, and is skipped (not failed) when one is unavailable.
    """
    if shutil.which("git") is None:
        pytest.skip("git executable not found on PATH")

    source_repo = tmp_path / "source_repo"
    source_repo.mkdir()
    _run_git("init", cwd=source_repo)
    _run_git("checkout", "-b", "main", cwd=source_repo)
    _run_git("config", "user.email", "reference-flow@example.com", cwd=source_repo)
    _run_git("config", "user.name", "Reference Flow Test", cwd=source_repo)
    (source_repo / "greeter.py").write_text(
        "def greet(name):\n    return f'hello {name}'\n", encoding="utf-8"
    )
    (source_repo / "main.go").write_text("package main\n\nfunc main() {}\n", encoding="utf-8")
    (source_repo / "notes.md").write_text("# notes\n", encoding="utf-8")
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

    result = await bootstrap(config, extra_steps=[clone_step, enumerate_step, parse_step])

    assert result.step_names() == (
        "collect",
        "unpack_repositories",
        "persist_repositories",
        "clone_repositories",
        "enumerate_files",
        "parse_files",
    )

    parse_results = result.context.require("parse_results")
    assert len(parse_results) == 3
    assert any(parsed.succeeded for parsed in parse_results)

    python_result = next(r for r in parse_results if r.relative_path == "greeter.py")
    assert python_result.succeeded is True
    assert python_result.language == SourceLanguage.PYTHON
    assert any(function.name == "greet" for function in python_result.functions)

    go_result = next(r for r in parse_results if r.relative_path == "main.go")
    assert go_result.succeeded is True
    assert go_result.language == SourceLanguage.GO

    notes_result = next(r for r in parse_results if r.relative_path == "notes.md")
    assert notes_result.succeeded is False
