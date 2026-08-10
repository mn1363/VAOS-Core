"""Metrics analyzer Port: normalized code metrics.

`MetricsAnalyzer` turns a single file's `extractors.ast.base.AstExtractionResult` into
`NormalizedCodeMetrics` -- the file's raw structural counts re-expressed as densities per
thousand lines of code (KLOC), so files of different sizes become comparable on the same scale.
This is a distinct concern from `analyzers.complexity` (which turns the same counts into
shape-proxy ratios like methods-per-class) and `analyzers.documentation` (coverage ratios): this
Port normalizes *volume*, not shape or coverage.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from src.core.exceptions import ValidationError
from src.core.logging import get_logger
from src.extractors.ast.base import AstExtractionResult

_logger = get_logger("analyzers.metrics")

#: Number of lines one KLOC (thousand lines of code) represents, the normalization base every
#: `..._per_kloc` field on `NormalizedCodeMetrics` is expressed against.
_LINES_PER_KLOC = 1000


@dataclass(frozen=True, slots=True)
class NormalizedCodeMetrics:
    """A single file's structural counts, normalized to a per-KLOC density scale.

    Attributes:
        relative_path: Path of the source file these metrics were derived from.
        line_count: Number of lines in the file, carried through as the normalization base.
        classes_per_kloc: Classes declared per 1000 lines of code, or `0.0` when `line_count`
            is zero.
        functions_per_kloc: Free functions declared per 1000 lines of code, or `0.0` when
            `line_count` is zero.
        methods_per_kloc: Methods declared per 1000 lines of code, or `0.0` when `line_count`
            is zero.
        symbols_per_kloc: Total symbol-table entries per 1000 lines of code, or `0.0` when
            `line_count` is zero.
    """

    relative_path: str
    line_count: int = 0
    classes_per_kloc: float = 0.0
    functions_per_kloc: float = 0.0
    methods_per_kloc: float = 0.0
    symbols_per_kloc: float = 0.0

    def __post_init__(self) -> None:
        """Validate that every count and density field is non-negative.

        Raises:
            ValidationError: If `line_count` or any `..._per_kloc` field is negative.
        """
        if self.line_count < 0:
            raise ValidationError("NormalizedCodeMetrics: line_count must not be negative")
        for field_name in (
            "classes_per_kloc",
            "functions_per_kloc",
            "methods_per_kloc",
            "symbols_per_kloc",
        ):
            if getattr(self, field_name) < 0:
                raise ValidationError(f"NormalizedCodeMetrics: {field_name} must not be negative")


@dataclass(frozen=True, slots=True)
class MetricsAnalysisResult:
    """Outcome of a single `MetricsAnalyzer.analyze` call.

    Attributes:
        relative_path: The file analysis was attempted against.
        succeeded: Whether analysis completed successfully.
        metrics: The resulting normalized metrics. Always present when `succeeded` is True,
            always None when `succeeded` is False.
        error_message: Explanation of the failure. Always None when `succeeded` is True, always
            set when `succeeded` is False.
    """

    relative_path: str
    succeeded: bool
    metrics: NormalizedCodeMetrics | None = None
    error_message: str | None = None

    def __post_init__(self) -> None:
        """Validate that `succeeded`, `metrics`, and `error_message` are consistent.

        Raises:
            ValidationError: If a successful result is missing `metrics` or carries an error
                message, or a failed result carries `metrics` or no error message.
        """
        if self.succeeded:
            if self.error_message is not None:
                raise ValidationError(
                    "MetricsAnalysisResult: error_message must be None when succeeded is True"
                )
            if self.metrics is None:
                raise ValidationError(
                    "MetricsAnalysisResult: metrics is required when succeeded is True"
                )
        else:
            if self.metrics is not None:
                raise ValidationError(
                    "MetricsAnalysisResult: metrics must be None when succeeded is False"
                )
            if self.error_message is None:
                raise ValidationError(
                    "MetricsAnalysisResult: error_message is required when succeeded is False"
                )

    @classmethod
    def ok(cls, *, relative_path: str, metrics: NormalizedCodeMetrics) -> "MetricsAnalysisResult":
        """Build a successful result.

        Args:
            relative_path: The file that was analyzed.
            metrics: The resulting normalized metrics.

        Returns:
            A `MetricsAnalysisResult` with `succeeded=True`.
        """
        return cls(relative_path=relative_path, succeeded=True, metrics=metrics)

    @classmethod
    def failed(cls, *, relative_path: str, error_message: str) -> "MetricsAnalysisResult":
        """Build a failed result.

        Args:
            relative_path: The file that analysis was attempted against.
            error_message: Human-readable explanation of the failure.

        Returns:
            A `MetricsAnalysisResult` with `succeeded=False`.
        """
        _logger.debug("Metrics analysis failed for '%s': %s", relative_path, error_message)
        return cls(relative_path=relative_path, succeeded=False, error_message=error_message)


class MetricsAnalyzer(ABC):
    """Produces normalized, size-comparable code metrics from a file's already-extracted counts.

    A concrete implementation decides how to normalize `AstMetadata`'s raw counts against file
    size; it does not judge whether the resulting densities are good or bad -- that evaluative
    judgment belongs to `analyzers.quality` -- and does not aggregate many files into a
    repository-wide rollup, which is a later, not-yet-scoped `pipeline` concern.
    """

    @abstractmethod
    def analyze(self, extraction_result: AstExtractionResult) -> MetricsAnalysisResult:
        """Produce normalized code metrics for the file described by `extraction_result`.

        Args:
            extraction_result: The outcome of extracting one file's AST metadata, as produced by
                `src.extractors.ast`.

        Returns:
            A successful result carrying the file's `NormalizedCodeMetrics`, or a failed result
            carrying an explanation, if metrics cannot be derived from `extraction_result`.

        Raises:
            ValidationError: If `extraction_result.succeeded` is False -- analysis requires a
                successful extraction.
        """
        ...


def require_successful_extraction(extraction_result: AstExtractionResult) -> AstExtractionResult:
    """Validate that `extraction_result` represents a successful extraction.

    Every `MetricsAnalyzer.analyze` implementation calls this first, so a caller error (an
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
            "cannot compute metrics from a failed AstExtractionResult",
            details={"relative_path": extraction_result.relative_path},
        )
    return extraction_result


def per_kloc(count: int, line_count: int) -> float:
    """Normalize `count` against `line_count`, expressed per 1000 lines of code.

    Shared by every `..._per_kloc` field on `NormalizedCodeMetrics` so a file with zero lines
    produces a well-defined `0.0` rather than raising `ZeroDivisionError`.

    Args:
        count: The raw construct count to normalize. Must not be negative.
        line_count: The file's total line count, the normalization base. May legitimately be
            zero.

    Returns:
        `count / line_count * 1000` as a `float`, or `0.0` if `line_count` is zero.

    Raises:
        ValidationError: If `count` or `line_count` is negative.
    """
    if count < 0:
        raise ValidationError("per_kloc: count must not be negative")
    if line_count < 0:
        raise ValidationError("per_kloc: line_count must not be negative")
    if line_count == 0:
        return 0.0
    return count / line_count * _LINES_PER_KLOC
