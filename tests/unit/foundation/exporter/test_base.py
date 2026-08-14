"""Unit tests for `src.foundation.exporter.base`."""

from uuid import UUID

import pytest
from src.core.exceptions import ValidationError
from src.extractors.foundation.base import FoundationCandidateKind
from src.foundation.exporter.base import (
    DEFAULT_FOUNDATION_EXPORT_FORMAT_VERSION,
    FoundationExport,
    FoundationExporter,
    compute_export_checksum,
)
from src.foundation.merger.base import FoundationMember, FoundationResult

REPO_A = UUID("11111111-1111-1111-1111-111111111111")

_VALID_CHECKSUM = "a" * 64


def _member(subject_id: str = "a", score: float = 0.5) -> FoundationMember:
    """Build a minimal `FoundationMember` for use in exporter tests."""
    return FoundationMember(
        subject_id=subject_id,
        repository_id=REPO_A,
        name="retry",
        kind=FoundationCandidateKind.FUNCTION,
        relative_path="a.py",
        score=score,
    )


def test_default_foundation_export_format_version_is_a_non_blank_string() -> None:
    """The default format version constant should be a usable, non-blank string."""
    assert DEFAULT_FOUNDATION_EXPORT_FORMAT_VERSION.strip() != ""


def test_compute_export_checksum_is_deterministic() -> None:
    """Computing the checksum twice for the same payload should yield the same digest."""
    payload = {"members": [{"subject_id": "a", "score": 0.5}]}
    assert compute_export_checksum(payload) == compute_export_checksum(payload)


def test_compute_export_checksum_is_independent_of_key_order() -> None:
    """Two dicts with the same keys inserted in different orders should hash identically."""
    first = {"a": 1, "b": 2}
    second = {"b": 2, "a": 1}
    assert compute_export_checksum(first) == compute_export_checksum(second)


def test_compute_export_checksum_differs_for_different_payloads() -> None:
    """Two meaningfully different payloads should hash differently."""
    assert compute_export_checksum({"a": 1}) != compute_export_checksum({"a": 2})


def test_compute_export_checksum_returns_a_64_character_hex_digest() -> None:
    """The returned checksum should be a 64-character lowercase hex string."""
    checksum = compute_export_checksum({"a": 1})
    assert len(checksum) == 64
    assert all(c in "0123456789abcdef" for c in checksum)


def test_compute_export_checksum_rejects_a_non_json_safe_payload() -> None:
    """A payload containing a value `json.dumps` cannot render should raise."""
    with pytest.raises(ValidationError):
        compute_export_checksum({"bad": object()})


def test_foundation_export_accepts_valid_fields() -> None:
    """A well-formed export should construct cleanly."""
    export = FoundationExport(
        format_version="1.0", member_count=1, payload={"members": []}, checksum=_VALID_CHECKSUM
    )
    assert export.member_count == 1


def test_foundation_export_is_frozen() -> None:
    """`FoundationExport` should be immutable once constructed."""
    export = FoundationExport(
        format_version="1.0", member_count=0, payload={}, checksum=_VALID_CHECKSUM
    )
    with pytest.raises(AttributeError):
        export.member_count = 1  # type: ignore[misc]


def test_foundation_export_rejects_blank_format_version() -> None:
    """A blank `format_version` should raise."""
    with pytest.raises(ValidationError):
        FoundationExport(format_version=" ", member_count=0, payload={}, checksum=_VALID_CHECKSUM)


def test_foundation_export_rejects_negative_member_count() -> None:
    """A negative `member_count` should raise."""
    with pytest.raises(ValidationError):
        FoundationExport(
            format_version="1.0", member_count=-1, payload={}, checksum=_VALID_CHECKSUM
        )


def test_foundation_export_rejects_a_short_checksum() -> None:
    """A `checksum` shorter than 64 characters should raise."""
    with pytest.raises(ValidationError):
        FoundationExport(format_version="1.0", member_count=0, payload={}, checksum="abc")


def test_foundation_export_rejects_a_non_hex_checksum() -> None:
    """A `checksum` containing non-hex characters should raise."""
    with pytest.raises(ValidationError):
        FoundationExport(
            format_version="1.0", member_count=0, payload={}, checksum="z" * 64
        )


def test_foundation_export_rejects_an_uppercase_checksum() -> None:
    """A `checksum` using uppercase hex digits should raise -- lowercase only."""
    with pytest.raises(ValidationError):
        FoundationExport(
            format_version="1.0", member_count=0, payload={}, checksum="A" * 64
        )


def test_foundation_exporter_cannot_be_instantiated_directly() -> None:
    """The abstract `FoundationExporter` Port must not be instantiable."""
    with pytest.raises(TypeError):
        FoundationExporter()  # type: ignore[abstract]


def test_result_to_mapping_checksum_round_trips_through_export_construction() -> None:
    """A `FoundationExport` built from a result's own mapping and checksum should validate."""
    result = FoundationResult(members=(_member(subject_id="a", score=0.75),))
    payload = result.to_mapping()
    export = FoundationExport(
        format_version=DEFAULT_FOUNDATION_EXPORT_FORMAT_VERSION,
        member_count=result.member_count,
        payload=payload,
        checksum=compute_export_checksum(payload),
    )
    assert export.member_count == 1
    assert export.payload == payload
