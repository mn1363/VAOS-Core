"""Base entity type shared by every domain entity."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4


@dataclass(kw_only=True)
class Entity:
    """Base class for domain entities identified by a stable UUID.

    Two entities are considered equal when their `id` fields match,
    regardless of any other attribute, which matches standard DDD entity
    semantics (as opposed to value object equality). Subclasses must be
    declared with `@dataclass(eq=False, kw_only=True)` so this identity
    based equality is inherited rather than overwritten by a generated,
    field-by-field `__eq__`.

    Attributes:
        id: Stable, globally unique identifier for this entity.
        created_at: Timestamp at which the entity was first created.
    """

    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __eq__(self, other: object) -> bool:
        """Compare entities by identity rather than by attribute values.

        Args:
            other: The object to compare against.

        Returns:
            True if `other` is an `Entity` with the same `id`.
        """
        if not isinstance(other, Entity):
            return NotImplemented
        return self.id == other.id

    def __hash__(self) -> int:
        """Hash the entity using its identity, matching `__eq__` semantics.

        Returns:
            Hash of the entity's `id`.
        """
        return hash(self.id)
