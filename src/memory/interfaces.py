"""The `MemoryStore` Port: short- and medium-term AI memory storage."""

from abc import ABC, abstractmethod
from typing import Any


class MemoryStore(ABC):
    """Stores and retrieves freeform memory entries keyed by string."""

    @abstractmethod
    async def get(self, key: str) -> Any | None:
        """Retrieve a memory entry.

        Args:
            key: Key the entry was stored under.

        Returns:
            The stored value, or None if no entry exists for `key`.
        """
        ...

    @abstractmethod
    async def set(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        """Store a memory entry.

        Args:
            key: Key to store the entry under.
            value: Value to store.
            ttl_seconds: Optional time-to-live, in seconds, after which the
                entry may be evicted.
        """
        ...

    @abstractmethod
    async def delete(self, key: str) -> None:
        """Remove a memory entry.

        Args:
            key: Key of the entry to remove.
        """
        ...
