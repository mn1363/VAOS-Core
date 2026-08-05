"""The `Task` entity: a unit of asynchronous work within VAOS."""

from dataclasses import dataclass, field
from typing import Any

from domain.entities.base import Entity
from domain.enums.status import TaskStatus


@dataclass(eq=False, kw_only=True)
class Task(Entity):
    """A unit of work that can be scheduled, executed and tracked.

    Attributes:
        name: Human-readable name identifying the kind of work.
        status: Current lifecycle status of the task.
        payload: Freeform structured data required to execute the task.
    """

    name: str
    status: TaskStatus = TaskStatus.PENDING
    payload: dict[str, Any] = field(default_factory=dict)
