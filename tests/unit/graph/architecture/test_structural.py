"""Unit tests for `src.graph.architecture.structural`.

Every case below builds real `PackageUnit`/`ArchitectureExtractionResult` DTOs (no mocks) and
runs them through a `StructuralArchitectureGraphBuilder`. The builder's output is always a real
`ArchitectureGraph`, so its own `__post_init__` validators (sorted, unique, immediate-child,
single-parent, edges-reference-nodes) run on every graph these tests produce.
"""

from itertools import permutations

import pytest
from src.core.exceptions import ValidationError
from src.extractors.architecture.base import ArchitectureExtractionResult, PackageUnit
from src.graph.architecture.base import (
    ArchitectureGraph,
    ArchitectureGraphBuilder,
    PackageContainmentEdge,
    PackageNode,
)
from src.graph.architecture.structural import StructuralArchitectureGraphBuilder
from src.parsers.base import ParsedModule


def _unit(
    relative_path: str,
    package_path: tuple[str, ...],
    *,
    is_package_root: bool = False,
    declared_modules: tuple[ParsedModule, ...] = (),
) -> PackageUnit:
    """Build a `PackageUnit` directly, exactly as the caller specifies it."""
    return PackageUnit(
        relative_path=relative_path,
        package_path=package_path,
        is_package_root=is_package_root,
        declared_modules=declared_modules,
    )


def _ok(
    relative_path: str,
    package_path: tuple[str, ...],
    *,
    is_package_root: bool = False,
    declared_modules: tuple[ParsedModule, ...] = (),
) -> ArchitectureExtractionResult:
    """Build a successful `ArchitectureExtractionResult` whose own path matches its unit's."""
    unit = _unit(
        relative_path,
        package_path,
        is_package_root=is_package_root,
        declared_modules=declared_modules,
    )
    return ArchitectureExtractionResult.ok(relative_path=relative_path, unit=unit)


def _failed(relative_path: str = "broken.py") -> ArchitectureExtractionResult:
    """Build a failed `ArchitectureExtractionResult`."""
    return ArchitectureExtractionResult.failed(
        relative_path=relative_path, error_message="extraction failed"
    )


def _node_by_path(graph: ArchitectureGraph, package_path: tuple[str, ...]) -> PackageNode:
    """Return the single node with exactly `package_path`."""
    matches = [node for node in graph.nodes if node.package_path == package_path]
    assert len(matches) == 1
    return matches[0]


def _edge_pairs(graph: ArchitectureGraph) -> list[tuple[tuple[str, ...], tuple[str, ...]]]:
    """Render `graph.edges` as plain `(parent_path, child_path)` pairs."""
    return [(edge.parent_path, edge.child_path) for edge in graph.edges]


# --- construction and Port conformance -------------------------------------------------------


def test_builder_can_be_instantiated_with_no_arguments() -> None:
    """The concrete builder is zero-argument and carries no instance state."""
    builder = StructuralArchitectureGraphBuilder()
    assert vars(builder) == {}


def test_builder_is_an_architecture_graph_builder() -> None:
    """The concrete builder must satisfy the `ArchitectureGraphBuilder` Port."""
    assert isinstance(StructuralArchitectureGraphBuilder(), ArchitectureGraphBuilder)


# --- empty and root-level input --------------------------------------------------------------


def test_empty_input_returns_an_empty_graph() -> None:
    """No results means no nodes and no edges -- not even a synthesized root node."""
    graph = StructuralArchitectureGraphBuilder().build(())
    assert graph == ArchitectureGraph()
    assert graph.nodes == ()
    assert graph.edges == ()


def test_empty_list_input_returns_an_empty_graph() -> None:
    """Any empty `Sequence`, not just a tuple, yields the empty graph."""
    assert StructuralArchitectureGraphBuilder().build([]) == ArchitectureGraph()


def test_one_root_level_file_produces_only_the_root_node() -> None:
    """A root-level file belongs to the `()` node, and creates no edge."""
    graph = StructuralArchitectureGraphBuilder().build([_ok("a.py", ())])
    assert graph.nodes == (PackageNode(package_path=(), file_paths=("a.py",)),)
    assert graph.edges == ()


def test_root_level_package_root_file_creates_no_self_edge() -> None:
    """A package-root marker at the repository root flags the root node, with no edge."""
    graph = StructuralArchitectureGraphBuilder().build(
        [_ok("__init__.py", (), is_package_root=True)]
    )
    assert graph.nodes == (
        PackageNode(package_path=(), file_paths=("__init__.py",), has_package_root_file=True),
    )
    assert graph.edges == ()


# --- nesting and ancestor synthesis ----------------------------------------------------------


def test_one_nested_file_produces_the_root_and_the_leaf_package() -> None:
    """`src/a.py` yields the root ancestor, the `src` leaf node, and one edge between them."""
    graph = StructuralArchitectureGraphBuilder().build([_ok("src/a.py", ("src",))])
    assert graph.nodes == (
        PackageNode(package_path=()),
        PackageNode(package_path=("src",), file_paths=("src/a.py",)),
    )
    assert graph.edges == (PackageContainmentEdge(parent_path=(), child_path=("src",)),)


def test_deep_nesting_synthesizes_every_ancestor_and_one_edge_per_non_root_package() -> None:
    """`src/a/b/c.py` yields root, `src`, `src/a`, and the `src/a/b` leaf, chained by 3 edges."""
    graph = StructuralArchitectureGraphBuilder().build([_ok("src/a/b/c.py", ("src", "a", "b"))])
    assert [node.package_path for node in graph.nodes] == [
        (),
        ("src",),
        ("src", "a"),
        ("src", "a", "b"),
    ]
    assert _node_by_path(graph, ("src", "a", "b")).file_paths == ("src/a/b/c.py",)
    assert _edge_pairs(graph) == [
        ((), ("src",)),
        (("src",), ("src", "a")),
        (("src", "a"), ("src", "a", "b")),
    ]
    assert graph.edge_count == graph.node_count - 1


def test_ancestor_only_nodes_have_no_files_and_no_package_root_flag() -> None:
    """A package no unit belongs to directly is a valid node with empty membership."""
    graph = StructuralArchitectureGraphBuilder().build([_ok("src/a/b/c.py", ("src", "a", "b"))])
    for ancestor in ((), ("src",), ("src", "a")):
        node = _node_by_path(graph, ancestor)
        assert node.file_paths == ()
        assert node.has_package_root_file is False


def test_a_package_with_no_direct_file_sits_between_populated_packages() -> None:
    """`src/a` has no file of its own here, yet is a node connecting `src` and `src/a/b`."""
    graph = StructuralArchitectureGraphBuilder().build(
        [_ok("src/x.py", ("src",)), _ok("src/a/b/c.py", ("src", "a", "b"))]
    )
    assert _node_by_path(graph, ("src", "a")) == PackageNode(package_path=("src", "a"))
    assert _node_by_path(graph, ("src",)).file_paths == ("src/x.py",)
    assert _node_by_path(graph, ("src", "a", "b")).file_paths == ("src/a/b/c.py",)


def test_no_package_paths_beyond_observed_and_ancestors_are_synthesized() -> None:
    """Sibling directories that no unit mentions never appear as nodes."""
    graph = StructuralArchitectureGraphBuilder().build(
        [_ok("a/x.py", ("a",)), _ok("c/y.py", ("c",))]
    )
    assert [node.package_path for node in graph.nodes] == [(), ("a",), ("c",)]


# --- grouping, membership, and package-root propagation --------------------------------------


def test_multiple_files_in_one_package_are_grouped_into_one_node() -> None:
    """Units sharing a `package_path` produce a single node listing all their files."""
    graph = StructuralArchitectureGraphBuilder().build(
        [_ok("src/b.py", ("src",)), _ok("src/a.py", ("src",)), _ok("src/c.py", ("src",))]
    )
    src_nodes = [node for node in graph.nodes if node.package_path == ("src",)]
    assert len(src_nodes) == 1
    assert src_nodes[0].file_paths == ("src/a.py", "src/b.py", "src/c.py")


def test_file_paths_are_deduplicated_and_lexicographically_sorted() -> None:
    """Membership is `sorted(set(...))`, regardless of input order or repetition."""
    graph = StructuralArchitectureGraphBuilder().build(
        [
            _ok("src/z.py", ("src",)),
            _ok("src/a.py", ("src",)),
            _ok("src/z.py", ("src",)),
            _ok("src/m.py", ("src",)),
            _ok("src/a.py", ("src",)),
        ]
    )
    assert _node_by_path(graph, ("src",)).file_paths == ("src/a.py", "src/m.py", "src/z.py")


def test_duplicate_identical_results_collapse_to_one_membership_entry() -> None:
    """Two identical successful results are indistinguishable from one."""
    once = StructuralArchitectureGraphBuilder().build([_ok("src/a.py", ("src",))])
    twice = StructuralArchitectureGraphBuilder().build(
        [_ok("src/a.py", ("src",)), _ok("src/a.py", ("src",))]
    )
    assert twice == once


def test_package_root_flag_is_true_when_any_unit_in_the_package_is_a_root_file() -> None:
    """One `is_package_root` unit among several flags the whole package node."""
    graph = StructuralArchitectureGraphBuilder().build(
        [
            _ok("src/z.py", ("src",)),
            _ok("src/__init__.py", ("src",), is_package_root=True),
            _ok("src/a.py", ("src",)),
        ]
    )
    node = _node_by_path(graph, ("src",))
    assert node.has_package_root_file is True
    assert node.file_paths == ("src/__init__.py", "src/a.py", "src/z.py")


def test_package_root_flag_is_false_when_no_unit_in_the_package_is_a_root_file() -> None:
    """Without any `is_package_root` unit, the flag stays False."""
    graph = StructuralArchitectureGraphBuilder().build(
        [_ok("src/a.py", ("src",)), _ok("src/b.py", ("src",))]
    )
    assert _node_by_path(graph, ("src",)).has_package_root_file is False


def test_package_root_flag_does_not_leak_to_ancestors_or_siblings() -> None:
    """A marker in `src/a` flags `src/a` only -- not `src`, the root, or `src/b`."""
    graph = StructuralArchitectureGraphBuilder().build(
        [
            _ok("src/a/__init__.py", ("src", "a"), is_package_root=True),
            _ok("src/b/util.py", ("src", "b")),
        ]
    )
    flags = {node.package_path: node.has_package_root_file for node in graph.nodes}
    assert flags == {(): False, ("src",): False, ("src", "a"): True, ("src", "b"): False}


def test_file_membership_uses_the_unit_relative_path_not_the_result_relative_path() -> None:
    """`unit.relative_path` is the membership source; the result's own path is ignored."""
    result = ArchitectureExtractionResult.ok(
        relative_path="ignored/elsewhere.py",
        unit=_unit("src/a.py", ("src",)),
    )
    graph = StructuralArchitectureGraphBuilder().build([result])
    assert _node_by_path(graph, ("src",)).file_paths == ("src/a.py",)
    assert all("ignored/elsewhere.py" not in node.file_paths for node in graph.nodes)
    assert [node.package_path for node in graph.nodes] == [(), ("src",)]


def test_declared_modules_do_not_alter_the_graph() -> None:
    """`PackageUnit.declared_modules` has no representation in the graph."""
    declared = (ParsedModule(name="inner", line_number=3), ParsedModule(name="other"))
    without = StructuralArchitectureGraphBuilder().build([_ok("src/a.py", ("src",))])
    with_modules = StructuralArchitectureGraphBuilder().build(
        [_ok("src/a.py", ("src",), declared_modules=declared)]
    )
    assert with_modules == without
    assert [node.package_path for node in with_modules.nodes] == [(), ("src",)]


# --- ordering and determinism ----------------------------------------------------------------


def test_nodes_are_sorted_by_package_path_tuple_not_by_node_id_string() -> None:
    """`('a', 'b')` sorts before `('a-b',)` as a tuple, though `"a/b"` sorts after `"a-b"`."""
    graph = StructuralArchitectureGraphBuilder().build(
        [_ok("a-b/y.py", ("a-b",)), _ok("a/b/x.py", ("a", "b"))]
    )
    assert [node.package_path for node in graph.nodes] == [(), ("a",), ("a", "b"), ("a-b",)]
    node_ids = [node.node_id for node in graph.nodes]
    assert node_ids == ["", "a", "a/b", "a-b"]
    assert node_ids != sorted(node_ids)


def test_edges_are_sorted_by_parent_path_then_child_path() -> None:
    """Edges interleave by parent: `() -> ..` first, then `src -> ..`, ordered by child."""
    graph = StructuralArchitectureGraphBuilder().build(
        [
            _ok("web/s.ts", ("web",)),
            _ok("src/a/m.py", ("src", "a")),
            _ok("src/b/n.py", ("src", "b")),
            _ok("lib/l.py", ("lib",)),
        ]
    )
    assert _edge_pairs(graph) == [
        ((), ("lib",)),
        ((), ("src",)),
        ((), ("web",)),
        (("src",), ("src", "a")),
        (("src",), ("src", "b")),
    ]
    assert _edge_pairs(graph) == sorted(_edge_pairs(graph))


def test_every_non_root_node_has_exactly_one_incoming_edge_from_its_immediate_parent() -> None:
    """Each non-root package appears as `child_path` exactly once, under `package_path[:-1]`."""
    graph = StructuralArchitectureGraphBuilder().build(
        [_ok("a/b/c/x.py", ("a", "b", "c")), _ok("a/y.py", ("a",)), _ok("d/z.py", ("d",))]
    )
    non_root_paths = sorted(node.package_path for node in graph.nodes if node.package_path)
    assert sorted(edge.child_path for edge in graph.edges) == non_root_paths
    assert all(edge.parent_path == edge.child_path[:-1] for edge in graph.edges)


def test_reversing_input_order_produces_an_equal_graph() -> None:
    """Output is independent of input order."""
    results = [
        _ok("main.py", ()),
        _ok("src/__init__.py", ("src",), is_package_root=True),
        _ok("src/a/m.py", ("src", "a")),
        _ok("web/s.ts", ("web",)),
    ]
    builder = StructuralArchitectureGraphBuilder()
    assert builder.build(list(reversed(results))) == builder.build(results)


def test_every_input_permutation_produces_an_equal_graph() -> None:
    """Stronger determinism check: all orderings of a small mixed input agree."""
    results = [
        _ok("src/b.py", ("src",)),
        _ok("src/__init__.py", ("src",), is_package_root=True),
        _ok("src/a/c.py", ("src", "a")),
        _ok("top.py", ()),
    ]
    builder = StructuralArchitectureGraphBuilder()
    expected = builder.build(results)
    assert all(builder.build(list(order)) == expected for order in permutations(results))


def test_repeated_builds_by_one_instance_are_equal() -> None:
    """A builder holds no state between calls."""
    builder = StructuralArchitectureGraphBuilder()
    results = [_ok("src/a.py", ("src",)), _ok("src/b/c.py", ("src", "b"))]
    assert builder.build(results) == builder.build(results)


# --- representative full-graph outputs -------------------------------------------------------


def test_mixed_root_and_nested_packages_produce_the_exact_expected_graph() -> None:
    """Root file, a package-root marker, a nested package, and a sibling top-level package."""
    graph = StructuralArchitectureGraphBuilder().build(
        [
            _ok("main.py", ()),
            _ok("src/__init__.py", ("src",), is_package_root=True),
            _ok("src/a/m.py", ("src", "a")),
            _ok("web/s.ts", ("web",)),
        ]
    )
    assert graph == ArchitectureGraph(
        nodes=(
            PackageNode(package_path=(), file_paths=("main.py",)),
            PackageNode(
                package_path=("src",), file_paths=("src/__init__.py",), has_package_root_file=True
            ),
            PackageNode(package_path=("src", "a"), file_paths=("src/a/m.py",)),
            PackageNode(package_path=("web",), file_paths=("web/s.ts",)),
        ),
        edges=(
            PackageContainmentEdge(parent_path=(), child_path=("src",)),
            PackageContainmentEdge(parent_path=(), child_path=("web",)),
            PackageContainmentEdge(parent_path=("src",), child_path=("src", "a")),
        ),
    )


def test_package_root_marker_in_a_nested_package_produces_the_expected_graph() -> None:
    """`src/__init__.py` alone: root ancestor, flagged `src`, one edge."""
    graph = StructuralArchitectureGraphBuilder().build(
        [_ok("src/__init__.py", ("src",), is_package_root=True)]
    )
    assert graph == ArchitectureGraph(
        nodes=(
            PackageNode(package_path=()),
            PackageNode(
                package_path=("src",), file_paths=("src/__init__.py",), has_package_root_file=True
            ),
        ),
        edges=(PackageContainmentEdge(parent_path=(), child_path=("src",)),),
    )


def test_root_node_holds_root_files_and_still_has_children() -> None:
    """A repository with root-level files and a package: root node carries files and an edge."""
    graph = StructuralArchitectureGraphBuilder().build(
        [_ok("app.py", ()), _ok("pkg/x.py", ("pkg",))]
    )
    assert _node_by_path(graph, ()).file_paths == ("app.py",)
    assert _edge_pairs(graph) == [((), ("pkg",))]


# --- trust-verbatim behavior for synthetic, Port-level-only inputs ----------------------------


def test_same_file_under_different_packages_is_trusted_verbatim_and_does_not_raise() -> None:
    """A synthetic conflict is neither reconciled nor rejected: the file lists under both."""
    graph = StructuralArchitectureGraphBuilder().build(
        [_ok("a/x.py", ("a",)), _ok("a/x.py", ("b",))]
    )
    assert _node_by_path(graph, ("a",)).file_paths == ("a/x.py",)
    assert _node_by_path(graph, ("b",)).file_paths == ("a/x.py",)
    assert [node.package_path for node in graph.nodes] == [(), ("a",), ("b",)]


def test_package_path_is_trusted_even_when_it_disagrees_with_relative_path() -> None:
    """The builder never re-derives `package_path` from `relative_path`."""
    graph = StructuralArchitectureGraphBuilder().build([_ok("elsewhere/file.py", ("declared",))])
    assert _node_by_path(graph, ("declared",)).file_paths == ("elsewhere/file.py",)
    assert [node.package_path for node in graph.nodes] == [(), ("declared",)]


def test_path_separators_are_not_normalized() -> None:
    """Backslash-separated paths are trusted exactly as supplied, never split or rewritten."""
    graph = StructuralArchitectureGraphBuilder().build(
        [_ok("pkg\\sub\\util.py", ()), _ok("pkg\\__init__.py", ())]
    )
    assert graph.nodes == (
        PackageNode(package_path=(), file_paths=("pkg\\__init__.py", "pkg\\sub\\util.py")),
    )
    assert graph.edges == ()


# --- failure behavior ------------------------------------------------------------------------


def test_a_failed_extraction_mixed_into_successful_results_raises_validation_error() -> None:
    """One failed result anywhere in the sequence is rejected with the existing error type."""
    with pytest.raises(ValidationError):
        StructuralArchitectureGraphBuilder().build(
            [_ok("src/a.py", ("src",)), _failed("src/b.py"), _ok("src/c.py", ("src",))]
        )


def test_a_lone_failed_extraction_raises_validation_error() -> None:
    """A sequence consisting only of a failed result is rejected, not treated as empty."""
    with pytest.raises(ValidationError):
        StructuralArchitectureGraphBuilder().build([_failed()])


def test_a_failed_extraction_is_rejected_before_any_graph_is_assembled() -> None:
    """Rejection reports the failed file, and happens even if it is last in the sequence."""
    with pytest.raises(ValidationError) as exc_info:
        StructuralArchitectureGraphBuilder().build(
            [_ok("a.py", ()), _ok("src/b.py", ("src",)), _failed("last.py")]
        )
    assert exc_info.value.details["relative_path"] == "last.py"
