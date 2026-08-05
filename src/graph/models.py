"""Data structures used by the graph subsystem."""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class GraphNode:
    """A single node in the knowledge graph.

    Attributes:
        id: Unique identifier of the node.
        label: Category or type label for the node.
        properties: Freeform properties attached to the node.
    """

    id: str
    label: str
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class GraphEdge:
    """A single directed edge in the knowledge graph.

    Attributes:
        source_id: Identifier of the edge's source node.
        target_id: Identifier of the edge's target node.
        relation: Name describing the relationship the edge represents.
        properties: Freeform properties attached to the edge.
    """

    source_id: str
    target_id: str
    relation: str
    properties: dict[str, Any] = field(default_factory=dict)
