"""Tests for memory retrieval in repository-analysis pipelines."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from src.bootstrap.memory_steps import (
    build_architecture_memory_persistence_step,
    build_memory_aware_step,
)
from src.domain.entities import RepositoryProvider, SourceRepository
from src.memory.base import MemoryRecord
from src.memory.contracts import create_architecture_memory_record
from src.pipeline.context import PipelineContext
from src.pipeline.steps import CallableStep
from src.storage.filesystem.memory import FilesystemMemoryStore


@pytest.mark.asyncio
async def test_retrieval_combines_project_and_repository_memory_by_recency(tmp_path: Path) -> None:
    store = FilesystemMemoryStore(tmp_path)
    repository = SourceRepository(
        name="vaos", source_uri="/tmp/vaos", provider=RepositoryProvider.FILESYSTEM
    )
    now = datetime(2026, 11, 28, tzinfo=UTC)
    project_record = MemoryRecord(
        id=uuid4(),
        memory_type="architecture_decision",
        content={"decision": "keep ports independent"},
        created_at=now,
        updated_at=now,
    )
    repository_record = MemoryRecord(
        id=uuid4(),
        memory_type="analysis_observation",
        content={"observation": "parser boundary"},
        entity_id=repository.id,
        created_at=now,
        updated_at=now + timedelta(minutes=1),
    )
    unrelated_record = MemoryRecord(
        id=uuid4(),
        memory_type="analysis_observation",
        content={"observation": "other repository"},
        entity_id=uuid4(),
        created_at=now,
        updated_at=now + timedelta(minutes=2),
    )
    for record in (project_record, repository_record, unrelated_record):
        await store.upsert(record)

    context = PipelineContext(values={"repositories": (repository,)})
    step = build_memory_aware_step(
        CallableStep("analysis_consumer", lambda: None, output_key="consumer_ran"), store
    )
    assert step.name == "analysis_consumer"
    await step.execute(context)

    assert context.require("consumer_ran") is None
    retrieved = context.require("memory_records_by_repository")[repository.id]
    assert retrieved == (repository_record, project_record)
    assert context.require("project_memory_records") == (project_record,)
    await store.aclose()


def test_retrieval_step_rejects_non_positive_limit(tmp_path: Path) -> None:
    store = FilesystemMemoryStore(tmp_path)
    with pytest.raises(ValueError, match="limit_per_scope must be positive"):
        build_memory_aware_step(
            CallableStep("noop", lambda: None, output_key="unused"), store, limit_per_scope=0
        )


@pytest.mark.asyncio
async def test_persistence_step_stores_only_explicit_approved_memory_before_retrieval(tmp_path: Path) -> None:
    store = FilesystemMemoryStore(tmp_path)
    repository = SourceRepository(
        name="vaos", source_uri="/tmp/vaos", provider=RepositoryProvider.FILESYSTEM
    )
    record = create_architecture_memory_record(
        record_id=uuid4(),
        approved_by="project_owner",
        approval_source="user_instruction",
        approval_reference="test-fixture",
        memory_type="architecture_constraint",
        expected_package_path=("src", "domain"),
        entity_id=repository.id,
    )
    context = PipelineContext(
        values={
            "repositories": (repository,),
            "architecture_memory_records_to_persist": (record,),
        }
    )

    persist_step = build_architecture_memory_persistence_step(store)
    await persist_step.execute(context)
    # Repeating the same step is an idempotent upsert, not a duplicate insert.
    await persist_step.execute(context)
    retrieval_step = build_memory_aware_step(
        CallableStep("analysis_consumer", lambda: None, output_key="consumer_ran"), store
    )
    await retrieval_step.execute(context)

    assert context.require("persisted_architecture_memory_ids") == (record.id,)
    assert await store.get(record.id) == record
    assert context.require("memory_records_by_repository")[repository.id] == (record,)
    await store.aclose()


@pytest.mark.asyncio
async def test_persistence_step_rejects_unapproved_memory_without_writing(tmp_path: Path) -> None:
    store = FilesystemMemoryStore(tmp_path)
    record = create_architecture_memory_record(
        record_id=uuid4(),
        approved_by="project_owner",
        approval_source="user_instruction",
        approval_reference="test-fixture",
        memory_type="architecture_constraint",
        expected_package_path=("src",),
    )
    inactive = MemoryRecord(
        id=record.id,
        memory_type=record.memory_type,
        content=record.content,
        metadata={**record.metadata, "status": "inactive"},
    )
    context = PipelineContext(values={"architecture_memory_records_to_persist": (inactive,)})

    with pytest.raises(ValueError, match="is not eligible"):
        await build_architecture_memory_persistence_step(store).execute(context)

    assert await store.get(record.id) is None
    await store.aclose()
