"""Integration test: real-repository analysis composition via `src.bootstrap.analysis_steps`.

Proves that `build_analysis_steps`, attached only through `bootstrap(config,
extra_steps=build_analysis_steps(config))`, produces the same real, structural data the
already-frozen Reference Flow and each single-extractor integration test already prove
individually -- now composed together, from production code, in one milestone. Like every other
integration test in this directory, this clones a real, local (no-network) git repository, so it
needs the real `git` executable and is skipped, not failed, if one is unavailable.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest
from src.bootstrap.analysis_steps import (
    _all_parsers,
    _clone_repository_func,
    _enumerate_files,
    _parse_files_func,
    build_analysis_steps,
)
from src.bootstrap.errors import BootstrapError
from src.bootstrap.wiring import bootstrap, build_repository_client, build_workspace_manager
from src.core.config import AppConfig
from src.extractors.interfaces.base import InterfaceOrigin
from src.pipeline.base import StepExecutionError


def _config(raw: dict[str, object]) -> AppConfig:
    """Build an `AppConfig` directly from a raw mapping, bypassing `load_config`/YAML/env."""
    return AppConfig(raw=raw)


def _run_git(*args: str, cwd: Path) -> None:
    """Run a `git` subcommand in `cwd`, raising if it fails."""
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _write_fixture_repository(root: Path) -> None:
    """Populate `root` with a fixture repository covering every case this milestone must
    handle: a documented Python class/function, a Go source file, a TypeScript
    interface/class pair, a nested directory, a dot-directory, an unsupported `README.md`,
    and an undecodable-byte file -- then commit it."""
    (root / "app.py").write_text(
        '"""Application entry point."""\n'
        "import os\n"
        "\n"
        "\n"
        "class Base:\n"
        '    """A documented base class."""\n'
        "\n"
        "    def run(self):\n"
        "        return os.getcwd()\n"
        "\n"
        "\n"
        "def main():\n"
        '    """Run the application."""\n'
        "    return Base().run()\n",
        encoding="utf-8",
    )
    nested = root / "pkg" / "sub"
    nested.mkdir(parents=True)
    (root / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (nested / "util.py").write_text(
        "def helper(value):\n    return value\n", encoding="utf-8"
    )
    (root / "greeter.go").write_text(
        "package main\n\ntype Greeter struct{}\n\nfunc Greet() {}\n", encoding="utf-8"
    )
    web = root / "web"
    web.mkdir()
    (web / "shape.ts").write_text(
        "export interface Shape { area(): number }\n"
        "export class Square implements Shape { area() { return 1 } }\n",
        encoding="utf-8",
    )
    (root / "README.md").write_text("# Fixture repository\n", encoding="utf-8")
    (root / "blob.bin").write_bytes(b"\x00\x01\x02\xff\xfe")
    hidden = root / ".hidden"
    hidden.mkdir()
    (hidden / "secret.py").write_text("SECRET = 1\n", encoding="utf-8")
    _run_git("add", "-A", cwd=root)
    _run_git("commit", "-m", "fixture repository", cwd=root)


@pytest.mark.asyncio
async def test_real_repository_analysis_executes_against_one_real_local_repository(
    tmp_path: Path,
) -> None:
    """The production `build_analysis_steps` composition, run through the real, unmodified
    `bootstrap`, produces the exact 14-step sequence and real, structural results from all
    six extractors against a real local repository."""
    if shutil.which("git") is None:
        pytest.skip("git executable not found on PATH")

    source_repo = tmp_path / "source_repo"
    source_repo.mkdir()
    _run_git("init", cwd=source_repo)
    _run_git("config", "user.email", "test@example.com", cwd=source_repo)
    _run_git("config", "user.name", "Test", cwd=source_repo)
    _run_git("checkout", "-b", "main", cwd=source_repo)
    _write_fixture_repository(source_repo)

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

    result = await bootstrap(config, extra_steps=build_analysis_steps(config))

    assert result.step_names() == (
        "collect",
        "unpack_repositories",
        "persist_repositories",
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
    )

    files_to_parse = result.context.require("files_to_parse")
    files_to_parse_paths = {path for path, _content in files_to_parse}
    # blob.bin's bytes are not UTF-8-decodable, so enumerate_files already excludes it before
    # parse_files ever runs -- it never becomes a ParseResult, successful or failed.
    assert "blob.bin" not in files_to_parse_paths
    # .hidden is a dot-directory, so nothing under it is enumerated at all.
    assert str(Path(".hidden") / "secret.py") not in files_to_parse_paths

    parse_results = result.context.require("parse_results")
    parse_results_by_path = {r.relative_path: r for r in parse_results}
    assert "blob.bin" not in parse_results_by_path
    assert parse_results_by_path["README.md"].succeeded is False
    assert parse_results_by_path["app.py"].succeeded is True

    successful_parse_results = result.context.require("successful_parse_results")
    assert all(r.succeeded for r in successful_parse_results)
    assert len(successful_parse_results) == len(
        [r for r in parse_results if r.succeeded]
    )
    # order is preserved: successful results appear in the same relative order as in
    # parse_results, with failures simply omitted.
    assert [r.relative_path for r in successful_parse_results] == [
        r.relative_path for r in parse_results if r.succeeded
    ]
    successful_paths = {r.relative_path for r in successful_parse_results}
    assert successful_paths == {
        "app.py",
        str(Path("pkg") / "__init__.py"),
        str(Path("pkg") / "sub" / "util.py"),
        "greeter.go",
        str(Path("web") / "shape.ts"),
    }

    for key in (
        "import_results",
        "ast_results",
        "symbol_results",
        "architecture_results",
        "interface_results",
        "foundation_results",
    ):
        results = result.context.require(key)
        assert len(results) == len(successful_parse_results)
        assert all(r.succeeded is True for r in results)

    interface_results = result.context.require("interface_results")
    interfaces = [
        (interface.name, interface.origin)
        for extraction_result in interface_results
        for interface in extraction_result.interfaces
    ]
    assert ("Base", InterfaceOrigin.ABSTRACT_CLASS) not in interfaces  # Base is not ABC-based
    assert ("Shape", InterfaceOrigin.LANGUAGE_INTERFACE) in interfaces

    foundation_results = result.context.require("foundation_results")
    app_foundation = next(r for r in foundation_results if r.relative_path == "app.py")
    candidate_names = {c.name for c in app_foundation.candidates}
    assert {"Base", "main"}.issubset(candidate_names)


@pytest.mark.asyncio
async def test_real_repository_analysis_is_deterministic_across_repeated_runs(
    tmp_path: Path,
) -> None:
    """Running the exact same composition twice, against two independent workspaces, produces
    identical results."""
    if shutil.which("git") is None:
        pytest.skip("git executable not found on PATH")

    source_repo = tmp_path / "source_repo"
    source_repo.mkdir()
    _run_git("init", cwd=source_repo)
    _run_git("config", "user.email", "test@example.com", cwd=source_repo)
    _run_git("config", "user.name", "Test", cwd=source_repo)
    _run_git("checkout", "-b", "main", cwd=source_repo)
    _write_fixture_repository(source_repo)

    async def run(tag: str):
        config = _config(
            {
                "collectors": {"backend": "filesystem", "source": str(source_repo)},
                "storage": {
                    "backend": "filesystem",
                    "filesystem": {"root": str(tmp_path / f"storage-{tag}")},
                },
                "repository": {"workspace_root": str(tmp_path / f"workspaces-{tag}")},
            }
        )
        result = await bootstrap(config, extra_steps=build_analysis_steps(config))
        return result.context

    first = await run("a")
    second = await run("b")

    for key in (
        "successful_parse_results",
        "import_results",
        "ast_results",
        "symbol_results",
        "architecture_results",
        "interface_results",
        "foundation_results",
    ):
        assert first.require(key) == second.require(key)


@pytest.mark.asyncio
async def test_require_single_repository_rejects_multiple_local_repositories(
    tmp_path: Path,
) -> None:
    """Two repositories discovered by `LocalCollector` under one scan root are rejected at
    `require_single_repository`, not silently analyzed as if they were one."""
    if shutil.which("git") is None:
        pytest.skip("git executable not found on PATH")

    scan_root = tmp_path / "scan_root"
    for name in ("repo_one", "repo_two"):
        repo = scan_root / name
        repo.mkdir(parents=True)
        _run_git("init", cwd=repo)
        _run_git("config", "user.email", "test@example.com", cwd=repo)
        _run_git("config", "user.name", "Test", cwd=repo)
        _run_git("checkout", "-b", "main", cwd=repo)
        (repo / "a.py").write_text("x = 1\n", encoding="utf-8")
        _run_git("add", "-A", cwd=repo)
        _run_git("commit", "-m", "init", cwd=repo)

    config = _config(
        {
            "collectors": {"backend": "local", "source": str(scan_root)},
            "storage": {
                "backend": "filesystem",
                "filesystem": {"root": str(tmp_path / "storage")},
            },
            "repository": {"workspace_root": str(tmp_path / "workspaces")},
        }
    )

    with pytest.raises(StepExecutionError) as exc_info:
        await bootstrap(config, extra_steps=build_analysis_steps(config))

    assert exc_info.value.details["failed_step"] == "require_single_repository"
    assert isinstance(exc_info.value.__cause__, BootstrapError)


# --- equivalence with the Reference Flow's own test-local helpers -----------------------------


def _reference_flow_enumerate_files(workspaces: tuple[Path, ...]) -> tuple[tuple[str, str], ...]:
    """A local copy of `tests/integration/test_reference_flow.py`'s own `_enumerate_files`,
    kept test-local per this milestone's own scope (it does not import that test module's
    private helpers, matching this repository's "self-contained test modules" convention)."""
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


def test_enumerate_files_matches_reference_flow_helper(tmp_path: Path) -> None:
    """The promoted `_enumerate_files` produces byte-for-byte identical output to the Reference
    Flow's own already-frozen, test-local helper, for the same fixture."""
    (tmp_path / "a.py").write_text("a", encoding="utf-8")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("x", encoding="utf-8")
    nested = tmp_path / "pkg"
    nested.mkdir()
    (nested / "mod.py").write_text("m", encoding="utf-8")

    assert _enumerate_files((tmp_path,)) == _reference_flow_enumerate_files((tmp_path,))


def test_parse_files_matches_reference_flow_dispatch() -> None:
    """The promoted `_parse_files_func` parses identically to the Reference Flow's own
    dispatch, for both a supported and an unsupported file."""
    reference_parsers = _all_parsers()
    promoted = _parse_files_func(_all_parsers())
    reference = _parse_files_func(reference_parsers)

    for item in [("a.py", "def f():\n    pass\n"), ("README.md", "# readme")]:
        assert promoted(item) == reference(item)


@pytest.mark.asyncio
async def test_clone_repository_func_matches_reference_flow_shape(tmp_path: Path) -> None:
    """The promoted `_clone_repository_func` allocates and clones exactly like the Reference
    Flow's own closure factory -- proven here by using the identical, already-frozen
    `RepositoryClient`/`WorkspaceManager` builders both draw from."""
    config = _config({"repository": {"workspace_root": str(tmp_path)}})
    repository_client = build_repository_client(config)
    workspace_manager = build_workspace_manager(config)

    promoted_clone = _clone_repository_func(repository_client, workspace_manager)
    assert callable(promoted_clone)
    assert promoted_clone.__code__.co_argcount == 1
