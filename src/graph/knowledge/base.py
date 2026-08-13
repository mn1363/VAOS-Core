"""Knowledge graph Port: semantic relationship graph representation.

`KnowledgeGraphBuilder` assembles many files' already-extracted symbols, patterns, interfaces,
and foundation candidates -- plus, optionally, an already-built `graph.architecture.base.
ArchitectureGraph` -- into a single `KnowledgeGraph`: a typed, semantic graph connecting
repository entities (files) to the capabilities, patterns, interfaces, and other domain concepts
recognized within them, and to the packages they belong to.

Unlike `graph.architecture` and `graph.dependency`, which each assemble one extractor's output
into one topology, the knowledge graph is deliberately the widest-scoped of the four: it draws on
every extractor contract whose output names a reusable domain concept --
`extractors.symbols` (classes/functions/methods/constants), `extractors.patterns` (recognized
code patterns), `extractors.interfaces` (interface-shaped declarations), and
`extractors.foundation` (raw reuse-candidacy signals) -- and reuses `graph.architecture.base.
PackageNode` rather than redefining a second notion of "package" for the same repository. This
is the one place in `src.graph` sibling subpackages import from one another, a deliberate,
narrow loosening of the strict sibling-isolation every prior `extractors`/`analyzers` phase
observed.

`src.analyzers` is an allowed import for this whole package but is deliberately unused here, for
the same reason `graph.architecture`/`graph.dependency` prefer the extractor-level DTOs over
their analyzer-level counterparts: every analyzer DTO these four extractors feed
(`ArchitectureAssessment`, `DependencyProfile`, quality/security/test indicators, ...) is already
an aggregated *judgment* about one file, not additional *structural* detail a graph needs -- see
each analyzer base module's own docstring for what it adds instead. `src.domain` is likewise
allowed but unused: every node here is keyed by the same path/qualified-name strings the
extractor layer already uses, rather than the domain layer's UUID-keyed entities, so every
`KnowledgeNode.identifier` stays consistent with `graph.architecture`/`graph.dependency`/
`graph.callgraph`'s own identifier schemes without introducing a second kind of key.

This Port does not parse source code, extract any of the four concepts above itself, or score,
select, or rank any of them -- those are `parsers`/`extractors.*` concerns (already built) or
`foundation`'s concern (a later, not-yet-built phase).
"""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum, auto
from typing import Any

from src.core.exceptions import NotFoundError, ValidationError
from src.core.logging import get_logger
from src.extractors.foundation.base import FoundationExtractionResult
from src.extractors.interfaces.base import InterfaceExtractionResult
from src.extractors.patterns.base import PatternExtractionResult
from src.extractors.symbols.base import SymbolExtractionResult, build_qualified_name
from src.graph.architecture.base import ArchitectureGraph, PackageNode

_logger = get_logger("graph.knowledge")


class KnowledgeNodeKind(StrEnum):
    """The kinds of domain concept a `KnowledgeNode` can represent."""

    ENTITY = auto()
    """A source file -- the repository-entity anchor every other kind relates back to."""

    PACKAGE = auto()
    """A package/namespace, mirroring `graph.architecture.base.PackageNode` rather than
    redefining it."""

    SYMBOL = auto()
    """A class, function, method, or constant (`extractors.symbols.base.ExtractedSymbol`)."""

    CAPABILITY = auto()
    """A raw reuse-candidacy signal set (`extractors.foundation.base.FoundationCandidate`)."""

    PATTERN = auto()
    """A recognized code pattern (`extractors.patterns.base.ExtractedPattern`)."""

    INTERFACE = auto()
    """An interface-shaped declaration (`extractors.interfaces.base.ExtractedInterface`)."""


class KnowledgeRelationKind(StrEnum):
    """The kinds of semantic relationship a `KnowledgeRelation` can represent."""

    DECLARES = auto()
    """An `ENTITY` declares a `SYMBOL`/`CAPABILITY`/`PATTERN`/`INTERFACE` found within it."""

    BELONGS_TO_PACKAGE = auto()
    """An `ENTITY` belongs to a `PACKAGE`."""

    EXTENDS = auto()
    """An `INTERFACE` extends a base interface, from `ExtractedInterface.base_interfaces`. The
    base interface's own node may or may not be present in the same graph -- see
    `KnowledgeGraph.__post_init__`."""


def _node_id(kind: KnowledgeNodeKind, raw_identifier: str) -> str:
    """Build a `KnowledgeNode.identifier`, namespaced by kind to guarantee global uniqueness.

    Args:
        kind: The node kind `raw_identifier` belongs to.
        raw_identifier: A kind-scoped identifier (a `relative_path`, a `build_qualified_name`
            result, or a `PackageNode.node_id`) that is only unique *within* its own kind.

    Returns:
        `raw_identifier` prefixed with `kind`'s value and a colon (e.g.
        `"symbol:src/a.py::Foo.bar"`), unique across every `KnowledgeNodeKind`.
    """
    return f"{kind.value}:{raw_identifier}"


@dataclass(frozen=True, slots=True)
class KnowledgeNode:
    """A single domain concept in a repository's knowledge graph.

    Attributes:
        identifier: This node's globally-unique id -- see `_node_id`.
        kind: Which kind of domain concept this node represents.
        label: Human-readable display name (e.g. a symbol's unqualified name, a pattern's name).
        relative_path: Path of the owning file, when this concept belongs to one. None for
            `PACKAGE` nodes, which span potentially many files.
        attributes: Freeform, human-readable supporting details, carried through from whichever
            extractor DTO this node was derived from (e.g. `ExtractedPattern.evidence`,
            `FoundationCandidate.signals`).
    """

    identifier: str
    kind: KnowledgeNodeKind
    label: str
    relative_path: str | None = None
    attributes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Validate that `identifier` is properly namespaced for `kind`.

        Raises:
            ValidationError: If `identifier` does not start with `kind`'s own `_node_id` prefix.
        """
        if not self.identifier.startswith(f"{self.kind.value}:"):
            raise ValidationError(
                "KnowledgeNode: identifier must be namespaced by its own kind",
                details={"identifier": self.identifier, "kind": str(self.kind)},
            )


@dataclass(frozen=True, slots=True)
class KnowledgeRelation:
    """A single semantic relationship between two `KnowledgeNode`s.

    Attributes:
        source: `KnowledgeNode.identifier` this relationship originates from. Must reference a
            node present in the same `KnowledgeGraph`.
        target: `KnowledgeNode.identifier` this relationship points to. Must reference a node
            present in the same `KnowledgeGraph`, except when `kind` is `EXTENDS` -- see
            `KnowledgeGraph.__post_init__`.
        kind: Which kind of semantic relationship this is.
    """

    source: str
    target: str
    kind: KnowledgeRelationKind

    def __post_init__(self) -> None:
        """Validate that `source` and `target` are both non-blank.

        Raises:
            ValidationError: If `source` or `target` is empty or whitespace-only.
        """
        if not self.source.strip():
            raise ValidationError("KnowledgeRelation: source must not be empty")
        if not self.target.strip():
            raise ValidationError("KnowledgeRelation: target must not be empty")


@dataclass(frozen=True, slots=True)
class KnowledgeGraph:
    """A repository's semantic knowledge graph, assembled from many files' recognized concepts.

    Attributes:
        nodes: Every domain concept found, sorted by `identifier` so the result is deterministic
            regardless of input order.
        relations: Every semantic relationship between two `nodes`, sorted by `(source, target,
            kind)`.
    """

    nodes: tuple[KnowledgeNode, ...] = ()
    relations: tuple[KnowledgeRelation, ...] = ()

    def __post_init__(self) -> None:
        """Validate that `nodes` and `relations` are sorted, unique, and internally consistent.

        Raises:
            ValidationError: If `nodes` is not sorted by `identifier`, contains a duplicate
                `identifier`, if `relations` is not sorted by `(source, target, kind)`, if any
                relation's `source` is absent from `nodes`, or if a non-`EXTENDS` relation's
                `target` is absent from `nodes`.
        """
        identifiers = [node.identifier for node in self.nodes]
        if identifiers != sorted(identifiers):
            raise ValidationError("KnowledgeGraph: nodes must be sorted by identifier")
        if len(set(identifiers)) != len(identifiers):
            raise ValidationError("KnowledgeGraph: nodes must not contain duplicate identifiers")

        relation_keys = [
            (relation.source, relation.target, relation.kind) for relation in self.relations
        ]
        if relation_keys != sorted(relation_keys, key=lambda key: (key[0], key[1], key[2].value)):
            raise ValidationError(
                "KnowledgeGraph: relations must be sorted by (source, target, kind)"
            )

        known_ids = set(identifiers)
        for relation in self.relations:
            if relation.source not in known_ids:
                raise ValidationError(
                    "KnowledgeGraph: relation.source must reference a node present in this graph",
                    details={"source": relation.source},
                )
            if relation.kind is not KnowledgeRelationKind.EXTENDS and relation.target not in (
                known_ids
            ):
                raise ValidationError(
                    "KnowledgeGraph: relation.target must reference a node present in this "
                    "graph, unless kind is EXTENDS",
                    details={"target": relation.target, "kind": str(relation.kind)},
                )

    @property
    def node_count(self) -> int:
        """Total number of domain concepts in this graph."""
        return len(self.nodes)

    @property
    def relation_count(self) -> int:
        """Total number of semantic relationships in this graph."""
        return len(self.relations)

    def get_node(self, identifier: str) -> KnowledgeNode:
        """Retrieve a single node by its `identifier`.

        Args:
            identifier: The node identifier to look up.

        Returns:
            The matching `KnowledgeNode`.

        Raises:
            NotFoundError: If no node in this graph has that `identifier`.
        """
        for node in self.nodes:
            if node.identifier == identifier:
                return node
        raise NotFoundError(f"no knowledge node with identifier '{identifier}' in this graph")

    def relations_from(self, identifier: str) -> tuple[KnowledgeRelation, ...]:
        """Retrieve every relationship whose `source` is `identifier`.

        Args:
            identifier: `KnowledgeNode.identifier` to look up outgoing relationships for.

        Returns:
            Every `KnowledgeRelation` with that `source`, in this graph's own `(source, target,
            kind)` order.
        """
        return tuple(relation for relation in self.relations if relation.source == identifier)

    def to_mapping(self) -> dict[str, Any]:
        """Render this graph as a plain, JSON-safe nested structure.

        Returns:
            A dict with `"nodes"` and `"relations"` lists, each entry a dict of primitive values.
        """
        return {
            "nodes": [
                {
                    "identifier": node.identifier,
                    "kind": str(node.kind),
                    "label": node.label,
                    "relative_path": node.relative_path,
                    "attributes": list(node.attributes),
                }
                for node in self.nodes
            ],
            "relations": [
                {
                    "source": relation.source,
                    "target": relation.target,
                    "kind": str(relation.kind),
                }
                for relation in self.relations
            ],
        }


class KnowledgeGraphBuilder(ABC):
    """Assembles many files' recognized domain concepts into one repository-wide `KnowledgeGraph`.

    A concrete implementation decides how to turn each `ExtractedSymbol`/`ExtractedPattern`/
    `ExtractedInterface`/`FoundationCandidate` into a `KnowledgeNode` (see `_node_id` for the
    required identifier scheme), how to relate each back to its owning file with a `DECLARES`
    relation, how to relate an `ExtractedInterface`'s `base_interfaces` with `EXTENDS` relations,
    and, when `architecture_graph` is given, how to relate each file to its `PACKAGE` node with a
    `BELONGS_TO_PACKAGE` relation. It does not itself extract, parse, or score any of these
    concepts -- all upstream concerns already handled by `src.parsers`/`src.extractors`, or, for
    scoring, the future `foundation` phase.
    """

    @abstractmethod
    def build(
        self,
        *,
        symbol_results: Sequence[SymbolExtractionResult] = (),
        pattern_results: Sequence[PatternExtractionResult] = (),
        interface_results: Sequence[InterfaceExtractionResult] = (),
        foundation_results: Sequence[FoundationExtractionResult] = (),
        architecture_graph: ArchitectureGraph | None = None,
    ) -> "KnowledgeGraph":
        """Assemble a `KnowledgeGraph` from many files' recognized domain concepts.

        Args:
            symbol_results: Outcomes of extracting classes/functions/methods/constants, as
                produced by `src.extractors.symbols`. Every entry must be successful -- see
                `require_successful_symbol_extractions`.
            pattern_results: Outcomes of extracting recognized code patterns, as produced by
                `src.extractors.patterns`. Every entry must be successful -- see
                `require_successful_pattern_extractions`.
            interface_results: Outcomes of extracting interface-shaped declarations, as produced
                by `src.extractors.interfaces`. Every entry must be successful -- see
                `require_successful_interface_extractions`.
            foundation_results: Outcomes of extracting raw foundation-candidacy signals, as
                produced by `src.extractors.foundation`. Every entry must be successful -- see
                `require_successful_foundation_extractions`.
            architecture_graph: An already-built `ArchitectureGraph` covering the same files, if
                package-membership relationships should be included. `PACKAGE` nodes and
                `BELONGS_TO_PACKAGE` relations are omitted entirely when None.

        Returns:
            A `KnowledgeGraph` whose `nodes` cover every recognized concept across all four
            result sequences (plus every `PackageNode` in `architecture_graph`, when given), and
            whose `relations` connect each concept back to its owning file, each interface to its
            declared base interfaces, and, when `architecture_graph` is given, each file to its
            package.

        Raises:
            ValidationError: If any entry in any of the four result sequences is itself a failed
                extraction.
        """
        ...


def require_successful_symbol_extractions(
    extraction_results: Sequence[SymbolExtractionResult],
) -> Sequence[SymbolExtractionResult]:
    """Validate that every entry in `extraction_results` represents a successful extraction.

    Args:
        extraction_results: The raw `symbol_results` argument passed to `build`.

    Returns:
        `extraction_results`, unchanged.

    Raises:
        ValidationError: If any entry's `succeeded` is False.
    """
    for extraction_result in extraction_results:
        if not extraction_result.succeeded:
            _logger.debug(
                "Rejected graph build from an unsuccessful symbol extraction of '%s'",
                extraction_result.relative_path,
            )
            raise ValidationError(
                "cannot build a knowledge graph from a failed SymbolExtractionResult",
                details={"relative_path": extraction_result.relative_path},
            )
    return extraction_results


def require_successful_pattern_extractions(
    extraction_results: Sequence[PatternExtractionResult],
) -> Sequence[PatternExtractionResult]:
    """Validate that every entry in `extraction_results` represents a successful extraction.

    Args:
        extraction_results: The raw `pattern_results` argument passed to `build`.

    Returns:
        `extraction_results`, unchanged.

    Raises:
        ValidationError: If any entry's `succeeded` is False.
    """
    for extraction_result in extraction_results:
        if not extraction_result.succeeded:
            _logger.debug(
                "Rejected graph build from an unsuccessful pattern extraction of '%s'",
                extraction_result.relative_path,
            )
            raise ValidationError(
                "cannot build a knowledge graph from a failed PatternExtractionResult",
                details={"relative_path": extraction_result.relative_path},
            )
    return extraction_results


def require_successful_interface_extractions(
    extraction_results: Sequence[InterfaceExtractionResult],
) -> Sequence[InterfaceExtractionResult]:
    """Validate that every entry in `extraction_results` represents a successful extraction.

    Args:
        extraction_results: The raw `interface_results` argument passed to `build`.

    Returns:
        `extraction_results`, unchanged.

    Raises:
        ValidationError: If any entry's `succeeded` is False.
    """
    for extraction_result in extraction_results:
        if not extraction_result.succeeded:
            _logger.debug(
                "Rejected graph build from an unsuccessful interface extraction of '%s'",
                extraction_result.relative_path,
            )
            raise ValidationError(
                "cannot build a knowledge graph from a failed InterfaceExtractionResult",
                details={"relative_path": extraction_result.relative_path},
            )
    return extraction_results


def require_successful_foundation_extractions(
    extraction_results: Sequence[FoundationExtractionResult],
) -> Sequence[FoundationExtractionResult]:
    """Validate that every entry in `extraction_results` represents a successful extraction.

    Args:
        extraction_results: The raw `foundation_results` argument passed to `build`.

    Returns:
        `extraction_results`, unchanged.

    Raises:
        ValidationError: If any entry's `succeeded` is False.
    """
    for extraction_result in extraction_results:
        if not extraction_result.succeeded:
            _logger.debug(
                "Rejected graph build from an unsuccessful foundation extraction of '%s'",
                extraction_result.relative_path,
            )
            raise ValidationError(
                "cannot build a knowledge graph from a failed FoundationExtractionResult",
                details={"relative_path": extraction_result.relative_path},
            )
    return extraction_results


def symbol_node_id(*, relative_path: str, name: str, owner: str | None = None) -> str:
    """Build the `KnowledgeNode.identifier` for a `SYMBOL` node.

    Args:
        relative_path: Path of the file the symbol was found in.
        name: The symbol's own, unqualified name.
        owner: The symbol's owning class name, for a method. None otherwise.

    Returns:
        A `SYMBOL`-namespaced id built from the same `build_qualified_name` scheme
        `extractors.symbols.base.ExtractedSymbol.qualified_name` already uses.
    """
    return _node_id(
        KnowledgeNodeKind.SYMBOL,
        build_qualified_name(relative_path=relative_path, name=name, owner=owner),
    )


def pattern_node_id(*, relative_path: str, subject_name: str, name: str) -> str:
    """Build the `KnowledgeNode.identifier` for a `PATTERN` node.

    Args:
        relative_path: Path of the file the pattern was found in.
        subject_name: Name of the class or function the pattern was recognized in.
        name: The pattern's own name (`ExtractedPattern.name`).

    Returns:
        A `PATTERN`-namespaced id, qualified by the file and the pattern's subject.
    """
    return _node_id(
        KnowledgeNodeKind.PATTERN,
        build_qualified_name(relative_path=relative_path, name=name, owner=subject_name),
    )


def interface_node_id(*, relative_path: str, name: str) -> str:
    """Build the `KnowledgeNode.identifier` for an `INTERFACE` node.

    Args:
        relative_path: Path of the file the interface was found in.
        name: The interface's own name.

    Returns:
        An `INTERFACE`-namespaced id, qualified by the file.
    """
    return _node_id(
        KnowledgeNodeKind.INTERFACE, build_qualified_name(relative_path=relative_path, name=name)
    )


def capability_node_id(*, relative_path: str, name: str) -> str:
    """Build the `KnowledgeNode.identifier` for a `CAPABILITY` node.

    Args:
        relative_path: Path of the file the foundation candidate was found in.
        name: The candidate's own name.

    Returns:
        A `CAPABILITY`-namespaced id, qualified by the file.
    """
    return _node_id(
        KnowledgeNodeKind.CAPABILITY,
        build_qualified_name(relative_path=relative_path, name=name),
    )


def entity_node_id(*, relative_path: str) -> str:
    """Build the `KnowledgeNode.identifier` for an `ENTITY` (file) node.

    Args:
        relative_path: Path of the file.

    Returns:
        An `ENTITY`-namespaced id wrapping `relative_path` directly.
    """
    return _node_id(KnowledgeNodeKind.ENTITY, relative_path)


def package_node_id(package_node: PackageNode) -> str:
    """Build the `KnowledgeNode.identifier` for a `PACKAGE` node.

    Args:
        package_node: The `graph.architecture.base.PackageNode` this node mirrors.

    Returns:
        A `PACKAGE`-namespaced id wrapping `package_node.node_id`.
    """
    return _node_id(KnowledgeNodeKind.PACKAGE, package_node.node_id)
