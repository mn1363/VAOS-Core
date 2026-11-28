from uuid import uuid4

from src.memory.base import MemoryRecord
from src.memory.policy import memory_is_eligible, select_memory_for_analyzer


def _memory(memory_type: str, metadata: dict[str, object]) -> MemoryRecord:
    return MemoryRecord(
        id=uuid4(), memory_type=memory_type, content={"decision": "test"}, metadata=metadata
    )


def _valid_metadata(*, scopes: list[str] | None = None) -> dict[str, object]:
    return {
        "status": "active",
        "confidence": 0.9,
        "analysis_scopes": scopes or ["architecture"],
    }


def test_memory_policy_accepts_only_explicit_high_confidence_scoped_records() -> None:
    record = _memory("architecture_decision", _valid_metadata())

    assert memory_is_eligible(record, analyzer="architecture")
    assert select_memory_for_analyzer((record,), analyzer="architecture") == (record,)


def test_memory_policy_rejects_unknown_type_inactive_low_confidence_and_wrong_scope() -> None:
    valid = _valid_metadata()
    candidates = (
        _memory("unknown", valid),
        _memory("architecture_decision", {**valid, "status": "deprecated"}),
        _memory("architecture_decision", {**valid, "confidence": 0.79}),
        _memory("architecture_decision", _valid_metadata(scopes=["security"])),
        _memory("architecture_decision", {**valid, "confidence": True}),
        _memory("architecture_decision", {**valid, "analysis_scopes": "architecture"}),
    )

    assert select_memory_for_analyzer(candidates, analyzer="architecture") == ()


def test_memory_policy_is_analyzer_specific_and_deterministic() -> None:
    first = _memory("security_policy", _valid_metadata(scopes=["security"]))
    second = _memory("architecture_decision", _valid_metadata())
    records = (first, second)

    assert select_memory_for_analyzer(records, analyzer="architecture") == (second,)
    assert select_memory_for_analyzer(records, analyzer="security") == (first,)
    assert select_memory_for_analyzer(records, analyzer="unknown") == ()
