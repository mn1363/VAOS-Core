"""Base domain event type."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4


@dataclass(frozen=True, kw_only=True)
class DomainEvent:
    """Base class for immutable events raised by the domain layer.

    Attributes:
        event_id: Unique identifier of this event occurrence.
        occurred_at: Timestamp at which the event occurred.
    """

    event_id: UUID = field(default_factory=uuid4)
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))
