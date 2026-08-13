"""Call graph Port: function/method call graph representation.

`CallGraphBuilder` assembles many files' `extractors.symbols.base.ExtractedSymbol`s into a
`CallGraph` of `CallableNode`s -- one per declared function or method -- optionally linked by
`CallEdge`s recording which callable invokes which other callable.

No frozen Phase 1-7 Port resolves an actual caller-to-callee relationship anywhere: `extractors.
symbols` records that a function or method *exists* (`ExtractedSymbol`), not what it *calls*, and
no `extractors.ast`/`analyzers.*` contract fills that gap either. This is a genuine, reported
contract gap, not a guess papered over: `CallGraphBuilder.build` can always produce `CallableNode`s
from genuinely available `SymbolExtractionResult` data, but can only produce `CallEdge`s from an
explicit, externally-supplied `call_edges` sequence -- there is currently nothing upstream for a
concrete implementation to derive them from. This matches the task's own "when available" framing
for this graph: the representation is fully call-relationship-capable, and a future extractor
phase (or a corrected/extended one) supplying resolved call sites would plug directly into the
existing `call_edges` parameter without any change to this contract.

This Port does not parse source code, extract symbols itself, or resolve which call a callable
site actually targets -- parsing and symbol extraction are `parsers`/`extractors.symbols`
concerns, already built; call-site resolution is the missing upstream concern described above.
"""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from src.core.exceptions import NotFoundError, ValidationError
from src.core.logging import get_logger
from src.extractors.symbols.base import ExtractedSymbolKind, SymbolExtractionResult

_logger = get_logger("graph.callgraph")

#: The only `ExtractedSymbolKind` values a call graph represents as nodes -- classes and
#: constants are not callable and never appear here.
_CALLABLE_SYMBOL_KINDS = (ExtractedSymbolKind.FUNCTION, ExtractedSymbolKind.METHOD)


@dataclass(frozen=True, slots=True)
class CallableNode:
    """A single function or method a `CallGraph` can represent call relationships between.

    Attributes:
        qualified_name: The callable's fully-qualified name, carried through unchanged from
            `ExtractedSymbol.qualified_name` -- already unambiguous across an entire repository.
        name: The callable's own, unqualified name.
        kind: Always `FUNCTION` or `METHOD` -- validated in `__post_init__`.
        relative_path: Path of the file the callable was found in.
        line_number: 1-indexed line the callable is declared on. 0 if unknown.
    """

    qualified_name: str
    name: str
    kind: ExtractedSymbolKind
    relative_path: str
    line_number: int = 0

    def __post_init__(self) -> None:
        """Validate that `kind` is one this graph can represent.

        Raises:
            ValidationError: If `kind` is not `FUNCTION` or `METHOD`.
        """
        if self.kind not in _CALLABLE_SYMBOL_KINDS:
            raise ValidationError(
                "CallableNode: kind must be FUNCTION or METHOD",
                details={"qualified_name": self.qualified_name, "kind": str(self.kind)},
            )


@dataclass(frozen=True, slots=True)
class CallEdge:
    """A single call relationship from one callable to another.

    Attributes:
        caller: `CallableNode.qualified_name` of the callable making the call. Must reference a
            node present in the same `CallGraph`.
        callee: `CallableNode.qualified_name` of the callable being called, or any other
            qualified-name-shaped string identifying it (e.g. a third-party function this
            graph's own inputs never declared a `CallableNode` for). Not required to reference a
            node present in the same `CallGraph` -- see `CallGraph.__post_init__`.
        line_number: 1-indexed line the call occurs on. 0 if unknown.
    """

    caller: str
    callee: str
    line_number: int = 0

    def __post_init__(self) -> None:
        """Validate that `caller` and `callee` are both non-blank.

        Raises:
            ValidationError: If `caller` or `callee` is empty or whitespace-only.
        """
        if not self.caller.strip():
            raise ValidationError("CallEdge: caller must not be empty")
        if not self.callee.strip():
            raise ValidationError("CallEdge: callee must not be empty")


@dataclass(frozen=True, slots=True)
class CallGraph:
    """A repository's function/method call graph, assembled from many files' declared callables.

    Attributes:
        nodes: Every function/method declared across the files this graph was built from, sorted
            by `qualified_name` so the result is deterministic regardless of input order.
        edges: Every known call relationship between them, sorted by `(caller, callee,
            line_number)`. Always empty unless a `CallGraphBuilder.build` call was given an
            explicit `call_edges` sequence -- see the module docstring.
    """

    nodes: tuple[CallableNode, ...] = ()
    edges: tuple[CallEdge, ...] = ()

    def __post_init__(self) -> None:
        """Validate that `nodes` and `edges` are sorted, unique, and internally consistent.

        Raises:
            ValidationError: If `nodes` is not sorted by `qualified_name`, contains a duplicate
                `qualified_name`, if `edges` is not sorted by `(caller, callee, line_number)`, or
                if any edge's `caller` is absent from `nodes` (a call graph only ever records
                calls *from* a callable it actually knows about; the `callee` end may reference a
                callable outside this graph's own inputs).
        """
        qualified_names = [node.qualified_name for node in self.nodes]
        if qualified_names != sorted(qualified_names):
            raise ValidationError("CallGraph: nodes must be sorted by qualified_name")
        if len(set(qualified_names)) != len(qualified_names):
            raise ValidationError("CallGraph: nodes must not contain duplicate qualified_name values")

        edge_keys = [(edge.caller, edge.callee, edge.line_number) for edge in self.edges]
        if edge_keys != sorted(edge_keys):
            raise ValidationError("CallGraph: edges must be sorted by (caller, callee, line_number)")

        known_names = set(qualified_names)
        for edge in self.edges:
            if edge.caller not in known_names:
                raise ValidationError(
                    "CallGraph: edge.caller must reference a node present in this graph",
                    details={"caller": edge.caller},
                )

    @property
    def node_count(self) -> int:
        """Total number of callables in this graph."""
        return len(self.nodes)

    @property
    def edge_count(self) -> int:
        """Total number of known call relationships in this graph."""
        return len(self.edges)

    def get_node(self, qualified_name: str) -> CallableNode:
        """Retrieve a single callable node by its `qualified_name`.

        Args:
            qualified_name: The callable's fully-qualified name to look up.

        Returns:
            The matching `CallableNode`.

        Raises:
            NotFoundError: If no node in this graph has that `qualified_name`.
        """
        for node in self.nodes:
            if node.qualified_name == qualified_name:
                return node
        raise NotFoundError(f"no callable node with qualified_name '{qualified_name}' in this graph")

    def callees_of(self, qualified_name: str) -> tuple[CallEdge, ...]:
        """Retrieve every known call made by the callable identified by `qualified_name`.

        Args:
            qualified_name: `CallableNode.qualified_name` of the calling callable.

        Returns:
            Every `CallEdge` with that `caller`, in this graph's own `(caller, callee,
            line_number)` order.
        """
        return tuple(edge for edge in self.edges if edge.caller == qualified_name)

    def to_mapping(self) -> dict[str, Any]:
        """Render this graph as a plain, JSON-safe nested structure.

        Returns:
            A dict with `"nodes"` and `"edges"` lists, each entry a dict of primitive values.
        """
        return {
            "nodes": [
                {
                    "qualified_name": node.qualified_name,
                    "name": node.name,
                    "kind": str(node.kind),
                    "relative_path": node.relative_path,
                    "line_number": node.line_number,
                }
                for node in self.nodes
            ],
            "edges": [
                {
                    "caller": edge.caller,
                    "callee": edge.callee,
                    "line_number": edge.line_number,
                }
                for edge in self.edges
            ],
        }


class CallGraphBuilder(ABC):
    """Assembles many files' declared callables -- and, where available, resolved call
    relationships between them -- into one repository-wide `CallGraph`.

    A concrete implementation decides which of a file's `ExtractedSymbol`s become `CallableNode`s
    (always `FUNCTION`/`METHOD` symbols only) and how to translate an externally-supplied
    `call_edges` sequence into this graph's own `CallEdge`s; it does not itself resolve which
    call site targets which callable -- see the module docstring for why that data is not
    currently available from any upstream Port.
    """

    @abstractmethod
    def build(
        self,
        extraction_results: Sequence[SymbolExtractionResult],
        call_edges: Sequence[CallEdge] = (),
    ) -> CallGraph:
        """Assemble a `CallGraph` from many files' declared callables.

        Args:
            extraction_results: The outcomes of extracting classes, functions, and constants for
                every file under consideration, as produced by `src.extractors.symbols`. Every
                entry must be successful -- see `require_successful_extractions`. Only `FUNCTION`
                and `METHOD` symbols become `CallableNode`s; `CLASS` and `CONSTANT` symbols are
                not part of a call graph.
            call_edges: Already-resolved call relationships to include, if any are available from
                outside this Port -- no upstream Phase 1-7 contract currently produces these (see
                the module docstring). Defaults to empty, producing a nodes-only `CallGraph`.

        Returns:
            A `CallGraph` whose `nodes` cover every `FUNCTION`/`METHOD` symbol across
            `extraction_results`, and whose `edges` mirror `call_edges` whose `caller` matches one
            of those nodes.

        Raises:
            ValidationError: If any entry in `extraction_results` is itself a failed extraction.
        """
        ...


def require_successful_extractions(
    extraction_results: Sequence[SymbolExtractionResult],
) -> Sequence[SymbolExtractionResult]:
    """Validate that every entry in `extraction_results` represents a successful extraction.

    Every `CallGraphBuilder.build` implementation calls this first, so a caller error (a
    `SymbolExtractionResult` with `succeeded=False` mixed into the sequence) is reported the same
    way -- as an immediate `ValidationError` -- across every implementation. `analyzers.tests.
    base` defines a same-shaped validator for this DTO, but it exists there for the tests
    analyzer's own domain-specific reasons; deliberately not reused here to avoid a `graph.
    callgraph -> analyzers.tests` dependency a future reader would have no reason to expect.

    Args:
        extraction_results: The raw `extraction_results` argument passed to `build`.

    Returns:
        `extraction_results`, unchanged.

    Raises:
        ValidationError: If any entry's `succeeded` is False.
    """
    for extraction_result in extraction_results:
        if not extraction_result.succeeded:
            _logger.debug(
                "Rejected graph build from an unsuccessful extraction of '%s'",
                extraction_result.relative_path,
            )
            raise ValidationError(
                "cannot build a call graph from a failed SymbolExtractionResult",
                details={"relative_path": extraction_result.relative_path},
            )
    return extraction_results


def is_callable_symbol_kind(kind: ExtractedSymbolKind) -> bool:
    """Report whether `kind` is one a call graph represents as a `CallableNode`.

    Args:
        kind: The `ExtractedSymbolKind` to check.

    Returns:
        True if `kind` is `FUNCTION` or `METHOD`.
    """
    return kind in _CALLABLE_SYMBOL_KINDS
