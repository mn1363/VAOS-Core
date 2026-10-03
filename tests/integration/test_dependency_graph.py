"""Integration test: `StructuralDependencyGraphBuilder` over real `import_results`.

Proves that the concrete builder consumes the real, structural `import_results` produced by the
real-repository analysis composition (`bootstrap(config, extra_steps=build_analysis_steps(config))`
-- the real file enumeration, the real five parsers, and the real `StructuralImportExtractor`) over
a small, real, local (no-network) git repository, and assembles them into a valid, deterministic
`DependencyGraph`. The builder is invoked directly on the context's own `import_results`; the
composition itself is not modified and still has exactly its fifteen existing steps -- there is no
dependency-graph step.

Like every other integration test in this directory, this clones a real, local git repository, so
it needs the real `git` executable and is skipped, not failed, if one is unavailable.

**Cross-platform handling.** `_enumerate_files` yields platform-native relative paths (backslash-
separated on Windows) and this milestone deliberately does not change that. The builder trusts each
input `relative_path` verbatim as its `INTERNAL_FILE` identifier, but matches on a normalized
(`/`-separated) key, so internal imports resolve identically on both platforms. Every expected
`INTERNAL_FILE` identifier below is therefore spelled through `_native`, while `external:` and
`unresolved:` identifiers -- built from raw targets and normalized keys -- are platform-independent.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from src.bootstrap.analysis_steps import build_analysis_steps
from src.bootstrap.wiring import bootstrap
from src.core.config import AppConfig
from src.extractors.imports.base import ImportExtractionResult
from src.graph.dependency.base import DependencyGraph, DependencyNodeKind
from src.graph.dependency.structural import StructuralDependencyGraphBuilder
from src.pipeline.base import PipelineResult

INTERNAL_FILE = DependencyNodeKind.INTERNAL_FILE
EXTERNAL_MODULE = DependencyNodeKind.EXTERNAL_MODULE
UNRESOLVED_INTERNAL = DependencyNodeKind.UNRESOLVED_INTERNAL


def _native(posix_path: str) -> str:
    """Spell a `/`-separated repository path the way `_enumerate_files` does on this platform."""
    return str(Path(posix_path))


def _config(raw: dict[str, object]) -> AppConfig:
    """Build an `AppConfig` directly from a raw mapping, bypassing `load_config`/YAML/env."""
    return AppConfig(raw=raw)


def _run_git(*args: str, cwd: Path) -> None:
    """Run a `git` subcommand in `cwd`, raising if it fails."""
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _write_fixture_repository(root: Path) -> None:
    """Populate `root` with a small multi-language repository, then commit it.

    Covers: a Python absolute first-party import (`main.py` -> `pkg/util.py`, which the upstream
    extractor flags as *not* internal); Python relative imports (`from . import consts`,
    `from .consts import X`) and one that escapes to a missing target; a TypeScript relative
    import that resolves and one that does not; a quoted C++ include that resolves, one that does
    not, and an angle include; Go and Rust files; external imports in several languages; files
    with zero imports; a file no parser supports; and a dot-directory the enumerator prunes.
    """
    (root / "main.py").write_text(
        "from pkg.util import helper\nimport os\nimport requests\n", encoding="utf-8"
    )

    pkg = root / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "util.py").write_text(
        "from . import consts\nfrom .consts import X\nfrom ..missing import q\n",
        encoding="utf-8",
    )
    (pkg / "consts.py").write_text("X = 1\n", encoding="utf-8")

    web = root / "web"
    web.mkdir()
    (web / "app.ts").write_text(
        'import { a } from "./util";\nimport React from "react";\nimport { b } from "./gone";\n',
        encoding="utf-8",
    )
    (web / "util.ts").write_text("export const a = 1;\n", encoding="utf-8")

    native = root / "native"
    native.mkdir()
    (native / "conn.cpp").write_text(
        '#include "conn.h"\n#include <vector>\n#include "missing.h"\n\nint main() { return 0; }\n',
        encoding="utf-8",
    )
    (native / "conn.h").write_text("#pragma once\n", encoding="utf-8")

    svc = root / "svc"
    svc.mkdir()
    (svc / "main.go").write_text(
        'package main\n\nimport "fmt"\nimport "./util"\n\nfunc main() {}\n', encoding="utf-8"
    )

    lib = root / "lib"
    lib.mkdir()
    (lib / "lib.rs").write_text(
        "use crate::a::B;\nuse std::fmt;\n\npub fn f() {}\n", encoding="utf-8"
    )

    docs = root / "docs"
    docs.mkdir()
    (docs / "README.md").write_text("# Notes\n", encoding="utf-8")

    hidden = root / ".hidden"
    hidden.mkdir()
    (hidden / "secret.py").write_text("import os\n", encoding="utf-8")

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


_EXPECTED_STEP_NAMES = (
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
    "build_architecture_graph",
)


async def _run_analysis(source_repo: Path, tmp_path: Path, tag: str) -> PipelineResult:
    """Run the real, unmodified 15-step composition and return its `PipelineResult`.

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
    assert result.step_names() == _EXPECTED_STEP_NAMES
    return result


async def _real_import_results(
    source_repo: Path, tmp_path: Path, tag: str
) -> tuple[ImportExtractionResult, ...]:
    """Run the real composition and return its real `import_results`."""
    result = await _run_analysis(source_repo, tmp_path, tag)
    import_results: tuple[ImportExtractionResult, ...] = result.context.require("import_results")
    return import_results


def _skip_without_git() -> None:
    """Skip the calling test if the real `git` executable is unavailable."""
    if shutil.which("git") is None:
        pytest.skip("git executable not found on PATH")


def _edge_triples(graph: DependencyGraph) -> set[tuple[str, str, int]]:
    """Return every edge of `graph` as a `(source, target, line_number)` triple."""
    return {(edge.source, edge.target, edge.line_number) for edge in graph.edges}


@pytest.mark.asyncio
async def test_composition_is_unchanged_and_exposes_real_import_results(tmp_path: Path) -> None:
    """The composition keeps its 15 steps (no dependency-graph step) and yields real results."""
    _skip_without_git()
    source_repo = _make_source_repository(tmp_path)
    result = await _run_analysis(source_repo, tmp_path, "a")

    assert len(result.step_names()) == 15
    assert not any("dependency" in name for name in result.step_names())

    import_results = result.context.require("import_results")
    successful_parse_results = result.context.require("successful_parse_results")
    assert [r.relative_path for r in import_results] == [
        r.relative_path for r in successful_parse_results
    ]
    assert all(r.succeeded is True for r in import_results)
    assert sorted(r.relative_path for r in import_results) == sorted(
        _native(path)
        for path in (
            "lib/lib.rs",
            "main.py",
            "native/conn.cpp",
            "native/conn.h",
            "pkg/__init__.py",
            "pkg/consts.py",
            "pkg/util.py",
            "svc/main.go",
            "web/app.ts",
            "web/util.ts",
        )
    )


@pytest.mark.asyncio
async def test_real_results_build_the_expected_dependency_graph(tmp_path: Path) -> None:
    """The real `import_results` build exactly the graph the frozen contract prescribes."""
    _skip_without_git()
    source_repo = _make_source_repository(tmp_path)
    results = await _real_import_results(source_repo, tmp_path, "a")

    graph = StructuralDependencyGraphBuilder().build(results)

    assert isinstance(graph, DependencyGraph)  # `DependencyGraph.__post_init__` already ran
    assert {(node.identifier, node.kind) for node in graph.nodes} == {
        # Every successful input file is an INTERNAL_FILE node -- imports or not.
        *(
            (_native(path), INTERNAL_FILE)
            for path in (
                "lib/lib.rs",
                "main.py",
                "native/conn.cpp",
                "native/conn.h",
                "pkg/__init__.py",
                "pkg/consts.py",
                "pkg/util.py",
                "svc/main.go",
                "web/app.ts",
                "web/util.ts",
            )
        ),
        ("external:fmt", EXTERNAL_MODULE),
        ("external:os", EXTERNAL_MODULE),
        ("external:react", EXTERNAL_MODULE),
        ("external:requests", EXTERNAL_MODULE),
        ("external:std", EXTERNAL_MODULE),
        ("external:vector", EXTERNAL_MODULE),
        ("unresolved:lib/lib.rs#crate::a", UNRESOLVED_INTERNAL),
        ("unresolved:missing", UNRESOLVED_INTERNAL),
        ("unresolved:native/missing.h", UNRESOLVED_INTERNAL),
        ("unresolved:svc/util", UNRESOLVED_INTERNAL),
        ("unresolved:web/gone", UNRESOLVED_INTERNAL),
    }
    assert _edge_triples(graph) == {
        (_native("lib/lib.rs"), "external:std", 2),
        (_native("lib/lib.rs"), "unresolved:lib/lib.rs#crate::a", 1),
        (_native("main.py"), "external:os", 2),
        (_native("main.py"), "external:requests", 3),
        (_native("main.py"), _native("pkg/util.py"), 1),
        (_native("native/conn.cpp"), "external:vector", 2),
        (_native("native/conn.cpp"), _native("native/conn.h"), 1),
        (_native("native/conn.cpp"), "unresolved:native/missing.h", 3),
        (_native("pkg/util.py"), _native("pkg/consts.py"), 1),
        (_native("pkg/util.py"), _native("pkg/consts.py"), 2),
        (_native("pkg/util.py"), "unresolved:missing", 3),
        (_native("svc/main.go"), "external:fmt", 3),
        (_native("svc/main.go"), "unresolved:svc/util", 4),
        (_native("web/app.ts"), "external:react", 2),
        (_native("web/app.ts"), "unresolved:web/gone", 3),
        (_native("web/app.ts"), _native("web/util.ts"), 1),
    }
    assert graph.edge_count == sum(len(r.edges) for r in results)


@pytest.mark.asyncio
async def test_python_absolute_first_party_import_is_reclassified_as_internal(
    tmp_path: Path,
) -> None:
    """`from pkg.util import helper` is upstream `is_internal=False` yet resolves to a file."""
    _skip_without_git()
    source_repo = _make_source_repository(tmp_path)
    results = await _real_import_results(source_repo, tmp_path, "a")

    upstream = next(
        edge
        for result in results
        if result.relative_path == "main.py"
        for edge in result.edges
        if edge.target_module == "pkg.util"
    )
    assert upstream.is_internal is False  # the extractor's flag is not "definitely first-party"

    graph = StructuralDependencyGraphBuilder().build(results)
    (edge,) = (
        e for e in graph.edges if e.source == "main.py" and e.target == _native("pkg/util.py")
    )
    assert edge.is_internal is True
    assert edge.imported_names == ("helper",)
    assert graph.get_node(_native("pkg/util.py")).kind is INTERNAL_FILE


@pytest.mark.asyncio
async def test_python_relative_imports_resolve_inside_the_package(tmp_path: Path) -> None:
    """`from . import consts` and `from .consts import X` both reach `pkg/consts.py`."""
    _skip_without_git()
    source_repo = _make_source_repository(tmp_path)
    results = await _real_import_results(source_repo, tmp_path, "a")

    graph = StructuralDependencyGraphBuilder().build(results)

    util_edges = graph.outgoing_edges(_native("pkg/util.py"))
    to_consts = [e for e in util_edges if e.target == _native("pkg/consts.py")]
    assert [(e.imported_names, e.line_number, e.is_internal) for e in to_consts] == [
        (("consts",), 1, True),
        (("X",), 2, True),
    ]
    # `from ..missing import q` hops above `pkg/` to a missing root-level module.
    missing = graph.get_node("unresolved:missing")
    assert missing.kind is UNRESOLVED_INTERNAL
    assert [e.is_internal for e in util_edges if e.target == "unresolved:missing"] == [True]


@pytest.mark.asyncio
async def test_typescript_relative_imports_resolve_or_stay_unresolved(tmp_path: Path) -> None:
    """`./util` resolves to `web/util.ts`; `./gone` is an unresolved internal; `react` external."""
    _skip_without_git()
    source_repo = _make_source_repository(tmp_path)
    results = await _real_import_results(source_repo, tmp_path, "a")

    graph = StructuralDependencyGraphBuilder().build(results)

    app = {e.target: e for e in graph.outgoing_edges(_native("web/app.ts"))}
    assert app[_native("web/util.ts")].is_internal is True
    assert app["unresolved:web/gone"].is_internal is True
    assert app["external:react"].is_internal is False


@pytest.mark.asyncio
async def test_quoted_cpp_include_resolves_and_angle_include_stays_external(
    tmp_path: Path,
) -> None:
    """`"conn.h"` resolves next to the includer; `"missing.h"` does not; `<vector>` is external."""
    _skip_without_git()
    source_repo = _make_source_repository(tmp_path)
    results = await _real_import_results(source_repo, tmp_path, "a")

    graph = StructuralDependencyGraphBuilder().build(results)

    includes = {e.target: e for e in graph.outgoing_edges(_native("native/conn.cpp"))}
    assert includes[_native("native/conn.h")].is_internal is True
    assert includes["unresolved:native/missing.h"].is_internal is True
    assert includes["external:vector"].is_internal is False


@pytest.mark.asyncio
async def test_external_imports_and_go_rust_are_never_resolved_to_files(tmp_path: Path) -> None:
    """External imports stay external; Go/Rust never yield an `INTERNAL_FILE` target."""
    _skip_without_git()
    source_repo = _make_source_repository(tmp_path)
    results = await _real_import_results(source_repo, tmp_path, "a")

    graph = StructuralDependencyGraphBuilder().build(results)

    for source in ("svc/main.go", "lib/lib.rs"):
        for edge in graph.outgoing_edges(_native(source)):
            assert graph.get_node(edge.target).kind is not INTERNAL_FILE
    external_ids = {n.identifier for n in graph.nodes if n.kind is EXTERNAL_MODULE}
    assert {"external:os", "external:requests", "external:react", "external:fmt"} <= external_ids
    for edge in graph.edges:
        assert edge.is_internal is (graph.get_node(edge.target).kind is not EXTERNAL_MODULE)


@pytest.mark.asyncio
async def test_zero_import_files_are_nodes_without_outgoing_edges(tmp_path: Path) -> None:
    """Files that import nothing still appear as `INTERNAL_FILE` nodes."""
    _skip_without_git()
    source_repo = _make_source_repository(tmp_path)
    results = await _real_import_results(source_repo, tmp_path, "a")

    graph = StructuralDependencyGraphBuilder().build(results)

    for path in ("pkg/__init__.py", "native/conn.h", "web/util.ts"):
        assert graph.get_node(_native(path)).kind is INTERNAL_FILE
        assert graph.outgoing_edges(_native(path)) == ()


@pytest.mark.asyncio
async def test_unsupported_and_hidden_files_never_reach_the_graph(tmp_path: Path) -> None:
    """The unsupported README and the pruned dot-directory are absent from the graph."""
    _skip_without_git()
    source_repo = _make_source_repository(tmp_path)
    results = await _real_import_results(source_repo, tmp_path, "a")

    graph = StructuralDependencyGraphBuilder().build(results)

    assert all("README" not in node.identifier for node in graph.nodes)
    assert all(".hidden" not in node.identifier for node in graph.nodes)


@pytest.mark.asyncio
async def test_internal_file_identifiers_are_the_verbatim_input_paths(tmp_path: Path) -> None:
    """On every platform, `INTERNAL_FILE` identifiers equal the real `relative_path`s exactly."""
    _skip_without_git()
    source_repo = _make_source_repository(tmp_path)
    results = await _real_import_results(source_repo, tmp_path, "a")

    graph = StructuralDependencyGraphBuilder().build(results)

    internal_identifiers = sorted(n.identifier for n in graph.nodes if n.kind is INTERNAL_FILE)
    assert internal_identifiers == sorted(r.relative_path for r in results)
    assert {e.source for e in graph.edges} <= set(internal_identifiers)


@pytest.mark.asyncio
async def test_graph_build_is_deterministic_across_repeated_builds_runs_and_orderings(
    tmp_path: Path,
) -> None:
    """Building twice, from two independent runs, and from reversed input gives equal graphs."""
    _skip_without_git()
    source_repo = _make_source_repository(tmp_path)
    first_results = await _real_import_results(source_repo, tmp_path, "a")
    second_results = await _real_import_results(source_repo, tmp_path, "b")

    builder = StructuralDependencyGraphBuilder()
    first = builder.build(first_results)
    assert builder.build(first_results) == first
    assert builder.build(second_results) == first
    assert StructuralDependencyGraphBuilder().build(tuple(reversed(first_results))) == first
