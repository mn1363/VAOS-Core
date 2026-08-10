"""Complexity analyzer Port: complexity-proxy measurement analysis.

`ComplexityAnalyzer` turns a single file's `extractors.ast.base.AstExtractionResult` into
`ComplexityMetrics` -- ratios derived from the structural counts `AstExtractor` already produced
(methods per class, lines per function, the proportion of functions declared `async`). These are
*proxy* signals for complexity, not true cyclomatic or cognitive complexity: `src.extractors`
does not expose branch counts, nesting depth, or control-flow information, and this Port does not
invent any -- it only turns the counts that already exist into normalized, comparable ratios.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from src.core.exceptions import ValidationError
from src.core.logging import get_logger
from src.extractors.ast.base import AstExtractionResult

_logger = get_logger("analyzers.complexity")


@dataclass(frozen=True, slots=True)
class ComplexityMetrics:
    """Complexity-proxy ratios derived from a single file's structural counts.

    Attributes:
        relative_path: Path of the source file these metrics were derived from.
        methods_per_class: `method_count / class_count`, or `0.0` when the file declares no
            classes (nothing to average over).
        lines_per_function: `line_count / function_count`, or `0.0` when the file declares no
            free functions (methods are not counted here; see `methods_per_class`).
        async_function_ratio: `async_function_count / function_count`, or `0.0` when the file
            declares no free functions.
        class_count: Number of classes in the file, carried through for traceability.
        function_count: Number of free functions in the file, carried through for traceability.
        method_count: Number of methods across every class in the file, carried through for
            traceability.
    """

    relative_path: str
    methods_per_class: float = 0.0
    lines_per_function: float = 0.0
    async_function_ratio: float = 0.0
    class_count: int = 0
    function_count: int = 0
    method_count: int = 0

    def __post_init__(self) -> None:
        """Validate that every ratio and count field is non-negative.

        Raises:
            ValidationError: If any ratio or count field is negative.
        """
        if self.methods_per_class < 0:
            raise ValidationError("ComplexityMetrics: methods_per_class must not be negative")
        if self.lines_per_function < 0:
            raise ValidationError("ComplexityMetrics: lines_per_function must not be negative")
        if not 0.0 <= self.async_function_ratio <= 1.0:
            raise ValidationError(
                "ComplexityMetrics: async_function_ratio must be between 0.0 and 1.0"
            )
        if self.class_count < 0 or self.function_count < 0 or self.method_count < 0:
            raise ValidationError("ComplexityMetrics: counts must not be negative")


@dataclass(frozen=True, slots=True)
class ComplexityAnalysisResult:
    """Outcome of a single `ComplexityAnalyzer.analyze` call.

    Attributes:
        relative_path: The file analysis was attempted against.
        succeeded: Whether analysis completed successfully.
        metrics: The resulting complexity-proxy metrics. Always present when `succeeded` is
            True, always None when `succeeded` is False.
        error_message: Explanation of the failure. Always None when `succeeded` is True, always
            set when `succeeded` is False.
    """

    relative_path: str
    succeeded: bool
    metrics: ComplexityMetrics | None = None
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
                    "ComplexityAnalysisResult: error_message must be None when succeeded is True"
                )
            if self.metrics is None:
                raise ValidationError(
                    "ComplexityAnalysisResult: metrics is required when succeeded is True"
                )
        else:
            if self.metrics is not None:
                raise ValidationError(
                    "ComplexityAnalysisResult: metrics must be None when succeeded is False"
                )
            if self.error_message is None:
                raise ValidationError(
                    "ComplexityAnalysisResult: error_message is required when succeeded is False"
                )

    @classmethod
    def ok(
        cls, *, relative_path: str, metrics: ComplexityMetrics
    ) -> "ComplexityAnalysisResult":
        """Build a successful result.

        Args:
            relative_path: The file that was analyzed.
            metrics: The resulting complexity-proxy metrics.

        Returns:
            A `ComplexityAnalysisResult` with `succeeded=True`.
        """
        return cls(relative_path=relative_path, succeeded=True, metrics=metrics)

    @classmethod
    def failed(cls, *, relative_path: str, error_message: str) -> "ComplexityAnalysisResult":
        """Build a failed result.

        Args:
            relative_path: The file that analysis was attempted against.
            error_message: Human-readable explanation of the failure.

        Returns:
            A `ComplexityAnalysisResult` with `succeeded=False`.
        """
        _logger.debug("Complexity analysis failed for '%s': %s", relative_path, error_message)
        return cls(relative_path=relative_path, succeeded=False, error_message=error_message)


class ComplexityAnalyzer(ABC):
    """Analyzes complexity-proxy ratios from a single file's already-extracted AST metadata.

    A concrete implementation decides how to turn `AstMetadata`'s raw counts into normalized
    ratios; it does not compute true cyclomatic or cognitive complexity (`src.extractors` exposes
    no branch or control-flow data to derive that from) and does not judge whether the resulting
    ratios represent good or bad code -- that evaluative judgment belongs to `analyzers.quality`.
    """

    @abstractmethod
    def analyze(self, extraction_result: AstExtractionResult) -> ComplexityAnalysisResult:
        """Analyze complexity-proxy ratios for the file described by `extraction_result`.

        Args:
            extraction_result: The outcome of extracting one file's AST metadata, as produced by
                `src.extractors.ast`.

        Returns:
            A successful result carrying the file's `ComplexityMetrics`, or a failed result
            carrying an explanation, if metrics cannot be derived from `extraction_result`.

        Raises:
            ValidationError: If `extraction_result.succeeded` is False -- analysis requires a
                successful extraction.
        """
        ...


def require_successful_extraction(extraction_result: AstExtractionResult) -> AstExtractionResult:
    """Validate that `extraction_result` represents a successful extraction.

    Every `ComplexityAnalyzer.analyze` implementation calls this first, so a caller error (an
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
            "cannot analyze complexity from a failed AstExtractionResult",
            details={"relative_path": extraction_result.relative_path},
        )
    return extraction_result


def safe_ratio(numerator: int, denominator: int) -> float:
    """Compute `numerator / denominator`, defined as `0.0` when `denominator` is zero.

    Shared by every ratio field on `ComplexityMetrics` so a class-free or function-free file
    produces a well-defined `0.0` rather than raising `ZeroDivisionError`.

    Args:
        numerator: The ratio's numerator. Must not be negative.
        denominator: The ratio's denominator. May legitimately be zero.

    Returns:
        `numerator / denominator` as a `float`, or `0.0` if `denominator` is zero.

    Raises:
        ValidationError: If `numerator` is negative.
    """
    if numerator < 0:
        raise ValidationError("safe_ratio: numerator must not be negative")
    if denominator <= 0:
        return 0.0
    return numerator / denominator
