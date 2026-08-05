"""Data transfer objects representing `Artifact` entities across boundaries."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID


@dataclass(frozen=True, slots=True)
class ArtifactDTO:
    """Flat, transport-friendly representation of an `Artifact`.

    Attributes:
        id: Identifier of the artifact.
        name: Human-readable name of the artifact.
        source_uri: Location the artifact was collected from.
        status: Current lifecycle status, as a plain string.
        metadata: Freeform metadata values.
        created_at: Timestamp the artifact was first created.
    """

    id: UUID
    name: str
    source_uri: str
    status: str
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime | None = None
