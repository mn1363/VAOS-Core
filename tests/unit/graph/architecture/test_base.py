"""Unit tests for `src.graph.architecture.base`."""

import pytest
from src.core.exceptions import NotFoundError, ValidationError
from src.extractors.architecture.base import ArchitectureExtractionResult, PackageUnit
from src.graph.architecture.base import (
    ArchitectureGraph,
    ArchitectureGraphBuilder,
    PackageContainmentEdge,
    PackageNode,
    ancestor_package_paths,
    require_successful_extractions,
)


def _successful_extraction(
    relative_path: str = "src/a.py", package_path: tuple[str, ...] = ("src",)
) -> ArchitectureExtractionResult:
    """Build a minimal, successful `ArchitectureExtractionResult` for use in graph tests."""
    unit = PackageUnit(relative_path=relative_path, package_path=package_path)
    return ArchitectureExtractionResult.ok(relative_path=relative_path, unit=unit)


def _failed_extraction(relative_path: str = "src/a.py") -> ArchitectureExtractionResult:
    """Build a minimal, failed `ArchitectureExtractionResult` for use in graph tests."""
    return ArchitectureExtractionResult.failed(relative_path=relative_path, error_message="bad")


def test_architecture_graph_builder_cannot_be_instantiated_directly() -> None:
    """The abstract `ArchitectureGraphBuilder` Port must not be instantiable."""
    with pytest.raises(TypeError):
        ArchitectureGraphBuilder()  # type: ignore[abstract]


def test_package_node_defaults() -> None:
    """`PackageNode` should default `file_paths` and `has_package_root_file` sensibly."""
    node = PackageNode(package_path=("src",))
    assert node.file_paths == ()
    assert node.has_package_root_file is False


def test_package_node_is_frozen() -> None:
    """`PackageNode` should be immutable once constructed."""
    node = PackageNode(package_path=("src",))
    with pytest.raises(AttributeError):
        node.package_path = ("other",)  # type: ignore[misc]


def test_package_node_node_id_joins_segments() -> None:
    """`node_id` should join `package_path` segments with `/`."""
    node = PackageNode(package_path=("src", "graph", "architecture"))
    assert node.node_id == "src/graph/architecture"


def test_package_node_node_id_for_repository_root() -> None:
    """`node_id` should be the empty string for the repository-root package."""
    node = PackageNode(package_path=())
    assert node.node_id == ""


def test_package_node_depth() -> None:
    """`depth` should equal the number of `package_path` segments."""
    assert PackageNode(package_path=()).depth == 0
    assert PackageNode(package_path=("src", "graph")).depth == 2


def test_package_node_rejects_unsorted_file_paths() -> None:
    """Constructing a node with unsorted `file_paths` should raise."""
    with pytest.raises(ValidationError):
        PackageNode(package_path=("src",), file_paths=("b.py", "a.py"))


def test_package_node_rejects_duplicate_file_paths() -> None:
    """Constructing a node with duplicate `file_paths` should raise."""
    with pytest.raises(ValidationError):
        PackageNode(package_path=("src",), file_paths=("a.py", "a.py"))


def test_package_containment_edge_accepts_an_immediate_child() -> None:
    """An edge whose child extends the parent by exactly one segment should construct cleanly."""
    edge = PackageContainmentEdge(parent_path=("src",), child_path=("src", "graph"))
    assert edge.parent_id == "src"
    assert edge.child_id == "src/graph"


def test_package_containment_edge_rejects_a_non_immediate_child() -> None:
    """An edge whose child is more than one segment past the parent should raise."""
    with pytest.raises(ValidationError):
        PackageContainmentEdge(parent_path=("src",), child_path=("src", "graph", "architecture"))


def test_package_containment_edge_rejects_a_mismatched_prefix() -> None:
    """An edge whose child does not extend the parent at all should raise."""
    with pytest.raises(ValidationError):
        PackageContainmentEdge(parent_path=("src",), child_path=("other", "graph"))


def test_package_containment_edge_rejects_a_shorter_child() -> None:
    """An edge whose child is not longer than the parent should raise."""
    with pytest.raises(ValidationError):
        PackageContainmentEdge(parent_path=("src", "graph"), child_path=("src",))


def test_architecture_graph_defaults_to_empty() -> None:
    """An `ArchitectureGraph` with no nodes or edges should construct cleanly."""
    graph = ArchitectureGraph()
    assert graph.node_count == 0
    assert graph.edge_count == 0


def _sample_graph() -> ArchitectureGraph:
    """Build a small, valid three-node `ArchitectureGraph` for reuse across tests."""
    root = PackageNode(package_path=())
    src = PackageNode(package_path=("src",))
    graph_pkg = PackageNode(package_path=("src", "graph"), file_paths=("src/graph/__init__.py",))
    return ArchitectureGraph(
        nodes=(root, src, graph_pkg),
        edges=(
            PackageContainmentEdge(parent_path=(), child_path=("src",)),
            PackageContainmentEdge(parent_path=("src",), child_path=("src", "graph")),
        ),
    )


def test_architecture_graph_accepts_a_valid_tree() -> None:
    """A well-formed, sorted tree of nodes and edges should construct cleanly."""
    graph = _sample_graph()
    assert graph.node_count == 3
    assert graph.edge_count == 2


def test_architecture_graph_rejects_unsorted_nodes() -> None:
    """Constructing a graph with nodes out of `package_path` order should raise."""
    with pytest.raises(ValidationError):
        ArchitectureGraph(
            nodes=(PackageNode(package_path=("src",)), PackageNode(package_path=()))
        )


def test_architecture_graph_rejects_duplicate_node_paths() -> None:
    """Constructing a graph with two nodes sharing a `package_path` should raise."""
    with pytest.raises(ValidationError):
        ArchitectureGraph(
            nodes=(PackageNode(package_path=("src",)), PackageNode(package_path=("src",)))
        )


def test_architecture_graph_rejects_unsorted_edges() -> None:
    """Constructing a graph with edges out of order should raise."""
    with pytest.raises(ValidationError):
        ArchitectureGraph(
            nodes=(
                PackageNode(package_path=()),
                PackageNode(package_path=("a",)),
                PackageNode(package_path=("b",)),
            ),
            edges=(
                PackageContainmentEdge(parent_path=(), child_path=("b",)),
                PackageContainmentEdge(parent_path=(), child_path=("a",)),
            ),
        )


def test_architecture_graph_rejects_a_package_with_two_parents() -> None:
    """Constructing a graph where a package has two containment parents should raise."""
    with pytest.raises(ValidationError):
        ArchitectureGraph(
            nodes=(
                PackageNode(package_path=()),
                PackageNode(package_path=("a",)),
                PackageNode(package_path=("a", "b")),
                PackageNode(package_path=("c",)),
            ),
            edges=(
                PackageContainmentEdge(parent_path=(), child_path=("a",)),
                PackageContainmentEdge(parent_path=(), child_path=("c",)),
                PackageContainmentEdge(parent_path=("c",), child_path=("a", "b")),
            ),
        )


def test_architecture_graph_rejects_an_edge_to_an_unknown_package() -> None:
    """Constructing a graph whose edge references a package absent from `nodes` should raise."""
    with pytest.raises(ValidationError):
        ArchitectureGraph(
            nodes=(PackageNode(package_path=()),),
            edges=(PackageContainmentEdge(parent_path=(), child_path=("src",)),),
        )


def test_architecture_graph_get_node_returns_the_matching_node() -> None:
    """`get_node` should return the node whose `node_id` matches."""
    graph = _sample_graph()
    assert graph.get_node("src/graph").package_path == ("src", "graph")


def test_architecture_graph_get_node_raises_for_an_unknown_id() -> None:
    """`get_node` should raise `NotFoundError` for an id not present in the graph."""
    graph = _sample_graph()
    with pytest.raises(NotFoundError):
        graph.get_node("does/not/exist")


def test_architecture_graph_direct_children_returns_immediate_children_only() -> None:
    """`direct_children` should return only the immediate children of a node."""
    graph = _sample_graph()
    children = graph.direct_children("")
    assert [child.node_id for child in children] == ["src"]


def test_architecture_graph_direct_children_empty_for_a_leaf() -> None:
    """`direct_children` should return an empty tuple for a package with no children."""
    graph = _sample_graph()
    assert graph.direct_children("src/graph") == ()


def test_architecture_graph_to_mapping_is_json_safe() -> None:
    """`to_mapping` should render nodes and edges as plain dicts/lists."""
    mapping = _sample_graph().to_mapping()
    assert mapping["nodes"][1] == {
        "node_id": "src",
        "package_path": ["src"],
        "file_paths": [],
        "has_package_root_file": False,
    }
    assert mapping["edges"][0] == {
        "parent_id": "",
        "child_id": "src",
        "parent_path": [],
        "child_path": ["src"],
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


def test_ancestor_package_paths_for_a_nested_package() -> None:
    """`ancestor_package_paths` should list every proper prefix from the root inward."""
    assert ancestor_package_paths(("src", "a", "b")) == ((), ("src",), ("src", "a"))


def test_ancestor_package_paths_for_the_repository_root() -> None:
    """`ancestor_package_paths` should be empty for the repository root itself."""
    assert ancestor_package_paths(()) == ()


def test_ancestor_package_paths_for_a_top_level_package() -> None:
    """`ancestor_package_paths` should return just the root for a single-segment package."""
    assert ancestor_package_paths(("src",)) == ((),)
