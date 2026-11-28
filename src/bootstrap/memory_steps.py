"""Memory retrieval adapter for repository-analysis pipeline steps."""

from __future__ import annotations

from uuid import UUID

from src.domain.entities import SourceRepository
from src.memory.base import MemoryQuery, MemoryRecord, MemoryStore
from src.memory.contracts import ArchitectureMemoryContent, has_architecture_approval_provenance
from src.memory.lifecycle import persist_architecture_memory_if_no_conflict
from src.memory.policy import memory_is_eligible
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


class _PersistApprovedArchitectureMemoryStep(Step):
    """Persist only explicitly supplied, validated architecture memory records."""

    def __init__(self, store: MemoryStore) -> None:
        self._store = store

    @property
    def name(self) -> str:
        return "persist_approved_architecture_memory"

    async def execute(self, context: PipelineContext) -> PipelineContext:
        records = context.get("architecture_memory_records_to_persist", ())
        if not isinstance(records, (tuple, list)):
            raise TypeError("architecture_memory_records_to_persist must be a tuple or list")
        repositories: tuple[SourceRepository, ...] = tuple(context.get("repositories", ()))
        repository_ids = {repository.id for repository in repositories}
        persisted_ids: list[UUID] = []
        for record in records:
            if not isinstance(record, MemoryRecord):
                raise TypeError("architecture memory input must contain MemoryRecord values")
            if not memory_is_eligible(record, analyzer="architecture"):
                raise ValueError(f"architecture memory record {record.id} is not eligible")
            if ArchitectureMemoryContent.from_record(record) is None:
                raise ValueError(f"architecture memory record {record.id} has an invalid payload")
            if not has_architecture_approval_provenance(record):
                raise ValueError(f"architecture memory record {record.id} has no approval provenance")
            if record.entity_id is not None and record.entity_id not in repository_ids:
                raise ValueError(f"architecture memory record {record.id} references an unknown repository")
            await persist_architecture_memory_if_no_conflict(self._store, record)
            persisted_ids.append(record.id)
        context.set("persisted_architecture_memory_ids", tuple(persisted_ids))
        return context


def build_architecture_memory_persistence_step(store: MemoryStore) -> Step:
    """Build an idempotent persistence step for caller-approved architecture memory.

    Callers provide records under `architecture_memory_records_to_persist`. Stable record IDs
    make repeated pipeline runs safe because MemoryStore.upsert replaces the same record.
    No memory is inferred from source code or analyzer output.
    """
    return _PersistApprovedArchitectureMemoryStep(store)


class _MemoryAwareStep(Step):
    """Retrieve memory before a step without changing the pipeline's public step sequence."""

    def __init__(self, step: Step, store: MemoryStore, *, limit_per_scope: int = 100) -> None:
        if limit_per_scope <= 0:
            raise ValueError("limit_per_scope must be positive")
        self._step = step
        self._store = store
        self._limit_per_scope = limit_per_scope
        self._persistence_step = _PersistApprovedArchitectureMemoryStep(store)

    @property
    def name(self) -> str:
        return self._step.name

    async def execute(self, context: PipelineContext) -> PipelineContext:
        await self._persistence_step.execute(context)
        await _retrieve_memory(self._store, context, limit_per_scope=self._limit_per_scope)
        return await self._step.execute(context)


def build_memory_aware_step(step: Step, store: MemoryStore, *, limit_per_scope: int = 100) -> Step:
    """Wrap the first analysis step so its context includes relevant persistent memory."""
    return _MemoryAwareStep(step, store, limit_per_scope=limit_per_scope)
