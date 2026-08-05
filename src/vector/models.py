"""Data structures used by the vector subsystem."""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class VectorRecord:
    """A single embedding vector and its associated metadata.

    Attributes:
        id: Unique identifier of the record.
        vector: The embedding values.
        metadata: Freeform metadata associated with the vector.
    """

    id: str
    vector: list[float]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class VectorMatch:
    """A single similarity search result.

    Attributes:
        record: The matched vector record.
        score: Similarity score between the query and this record.
    """

    record: VectorRecord
    score: float
