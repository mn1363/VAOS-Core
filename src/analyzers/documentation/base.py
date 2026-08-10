"""Documentation analyzer Port: documentation coverage analysis.

`DocumentationAnalyzer` turns a single file's `extractors.ast.base.AstExtractionResult` into
`DocumentationCoverage` -- what fraction of the file's classes and functions carry a docstring,
individually and combined. A file with no classes (or no functions) is treated as fully covered
on that dimension (a vacuous `1.0`, not a `0.0`): there is nothing left undocumented to count
against it. This Port measures coverage as a fact; it does not judge whether that level of
coverage is *good enough* for the file's purpose -- that evaluative judgment belongs to
`analyzers.quality`.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from src.core.exceptions import ValidationError
from src.core.logging import get_logger
from src.extractors.ast.base import AstExtractionResult

_logger = get_logger("analyzers.documentation")


@dataclass(frozen=True, slots=True)
class DocumentationCoverage:
    """Documentation coverage ratios derived from a single file's structural counts.

    Attributes:
        relative_path: Path of the source file this coverage was derived from.
        class_count: Number of classes in the file, carried through for traceability.
        documented_class_count: Number of those classes carrying a docstring, carried through
            for traceability.
        class_documentation_ratio: `documented_class_count / class_count`, or `1.0` when the
            file declares no classes (vacuously fully covered).
        function_count: Number of functions (including methods) in the file, carried through
            for traceability.
        documented_function_count: Number of those functions carrying a docstring, carried
            through for traceability.
        function_documentation_ratio: `documented_function_count / function_count`, or `1.0`
            when the file declares no functions (vacuously fully covered).
        overall_documentation_ratio: `(documented_class_count + documented_function_count) /
            (class_count + function_count)`, or `1.0` when the file declares neither.
    """

    relative_path: str
    class_count: int = 0
    documented_class_count: int = 0
    class_documentation_ratio: float = 1.0
    function_count: int = 0
    documented_function_count: int = 0
    function_documentation_ratio: float = 1.0
    overall_documentation_ratio: float = 1.0

    def __post_init__(self) -> None:
        """Validate that counts and ratios are non-negative, bounded, and consistent.

        Raises:
            ValidationError: If any count is negative, if a documented count exceeds its total,
                or if any ratio field falls outside the closed interval `[0.0, 1.0]`.
        """
        if self.class_count < 0 or self.function_count < 0:
            raise ValidationError("DocumentationCoverage: counts must not be negative")
        if self.documented_class_count < 0 or self.documented_function_count < 0:
            raise ValidationError("DocumentationCoverage: documented counts must not be negative")
        if self.documented_class_count > self.class_count:
            raise ValidationError(
                "DocumentationCoverage: documented_class_count must not exceed class_count"
            )
        if self.documented_function_count > self.function_count:
            raise ValidationError(
                "DocumentationCoverage: documented_function_count must not exceed function_count"
            )
        for ratio_name in (
            "class_documentation_ratio",
            "function_documentation_ratio",
            "overall_documentation_ratio",
        ):
            if not 0.0 <= getattr(self, ratio_name) <= 1.0:
                raise ValidationError(
                    f"DocumentationCoverage: {ratio_name} must be between 0.0 and 1.0"
                )


@dataclass(frozen=True, slots=True)
class DocumentationAnalysisResult:
    """Outcome of a single `DocumentationAnalyzer.analyze` call.

    Attributes:
        relative_path: The file analysis was attempted against.
        succeeded: Whether analysis completed successfully.
        coverage: The resulting documentation coverage. Always present when `succeeded` is True,
            always None when `succeeded` is False.
        error_message: Explanation of the failure. Always None when `succeeded` is True, always
            set when `succeeded` is False.
    """

    relative_path: str
    succeeded: bool
    coverage: DocumentationCoverage | None = None
    error_message: str | None = None

    def __post_init__(self) -> None:
        """Validate that `succeeded`, `coverage`, and `error_message` are consistent.

        Raises:
            ValidationError: If a successful result is missing `coverage` or carries an error
                message, or a failed result carries a `coverage` or no error message.
        """
        if self.succeeded:
            if self.error_message is not None:
                raise ValidationError(
                    "DocumentationAnalysisResult: error_message must be None when succeeded "
                    "is True"
                )
            if self.coverage is None:
                raise ValidationError(
                    "DocumentationAnalysisResult: coverage is required when succeeded is True"
                )
        else:
            if self.coverage is not None:
                raise ValidationError(
                    "DocumentationAnalysisResult: coverage must be None when succeeded is False"
                )
            if self.error_message is None:
                raise ValidationError(
                    "DocumentationAnalysisResult: error_message is required when succeeded "
                    "is False"
                )

    @classmethod
    def ok(
        cls, *, relative_path: str, coverage: DocumentationCoverage
    ) -> "DocumentationAnalysisResult":
        """Build a successful result.

        Args:
            relative_path: The file that was analyzed.
            coverage: The resulting documentation coverage.

        Returns:
            A `DocumentationAnalysisResult` with `succeeded=True`.
        """
        return cls(relative_path=relative_path, succeeded=True, coverage=coverage)

    @classmethod
    def failed(cls, *, relative_path: str, error_message: str) -> "DocumentationAnalysisResult":
        """Build a failed result.

        Args:
            relative_path: The file that analysis was attempted against.
            error_message: Human-readable explanation of the failure.

        Returns:
            A `DocumentationAnalysisResult` with `succeeded=False`.
        """
        _logger.debug("Documentation analysis failed for '%s': %s", relative_path, error_message)
        return cls(relative_path=relative_path, succeeded=False, error_message=error_message)


class DocumentationAnalyzer(ABC):
    """Analyzes documentation coverage from a single file's already-extracted AST metadata.

    A concrete implementation decides how to turn `AstMetadata`'s documented/total counts into
    coverage ratios; it does not judge whether the resulting coverage level is adequate -- that
    evaluative judgment belongs to `analyzers.quality`.
    """

    @abstractmethod
    def analyze(self, extraction_result: AstExtractionResult) -> DocumentationAnalysisResult:
        """Analyze documentation coverage for the file described by `extraction_result`.

        Args:
            extraction_result: The outcome of extracting one file's AST metadata, as produced by
                `src.extractors.ast`.

        Returns:
            A successful result carrying the file's `DocumentationCoverage`, or a failed result
            carrying an explanation, if coverage cannot be derived from `extraction_result`.

        Raises:
            ValidationError: If `extraction_result.succeeded` is False -- analysis requires a
                successful extraction.
        """
        ...


def require_successful_extraction(extraction_result: AstExtractionResult) -> AstExtractionResult:
    """Validate that `extraction_result` represents a successful extraction.

    Every `DocumentationAnalyzer.analyze` implementation calls this first, so a caller error (an
    `AstExtractionResult` with `succeeded=False`) is reported the same way -- as an immediate
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
            "cannot analyze documentation from a failed AstExtractionResult",
            details={"relative_path": extraction_result.relative_path},
        )
    return extraction_result


def coverage_ratio(documented: int, total: int) -> float:
    """Compute a documentation coverage ratio, treating an empty population as fully covered.

    Shared by every ratio field on `DocumentationCoverage` so a file with no classes (or no
    functions) reports `1.0` -- vacuously fully covered -- rather than `0.0` or a division error.

    Args:
        documented: Number of documented constructs. Must not be negative.
        total: Total number of constructs. May legitimately be zero.

    Returns:
        `documented / total` as a `float`, or `1.0` if `total` is zero.

    Raises:
        ValidationError: If `documented` is negative or exceeds `total`.
    """
    if documented < 0:
        raise ValidationError("coverage_ratio: documented must not be negative")
    if total <= 0:
        return 1.0
    if documented > total:
        raise ValidationError("coverage_ratio: documented must not exceed total")
    return documented / total
