"""Data structures produced by `Analyzer` implementations."""

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID


@dataclass(frozen=True, slots=True)
class AnalysisOutcome:
    """Outcome of a single analysis attempt against an artifact.

    Attributes:
        artifact_id: Identifier of the artifact that was analyzed.
        succeeded: Whether the analysis attempt completed successfully.
        findings: Freeform structured findings produced by the analyzer.
        error_message: Explanation of the failure, when `succeeded` is False.
    """

    artifact_id: UUID
    succeeded: bool
    findings: dict[str, Any] = field(default_factory=dict)
    error_message: str | None = None
