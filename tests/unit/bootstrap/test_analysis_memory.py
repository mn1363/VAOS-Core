from dataclasses import dataclass
from uuid import uuid4

import pytest
from src.bootstrap.analysis_steps import (
    RepositoryScoped,
    _analyze_repository_result_func,
    _MemoryAwareAnalysisMapStep,
)
from src.memory.base import MemoryRecord
from src.pipeline.context import PipelineContext


@dataclass(frozen=True)
class _Extraction:
    relative_path: str


class _MemoryAwareAnalyzer:
    def __init__(self) -> None:
        self.received: tuple[MemoryRecord, ...] | None = None

    def analyze_with_memory(
        self, extraction: _Extraction, memory_records: tuple[MemoryRecord, ...]
    ) -> tuple[str, tuple[str, ...]]:
        self.received = memory_records
        return extraction.relative_path, tuple(record.memory_type for record in memory_records)


def _record(entity_id):
    return MemoryRecord(
        id=uuid4(),
        memory_type="architecture_decision",
        content={"note": "test"},
        entity_id=entity_id,
        metadata={
            "status": "active",
            "confidence": 0.95,
            "analysis_scopes": ["architecture"],
        },
    )


@pytest.mark.asyncio
async def test_analysis_step_passes_only_memory_for_owning_repository() -> None:
    first_id, second_id = uuid4(), uuid4()
    first_record, second_record = _record(first_id), _record(second_id)
    items = (
        RepositoryScoped(first_id, _Extraction("first.py")),
        RepositoryScoped(second_id, _Extraction("second.py")),
    )
    received = []

    def analyze(item, memories):
        received.append((item.repository_id, tuple(record.id for record in memories)))
        return RepositoryScoped(item.repository_id, item.result.relative_path)

    step = _MemoryAwareAnalysisMapStep(
        "analyze_test", analyze, input_key="inputs", output_key="outputs"
    )
    context = PipelineContext(
        values={
            "inputs": items,
            "memory_records_by_repository": {
                first_id: (first_record,),
                second_id: (second_record,),
            },
        }
    )
    await step.execute(context)

    assert received == [(first_id, (first_record.id,)), (second_id, (second_record.id,))]
    assert tuple(item.result for item in context.require("outputs")) == ("first.py", "second.py")


def test_analyzer_memory_extension_receives_records_and_preserves_repository_id() -> None:
    repository_id = uuid4()
    record = _record(repository_id)
    analyzer = _MemoryAwareAnalyzer()
    analyze = _analyze_repository_result_func(
        analyzer,
        lambda **kwargs: kwargs["error_message"],
        analyzer_scope="architecture",
    )

    result = analyze(RepositoryScoped(repository_id, _Extraction("src/module.py")), (record,))

    assert result.repository_id == repository_id
    assert result.result == ("src/module.py", ("architecture_decision",))
    assert analyzer.received == (record,)
