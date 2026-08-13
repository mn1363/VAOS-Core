"""Dependency graph Port: file-level import/dependency graph representation.

`DependencyGraphBuilder` assembles many files' `extractors.imports.base.DependencyEdge`s (each
already describing *one file's own* import statements) into a single, repository-wide
`DependencyGraph` -- a directed graph of `DependencyNode`s (files and the modules they import)
linked by `DependencyRelationEdge`s. This is exactly the cross-file assembly step `analyzers.
dependency.base` explicitly defers: "assembling many files' profiles into a repository-wide
dependency graph (resolving imports to actual files, detecting cycles) is explicitly a `graph`
concern."

The graph is built from `DependencyEdge` (the extractor-level DTO, one entry per import
statement) rather than `analyzers.dependency.base.DependencyProfile` (the analyzer-level DTO),
because a `DependencyProfile` already collapses every file's edges down to aggregate counts and
a deduplicated `external_targets` tuple, discarding the per-edge, per-line detail -- and every
internal edge outright -- a graph needs to represent actual source-to-target relationships.

Resolving an internal edge's `target_module` to one of the other files present in the same build
call is this Port's job (not extraction or parsing): each `DependencyNode` and its `kind` records
the outcome plainly rather than guessing, distinguishing a resolved internal file from an
internal target this Port's input didn't happen to include (`UNRESOLVED_INTERNAL`) from a genuine
external dependency (`EXTERNAL_MODULE`). This Port does not parse source code, extract import
statements itself, or judge how healthy the resulting dependency structure is -- those are
`parsers`, `extractors.imports`, and `analyzers.dependency`'s concerns respectively, each already
built.
"""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum, auto
from typing import Any

from src.analyzers.dependency.base import (
    require_successful_extraction as _require_successful_import_extraction,
)
from src.core.exceptions import NotFoundError, ValidationError
from src.core.logging import get_logger
from src.extractors.imports.base import ImportExtractionResult

_logger = get_logger("graph.dependency")


class DependencyNodeKind(StrEnum):
    """The three ways a `DependencyNode` can relate to the files this graph was built from."""

    INTERNAL_FILE = auto()
    """One of the files this graph was built from -- present as a `source` of at least one
    `DependencyRelationEdge`, and possibly also as a `target`."""

    EXTERNAL_MODULE = auto()
    """A third-party or standard-library dependency target, never itself a `source`."""

    UNRESOLVED_INTERNAL = auto()
    """An import an extractor marked `is_internal=True`, whose `target_module` did not match any
    `INTERNAL_FILE` node among this graph's own inputs (e.g. the target file was not included in
    the build call, or the target module string could not be matched to a known file path)."""


@dataclass(frozen=True, slots=True)
class DependencyNode:
    """A single file or import target in a repository's dependency graph.

    Attributes:
        identifier: For `INTERNAL_FILE`, the file's `relative_path`. For `EXTERNAL_MODULE` and
            `UNRESOLVED_INTERNAL`, the raw `target_module` string an import referred to it by.
        kind: Which of the three `DependencyNodeKind`s this node represents.
    """

    identifier: str
    kind: DependencyNodeKind

    def __post_init__(self) -> None:
        """Validate that `identifier` is non-blank.

        Raises:
            ValidationError: If `identifier` is empty or whitespace-only.
        """
        if not self.identifier.strip():
            raise ValidationError("DependencyNode: identifier must not be empty")


@dataclass(frozen=True, slots=True)
class DependencyRelationEdge:
    """A single import relationship between two `DependencyNode`s.

    Attributes:
        source: `DependencyNode.identifier` of the importing file. Always an `INTERNAL_FILE`.
        target: `DependencyNode.identifier` of the node being imported.
        is_internal: Whether the extractor considered this import project-internal, carried
            through from `extractors.imports.base.DependencyEdge.is_internal`.
        imported_names: The specific names imported, carried through from `DependencyEdge.
            imported_names`. Empty for a whole-module import.
        alias: The local alias the import was bound to, if any, carried through from
            `DependencyEdge.alias`.
        line_number: The source line the import statement appeared on, or `0` if unknown.
    """

    source: str
    target: str
    is_internal: bool = False
    imported_names: tuple[str, ...] = ()
    alias: str | None = None
    line_number: int = 0

    def __post_init__(self) -> None:
        """Validate that `source` and `target` are both non-blank.

        Raises:
            ValidationError: If `source` or `target` is empty or whitespace-only.
        """
        if not self.source.strip():
            raise ValidationError("DependencyRelationEdge: source must not be empty")
        if not self.target.strip():
            raise ValidationError("DependencyRelationEdge: target must not be empty")


@dataclass(frozen=True, slots=True)
class DependencyGraph:
    """A repository's file-level dependency graph, assembled from many files' import edges.

    Attributes:
        nodes: Every file this graph was built from, plus every distinct import target
            (internal or external) any of them referred to, sorted by `identifier` so the
            result is deterministic regardless of input order.
        edges: Every import relationship between two `nodes`, sorted by `(source, target,
            line_number)`. Two edges may legitimately share a `(source, target)` pair (e.g. two
            separate `from x import a` / `from x import b` statements on different lines).
    """

    nodes: tuple[DependencyNode, ...] = ()
    edges: tuple[DependencyRelationEdge, ...] = ()

    def __post_init__(self) -> None:
        """Validate that `nodes` and `edges` are sorted, unique, and internally consistent.

        Raises:
            ValidationError: If `nodes` is not sorted by `identifier`, contains a duplicate
                `identifier`, if `edges` is not sorted by `(source, target, line_number)`, if any
                edge's `source`/`target` is absent from `nodes`, if an edge's `source` node is not
                `INTERNAL_FILE`, or if an edge's `is_internal` is inconsistent with its `target`
                node's `kind`.
        """
        identifiers = [node.identifier for node in self.nodes]
        if identifiers != sorted(identifiers):
            raise ValidationError("DependencyGraph: nodes must be sorted by identifier")
        if len(set(identifiers)) != len(identifiers):
            raise ValidationError("DependencyGraph: nodes must not contain duplicate identifiers")

        edge_keys = [(edge.source, edge.target, edge.line_number) for edge in self.edges]
        if edge_keys != sorted(edge_keys):
            raise ValidationError(
                "DependencyGraph: edges must be sorted by (source, target, line_number)"
            )

        nodes_by_id = {node.identifier: node for node in self.nodes}
        for edge in self.edges:
            source_node = nodes_by_id.get(edge.source)
            target_node = nodes_by_id.get(edge.target)
            if source_node is None or target_node is None:
                raise ValidationError(
                    "DependencyGraph: edge references an identifier absent from nodes",
                    details={"source": edge.source, "target": edge.target},
                )
            if source_node.kind is not DependencyNodeKind.INTERNAL_FILE:
                raise ValidationError(
                    "DependencyGraph: edge.source must be an INTERNAL_FILE node",
                    details={"source": edge.source, "source_kind": str(source_node.kind)},
                )
            expected_external = target_node.kind is DependencyNodeKind.EXTERNAL_MODULE
            if edge.is_internal == expected_external:
                raise ValidationError(
                    "DependencyGraph: edge.is_internal is inconsistent with target node kind",
                    details={
                        "target": edge.target,
                        "target_kind": str(target_node.kind),
                        "is_internal": edge.is_internal,
                    },
                )

    @property
    def node_count(self) -> int:
        """Total number of nodes (files and import targets) in this graph."""
        return len(self.nodes)

    @property
    def edge_count(self) -> int:
        """Total number of import relationships in this graph."""
        return len(self.edges)

    def get_node(self, identifier: str) -> DependencyNode:
        """Retrieve a single node by its `DependencyNode.identifier`.

        Args:
            identifier: The node identifier to look up.

        Returns:
            The matching `DependencyNode`.

        Raises:
            NotFoundError: If no node in this graph has that `identifier`.
        """
        for node in self.nodes:
            if node.identifier == identifier:
                return node
        raise NotFoundError(f"no dependency node with identifier '{identifier}' in this graph")

    def outgoing_edges(self, identifier: str) -> tuple[DependencyRelationEdge, ...]:
        """Retrieve every import relationship whose `source` is `identifier`.

        Args:
            identifier: `DependencyNode.identifier` of the importing file.

        Returns:
            Every `DependencyRelationEdge` with that `source`, in this graph's own `(source,
            target, line_number)` order.
        """
        return tuple(edge for edge in self.edges if edge.source == identifier)

    def to_mapping(self) -> dict[str, Any]:
        """Render this graph as a plain, JSON-safe nested structure.

        Returns:
            A dict with `"nodes"` and `"edges"` lists, each entry a dict of primitive values.
        """
        return {
            "nodes": [
                {"identifier": node.identifier, "kind": str(node.kind)} for node in self.nodes
            ],
            "edges": [
                {
                    "source": edge.source,
                    "target": edge.target,
                    "is_internal": edge.is_internal,
                    "imported_names": list(edge.imported_names),
                    "alias": edge.alias,
                    "line_number": edge.line_number,
                }
                for edge in self.edges
            ],
        }


class DependencyGraphBuilder(ABC):
    """Assembles many files' `DependencyEdge`s into one repository-wide `DependencyGraph`.

    A concrete implementation decides how to resolve each internal `DependencyEdge.target_module`
    against the `relative_path`s present in its own input, and how to detect and represent import
    cycles if it chooses to; it does not judge how healthy the resulting structure is (see
    `analyzers.dependency`) and does not itself extract, parse, or collect anything -- all
    upstream concerns already handled by `src.extractors`, `src.parsers`, and `src.collectors`.
    """

    @abstractmethod
    def build(self, extraction_results: Sequence[ImportExtractionResult]) -> DependencyGraph:
        """Assemble a `DependencyGraph` from many files' import statements.

        Args:
            extraction_results: The outcomes of extracting import statements for every file
                under consideration, as produced by `src.extractors.imports`. Every entry must
                be successful -- see `require_successful_extractions`.

        Returns:
            A `DependencyGraph` whose `nodes` cover every file in `extraction_results` plus
            every distinct import target any of them referred to, and whose `edges` mirror every
            `DependencyEdge` across every entry, translated into node identifiers.

        Raises:
            ValidationError: If any entry in `extraction_results` is itself a failed extraction.
        """
        ...


def require_successful_extractions(
    extraction_results: Sequence[ImportExtractionResult],
) -> Sequence[ImportExtractionResult]:
    """Validate that every entry in `extraction_results` represents a successful extraction.

    Every `DependencyGraphBuilder.build` implementation calls this first, so a caller error (an
    `ImportExtractionResult` with `succeeded=False` mixed into the sequence) is reported the same
    way -- as an immediate `ValidationError` -- across every implementation. The actual per-item
    check is delegated to `analyzers.dependency.base.require_successful_extraction` (the existing
    validator for this exact DTO, reused rather than redefined here), applied across a whole
    sequence rather than to a single result.

    Args:
        extraction_results: The raw `extraction_results` argument passed to `build`.

    Returns:
        `extraction_results`, unchanged.

    Raises:
        ValidationError: If any entry's `succeeded` is False.
    """
    for extraction_result in extraction_results:
        _require_successful_import_extraction(extraction_result)
    return extraction_results
