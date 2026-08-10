"""Security analyzer Port: available security-related indicator evaluation.

`SecurityAnalyzer` turns a single file's `extractors.imports.base.ImportExtractionResult` into a
`SecurityAssessment` -- the file's external dependency *exposure surface* (how many external
modules it imports, and which ones), plus zero or more `SecurityIndicator` entries flagging
specific external targets worth a closer look. `src.extractors` exposes no vulnerability
database, secret scanner, or taint-analysis data, so this Port cannot and does not report actual
vulnerabilities or exploitability -- it evaluates only the exposure signal already available:
that importing an external module is a trust boundary, not a judgment about that module's safety.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from src.core.exceptions import ValidationError
from src.core.logging import get_logger
from src.domain.entities import FindingSeverity
from src.extractors.imports.base import ImportExtractionResult

_logger = get_logger("analyzers.security")


@dataclass(frozen=True, slots=True)
class SecurityIndicator:
    """A single security-related observation about one external dependency in a file.

    Attributes:
        subject: The external target module this indicator is about (a `DependencyEdge.
            target_module` value).
        relative_path: Path of the file the dependency was found in.
        severity: How significant this observation is.
        message: Human-readable explanation of the observation.
        line_number: 1-indexed line the import statement starts on. 0 if unknown.
    """

    subject: str
    relative_path: str
    severity: FindingSeverity
    message: str
    line_number: int = 0

    def __post_init__(self) -> None:
        """Validate that `subject` and `message` are non-blank.

        Raises:
            ValidationError: If `subject` or `message` is blank.
        """
        if not self.subject.strip():
            raise ValidationError("SecurityIndicator: subject must not be empty")
        if not self.message.strip():
            raise ValidationError("SecurityIndicator: message must not be empty")


@dataclass(frozen=True, slots=True)
class SecurityAssessment:
    """A single file's external dependency exposure, evaluated for security-related signals.

    Attributes:
        relative_path: Path of the source file this assessment was derived from.
        external_dependency_count: Number of import statements classified as external, carried
            through for traceability.
        external_targets: The file's distinct external target modules, deduplicated and
            lexicographically sorted so the result is deterministic.
        indicators: Specific security-related observations about individual dependencies,
            possibly empty.
    """

    relative_path: str
    external_dependency_count: int = 0
    external_targets: tuple[str, ...] = ()
    indicators: tuple[SecurityIndicator, ...] = ()

    def __post_init__(self) -> None:
        """Validate that the count is non-negative and `external_targets` is well-formed.

        Raises:
            ValidationError: If `external_dependency_count` is negative, or if
                `external_targets` is not sorted and free of duplicates.
        """
        if self.external_dependency_count < 0:
            raise ValidationError(
                "SecurityAssessment: external_dependency_count must not be negative"
            )
        if list(self.external_targets) != sorted(set(self.external_targets)):
            raise ValidationError(
                "SecurityAssessment: external_targets must be sorted and free of duplicates"
            )


@dataclass(frozen=True, slots=True)
class SecurityAnalysisResult:
    """Outcome of a single `SecurityAnalyzer.analyze` call.

    Attributes:
        relative_path: The file analysis was attempted against.
        succeeded: Whether analysis completed successfully.
        assessment: The resulting security assessment. Always present when `succeeded` is True,
            always None when `succeeded` is False.
        error_message: Explanation of the failure. Always None when `succeeded` is True, always
            set when `succeeded` is False.
    """

    relative_path: str
    succeeded: bool
    assessment: SecurityAssessment | None = None
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
                    "SecurityAnalysisResult: error_message must be None when succeeded is True"
                )
            if self.assessment is None:
                raise ValidationError(
                    "SecurityAnalysisResult: assessment is required when succeeded is True"
                )
        else:
            if self.assessment is not None:
                raise ValidationError(
                    "SecurityAnalysisResult: assessment must be None when succeeded is False"
                )
            if self.error_message is None:
                raise ValidationError(
                    "SecurityAnalysisResult: error_message is required when succeeded is False"
                )

    @classmethod
    def ok(cls, *, relative_path: str, assessment: SecurityAssessment) -> "SecurityAnalysisResult":
        """Build a successful result.

        Args:
            relative_path: The file that was analyzed.
            assessment: The resulting security assessment.

        Returns:
            A `SecurityAnalysisResult` with `succeeded=True`.
        """
        return cls(relative_path=relative_path, succeeded=True, assessment=assessment)

    @classmethod
    def failed(cls, *, relative_path: str, error_message: str) -> "SecurityAnalysisResult":
        """Build a failed result.

        Args:
            relative_path: The file that analysis was attempted against.
            error_message: Human-readable explanation of the failure.

        Returns:
            A `SecurityAnalysisResult` with `succeeded=False`.
        """
        _logger.debug("Security analysis failed for '%s': %s", relative_path, error_message)
        return cls(relative_path=relative_path, succeeded=False, error_message=error_message)


class SecurityAnalyzer(ABC):
    """Evaluates available security-related indicators from a file's already-extracted imports.

    A concrete implementation decides which external dependencies warrant a `SecurityIndicator`
    and at what severity, based solely on the exposure signal `ImportExtractor` already surfaced
    (that a dependency is external); it does not perform vulnerability scanning, secret
    detection, or taint analysis -- `src.extractors` provides no data to derive those from, and
    this Port does not invent any.
    """

    @abstractmethod
    def analyze(self, extraction_result: ImportExtractionResult) -> SecurityAnalysisResult:
        """Evaluate security-related indicators for the file described by `extraction_result`.

        Args:
            extraction_result: The outcome of extracting one file's normalized dependency edges,
                as produced by `src.extractors.imports`.

        Returns:
            A successful result carrying the file's `SecurityAssessment`, or a failed result
            carrying an explanation, if an assessment cannot be derived from `extraction_result`.

        Raises:
            ValidationError: If `extraction_result.succeeded` is False -- analysis requires a
                successful extraction.
        """
        ...


def require_successful_extraction(
    extraction_result: ImportExtractionResult,
) -> ImportExtractionResult:
    """Validate that `extraction_result` represents a successful extraction.

    Every `SecurityAnalyzer.analyze` implementation calls this first, so a caller error (an
    `ImportExtractionResult` with `succeeded=False`) is reported the same way -- as an immediate
    `ValidationError` -- across every implementation.

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
            "cannot evaluate security indicators from a failed ImportExtractionResult",
            details={"relative_path": extraction_result.relative_path},
        )
    return extraction_result
