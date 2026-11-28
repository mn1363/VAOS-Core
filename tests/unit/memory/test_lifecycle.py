import asyncio
from uuid import uuid4

import pytest
from src.memory.contracts import create_architecture_memory_record
from src.memory.lifecycle import (
    ensure_no_active_architecture_conflict,
    revoke_architecture_memory,
    supersede_architecture_memory,
)
from src.storage.filesystem.memory import FilesystemMemoryStore


def make_record(record_id=None, *, path=("src", "domain")):
    return create_architecture_memory_record(
        record_id=record_id or uuid4(), memory_type="architecture_decision",
        expected_package_path=path, approved_by="project_owner", approval_source="user_instruction",
        approval_reference="decision-001", confidence=0.95,
    )


@pytest.mark.asyncio
async def test_supersede_keeps_old_record_and_links_replacement(tmp_path):
    store = FilesystemMemoryStore(tmp_path)
    old = make_record()
    new = make_record()
    await store.upsert(old)
    result = await supersede_architecture_memory(
        store, current_record_id=old.id, replacement=new, actor="project_owner",
        reason="approved package restructuring", reference="decision-002",
    )
    saved_old = await store.get(old.id)
    saved_new = await store.get(new.id)
    assert result.status == "superseded"
    assert saved_old is not None and saved_old.metadata["status"] == "superseded"
    assert saved_new is not None and saved_new.metadata["lifecycle"]["supersedes_record_id"] == str(old.id)


@pytest.mark.asyncio
async def test_supersede_rejects_different_scope_without_mutation(tmp_path):
    store = FilesystemMemoryStore(tmp_path)
    old = make_record()
    await store.upsert(old)
    with pytest.raises(ValueError, match="same decision type"):
        await supersede_architecture_memory(
            store, current_record_id=old.id, replacement=make_record(path=("src", "services")),
            actor="project_owner", reason="change", reference="decision-002",
        )
    assert await store.get(old.id) == old


@pytest.mark.asyncio
async def test_revoke_preserves_record_and_excludes_it_from_active_policy(tmp_path):
    store = FilesystemMemoryStore(tmp_path)
    record = make_record()
    await store.upsert(record)
    await revoke_architecture_memory(
        store, record_id=record.id, actor="project_owner", reason="decision withdrawn",
        reference="decision-003",
    )
    saved = await store.get(record.id)
    assert saved is not None
    assert saved.metadata["status"] == "revoked"
    assert saved.metadata["lifecycle"]["actor"] == "project_owner"



@pytest.mark.asyncio
async def test_conflict_guard_rejects_second_active_record_in_same_scope(tmp_path):
    store = FilesystemMemoryStore(tmp_path)
    existing = make_record()
    candidate = make_record()
    await store.upsert(existing)
    with pytest.raises(ValueError, match="active architecture decision already exists"):
        await ensure_no_active_architecture_conflict(store, candidate)


@pytest.mark.asyncio
async def test_conflict_guard_allows_different_package_scope(tmp_path):
    store = FilesystemMemoryStore(tmp_path)
    await store.upsert(make_record())
    await ensure_no_active_architecture_conflict(store, make_record(path=("src", "services")))


@pytest.mark.asyncio
async def test_concurrent_supersede_allows_only_one_transition(tmp_path):
    store = FilesystemMemoryStore(tmp_path)
    original = make_record()
    first = make_record()
    second = make_record()
    await store.upsert(original)

    async def replace(candidate):
        return await supersede_architecture_memory(
            store, current_record_id=original.id, replacement=candidate,
            actor="project_owner", reason="approved change", reference="decision-004",
        )

    results = await asyncio.gather(replace(first), replace(second), return_exceptions=True)
    assert sum(not isinstance(result, BaseException) for result in results) == 1
    assert sum(isinstance(result, ValueError) for result in results) == 1
    saved_original = await store.get(original.id)
    assert saved_original is not None
    assert saved_original.metadata["status"] == "superseded"
    assert (await store.exists(first.id)) != (await store.exists(second.id))
