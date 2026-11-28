"""Memory retrieval adapter for repository-analysis pipeline steps."""

from __future__ import annotations

from uuid import UUID

from src.domain.entities import SourceRepository
from src.memory.base import MemoryQuery, MemoryRecord, MemoryStore
from src.pipeline.base import Step
from src.pipeline.context import PipelineContext


async def _retrieve_memory(
    store: MemoryStore, context: PipelineContext, *, limit_per_scope: int
) -> None:
    """Load project-wide and repository-specific records into the analysis context."""
    repositories: tuple[SourceRepository, ...] = tuple(context.require("repositories"))
    project_result = await store.query(MemoryQuery(entity_id_is_null=True, limit=limit_per_scope))
    project_records = project_result.records
    records_by_repository: dict[UUID, tuple[MemoryRecord, ...]] = {}
    for repository in repositories:
        entity_result = await store.query(
            MemoryQuery(entity_id=repository.id, limit=limit_per_scope)
        )
        unique = {record.id: record for record in (*project_records, *entity_result.records)}
        ordered = sorted(
            unique.values(), key=lambda record: (-record.updated_at.timestamp(), str(record.id))
        )
        records_by_repository[repository.id] = tuple(ordered[:limit_per_scope])
    context.set("memory_records_by_repository", records_by_repository)
    context.set("project_memory_records", project_records)


class _MemoryAwareStep(Step):
    """Retrieve memory before a step without changing the pipeline's public step sequence."""

    def __init__(self, step: Step, store: MemoryStore, *, limit_per_scope: int = 100) -> None:
        if limit_per_scope <= 0:
            raise ValueError("limit_per_scope must be positive")
        self._step = step
        self._store = store
        self._limit_per_scope = limit_per_scope

    @property
    def name(self) -> str:
        return self._step.name

    async def execute(self, context: PipelineContext) -> PipelineContext:
        await _retrieve_memory(self._store, context, limit_per_scope=self._limit_per_scope)
        return await self._step.execute(context)


def build_memory_aware_step(step: Step, store: MemoryStore, *, limit_per_scope: int = 100) -> Step:
    """Wrap the first analysis step so its context includes relevant persistent memory."""
    return _MemoryAwareStep(step, store, limit_per_scope=limit_per_scope)
