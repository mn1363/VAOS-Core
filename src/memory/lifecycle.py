from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from src.memory.base import MemoryQuery, MemoryRecord, MemoryStore
from src.memory.contracts import ArchitectureMemoryContent, has_architecture_approval_provenance
from src.memory.policy import memory_is_eligible


@dataclass(frozen=True, slots=True)
class ArchitectureMemoryTransition:
    previous_record_id: UUID
    current_record_id: UUID
    status: str


def _validated_active_record(record: MemoryRecord | None, record_id: UUID) -> MemoryRecord:
    if record is None:
        raise ValueError(f"architecture memory record {record_id} does not exist")
    if not memory_is_eligible(record, analyzer="architecture"):
        raise ValueError(f"architecture memory record {record_id} is not active and eligible")
    if ArchitectureMemoryContent.from_record(record) is None:
        raise ValueError(f"architecture memory record {record_id} has an invalid payload")
    if not has_architecture_approval_provenance(record):
        raise ValueError(f"architecture memory record {record_id} has no approval provenance")
    return record


def _metadata_with_lifecycle(
    record: MemoryRecord, *, status: str, action: str, actor: str, reason: str, reference: str
) -> dict[str, Any]:
    if not actor.strip() or not reason.strip() or not reference.strip():
        raise ValueError("lifecycle transition requires actor, reason, and reference")
    metadata = dict(record.metadata)
    metadata["status"] = status
    metadata["lifecycle"] = {
        "action": action,
        "actor": actor.strip(),
        "reason": reason.strip(),
        "reference": reference.strip(),
        "changed_at": datetime.now(UTC).isoformat(),
    }
    return metadata


async def supersede_architecture_memory(
    store: MemoryStore,
    *,
    current_record_id: UUID,
    replacement: MemoryRecord,
    actor: str,
    reason: str,
    reference: str,
) -> ArchitectureMemoryTransition:
    """Replace one active decision while retaining both records and their audit metadata."""
    current = _validated_active_record(await store.get(current_record_id), current_record_id)
    if replacement.id == current.id:
        raise ValueError("replacement must have a new stable record id")
    if not memory_is_eligible(replacement, analyzer="architecture"):
        raise ValueError("replacement record must be active and eligible")
    if ArchitectureMemoryContent.from_record(replacement) is None:
        raise ValueError("replacement record has an invalid architecture payload")
    if not has_architecture_approval_provenance(replacement):
        raise ValueError("replacement record has no approval provenance")
    if (replacement.memory_type, replacement.entity_id, replacement.content.get("expected_package_path")) != (
        current.memory_type, current.entity_id, current.content.get("expected_package_path")
    ):
        raise ValueError("replacement must target the same decision type, repository, and package scope")
    if await store.exists(replacement.id):
        raise ValueError("replacement record id already exists")

    old_updated = MemoryRecord(
        id=current.id, memory_type=current.memory_type, content=dict(current.content),
        metadata=_metadata_with_lifecycle(
            current, status="superseded", action="superseded", actor=actor, reason=reason, reference=reference
        ), entity_id=current.entity_id, created_at=current.created_at, updated_at=datetime.now(UTC),
    )
    new_metadata = dict(replacement.metadata)
    new_metadata["lifecycle"] = {
        "action": "replacement", "supersedes_record_id": str(current.id),
        "reason": reason.strip(), "reference": reference.strip(), "changed_at": datetime.now(UTC).isoformat(),
    }
    new_record = MemoryRecord(
        id=replacement.id, memory_type=replacement.memory_type, content=dict(replacement.content),
        metadata=new_metadata, entity_id=replacement.entity_id,
        created_at=replacement.created_at, updated_at=datetime.now(UTC),
    )
    replaced = await store.atomic_replace(current, (old_updated, new_record))
    if not replaced:
        raise ValueError(
            "architecture decision changed during supersede; reload it and retry the transition"
        )
    return ArchitectureMemoryTransition(current.id, new_record.id, "superseded")


async def revoke_architecture_memory(
    store: MemoryStore,
    *,
    record_id: UUID,
    actor: str,
    reason: str,
    reference: str,
) -> ArchitectureMemoryTransition:
    """Revoke an active decision without deleting its audit history."""
    current = _validated_active_record(await store.get(record_id), record_id)
    revoked = MemoryRecord(
        id=current.id, memory_type=current.memory_type, content=dict(current.content),
        metadata=_metadata_with_lifecycle(
            current, status="revoked", action="revoked", actor=actor, reason=reason, reference=reference
        ), entity_id=current.entity_id, created_at=current.created_at, updated_at=datetime.now(UTC),
    )
    replaced = await store.atomic_replace(current, (revoked,))
    if not replaced:
        raise ValueError(
            "architecture decision changed during revoke; reload it and retry the transition"
        )
    return ArchitectureMemoryTransition(current.id, current.id, "revoked")


async def ensure_no_active_architecture_conflict(store: MemoryStore, record: MemoryRecord) -> None:
    """Reject a second active record for the same type, repository, and package scope."""
    request = MemoryQuery(
        memory_type=record.memory_type,
        entity_id=record.entity_id,
        entity_id_is_null=record.entity_id is None,
        limit=2_147_483_647,
    )
    existing = await store.query(request)
    expected_path = record.content.get("expected_package_path")
    for candidate in existing.records:
        if candidate.id == record.id or candidate.metadata.get("status") != "active":
            continue
        if candidate.content.get("expected_package_path") == expected_path:
            raise ValueError(
                "an active architecture decision already exists for this type, repository, and package scope; "
                "use supersede_architecture_memory first"
            )


async def persist_architecture_memory_if_no_conflict(
    store: MemoryStore, record: MemoryRecord
) -> None:
    """Atomically insert an approved active architecture record into an unused scope."""
    created = await store.create_if_no_active_scope_conflict(record)
    if not created:
        raise ValueError(
            "an active architecture decision already exists for this type, repository, and package scope; "
            "use supersede_architecture_memory first"
        )
