"""Shared serialization and query helpers for persistent memory drivers."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from src.memory.base import MemoryQuery, MemoryRecord, matches_query


def memory_record_to_dict(record: MemoryRecord) -> dict[str, Any]:
    """Return a JSON-safe representation of a memory record."""
    return {
        "id": str(record.id),
        "memory_type": record.memory_type,
        "content": record.content,
        "metadata": record.metadata,
        "entity_id": str(record.entity_id) if record.entity_id is not None else None,
        "created_at": record.created_at.isoformat(),
        "updated_at": record.updated_at.isoformat(),
    }


def memory_record_from_dict(data: dict[str, Any]) -> MemoryRecord:
    """Reconstruct a memory record from its stored representation."""
    entity_id = data.get("entity_id")
    return MemoryRecord(
        id=UUID(str(data["id"])),
        memory_type=str(data["memory_type"]),
        content=dict(data["content"]),
        metadata=dict(data["metadata"]),
        entity_id=UUID(str(entity_id)) if entity_id is not None else None,
        created_at=datetime.fromisoformat(str(data["created_at"])),
        updated_at=datetime.fromisoformat(str(data["updated_at"])),
    )


def filter_memory_records(
    records: list[MemoryRecord], request: MemoryQuery
) -> tuple[MemoryRecord, ...]:
    """Apply the shared exact-match filter and stable ordering."""
    matched = [record for record in records if matches_query(record, request)]
    matched.sort(key=lambda record: str(record.id))
    return tuple(matched[: request.limit])
