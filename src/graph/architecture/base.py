"""Architecture graph Port: module/package containment graph representation.

`ArchitectureGraphBuilder` assembles many files' `extractors.architecture.base.PackageUnit`s
(each already describing *one file's own* package placement) into a single, repository-wide
`ArchitectureGraph` -- a connected containment tree of `PackageNode`s linked by
`PackageContainmentEdge`s. This is exactly the cross-file assembly step both
`extractors.architecture.base` and `analyzers.architecture.base` explicitly defer: "assembling
many files' units into a full package tree ... is a `graph` concern" and "requires a
repository-wide view, which is a `graph` concern (assembling many files' units into a tree)."

The graph is built from `PackageUnit` (the extractor-level DTO) rather than `analyzers.
architecture.base.ArchitectureAssessment` (the analyzer-level DTO), because `PackageUnit` alone
carries every file's own `declared_modules` and `is_package_root` in full; `ArchitectureAssessment`
already reduces `declared_modules` to a bare count and offers no further structural detail a
containment tree needs beyond what `PackageUnit` already provides.

This Port does not parse source code, extract package placement itself, or judge whether the
resulting tree is well-organized -- those are `parsers`, `extractors.architecture`, and
`analyzers.architecture`'s concerns respectively, each already built.
"""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from src.analyzers.architecture.base import (
    require_successful_extraction as _require_successful_architecture_extraction,
)
from src.core.exceptions import NotFoundError, ValidationError
from src.core.logging import get_logger
from src.extractors.architecture.base import ArchitectureExtractionResult

_logger = get_logger("graph.architecture")


@dataclass(frozen=True, slots=True)
class PackageNode:
    """A single package/namespace in a repository's architectural containment tree.

    Attributes:
        package_path: The package's own namespace path, as a tuple of directory segments (e.g.
            `("src", "extractors", "architecture")`), matching `extractors.architecture.base.
            PackageUnit.package_path` exactly -- carried through, not re-derived.
        file_paths: Paths of the files belonging directly to this package (not to any of its
            subpackages), deduplicated and lexicographically sorted so the result is
            deterministic regardless of input order.
        has_package_root_file: Whether any of `file_paths` is this package's own conventional
            root-marker file, carried through from `PackageUnit.is_package_root`.
    """

    package_path: tuple[str, ...]
    file_paths: tuple[str, ...] = ()
    has_package_root_file: bool = False

    def __post_init__(self) -> None:
        """Validate that `file_paths` is sorted and free of duplicates.

        Raises:
            ValidationError: If `file_paths` is not sorted or contains a duplicate.
        """
        if list(self.file_paths) != sorted(set(self.file_paths)):
            raise ValidationError("PackageNode: file_paths must be sorted and free of duplicates")

    @property
    def node_id(self) -> str:
        """Stable, deterministic identifier for this node, derived from `package_path`.

        Returns:
            `package_path`'s segments joined with `"/"` -- the empty string for the
            repository-root package (`package_path == ()`).
        """
        return "/".join(self.package_path)

    @property
    def depth(self) -> int:
        """Number of segments in `package_path`.

        Returns:
            How deeply nested this package is. `0` for the repository-root package.
        """
        return len(self.package_path)


@dataclass(frozen=True, slots=True)
class PackageContainmentEdge:
    """A single parent-to-child containment relationship between two `PackageNode`s.

    Attributes:
        parent_path: `package_path` of the containing package.
        child_path: `package_path` of the directly-contained package. Always exactly one
            segment longer than `parent_path`, and prefixed by it -- a `PackageContainmentEdge`
            only ever connects a package to an *immediate* child, never a distant descendant.
    """

    parent_path: tuple[str, ...]
    child_path: tuple[str, ...]

    def __post_init__(self) -> None:
        """Validate that `child_path` is an immediate child of `parent_path`.

        Raises:
            ValidationError: If `child_path` does not extend `parent_path` by exactly one
                segment.
        """
        is_immediate_child = (
            len(self.child_path) == len(self.parent_path) + 1
            and self.child_path[: len(self.parent_path)] == self.parent_path
        )
        if not is_immediate_child:
            raise ValidationError(
                "PackageContainmentEdge: child_path must be an immediate child of parent_path",
                details={"parent_path": self.parent_path, "child_path": self.child_path},
            )

    @property
    def parent_id(self) -> str:
        """Node id of the parent package, matching `PackageNode.node_id`."""
        return "/".join(self.parent_path)

    @property
    def child_id(self) -> str:
        """Node id of the child package, matching `PackageNode.node_id`."""
        return "/".join(self.child_path)


@dataclass(frozen=True, slots=True)
class ArchitectureGraph:
    """A repository's package/module containment tree, assembled from many files' `PackageUnit`s.

    Attributes:
        nodes: Every distinct package found -- plus any ancestor package implied by nesting, even
            one no file belongs to directly -- sorted by `package_path` so the result is
            deterministic regardless of input order.
        edges: Every immediate parent-child containment relationship between two `nodes`, sorted
            by `(parent_path, child_path)`. Each non-root package has at most one incoming edge
            (a package has exactly one immediate parent in a containment tree).
    """

    nodes: tuple[PackageNode, ...] = ()
    edges: tuple[PackageContainmentEdge, ...] = ()

    def __post_init__(self) -> None:
        """Validate that `nodes` and `edges` are sorted, unique, and internally consistent.

        Raises:
            ValidationError: If `nodes` is not sorted by `package_path`, contains a duplicate
                `package_path`, if `edges` is not sorted by `(parent_path, child_path)`, contains
                two edges with the same `child_path` (a package with two parents), or if any
                edge's `parent_path`/`child_path` is absent from `nodes`.
        """
        paths = [node.package_path for node in self.nodes]
        if paths != sorted(paths):
            raise ValidationError("ArchitectureGraph: nodes must be sorted by package_path")
        if len(set(paths)) != len(paths):
            raise ValidationError(
                "ArchitectureGraph: nodes must not contain duplicate package_path values"
            )

        edge_keys = [(edge.parent_path, edge.child_path) for edge in self.edges]
        if edge_keys != sorted(edge_keys):
            raise ValidationError(
                "ArchitectureGraph: edges must be sorted by (parent_path, child_path)"
            )
        child_paths = [edge.child_path for edge in self.edges]
        if len(set(child_paths)) != len(child_paths):
            raise ValidationError(
                "ArchitectureGraph: a package must not have more than one containment parent"
            )

        known_paths = set(paths)
        for edge in self.edges:
            if edge.parent_path not in known_paths or edge.child_path not in known_paths:
                raise ValidationError(
                    "ArchitectureGraph: edge references a package_path absent from nodes",
                    details={"parent_path": edge.parent_path, "child_path": edge.child_path},
                )

    @property
    def node_count(self) -> int:
        """Total number of packages in this graph."""
        return len(self.nodes)

    @property
    def edge_count(self) -> int:
        """Total number of containment relationships in this graph."""
        return len(self.edges)

    def get_node(self, node_id: str) -> PackageNode:
        """Retrieve a single package node by its `PackageNode.node_id`.

        Args:
            node_id: The `"/"`-joined package path to look up.

        Returns:
            The matching `PackageNode`.

        Raises:
            NotFoundError: If no node in this graph has that `node_id`.
        """
        for node in self.nodes:
            if node.node_id == node_id:
                return node
        raise NotFoundError(f"no package node with id '{node_id}' in this graph")

    def direct_children(self, node_id: str) -> tuple[PackageNode, ...]:
        """Retrieve every package directly contained by the package identified by `node_id`.

        Args:
            node_id: `PackageNode.node_id` of the candidate parent package.

        Returns:
            The `PackageNode`s connected to `node_id` by a `PackageContainmentEdge` as its
            child, in the same `package_path` order `nodes` is already sorted in.
        """
        child_ids = {edge.child_id for edge in self.edges if edge.parent_id == node_id}
        return tuple(node for node in self.nodes if node.node_id in child_ids)

    def to_mapping(self) -> dict[str, Any]:
        """Render this graph as a plain, JSON-safe nested structure.

        Returns:
            A dict with `"nodes"` and `"edges"` lists, each entry a dict of primitive values
            (paths rendered as lists of strings rather than tuples).
        """
        return {
            "nodes": [
                {
                    "node_id": node.node_id,
                    "package_path": list(node.package_path),
                    "file_paths": list(node.file_paths),
                    "has_package_root_file": node.has_package_root_file,
                }
                for node in self.nodes
            ],
            "edges": [
                {
                    "parent_id": edge.parent_id,
                    "child_id": edge.child_id,
                    "parent_path": list(edge.parent_path),
                    "child_path": list(edge.child_path),
                }
                for edge in self.edges
            ],
        }


class ArchitectureGraphBuilder(ABC):
    """Assembles many files' `PackageUnit`s into one repository-wide `ArchitectureGraph`.

    A concrete implementation decides how to walk a sequence of `ArchitectureExtractionResult`s
    and assemble their `PackageUnit`s into a connected containment tree; it does not judge
    whether the resulting structure is well-organized (see `analyzers.architecture`) and does not
    itself extract, parse, or collect anything -- all upstream concerns already handled by
    `src.extractors`, `src.parsers`, and `src.collectors`.
    """

    @abstractmethod
    def build(
        self, extraction_results: Sequence[ArchitectureExtractionResult]
    ) -> ArchitectureGraph:
        """Assemble an `ArchitectureGraph` from many files' architectural placements.

        Args:
            extraction_results: The outcomes of extracting architectural placement for every
                file under consideration, as produced by `src.extractors.architecture`. Every
                entry must be successful -- see `require_successful_extractions`.

        Returns:
            An `ArchitectureGraph` whose `nodes` cover every package observed across
            `extraction_results` -- plus every ancestor package implied by nesting, even one no
            file in `extraction_results` belongs to directly, so the tree is always connected
            back to the repository root (`package_path == ()`) -- and whose `edges` connect each
            package to its immediate parent. See `ancestor_package_paths`.

        Raises:
            ValidationError: If any entry in `extraction_results` is itself a failed extraction.
        """
        ...


def require_successful_extractions(
    extraction_results: Sequence[ArchitectureExtractionResult],
) -> Sequence[ArchitectureExtractionResult]:
    """Validate that every entry in `extraction_results` represents a successful extraction.

    Every `ArchitectureGraphBuilder.build` implementation calls this first, so a caller error (an
    `ArchitectureExtractionResult` with `succeeded=False` mixed into the sequence) is reported the
    same way -- as an immediate `ValidationError` -- across every implementation. The actual
    per-item check is delegated to `analyzers.architecture.base.require_successful_extraction`
    (the existing validator for this exact DTO, reused rather than redefined here), applied across
    a whole sequence rather than to a single result.

    Args:
        extraction_results: The raw `extraction_results` argument passed to `build`.

    Returns:
        `extraction_results`, unchanged.

    Raises:
        ValidationError: If any entry's `succeeded` is False.
    """
    for extraction_result in extraction_results:
        _require_successful_architecture_extraction(extraction_result)
    return extraction_results


def ancestor_package_paths(package_path: tuple[str, ...]) -> tuple[tuple[str, ...], ...]:
    """Derive every proper ancestor of `package_path`, from the repository root inward.

    Args:
        package_path: A package's own namespace path.

    Returns:
        Every proper prefix of `package_path`, starting with the empty tuple (the
        repository-root package) and ending with `package_path`'s immediate parent -- e.g. for
        `("src", "a", "b")`, returns `((), ("src",), ("src", "a"))`. Empty when `package_path`
        is itself `()` (the repository root has no ancestor).
    """
    return tuple(package_path[:i] for i in range(len(package_path)))
