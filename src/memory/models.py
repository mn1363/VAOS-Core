"""Data structures used by the memory subsystem."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class MemoryEntry:
    """A single stored memory entry.

    Attributes:
        key: Key the entry is stored under.
        value: Stored value.
        expires_at: Timestamp after which the entry is no longer valid,
            or None if the entry does not expire.
    """

    key: str
    value: Any
    expires_at: datetime | None = None
