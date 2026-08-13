"""Unit tests for `src.graph.dependency.base`."""

import pytest
from src.core.exceptions import NotFoundError, ValidationError
from src.extractors.imports.base import DependencyEdge, ImportExtractionResult
from src.graph.dependency.base import (
    DependencyGraph,
    DependencyGraphBuilder,
    DependencyNode,
    DependencyNodeKind,
    DependencyRelationEdge,
    require_successful_extractions,
)


def _successful_extraction(relative_path: str = "a.py") -> ImportExtractionResult:
    """Build a minimal, successful `ImportExtractionResult` for use in graph tests."""
    return ImportExtractionResult.ok(
        relative_path=relative_path,
        edges=(DependencyEdge(source_path=relative_path, target_module="os", is_internal=False),),
    )


def _failed_extraction(relative_path: str = "a.py") -> ImportExtractionResult:
    """Build a minimal, failed `ImportExtractionResult` for use in graph tests."""
    return ImportExtractionResult.failed(relative_path=relative_path, error_message="bad")


def test_dependency_graph_builder_cannot_be_instantiated_directly() -> None:
    """The abstract `DependencyGraphBuilder` Port must not be instantiable."""
    with pytest.raises(TypeError):
        DependencyGraphBuilder()  # type: ignore[abstract]


def test_dependency_node_rejects_an_empty_identifier() -> None:
    """Constructing a node with a blank identifier should raise."""
    with pytest.raises(ValidationError):
        DependencyNode(identifier="   ", kind=DependencyNodeKind.INTERNAL_FILE)


def test_dependency_node_is_frozen() -> None:
    """`DependencyNode` should be immutable once constructed."""
    node = DependencyNode(identifier="a.py", kind=DependencyNodeKind.INTERNAL_FILE)
    with pytest.raises(AttributeError):
        node.identifier = "b.py"  # type: ignore[misc]


def test_dependency_relation_edge_defaults() -> None:
    """`DependencyRelationEdge` should default optional fields sensibly."""
    edge = DependencyRelationEdge(source="a.py", target="os")
    assert edge.is_internal is False
    assert edge.imported_names == ()
    assert edge.alias is None
    assert edge.line_number == 0


def test_dependency_relation_edge_rejects_an_empty_source() -> None:
    """Constructing an edge with a blank source should raise."""
    with pytest.raises(ValidationError):
        DependencyRelationEdge(source="  ", target="os")


def test_dependency_relation_edge_rejects_an_empty_target() -> None:
    """Constructing an edge with a blank target should raise."""
    with pytest.raises(ValidationError):
        DependencyRelationEdge(source="a.py", target=" ")


def _sample_graph() -> DependencyGraph:
    """Build a small, valid `DependencyGraph` mixing internal, external, and unresolved edges."""
    a = DependencyNode(identifier="a.py", kind=DependencyNodeKind.INTERNAL_FILE)
    b = DependencyNode(identifier="b.py", kind=DependencyNodeKind.INTERNAL_FILE)
    os_module = DependencyNode(identifier="os", kind=DependencyNodeKind.EXTERNAL_MODULE)
    unresolved = DependencyNode(
        identifier="pkg.missing", kind=DependencyNodeKind.UNRESOLVED_INTERNAL
    )
    return DependencyGraph(
        nodes=(a, b, os_module, unresolved),
        edges=(
            DependencyRelationEdge(source="a.py", target="b.py", is_internal=True, line_number=1),
            DependencyRelationEdge(source="a.py", target="os", is_internal=False, line_number=2),
            DependencyRelationEdge(
                source="a.py", target="pkg.missing", is_internal=True, line_number=3
            ),
        ),
    )


def test_dependency_graph_accepts_a_valid_mix_of_edge_kinds() -> None:
    """A graph mixing internal, external, and unresolved-internal edges should construct."""
    graph = _sample_graph()
    assert graph.node_count == 4
    assert graph.edge_count == 3


def test_dependency_graph_rejects_unsorted_nodes() -> None:
    """Constructing a graph with nodes out of identifier order should raise."""
    with pytest.raises(ValidationError):
        DependencyGraph(
            nodes=(
                DependencyNode(identifier="b.py", kind=DependencyNodeKind.INTERNAL_FILE),
                DependencyNode(identifier="a.py", kind=DependencyNodeKind.INTERNAL_FILE),
            )
        )


def test_dependency_graph_rejects_duplicate_identifiers() -> None:
    """Constructing a graph with two nodes sharing an identifier should raise."""
    with pytest.raises(ValidationError):
        DependencyGraph(
            nodes=(
                DependencyNode(identifier="a.py", kind=DependencyNodeKind.INTERNAL_FILE),
                DependencyNode(identifier="a.py", kind=DependencyNodeKind.INTERNAL_FILE),
            )
        )


def test_dependency_graph_rejects_unsorted_edges() -> None:
    """Constructing a graph with edges out of order should raise."""
    a = DependencyNode(identifier="a.py", kind=DependencyNodeKind.INTERNAL_FILE)
    b = DependencyNode(identifier="b.py", kind=DependencyNodeKind.INTERNAL_FILE)
    with pytest.raises(ValidationError):
        DependencyGraph(
            nodes=(a, b),
            edges=(
                DependencyRelationEdge(source="b.py", target="a.py", is_internal=True),
                DependencyRelationEdge(source="a.py", target="b.py", is_internal=True),
            ),
        )


def test_dependency_graph_rejects_an_edge_to_an_unknown_node() -> None:
    """Constructing a graph whose edge references a node absent from `nodes` should raise."""
    a = DependencyNode(identifier="a.py", kind=DependencyNodeKind.INTERNAL_FILE)
    with pytest.raises(ValidationError):
        DependencyGraph(
            nodes=(a,), edges=(DependencyRelationEdge(source="a.py", target="b.py"),)
        )


def test_dependency_graph_rejects_an_edge_whose_source_is_not_a_file() -> None:
    """Constructing a graph whose edge originates from a non-`INTERNAL_FILE` node should raise."""
    os_module = DependencyNode(identifier="os", kind=DependencyNodeKind.EXTERNAL_MODULE)
    sys_module = DependencyNode(identifier="sys", kind=DependencyNodeKind.EXTERNAL_MODULE)
    with pytest.raises(ValidationError):
        DependencyGraph(
            nodes=(os_module, sys_module),
            edges=(DependencyRelationEdge(source="os", target="sys", is_internal=False),),
        )


def test_dependency_graph_rejects_is_internal_true_targeting_an_external_module() -> None:
    """An edge marked internal but targeting an `EXTERNAL_MODULE` node should raise."""
    a = DependencyNode(identifier="a.py", kind=DependencyNodeKind.INTERNAL_FILE)
    os_module = DependencyNode(identifier="os", kind=DependencyNodeKind.EXTERNAL_MODULE)
    with pytest.raises(ValidationError):
        DependencyGraph(
            nodes=(a, os_module),
            edges=(DependencyRelationEdge(source="a.py", target="os", is_internal=True),),
        )


def test_dependency_graph_rejects_is_internal_false_targeting_an_internal_file() -> None:
    """An edge marked external but targeting an `INTERNAL_FILE` node should raise."""
    a = DependencyNode(identifier="a.py", kind=DependencyNodeKind.INTERNAL_FILE)
    b = DependencyNode(identifier="b.py", kind=DependencyNodeKind.INTERNAL_FILE)
    with pytest.raises(ValidationError):
        DependencyGraph(
            nodes=(a, b),
            edges=(DependencyRelationEdge(source="a.py", target="b.py", is_internal=False),),
        )


def test_dependency_graph_get_node_returns_the_matching_node() -> None:
    """`get_node` should return the node whose `identifier` matches."""
    graph = _sample_graph()
    assert graph.get_node("os").kind is DependencyNodeKind.EXTERNAL_MODULE


def test_dependency_graph_get_node_raises_for_an_unknown_identifier() -> None:
    """`get_node` should raise `NotFoundError` for an identifier not present in the graph."""
    graph = _sample_graph()
    with pytest.raises(NotFoundError):
        graph.get_node("does-not-exist")


def test_dependency_graph_outgoing_edges_filters_by_source() -> None:
    """`outgoing_edges` should return only edges whose `source` matches."""
    graph = _sample_graph()
    targets = [edge.target for edge in graph.outgoing_edges("a.py")]
    assert targets == ["b.py", "os", "pkg.missing"]


def test_dependency_graph_outgoing_edges_empty_for_a_leaf() -> None:
    """`outgoing_edges` should return an empty tuple for a node with no outgoing edges."""
    graph = _sample_graph()
    assert graph.outgoing_edges("b.py") == ()


def test_dependency_graph_to_mapping_is_json_safe() -> None:
    """`to_mapping` should render nodes and edges as plain dicts/lists."""
    mapping = _sample_graph().to_mapping()
    assert mapping["nodes"][0] == {"identifier": "a.py", "kind": "internal_file"}
    assert mapping["edges"][0] == {
        "source": "a.py",
        "target": "b.py",
        "is_internal": True,
        "imported_names": [],
        "alias": None,
        "line_number": 1,
    }


def test_require_successful_extractions_returns_results_unchanged() -> None:
    """`require_successful_extractions` should pass all-successful results through unchanged."""
    results = (_successful_extraction("a.py"), _successful_extraction("b.py"))
    assert require_successful_extractions(results) is results


def test_require_successful_extractions_rejects_any_failed_result() -> None:
    """`require_successful_extractions` should raise if any entry failed."""
    results = (_successful_extraction("a.py"), _failed_extraction("b.py"))
    with pytest.raises(ValidationError):
        require_successful_extractions(results)
