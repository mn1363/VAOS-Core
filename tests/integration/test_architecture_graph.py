"""Integration test: `StructuralArchitectureGraphBuilder` over real `architecture_results`.

Proves that the concrete builder consumes the real, structural `architecture_results` produced by
the existing real-repository analysis composition (`bootstrap(config,
extra_steps=build_analysis_steps(config))`, unmodified) and assembles them into a valid,
deterministic `ArchitectureGraph`. The builder is invoked directly on the context's own
`architecture_results` after the composition's existing 14 steps have run -- no step is added to
the composition, and nothing in `src/bootstrap` is touched.

Like every other integration test in this directory, this clones a real, local (no-network) git
repository, so it needs the real `git` executable and is skipped, not failed, if one is
unavailable.

**Cross-platform handling.** The builder trusts each `PackageUnit` exactly as supplied and does no
path normalization; the extractor derives `package_path` by splitting `relative_path` on `/`
only. On a POSIX checkout the real results therefore describe the full nested package tree, and
`test_real_results_produce_the_exact_posix_graph` pins it exactly. On Windows, `relative_path` is
platform-native (backslash-separated), so nested files land in the root package -- existing,
frozen extractor behavior this milestone deliberately does not change. Every other assertion
here is therefore derived from the real `unit.relative_path` / `unit.package_path` values, and
holds unchanged on both platforms.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest
from src.bootstrap.analysis_steps import build_analysis_steps
from src.bootstrap.wiring import bootstrap
from src.core.config import AppConfig
from src.extractors.architecture.base import ArchitectureExtractionResult, PackageUnit
from src.graph.architecture.base import (
    ArchitectureGraph,
    PackageContainmentEdge,
    PackageNode,
    ancestor_package_paths,
)
from src.graph.architecture.structural import StructuralArchitectureGraphBuilder


def _config(raw: dict[str, object]) -> AppConfig:
    """Build an `AppConfig` directly from a raw mapping, bypassing `load_config`/YAML/env."""
    return AppConfig(raw=raw)


def _run_git(*args: str, cwd: Path) -> None:
    """Run a `git` subcommand in `cwd`, raising if it fails."""
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _write_fixture_repository(root: Path) -> None:
    """Populate `root` with a fixture repository, then commit it.

    Covers: root-level source files and a root-level package-root marker; package-root markers
    in Python (`__init__.py`), TypeScript (`index.ts`), and Rust (`mod.rs`); a three-deep nested
    package (`pkg/sub/deep`); a package (`lib`) with no direct file of its own, only a nested
    subpackage (`lib/inner`); a directory holding only an unsupported file (`docs/notes`), which
    never becomes a package; and a dot-directory the enumerator prunes.
    """
    (root / "__init__.py").write_text("", encoding="utf-8")
    (root / "app.py").write_text("def main():\n    return 1\n", encoding="utf-8")
    (root / "greeter.go").write_text("package main\n\nfunc Greet() {}\n", encoding="utf-8")

    deep = root / "pkg" / "sub" / "deep"
    deep.mkdir(parents=True)
    (root / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (root / "pkg" / "sub" / "__init__.py").write_text("", encoding="utf-8")
    (deep / "util.py").write_text("def helper(value):\n    return value\n", encoding="utf-8")

    web = root / "web"
    web.mkdir()
    (web / "index.ts").write_text(
        "export interface Shape { area(): number }\n", encoding="utf-8"
    )

    core = root / "core"
    core.mkdir()
    (core / "mod.rs").write_text("pub fn helper() {}\n", encoding="utf-8")

    inner = root / "lib" / "inner"
    inner.mkdir(parents=True)
    (inner / "only.py").write_text("VALUE = 1\n", encoding="utf-8")

    notes = root / "docs" / "notes"
    notes.mkdir(parents=True)
    (notes / "README.md").write_text("# Notes\n", encoding="utf-8")

    hidden = root / ".hidden"
    hidden.mkdir()
    (hidden / "secret.py").write_text("SECRET = 1\n", encoding="utf-8")

    _run_git("add", "-A", cwd=root)
    _run_git("commit", "-m", "fixture repository", cwd=root)


def _make_source_repository(tmp_path: Path) -> Path:
    """Create, populate, and commit the fixture repository under `tmp_path`."""
    source_repo = tmp_path / "source_repo"
    source_repo.mkdir()
    _run_git("init", cwd=source_repo)
    _run_git("config", "user.email", "test@example.com", cwd=source_repo)
    _run_git("config", "user.name", "Test", cwd=source_repo)
    _run_git("checkout", "-b", "main", cwd=source_repo)
    _write_fixture_repository(source_repo)
    return source_repo


async def _real_architecture_results(
    source_repo: Path, tmp_path: Path, tag: str
) -> tuple[ArchitectureExtractionResult, ...]:
    """Run the existing 14-step composition and return its real `architecture_results`.

    Each `tag` gets its own storage and workspace roots, so repeated runs are fully independent.
    """
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
    assert len(result.step_names()) == 14
    architecture_results: tuple[ArchitectureExtractionResult, ...] = result.context.require(
        "architecture_results"
    )
    return architecture_results


def _units(results: tuple[ArchitectureExtractionResult, ...]) -> list[PackageUnit]:
    """Return every real result's `PackageUnit`, asserting each result really succeeded."""
    units: list[PackageUnit] = []
    for extraction_result in results:
        assert extraction_result.succeeded is True
        assert extraction_result.unit is not None
        units.append(extraction_result.unit)
    return units


def _skip_without_git() -> None:
    """Skip the calling test if the real `git` executable is unavailable."""
    if shutil.which("git") is None:
        pytest.skip("git executable not found on PATH")


@pytest.mark.asyncio
async def test_builder_assembles_real_architecture_results_into_a_valid_graph(
    tmp_path: Path,
) -> None:
    """Real `architecture_results` build a valid, non-empty, tree-shaped `ArchitectureGraph`.

    Every expectation is derived from the real units' own `package_path`/`relative_path`/
    `is_package_root`, so this holds on POSIX and Windows alike.
    """
    _skip_without_git()
    source_repo = _make_source_repository(tmp_path)
    results = await _real_architecture_results(source_repo, tmp_path, "a")
    units = _units(results)
    assert units

    graph = StructuralArchitectureGraphBuilder().build(results)

    # Valid and non-empty. `ArchitectureGraph.__post_init__` already ran on construction.
    assert isinstance(graph, ArchitectureGraph)
    assert graph.node_count > 0
    node_paths = {node.package_path for node in graph.nodes}
    assert () in node_paths  # a non-empty graph is always connected back to the root

    # A containment tree: every non-root node has exactly one incoming edge.
    assert graph.edge_count == graph.node_count - 1
    assert sorted(edge.child_path for edge in graph.edges) == sorted(
        path for path in node_paths if path
    )

    # Every file the real extraction covered appears under the node for its `unit.package_path`
    # -- and nowhere else, since this input has no conflicting units.
    for unit in units:
        node = graph.get_node("/".join(unit.package_path))
        assert node.package_path == unit.package_path
        assert unit.relative_path in node.file_paths
    all_member_files = [path for node in graph.nodes for path in node.file_paths]
    assert sorted(all_member_files) == sorted({unit.relative_path for unit in units})

    # Files the parsers rejected never reach `architecture_results`, so never reach the graph.
    assert all(not path.endswith("README.md") for path in all_member_files)
    assert all(".hidden" not in path for path in all_member_files)

    # Ancestor nodes exist for every real (possibly nested) package path.
    for unit in units:
        for ancestor in ancestor_package_paths(unit.package_path):
            assert ancestor in node_paths


@pytest.mark.asyncio
async def test_package_root_flags_propagate_from_real_extractor_results(tmp_path: Path) -> None:
    """`has_package_root_file` matches the real `is_package_root` values, package by package."""
    _skip_without_git()
    source_repo = _make_source_repository(tmp_path)
    results = await _real_architecture_results(source_repo, tmp_path, "a")
    units = _units(results)

    graph = StructuralArchitectureGraphBuilder().build(results)

    # The fixture's root-level `__init__.py` is a package-root marker on every platform, so this
    # is never vacuous.
    assert any(unit.is_package_root for unit in units)
    for node in graph.nodes:
        expected = any(
            unit.is_package_root for unit in units if unit.package_path == node.package_path
        )
        assert node.has_package_root_file is expected
    root_node = graph.get_node("")
    assert root_node.has_package_root_file is True
    assert "__init__.py" in root_node.file_paths
    # The repository root is never linked to itself.
    assert all(edge.child_path != () for edge in graph.edges)


@pytest.mark.asyncio
async def test_graph_build_is_deterministic_across_repeated_builds_and_runs(
    tmp_path: Path,
) -> None:
    """Building twice, and building from two independent analysis runs, gives equal graphs."""
    _skip_without_git()
    source_repo = _make_source_repository(tmp_path)
    first_results = await _real_architecture_results(source_repo, tmp_path, "a")
    second_results = await _real_architecture_results(source_repo, tmp_path, "b")

    builder = StructuralArchitectureGraphBuilder()
    first = builder.build(first_results)
    assert builder.build(first_results) == first
    assert builder.build(second_results) == first
    assert StructuralArchitectureGraphBuilder().build(tuple(reversed(first_results))) == first


@pytest.mark.skipif(os.sep != "/", reason="exact path assertions assume POSIX separators")
@pytest.mark.asyncio
async def test_real_results_produce_the_exact_posix_graph(tmp_path: Path) -> None:
    """On POSIX, the fixture's real results build exactly this nested package tree."""
    _skip_without_git()
    source_repo = _make_source_repository(tmp_path)
    results = await _real_architecture_results(source_repo, tmp_path, "a")

    graph = StructuralArchitectureGraphBuilder().build(results)

    assert graph == ArchitectureGraph(
        nodes=(
            PackageNode(
                package_path=(),
                file_paths=("__init__.py", "app.py", "greeter.go"),
                has_package_root_file=True,
            ),
            PackageNode(
                package_path=("core",), file_paths=("core/mod.rs",), has_package_root_file=True
            ),
            PackageNode(package_path=("lib",)),
            PackageNode(package_path=("lib", "inner"), file_paths=("lib/inner/only.py",)),
            PackageNode(
                package_path=("pkg",), file_paths=("pkg/__init__.py",), has_package_root_file=True
            ),
            PackageNode(
                package_path=("pkg", "sub"),
                file_paths=("pkg/sub/__init__.py",),
                has_package_root_file=True,
            ),
            PackageNode(
                package_path=("pkg", "sub", "deep"), file_paths=("pkg/sub/deep/util.py",)
            ),
            PackageNode(
                package_path=("web",), file_paths=("web/index.ts",), has_package_root_file=True
            ),
        ),
        edges=(
            PackageContainmentEdge(parent_path=(), child_path=("core",)),
            PackageContainmentEdge(parent_path=(), child_path=("lib",)),
            PackageContainmentEdge(parent_path=(), child_path=("pkg",)),
            PackageContainmentEdge(parent_path=(), child_path=("web",)),
            PackageContainmentEdge(parent_path=("lib",), child_path=("lib", "inner")),
            PackageContainmentEdge(parent_path=("pkg",), child_path=("pkg", "sub")),
            PackageContainmentEdge(parent_path=("pkg", "sub"), child_path=("pkg", "sub", "deep")),
        ),
    )
    # `lib` is an ancestor-only node: no file of its own, no package-root flag.
    assert graph.get_node("lib") == PackageNode(package_path=("lib",))
    # `docs/notes` held only an unsupported file, so it is never a package.
    assert all(node.package_path[:1] != ("docs",) for node in graph.nodes)
