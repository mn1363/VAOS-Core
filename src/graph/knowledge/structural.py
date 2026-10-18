"""Structural knowledge graph builder: the first concrete `KnowledgeGraphBuilder` implementation.

`StructuralKnowledgeGraphBuilder` assembles many files' already-extracted symbols, patterns,
interfaces, and foundation candidates -- plus, optionally, an already-built `ArchitectureGraph` --
into one deterministic `KnowledgeGraph`, mapping each distinct accepted identity onto exactly one
node and relating it back to its owning file. It performs no module resolution, no import
resolution, no inference of any kind, no scoring, no ranking, and no cross-file analysis beyond
the exact base-interface name match described below; see `KnowledgeGraphBuilder`'s own docstring
in `base.py` for what is deliberately out of scope.

**Nodes.** One `ENTITY` node per distinct file path (see `StructuralKnowledgeGraphBuilder.build`
for which paths count); one `SYMBOL`, `PATTERN`, `INTERFACE`, or `CAPABILITY` node per *distinct
accepted identity* among the `ExtractedSymbol`, `ExtractedPattern`, `ExtractedInterface`, and
`FoundationCandidate` records respectively (see **Duplicate identities**); and, only when an
`ArchitectureGraph` is supplied, one `PACKAGE` node per `PackageNode`. Identifiers always come
from the frozen helpers in `base.py`; a symbol's identifier suffix is its own, already-qualified
`ExtractedSymbol.qualified_name`.

**Relations.** `DECLARES` (file -> every concept node found in it, exactly one per node),
`BELONGS_TO_PACKAGE` (file -> package, from `PackageNode.file_paths`), and `EXTENDS` (interface
-> each of its `base_interfaces`, resolved by exact name only).

**Duplicate identities.** Records are grouped by `(node kind, node identifier)` across every
successful input result. A group of one record is emitted unchanged. A multi-record group is
resolved by kind, and never partially: it is either coalesced as a whole or rejected as a whole,
with no representative, majority, or precedence rule.

- `SYMBOL` groups are coalesced only when every member has the same complete key
  `(qualified_name, name, kind, relative_path)`; `line_number` is ignored.
- `CAPABILITY` groups are coalesced only when every member has the same complete key
  `(relative_path, name, kind, signals)`, with `signals` compared as an ordered tuple;
  `is_public`, `has_docstring`, and `line_number` are ignored because the node does not project
  them. The candidate `kind` is an explicit guard even though it is not projected, so a class and
  a function sharing an identifier conflict. Identifier equality is necessary but not
  sufficient: a path/name delimiter ambiguity (`("a::b", "c")` versus `("a", "b::c")`) yields one
  identifier from different keys and is rejected.
- `INTERFACE` and `PATTERN` groups of two or more are always rejected, even when every record is
  identical.

A coalesced group yields one node built from its equivalence key through the same projection a
singleton record uses, and exactly one `DECLARES` relation. Every other multi-record group is
rejected; all rejected groups across all four families are collected and reported in one
`ValidationError` before any graph is assembled (see `StructuralKnowledgeGraphBuilder.build`).

Coalescing loses information the node does not carry: how many source declarations existed, and
each declaration's line number, `is_public`, and `has_docstring`. One node must therefore never be
read as one source declaration; the extractors' own output remains the record of declarations.
Coalescing is logged per AM-8, best-effort: ordinary exceptions raised by logging do not change
the graph or whether it is returned (AM-8.1). Exceptions deriving from `BaseException` but not
from `Exception` are not suppressed.

**Attribute encoding.** `KnowledgeNode.attributes` is a tuple of strings; this builder encodes
each carried-through detail as a `"<key>=<value>"` string, in a fixed order, split on the first
`"="`:

- `SYMBOL`: `("kind=<ExtractedSymbolKind value>",)` -- exactly one entry, e.g. `"kind=method"`.
- `PATTERN`: `"description=<description>"`, then one `"evidence=<item>"` per
  `ExtractedPattern.evidence` item, in the original order.
- `INTERFACE`: `"origin=<InterfaceOrigin value>"`, then one `"method_signature=<n>"` per
  `ExtractedInterface.method_signatures` item, in the original order. `base_interfaces` is never
  encoded as an attribute; it is represented by `EXTENDS` relations only.
- `CAPABILITY`: `FoundationCandidate.signals`, verbatim and unprefixed -- nothing is added,
  inferred, or invented.
- `PACKAGE`: `("has_package_root_file=true",)` or `("has_package_root_file=false",)`.
- `ENTITY`: empty.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, NamedTuple

from src.core.exceptions import ValidationError
from src.core.logging import get_logger
from src.extractors.foundation.base import (
    FoundationCandidate,
    FoundationCandidateKind,
    FoundationExtractionResult,
)
from src.extractors.interfaces.base import ExtractedInterface, InterfaceExtractionResult
from src.extractors.patterns.base import ExtractedPattern, PatternExtractionResult
from src.extractors.symbols.base import (
    ExtractedSymbol,
    ExtractedSymbolKind,
    SymbolExtractionResult,
)
from src.graph.architecture.base import ArchitectureGraph, PackageNode
from src.graph.knowledge.base import (
    KnowledgeGraph,
    KnowledgeGraphBuilder,
    KnowledgeNode,
    KnowledgeNodeKind,
    KnowledgeRelation,
    KnowledgeRelationKind,
    _node_id,
    capability_node_id,
    entity_node_id,
    interface_node_id,
    package_node_id,
    pattern_node_id,
    require_successful_foundation_extractions,
    require_successful_interface_extractions,
    require_successful_pattern_extractions,
    require_successful_symbol_extractions,
)

_logger = get_logger("graph.knowledge.structural")

_EXTERNAL_INTERFACE_PREFIX = "external::"
"""Raw-identifier prefix of the `EXTENDS` target used for a base interface that is not resolved
to exactly one extracted interface (e.g. `"interface:external::Base"`)."""

_DUPLICATE_IDENTIFIERS_PREFIX = "KnowledgeGraph: nodes must not contain duplicate identifiers"
"""Byte-identical prefix of the frozen `KnowledgeGraph` duplicate-identifier message. The builder's
own aggregate collision message extends it; `base.py` is never modified."""

_MAX_LISTED_COLLISIONS = 5
"""How many rejected identifiers the collision message lists before summarizing the rest."""

_REASON_CONFLICTING_RECORDS = "conflicting_records"
"""Collision reason for a `SYMBOL`/`CAPABILITY` group whose members are not all equivalent."""

_REASON_COALESCING_NOT_PERMITTED = "coalescing_not_permitted"
"""Collision reason for any `INTERFACE`/`PATTERN` group of two or more records."""

_SYMBOL_KEY_FIELDS = ("qualified_name", "name", "declaration_kind", "relative_path")
"""Diagnostic field names of `_SymbolKey`, in key order (`kind` is reported as
`declaration_kind`)."""

_CAPABILITY_KEY_FIELDS = ("relative_path", "name", "declaration_kind", "signals")
"""Diagnostic field names of `_CapabilityKey`, in key order (`kind` is reported as
`declaration_kind`)."""

_COALESCED_WARNING_FORMAT = (
    "Coalesced %d colliding node group(s) covering %d declaration(s): "
    "symbol=%d group(s)/%d declaration(s), capability=%d group(s)/%d declaration(s); "
    "declaration multiplicity and metadata outside the node projection are not preserved"
)
"""`%`-style aggregate WARNING emitted once per build that coalesced at least one group."""

_COALESCED_SYMBOL_DEBUG_FORMAT = "Coalesced %s (%s): %d declaration(s); line_numbers=%s"
"""`%`-style per-group DEBUG record for a coalesced `SYMBOL` group."""

_COALESCED_CAPABILITY_DEBUG_FORMAT = (
    "Coalesced %s (%s): %d declaration(s); line_numbers=%s; is_public=%s; has_docstring=%s"
)
"""`%`-style per-group DEBUG record for a coalesced `CAPABILITY` group."""


class _SymbolKey(NamedTuple):
    """Complete equivalence key of a `SYMBOL` record.

    `kind` is kept as the `ExtractedSymbolKind` member for comparison; diagnostics serialize it
    separately as `declaration_kind`. `line_number` is deliberately absent.
    """

    qualified_name: str
    name: str
    kind: ExtractedSymbolKind
    relative_path: str


class _CapabilityKey(NamedTuple):
    """Complete equivalence key of a `CAPABILITY` record.

    `kind` is kept as the `FoundationCandidateKind` member for comparison; diagnostics serialize
    it separately as `declaration_kind`. `signals` is an ordered tuple. `is_public`,
    `has_docstring`, and `line_number` are deliberately absent: the node projection ignores them.
    """

    relative_path: str
    name: str
    kind: FoundationCandidateKind
    signals: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _CoalescedGroup:
    """Everything the logging step needs about one coalesced `SYMBOL`/`CAPABILITY` group.

    All sequences are in canonical member order and hold one entry per source declaration.
    `is_public` and `has_docstring` are populated for `CAPABILITY` groups only.
    """

    identifier: str
    node_kind: KnowledgeNodeKind
    line_numbers: tuple[int, ...]
    is_public: tuple[bool, ...] = ()
    has_docstring: tuple[bool, ...] = ()


@dataclass(frozen=True, slots=True)
class _RejectedGroup:
    """One rejected collision group, with its already-serialized, JSON-safe diagnostics."""

    identifier: str
    node_kind: KnowledgeNodeKind
    reason: str
    differing_fields: tuple[str, ...]
    records: tuple[dict[str, Any], ...]


@dataclass(slots=True)
class _ConceptResolution:
    """The outcome of resolving one concept family's identity groups."""

    nodes: list[KnowledgeNode] = field(default_factory=list)
    coalesced: list[_CoalescedGroup] = field(default_factory=list)
    rejected: list[_RejectedGroup] = field(default_factory=list)


class StructuralKnowledgeGraphBuilder(KnowledgeGraphBuilder):
    """Assembles extracted symbols, patterns, interfaces, and foundation candidates into one
    `KnowledgeGraph`, one node per distinct accepted identity.

    Stateless and dependency-free: no `__init__` override, and a single instance may be reused
    across any number of `build` calls. Input records are only ever read, never mutated.
    """

    def build(
        self,
        *,
        symbol_results: Sequence[SymbolExtractionResult] = (),
        pattern_results: Sequence[PatternExtractionResult] = (),
        interface_results: Sequence[InterfaceExtractionResult] = (),
        foundation_results: Sequence[FoundationExtractionResult] = (),
        architecture_graph: ArchitectureGraph | None = None,
    ) -> KnowledgeGraph:
        """Assemble a `KnowledgeGraph` from many files' recognized domain concepts.

        Args:
            symbol_results: Outcomes of extracting classes/functions/methods/constants. Every
                entry must be successful.
            pattern_results: Outcomes of extracting recognized code patterns. Every entry must be
                successful.
            interface_results: Outcomes of extracting interface-shaped declarations. Every entry
                must be successful.
            foundation_results: Outcomes of extracting raw foundation-candidacy signals. Every
                entry must be successful.
            architecture_graph: An already-built `ArchitectureGraph`, if package membership
                should be included. `PACKAGE` nodes and `BELONGS_TO_PACKAGE` relations are
                omitted entirely when None.

        Returns:
            A valid `KnowledgeGraph` with:

            - one `ENTITY` node per distinct file path, taken from every result's
              `relative_path`, from every concept's own `relative_path` (always equal to its
              result's path for results produced by the real extractors), and, when
              `architecture_graph` is given, from every `PackageNode.file_paths` entry -- so a
              successful result with no concepts, and a file only the architecture graph knows
              about, each still get an entity. Entities are deduplicated by path, including
              paths contributed by coalesced records;
            - one concept node per distinct accepted identity among the symbols, patterns,
              interfaces, and foundation candidates, each related back to its owning file's
              entity by exactly one `DECLARES` relation. Records sharing one identifier form a
              group: a single record is emitted unchanged; a `SYMBOL` group whose every member
              has the same `(qualified_name, name, kind, relative_path)` key, or a `CAPABILITY`
              group whose every member has the same `(relative_path, name, kind, signals)` key,
              is coalesced into one node built from that key (one node, one `DECLARES`);
              anything else is rejected, see `Raises`. Coalescing loses the number of source
              declarations and their line numbers, `is_public`, and `has_docstring`; supplying
              the same successful result twice therefore yields the same graph as supplying it
              once, unless it contains an `INTERFACE` or `PATTERN` (those collide and reject);
            - one `PACKAGE` node per `PackageNode` in `architecture_graph`, labeled with
              `PackageNode.node_id` (empty for the repository root), each file in its
              `file_paths` related to it by a `BELONGS_TO_PACKAGE` relation. Package nodes are
              not deduplicated by the builder;
            - one `EXTENDS` relation per entry in each interface's `base_interfaces`: to the
              extracted interface of exactly that name when exactly one exists across all of
              `interface_results`, otherwise to `"interface:external::<base-name>"`. No import or
              module resolution is attempted, and an ambiguous name is never resolved. A base
              name repeated within one interface produces a repeated relation; nothing is
              deduplicated.

            `nodes` are sorted by `identifier` and `relations` by `(source, target,
            kind.value)`. Empty input yields an empty graph.

            If at least one `SYMBOL`/`CAPABILITY` group was coalesced, one aggregate WARNING and,
            when DEBUG is enabled, one DEBUG record per coalesced group are logged on the
            `vaos.graph.knowledge.structural` logger after the graph is fully built. Coalescing
            is logged per AM-8, best-effort: ordinary exceptions raised by logging do not change
            the graph or whether it is returned (AM-8.1). Exceptions deriving from
            `BaseException` but not from `Exception` are not suppressed.

        Raises:
            ValidationError: If any entry in any of the four result sequences is itself a failed
                extraction (checked for all four first, before any resolution or assembly).
                Otherwise, if any identity group is rejected -- a non-equivalent `SYMBOL` or
                `CAPABILITY` group (`reason="conflicting_records"`), or any `INTERFACE` or
                `PATTERN` group of two or more records, identical records included
                (`reason="coalescing_not_permitted"`) -- every rejected group across all four
                families is reported in a single error, before any graph is assembled, with the
                message `KnowledgeGraph: nodes must not contain duplicate identifiers; <count>
                colliding identifier(s) rejected: <listed>` (the first five identifiers in
                ascending order, each in single quotes, then ` (and <n> more)` when there are
                more) and `details` of `collision_count` plus `collisions`, one entry per
                rejected group ordered by identifier with `identifier`, `node_kind`, `reason`,
                `differing_fields`, and every member in `records`; all values are JSON-safe.
                Finally, a package identifier collision (never a concept collision) is
                propagated unchanged from `KnowledgeGraph`, with its existing message and empty
                details; concept collisions take precedence because they are evaluated first.
        """
        require_successful_symbol_extractions(symbol_results)
        require_successful_pattern_extractions(pattern_results)
        require_successful_interface_extractions(interface_results)
        require_successful_foundation_extractions(foundation_results)

        resolutions = (
            _resolve_symbols(symbol_results),
            _resolve_patterns(pattern_results),
            _resolve_interfaces(interface_results),
            _resolve_capabilities(foundation_results),
        )
        rejected = [group for resolution in resolutions for group in resolution.rejected]
        if rejected:
            raise _collision_error(rejected)

        concept_nodes = [node for resolution in resolutions for node in resolution.nodes]
        coalesced = [group for resolution in resolutions for group in resolution.coalesced]
        packages = architecture_graph.nodes if architecture_graph is not None else ()

        entity_paths: set[str] = set()
        entity_paths.update(result.relative_path for result in symbol_results)
        entity_paths.update(result.relative_path for result in pattern_results)
        entity_paths.update(result.relative_path for result in interface_results)
        entity_paths.update(result.relative_path for result in foundation_results)
        entity_paths.update(
            node.relative_path for node in concept_nodes if node.relative_path is not None
        )
        for package in packages:
            entity_paths.update(package.file_paths)

        nodes = [
            *(_entity_node(relative_path) for relative_path in entity_paths),
            *concept_nodes,
            *(_package_node(package) for package in packages),
        ]
        relations = [
            *(
                _declares_relation(node.relative_path, node.identifier)
                for node in concept_nodes
                if node.relative_path is not None
            ),
            *(
                KnowledgeRelation(
                    source=entity_node_id(relative_path=relative_path),
                    target=package_node_id(package),
                    kind=KnowledgeRelationKind.BELONGS_TO_PACKAGE,
                )
                for package in packages
                for relative_path in package.file_paths
            ),
            *_extends_relations(interface_results),
        ]

        graph = KnowledgeGraph(
            nodes=tuple(sorted(nodes, key=lambda node: node.identifier)),
            relations=tuple(
                sorted(
                    relations,
                    key=lambda relation: (relation.source, relation.target, relation.kind.value),
                )
            ),
        )
        _log_coalescing(coalesced)
        return graph


def _entity_node(relative_path: str) -> KnowledgeNode:
    """Build the `ENTITY` node for one file.

    Args:
        relative_path: Path of the file.

    Returns:
        A node labeled with `relative_path`, carrying it as its own `relative_path`, with empty
        attributes.
    """
    return KnowledgeNode(
        identifier=entity_node_id(relative_path=relative_path),
        kind=KnowledgeNodeKind.ENTITY,
        label=relative_path,
        relative_path=relative_path,
    )


def _declares_relation(relative_path: str, concept_identifier: str) -> KnowledgeRelation:
    """Build the `DECLARES` relation from a file's entity to one concept found in it.

    Args:
        relative_path: Path of the owning file.
        concept_identifier: `KnowledgeNode.identifier` of the concept.

    Returns:
        A `DECLARES` relation from the file's `ENTITY` node to the concept node.
    """
    return KnowledgeRelation(
        source=entity_node_id(relative_path=relative_path),
        target=concept_identifier,
        kind=KnowledgeRelationKind.DECLARES,
    )


def _symbol_key(symbol: ExtractedSymbol) -> _SymbolKey:
    """Build the complete equivalence key of one `ExtractedSymbol`.

    Args:
        symbol: The extracted symbol.

    Returns:
        `(qualified_name, name, kind, relative_path)`, with `kind` as the enum member.
        `line_number` is not part of the key.
    """
    return _SymbolKey(
        qualified_name=symbol.qualified_name,
        name=symbol.name,
        kind=symbol.kind,
        relative_path=symbol.relative_path,
    )


def _symbol_node(key: _SymbolKey) -> KnowledgeNode:
    """Build the `SYMBOL` node for one equivalence key.

    Used for singleton records and coalesced groups alike, so a coalesced node is identical to
    the node of any single record carrying the same key.

    Args:
        key: The symbol's complete equivalence key.

    Returns:
        A node whose identifier suffix is `key.qualified_name` as given -- ownership is never
        reconstructed from names -- labeled with `key.name`, with the single attribute
        `"kind=<key.kind value>"`.
    """
    return KnowledgeNode(
        identifier=_node_id(KnowledgeNodeKind.SYMBOL, key.qualified_name),
        kind=KnowledgeNodeKind.SYMBOL,
        label=key.name,
        relative_path=key.relative_path,
        attributes=(f"kind={key.kind.value}",),
    )


def _symbol_order_key(symbol: ExtractedSymbol) -> tuple[int, str, str, str, str]:
    """Canonical member order of a `SYMBOL` group: all record fields, line number first."""
    return (
        symbol.line_number,
        symbol.qualified_name,
        symbol.name,
        symbol.kind.value,
        symbol.relative_path,
    )


def _symbol_record(symbol: ExtractedSymbol) -> dict[str, Any]:
    """Serialize one symbol for collision diagnostics (JSON-safe; `kind` as `declaration_kind`)."""
    return {
        "qualified_name": symbol.qualified_name,
        "name": symbol.name,
        "declaration_kind": symbol.kind.value,
        "relative_path": symbol.relative_path,
        "line_number": symbol.line_number,
    }


def _resolve_symbols(results: Sequence[SymbolExtractionResult]) -> _ConceptResolution:
    """Group every symbol across `results` by node identifier and resolve each group.

    Args:
        results: Every successful symbol extraction result.

    Returns:
        One node per singleton or fully equivalent group, a `_CoalescedGroup` per multi-record
        equivalent group, and a `_RejectedGroup` (`conflicting_records`) per group with any
        non-equivalent member.
    """
    groups: dict[str, list[ExtractedSymbol]] = {}
    for result in results:
        for symbol in result.symbols:
            identifier = _node_id(KnowledgeNodeKind.SYMBOL, symbol.qualified_name)
            groups.setdefault(identifier, []).append(symbol)

    resolution = _ConceptResolution()
    for identifier, members in groups.items():
        keys = [_symbol_key(member) for member in members]
        ordered = sorted(members, key=_symbol_order_key)
        if all(key == keys[0] for key in keys):
            resolution.nodes.append(_symbol_node(keys[0]))
            if len(members) > 1:
                resolution.coalesced.append(
                    _CoalescedGroup(
                        identifier=identifier,
                        node_kind=KnowledgeNodeKind.SYMBOL,
                        line_numbers=tuple(member.line_number for member in ordered),
                    )
                )
        else:
            resolution.rejected.append(
                _RejectedGroup(
                    identifier=identifier,
                    node_kind=KnowledgeNodeKind.SYMBOL,
                    reason=_REASON_CONFLICTING_RECORDS,
                    differing_fields=_differing_fields(_SYMBOL_KEY_FIELDS, keys),
                    records=tuple(_symbol_record(member) for member in ordered),
                )
            )
    return resolution


def _pattern_node(pattern: ExtractedPattern) -> KnowledgeNode:
    """Build the `PATTERN` node for one `ExtractedPattern`.

    Args:
        pattern: The extracted pattern.

    Returns:
        A node labeled with `pattern.name`, with attributes `"description=<description>"`
        followed by one `"evidence=<item>"` per evidence item, in the original order.
    """
    return KnowledgeNode(
        identifier=pattern_node_id(
            relative_path=pattern.relative_path,
            subject_name=pattern.subject_name,
            name=pattern.name,
        ),
        kind=KnowledgeNodeKind.PATTERN,
        label=pattern.name,
        relative_path=pattern.relative_path,
        attributes=(
            f"description={pattern.description}",
            *(f"evidence={item}" for item in pattern.evidence),
        ),
    )


def _pattern_order_key(
    pattern: ExtractedPattern,
) -> tuple[int, str, str, str, str, tuple[str, ...]]:
    """Canonical member order of a `PATTERN` group: all record fields, line number first."""
    return (
        pattern.line_number,
        pattern.relative_path,
        pattern.subject_name,
        pattern.name,
        pattern.description,
        tuple(pattern.evidence),
    )


def _pattern_record(pattern: ExtractedPattern) -> dict[str, Any]:
    """Serialize one pattern for collision diagnostics (JSON-safe; tuples as lists)."""
    return {
        "name": pattern.name,
        "subject_name": pattern.subject_name,
        "relative_path": pattern.relative_path,
        "description": pattern.description,
        "evidence": list(pattern.evidence),
        "line_number": pattern.line_number,
    }


def _resolve_patterns(results: Sequence[PatternExtractionResult]) -> _ConceptResolution:
    """Group every pattern across `results` by node identifier and resolve each group.

    Args:
        results: Every successful pattern extraction result.

    Returns:
        One node per singleton group, and a `_RejectedGroup` (`coalescing_not_permitted`, no
        differing fields) per group of two or more records -- identical records included.
    """
    groups: dict[str, list[ExtractedPattern]] = {}
    for result in results:
        for pattern in result.patterns:
            identifier = pattern_node_id(
                relative_path=pattern.relative_path,
                subject_name=pattern.subject_name,
                name=pattern.name,
            )
            groups.setdefault(identifier, []).append(pattern)

    resolution = _ConceptResolution()
    for identifier, members in groups.items():
        if len(members) == 1:
            resolution.nodes.append(_pattern_node(members[0]))
        else:
            resolution.rejected.append(
                _RejectedGroup(
                    identifier=identifier,
                    node_kind=KnowledgeNodeKind.PATTERN,
                    reason=_REASON_COALESCING_NOT_PERMITTED,
                    differing_fields=(),
                    records=tuple(
                        _pattern_record(member)
                        for member in sorted(members, key=_pattern_order_key)
                    ),
                )
            )
    return resolution


def _interface_node(interface: ExtractedInterface) -> KnowledgeNode:
    """Build the `INTERFACE` node for one `ExtractedInterface`.

    Args:
        interface: The extracted interface.

    Returns:
        A node labeled with `interface.name`, with attributes `"origin=<origin value>"` followed
        by one `"method_signature=<n>"` per method signature, in the original order. Base
        interfaces are not encoded here -- see `_extends_relations`.
    """
    return KnowledgeNode(
        identifier=interface_node_id(relative_path=interface.relative_path, name=interface.name),
        kind=KnowledgeNodeKind.INTERFACE,
        label=interface.name,
        relative_path=interface.relative_path,
        attributes=(
            f"origin={interface.origin.value}",
            *(f"method_signature={signature}" for signature in interface.method_signatures),
        ),
    )


def _interface_order_key(
    interface: ExtractedInterface,
) -> tuple[int, str, str, str, tuple[str, ...], tuple[str, ...]]:
    """Canonical member order of an `INTERFACE` group: all record fields, line number first."""
    return (
        interface.line_number,
        interface.relative_path,
        interface.name,
        interface.origin.value,
        tuple(interface.method_signatures),
        tuple(interface.base_interfaces),
    )


def _interface_record(interface: ExtractedInterface) -> dict[str, Any]:
    """Serialize one interface for collision diagnostics (JSON-safe; `origin` as its value)."""
    return {
        "name": interface.name,
        "origin": interface.origin.value,
        "relative_path": interface.relative_path,
        "method_signatures": list(interface.method_signatures),
        "base_interfaces": list(interface.base_interfaces),
        "line_number": interface.line_number,
    }


def _resolve_interfaces(results: Sequence[InterfaceExtractionResult]) -> _ConceptResolution:
    """Group every interface across `results` by node identifier and resolve each group.

    Args:
        results: Every successful interface extraction result.

    Returns:
        One node per singleton group, and a `_RejectedGroup` (`coalescing_not_permitted`, no
        differing fields) per group of two or more records -- identical records included.
    """
    groups: dict[str, list[ExtractedInterface]] = {}
    for result in results:
        for interface in result.interfaces:
            identifier = interface_node_id(
                relative_path=interface.relative_path, name=interface.name
            )
            groups.setdefault(identifier, []).append(interface)

    resolution = _ConceptResolution()
    for identifier, members in groups.items():
        if len(members) == 1:
            resolution.nodes.append(_interface_node(members[0]))
        else:
            resolution.rejected.append(
                _RejectedGroup(
                    identifier=identifier,
                    node_kind=KnowledgeNodeKind.INTERFACE,
                    reason=_REASON_COALESCING_NOT_PERMITTED,
                    differing_fields=(),
                    records=tuple(
                        _interface_record(member)
                        for member in sorted(members, key=_interface_order_key)
                    ),
                )
            )
    return resolution


def _capability_key(candidate: FoundationCandidate) -> _CapabilityKey:
    """Build the complete equivalence key of one `FoundationCandidate`.

    Args:
        candidate: The foundation candidate.

    Returns:
        `(relative_path, name, kind, signals)`, with `kind` as the enum member and `signals` as
        an ordered tuple. `is_public`, `has_docstring`, and `line_number` are not part of the
        key.
    """
    return _CapabilityKey(
        relative_path=candidate.relative_path,
        name=candidate.name,
        kind=candidate.kind,
        signals=tuple(candidate.signals),
    )


def _capability_node(key: _CapabilityKey) -> KnowledgeNode:
    """Build the `CAPABILITY` node for one equivalence key.

    Used for singleton records and coalesced groups alike, so a coalesced node is identical to
    the node of any single record carrying the same key.

    Args:
        key: The candidate's complete equivalence key.

    Returns:
        A node labeled with `key.name`, whose attributes are exactly `key.signals`. The candidate
        `kind` guards equivalence but is not projected.
    """
    return KnowledgeNode(
        identifier=capability_node_id(relative_path=key.relative_path, name=key.name),
        kind=KnowledgeNodeKind.CAPABILITY,
        label=key.name,
        relative_path=key.relative_path,
        attributes=key.signals,
    )


def _capability_order_key(
    candidate: FoundationCandidate,
) -> tuple[int, str, str, str, tuple[str, ...], bool, bool]:
    """Canonical member order of a `CAPABILITY` group: all record fields, line number first."""
    return (
        candidate.line_number,
        candidate.relative_path,
        candidate.name,
        candidate.kind.value,
        tuple(candidate.signals),
        candidate.is_public,
        candidate.has_docstring,
    )


def _capability_record(candidate: FoundationCandidate) -> dict[str, Any]:
    """Serialize one candidate for collision diagnostics (JSON-safe; `kind` as
    `declaration_kind`, `signals` as a list)."""
    return {
        "name": candidate.name,
        "declaration_kind": candidate.kind.value,
        "relative_path": candidate.relative_path,
        "signals": list(candidate.signals),
        "is_public": candidate.is_public,
        "has_docstring": candidate.has_docstring,
        "line_number": candidate.line_number,
    }


def _resolve_capabilities(results: Sequence[FoundationExtractionResult]) -> _ConceptResolution:
    """Group every candidate across `results` by node identifier and resolve each group.

    Args:
        results: Every successful foundation extraction result.

    Returns:
        One node per singleton or fully equivalent group, a `_CoalescedGroup` per multi-record
        equivalent group, and a `_RejectedGroup` (`conflicting_records`) per group with any
        non-equivalent member.
    """
    groups: dict[str, list[FoundationCandidate]] = {}
    for result in results:
        for candidate in result.candidates:
            identifier = capability_node_id(
                relative_path=candidate.relative_path, name=candidate.name
            )
            groups.setdefault(identifier, []).append(candidate)

    resolution = _ConceptResolution()
    for identifier, members in groups.items():
        keys = [_capability_key(member) for member in members]
        ordered = sorted(members, key=_capability_order_key)
        if all(key == keys[0] for key in keys):
            resolution.nodes.append(_capability_node(keys[0]))
            if len(members) > 1:
                resolution.coalesced.append(
                    _CoalescedGroup(
                        identifier=identifier,
                        node_kind=KnowledgeNodeKind.CAPABILITY,
                        line_numbers=tuple(member.line_number for member in ordered),
                        is_public=tuple(member.is_public for member in ordered),
                        has_docstring=tuple(member.has_docstring for member in ordered),
                    )
                )
        else:
            resolution.rejected.append(
                _RejectedGroup(
                    identifier=identifier,
                    node_kind=KnowledgeNodeKind.CAPABILITY,
                    reason=_REASON_CONFLICTING_RECORDS,
                    differing_fields=_differing_fields(_CAPABILITY_KEY_FIELDS, keys),
                    records=tuple(_capability_record(member) for member in ordered),
                )
            )
    return resolution


def _differing_fields(
    field_names: tuple[str, ...], keys: Sequence[tuple[Any, ...]]
) -> tuple[str, ...]:
    """Name the key fields whose values are not all equal across a group.

    Args:
        field_names: Diagnostic names of the key's fields, in key order.
        keys: The complete equivalence key of every group member, positionally aligned with
            `field_names`. Enum-valued fields hold the original enum members, so equality is
            decided on members, never on serialized names.

    Returns:
        The diagnostic names of every field with more than one distinct value across `keys`, in
        ascending name order.
    """
    return tuple(
        sorted(
            name
            for position, name in enumerate(field_names)
            if len({key[position] for key in keys}) > 1
        )
    )


def _collision_error(rejected: Sequence[_RejectedGroup]) -> ValidationError:
    """Build the single aggregate `ValidationError` for every rejected collision group.

    Args:
        rejected: Every rejected group across all four concept families, in any order.

    Returns:
        A `ValidationError` whose message extends the frozen duplicate-identifier prefix with
        the group count and the first five identifiers (ascending, single-quoted, plus
        ` (and <n> more)` beyond five), and whose `details` hold `collision_count` and
        `collisions` ordered by identifier -- every group with every member record, all
        JSON-safe.
    """
    ordered = sorted(rejected, key=lambda group: group.identifier)
    count = len(ordered)
    listed = ", ".join(f"'{group.identifier}'" for group in ordered[:_MAX_LISTED_COLLISIONS])
    if count > _MAX_LISTED_COLLISIONS:
        listed += f" (and {count - _MAX_LISTED_COLLISIONS} more)"
    return ValidationError(
        f"{_DUPLICATE_IDENTIFIERS_PREFIX}; {count} colliding identifier(s) rejected: {listed}",
        details={
            "collision_count": count,
            "collisions": [
                {
                    "identifier": group.identifier,
                    "node_kind": group.node_kind.value,
                    "reason": group.reason,
                    "differing_fields": list(group.differing_fields),
                    "records": list(group.records),
                }
                for group in ordered
            ],
        },
    )


def _log_coalescing(coalesced: Sequence[_CoalescedGroup]) -> None:
    """Best-effort logging of coalesced groups, after the graph is fully built and validated.

    Emits nothing when no group was coalesced. Otherwise emits one aggregate WARNING and, when
    DEBUG is enabled, one DEBUG record per coalesced group, in ascending identifier order. The
    declaration total counts every supplied declaration -- the sum of the coalesced groups'
    sizes -- not the number of records removed.

    Every count and payload is computed before the guarded region. The guarded region holds
    only the DEBUG enablement check and the logging calls themselves, and catches `Exception`
    only: an ordinary exception raised by logging (a handler's `emit`, a handler or logger
    filter, ...) is suppressed without re-raising, re-logging, or any alternative reporting, and
    skips the remaining log calls for this build. Exceptions deriving from `BaseException` but
    not from `Exception` (`KeyboardInterrupt`, `SystemExit`, ...) are deliberately not caught.
    Logging is best-effort: records may therefore be missing or incomplete if the logging
    subsystem itself fails, but the already-built graph is unaffected (AM-8.1, AM-8.9).

    Args:
        coalesced: Every coalesced `SYMBOL`/`CAPABILITY` group of this build, in any order.
    """
    if not coalesced:
        return

    ordered = sorted(coalesced, key=lambda group: group.identifier)
    symbol_groups = [group for group in ordered if group.node_kind is KnowledgeNodeKind.SYMBOL]
    capability_groups = [
        group for group in ordered if group.node_kind is KnowledgeNodeKind.CAPABILITY
    ]
    symbol_declarations = sum(len(group.line_numbers) for group in symbol_groups)
    capability_declarations = sum(len(group.line_numbers) for group in capability_groups)
    warning_arguments = (
        len(ordered),
        symbol_declarations + capability_declarations,
        len(symbol_groups),
        symbol_declarations,
        len(capability_groups),
        capability_declarations,
    )
    debug_records: list[tuple[str, tuple[object, ...]]] = []
    for group in ordered:
        shared = (
            group.identifier,
            group.node_kind.value,
            len(group.line_numbers),
            str(list(group.line_numbers)),
        )
        if group.node_kind is KnowledgeNodeKind.CAPABILITY:
            debug_records.append(
                (
                    _COALESCED_CAPABILITY_DEBUG_FORMAT,
                    (*shared, str(list(group.is_public)), str(list(group.has_docstring))),
                )
            )
        else:
            debug_records.append((_COALESCED_SYMBOL_DEBUG_FORMAT, shared))

    try:
        _logger.warning(_COALESCED_WARNING_FORMAT, *warning_arguments)
        if _logger.isEnabledFor(logging.DEBUG):
            for debug_format, debug_arguments in debug_records:
                _logger.debug(debug_format, *debug_arguments)
    except Exception:
        return


def _package_node(package: PackageNode) -> KnowledgeNode:
    """Build the `PACKAGE` node for one `PackageNode`.

    Args:
        package: The architecture graph's package node.

    Returns:
        A node labeled with `package.node_id` (empty for the repository root), with no
        `relative_path`, and the single attribute `"has_package_root_file=true"` or
        `"has_package_root_file=false"`.
    """
    flag = "true" if package.has_package_root_file else "false"
    return KnowledgeNode(
        identifier=package_node_id(package),
        kind=KnowledgeNodeKind.PACKAGE,
        label=package.node_id,
        relative_path=None,
        attributes=(f"has_package_root_file={flag}",),
    )


def _extends_relations(results: Sequence[InterfaceExtractionResult]) -> list[KnowledgeRelation]:
    """Build one `EXTENDS` relation per base-interface entry across `results`, in input order.

    Args:
        results: Every successful interface extraction result.

    Returns:
        For each interface and each of its `base_interfaces` entries, a relation from the
        interface's node to the node of the single extracted interface whose name equals the
        entry exactly (across all of `results`), or to `"interface:external::<entry>"` when
        zero or more than one extracted interface has that name.
    """
    identifiers_by_name: dict[str, list[str]] = {}
    for result in results:
        for interface in result.interfaces:
            identifiers_by_name.setdefault(interface.name, []).append(
                interface_node_id(relative_path=interface.relative_path, name=interface.name)
            )

    relations: list[KnowledgeRelation] = []
    for result in results:
        for interface in result.interfaces:
            source = interface_node_id(relative_path=interface.relative_path, name=interface.name)
            for base_name in interface.base_interfaces:
                matches = identifiers_by_name.get(base_name, [])
                target = (
                    matches[0]
                    if len(matches) == 1
                    else _node_id(
                        KnowledgeNodeKind.INTERFACE, f"{_EXTERNAL_INTERFACE_PREFIX}{base_name}"
                    )
                )
                relations.append(
                    KnowledgeRelation(
                        source=source, target=target, kind=KnowledgeRelationKind.EXTENDS
                    )
                )
    return relations
