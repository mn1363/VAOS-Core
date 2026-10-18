"""Unit tests for `src.graph.knowledge.structural`."""

import ast
import copy
import dataclasses
import inspect
import itertools
import json
import logging
from collections.abc import Iterator, Sequence
from typing import Any

import pytest
import src.core.logging as core_logging
from src.core.exceptions import ValidationError
from src.extractors.foundation.base import (
    FoundationCandidate,
    FoundationCandidateKind,
    FoundationExtractionResult,
)
from src.extractors.interfaces.base import (
    ExtractedInterface,
    InterfaceExtractionResult,
    InterfaceOrigin,
)
from src.extractors.patterns.base import ExtractedPattern, PatternExtractionResult
from src.extractors.symbols.base import (
    ExtractedSymbol,
    ExtractedSymbolKind,
    SymbolExtractionResult,
    build_qualified_name,
)
from src.graph.architecture.base import (
    ArchitectureGraph,
    PackageContainmentEdge,
    PackageNode,
)
from src.graph.knowledge import structural as structural_module
from src.graph.knowledge.base import (
    KnowledgeGraph,
    KnowledgeGraphBuilder,
    KnowledgeNode,
    KnowledgeNodeKind,
    KnowledgeRelation,
    KnowledgeRelationKind,
    capability_node_id,
    interface_node_id,
    pattern_node_id,
    symbol_node_id,
)
from src.graph.knowledge.structural import StructuralKnowledgeGraphBuilder

_DECLARES = KnowledgeRelationKind.DECLARES
_BELONGS = KnowledgeRelationKind.BELONGS_TO_PACKAGE
_EXTENDS = KnowledgeRelationKind.EXTENDS


def _symbol(
    relative_path: str,
    name: str,
    kind: ExtractedSymbolKind = ExtractedSymbolKind.FUNCTION,
    owner: str | None = None,
    line_number: int = 0,
) -> ExtractedSymbol:
    """Build an `ExtractedSymbol` whose `qualified_name` follows the frozen scheme."""
    return ExtractedSymbol(
        qualified_name=build_qualified_name(relative_path=relative_path, name=name, owner=owner),
        name=name,
        kind=kind,
        relative_path=relative_path,
        line_number=line_number,
    )


def _pattern(
    relative_path: str,
    subject_name: str = "Foo",
    name: str = "factory_method",
    description: str = "builds Foo",
    evidence: tuple[str, ...] = (),
    line_number: int = 0,
) -> ExtractedPattern:
    """Build an `ExtractedPattern`."""
    return ExtractedPattern(
        name=name,
        relative_path=relative_path,
        subject_name=subject_name,
        description=description,
        evidence=evidence,
        line_number=line_number,
    )


def _interface(
    relative_path: str,
    name: str,
    origin: InterfaceOrigin = InterfaceOrigin.ABSTRACT_CLASS,
    method_signatures: tuple[str, ...] = (),
    base_interfaces: tuple[str, ...] = (),
    line_number: int = 0,
) -> ExtractedInterface:
    """Build an `ExtractedInterface`."""
    return ExtractedInterface(
        name=name,
        origin=origin,
        relative_path=relative_path,
        method_signatures=method_signatures,
        base_interfaces=base_interfaces,
        line_number=line_number,
    )


def _candidate(
    relative_path: str,
    name: str,
    kind: FoundationCandidateKind = FoundationCandidateKind.CLASS,
    signals: tuple[str, ...] = (),
    line_number: int = 0,
    is_public: bool = False,
    has_docstring: bool = False,
) -> FoundationCandidate:
    """Build a `FoundationCandidate`."""
    return FoundationCandidate(
        name=name,
        kind=kind,
        relative_path=relative_path,
        is_public=is_public,
        has_docstring=has_docstring,
        signals=signals,
        line_number=line_number,
    )


def _symbols_result(relative_path: str, *symbols: ExtractedSymbol) -> SymbolExtractionResult:
    """Build a successful `SymbolExtractionResult`."""
    return SymbolExtractionResult.ok(relative_path=relative_path, symbols=symbols)


def _patterns_result(relative_path: str, *patterns: ExtractedPattern) -> PatternExtractionResult:
    """Build a successful `PatternExtractionResult`."""
    return PatternExtractionResult.ok(relative_path=relative_path, patterns=patterns)


def _interfaces_result(
    relative_path: str, *interfaces: ExtractedInterface
) -> InterfaceExtractionResult:
    """Build a successful `InterfaceExtractionResult`."""
    return InterfaceExtractionResult.ok(relative_path=relative_path, interfaces=interfaces)


def _foundation_result(
    relative_path: str, *candidates: FoundationCandidate
) -> FoundationExtractionResult:
    """Build a successful `FoundationExtractionResult`."""
    return FoundationExtractionResult.ok(relative_path=relative_path, candidates=candidates)


def _entity(relative_path: str) -> KnowledgeNode:
    """The expected `ENTITY` node for `relative_path`."""
    return KnowledgeNode(
        identifier=f"entity:{relative_path}",
        kind=KnowledgeNodeKind.ENTITY,
        label=relative_path,
        relative_path=relative_path,
    )


def _declares(relative_path: str, target: str) -> KnowledgeRelation:
    """The expected `DECLARES` relation from `relative_path`'s entity to `target`."""
    return KnowledgeRelation(source=f"entity:{relative_path}", target=target, kind=_DECLARES)


# -- Construction and contract --------------------------------------------------------------------


def test_builder_is_zero_argument_constructible_and_a_knowledge_graph_builder() -> None:
    """The builder constructs with no arguments and satisfies the `KnowledgeGraphBuilder` Port."""
    builder = StructuralKnowledgeGraphBuilder()
    assert isinstance(builder, KnowledgeGraphBuilder)


def test_builder_is_stateless_with_no_init_override() -> None:
    """The builder declares no `__init__` and holds no instance state."""
    assert "__init__" not in vars(StructuralKnowledgeGraphBuilder)
    assert vars(StructuralKnowledgeGraphBuilder()) == {}


def test_build_signature_matches_the_port_exactly() -> None:
    """`build` has the Port's exact keyword-only parameters, names, and defaults."""
    concrete = inspect.signature(StructuralKnowledgeGraphBuilder.build).parameters
    port = inspect.signature(KnowledgeGraphBuilder.build).parameters
    assert [(p.name, p.kind, p.default) for p in concrete.values()] == [
        (p.name, p.kind, p.default) for p in port.values()
    ]
    keyword_only = [p.name for p in concrete.values() if p.kind is p.KEYWORD_ONLY]
    assert keyword_only == [
        "symbol_results",
        "pattern_results",
        "interface_results",
        "foundation_results",
        "architecture_graph",
    ]


def test_build_rejects_positional_arguments() -> None:
    """`build` accepts keyword arguments only."""
    with pytest.raises(TypeError):
        StructuralKnowledgeGraphBuilder().build(())  # type: ignore[misc]


# -- Empty input ----------------------------------------------------------------------------------


def test_empty_successful_input_builds_a_valid_empty_graph() -> None:
    """No arguments and explicitly empty sequences both build an empty `KnowledgeGraph`."""
    builder = StructuralKnowledgeGraphBuilder()
    assert builder.build() == KnowledgeGraph()
    graph = builder.build(
        symbol_results=(),
        pattern_results=(),
        interface_results=(),
        foundation_results=(),
        architecture_graph=None,
    )
    assert graph == KnowledgeGraph()
    assert graph.node_count == 0
    assert graph.relation_count == 0


def test_empty_architecture_graph_alone_builds_an_empty_graph() -> None:
    """An empty `ArchitectureGraph` contributes no packages and no entities."""
    graph = StructuralKnowledgeGraphBuilder().build(architecture_graph=ArchitectureGraph())
    assert graph == KnowledgeGraph()


# -- Entities -------------------------------------------------------------------------------------


def test_successful_results_without_concepts_still_produce_entities() -> None:
    """Every successful result's path becomes an entity, even with no concepts and no relations."""
    graph = StructuralKnowledgeGraphBuilder().build(
        symbol_results=(_symbols_result("s.py"),),
        pattern_results=(_patterns_result("p.py"),),
        interface_results=(_interfaces_result("i.py"),),
        foundation_results=(_foundation_result("f.py"),),
    )
    assert graph.nodes == (_entity("f.py"), _entity("i.py"), _entity("p.py"), _entity("s.py"))
    assert graph.relations == ()


def test_entity_node_shape() -> None:
    """An entity is labeled and pathed with its relative path and has empty attributes."""
    graph = StructuralKnowledgeGraphBuilder().build(symbol_results=(_symbols_result("src/a.py"),))
    entity = graph.get_node("entity:src/a.py")
    assert entity.kind is KnowledgeNodeKind.ENTITY
    assert entity.label == "src/a.py"
    assert entity.relative_path == "src/a.py"
    assert entity.attributes == ()


def test_entities_are_deduplicated_across_all_four_result_sequences() -> None:
    """One file represented in every sequence yields one entity declaring all four concepts."""
    symbol = _symbol("a.py", "f")
    pattern = _pattern("a.py")
    interface = _interface("a.py", "Runnable")
    candidate = _candidate("a.py", "Foo")
    graph = StructuralKnowledgeGraphBuilder().build(
        symbol_results=(_symbols_result("a.py", symbol),),
        pattern_results=(_patterns_result("a.py", pattern),),
        interface_results=(_interfaces_result("a.py", interface),),
        foundation_results=(_foundation_result("a.py", candidate),),
    )
    entities = [node for node in graph.nodes if node.kind is KnowledgeNodeKind.ENTITY]
    assert entities == [_entity("a.py")]
    assert [relation.target for relation in graph.relations_from("entity:a.py")] == [
        "capability:a.py::Foo",
        "interface:a.py::Runnable",
        "pattern:a.py::Foo.factory_method",
        "symbol:a.py::f",
    ]
    assert graph.node_count == 5
    assert graph.relation_count == 4


def test_two_results_for_the_same_file_share_one_entity() -> None:
    """Two distinct-concept results for one path share a single entity."""
    graph = StructuralKnowledgeGraphBuilder().build(
        symbol_results=(
            _symbols_result("a.py", _symbol("a.py", "f")),
            _symbols_result("a.py", _symbol("a.py", "g")),
        ),
    )
    entities = [node for node in graph.nodes if node.kind is KnowledgeNodeKind.ENTITY]
    assert entities == [_entity("a.py")]
    assert graph.relation_count == 2


def test_a_concept_declared_under_another_path_is_owned_by_its_own_file() -> None:
    """A concept's own `relative_path` decides its owner; both paths get an entity."""
    symbol = _symbol("b.py", "f")
    graph = StructuralKnowledgeGraphBuilder().build(
        symbol_results=(_symbols_result("a.py", symbol),)
    )
    assert graph.nodes == (
        _entity("a.py"),
        _entity("b.py"),
        KnowledgeNode(
            identifier="symbol:b.py::f",
            kind=KnowledgeNodeKind.SYMBOL,
            label="f",
            relative_path="b.py",
            attributes=("kind=function",),
        ),
    )
    assert graph.relations == (_declares("b.py", "symbol:b.py::f"),)


# -- Symbols --------------------------------------------------------------------------------------


def test_one_symbol_produces_one_node_and_one_declares_relation() -> None:
    """A single symbol yields its entity, its node, and one `DECLARES` relation."""
    symbol = _symbol("a.py", "f", ExtractedSymbolKind.FUNCTION)
    graph = StructuralKnowledgeGraphBuilder().build(
        symbol_results=(_symbols_result("a.py", symbol),)
    )
    assert graph.nodes == (
        _entity("a.py"),
        KnowledgeNode(
            identifier="symbol:a.py::f",
            kind=KnowledgeNodeKind.SYMBOL,
            label="f",
            relative_path="a.py",
            attributes=("kind=function",),
        ),
    )
    assert graph.relations == (_declares("a.py", "symbol:a.py::f"),)


def test_symbol_kinds_are_preserved_in_a_kind_attribute() -> None:
    """Class, function, method, and constant symbols each carry their source kind."""
    graph = StructuralKnowledgeGraphBuilder().build(
        symbol_results=(
            _symbols_result(
                "a.py",
                _symbol("a.py", "Foo", ExtractedSymbolKind.CLASS),
                _symbol("a.py", "bar", ExtractedSymbolKind.METHOD, owner="Foo"),
                _symbol("a.py", "run", ExtractedSymbolKind.FUNCTION),
                _symbol("a.py", "LIMIT", ExtractedSymbolKind.CONSTANT),
            ),
        )
    )
    attributes = {
        node.identifier: node.attributes
        for node in graph.nodes
        if node.kind is KnowledgeNodeKind.SYMBOL
    }
    assert attributes == {
        "symbol:a.py::Foo": ("kind=class",),
        "symbol:a.py::Foo.bar": ("kind=method",),
        "symbol:a.py::run": ("kind=function",),
        "symbol:a.py::LIMIT": ("kind=constant",),
    }


def test_method_symbol_identifier_matches_the_frozen_symbol_node_id_helper() -> None:
    """A method's identifier equals the frozen `symbol_node_id` for the same owner and name."""
    method = _symbol("a.py", "bar", ExtractedSymbolKind.METHOD, owner="Foo")
    graph = StructuralKnowledgeGraphBuilder().build(
        symbol_results=(_symbols_result("a.py", method),)
    )
    expected = symbol_node_id(relative_path="a.py", name="bar", owner="Foo")
    assert expected == "symbol:a.py::Foo.bar"
    node = graph.get_node(expected)
    assert node.label == "bar"
    assert node.relative_path == "a.py"


def test_symbol_identifier_uses_the_given_qualified_name_without_reconstruction() -> None:
    """The identifier suffix is `qualified_name` verbatim; ownership is never re-derived."""
    symbol = ExtractedSymbol(
        qualified_name="a.py::Outer.Inner.method",
        name="method",
        kind=ExtractedSymbolKind.METHOD,
        relative_path="a.py",
    )
    graph = StructuralKnowledgeGraphBuilder().build(
        symbol_results=(_symbols_result("a.py", symbol),)
    )
    node = graph.get_node("symbol:a.py::Outer.Inner.method")
    assert node.label == "method"


# -- Patterns -------------------------------------------------------------------------------------


def test_pattern_node_carries_description_and_evidence_in_order() -> None:
    """A pattern node is labeled with its name and carries description then evidence, in order."""
    pattern = _pattern(
        "a.py",
        subject_name="Foo",
        name="factory_method",
        description="builds Foo instances",
        evidence=("name starts with create_", "returns Foo", "decorated with @staticmethod"),
    )
    graph = StructuralKnowledgeGraphBuilder().build(
        pattern_results=(_patterns_result("a.py", pattern),)
    )
    assert graph.nodes == (
        _entity("a.py"),
        KnowledgeNode(
            identifier="pattern:a.py::Foo.factory_method",
            kind=KnowledgeNodeKind.PATTERN,
            label="factory_method",
            relative_path="a.py",
            attributes=(
                "description=builds Foo instances",
                "evidence=name starts with create_",
                "evidence=returns Foo",
                "evidence=decorated with @staticmethod",
            ),
        ),
    )
    assert graph.relations == (_declares("a.py", "pattern:a.py::Foo.factory_method"),)


def test_pattern_without_evidence_carries_only_its_description() -> None:
    """A pattern with no evidence has exactly one attribute: its description."""
    graph = StructuralKnowledgeGraphBuilder().build(
        pattern_results=(_patterns_result("a.py", _pattern("a.py", description="why")),)
    )
    node = graph.get_node("pattern:a.py::Foo.factory_method")
    assert node.attributes == ("description=why",)


def test_patterns_with_the_same_name_on_different_subjects_are_distinct() -> None:
    """The subject name qualifies a pattern's identity."""
    graph = StructuralKnowledgeGraphBuilder().build(
        pattern_results=(
            _patterns_result(
                "a.py", _pattern("a.py", subject_name="Foo"), _pattern("a.py", subject_name="Bar")
            ),
        )
    )
    pattern_ids = [
        node.identifier for node in graph.nodes if node.kind is KnowledgeNodeKind.PATTERN
    ]
    assert pattern_ids == [
        "pattern:a.py::Bar.factory_method",
        "pattern:a.py::Foo.factory_method",
    ]


# -- Interfaces and EXTENDS -----------------------------------------------------------------------


def test_interface_node_carries_origin_and_method_signatures_in_order() -> None:
    """An interface node is labeled with its name and carries origin then method signatures."""
    interface = _interface(
        "a.py",
        "Runnable",
        origin=InterfaceOrigin.ABSTRACT_CLASS,
        method_signatures=("stop", "run"),
    )
    graph = StructuralKnowledgeGraphBuilder().build(
        interface_results=(_interfaces_result("a.py", interface),)
    )
    assert graph.nodes == (
        _entity("a.py"),
        KnowledgeNode(
            identifier="interface:a.py::Runnable",
            kind=KnowledgeNodeKind.INTERFACE,
            label="Runnable",
            relative_path="a.py",
            attributes=("origin=abstract_class", "method_signature=stop", "method_signature=run"),
        ),
    )
    assert graph.relations == (_declares("a.py", "interface:a.py::Runnable"),)


@pytest.mark.parametrize(
    ("origin", "expected"),
    [
        (InterfaceOrigin.LANGUAGE_INTERFACE, "origin=language_interface"),
        (InterfaceOrigin.TRAIT, "origin=trait"),
        (InterfaceOrigin.ABSTRACT_CLASS, "origin=abstract_class"),
    ],
)
def test_interface_origin_attribute_encoding(origin: InterfaceOrigin, expected: str) -> None:
    """Every `InterfaceOrigin` is encoded as an `origin=<value>` attribute."""
    graph = StructuralKnowledgeGraphBuilder().build(
        interface_results=(_interfaces_result("a.py", _interface("a.py", "I", origin=origin)),)
    )
    assert graph.get_node("interface:a.py::I").attributes == (expected,)


def test_base_interfaces_are_never_encoded_as_attributes() -> None:
    """Base interfaces are represented by `EXTENDS` relations only, never attribute strings."""
    graph = StructuralKnowledgeGraphBuilder().build(
        interface_results=(
            _interfaces_result("a.py", _interface("a.py", "Child", base_interfaces=("Base",))),
        )
    )
    attributes = graph.get_node("interface:a.py::Child").attributes
    assert attributes == ("origin=abstract_class",)
    assert not any("Base" in attribute for attribute in attributes)
    assert graph.relations_from("interface:a.py::Child") == (
        KnowledgeRelation(
            source="interface:a.py::Child", target="interface:external::Base", kind=_EXTENDS
        ),
    )


def test_unique_exact_name_base_interface_resolves_to_that_interface_node() -> None:
    """A base name matching exactly one extracted interface (even in another file) resolves."""
    graph = StructuralKnowledgeGraphBuilder().build(
        interface_results=(
            _interfaces_result("a.py", _interface("a.py", "Child", base_interfaces=("Base",))),
            _interfaces_result("b.py", _interface("b.py", "Base")),
        )
    )
    assert graph.relations_from("interface:a.py::Child") == (
        KnowledgeRelation(
            source="interface:a.py::Child", target="interface:b.py::Base", kind=_EXTENDS
        ),
    )
    assert graph.get_node("interface:b.py::Base").label == "Base"


def test_unique_resolution_works_within_one_file() -> None:
    """A base declared in the same file resolves to that file's own interface node."""
    graph = StructuralKnowledgeGraphBuilder().build(
        interface_results=(
            _interfaces_result(
                "a.py",
                _interface("a.py", "Base"),
                _interface("a.py", "Child", base_interfaces=("Base",)),
            ),
        )
    )
    assert graph.relations_from("interface:a.py::Child") == (
        KnowledgeRelation(
            source="interface:a.py::Child", target="interface:a.py::Base", kind=_EXTENDS
        ),
    )


def test_missing_base_interface_uses_the_external_reference() -> None:
    """A base name matching no extracted interface points at `interface:external::<name>`."""
    graph = StructuralKnowledgeGraphBuilder().build(
        interface_results=(
            _interfaces_result(
                "a.py", _interface("a.py", "Child", base_interfaces=("abc.ABC", "Protocol"))
            ),
        )
    )
    targets = [relation.target for relation in graph.relations_from("interface:a.py::Child")]
    assert targets == ["interface:external::Protocol", "interface:external::abc.ABC"]
    # The external targets are deliberately absent from the graph's nodes.
    known = {node.identifier for node in graph.nodes}
    assert not any(target in known for target in targets)


def test_ambiguous_base_interface_uses_the_external_reference_and_picks_no_winner() -> None:
    """A base name shared by two extracted interfaces is never resolved to either of them."""
    graph = StructuralKnowledgeGraphBuilder().build(
        interface_results=(
            _interfaces_result("a.py", _interface("a.py", "Child", base_interfaces=("Base",))),
            _interfaces_result("b.py", _interface("b.py", "Base")),
            _interfaces_result("c.py", _interface("c.py", "Base")),
        )
    )
    assert graph.relations_from("interface:a.py::Child") == (
        KnowledgeRelation(
            source="interface:a.py::Child", target="interface:external::Base", kind=_EXTENDS
        ),
    )
    assert not any(
        relation.kind is _EXTENDS
        and relation.target in {"interface:b.py::Base", "interface:c.py::Base"}
        for relation in graph.relations
    )
    # Both candidate interfaces still exist as nodes.
    assert graph.get_node("interface:b.py::Base")
    assert graph.get_node("interface:c.py::Base")


@pytest.mark.parametrize("base_name", ["base", "BASE", "pkg.Base", " Base", "Base "])
def test_base_interface_matching_is_exact_name_only(base_name: str) -> None:
    """Case differences, qualification, and whitespace never match; no normalization is done."""
    graph = StructuralKnowledgeGraphBuilder().build(
        interface_results=(
            _interfaces_result("a.py", _interface("a.py", "Child", base_interfaces=(base_name,))),
            _interfaces_result("b.py", _interface("b.py", "Base")),
        )
    )
    assert graph.relations_from("interface:a.py::Child") == (
        KnowledgeRelation(
            source="interface:a.py::Child",
            target=f"interface:external::{base_name}",
            kind=_EXTENDS,
        ),
    )


def test_multiple_base_interfaces_each_get_their_own_extends_relation() -> None:
    """Resolved and external bases coexist; one relation per `base_interfaces` entry."""
    graph = StructuralKnowledgeGraphBuilder().build(
        interface_results=(
            _interfaces_result(
                "a.py",
                _interface("a.py", "Base"),
                _interface("a.py", "Child", base_interfaces=("Base", "Protocol")),
            ),
        )
    )
    assert graph.relations_from("interface:a.py::Child") == (
        KnowledgeRelation(
            source="interface:a.py::Child", target="interface:a.py::Base", kind=_EXTENDS
        ),
        KnowledgeRelation(
            source="interface:a.py::Child", target="interface:external::Protocol", kind=_EXTENDS
        ),
    )


def test_a_repeated_base_name_is_not_deduplicated() -> None:
    """One `EXTENDS` relation is emitted per `base_interfaces` entry, repeats included."""
    graph = StructuralKnowledgeGraphBuilder().build(
        interface_results=(
            _interfaces_result("a.py", _interface("a.py", "Child", base_interfaces=("B", "B"))),
        )
    )
    assert [relation.target for relation in graph.relations_from("interface:a.py::Child")] == [
        "interface:external::B",
        "interface:external::B",
    ]


# -- Foundation candidates ------------------------------------------------------------------------


def test_foundation_candidate_node_identity_and_signals() -> None:
    """A candidate is a `CAPABILITY` node labeled with its name, with its signals verbatim."""
    candidate = _candidate("a.py", "Foo", signals=("no base classes", "decorated with @dataclass"))
    graph = StructuralKnowledgeGraphBuilder().build(
        foundation_results=(_foundation_result("a.py", candidate),)
    )
    assert graph.nodes == (
        KnowledgeNode(
            identifier="capability:a.py::Foo",
            kind=KnowledgeNodeKind.CAPABILITY,
            label="Foo",
            relative_path="a.py",
            attributes=("no base classes", "decorated with @dataclass"),
        ),
        _entity("a.py"),
    )
    assert graph.relations == (_declares("a.py", "capability:a.py::Foo"),)


def test_foundation_candidate_with_no_signals_has_no_attributes() -> None:
    """No signal is ever invented: empty signals give empty attributes."""
    candidate = FoundationCandidate(
        name="make",
        kind=FoundationCandidateKind.FUNCTION,
        relative_path="a.py",
        is_public=True,
        has_docstring=True,
        signals=(),
    )
    graph = StructuralKnowledgeGraphBuilder().build(
        foundation_results=(_foundation_result("a.py", candidate),)
    )
    assert graph.get_node("capability:a.py::make").attributes == ()


def test_same_name_in_different_concept_kinds_does_not_collide() -> None:
    """Node identifiers are namespaced by kind, so one name may be a symbol, interface, etc."""
    graph = StructuralKnowledgeGraphBuilder().build(
        symbol_results=(
            _symbols_result("a.py", _symbol("a.py", "Foo", ExtractedSymbolKind.CLASS)),
        ),
        interface_results=(_interfaces_result("a.py", _interface("a.py", "Foo")),),
        foundation_results=(_foundation_result("a.py", _candidate("a.py", "Foo")),),
    )
    assert [node.identifier for node in graph.nodes] == [
        "capability:a.py::Foo",
        "entity:a.py",
        "interface:a.py::Foo",
        "symbol:a.py::Foo",
    ]


# -- Architecture graph ---------------------------------------------------------------------------


def _architecture_graph() -> ArchitectureGraph:
    """A small architecture graph: a root package and one nested package."""
    return ArchitectureGraph(
        nodes=(
            PackageNode(
                package_path=(), file_paths=("__init__.py", "app.py"), has_package_root_file=True
            ),
            PackageNode(package_path=("pkg",), file_paths=("pkg/mod.py",)),
        ),
        edges=(PackageContainmentEdge(parent_path=(), child_path=("pkg",)),),
    )


def test_package_nodes_and_membership_relations_are_omitted_without_an_architecture_graph() -> None:
    """With `architecture_graph=None`, no `PACKAGE` node or `BELONGS_TO_PACKAGE` relation exists."""
    graph = StructuralKnowledgeGraphBuilder().build(
        symbol_results=(_symbols_result("app.py", _symbol("app.py", "main")),)
    )
    assert all(node.kind is not KnowledgeNodeKind.PACKAGE for node in graph.nodes)
    assert all(relation.kind is not _BELONGS for relation in graph.relations)


def test_package_nodes_and_belongs_to_package_relations() -> None:
    """Each `PackageNode` becomes a `PACKAGE` node; each member file belongs to its package."""
    graph = StructuralKnowledgeGraphBuilder().build(architecture_graph=_architecture_graph())
    assert graph.nodes == (
        _entity("__init__.py"),
        _entity("app.py"),
        _entity("pkg/mod.py"),
        KnowledgeNode(
            identifier="package:",
            kind=KnowledgeNodeKind.PACKAGE,
            label="",
            relative_path=None,
            attributes=("has_package_root_file=true",),
        ),
        KnowledgeNode(
            identifier="package:pkg",
            kind=KnowledgeNodeKind.PACKAGE,
            label="pkg",
            relative_path=None,
            attributes=("has_package_root_file=false",),
        ),
    )
    assert graph.relations == (
        KnowledgeRelation(source="entity:__init__.py", target="package:", kind=_BELONGS),
        KnowledgeRelation(source="entity:app.py", target="package:", kind=_BELONGS),
        KnowledgeRelation(source="entity:pkg/mod.py", target="package:pkg", kind=_BELONGS),
    )


def test_package_only_files_become_entities_without_any_extractor_result() -> None:
    """A file known only to the architecture graph still gets an entity and a membership."""
    graph = StructuralKnowledgeGraphBuilder().build(architecture_graph=_architecture_graph())
    entity = graph.get_node("entity:pkg/mod.py")
    assert entity.relative_path == "pkg/mod.py"
    assert [relation.kind for relation in graph.relations_from("entity:pkg/mod.py")] == [_BELONGS]


def test_a_file_in_results_and_in_a_package_has_one_entity_with_both_relations() -> None:
    """A file with a concept and a package has one entity with a `DECLARES` and a membership."""
    graph = StructuralKnowledgeGraphBuilder().build(
        symbol_results=(_symbols_result("app.py", _symbol("app.py", "main")),),
        architecture_graph=_architecture_graph(),
    )
    entities = [node for node in graph.nodes if node.kind is KnowledgeNodeKind.ENTITY]
    assert [entity.identifier for entity in entities] == [
        "entity:__init__.py",
        "entity:app.py",
        "entity:pkg/mod.py",
    ]
    assert graph.relations_from("entity:app.py") == (
        KnowledgeRelation(source="entity:app.py", target="package:", kind=_BELONGS),
        KnowledgeRelation(source="entity:app.py", target="symbol:app.py::main", kind=_DECLARES),
    )


def test_a_package_without_files_still_becomes_a_node() -> None:
    """An ancestor-only package has a node and no membership relation."""
    architecture = ArchitectureGraph(
        nodes=(
            PackageNode(package_path=()),
            PackageNode(package_path=("lib",)),
            PackageNode(package_path=("lib", "inner"), file_paths=("lib/inner/only.py",)),
        ),
        edges=(
            PackageContainmentEdge(parent_path=(), child_path=("lib",)),
            PackageContainmentEdge(parent_path=("lib",), child_path=("lib", "inner")),
        ),
    )
    graph = StructuralKnowledgeGraphBuilder().build(architecture_graph=architecture)
    assert [node.identifier for node in graph.nodes] == [
        "entity:lib/inner/only.py",
        "package:",
        "package:lib",
        "package:lib/inner",
    ]
    assert graph.relations == (
        KnowledgeRelation(
            source="entity:lib/inner/only.py", target="package:lib/inner", kind=_BELONGS
        ),
    )


# -- Duplicate identities -------------------------------------------------------------------------


def test_equivalent_duplicate_symbols_in_one_result_coalesce_into_one_node() -> None:
    """Two symbols with one complete key become one node and one `DECLARES` relation."""
    symbol = _symbol("a.py", "f")
    graph = StructuralKnowledgeGraphBuilder().build(
        symbol_results=(_symbols_result("a.py", symbol, symbol),)
    )
    assert graph == StructuralKnowledgeGraphBuilder().build(
        symbol_results=(_symbols_result("a.py", symbol),)
    )
    assert graph.relations == (_declares("a.py", "symbol:a.py::f"),)


def test_equivalent_duplicate_symbols_across_results_coalesce_into_one_node() -> None:
    """The same symbol arriving in two results is coalesced, not rejected."""
    symbol = _symbol("a.py", "f")
    graph = StructuralKnowledgeGraphBuilder().build(
        symbol_results=(_symbols_result("a.py", symbol), _symbols_result("a.py", symbol))
    )
    assert [node.identifier for node in graph.nodes] == ["entity:a.py", "symbol:a.py::f"]
    assert graph.relations == (_declares("a.py", "symbol:a.py::f"),)


def test_duplicate_pattern_identity_is_rejected() -> None:
    """Two patterns with one `(path, subject, name)` identity are rejected."""
    with pytest.raises(ValidationError, match="duplicate identifiers"):
        StructuralKnowledgeGraphBuilder().build(
            pattern_results=(
                _patterns_result(
                    "a.py", _pattern("a.py", description="one"), _pattern("a.py", description="two")
                ),
            )
        )


def test_duplicate_interface_identity_is_rejected() -> None:
    """Two interfaces with one `(path, name)` identity are rejected."""
    with pytest.raises(ValidationError, match="duplicate identifiers"):
        StructuralKnowledgeGraphBuilder().build(
            interface_results=(
                _interfaces_result("a.py", _interface("a.py", "I"), _interface("a.py", "I")),
            )
        )


def test_duplicate_capability_identity_is_rejected() -> None:
    """A class and a function sharing a name in one file collide as capabilities."""
    with pytest.raises(ValidationError, match="duplicate identifiers"):
        StructuralKnowledgeGraphBuilder().build(
            foundation_results=(
                _foundation_result(
                    "a.py",
                    _candidate("a.py", "Foo", FoundationCandidateKind.CLASS),
                    _candidate("a.py", "Foo", FoundationCandidateKind.FUNCTION),
                ),
            )
        )


# -- Validation -----------------------------------------------------------------------------------


def test_failed_symbol_extraction_propagates_the_validation_error() -> None:
    """A failed symbol result raises the existing `ValidationError`."""
    failed = SymbolExtractionResult.failed(relative_path="bad.py", error_message="boom")
    with pytest.raises(ValidationError, match="failed SymbolExtractionResult"):
        StructuralKnowledgeGraphBuilder().build(symbol_results=(_symbols_result("a.py"), failed))


def test_failed_pattern_extraction_propagates_the_validation_error() -> None:
    """A failed pattern result raises the existing `ValidationError`."""
    failed = PatternExtractionResult.failed(relative_path="bad.py", error_message="boom")
    with pytest.raises(ValidationError, match="failed PatternExtractionResult"):
        StructuralKnowledgeGraphBuilder().build(pattern_results=(failed,))


def test_failed_interface_extraction_propagates_the_validation_error() -> None:
    """A failed interface result raises the existing `ValidationError`."""
    failed = InterfaceExtractionResult.failed(relative_path="bad.py", error_message="boom")
    with pytest.raises(ValidationError, match="failed InterfaceExtractionResult"):
        StructuralKnowledgeGraphBuilder().build(interface_results=(failed,))


def test_failed_foundation_extraction_propagates_the_validation_error() -> None:
    """A failed foundation result raises the existing `ValidationError`."""
    failed = FoundationExtractionResult.failed(relative_path="bad.py", error_message="boom")
    with pytest.raises(ValidationError, match="failed FoundationExtractionResult"):
        StructuralKnowledgeGraphBuilder().build(foundation_results=(failed,))


def test_a_failed_result_is_rejected_even_when_every_other_input_is_valid_and_non_empty() -> None:
    """A single failed entry fails the whole build; nothing is partially assembled."""
    failed = FoundationExtractionResult.failed(relative_path="bad.py", error_message="boom")
    with pytest.raises(ValidationError):
        StructuralKnowledgeGraphBuilder().build(
            symbol_results=(_symbols_result("a.py", _symbol("a.py", "f")),),
            pattern_results=(_patterns_result("a.py", _pattern("a.py")),),
            interface_results=(_interfaces_result("a.py", _interface("a.py", "I")),),
            foundation_results=(failed,),
            architecture_graph=_architecture_graph(),
        )


# -- Determinism ----------------------------------------------------------------------------------


def _full_inputs() -> dict[str, tuple[object, ...]]:
    """Inputs spanning every family, in a deliberately non-sorted order."""
    return {
        "symbol_results": (
            _symbols_result(
                "z.py",
                _symbol("z.py", "Zed", ExtractedSymbolKind.CLASS),
                _symbol("z.py", "run", ExtractedSymbolKind.METHOD, owner="Zed"),
            ),
            _symbols_result("a.py", _symbol("a.py", "alpha")),
        ),
        "pattern_results": (
            _patterns_result("m.py", _pattern("m.py", subject_name="Zed", evidence=("e2", "e1"))),
        ),
        "interface_results": (
            _interfaces_result(
                "z.py", _interface("z.py", "Zi", base_interfaces=("Ai", "Missing", "Ai2"))
            ),
            _interfaces_result("a.py", _interface("a.py", "Ai"), _interface("a.py", "Ai2")),
        ),
        "foundation_results": (
            _foundation_result("z.py", _candidate("z.py", "Zed", signals=("s2", "s1"))),
            _foundation_result(
                "b.py", _candidate("b.py", "beta", FoundationCandidateKind.FUNCTION)
            ),
        ),
    }


def _build_from(inputs: dict[str, tuple[object, ...]], *, reverse: bool) -> KnowledgeGraph:
    """Build from `inputs`, optionally with each sequence reversed."""

    def ordered(key: str) -> tuple[object, ...]:
        values = inputs[key]
        return tuple(reversed(values)) if reverse else values

    return StructuralKnowledgeGraphBuilder().build(
        symbol_results=ordered("symbol_results"),  # type: ignore[arg-type]
        pattern_results=ordered("pattern_results"),  # type: ignore[arg-type]
        interface_results=ordered("interface_results"),  # type: ignore[arg-type]
        foundation_results=ordered("foundation_results"),  # type: ignore[arg-type]
        architecture_graph=_architecture_graph(),
    )


def test_nodes_are_sorted_by_identifier_and_relations_by_source_target_kind() -> None:
    """Output ordering follows the documented keys."""
    graph = _build_from(_full_inputs(), reverse=False)
    identifiers = [node.identifier for node in graph.nodes]
    assert identifiers == sorted(identifiers)
    keys = [(r.source, r.target, r.kind.value) for r in graph.relations]
    assert keys == sorted(keys)
    assert graph.node_count > 0
    assert graph.relation_count > 0


def test_output_is_independent_of_input_order() -> None:
    """Reversing every input sequence produces an identical graph."""
    inputs = _full_inputs()
    assert _build_from(inputs, reverse=True) == _build_from(inputs, reverse=False)


def test_repeated_builds_are_equal_and_one_instance_holds_no_state() -> None:
    """Repeated builds, on one instance or two, give equal graphs regardless of what came before."""
    inputs = _full_inputs()
    builder = StructuralKnowledgeGraphBuilder()
    first = _build_from(inputs, reverse=False)
    builder.build(symbol_results=(_symbols_result("other.py", _symbol("other.py", "x")),))
    assert _build_from(inputs, reverse=False) == first
    assert builder.build() == KnowledgeGraph()


def test_extends_relations_sort_by_target_within_one_source() -> None:
    """Several `EXTENDS` relations from one interface are ordered by target identifier."""
    graph = _build_from(_full_inputs(), reverse=False)
    assert graph.relations_from("interface:z.py::Zi") == (
        KnowledgeRelation(source="interface:z.py::Zi", target="interface:a.py::Ai", kind=_EXTENDS),
        KnowledgeRelation(source="interface:z.py::Zi", target="interface:a.py::Ai2", kind=_EXTENDS),
        KnowledgeRelation(
            source="interface:z.py::Zi", target="interface:external::Missing", kind=_EXTENDS
        ),
    )


def test_inputs_are_not_mutated() -> None:
    """Building leaves every input record equal to a deep copy taken beforehand."""
    inputs = _full_inputs()
    architecture = _architecture_graph()
    before = copy.deepcopy((inputs, architecture))
    _build_from(inputs, reverse=False)
    assert (inputs, architecture) == before

# -- Duplicate identity policy: shared helpers ----------------------------------------------------

_LOGGER_NAME = "vaos.graph.knowledge.structural"
_DUPLICATE_PREFIX = "KnowledgeGraph: nodes must not contain duplicate identifiers"
_CLASS = FoundationCandidateKind.CLASS
_FUNCTION = FoundationCandidateKind.FUNCTION


def _warning_message(
    *,
    symbol_groups: int = 0,
    symbol_declarations: int = 0,
    capability_groups: int = 0,
    capability_declarations: int = 0,
) -> str:
    """The exact aggregate WARNING text for the given counts, spelled out independently."""
    return (
        f"Coalesced {symbol_groups + capability_groups} colliding node group(s) covering "
        f"{symbol_declarations + capability_declarations} declaration(s): "
        f"symbol={symbol_groups} group(s)/{symbol_declarations} declaration(s), "
        f"capability={capability_groups} group(s)/{capability_declarations} declaration(s); "
        "declaration multiplicity and metadata outside the node projection are not preserved"
    )


def _raw_symbol(
    qualified_name: str,
    name: str,
    kind: ExtractedSymbolKind,
    relative_path: str,
    line_number: int = 0,
) -> ExtractedSymbol:
    """Build an `ExtractedSymbol` with every field given explicitly."""
    return ExtractedSymbol(
        qualified_name=qualified_name,
        name=name,
        kind=kind,
        relative_path=relative_path,
        line_number=line_number,
    )


def _build_one(
    *,
    symbols: Sequence[ExtractedSymbol] = (),
    candidates: Sequence[FoundationCandidate] = (),
    interfaces: Sequence[ExtractedInterface] = (),
    patterns: Sequence[ExtractedPattern] = (),
    path: str = "m.py",
) -> KnowledgeGraph:
    """Build from exactly one successful result per family, all reported for `path`."""
    return StructuralKnowledgeGraphBuilder().build(
        symbol_results=(_symbols_result(path, *symbols),),
        pattern_results=(_patterns_result(path, *patterns),),
        interface_results=(_interfaces_result(path, *interfaces),),
        foundation_results=(_foundation_result(path, *candidates),),
    )


def _rejection(**inputs: Any) -> ValidationError:
    """Build from `inputs`, requiring a `ValidationError`, and return it."""
    with pytest.raises(ValidationError) as excinfo:
        StructuralKnowledgeGraphBuilder().build(**inputs)
    return excinfo.value


def _rejection_one(**kwargs: Any) -> ValidationError:
    """Like `_build_one`, requiring a `ValidationError`, and return it."""
    with pytest.raises(ValidationError) as excinfo:
        _build_one(**kwargs)
    return excinfo.value


def _collisions(error: ValidationError) -> list[dict[str, Any]]:
    """The `collisions` entries of an aggregate collision error's details."""
    collisions: list[dict[str, Any]] = list(error.details["collisions"])
    return collisions


def _is_json_safe(value: object) -> bool:
    """Whether `value` is built only from str, int, bool, lists, and str-keyed dicts."""
    if isinstance(value, dict):
        return all(type(key) is str and _is_json_safe(item) for key, item in value.items())
    if isinstance(value, list):
        return all(_is_json_safe(item) for item in value)
    return type(value) in {str, int, bool}


def _symbol_diag(
    qualified_name: str, name: str, kind: str, relative_path: str, line_number: int
) -> dict[str, Any]:
    """The expected serialized diagnostic record of a symbol."""
    return {
        "qualified_name": qualified_name,
        "name": name,
        "declaration_kind": kind,
        "relative_path": relative_path,
        "line_number": line_number,
    }


def _capability_diag(
    name: str,
    kind: str,
    relative_path: str,
    line_number: int,
    *,
    signals: tuple[str, ...] = (),
    is_public: bool = False,
    has_docstring: bool = False,
) -> dict[str, Any]:
    """The expected serialized diagnostic record of a candidate."""
    return {
        "name": name,
        "declaration_kind": kind,
        "relative_path": relative_path,
        "signals": list(signals),
        "is_public": is_public,
        "has_docstring": has_docstring,
        "line_number": line_number,
    }


def _colliding_package_architecture() -> ArchitectureGraph:
    """A valid `ArchitectureGraph` whose two distinct `package_path`s share one `node_id`."""
    return ArchitectureGraph(
        nodes=(PackageNode(package_path=("a", "b")), PackageNode(package_path=("a/b",)))
    )


# -- Duplicate identity policy: logging fixtures --------------------------------------------------


class _Capture(logging.Handler):
    """Collects every record the structural logger emits."""

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        """Remember `record`."""
        self.records.append(record)

    def lines(self) -> list[tuple[int, str]]:
        """Every captured record as `(level, formatted message)`, in emission order."""
        return [(record.levelno, record.getMessage()) for record in self.records]


class _RaisingHandler(logging.Handler):
    """A handler whose `emit` raises `error`, optionally only for one record level."""

    def __init__(self, error: BaseException, *, only_level: int | None = None) -> None:
        super().__init__(level=logging.DEBUG)
        self.error = error
        self.only_level = only_level

    def emit(self, record: logging.LogRecord) -> None:
        """Raise the configured error for matching records."""
        if self.only_level is None or record.levelno == self.only_level:
            raise self.error


class _Boom(BaseException):
    """A test-local `BaseException` that is deliberately not an `Exception`."""


def _raising_filter(record: logging.LogRecord) -> bool:
    """A filter that always raises an ordinary exception."""
    raise RuntimeError("filter failure")


def _structural_logger() -> logging.Logger:
    """The logger the builder logs on."""
    return logging.getLogger(_LOGGER_NAME)


@pytest.fixture
def log_capture() -> Iterator[_Capture]:
    """Isolate the structural logger: DEBUG level, no propagation, one capturing handler.

    The logger's level, `disabled`/`propagate` flags, handlers, and filters are restored
    afterwards, so no other test observes any change.
    """
    logger = _structural_logger()
    saved = (logger.level, logger.disabled, logger.propagate)
    saved_handlers = list(logger.handlers)
    saved_filters = list(logger.filters)
    capture = _Capture()
    logger.handlers = [capture]
    logger.filters = []
    logger.setLevel(logging.DEBUG)
    logger.disabled = False
    logger.propagate = False
    try:
        yield capture
    finally:
        logger.handlers = saved_handlers
        logger.filters = saved_filters
        logger.setLevel(saved[0])
        logger.disabled = saved[1]
        logger.propagate = saved[2]


def _coalescing_inputs() -> dict[str, Any]:
    """Keyword arguments for one build that coalesces two SYMBOL groups and one CAPABILITY group.

    The SYMBOL groups have sizes 2 (`A.x`) and 3 (`g`); the CAPABILITY group has size 2 (`f`).
    """
    return {
        "symbol_results": (
            _symbols_result(
                "m.py",
                _symbol("m.py", "x", ExtractedSymbolKind.METHOD, "A", line_number=7),
                _symbol("m.py", "x", ExtractedSymbolKind.METHOD, "A", line_number=3),
                _symbol("m.py", "g", line_number=20),
                _symbol("m.py", "g", line_number=10),
                _symbol("m.py", "g", line_number=30),
            ),
        ),
        "foundation_results": (
            _foundation_result(
                "m.py",
                _candidate("m.py", "f", _FUNCTION, line_number=9, is_public=True),
                _candidate("m.py", "f", _FUNCTION, line_number=2, has_docstring=True),
            ),
        ),
    }


# -- Duplicate identity policy: coalescing (A) ----------------------------------------------------


def test_a1_property_getter_and_setter_methods_coalesce_into_one_symbol_node() -> None:
    """A getter/setter pair (two METHOD symbols) yields one node and exactly one `DECLARES`."""
    getter = _symbol("m.py", "x", ExtractedSymbolKind.METHOD, "A", line_number=3)
    setter = _symbol("m.py", "x", ExtractedSymbolKind.METHOD, "A", line_number=7)
    graph = _build_one(symbols=(getter, setter))
    assert graph.nodes == (
        _entity("m.py"),
        KnowledgeNode(
            identifier="symbol:m.py::A.x",
            kind=KnowledgeNodeKind.SYMBOL,
            label="x",
            relative_path="m.py",
            attributes=("kind=method",),
        ),
    )
    assert graph.relations == (_declares("m.py", "symbol:m.py::A.x"),)


def test_a2_overloads_coalesce_into_one_symbol_and_one_capability_node() -> None:
    """Three overloads (docstring False, False, True): one SYMBOL, one CAPABILITY, 2 DECLARES."""
    symbols = tuple(_symbol("m.py", "f", line_number=line) for line in (4, 6, 8))
    candidates = tuple(
        _candidate("m.py", "f", _FUNCTION, line_number=line, has_docstring=documented)
        for line, documented in ((4, False), (6, False), (8, True))
    )
    graph = _build_one(symbols=symbols, candidates=candidates)
    assert [node.identifier for node in graph.nodes] == [
        "capability:m.py::f",
        "entity:m.py",
        "symbol:m.py::f",
    ]
    assert graph.relations == (
        _declares("m.py", "capability:m.py::f"),
        _declares("m.py", "symbol:m.py::f"),
    )


def test_a3_a_repeated_function_definition_differing_only_by_line_number_coalesces() -> None:
    """Two definitions of one function that differ only in line number are one node."""
    graph = _build_one(
        symbols=(_symbol("m.py", "g", line_number=24), _symbol("m.py", "g", line_number=28))
    )
    assert graph.get_node("symbol:m.py::g").attributes == ("kind=function",)
    assert graph.node_count == 2
    assert graph.relations == (_declares("m.py", "symbol:m.py::g"),)


def test_a4_candidates_differing_only_in_unprojected_fields_coalesce() -> None:
    """`is_public`, `has_docstring`, and `line_number` never affect capability equivalence."""
    graph = _build_one(
        candidates=(
            _candidate("m.py", "f", _FUNCTION, line_number=1),
            _candidate("m.py", "f", _FUNCTION, line_number=5, is_public=True),
            _candidate("m.py", "f", _FUNCTION, line_number=9, has_docstring=True),
            _candidate("m.py", "f", _FUNCTION, line_number=0, is_public=True, has_docstring=True),
        )
    )
    assert graph.get_node("capability:m.py::f").attributes == ()
    assert graph.node_count == 2
    assert graph.relations == (_declares("m.py", "capability:m.py::f"),)


def test_a5_a_coalesced_symbol_node_equals_the_node_from_one_singleton() -> None:
    """The coalesced node is built from the key, identical to a singleton's, with a frozen id."""
    coalesced = _build_one(
        symbols=(
            _symbol("m.py", "bar", ExtractedSymbolKind.METHOD, "Foo", line_number=3),
            _symbol("m.py", "bar", ExtractedSymbolKind.METHOD, "Foo", line_number=40),
        )
    )
    singleton = _build_one(
        symbols=(_symbol("m.py", "bar", ExtractedSymbolKind.METHOD, "Foo", line_number=11),)
    )
    assert coalesced == singleton
    assert coalesced.to_mapping() == singleton.to_mapping()
    expected_id = symbol_node_id(relative_path="m.py", name="bar", owner="Foo")
    assert expected_id == "symbol:m.py::Foo.bar"
    assert coalesced.get_node(expected_id) == singleton.get_node(expected_id)


def test_a5_a_coalesced_capability_node_equals_the_node_from_one_singleton() -> None:
    """The same holds for capabilities, including a non-empty ordered `signals` tuple."""
    signals = ("no base classes", "decorated with @dataclass")
    coalesced = _build_one(
        candidates=(
            _candidate("m.py", "Foo", _CLASS, signals, line_number=1),
            _candidate("m.py", "Foo", _CLASS, signals, line_number=9, is_public=True),
        )
    )
    singleton = _build_one(candidates=(_candidate("m.py", "Foo", _CLASS, signals),))
    assert coalesced == singleton
    expected_id = capability_node_id(relative_path="m.py", name="Foo")
    assert expected_id == "capability:m.py::Foo"
    assert coalesced.get_node(expected_id).attributes == signals


@pytest.mark.parametrize("reverse_entries", [False, True])
def test_a6_equivalent_groups_across_two_result_entries_coalesce_in_either_order(
    reverse_entries: bool,
) -> None:
    """A symbol and a candidate spread over two entries each give one node and one `DECLARES`."""
    symbol_entries = (
        _symbols_result("m.py", _symbol("m.py", "f", line_number=1)),
        _symbols_result("m.py", _symbol("m.py", "f", line_number=9)),
    )
    foundation_entries = (
        _foundation_result("m.py", _candidate("m.py", "f", _FUNCTION, line_number=1)),
        _foundation_result(
            "m.py", _candidate("m.py", "f", _FUNCTION, line_number=9, has_docstring=True)
        ),
    )
    if reverse_entries:
        symbol_entries = symbol_entries[::-1]
        foundation_entries = foundation_entries[::-1]
    graph = StructuralKnowledgeGraphBuilder().build(
        symbol_results=symbol_entries, foundation_results=foundation_entries
    )
    assert [node.identifier for node in graph.nodes] == [
        "capability:m.py::f",
        "entity:m.py",
        "symbol:m.py::f",
    ]
    assert len(graph.relations) == 2


def test_a7_supplying_one_result_twice_matches_supplying_it_once(log_capture: _Capture) -> None:
    """A doubled result gives the same graph, but a WARNING counting every declaration."""
    symbols = _symbols_result("m.py", _symbol("m.py", "f", line_number=3))
    candidates = _foundation_result("m.py", _candidate("m.py", "f", _FUNCTION, line_number=3))
    builder = StructuralKnowledgeGraphBuilder()

    once = builder.build(symbol_results=(symbols,), foundation_results=(candidates,))
    assert log_capture.records == []

    twice = builder.build(
        symbol_results=(symbols, symbols), foundation_results=(candidates, candidates)
    )
    assert twice == once
    assert twice.to_mapping() == once.to_mapping()
    warnings = [line for line in log_capture.lines() if line[0] == logging.WARNING]
    assert warnings == [
        (
            logging.WARNING,
            _warning_message(
                symbol_groups=1,
                symbol_declarations=2,
                capability_groups=1,
                capability_declarations=2,
            ),
        )
    ]
    assert "covering 4 declaration(s)" in warnings[0][1]


# -- Duplicate identity policy: rejection (B) -----------------------------------------------------


def test_b1_a_class_and_a_function_sharing_a_name_produce_the_golden_diagnostic() -> None:
    """The class/function collision yields the exact approved message and structured details."""
    symbols = (
        _symbol("m.py", "Foo", ExtractedSymbolKind.FUNCTION, line_number=4),
        _symbol("m.py", "Foo", ExtractedSymbolKind.CLASS, line_number=1),
    )
    candidates = (
        _candidate("m.py", "Foo", _FUNCTION, line_number=4),
        _candidate("m.py", "Foo", _CLASS, line_number=1),
    )
    error = _rejection_one(symbols=symbols, candidates=candidates)

    assert str(error) == (
        f"{_DUPLICATE_PREFIX}; 2 colliding identifier(s) rejected: "
        "'capability:m.py::Foo', 'symbol:m.py::Foo'"
    )
    assert error.details == {
        "collision_count": 2,
        "collisions": [
            {
                "identifier": "capability:m.py::Foo",
                "node_kind": "capability",
                "reason": "conflicting_records",
                "differing_fields": ["declaration_kind"],
                "records": [
                    _capability_diag("Foo", "class", "m.py", 1),
                    _capability_diag("Foo", "function", "m.py", 4),
                ],
            },
            {
                "identifier": "symbol:m.py::Foo",
                "node_kind": "symbol",
                "reason": "conflicting_records",
                "differing_fields": ["declaration_kind"],
                "records": [
                    _symbol_diag("m.py::Foo", "Foo", "class", "m.py", 1),
                    _symbol_diag("m.py::Foo", "Foo", "function", "m.py", 4),
                ],
            },
        ],
    }
    # The approved field order is part of the contract.
    capability_collision, symbol_collision = _collisions(error)
    assert list(capability_collision["records"][0]) == [
        "name",
        "declaration_kind",
        "relative_path",
        "signals",
        "is_public",
        "has_docstring",
        "line_number",
    ]
    assert list(symbol_collision["records"][0]) == [
        "qualified_name",
        "name",
        "declaration_kind",
        "relative_path",
        "line_number",
    ]
    assert list(capability_collision) == [
        "identifier",
        "node_kind",
        "reason",
        "differing_fields",
        "records",
    ]


def test_b2_a_class_and_a_constant_with_one_symbol_identifier_are_rejected() -> None:
    """A class and a constant sharing a qualified name differ in `declaration_kind` only."""
    error = _rejection_one(
        symbols=(
            _symbol("m.ts", "Foo", ExtractedSymbolKind.CLASS, line_number=1),
            _symbol("m.ts", "Foo", ExtractedSymbolKind.CONSTANT, line_number=2),
        ),
        path="m.ts",
    )
    (collision,) = _collisions(error)
    assert collision["identifier"] == "symbol:m.ts::Foo"
    assert collision["reason"] == "conflicting_records"
    assert collision["differing_fields"] == ["declaration_kind"]
    assert [record["declaration_kind"] for record in collision["records"]] == [
        "class",
        "constant",
    ]


def test_b3_candidates_differing_only_in_candidate_kind_are_rejected_by_the_kind_guard() -> None:
    """The candidate `kind` is not projected, yet a class and a function never coalesce."""
    class_candidate = _candidate("m.py", "Foo", _CLASS, line_number=1)
    function_candidate = _candidate("m.py", "Foo", _FUNCTION, line_number=1)
    # Alone, either one yields the very same node, so only the kind guard separates them.
    assert _build_one(candidates=(class_candidate,)) == _build_one(candidates=(function_candidate,))
    error = _rejection_one(candidates=(class_candidate, function_candidate))
    (collision,) = _collisions(error)
    assert collision["identifier"] == "capability:m.py::Foo"
    assert collision["differing_fields"] == ["declaration_kind"]
    assert len(collision["records"]) == 2


@pytest.mark.parametrize(
    ("first", "second", "expected"),
    [
        pytest.param(
            _candidate("m.py", "f", _FUNCTION, ("a",)),
            _candidate("m.py", "f", _FUNCTION, ("b",)),
            ["signals"],
            id="different-signals",
        ),
        pytest.param(
            _candidate("m.py", "f", _FUNCTION, ("a", "b")),
            _candidate("m.py", "f", _FUNCTION, ("b", "a")),
            ["signals"],
            id="reversed-signals",
        ),
        pytest.param(
            _candidate("m.py", "f", _FUNCTION, ("a",)),
            _candidate("m.py", "f", _FUNCTION, ()),
            ["signals"],
            id="signals-versus-none",
        ),
        pytest.param(
            _candidate("m.py", "f", _CLASS, ("a",)),
            _candidate("m.py", "f", _FUNCTION, ("b",)),
            ["declaration_kind", "signals"],
            id="kind-and-signals",
        ),
        pytest.param(
            _candidate("a::b", "c", _FUNCTION),
            _candidate("a", "b::c", _FUNCTION),
            ["name", "relative_path"],
            id="delimiter-ambiguity",
        ),
    ],
)
def test_b4_capability_conflicts_report_their_sorted_differing_fields(
    first: FoundationCandidate, second: FoundationCandidate, expected: list[str]
) -> None:
    """Every non-equivalent capability pair is rejected with exactly its differing key fields."""
    error = _rejection(foundation_results=(_foundation_result("m.py", first, second),))
    (collision,) = _collisions(error)
    assert collision["node_kind"] == "capability"
    assert collision["reason"] == "conflicting_records"
    assert collision["differing_fields"] == expected
    assert len(collision["records"]) == 2


def test_b4_the_delimiter_ambiguity_collides_on_one_identifier_from_different_keys() -> None:
    """`("a::b", "c")` and `("a", "b::c")` share an identifier; the full key tells them apart."""
    assert capability_node_id(relative_path="a::b", name="c") == capability_node_id(
        relative_path="a", name="b::c"
    )
    error = _rejection(
        foundation_results=(
            _foundation_result(
                "m.py", _candidate("a::b", "c", _FUNCTION), _candidate("a", "b::c", _FUNCTION)
            ),
        )
    )
    (collision,) = _collisions(error)
    assert collision["identifier"] == "capability:a::b::c"
    assert sorted(record["relative_path"] for record in collision["records"]) == ["a", "a::b"]


@pytest.mark.parametrize(
    ("first", "second", "expected"),
    [
        pytest.param(
            _raw_symbol("m.py::f", "f", ExtractedSymbolKind.FUNCTION, "m.py"),
            _raw_symbol("m.py::f", "g", ExtractedSymbolKind.FUNCTION, "m.py"),
            ["name"],
            id="different-name",
        ),
        pytest.param(
            _raw_symbol("m.py::f", "f", ExtractedSymbolKind.FUNCTION, "m.py"),
            _raw_symbol("m.py::f", "f", ExtractedSymbolKind.FUNCTION, "other.py"),
            ["relative_path"],
            id="different-relative-path",
        ),
        pytest.param(
            _raw_symbol("a::b::c", "c", ExtractedSymbolKind.FUNCTION, "a::b"),
            _raw_symbol("a::b::c", "b::c", ExtractedSymbolKind.FUNCTION, "a"),
            ["name", "relative_path"],
            id="delimiter-ambiguity",
        ),
        pytest.param(
            _raw_symbol("m.py::f", "f", ExtractedSymbolKind.CLASS, "m.py"),
            _raw_symbol("m.py::f", "g", ExtractedSymbolKind.FUNCTION, "other.py"),
            ["declaration_kind", "name", "relative_path"],
            id="kind-name-and-path",
        ),
    ],
)
def test_b4_symbol_conflicts_report_their_sorted_differing_fields(
    first: ExtractedSymbol, second: ExtractedSymbol, expected: list[str]
) -> None:
    """Every non-equivalent symbol pair is rejected; `qualified_name` is never reported."""
    error = _rejection(symbol_results=(_symbols_result("m.py", first, second),))
    (collision,) = _collisions(error)
    assert collision["node_kind"] == "symbol"
    assert collision["reason"] == "conflicting_records"
    assert collision["differing_fields"] == expected
    assert "qualified_name" not in collision["differing_fields"]


def test_b5_a_conflicting_member_rejects_the_whole_group_without_partial_coalescing() -> None:
    """`{A, A, B}` is rejected entirely: no representative, majority, or partial node."""
    equivalent = _symbol("m.py", "f", ExtractedSymbolKind.FUNCTION, line_number=1)
    equivalent_again = _symbol("m.py", "f", ExtractedSymbolKind.FUNCTION, line_number=2)
    odd_one_out = _symbol("m.py", "f", ExtractedSymbolKind.CLASS, line_number=3)
    error = _rejection_one(symbols=(equivalent, equivalent_again, odd_one_out))
    (collision,) = _collisions(error)
    assert collision["differing_fields"] == ["declaration_kind"]
    assert [(r["declaration_kind"], r["line_number"]) for r in collision["records"]] == [
        ("function", 1),
        ("function", 2),
        ("class", 3),
    ]


def test_b5_a_three_member_group_of_distinct_members_lists_every_record() -> None:
    """A three-member conflicting capability group reports all three members."""
    error = _rejection_one(
        candidates=(
            _candidate("m.py", "f", _FUNCTION, ("a",), line_number=1),
            _candidate("m.py", "f", _FUNCTION, ("b",), line_number=2),
            _candidate("m.py", "f", _CLASS, ("a",), line_number=3),
        )
    )
    (collision,) = _collisions(error)
    assert collision["differing_fields"] == ["declaration_kind", "signals"]
    assert [record["line_number"] for record in collision["records"]] == [1, 2, 3]


def test_b6_seven_rejected_groups_raise_one_error_with_a_truncated_message() -> None:
    """The message lists five identifiers then `(and 2 more)`; the details list all seven."""
    symbols = tuple(
        symbol
        for index in range(7)
        for symbol in (
            _symbol("m.py", f"N{index}", ExtractedSymbolKind.CLASS, line_number=1),
            _symbol("m.py", f"N{index}", ExtractedSymbolKind.FUNCTION, line_number=2),
        )
    )
    error = _rejection_one(symbols=symbols)
    assert str(error) == (
        f"{_DUPLICATE_PREFIX}; 7 colliding identifier(s) rejected: "
        "'symbol:m.py::N0', 'symbol:m.py::N1', 'symbol:m.py::N2', 'symbol:m.py::N3', "
        "'symbol:m.py::N4' (and 2 more)"
    )
    assert error.details["collision_count"] == 7
    identifiers = [collision["identifier"] for collision in _collisions(error)]
    assert identifiers == [f"symbol:m.py::N{index}" for index in range(7)]
    assert all(len(collision["records"]) == 2 for collision in _collisions(error))


@pytest.mark.parametrize("count", [1, 5, 6])
def test_b6_the_message_suffix_appears_only_beyond_five_groups(count: int) -> None:
    """Five or fewer groups list every identifier with no `(and ... more)` suffix."""
    symbols = tuple(
        symbol
        for index in range(count)
        for symbol in (
            _symbol("m.py", f"N{index}", ExtractedSymbolKind.CLASS),
            _symbol("m.py", f"N{index}", ExtractedSymbolKind.FUNCTION),
        )
    )
    message = str(_rejection_one(symbols=symbols))
    assert message.startswith(f"{_DUPLICATE_PREFIX}; {count} colliding identifier(s) rejected: ")
    assert ("(and 1 more)" in message) is (count == 6)
    assert message.count("'symbol:m.py::N") == min(count, 5)


def test_b7_coalescible_groups_plus_one_conflict_report_only_the_rejected_group(
    log_capture: _Capture,
) -> None:
    """Coalescible groups never appear in the error, and nothing is logged when a build raises."""
    error = _rejection_one(
        symbols=(
            _symbol("m.py", "ok", line_number=1),
            _symbol("m.py", "ok", line_number=2),
            _symbol("m.py", "Bad", ExtractedSymbolKind.CLASS),
            _symbol("m.py", "Bad", ExtractedSymbolKind.FUNCTION),
        ),
        candidates=(
            _candidate("m.py", "ok", _FUNCTION, line_number=1),
            _candidate("m.py", "ok", _FUNCTION, line_number=2),
        ),
    )
    assert str(error) == (
        f"{_DUPLICATE_PREFIX}; 1 colliding identifier(s) rejected: 'symbol:m.py::Bad'"
    )
    assert [c["identifier"] for c in _collisions(error)] == ["symbol:m.py::Bad"]
    assert log_capture.records == []


def test_b9_only_declaration_kind_is_reported_when_it_alone_varies_in_a_group_of_three() -> None:
    """Fields equal across every member are never reported, and `qualified_name` never is."""
    error = _rejection_one(
        symbols=(
            _symbol("m.py", "Foo", ExtractedSymbolKind.CLASS, line_number=1),
            _symbol("m.py", "Foo", ExtractedSymbolKind.FUNCTION, line_number=2),
            _symbol("m.py", "Foo", ExtractedSymbolKind.CONSTANT, line_number=3),
        )
    )
    (collision,) = _collisions(error)
    assert collision["differing_fields"] == ["declaration_kind"]
    assert len(collision["records"]) == 3


def test_b10_diagnostics_serialize_enums_by_value_under_the_declaration_kind_name() -> None:
    """Records use `declaration_kind` as a plain `str`; the details are fully JSON-safe."""
    error = _rejection_one(
        symbols=(
            _symbol("m.py", "Foo", ExtractedSymbolKind.CLASS),
            _symbol("m.py", "Foo", ExtractedSymbolKind.FUNCTION),
        ),
        candidates=(
            _candidate("m.py", "Foo", _CLASS, ("s",)),
            _candidate("m.py", "Foo", _FUNCTION, ("s",)),
        ),
        interfaces=(
            _interface("m.py", "I", InterfaceOrigin.TRAIT, ("run",), ("B",)),
            _interface("m.py", "I", InterfaceOrigin.TRAIT, ("run",), ("B",)),
        ),
    )
    details = dict(error.details)
    assert _is_json_safe(details)
    assert json.loads(json.dumps(details)) == details
    for collision in details["collisions"]:
        assert type(collision["node_kind"]) is str
        for record in collision["records"]:
            assert "kind" not in record
            assert all(type(value) is not tuple for value in record.values())
            if "declaration_kind" in record:
                assert type(record["declaration_kind"]) is str
            if "origin" in record:
                assert type(record["origin"]) is str
                assert record["origin"] == "trait"
    assert {tuple(c["differing_fields"]) for c in details["collisions"]} == {
        ("declaration_kind",),
        (),
    }


# -- Duplicate identity policy: interfaces and patterns (C) ---------------------------------------


@pytest.mark.parametrize("identical", [True, False])
def test_c1_interface_collisions_are_rejected_even_when_the_records_are_identical(
    identical: bool,
) -> None:
    """Every multi-record INTERFACE group is `coalescing_not_permitted`, with all its records."""
    first = _interface("m.py", "I", InterfaceOrigin.ABSTRACT_CLASS, ("run",), ("Base",), 1)
    second = (
        first
        if identical
        else _interface("m.py", "I", InterfaceOrigin.TRAIT, ("stop", "run"), (), 5)
    )
    error = _rejection_one(interfaces=(second, first))
    (collision,) = _collisions(error)
    first_record = {
        "name": "I",
        "origin": "abstract_class",
        "relative_path": "m.py",
        "method_signatures": ["run"],
        "base_interfaces": ["Base"],
        "line_number": 1,
    }
    second_record = (
        first_record
        if identical
        else {
            "name": "I",
            "origin": "trait",
            "relative_path": "m.py",
            "method_signatures": ["stop", "run"],
            "base_interfaces": [],
            "line_number": 5,
        }
    )
    assert collision == {
        "identifier": "interface:m.py::I",
        "node_kind": "interface",
        "reason": "coalescing_not_permitted",
        "differing_fields": [],
        "records": [first_record, second_record],
    }
    assert list(collision["records"][0]) == [
        "name",
        "origin",
        "relative_path",
        "method_signatures",
        "base_interfaces",
        "line_number",
    ]


@pytest.mark.parametrize("identical", [True, False])
def test_c1_pattern_collisions_are_rejected_even_when_the_records_are_identical(
    identical: bool,
) -> None:
    """Every multi-record PATTERN group is `coalescing_not_permitted`, with all its records."""
    first = _pattern("m.py", "Foo", "factory_method", "builds Foo", ("e1", "e2"), 2)
    second = first if identical else _pattern("m.py", "Foo", "factory_method", "other", (), 8)
    error = _rejection_one(patterns=(second, first))
    (collision,) = _collisions(error)
    first_record = {
        "name": "factory_method",
        "subject_name": "Foo",
        "relative_path": "m.py",
        "description": "builds Foo",
        "evidence": ["e1", "e2"],
        "line_number": 2,
    }
    second_record = (
        first_record
        if identical
        else {
            "name": "factory_method",
            "subject_name": "Foo",
            "relative_path": "m.py",
            "description": "other",
            "evidence": [],
            "line_number": 8,
        }
    )
    assert collision == {
        "identifier": "pattern:m.py::Foo.factory_method",
        "node_kind": "pattern",
        "reason": "coalescing_not_permitted",
        "differing_fields": [],
        "records": [first_record, second_record],
    }
    assert list(collision["records"][0]) == [
        "name",
        "subject_name",
        "relative_path",
        "description",
        "evidence",
        "line_number",
    ]


def test_c2_a_doubled_result_with_symbols_and_interfaces_rejects_on_the_interface_group(
    log_capture: _Capture,
) -> None:
    """Eligible SYMBOL groups would coalesce, but the INTERFACE group rejects the whole build."""
    symbols = _symbols_result("m.py", _symbol("m.py", "f", line_number=1))
    interfaces = _interfaces_result("m.py", _interface("m.py", "I"))
    error = _rejection(
        symbol_results=(symbols, symbols), interface_results=(interfaces, interfaces)
    )
    assert str(error) == (
        f"{_DUPLICATE_PREFIX}; 1 colliding identifier(s) rejected: 'interface:m.py::I'"
    )
    (collision,) = _collisions(error)
    assert collision["node_kind"] == "interface"
    assert len(collision["records"]) == 2
    assert log_capture.records == []


def test_c3_the_same_interface_name_in_different_files_remains_valid() -> None:
    """Distinct `(path, name)` identities never collide; EXTENDS stays exact-name-only."""
    graph = StructuralKnowledgeGraphBuilder().build(
        interface_results=(
            _interfaces_result("a.py", _interface("a.py", "Base")),
            _interfaces_result("b.py", _interface("b.py", "Base")),
            _interfaces_result(
                "c.py", _interface("c.py", "Child", base_interfaces=("Base", "Base"))
            ),
        )
    )
    assert graph.get_node("interface:a.py::Base")
    assert graph.get_node("interface:b.py::Base")
    assert [relation.target for relation in graph.relations_from("interface:c.py::Child")] == [
        "interface:external::Base",
        "interface:external::Base",
    ]


# -- Duplicate identity policy: determinism (D) ---------------------------------------------------

_RECORD_FIELDS = ("symbols", "patterns", "interfaces", "candidates")


def _with_reversed_records(result: Any) -> Any:
    """Return `result` with the records inside it in reverse order."""
    for field_name in _RECORD_FIELDS:
        if hasattr(result, field_name):
            return dataclasses.replace(
                result, **{field_name: tuple(reversed(getattr(result, field_name)))}
            )
    raise AssertionError("not an extraction result")


def _arrangements(inputs: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Every combination of result-entry order and record order, per family."""
    keys = list(inputs)
    options_per_key = []
    for key in keys:
        options = []
        for permutation in itertools.permutations(inputs[key]):
            for reverse in (False, True):
                options.append(
                    tuple(_with_reversed_records(r) if reverse else r for r in permutation)
                )
        options_per_key.append(options)
    for combination in itertools.product(*options_per_key):
        yield dict(zip(keys, combination, strict=True))


def _spread_inputs() -> dict[str, Any]:
    """Equivalent groups spread over several entries and paths, plus unrelated singletons."""
    return {
        "symbol_results": (
            _symbols_result(
                "a.py", _symbol("a.py", "f", line_number=1), _symbol("a.py", "g", line_number=2)
            ),
            _symbols_result("a.py", _symbol("a.py", "f", line_number=9)),
            _symbols_result(
                "b.py",
                _symbol("b.py", "Foo", ExtractedSymbolKind.CLASS, line_number=1),
                _symbol("b.py", "bar", ExtractedSymbolKind.METHOD, "Foo", line_number=3),
                _symbol("b.py", "bar", ExtractedSymbolKind.METHOD, "Foo", line_number=7),
            ),
        ),
        "foundation_results": (
            _foundation_result(
                "a.py",
                _candidate("a.py", "f", _FUNCTION, line_number=1),
                _candidate("a.py", "g", _FUNCTION),
            ),
            _foundation_result(
                "a.py", _candidate("a.py", "f", _FUNCTION, line_number=9, has_docstring=True)
            ),
        ),
        "interface_results": (_interfaces_result("a.py", _interface("a.py", "I")),),
    }


def test_d1_any_input_order_produces_equal_graphs_and_identical_mappings() -> None:
    """Sequence order, result-entry order, and record order never change the graph."""
    builder = StructuralKnowledgeGraphBuilder()
    reference = builder.build(**_spread_inputs())
    assert [n.identifier for n in reference.nodes].count("symbol:a.py::f") == 1
    builds = 0
    for arrangement in _arrangements(_spread_inputs()):
        graph = builder.build(**arrangement)
        assert graph == reference
        assert graph.to_mapping() == reference.to_mapping()
        builds += 1
    assert builds > 50


def _rejected_inputs() -> dict[str, Any]:
    """Rejected groups in all four families, spread over several result entries."""
    function_foo = _symbol("a.py", "Foo", ExtractedSymbolKind.FUNCTION, line_number=4)
    class_foo = _symbol("a.py", "Foo", ExtractedSymbolKind.CLASS, line_number=1)
    interface = _interface("a.py", "I", base_interfaces=("B",), line_number=3)
    return {
        "symbol_results": (
            _symbols_result("a.py", function_foo),
            _symbols_result("a.py", class_foo),
        ),
        "foundation_results": (
            _foundation_result("a.py", _candidate("a.py", "Foo", _FUNCTION, ("x",), 4)),
            _foundation_result("a.py", _candidate("a.py", "Foo", _CLASS, ("y",), 1)),
        ),
        "interface_results": (
            _interfaces_result("a.py", interface),
            _interfaces_result("a.py", interface),
        ),
        "pattern_results": (
            _patterns_result("a.py", _pattern("a.py", "Foo", "p", "one", ("e",), 6)),
            _patterns_result("a.py", _pattern("a.py", "Foo", "p", "two", (), 2)),
        ),
    }


def test_d2_a_rejected_input_gives_identical_text_and_details_in_every_order() -> None:
    """Message text and deeply-equal details are independent of every input arrangement."""
    builder = StructuralKnowledgeGraphBuilder()
    with pytest.raises(ValidationError) as reference_info:
        builder.build(**_rejected_inputs())
    reference = reference_info.value
    assert reference.details["collision_count"] == 4
    assert [c["identifier"] for c in _collisions(reference)] == [
        "capability:a.py::Foo",
        "interface:a.py::I",
        "pattern:a.py::Foo.p",
        "symbol:a.py::Foo",
    ]
    arrangements = 0
    for arrangement in _arrangements(_rejected_inputs()):
        with pytest.raises(ValidationError) as excinfo:
            builder.build(**arrangement)
        assert str(excinfo.value) == str(reference)
        assert excinfo.value.details == reference.details
        arrangements += 1
    assert arrangements > 100


def test_d3_log_records_have_identical_order_and_text_in_every_input_order(
    log_capture: _Capture,
) -> None:
    """The WARNING and every DEBUG record are independent of the input arrangement."""
    builder = StructuralKnowledgeGraphBuilder()
    builder.build(**_spread_inputs())
    reference = log_capture.lines()
    # One WARNING, then DEBUG for capability a.py::f, symbol a.py::f, and symbol b.py::Foo.bar.
    assert len(reference) == 4
    for arrangement in _arrangements(_spread_inputs()):
        log_capture.records.clear()
        builder.build(**arrangement)
        assert log_capture.lines() == reference


# -- Duplicate identity policy: logging (E) -------------------------------------------------------


def test_e1_a_coalescing_build_emits_exactly_one_exact_warning(log_capture: _Capture) -> None:
    """Two SYMBOL groups (sizes 2, 3) and one CAPABILITY group (size 2) give the spec's example."""
    StructuralKnowledgeGraphBuilder().build(**_coalescing_inputs())
    warnings = [record for record in log_capture.records if record.levelno == logging.WARNING]
    assert len(warnings) == 1
    (warning,) = warnings
    assert warning.name == _LOGGER_NAME
    assert warning.getMessage() == (
        "Coalesced 3 colliding node group(s) covering 7 declaration(s): "
        "symbol=2 group(s)/5 declaration(s), capability=1 group(s)/2 declaration(s); "
        "declaration multiplicity and metadata outside the node projection are not preserved"
    )
    assert warning.msg == (
        "Coalesced %d colliding node group(s) covering %d declaration(s): "
        "symbol=%d group(s)/%d declaration(s), capability=%d group(s)/%d declaration(s); "
        "declaration multiplicity and metadata outside the node projection are not preserved"
    )
    assert warning.args == (3, 7, 2, 5, 1, 2)


@pytest.mark.parametrize(
    ("symbol_sizes", "capability_sizes", "expected"),
    [
        pytest.param(
            (3,),
            (),
            _warning_message(symbol_groups=1, symbol_declarations=3),
            id="one-symbol-group-of-three",
        ),
        pytest.param(
            (),
            (2, 3),
            _warning_message(capability_groups=2, capability_declarations=5),
            id="capability-groups-of-two-and-three",
        ),
        pytest.param(
            (2, 3),
            (4,),
            _warning_message(
                symbol_groups=2,
                symbol_declarations=5,
                capability_groups=1,
                capability_declarations=4,
            ),
            id="mixed",
        ),
    ],
)
def test_e1b_declaration_totals_are_the_sum_of_group_sizes_not_the_records_removed(
    log_capture: _Capture,
    symbol_sizes: tuple[int, ...],
    capability_sizes: tuple[int, ...],
    expected: str,
) -> None:
    """A group of three contributes three declarations; two plus three contribute five."""
    symbols = tuple(
        _symbol("m.py", f"s{group}", line_number=line)
        for group, size in enumerate(symbol_sizes)
        for line in range(1, size + 1)
    )
    candidates = tuple(
        _candidate("m.py", f"c{group}", _FUNCTION, line_number=line)
        for group, size in enumerate(capability_sizes)
        for line in range(1, size + 1)
    )
    _build_one(symbols=symbols, candidates=candidates)
    warnings = [line for line in log_capture.lines() if line[0] == logging.WARNING]
    assert warnings == [(logging.WARNING, expected)]


def test_e2_builds_that_do_not_coalesce_or_that_raise_emit_no_coalescing_records(
    log_capture: _Capture,
) -> None:
    """No coalescing, a rejected concept build, and a package collision all log nothing."""
    builder = StructuralKnowledgeGraphBuilder()
    builder.build(symbol_results=(_symbols_result("m.py", _symbol("m.py", "f")),))
    assert log_capture.records == []

    with pytest.raises(ValidationError):
        _build_one(
            symbols=(
                _symbol("m.py", "ok", line_number=1),
                _symbol("m.py", "ok", line_number=2),
                _symbol("m.py", "Bad", ExtractedSymbolKind.CLASS),
                _symbol("m.py", "Bad", ExtractedSymbolKind.FUNCTION),
            )
        )
    assert log_capture.records == []

    with pytest.raises(ValidationError):
        builder.build(
            symbol_results=(_symbols_result("m.py", _symbol("m.py", "f"), _symbol("m.py", "f")),),
            architecture_graph=_colliding_package_architecture(),
        )
    assert log_capture.records == []


def test_e3_debug_records_follow_identifier_then_canonical_member_order(
    log_capture: _Capture,
) -> None:
    """One DEBUG record per coalesced group, ascending by identifier, members in canonical order."""
    StructuralKnowledgeGraphBuilder().build(
        symbol_results=(
            _symbols_result(
                "m.py",
                _symbol("m.py", "x", ExtractedSymbolKind.METHOD, "A", line_number=7),
                _symbol("m.py", "x", ExtractedSymbolKind.METHOD, "A", line_number=3),
                _symbol("m.py", "single"),
            ),
        ),
        foundation_results=(
            _foundation_result(
                "m.py",
                _candidate("m.py", "f", _FUNCTION, line_number=8, has_docstring=True),
                _candidate("m.py", "f", _FUNCTION, line_number=4),
                _candidate("m.py", "f", _FUNCTION, line_number=6),
            ),
        ),
    )
    levels = [level for level, _ in log_capture.lines()]
    assert levels == [logging.WARNING, logging.DEBUG, logging.DEBUG]
    debug_messages = [message for level, message in log_capture.lines() if level == logging.DEBUG]
    assert debug_messages == [
        "Coalesced capability:m.py::f (capability): 3 declaration(s); line_numbers=[4, 6, 8]; "
        "is_public=[False, False, False]; has_docstring=[False, False, True]",
        "Coalesced symbol:m.py::A.x (symbol): 2 declaration(s); line_numbers=[3, 7]",
    ]


def test_e3_capability_flags_follow_the_canonical_member_order(log_capture: _Capture) -> None:
    """`is_public` and `has_docstring` are listed in the same order as `line_numbers`."""
    _build_one(
        candidates=(
            _candidate("m.py", "f", _FUNCTION, line_number=9, is_public=True),
            _candidate("m.py", "f", _FUNCTION, line_number=1, has_docstring=True),
        )
    )
    (debug_message,) = [m for level, m in log_capture.lines() if level == logging.DEBUG]
    assert debug_message == (
        "Coalesced capability:m.py::f (capability): 2 declaration(s); line_numbers=[1, 9]; "
        "is_public=[False, True]; has_docstring=[True, False]"
    )


def test_e3_no_debug_records_are_emitted_when_debug_is_disabled(log_capture: _Capture) -> None:
    """With the level at WARNING only the aggregate WARNING is emitted."""
    _structural_logger().setLevel(logging.WARNING)
    StructuralKnowledgeGraphBuilder().build(**_coalescing_inputs())
    assert [level for level, _ in log_capture.lines()] == [logging.WARNING]


def test_e4_the_graph_is_identical_for_every_logging_configuration(log_capture: _Capture) -> None:
    """DEBUG on, DEBUG off, logging silenced, and an ordinary logging exception: same graph."""
    builder = StructuralKnowledgeGraphBuilder()
    logger = _structural_logger()

    logger.setLevel(logging.DEBUG)
    with_debug = builder.build(**_coalescing_inputs())
    logger.setLevel(logging.WARNING)
    without_debug = builder.build(**_coalescing_inputs())
    logger.setLevel(logging.CRITICAL + 1)
    silenced = builder.build(**_coalescing_inputs())
    logger.setLevel(logging.DEBUG)
    logger.handlers = [_RaisingHandler(RuntimeError("handler failure"))]
    with_failing_logging = builder.build(**_coalescing_inputs())

    for graph in (without_debug, silenced, with_failing_logging):
        assert graph == with_debug
        assert graph.to_mapping() == with_debug.to_mapping()


_FAILURE_MODES = ["handler-emit", "debug-only-emit", "handler-filter", "logger-filter"]


def _install_failure(mode: str) -> None:
    """Configure the structural logger so that logging raises an ordinary exception."""
    logger = _structural_logger()
    if mode == "handler-emit":
        logger.handlers = [_RaisingHandler(RuntimeError("emit failure"))]
    elif mode == "debug-only-emit":
        logger.handlers = [_RaisingHandler(RuntimeError("emit failure"), only_level=logging.DEBUG)]
    elif mode == "handler-filter":
        handler = _Capture()
        handler.addFilter(_raising_filter)
        logger.handlers = [handler]
    elif mode == "logger-filter":
        logger.addFilter(_raising_filter)
    else:
        raise AssertionError(mode)


@pytest.mark.parametrize("mode", _FAILURE_MODES)
def test_e5_ordinary_logging_exceptions_never_prevent_the_graph_from_being_returned(
    log_capture: _Capture, mode: str
) -> None:
    """A raising handler `emit`, handler filter, or logger filter is suppressed.

    No assertion is made about which records were emitted: logging is best-effort.
    """
    builder = StructuralKnowledgeGraphBuilder()
    healthy = builder.build(**_coalescing_inputs())
    _install_failure(mode)
    failing = builder.build(**_coalescing_inputs())
    assert failing == healthy
    assert failing.to_mapping() == healthy.to_mapping()


@pytest.mark.parametrize("error_type", [_Boom, KeyboardInterrupt, SystemExit])
@pytest.mark.parametrize("only_level", [None, logging.DEBUG])
def test_e6_exceptions_outside_exception_propagate_out_of_build(
    log_capture: _Capture, error_type: type[BaseException], only_level: int | None
) -> None:
    """`BaseException` subclasses that are not `Exception`s are not suppressed."""
    _structural_logger().handlers = [_RaisingHandler(error_type(), only_level=only_level)]
    with pytest.raises(error_type):
        StructuralKnowledgeGraphBuilder().build(**_coalescing_inputs())


def _outcome(inputs: dict[str, Any]) -> tuple[type[BaseException], str, dict[str, Any]]:
    """The exception type, message, and details a build raises for `inputs`."""
    with pytest.raises(ValidationError) as excinfo:
        StructuralKnowledgeGraphBuilder().build(**inputs)
    return type(excinfo.value), str(excinfo.value), dict(excinfo.value.details)


def _failing_builds() -> dict[str, dict[str, Any]]:
    """One input for each of the three failure branches a build can take."""
    failed = SymbolExtractionResult.failed(relative_path="bad.py", error_message="boom")
    return {
        "extraction": {"symbol_results": (_symbols_result("m.py", _symbol("m.py", "f")), failed)},
        "concept-collision": {
            "symbol_results": (
                _symbols_result(
                    "m.py",
                    _symbol("m.py", "Foo", ExtractedSymbolKind.CLASS),
                    _symbol("m.py", "Foo", ExtractedSymbolKind.FUNCTION),
                ),
            )
        },
        "package-validation": {
            "symbol_results": (
                _symbols_result("m.py", _symbol("m.py", "f"), _symbol("m.py", "f")),
            ),
            "architecture_graph": _colliding_package_architecture(),
        },
    }


@pytest.mark.parametrize("mode", _FAILURE_MODES)
@pytest.mark.parametrize("branch", ["extraction", "concept-collision", "package-validation"])
def test_e7_failures_are_identical_with_failing_logging(
    log_capture: _Capture, mode: str, branch: str
) -> None:
    """Extraction, collision, and package-validation errors do not depend on logging health."""
    inputs = _failing_builds()[branch]
    healthy = _outcome(inputs)
    _install_failure(mode)
    assert _outcome(inputs) == healthy


def test_e8_builds_carry_no_state_across_a_logging_failure(log_capture: _Capture) -> None:
    """After a build whose logging failed, each later coalescing build logs its own records."""
    builder = StructuralKnowledgeGraphBuilder()
    logger = _structural_logger()
    healthy_handlers = list(logger.handlers)

    logger.handlers = [_RaisingHandler(RuntimeError("emit failure"))]
    first = builder.build(**_coalescing_inputs())
    logger.handlers = healthy_handlers
    second = builder.build(**_coalescing_inputs())
    third = builder.build(**_coalescing_inputs())

    assert first == second == third
    warnings = [line for line in log_capture.lines() if line[0] == logging.WARNING]
    assert len(warnings) == 2
    assert warnings[0] == warnings[1]
    # Each healthy build emitted its own complete set: one WARNING and three DEBUG records.
    assert len(log_capture.lines()) == 2 * (1 + 3)


def test_e9_only_warning_and_debug_records_are_ever_introduced(log_capture: _Capture) -> None:
    """No INFO, ERROR, or CRITICAL record exists, and no logger other than the module's is used."""
    builder = StructuralKnowledgeGraphBuilder()
    builder.build(**_coalescing_inputs())
    builder.build(**_full_inputs())
    assert {record.levelno for record in log_capture.records} == {logging.WARNING, logging.DEBUG}
    assert {record.name for record in log_capture.records} == {_LOGGER_NAME}
    assert structural_module._logger.name == _LOGGER_NAME
    assert structural_module.get_logger is core_logging.get_logger


def test_r3_the_guarded_logging_region_is_minimal_and_catches_only_exception() -> None:
    """Code review as a test: one `try`, logging calls only, `Exception` only, after the graph."""
    tree = ast.parse(inspect.getsource(structural_module))

    tries = [node for node in ast.walk(tree) if isinstance(node, ast.Try)]
    assert len(tries) == 1
    (guarded,) = tries
    assert len(guarded.handlers) == 1
    handler = guarded.handlers[0]
    assert handler.type is not None
    assert ast.unparse(handler.type) == "Exception"
    assert [type(statement) for statement in handler.body] == [ast.Return]
    assert not guarded.orelse
    assert not guarded.finalbody
    called = {
        ast.unparse(node.func)
        for statement in guarded.body
        for node in ast.walk(statement)
        if isinstance(node, ast.Call)
    }
    assert called == {"_logger.warning", "_logger.isEnabledFor", "_logger.debug"}

    (build,) = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "build"
    ]
    lines = {
        ast.unparse(node.func): node.lineno
        for node in ast.walk(build)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert lines["_collision_error"] < lines["KnowledgeGraph"] < lines["_log_coalescing"]
    assert [type(statement) for statement in build.body[-2:]] == [ast.Expr, ast.Return]


# -- Duplicate identity policy: entities, packages, relations, frozen contract (F, G, H) ----------


def test_f1_coalescing_leaves_one_entity_per_path() -> None:
    """Entity count is unchanged by coalescing: one entity per distinct path."""
    graph = StructuralKnowledgeGraphBuilder().build(
        symbol_results=(
            _symbols_result("a.py", _symbol("a.py", "f", line_number=1)),
            _symbols_result("a.py", _symbol("a.py", "f", line_number=2)),
            _symbols_result("b.py", _symbol("b.py", "g", line_number=1)),
        ),
        foundation_results=(
            _foundation_result("a.py", _candidate("a.py", "f", _FUNCTION, line_number=1)),
            _foundation_result("a.py", _candidate("a.py", "f", _FUNCTION, line_number=2)),
        ),
    )
    entities = [node.identifier for node in graph.nodes if node.kind is KnowledgeNodeKind.ENTITY]
    assert entities == ["entity:a.py", "entity:b.py"]
    # Two entities, symbols `f` and `g`, and capability `f`.
    assert graph.node_count == 5
    assert graph.relation_count == 3


def test_f2_a_package_identifier_collision_keeps_the_frozen_error_and_empty_details() -> None:
    """Package nodes are not deduplicated: a colliding `node_id` raises the existing error."""
    error = _rejection(architecture_graph=_colliding_package_architecture())
    assert str(error) == _DUPLICATE_PREFIX
    assert error.details == {}
    assert type(error) is ValidationError


def test_f3_a_concept_collision_takes_precedence_over_a_package_collision() -> None:
    """Concept collisions are evaluated before assembly, so their diagnostic wins."""
    error = _rejection(
        symbol_results=(
            _symbols_result(
                "m.py",
                _symbol("m.py", "Foo", ExtractedSymbolKind.CLASS),
                _symbol("m.py", "Foo", ExtractedSymbolKind.FUNCTION),
            ),
        ),
        architecture_graph=_colliding_package_architecture(),
    )
    assert str(error) == (
        f"{_DUPLICATE_PREFIX}; 1 colliding identifier(s) rejected: 'symbol:m.py::Foo'"
    )
    assert error.details["collision_count"] == 1


def test_f4_repeated_extends_and_package_membership_are_unchanged_by_coalescing() -> None:
    """Coalescing neither deduplicates repeated `EXTENDS` targets nor touches membership."""
    graph = StructuralKnowledgeGraphBuilder().build(
        symbol_results=(
            _symbols_result(
                "app.py", _symbol("app.py", "f", line_number=1), _symbol("app.py", "f")
            ),
        ),
        interface_results=(
            _interfaces_result("app.py", _interface("app.py", "Child", base_interfaces=("B", "B"))),
        ),
        architecture_graph=_architecture_graph(),
    )
    assert [r.target for r in graph.relations_from("interface:app.py::Child")] == [
        "interface:external::B",
        "interface:external::B",
    ]
    membership = KnowledgeRelation(source="entity:app.py", target="package:", kind=_BELONGS)
    assert membership in graph.relations
    assert len([n for n in graph.nodes if n.identifier == "symbol:app.py::f"]) == 1


def test_g2_frozen_identifier_helpers_and_the_frozen_validator_are_unchanged() -> None:
    """Golden identifiers hold, and `KnowledgeGraph(nodes=(n, n))` still rejects duplicates."""
    assert symbol_node_id(relative_path="a.py", name="bar", owner="Foo") == "symbol:a.py::Foo.bar"
    assert capability_node_id(relative_path="a.py", name="Foo") == "capability:a.py::Foo"
    assert interface_node_id(relative_path="a.py", name="Foo") == "interface:a.py::Foo"
    assert (
        pattern_node_id(relative_path="a.py", subject_name="Foo", name="p") == "pattern:a.py::Foo.p"
    )
    node = KnowledgeNode(identifier="symbol:a.py::f", kind=KnowledgeNodeKind.SYMBOL, label="f")
    with pytest.raises(ValidationError) as excinfo:
        KnowledgeGraph(nodes=(node, node))
    assert str(excinfo.value) == _DUPLICATE_PREFIX
    assert excinfo.value.details == {}


def test_h1_a_build_without_collisions_maps_one_node_per_record_and_logs_nothing(
    log_capture: _Capture,
) -> None:
    """With no collision, output has exactly one concept node and `DECLARES` per record."""
    inputs = _full_inputs()
    graph = StructuralKnowledgeGraphBuilder().build(
        **inputs, architecture_graph=_architecture_graph()
    )
    record_count = sum(
        len(getattr(result, field_name))
        for results in inputs.values()
        for result in results
        for field_name in _RECORD_FIELDS
        if hasattr(result, field_name)
    )
    concept_kinds = {
        KnowledgeNodeKind.SYMBOL,
        KnowledgeNodeKind.PATTERN,
        KnowledgeNodeKind.INTERFACE,
        KnowledgeNodeKind.CAPABILITY,
    }
    assert len([n for n in graph.nodes if n.kind in concept_kinds]) == record_count
    assert len([r for r in graph.relations if r.kind is _DECLARES]) == record_count
    assert log_capture.records == []
