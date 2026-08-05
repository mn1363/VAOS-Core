"""The `GraphStore` Port: knowledge graph storage."""

from abc import ABC, abstractmethod
from typing import Any

from graph.models import GraphEdge, GraphNode


class GraphStore(ABC):
    """Stores and queries a graph of nodes and edges."""

    @abstractmethod
    async def add_node(self, node: GraphNode) -> None:
        """Add or update a node in the graph.

        Args:
            node: The node to add or update.
        """
        ...

    @abstractmethod
    async def add_edge(self, edge: GraphEdge) -> None:
        """Add or update an edge in the graph.

        Args:
            edge: The edge to add or update.
        """
        ...

    @abstractmethod
    async def neighbors(self, node_id: str) -> list[GraphNode]:
        """Retrieve every node directly connected to `node_id`.

        Args:
            node_id: Identifier of the node to inspect.

        Returns:
            The list of directly connected nodes.
        """
        ...

    @abstractmethod
    async def query(self, expression: str) -> list[dict[str, Any]]:
        """Run a backend-specific graph query.

        Args:
            expression: Query expression understood by the underlying
                graph engine.

        Returns:
            A list of result rows, each represented as a mapping.
        """
        ...
