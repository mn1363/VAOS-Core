"""The `VectorStore` Port: embedding storage and similarity search."""

from abc import ABC, abstractmethod

from vector.models import VectorMatch, VectorRecord


class VectorStore(ABC):
    """Stores embedding vectors and performs similarity search over them."""

    @abstractmethod
    async def upsert(self, record: VectorRecord) -> None:
        """Insert or update a vector record.

        Args:
            record: The vector record to store.
        """
        ...

    @abstractmethod
    async def query(self, vector: list[float], top_k: int = 10) -> list[VectorMatch]:
        """Find the records most similar to `vector`.

        Args:
            vector: Query embedding to compare stored vectors against.
            top_k: Maximum number of matches to return.

        Returns:
            The closest matches, ordered from most to least similar.
        """
        ...

    @abstractmethod
    async def delete(self, record_id: str) -> None:
        """Remove a vector record.

        Args:
            record_id: Identifier of the record to remove.
        """
        ...
