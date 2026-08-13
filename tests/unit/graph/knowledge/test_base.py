"""Unit tests for `src.graph.knowledge.base`."""

import pytest
from src.core.exceptions import NotFoundError, ValidationError
from src.extractors.foundation.base import FoundationExtractionResult
from src.extractors.interfaces.base import InterfaceExtractionResult
from src.extractors.patterns.base import PatternExtractionResult
from src.extractors.symbols.base import SymbolExtractionResult
from src.graph.architecture.base import PackageNode
from src.graph.knowledge.base import (
    KnowledgeGraph,
    KnowledgeGraphBuilder,
    KnowledgeNode,
    KnowledgeNodeKind,
    KnowledgeRelation,
    KnowledgeRelationKind,
    capability_node_id,
    entity_node_id,
    interface_node_id,
    package_node_id,
    pattern_node_id,
    require_successful_foundation_extractions,
    require_successful_interface_extractions,
    require_successful_pattern_extractions,
    require_successful_symbol_extractions,
    symbol_node_id,
)


def test_knowledge_graph_builder_cannot_be_instantiated_directly() -> None:
    """The abstract `KnowledgeGraphBuilder` Port must not be instantiable."""
    with pytest.raises(TypeError):
        KnowledgeGraphBuilder()  # type: ignore[abstract]


def test_symbol_node_id_matches_the_qualified_name_scheme() -> None:
    """`symbol_node_id` should namespace `build_qualified_name`'s own output."""
    assert symbol_node_id(relative_path="a.py", name="f") == "symbol:a.py::f"


def test_symbol_node_id_includes_the_owner_for_a_method() -> None:
    """`symbol_node_id` should thread `owner` through to the qualified name."""
    assert symbol_node_id(relative_path="a.py", name="bar", owner="Foo") == "symbol:a.py::Foo.bar"


def test_pattern_node_id_is_qualified_by_subject() -> None:
    """`pattern_node_id` should namespace a pattern by its file and subject."""
    result = pattern_node_id(relative_path="a.py", subject_name="Foo", name="factory_method")
    assert result == "pattern:a.py::Foo.factory_method"


def test_interface_node_id() -> None:
    """`interface_node_id` should namespace an interface by its file."""
    assert interface_node_id(relative_path="a.py", name="Runnable") == "interface:a.py::Runnable"


def test_capability_node_id() -> None:
    """`capability_node_id` should namespace a candidate by its file."""
    assert capability_node_id(relative_path="a.py", name="Foo") == "capability:a.py::Foo"


def test_entity_node_id_wraps_the_relative_path_directly() -> None:
    """`entity_node_id` should wrap `relative_path` without further qualification."""
    assert entity_node_id(relative_path="a.py") == "entity:a.py"


def test_package_node_id_wraps_the_package_node_id() -> None:
    """`package_node_id` should namespace a `PackageNode`'s own `node_id`."""
    node = PackageNode(package_path=("src", "graph"))
    assert package_node_id(node) == "package:src/graph"


def test_knowledge_node_rejects_an_identifier_not_namespaced_by_its_kind() -> None:
    """Constructing a node whose `identifier` prefix does not match `kind` should raise."""
    with pytest.raises(ValidationError):
        KnowledgeNode(identifier="pattern:a.py::Foo", kind=KnowledgeNodeKind.SYMBOL, label="Foo")


def test_knowledge_node_accepts_a_correctly_namespaced_identifier() -> None:
    """Constructing a node whose `identifier` is namespaced by its own `kind` should succeed."""
    node = KnowledgeNode(identifier="symbol:a.py::f", kind=KnowledgeNodeKind.SYMBOL, label="f")
    assert node.label == "f"


def test_knowledge_relation_rejects_an_empty_source() -> None:
    """Constructing a relation with a blank source should raise."""
    with pytest.raises(ValidationError):
        KnowledgeRelation(source=" ", target="entity:a.py", kind=KnowledgeRelationKind.DECLARES)


def test_knowledge_relation_rejects_an_empty_target() -> None:
    """Constructing a relation with a blank target should raise."""
    with pytest.raises(ValidationError):
        KnowledgeRelation(source="entity:a.py", target="  ", kind=KnowledgeRelationKind.DECLARES)


def _sample_graph() -> KnowledgeGraph:
    """Build a small, valid `KnowledgeGraph` with an entity declaring one symbol."""
    entity = KnowledgeNode(identifier="entity:a.py", kind=KnowledgeNodeKind.ENTITY, label="a.py")
    symbol = KnowledgeNode(
        identifier="symbol:a.py::f", kind=KnowledgeNodeKind.SYMBOL, label="f", relative_path="a.py"
    )
    interface = KnowledgeNode(
        identifier="interface:a.py::Runnable",
        kind=KnowledgeNodeKind.INTERFACE,
        label="Runnable",
        relative_path="a.py",
    )
    return KnowledgeGraph(
        nodes=(entity, interface, symbol),
        relations=(
            # Sorted by (source, target, kind): both DECLARES relations share the same source,
            # so they order by target ("interface:..." < "symbol:..."); the EXTENDS relation's
            # source ("interface:a.py::Runnable") sorts after "entity:a.py" and comes last.
            KnowledgeRelation(
                source="entity:a.py",
                target="interface:a.py::Runnable",
                kind=KnowledgeRelationKind.DECLARES,
            ),
            KnowledgeRelation(
                source="entity:a.py", target="symbol:a.py::f", kind=KnowledgeRelationKind.DECLARES
            ),
            KnowledgeRelation(
                source="interface:a.py::Runnable",
                target="interface:external::Base",
                kind=KnowledgeRelationKind.EXTENDS,
            ),
        ),
    )


def test_knowledge_graph_accepts_an_extends_relation_to_an_unknown_target() -> None:
    """An `EXTENDS` relation whose `target` is outside this graph's own `nodes` should be fine."""
    graph = _sample_graph()
    assert graph.node_count == 3
    assert graph.relation_count == 3


def test_knowledge_graph_rejects_unsorted_nodes() -> None:
    """Constructing a graph with nodes out of `identifier` order should raise."""
    a = KnowledgeNode(identifier="entity:b.py", kind=KnowledgeNodeKind.ENTITY, label="b.py")
    b = KnowledgeNode(identifier="entity:a.py", kind=KnowledgeNodeKind.ENTITY, label="a.py")
    with pytest.raises(ValidationError):
        KnowledgeGraph(nodes=(a, b))


def test_knowledge_graph_rejects_duplicate_identifiers() -> None:
    """Constructing a graph with two nodes sharing an `identifier` should raise."""
    a = KnowledgeNode(identifier="entity:a.py", kind=KnowledgeNodeKind.ENTITY, label="a.py")
    with pytest.raises(ValidationError):
        KnowledgeGraph(nodes=(a, a))


def test_knowledge_graph_rejects_unsorted_relations() -> None:
    """Constructing a graph with relations out of order should raise."""
    a = KnowledgeNode(identifier="entity:a.py", kind=KnowledgeNodeKind.ENTITY, label="a.py")
    b = KnowledgeNode(identifier="entity:b.py", kind=KnowledgeNodeKind.ENTITY, label="b.py")
    with pytest.raises(ValidationError):
        KnowledgeGraph(
            nodes=(a, b),
            relations=(
                KnowledgeRelation(
                    source="entity:b.py", target="entity:a.py", kind=KnowledgeRelationKind.DECLARES
                ),
                KnowledgeRelation(
                    source="entity:a.py", target="entity:b.py", kind=KnowledgeRelationKind.DECLARES
                ),
            ),
        )


def test_knowledge_graph_rejects_a_relation_from_an_unknown_source() -> None:
    """A relation whose `source` is absent from `nodes` should raise."""
    a = KnowledgeNode(identifier="entity:a.py", kind=KnowledgeNodeKind.ENTITY, label="a.py")
    with pytest.raises(ValidationError):
        KnowledgeGraph(
            nodes=(a,),
            relations=(
                KnowledgeRelation(
                    source="entity:unknown.py",
                    target="entity:a.py",
                    kind=KnowledgeRelationKind.DECLARES,
                ),
            ),
        )


def test_knowledge_graph_rejects_a_non_extends_relation_to_an_unknown_target() -> None:
    """A `DECLARES` relation whose `target` is absent from `nodes` should raise."""
    a = KnowledgeNode(identifier="entity:a.py", kind=KnowledgeNodeKind.ENTITY, label="a.py")
    with pytest.raises(ValidationError):
        KnowledgeGraph(
            nodes=(a,),
            relations=(
                KnowledgeRelation(
                    source="entity:a.py",
                    target="symbol:a.py::missing",
                    kind=KnowledgeRelationKind.DECLARES,
                ),
            ),
        )


def test_knowledge_graph_get_node_returns_the_matching_node() -> None:
    """`get_node` should return the node whose `identifier` matches."""
    graph = _sample_graph()
    assert graph.get_node("symbol:a.py::f").label == "f"


def test_knowledge_graph_get_node_raises_for_an_unknown_identifier() -> None:
    """`get_node` should raise `NotFoundError` for an identifier not present in the graph."""
    graph = _sample_graph()
    with pytest.raises(NotFoundError):
        graph.get_node("entity:does-not-exist")


def test_knowledge_graph_relations_from_filters_by_source() -> None:
    """`relations_from` should return only relations whose `source` matches."""
    graph = _sample_graph()
    targets = [relation.target for relation in graph.relations_from("entity:a.py")]
    assert targets == ["interface:a.py::Runnable", "symbol:a.py::f"]


def test_knowledge_graph_relations_from_empty_for_a_leaf() -> None:
    """`relations_from` should return an empty tuple for a node with no outgoing relations."""
    graph = _sample_graph()
    assert graph.relations_from("symbol:a.py::f") == ()


def test_knowledge_graph_to_mapping_is_json_safe() -> None:
    """`to_mapping` should render nodes and relations as plain dicts/lists."""
    mapping = _sample_graph().to_mapping()
    assert mapping["nodes"][0] == {
        "identifier": "entity:a.py",
        "kind": "entity",
        "label": "a.py",
        "relative_path": None,
        "attributes": [],
    }
    assert mapping["relations"][0] == {
        "source": "entity:a.py",
        "target": "interface:a.py::Runnable",
        "kind": "declares",
    }


def test_require_successful_symbol_extractions_rejects_a_failed_result() -> None:
    """`require_successful_symbol_extractions` should raise if any entry failed."""
    ok = SymbolExtractionResult.ok(relative_path="a.py")
    failed = SymbolExtractionResult.failed(relative_path="b.py", error_message="bad")
    with pytest.raises(ValidationError):
        require_successful_symbol_extractions((ok, failed))


def test_require_successful_symbol_extractions_returns_results_unchanged() -> None:
    """`require_successful_symbol_extractions` should pass all-successful results through."""
    results = (SymbolExtractionResult.ok(relative_path="a.py"),)
    assert require_successful_symbol_extractions(results) is results


def test_require_successful_pattern_extractions_rejects_a_failed_result() -> None:
    """`require_successful_pattern_extractions` should raise if any entry failed."""
    ok = PatternExtractionResult.ok(relative_path="a.py")
    failed = PatternExtractionResult.failed(relative_path="b.py", error_message="bad")
    with pytest.raises(ValidationError):
        require_successful_pattern_extractions((ok, failed))


def test_require_successful_interface_extractions_rejects_a_failed_result() -> None:
    """`require_successful_interface_extractions` should raise if any entry failed."""
    ok = InterfaceExtractionResult.ok(relative_path="a.py")
    failed = InterfaceExtractionResult.failed(relative_path="b.py", error_message="bad")
    with pytest.raises(ValidationError):
        require_successful_interface_extractions((ok, failed))


def test_require_successful_foundation_extractions_rejects_a_failed_result() -> None:
    """`require_successful_foundation_extractions` should raise if any entry failed."""
    ok = FoundationExtractionResult.ok(relative_path="a.py")
    failed = FoundationExtractionResult.failed(relative_path="b.py", error_message="bad")
    with pytest.raises(ValidationError):
        require_successful_foundation_extractions((ok, failed))
