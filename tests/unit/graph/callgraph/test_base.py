"""Unit tests for `src.graph.callgraph.base`."""

import pytest
from src.core.exceptions import NotFoundError, ValidationError
from src.extractors.symbols.base import ExtractedSymbolKind, SymbolExtractionResult
from src.graph.callgraph.base import (
    CallableNode,
    CallEdge,
    CallGraph,
    CallGraphBuilder,
    is_callable_symbol_kind,
    require_successful_extractions,
)


def _successful_extraction(relative_path: str = "a.py") -> SymbolExtractionResult:
    """Build a minimal, successful `SymbolExtractionResult` for use in graph tests."""
    return SymbolExtractionResult.ok(relative_path=relative_path, symbols=())


def _failed_extraction(relative_path: str = "a.py") -> SymbolExtractionResult:
    """Build a minimal, failed `SymbolExtractionResult` for use in graph tests."""
    return SymbolExtractionResult.failed(relative_path=relative_path, error_message="bad")


def test_call_graph_builder_cannot_be_instantiated_directly() -> None:
    """The abstract `CallGraphBuilder` Port must not be instantiable."""
    with pytest.raises(TypeError):
        CallGraphBuilder()  # type: ignore[abstract]


@pytest.mark.parametrize("kind", [ExtractedSymbolKind.FUNCTION, ExtractedSymbolKind.METHOD])
def test_callable_node_accepts_function_and_method_kinds(kind: ExtractedSymbolKind) -> None:
    """A `CallableNode` should accept `FUNCTION` and `METHOD` kinds."""
    node = CallableNode(qualified_name="a.py::f", name="f", kind=kind, relative_path="a.py")
    assert node.kind is kind


@pytest.mark.parametrize("kind", [ExtractedSymbolKind.CLASS, ExtractedSymbolKind.CONSTANT])
def test_callable_node_rejects_non_callable_kinds(kind: ExtractedSymbolKind) -> None:
    """A `CallableNode` should reject `CLASS` and `CONSTANT` kinds."""
    with pytest.raises(ValidationError):
        CallableNode(qualified_name="a.py::X", name="X", kind=kind, relative_path="a.py")


def test_call_edge_defaults() -> None:
    """`CallEdge` should default `line_number` to 0."""
    edge = CallEdge(caller="a.py::f", callee="a.py::g")
    assert edge.line_number == 0


def test_call_edge_rejects_an_empty_caller() -> None:
    """Constructing an edge with a blank caller should raise."""
    with pytest.raises(ValidationError):
        CallEdge(caller="  ", callee="a.py::g")


def test_call_edge_rejects_an_empty_callee() -> None:
    """Constructing an edge with a blank callee should raise."""
    with pytest.raises(ValidationError):
        CallEdge(caller="a.py::f", callee=" ")


def _sample_graph() -> CallGraph:
    """Build a small, valid `CallGraph` with one known and one external callee."""
    f = CallableNode(
        qualified_name="a.py::f", name="f", kind=ExtractedSymbolKind.FUNCTION, relative_path="a.py"
    )
    g = CallableNode(
        qualified_name="a.py::g", name="g", kind=ExtractedSymbolKind.FUNCTION, relative_path="a.py"
    )
    return CallGraph(
        nodes=(f, g),
        edges=(
            CallEdge(caller="a.py::f", callee="a.py::g", line_number=5),
            CallEdge(caller="a.py::f", callee="external.module::h", line_number=6),
        ),
    )


def test_call_graph_accepts_an_edge_to_an_unknown_external_callee() -> None:
    """A `CallGraph` should accept an edge whose `callee` is not one of its own `nodes`."""
    graph = _sample_graph()
    assert graph.node_count == 2
    assert graph.edge_count == 2


def test_call_graph_rejects_unsorted_nodes() -> None:
    """Constructing a graph with nodes out of `qualified_name` order should raise."""
    f = CallableNode(
        qualified_name="a.py::g", name="g", kind=ExtractedSymbolKind.FUNCTION, relative_path="a.py"
    )
    g = CallableNode(
        qualified_name="a.py::f", name="f", kind=ExtractedSymbolKind.FUNCTION, relative_path="a.py"
    )
    with pytest.raises(ValidationError):
        CallGraph(nodes=(f, g))


def test_call_graph_rejects_duplicate_qualified_names() -> None:
    """Constructing a graph with two nodes sharing a `qualified_name` should raise."""
    f = CallableNode(
        qualified_name="a.py::f", name="f", kind=ExtractedSymbolKind.FUNCTION, relative_path="a.py"
    )
    with pytest.raises(ValidationError):
        CallGraph(nodes=(f, f))


def test_call_graph_rejects_unsorted_edges() -> None:
    """Constructing a graph with edges out of order should raise."""
    f = CallableNode(
        qualified_name="a.py::f", name="f", kind=ExtractedSymbolKind.FUNCTION, relative_path="a.py"
    )
    with pytest.raises(ValidationError):
        CallGraph(
            nodes=(f,),
            edges=(
                CallEdge(caller="a.py::f", callee="z"),
                CallEdge(caller="a.py::f", callee="a"),
            ),
        )


def test_call_graph_rejects_an_edge_whose_caller_is_unknown() -> None:
    """An edge whose `caller` is not a node in this graph should raise."""
    f = CallableNode(
        qualified_name="a.py::f", name="f", kind=ExtractedSymbolKind.FUNCTION, relative_path="a.py"
    )
    with pytest.raises(ValidationError):
        CallGraph(nodes=(f,), edges=(CallEdge(caller="a.py::unknown", callee="a.py::f"),))


def test_call_graph_get_node_returns_the_matching_node() -> None:
    """`get_node` should return the node whose `qualified_name` matches."""
    graph = _sample_graph()
    assert graph.get_node("a.py::g").name == "g"


def test_call_graph_get_node_raises_for_an_unknown_qualified_name() -> None:
    """`get_node` should raise `NotFoundError` for a name not present in the graph."""
    graph = _sample_graph()
    with pytest.raises(NotFoundError):
        graph.get_node("does-not-exist")


def test_call_graph_callees_of_filters_by_caller() -> None:
    """`callees_of` should return only edges whose `caller` matches."""
    graph = _sample_graph()
    callees = [edge.callee for edge in graph.callees_of("a.py::f")]
    assert callees == ["a.py::g", "external.module::h"]


def test_call_graph_callees_of_empty_for_a_leaf() -> None:
    """`callees_of` should return an empty tuple for a callable that makes no known calls."""
    graph = _sample_graph()
    assert graph.callees_of("a.py::g") == ()


def test_call_graph_to_mapping_is_json_safe() -> None:
    """`to_mapping` should render nodes and edges as plain dicts/lists."""
    mapping = _sample_graph().to_mapping()
    assert mapping["nodes"][0] == {
        "qualified_name": "a.py::f",
        "name": "f",
        "kind": "function",
        "relative_path": "a.py",
        "line_number": 0,
    }
    assert mapping["edges"][0] == {"caller": "a.py::f", "callee": "a.py::g", "line_number": 5}


def test_require_successful_extractions_returns_results_unchanged() -> None:
    """`require_successful_extractions` should pass all-successful results through unchanged."""
    results = (_successful_extraction("a.py"), _successful_extraction("b.py"))
    assert require_successful_extractions(results) is results


def test_require_successful_extractions_rejects_any_failed_result() -> None:
    """`require_successful_extractions` should raise if any entry failed."""
    results = (_successful_extraction("a.py"), _failed_extraction("b.py"))
    with pytest.raises(ValidationError):
        require_successful_extractions(results)


def test_is_callable_symbol_kind_true_for_function_and_method() -> None:
    """`is_callable_symbol_kind` should be True for `FUNCTION` and `METHOD`."""
    assert is_callable_symbol_kind(ExtractedSymbolKind.FUNCTION) is True
    assert is_callable_symbol_kind(ExtractedSymbolKind.METHOD) is True


def test_is_callable_symbol_kind_false_for_class_and_constant() -> None:
    """`is_callable_symbol_kind` should be False for `CLASS` and `CONSTANT`."""
    assert is_callable_symbol_kind(ExtractedSymbolKind.CLASS) is False
    assert is_callable_symbol_kind(ExtractedSymbolKind.CONSTANT) is False
