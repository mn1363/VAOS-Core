"""Integration test: collect -> clone -> enumerate -> parse -> extract architecture.

Extends the Reference Flow (see `tests/integration/test_reference_flow.py`, frozen as a
milestone and intentionally not imported from here) with one additional `MapStep`, proving
`StructuralArchitectureExtractor` -- the first concrete `ArchitectureExtractor` implementation
-- consumes real `ParseResult`s produced by the real flow and yields real `PackageUnit` data.
This file defines its own local helpers rather than importing `test_reference_flow.py`'s,
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
from src.extractors.architecture.structural import StructuralArchitectureExtractor
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


@pytest.mark.asyncio
async def test_architecture_is_extracted_from_a_real_local_repository(tmp_path: Path) -> None:
    """The Reference Flow, extended with one `extract_architecture` step, produces real
    `PackageUnit` data from a real, local git repository -- a nested, non-root Python file; a
    nested Python package-root marker; and a root-level Go file carrying its own declared
    `package` module."""
    if shutil.which("git") is None:
        pytest.skip("git executable not found on PATH")

    source_repo = tmp_path / "source_repo"
    source_repo.mkdir()
    _run_git("init", cwd=source_repo)
    _run_git("checkout", "-b", "main", cwd=source_repo)
    _run_git("config", "user.email", "architecture-extraction@example.com", cwd=source_repo)
    _run_git("config", "user.name", "Architecture Extraction Test", cwd=source_repo)
    (source_repo / "pkg").mkdir()
    (source_repo / "pkg" / "widget.py").write_text(
        "class Widget:\n    pass\n", encoding="utf-8"
    )
    (source_repo / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (source_repo / "helpers.go").write_text(
        "package main\n\nfunc Helper() {}\n", encoding="utf-8"
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
    extract_architecture_step: Step = MapStep(
        "extract_architecture",
        StructuralArchitectureExtractor().extract,
        input_key="parse_results",
        output_key="architecture_results",
    )

    result = await bootstrap(
        config,
        extra_steps=[clone_step, enumerate_step, parse_step, extract_architecture_step],
    )

    assert result.step_names() == (
        "collect",
        "unpack_repositories",
        "persist_repositories",
        "clone_repositories",
        "enumerate_files",
        "parse_files",
        "extract_architecture",
    )

    architecture_results = result.context.require("architecture_results")
    assert len(architecture_results) == 3

    widget_result = next(r for r in architecture_results if r.relative_path == "pkg/widget.py")
    assert widget_result.succeeded is True
    widget_unit = widget_result.unit
    assert widget_unit is not None
    assert widget_unit.package_path == ("pkg",)
    assert widget_unit.is_package_root is False
    assert widget_unit.declared_modules == ()

    init_result = next(r for r in architecture_results if r.relative_path == "pkg/__init__.py")
    assert init_result.succeeded is True
    init_unit = init_result.unit
    assert init_unit is not None
    assert init_unit.package_path == ("pkg",)
    assert init_unit.is_package_root is True
    assert init_unit.declared_modules == ()

    helpers_result = next(r for r in architecture_results if r.relative_path == "helpers.go")
    assert helpers_result.succeeded is True
    helpers_unit = helpers_result.unit
    assert helpers_unit is not None
    assert helpers_unit.package_path == ()
    assert helpers_unit.is_package_root is False
    assert len(helpers_unit.declared_modules) == 1
    assert helpers_unit.declared_modules[0].name == "main"
