"""Tests for memory retrieval in repository-analysis pipelines."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from src.bootstrap.memory_steps import build_memory_aware_step
from src.domain.entities import RepositoryProvider, SourceRepository
from src.memory.base import MemoryRecord
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
