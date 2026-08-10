"""Quality analyzer Port: measurable code-quality indicator evaluation.

`QualityAnalyzer` turns a single file's `extractors.foundation.base.FoundationExtractionResult`
into a `QualityAssessment` -- how much of the file's public API surface (its `FoundationCandidate`
classes and functions) carries a docstring, plus zero or more `QualityIndicator` entries flagging
specific candidates worth a closer look (e.g. a public candidate with no docstring). Unlike the
purely descriptive `analyzers.architecture`/`complexity`/`documentation`/`metrics` Ports, this one
*evaluates* -- each `QualityIndicator` carries a `domain.entities.FindingSeverity`, the same
severity vocabulary a future `AnalysisRun`'s persisted `Finding`s use, so a concrete
implementation's judgments are expressed in a vocabulary later layers already understand.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from src.core.exceptions import ValidationError
from src.core.logging import get_logger
from src.domain.entities import FindingSeverity
from src.extractors.foundation.base import FoundationExtractionResult

_logger = get_logger("analyzers.quality")


@dataclass(frozen=True, slots=True)
class QualityIndicator:
    """A single quality observation about one construct in a file.

    Attributes:
        subject_name: Name of the class or function this indicator is about.
        relative_path: Path of the file the subject was found in.
        severity: How significant this observation is.
        message: Human-readable explanation of the observation.
        line_number: 1-indexed line the subject is declared on. 0 if unknown.
    """

    subject_name: str
    relative_path: str
    severity: FindingSeverity
    message: str
    line_number: int = 0

    def __post_init__(self) -> None:
        """Validate that `subject_name` and `message` are non-blank.

        Raises:
            ValidationError: If `subject_name` or `message` is blank.
        """
        if not self.subject_name.strip():
            raise ValidationError("QualityIndicator: subject_name must not be empty")
        if not self.message.strip():
            raise ValidationError("QualityIndicator: message must not be empty")


@dataclass(frozen=True, slots=True)
class QualityAssessment:
    """A single file's quality assessment, derived from its foundation candidates.

    Attributes:
        relative_path: Path of the source file this assessment was derived from.
        candidate_count: Total number of foundation candidates found in the file, carried
            through for traceability.
        public_candidate_count: Number of those candidates that are public.
        documented_public_ratio: `documented public candidates / public_candidate_count`, or
            `1.0` when the file has no public candidates (vacuously fully documented).
        indicators: Specific quality observations about individual candidates, possibly empty.
    """

    relative_path: str
    candidate_count: int = 0
    public_candidate_count: int = 0
    documented_public_ratio: float = 1.0
    indicators: tuple[QualityIndicator, ...] = ()

    def __post_init__(self) -> None:
        """Validate that counts are non-negative, consistent, and the ratio is bounded.

        Raises:
            ValidationError: If either count is negative, if `public_candidate_count` exceeds
                `candidate_count`, or if `documented_public_ratio` falls outside `[0.0, 1.0]`.
        """
        if self.candidate_count < 0 or self.public_candidate_count < 0:
            raise ValidationError("QualityAssessment: counts must not be negative")
        if self.public_candidate_count > self.candidate_count:
            raise ValidationError(
                "QualityAssessment: public_candidate_count must not exceed candidate_count"
            )
        if not 0.0 <= self.documented_public_ratio <= 1.0:
            raise ValidationError(
                "QualityAssessment: documented_public_ratio must be between 0.0 and 1.0"
            )


@dataclass(frozen=True, slots=True)
class QualityAnalysisResult:
    """Outcome of a single `QualityAnalyzer.analyze` call.

    Attributes:
        relative_path: The file analysis was attempted against.
        succeeded: Whether analysis completed successfully.
        assessment: The resulting quality assessment. Always present when `succeeded` is True,
            always None when `succeeded` is False.
        error_message: Explanation of the failure. Always None when `succeeded` is True, always
            set when `succeeded` is False.
    """

    relative_path: str
    succeeded: bool
    assessment: QualityAssessment | None = None
    error_message: str | None = None

    def __post_init__(self) -> None:
        """Validate that `succeeded`, `assessment`, and `error_message` are consistent.

        Raises:
            ValidationError: If a successful result is missing `assessment` or carries an error
                message, or a failed result carries an `assessment` or no error message.
        """
        if self.succeeded:
            if self.error_message is not None:
                raise ValidationError(
                    "QualityAnalysisResult: error_message must be None when succeeded is True"
                )
            if self.assessment is None:
                raise ValidationError(
                    "QualityAnalysisResult: assessment is required when succeeded is True"
                )
        else:
            if self.assessment is not None:
                raise ValidationError(
                    "QualityAnalysisResult: assessment must be None when succeeded is False"
                )
            if self.error_message is None:
                raise ValidationError(
                    "QualityAnalysisResult: error_message is required when succeeded is False"
                )

    @classmethod
    def ok(cls, *, relative_path: str, assessment: QualityAssessment) -> "QualityAnalysisResult":
        """Build a successful result.

        Args:
            relative_path: The file that was analyzed.
            assessment: The resulting quality assessment.

        Returns:
            A `QualityAnalysisResult` with `succeeded=True`.
        """
        return cls(relative_path=relative_path, succeeded=True, assessment=assessment)

    @classmethod
    def failed(cls, *, relative_path: str, error_message: str) -> "QualityAnalysisResult":
        """Build a failed result.

        Args:
            relative_path: The file that analysis was attempted against.
            error_message: Human-readable explanation of the failure.

        Returns:
            A `QualityAnalysisResult` with `succeeded=False`.
        """
        _logger.debug("Quality analysis failed for '%s': %s", relative_path, error_message)
        return cls(relative_path=relative_path, succeeded=False, error_message=error_message)


class QualityAnalyzer(ABC):
    """Evaluates measurable quality indicators from a file's already-extracted foundation
    candidates.

    A concrete implementation decides which observable signals (`is_public`, `has_docstring`,
    freeform `signals`) on each `FoundationCandidate` warrant a `QualityIndicator` and at what
    severity; it does not select which candidates belong in an actual foundation -- that remains
    the future `foundation` phase's job -- and does not invent quality signals beyond what
    `FoundationExtractor` already surfaced.
    """

    @abstractmethod
    def analyze(self, extraction_result: FoundationExtractionResult) -> QualityAnalysisResult:
        """Evaluate quality indicators for the file described by `extraction_result`.

        Args:
            extraction_result: The outcome of extracting one file's foundation candidates, as
                produced by `src.extractors.foundation`.

        Returns:
            A successful result carrying the file's `QualityAssessment`, or a failed result
            carrying an explanation, if an assessment cannot be derived from `extraction_result`.

        Raises:
            ValidationError: If `extraction_result.succeeded` is False -- analysis requires a
                successful extraction.
        """
        ...


def require_successful_extraction(
    extraction_result: FoundationExtractionResult,
) -> FoundationExtractionResult:
    """Validate that `extraction_result` represents a successful extraction.

    Every `QualityAnalyzer.analyze` implementation calls this first, so a caller error (a
    `FoundationExtractionResult` with `succeeded=False`) is reported the same way -- as an
    immediate `ValidationError` -- across every implementation.

    Args:
        extraction_result: The raw `extraction_result` argument passed to `analyze`.

    Returns:
        `extraction_result`, unchanged.

    Raises:
        ValidationError: If `extraction_result.succeeded` is False.
    """
    if not extraction_result.succeeded:
        _logger.debug(
            "Rejected analysis of an unsuccessful extraction of '%s'",
            extraction_result.relative_path,
        )
        raise ValidationError(
            "cannot evaluate quality from a failed FoundationExtractionResult",
            details={"relative_path": extraction_result.relative_path},
        )
    return extraction_result
