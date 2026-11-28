"""Typed payload contracts and safe factories for project memory producers."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from src.core.exceptions import ValidationError
from src.memory.base import MemoryRecord

_ARCHITECTURE_MEMORY_TYPES = frozenset({"architecture_decision", "architecture_constraint"})


@dataclass(frozen=True, slots=True)
class ArchitectureMemoryContent:
    """A typed package-placement expectation stored in an architecture memory record."""

    expected_package_path: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.expected_package_path or any(
            not isinstance(segment, str) or not segment.strip() for segment in self.expected_package_path
        ):
            raise ValidationError("ArchitectureMemoryContent: expected_package_path must contain non-empty segments")

    @classmethod
    def from_record(cls, record: MemoryRecord) -> "ArchitectureMemoryContent | None":
        """Parse the supported payload. Return None for unknown or malformed content."""
        if record.memory_type not in _ARCHITECTURE_MEMORY_TYPES:
            return None
        raw_path: Any = record.content.get("expected_package_path")
        if not isinstance(raw_path, (list, tuple)) or not raw_path:
            return None
        if any(not isinstance(segment, str) or not segment.strip() for segment in raw_path):
            return None
        return cls(expected_package_path=tuple(raw_path))


def create_architecture_memory_record(
    *,
    record_id: UUID,
    memory_type: str,
    expected_package_path: tuple[str, ...],
    approved_by: str,
    approval_source: str,
    approval_reference: str,
    confidence: float = 1.0,
    entity_id: UUID | None = None,
    approved_at: datetime | None = None,
) -> MemoryRecord:
    """Create an active, explicitly scoped architecture memory record.

    This factory is for trusted project-memory producers. It does not infer or
    approve decisions from source text.
    """
    if memory_type not in _ARCHITECTURE_MEMORY_TYPES:
        raise ValidationError("unsupported architecture memory_type")
    content = ArchitectureMemoryContent(expected_package_path=expected_package_path)
    if not approved_by.strip() or not approval_source.strip() or not approval_reference.strip():
        raise ValidationError("architecture memory requires approval identity, source, and reference")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0.8 <= confidence <= 1.0:
        raise ValidationError("architecture memory confidence must be between 0.8 and 1.0")
    return MemoryRecord(
        id=record_id,
        memory_type=memory_type,
        content={"expected_package_path": list(content.expected_package_path)},
        metadata={
            "status": "active",
            "confidence": float(confidence),
            "analysis_scopes": ["architecture"],
            "approval": {
                "approved_by": approved_by.strip(),
                "source": approval_source.strip(),
                "reference": approval_reference.strip(),
                "approved_at": (approved_at or datetime.now(UTC)).isoformat(),
            },
        },
        entity_id=entity_id,
    )



def has_architecture_approval_provenance(record: MemoryRecord) -> bool:
    """Check that a record carries explicit, auditable approval provenance."""
    approval = record.metadata.get("approval")
    if not isinstance(approval, dict):
        return False
    required = ("approved_by", "source", "reference", "approved_at")
    if any(not isinstance(approval.get(key), str) or not approval[key].strip() for key in required):
        return False
    try:
        datetime.fromisoformat(approval["approved_at"])
    except ValueError:
        return False
    return True
