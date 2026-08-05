"""Data transfer objects representing `Task` entities."""

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID


@dataclass(frozen=True, slots=True)
class TaskDTO:
    """Flat, transport-friendly representation of a `Task`.

    Attributes:
        id: Identifier of the task.
        name: Human-readable name identifying the kind of work.
        status: Current lifecycle status, as a plain string.
        payload: Freeform structured data required to execute the task.
    """

    id: UUID
    name: str
    status: str
    payload: dict[str, Any] = field(default_factory=dict)
