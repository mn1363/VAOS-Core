"""Integration test: collect -> clone -> enumerate -> parse -> extract interfaces.

Extends the Reference Flow (see `tests/integration/test_reference_flow.py`, frozen as a
milestone and intentionally not imported from here) with one additional `MapStep`, proving
`StructuralInterfaceExtractor` -- the first concrete `InterfaceExtractor` implementation --
consumes real `ParseResult`s produced by the real flow and yields real `ExtractedInterface` data
across all three `InterfaceOrigin` values. This file defines its own local helpers rather than
importing `test_reference_flow.py`'s or `test_architecture_extraction.py`'s, matching this
repository's own convention of self-contained test modules.

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
from src.extractors.interfaces.base import InterfaceOrigin
from src.extractors.interfaces.structural import StructuralInterfaceExtractor
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


@pytest.mark.asyncio
async def test_interfaces_are_extracted_from_a_real_local_repository(tmp_path: Path) -> None:
    """The Reference Flow, extended with one `extract_interfaces` step, produces real
    `ExtractedInterface` data from a real, local git repository -- a Go `interface`, a Rust
    `trait`, a TypeScript `interface`, and a Python `ABC` class, covering all three
    `InterfaceOrigin` values end to end."""
    if shutil.which("git") is None:
        pytest.skip("git executable not found on PATH")

    source_repo = tmp_path / "source_repo"
    source_repo.mkdir()
    _run_git("init", cwd=source_repo)
    _run_git("checkout", "-b", "main", cwd=source_repo)
    _run_git("config", "user.email", "interfaces-extraction@example.com", cwd=source_repo)
    _run_git("config", "user.name", "Interfaces Extraction Test", cwd=source_repo)
    (source_repo / "greeter.go").write_text(
        "package main\n\ntype Greeter interface {\n\tGreet() string\n}\n", encoding="utf-8"
    )
    (source_repo / "writer.rs").write_text(
        "trait Writer {\n    fn write(&self, s: String);\n}\n", encoding="utf-8"
    )
    (source_repo / "reader.ts").write_text(
        "interface Reader {\n  read(): string;\n}\n", encoding="utf-8"
    )
    (source_repo / "shape.py").write_text(
        "from abc import ABC, abstractmethod\n\n"
        "class Shape(ABC):\n"
        "    @abstractmethod\n"
        "    def area(self):\n"
        "        pass\n",
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
    extract_interfaces_step: Step = MapStep(
        "extract_interfaces",
        StructuralInterfaceExtractor().extract,
        input_key="parse_results",
        output_key="interface_results",
    )

    result = await bootstrap(
        config,
        extra_steps=[clone_step, enumerate_step, parse_step, extract_interfaces_step],
    )

    assert result.step_names() == (
        "collect",
        "unpack_repositories",
        "persist_repositories",
        "clone_repositories",
        "enumerate_files",
        "parse_files",
        "extract_interfaces",
    )

    interface_results = result.context.require("interface_results")
    assert len(interface_results) == 4

    go_result = next(r for r in interface_results if r.relative_path == "greeter.go")
    assert go_result.succeeded is True
    assert len(go_result.interfaces) == 1
    assert go_result.interfaces[0].origin == InterfaceOrigin.LANGUAGE_INTERFACE
    assert go_result.interfaces[0].name == "Greeter"

    rust_result = next(r for r in interface_results if r.relative_path == "writer.rs")
    assert rust_result.succeeded is True
    assert len(rust_result.interfaces) == 1
    assert rust_result.interfaces[0].origin == InterfaceOrigin.TRAIT
    assert rust_result.interfaces[0].name == "Writer"

    ts_result = next(r for r in interface_results if r.relative_path == "reader.ts")
    assert ts_result.succeeded is True
    assert len(ts_result.interfaces) == 1
    assert ts_result.interfaces[0].origin == InterfaceOrigin.LANGUAGE_INTERFACE
    assert ts_result.interfaces[0].name == "Reader"

    python_result = next(r for r in interface_results if r.relative_path == "shape.py")
    assert python_result.succeeded is True
    assert len(python_result.interfaces) == 1
    assert python_result.interfaces[0].origin == InterfaceOrigin.ABSTRACT_CLASS
    assert python_result.interfaces[0].name == "Shape"
    assert python_result.interfaces[0].method_signatures == ("area",)
    assert python_result.interfaces[0].base_interfaces == ("ABC",)
