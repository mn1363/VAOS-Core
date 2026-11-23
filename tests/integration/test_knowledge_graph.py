"""Integration test: `StructuralKnowledgeGraphBuilder` over real extraction results.

Proves that the concrete builder consumes the real `symbol_results`, `interface_results`,
`foundation_results`, and `architecture_graph` produced by the real-repository analysis
composition (`bootstrap(config, extra_steps=build_analysis_steps(config))`) and assembles them
into a valid, deterministic `KnowledgeGraph`. The builder is invoked directly on those context
values; it is not a pipeline step, so the composition still has exactly its 16 steps and writes no
knowledge graph. `pattern_results` stays `()` here because no concrete Pattern Extractor exists
yet -- non-empty pattern mapping is covered at unit level.

Like every other integration test in this directory, this clones a real, local (no-network) git
repository, so it needs the real `git` executable and is skipped, not failed, if one is
unavailable.

**Cross-platform handling.** Real `relative_path` values are platform-native (backslash-separated
on Windows), and the architecture extractor splits them on `/` only, so on Windows nested files
land in the root package -- existing, frozen extractor behavior. Fixture file identifiers here are
therefore built with `os.path.join` (`_p`), and every package expectation is derived from the real
`architecture_graph` rather than hard-coded, so each assertion holds unchanged on both platforms.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest
from src.bootstrap.analysis_steps import build_analysis_steps
from src.bootstrap.wiring import bootstrap
from src.core.config import AppConfig
from src.extractors.foundation.base import FoundationExtractionResult
from src.extractors.interfaces.base import InterfaceExtractionResult
from src.extractors.symbols.base import SymbolExtractionResult
from src.graph.architecture.base import ArchitectureGraph
from src.graph.knowledge.base import (
    KnowledgeGraph,
    KnowledgeNodeKind,
    KnowledgeRelation,
    KnowledgeRelationKind,
)
from src.graph.knowledge.structural import StructuralKnowledgeGraphBuilder
from src.parsers.base import ParseResult
from src.pipeline.base import PipelineResult


def _config(raw: dict[str, object]) -> AppConfig:
    """Build an `AppConfig` directly from a raw mapping, bypassing `load_config`/YAML/env."""
    return AppConfig(raw=raw)


def _run_git(*args: str, cwd: Path) -> None:
    """Run a `git` subcommand in `cwd`, raising if it fails."""
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _p(*parts: str) -> str:
    """A fixture-relative path in the platform's native separator, as real results report it."""
    return os.path.join(*parts)


_SHAPES_PY = '''\
from abc import ABC, abstractmethod
from typing import Protocol


class Shape(ABC):
    """A geometric shape."""

    @abstractmethod
    def area(self):
        ...

    @abstractmethod
    def perimeter(self):
        ...


class Renderable(Protocol):
    def render(self):
        ...


class Drawable(Renderable, Shape, Protocol):
    def draw(self):
        ...


def make_shape():
    return None
'''


def _write_fixture_repository(root: Path) -> None:
    """Populate `root` with a fixture repository, then commit it.

    Covers every concept family the real extractors produce:

    - an empty Python file (a successful result with no concepts) and a Python package marker;
    - a Python module whose three ABC/Protocol classes (`Shape`, `Renderable`, `Drawable`) give
      every `EXTENDS` outcome: `Drawable` extends `Renderable` (a unique exact-name match),
      `Shape` (ambiguous: a TypeScript `Shape` interface exists too), and `Protocol` (no
      extracted interface), while `Shape` itself extends `ABC` (external);
    - Python methods, a Python function, a Go interface/function/constant, a TypeScript
      interface/class/constant, and a Rust trait/function;
    - an unsupported file (`docs/notes/README.md`) and a dot-directory the enumerator prunes, which
      must never reach the graph.
    """
    (root / "__init__.py").write_text("", encoding="utf-8")
    (root / "app.py").write_text("def main():\n    return 1\n", encoding="utf-8")
    (root / "greeter.go").write_text(
        "package main\n\n"
        "type Greeter interface {\n\tGreet() string\n}\n\n"
        "const MaxSize = 10\n\n"
        "func Greet() {}\n",
        encoding="utf-8",
    )

    pkg = root / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "shapes.py").write_text(_SHAPES_PY, encoding="utf-8")

    web = root / "web"
    web.mkdir()
    (web / "index.ts").write_text(
        "export interface Shape { unit: string; area(): number }\n"
        "export interface Measurable {\n"
        "    readonly unit: string;\n"
        "    scale?: number;\n"
        "    area(): number;\n"
        "}\n"
        "export const VERSION = 1;\n"
        "export class Box { size(): number { return 1; } }\n",
        encoding="utf-8",
    )

    core = root / "core"
    core.mkdir()
    (core / "mod.rs").write_text(
        "pub trait Plugin {\n    fn run(&self);\n}\n\npub fn helper() {}\n", encoding="utf-8"
    )

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
    "build_dependency_graph",
)


@dataclass(frozen=True)
class _RealResults:
    """The real composition outputs the builder consumes, read from a finished run's context."""

    successful_parse_results: tuple[ParseResult, ...]
    symbol_results: tuple[SymbolExtractionResult, ...]
    interface_results: tuple[InterfaceExtractionResult, ...]
    foundation_results: tuple[FoundationExtractionResult, ...]
    architecture_graph: ArchitectureGraph


async def _run_analysis(source_repo: Path, tmp_path: Path, tag: str) -> PipelineResult:
    """Run the real 16-step composition and return its `PipelineResult`.

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


async def _real_results(source_repo: Path, tmp_path: Path, tag: str) -> _RealResults:
    """Run the real composition and collect the context values the builder consumes."""
    result = await _run_analysis(source_repo, tmp_path, tag)
    architecture_graph = result.context.require("architecture_graph")
    assert isinstance(architecture_graph, ArchitectureGraph)
    return _RealResults(
        successful_parse_results=tuple(result.context.require("successful_parse_results")),
        symbol_results=tuple(result.context.require("symbol_results")),
        interface_results=tuple(result.context.require("interface_results")),
        foundation_results=tuple(result.context.require("foundation_results")),
        architecture_graph=architecture_graph,
    )


def _build(real: _RealResults) -> KnowledgeGraph:
    """Invoke the builder directly on the real results, with the real architecture graph."""
    return StructuralKnowledgeGraphBuilder().build(
        symbol_results=real.symbol_results,
        pattern_results=(),
        interface_results=real.interface_results,
        foundation_results=real.foundation_results,
        architecture_graph=real.architecture_graph,
    )


def _skip_without_git() -> None:
    """Skip the calling test if the real `git` executable is unavailable."""
    if shutil.which("git") is None:
        pytest.skip("git executable not found on PATH")


def _ids(graph: KnowledgeGraph, kind: KnowledgeNodeKind) -> set[str]:
    """Every node identifier of `kind` in `graph`."""
    return {node.identifier for node in graph.nodes if node.kind is kind}


# The exact concept identifiers the fixture's real extraction results are expected to produce.
_SHAPES = _p("pkg", "shapes.py")
_INDEX = _p("web", "index.ts")
_MOD = _p("core", "mod.rs")

_EXPECTED_ENTITY_PATHS = {
    "__init__.py",
    "app.py",
    "greeter.go",
    _p("pkg", "__init__.py"),
    _SHAPES,
    _INDEX,
    _MOD,
}

_EXPECTED_SYMBOL_IDS = {
    "symbol:app.py::main",
    "symbol:greeter.go::Greet",
    "symbol:greeter.go::MaxSize",
    f"symbol:{_SHAPES}::Shape",
    f"symbol:{_SHAPES}::Renderable",
    f"symbol:{_SHAPES}::Drawable",
    f"symbol:{_SHAPES}::Shape.area",
    f"symbol:{_SHAPES}::Shape.perimeter",
    f"symbol:{_SHAPES}::Renderable.render",
    f"symbol:{_SHAPES}::Drawable.draw",
    f"symbol:{_SHAPES}::make_shape",
    f"symbol:{_INDEX}::Shape.area",
    f"symbol:{_INDEX}::Shape.unit",
    f"symbol:{_INDEX}::Measurable.area",
    f"symbol:{_INDEX}::Measurable.unit",
    f"symbol:{_INDEX}::Measurable.scale",
    f"symbol:{_INDEX}::Box",
    f"symbol:{_INDEX}::Box.size",
    f"symbol:{_INDEX}::VERSION",
    f"symbol:{_MOD}::helper",
}

_EXPECTED_INTERFACE_IDS = {
    "interface:greeter.go::Greeter",
    f"interface:{_SHAPES}::Shape",
    f"interface:{_SHAPES}::Renderable",
    f"interface:{_SHAPES}::Drawable",
    f"interface:{_INDEX}::Shape",
    f"interface:{_INDEX}::Measurable",
    f"interface:{_MOD}::Plugin",
}

_EXPECTED_CAPABILITY_IDS = {
    "capability:app.py::main",
    "capability:greeter.go::Greet",
    f"capability:{_SHAPES}::Shape",
    f"capability:{_SHAPES}::Renderable",
    f"capability:{_SHAPES}::Drawable",
    f"capability:{_SHAPES}::make_shape",
    f"capability:{_INDEX}::Box",
    f"capability:{_MOD}::helper",
}

_EXPECTED_EXTENDS = {
    # `Shape(ABC)`: `ABC` is not an extracted interface.
    (f"interface:{_SHAPES}::Shape", "interface:external::ABC"),
    (f"interface:{_SHAPES}::Renderable", "interface:external::Protocol"),
    # `Drawable(Renderable, Shape, Protocol)`: `Renderable` names exactly one extracted
    # interface; `Shape` names two (Python and TypeScript), so it is never resolved; `Protocol`
    # names none.
    (f"interface:{_SHAPES}::Drawable", f"interface:{_SHAPES}::Renderable"),
    (f"interface:{_SHAPES}::Drawable", "interface:external::Shape"),
    (f"interface:{_SHAPES}::Drawable", "interface:external::Protocol"),
}


@pytest.mark.asyncio
async def test_builder_assembles_real_results_into_a_valid_graph(tmp_path: Path) -> None:
    """Real extraction results build a valid, non-empty `KnowledgeGraph` of the exact concepts."""
    _skip_without_git()
    real = await _real_results(_make_source_repository(tmp_path), tmp_path, "a")

    graph = _build(real)

    # Valid and non-empty. `KnowledgeGraph.__post_init__` already ran on construction.
    assert isinstance(graph, KnowledgeGraph)
    assert graph.node_count > 0
    assert graph.relation_count > 0

    assert _ids(graph, KnowledgeNodeKind.ENTITY) == {
        f"entity:{path}" for path in _EXPECTED_ENTITY_PATHS
    }
    assert _ids(graph, KnowledgeNodeKind.SYMBOL) == _EXPECTED_SYMBOL_IDS
    assert _ids(graph, KnowledgeNodeKind.INTERFACE) == _EXPECTED_INTERFACE_IDS
    assert _ids(graph, KnowledgeNodeKind.CAPABILITY) == _EXPECTED_CAPABILITY_IDS
    # No concrete Pattern Extractor exists yet, so no pattern is ever fed in.
    assert _ids(graph, KnowledgeNodeKind.PATTERN) == set()


@pytest.mark.asyncio
async def test_entities_cover_exactly_the_files_the_real_parsers_accepted(tmp_path: Path) -> None:
    """Every successfully parsed file -- empty ones included -- is an entity; nothing else is."""
    _skip_without_git()
    real = await _real_results(_make_source_repository(tmp_path), tmp_path, "a")

    graph = _build(real)

    parsed_paths = {result.relative_path for result in real.successful_parse_results}
    entity_nodes = [node for node in graph.nodes if node.kind is KnowledgeNodeKind.ENTITY]
    assert {node.relative_path for node in entity_nodes} == parsed_paths
    assert parsed_paths == _EXPECTED_ENTITY_PATHS
    for node in entity_nodes:
        assert node.identifier == f"entity:{node.relative_path}"
        assert node.label == node.relative_path
        assert node.attributes == ()

    # The empty root `__init__.py` is a successful extraction with no concepts, yet still an
    # entity: it declares nothing and only belongs to its (root) package.
    assert [r.kind for r in graph.relations_from("entity:__init__.py")] == [
        KnowledgeRelationKind.BELONGS_TO_PACKAGE
    ]

    # Files the parsers rejected, and pruned dot-directories, never reach the graph.
    assert all("README.md" not in node.identifier for node in graph.nodes)
    assert all(".hidden" not in node.identifier for node in graph.nodes)


@pytest.mark.asyncio
async def test_every_concept_is_declared_once_by_its_own_file(tmp_path: Path) -> None:
    """Each concept node has exactly one `DECLARES` relation, from its own file's entity."""
    _skip_without_git()
    real = await _real_results(_make_source_repository(tmp_path), tmp_path, "a")

    graph = _build(real)

    concept_kinds = {
        KnowledgeNodeKind.SYMBOL,
        KnowledgeNodeKind.INTERFACE,
        KnowledgeNodeKind.CAPABILITY,
        KnowledgeNodeKind.PATTERN,
    }
    declares = [r for r in graph.relations if r.kind is KnowledgeRelationKind.DECLARES]
    concept_nodes = [node for node in graph.nodes if node.kind in concept_kinds]
    assert len(declares) == len(concept_nodes)
    assert {(r.source, r.target) for r in declares} == {
        (f"entity:{node.relative_path}", node.identifier) for node in concept_nodes
    }

    # One real result's concepts line up one-to-one with the real extractor output.
    assert len(_ids(graph, KnowledgeNodeKind.SYMBOL)) == sum(
        len(result.symbols) for result in real.symbol_results
    )
    assert len(_ids(graph, KnowledgeNodeKind.INTERFACE)) == sum(
        len(result.interfaces) for result in real.interface_results
    )
    assert len(_ids(graph, KnowledgeNodeKind.CAPABILITY)) == sum(
        len(result.candidates) for result in real.foundation_results
    )


@pytest.mark.asyncio
async def test_concept_attributes_carry_real_extractor_details(tmp_path: Path) -> None:
    """Attributes are derived from the real DTOs: symbol kind, interface origin and methods."""
    _skip_without_git()
    real = await _real_results(_make_source_repository(tmp_path), tmp_path, "a")

    graph = _build(real)

    assert graph.get_node(f"symbol:{_SHAPES}::Shape").attributes == ("kind=class",)
    assert graph.get_node(f"symbol:{_SHAPES}::Shape.area").attributes == ("kind=method",)
    assert graph.get_node("symbol:app.py::main").attributes == ("kind=function",)
    assert graph.get_node("symbol:greeter.go::MaxSize").attributes == ("kind=constant",)
    assert graph.get_node(f"symbol:{_INDEX}::Shape.unit").attributes == ("kind=property",)
    assert graph.get_node(f"symbol:{_INDEX}::Measurable.scale").attributes == ("kind=property",)

    assert graph.get_node(f"interface:{_SHAPES}::Shape").attributes == (
        "origin=abstract_class",
        "method_signature=area",
        "method_signature=perimeter",
    )
    assert graph.get_node("interface:greeter.go::Greeter").attributes == (
        "origin=language_interface",
    )
    assert graph.get_node(f"interface:{_MOD}::Plugin").attributes == ("origin=trait",)

    # The real Foundation extractor emits no signals, so no capability carries any attribute.
    capabilities = [n for n in graph.nodes if n.kind is KnowledgeNodeKind.CAPABILITY]
    assert capabilities
    assert all(node.attributes == () for node in capabilities)


@pytest.mark.asyncio
async def test_interface_properties_flow_into_the_graph_as_distinct_symbol_nodes(
    tmp_path: Path,
) -> None:
    """Real TypeScript interface properties become SYMBOL nodes, each declared by its own file."""
    _skip_without_git()
    real = await _real_results(_make_source_repository(tmp_path), tmp_path, "a")

    graph = _build(real)

    expected = {
        f"symbol:{_INDEX}::Shape.unit",
        f"symbol:{_INDEX}::Measurable.unit",
        f"symbol:{_INDEX}::Measurable.scale",
    }
    property_nodes = [node for node in graph.nodes if node.attributes == ("kind=property",)]
    assert {node.identifier for node in property_nodes} == expected
    assert all(node.kind is KnowledgeNodeKind.SYMBOL for node in property_nodes)
    assert all(node.relative_path == _INDEX for node in property_nodes)
    assert sorted(node.label for node in property_nodes) == ["scale", "unit", "unit"]

    declares = {
        (relation.source, relation.target)
        for relation in graph.relations
        if relation.kind is KnowledgeRelationKind.DECLARES
    }
    for identifier in expected:
        assert (f"entity:{_INDEX}", identifier) in declares

    # A property is a symbol only: it is never an interface or a capability of its own.
    assert f"interface:{_INDEX}::Shape.unit" not in _ids(graph, KnowledgeNodeKind.INTERFACE)
    assert f"capability:{_INDEX}::Shape.unit" not in _ids(graph, KnowledgeNodeKind.CAPABILITY)


@pytest.mark.asyncio
async def test_extends_relations_follow_exact_name_resolution(tmp_path: Path) -> None:
    """Real base interfaces resolve only on a unique exact name; everything else is external."""
    _skip_without_git()
    real = await _real_results(_make_source_repository(tmp_path), tmp_path, "a")

    graph = _build(real)

    extends = {
        (relation.source, relation.target)
        for relation in graph.relations
        if relation.kind is KnowledgeRelationKind.EXTENDS
    }
    assert extends == _EXPECTED_EXTENDS
    # The ambiguous `Shape` base is never resolved to either real `Shape` interface node...
    drawable = f"interface:{_SHAPES}::Drawable"
    drawable_targets = {
        r.target for r in graph.relations_from(drawable) if r.kind is KnowledgeRelationKind.EXTENDS
    }
    assert f"interface:{_SHAPES}::Shape" not in drawable_targets
    assert f"interface:{_INDEX}::Shape" not in drawable_targets
    # ...and both of them, and the resolved base, really exist as nodes.
    assert graph.get_node(f"interface:{_SHAPES}::Shape").label == "Shape"
    assert graph.get_node(f"interface:{_INDEX}::Shape").label == "Shape"
    assert f"interface:{_SHAPES}::Renderable" in drawable_targets
    # External targets are not nodes.
    known = {node.identifier for node in graph.nodes}
    assert "interface:external::Protocol" not in known


@pytest.mark.asyncio
async def test_package_nodes_and_membership_match_the_real_architecture_graph(
    tmp_path: Path,
) -> None:
    """One `PACKAGE` node per real `PackageNode`; each real member file belongs to its package."""
    _skip_without_git()
    real = await _real_results(_make_source_repository(tmp_path), tmp_path, "a")

    graph = _build(real)

    architecture = real.architecture_graph
    assert architecture.node_count > 0
    assert _ids(graph, KnowledgeNodeKind.PACKAGE) == {
        f"package:{node.node_id}" for node in architecture.nodes
    }
    for package in architecture.nodes:
        node = graph.get_node(f"package:{package.node_id}")
        assert node.label == package.node_id
        assert node.relative_path is None
        expected_flag = "true" if package.has_package_root_file else "false"
        assert node.attributes == (f"has_package_root_file={expected_flag}",)

    membership = {
        (relation.source, relation.target)
        for relation in graph.relations
        if relation.kind is KnowledgeRelationKind.BELONGS_TO_PACKAGE
    }
    assert membership == {
        (f"entity:{path}", f"package:{package.node_id}")
        for package in architecture.nodes
        for path in package.file_paths
    }
    # Every file the real architecture graph lists is also an entity.
    for package in architecture.nodes:
        for path in package.file_paths:
            assert graph.get_node(f"entity:{path}").relative_path == path


@pytest.mark.asyncio
async def test_graph_is_exactly_the_sum_of_its_parts(tmp_path: Path) -> None:
    """The full node and relation sets equal the exact expected fixture sets."""
    _skip_without_git()
    real = await _real_results(_make_source_repository(tmp_path), tmp_path, "a")

    graph = _build(real)

    expected_nodes = (
        {f"entity:{path}" for path in _EXPECTED_ENTITY_PATHS}
        | _EXPECTED_SYMBOL_IDS
        | _EXPECTED_INTERFACE_IDS
        | _EXPECTED_CAPABILITY_IDS
        | {f"package:{node.node_id}" for node in real.architecture_graph.nodes}
    )
    assert {node.identifier for node in graph.nodes} == expected_nodes
    assert graph.node_count == len(expected_nodes)

    expected_relations = (
        {
            KnowledgeRelation(
                source=f"entity:{node.relative_path}",
                target=node.identifier,
                kind=KnowledgeRelationKind.DECLARES,
            )
            for node in graph.nodes
            if node.kind
            in {
                KnowledgeNodeKind.SYMBOL,
                KnowledgeNodeKind.INTERFACE,
                KnowledgeNodeKind.CAPABILITY,
            }
        }
        | {
            KnowledgeRelation(
                source=f"entity:{path}",
                target=f"package:{package.node_id}",
                kind=KnowledgeRelationKind.BELONGS_TO_PACKAGE,
            )
            for package in real.architecture_graph.nodes
            for path in package.file_paths
        }
        | {
            KnowledgeRelation(source=source, target=target, kind=KnowledgeRelationKind.EXTENDS)
            for source, target in _EXPECTED_EXTENDS
        }
    )
    assert set(graph.relations) == expected_relations
    assert graph.relation_count == len(expected_relations)


@pytest.mark.asyncio
async def test_build_is_deterministic_across_repeated_builds_runs_and_input_order(
    tmp_path: Path,
) -> None:
    """Repeated builds, independent analysis runs, and reversed inputs all give equal graphs."""
    _skip_without_git()
    source_repo = _make_source_repository(tmp_path)
    first_real = await _real_results(source_repo, tmp_path, "a")
    second_real = await _real_results(source_repo, tmp_path, "b")

    builder = StructuralKnowledgeGraphBuilder()
    first = _build(first_real)
    assert _build(first_real) == first
    assert _build(second_real) == first
    assert first.to_mapping() == _build(second_real).to_mapping()
    assert (
        builder.build(
            symbol_results=tuple(reversed(first_real.symbol_results)),
            pattern_results=(),
            interface_results=tuple(reversed(first_real.interface_results)),
            foundation_results=tuple(reversed(first_real.foundation_results)),
            architecture_graph=first_real.architecture_graph,
        )
        == first
    )

    identifiers = [node.identifier for node in first.nodes]
    assert identifiers == sorted(identifiers)
    keys = [(r.source, r.target, r.kind.value) for r in first.relations]
    assert keys == sorted(keys)


@pytest.mark.asyncio
async def test_builder_without_architecture_graph_omits_packages_on_real_results(
    tmp_path: Path,
) -> None:
    """On the same real results, omitting the architecture graph drops only package content."""
    _skip_without_git()
    source_repo = _make_source_repository(tmp_path)
    real = await _real_results(source_repo, tmp_path, "a")

    with_packages = _build(real)
    without_packages = StructuralKnowledgeGraphBuilder().build(
        symbol_results=real.symbol_results,
        interface_results=real.interface_results,
        foundation_results=real.foundation_results,
    )

    assert _ids(without_packages, KnowledgeNodeKind.PACKAGE) == set()
    assert all(
        relation.kind is not KnowledgeRelationKind.BELONGS_TO_PACKAGE
        for relation in without_packages.relations
    )
    assert {
        n.identifier for n in with_packages.nodes if n.kind is not KnowledgeNodeKind.PACKAGE
    } == {n.identifier for n in without_packages.nodes}
    # The builder is not a pipeline step: the composition itself still writes no knowledge graph.
    result = await _run_analysis(source_repo, tmp_path, "c")
    assert len(result.step_names()) == 16
    assert not any("knowledge" in name for name in result.step_names())
