"""Architecture analyzer Port: package/module organization analysis.

`ArchitectureAnalyzer` turns a single file's `extractors.architecture.base.
ArchitectureExtractionResult` into an `ArchitectureAssessment` -- a description of how deeply
nested that file's package placement is, whether it is that package's own root marker, and how
many nested modules it declares -- derived entirely from the `PackageUnit` the extractor already
produced. Judging whether a repository's *overall* package layout is well-organized (cohesion,
layering violations across many files) requires a repository-wide view, which is a `graph`
concern (assembling many files' units into a tree) or a later `pipeline` concern (comparing many
`ArchitectureAssessment`s); this Port only assesses one file's own placement.

Like `extractors.architecture.base.ArchitectureExtractor.extract`, `analyze` operates on
already-produced, in-memory data -- here an `ArchitectureExtractionResult` rather than a
`parsers.base.ParseResult` -- and performs no I/O, no cross-file aggregation, and no scoring of
a repository as a whole.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from src.core.exceptions import ValidationError
from src.core.logging import get_logger
from src.extractors.architecture.base import ArchitectureExtractionResult

_logger = get_logger("analyzers.architecture")


@dataclass(frozen=True, slots=True)
class ArchitectureAssessment:
    """The architectural placement of a single file, described in analyzable terms.

    Attributes:
        relative_path: Path of the source file this assessment was derived from.
        package_path: The file's package/namespace path, carried through from the originating
            `PackageUnit` unchanged.
        is_package_root: Whether the file itself is the conventional marker file for its
            package, carried through from the originating `PackageUnit`.
        declared_module_count: Number of nested module/namespace declarations the file itself
            contains, carried through as a count from `PackageUnit.declared_modules`.
    """

    relative_path: str
    package_path: tuple[str, ...]
    is_package_root: bool = False
    declared_module_count: int = 0

    def __post_init__(self) -> None:
        """Validate that `declared_module_count` is non-negative.

        Raises:
            ValidationError: If `declared_module_count` is negative.
        """
        if self.declared_module_count < 0:
            raise ValidationError(
                "ArchitectureAssessment: declared_module_count must not be negative"
            )

    @property
    def package_depth(self) -> int:
        """Number of segments in `package_path`.

        Returns:
            How deeply nested the file's package placement is (e.g. `3` for `("src",
            "extractors", "architecture")`). Derived from `package_path` rather than stored, so
            it can never disagree with it.
        """
        return len(self.package_path)


@dataclass(frozen=True, slots=True)
class ArchitectureAnalysisResult:
    """Outcome of a single `ArchitectureAnalyzer.analyze` call.

    Attributes:
        relative_path: The file analysis was attempted against.
        succeeded: Whether analysis completed successfully.
        assessment: The resulting architectural assessment. Always present when `succeeded` is
            True, always None when `succeeded` is False.
        error_message: Explanation of the failure. Always None when `succeeded` is True, always
            set when `succeeded` is False.
    """

    relative_path: str
    succeeded: bool
    assessment: ArchitectureAssessment | None = None
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
                    "ArchitectureAnalysisResult: error_message must be None when succeeded "
                    "is True"
                )
            if self.assessment is None:
                raise ValidationError(
                    "ArchitectureAnalysisResult: assessment is required when succeeded is True"
                )
        else:
            if self.assessment is not None:
                raise ValidationError(
                    "ArchitectureAnalysisResult: assessment must be None when succeeded is False"
                )
            if self.error_message is None:
                raise ValidationError(
                    "ArchitectureAnalysisResult: error_message is required when succeeded "
                    "is False"
                )

    @classmethod
    def ok(
        cls, *, relative_path: str, assessment: ArchitectureAssessment
    ) -> "ArchitectureAnalysisResult":
        """Build a successful result.

        Args:
            relative_path: The file that was analyzed.
            assessment: The resulting architectural assessment.

        Returns:
            An `ArchitectureAnalysisResult` with `succeeded=True`.
        """
        return cls(relative_path=relative_path, succeeded=True, assessment=assessment)

    @classmethod
    def failed(
        cls, *, relative_path: str, error_message: str
    ) -> "ArchitectureAnalysisResult":
        """Build a failed result.

        Args:
            relative_path: The file that analysis was attempted against.
            error_message: Human-readable explanation of the failure.

        Returns:
            An `ArchitectureAnalysisResult` with `succeeded=False`.
        """
        _logger.debug("Architecture analysis failed for '%s': %s", relative_path, error_message)
        return cls(relative_path=relative_path, succeeded=False, error_message=error_message)


class ArchitectureAnalyzer(ABC):
    """Analyzes a single file's package/module placement from its already-extracted structure.

    A concrete implementation decides how to describe *where a file sits* in analyzable terms
    (depth, root-marker status, declared-module count); it does not judge whether a repository's
    overall structure is well-designed across many files -- that requires a repository-wide view
    belonging to a later, not-yet-scoped phase (`graph`, `pipeline`).
    """

    @abstractmethod
    def analyze(
        self, extraction_result: ArchitectureExtractionResult
    ) -> ArchitectureAnalysisResult:
        """Analyze the package/module organization of the file described by `extraction_result`.

        Args:
            extraction_result: The outcome of extracting one file's architectural placement, as
                produced by `src.extractors.architecture`.

        Returns:
            A successful result carrying the file's `ArchitectureAssessment`, or a failed result
            carrying an explanation, if an assessment cannot be derived from `extraction_result`.

        Raises:
            ValidationError: If `extraction_result.succeeded` is False -- analysis requires a
                successful extraction; an extractor failure is the extractor's own reported
                outcome, not something this layer re-derives structure from.
        """
        ...


def require_successful_extraction(
    extraction_result: ArchitectureExtractionResult,
) -> ArchitectureExtractionResult:
    """Validate that `extraction_result` represents a successful extraction.

    Every `ArchitectureAnalyzer.analyze` implementation calls this first, so a caller error (an
    `ArchitectureExtractionResult` with `succeeded=False`) is reported the same way -- as an
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
            "cannot analyze architecture from a failed ArchitectureExtractionResult",
            details={"relative_path": extraction_result.relative_path},
        )
    return extraction_result
