"""Foundation exporter Port: stable, deterministic export of a Foundation result.

`FoundationExporter` turns a `foundation.merger.base.FoundationResult` into a `FoundationExport`
-- a plain, JSON-safe rendering of that result (`FoundationResult.to_mapping`), tagged with a
format version so a future consumer can detect a breaking change to the export shape itself
independent of the `FoundationResult` data it wraps, and a SHA-256 checksum over the payload's
canonical JSON form (mirroring `parsers.base.compute_content_hash`'s own SHA-256-over-canonical-
text approach) so a consumer can verify two exports represent the same result without comparing
nested structures directly. It does not itself decide which members belong in the result -- that
is `foundation.merger`'s concern, consumed here only via the `FoundationResult` it produces.
"""

import hashlib
import json
from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from src.core.exceptions import ValidationError
from src.foundation.merger.base import FoundationResult

DEFAULT_FOUNDATION_EXPORT_FORMAT_VERSION = "1.0"
"""Format version a concrete `FoundationExporter` should use for `FoundationExport.
format_version` unless it has a specific reason to use another, e.g. serving an older consumer
that has not migrated to a newer export shape yet."""

_HEX_DIGITS = frozenset("0123456789abcdef")


@dataclass(frozen=True, slots=True)
class FoundationExport:
    """A stable, deterministic external representation of a `FoundationResult`.

    Attributes:
        format_version: Version tag for this export's own shape (e.g. `"1.0"`), independent of
            the `FoundationResult` data `payload` wraps.
        member_count: Number of members in the exported result, carried through from `payload`
            for traceability without requiring a consumer to inspect `payload` itself.
        payload: The exported `FoundationResult`, rendered as a plain, JSON-safe nested
            structure -- keys and list order fixed by `FoundationResult.to_mapping`'s own
            deterministic sort order, so two exports of the same logical result are always
            identical.
        checksum: SHA-256 hex digest of `payload`'s canonical JSON form, letting a consumer
            verify export stability without re-serializing and comparing nested structures
            directly. See `compute_export_checksum`.
    """

    format_version: str
    member_count: int
    payload: dict[str, Any]
    checksum: str

    def __post_init__(self) -> None:
        """Validate that `format_version` is non-blank, `member_count` is non-negative, and
        `checksum` is a well-formed SHA-256 hex digest.

        Raises:
            ValidationError: If `format_version` is blank, `member_count` is negative, or
                `checksum` is not a 64-character lowercase hex string.
        """
        if not self.format_version.strip():
            raise ValidationError("FoundationExport: format_version must not be empty")
        if self.member_count < 0:
            raise ValidationError("FoundationExport: member_count must not be negative")
        if len(self.checksum) != 64 or any(c not in _HEX_DIGITS for c in self.checksum):
            raise ValidationError(
                "FoundationExport: checksum must be a 64-character lowercase hex digest"
            )


def compute_export_checksum(payload: Mapping[str, Any]) -> str:
    """Compute a stable SHA-256 hex digest of `payload`'s canonical JSON form.

    Canonical form uses sorted keys and no whitespace, so semantically identical payloads always
    produce the same digest regardless of key insertion order.

    Args:
        payload: A JSON-safe nested structure, such as `FoundationResult.to_mapping`'s return
            value.

    Returns:
        A 64-character lowercase hex digest.

    Raises:
        ValidationError: If `payload` contains a value that cannot be rendered as JSON.
    """
    try:
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise ValidationError(
            f"cannot compute export checksum: payload is not JSON-safe: {exc}"
        ) from exc
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class FoundationExporter(ABC):
    """Exports a `FoundationResult` into a stable, deterministic `FoundationExport`.

    A concrete implementation decides exactly which `format_version` it produces and, if it
    extends `payload` beyond `FoundationResult.to_mapping`'s own shape, how it does so; it does
    not decide which members belong in the result -- that is `foundation.merger`'s concern.
    """

    @abstractmethod
    def export(self, result: FoundationResult) -> FoundationExport:
        """Export `result` as a `FoundationExport`.

        Args:
            result: The merged Foundation decision to export.

        Returns:
            A `FoundationExport` whose `payload` is derived from `result.to_mapping()`, whose
            `member_count` equals `result.member_count`, and whose `checksum` is
            `compute_export_checksum(payload)`.

        Raises:
            ValidationError: If the payload built from `result` cannot be rendered as JSON --
                see `compute_export_checksum`.
        """
        ...
