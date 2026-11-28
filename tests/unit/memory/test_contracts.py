"""Tests for typed memory payload contracts and producer helpers."""

from uuid import uuid4

import pytest
from src.core.exceptions import ValidationError
from src.memory.contracts import ArchitectureMemoryContent, create_architecture_memory_record


def test_architecture_memory_factory_creates_active_scoped_record() -> None:
    record = create_architecture_memory_record(
        record_id=uuid4(),
        approved_by="project_owner",
        approval_source="user_instruction",
        approval_reference="test-fixture",
        memory_type="architecture_constraint",
        expected_package_path=("src", "domain"),
        confidence=0.95,
    )

    assert record.content == {"expected_package_path": ["src", "domain"]}
    assert record.metadata["status"] == "active"
    assert record.metadata["confidence"] == 0.95
    assert record.metadata["analysis_scopes"] == ["architecture"]
    assert record.metadata["approval"]["approved_by"] == "project_owner"
    assert record.metadata["approval"]["source"] == "user_instruction"
    assert record.metadata["approval"]["reference"] == "test-fixture"
    assert ArchitectureMemoryContent.from_record(record) == ArchitectureMemoryContent(
        expected_package_path=("src", "domain")
    )


@pytest.mark.parametrize("confidence", [0.79, 1.01, True, float("nan")])
def test_architecture_memory_factory_rejects_invalid_confidence(confidence: float) -> None:
    with pytest.raises(ValidationError):
        create_architecture_memory_record(
            record_id=uuid4(),
            approved_by="project_owner",
            approval_source="user_instruction",
            approval_reference="test-fixture",
            memory_type="architecture_decision",
            expected_package_path=("src",),
            confidence=confidence,
        )


def test_architecture_memory_factory_rejects_unknown_memory_type() -> None:
    with pytest.raises(ValidationError):
        create_architecture_memory_record(
            record_id=uuid4(),
            approved_by="project_owner",
            approval_source="user_instruction",
            approval_reference="test-fixture",
            memory_type="freeform_note",
            expected_package_path=("src",),
        )


def test_architecture_memory_factory_rejects_empty_path_segments() -> None:
    with pytest.raises(ValidationError):
        create_architecture_memory_record(
            record_id=uuid4(),
            approved_by="project_owner",
            approval_source="user_instruction",
            approval_reference="test-fixture",
            memory_type="architecture_constraint",
            expected_package_path=("src", ""),
        )
