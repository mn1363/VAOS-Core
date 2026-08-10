"""Dependency analyzer Port: per-file dependency relationship analysis.

`DependencyAnalyzer` turns a single file's `extractors.imports.base.ImportExtractionResult` into
a `DependencyProfile` -- how many of the file's own import statements are internal (same-project)
versus external, and which external modules it imports, deduplicated and sorted for a
deterministic result. This analyzes the dependency relationships one file itself declares;
assembling many files' profiles into a repository-wide dependency graph (resolving imports to
actual files, detecting cycles) is explicitly a `graph` concern, a later, not-yet-built phase
this Port does not perform.
"""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass

from src.core.exceptions import ValidationError
from src.core.logging import get_logger
from src.extractors.imports.base import DependencyEdge, ImportExtractionResult

_logger = get_logger("analyzers.dependency")


@dataclass(frozen=True, slots=True)
class DependencyProfile:
    """A single file's own dependency relationships, summarized from its normalized edges.

    Attributes:
        relative_path: Path of the source file this profile was derived from.
        total_dependency_count: Total number of import statements the file declares.
        internal_dependency_count: Number of those imports classified as internal
            (same-project), carried through from `DependencyEdge.is_internal`.
        external_dependency_count: Number of those imports classified as external.
        external_targets: The file's distinct external `DependencyEdge.target_module` values,
            deduplicated and lexicographically sorted so the result is deterministic regardless
            of the input edges' original order.
    """

    relative_path: str
    total_dependency_count: int = 0
    internal_dependency_count: int = 0
    external_dependency_count: int = 0
    external_targets: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Validate that the counts are non-negative and internally consistent.

        Raises:
            ValidationError: If any count is negative, if `internal_dependency_count` plus
                `external_dependency_count` does not equal `total_dependency_count`, or if
                `external_targets` is not sorted and free of duplicates.
        """
        if (
            self.total_dependency_count < 0
            or self.internal_dependency_count < 0
            or self.external_dependency_count < 0
        ):
            raise ValidationError("DependencyProfile: counts must not be negative")
        if self.internal_dependency_count + self.external_dependency_count != (
            self.total_dependency_count
        ):
            raise ValidationError(
                "DependencyProfile: internal_dependency_count + external_dependency_count "
                "must equal total_dependency_count"
            )
        if list(self.external_targets) != sorted(set(self.external_targets)):
            raise ValidationError(
                "DependencyProfile: external_targets must be sorted and free of duplicates"
            )


@dataclass(frozen=True, slots=True)
class DependencyAnalysisResult:
    """Outcome of a single `DependencyAnalyzer.analyze` call.

    Attributes:
        relative_path: The file analysis was attempted against.
        succeeded: Whether analysis completed successfully.
        profile: The resulting dependency profile. Always present when `succeeded` is True,
            always None when `succeeded` is False.
        error_message: Explanation of the failure. Always None when `succeeded` is True, always
            set when `succeeded` is False.
    """

    relative_path: str
    succeeded: bool
    profile: DependencyProfile | None = None
    error_message: str | None = None

    def __post_init__(self) -> None:
        """Validate that `succeeded`, `profile`, and `error_message` are consistent.

        Raises:
            ValidationError: If a successful result is missing `profile` or carries an error
                message, or a failed result carries a `profile` or no error message.
        """
        if self.succeeded:
            if self.error_message is not None:
                raise ValidationError(
                    "DependencyAnalysisResult: error_message must be None when succeeded is True"
                )
            if self.profile is None:
                raise ValidationError(
                    "DependencyAnalysisResult: profile is required when succeeded is True"
                )
        else:
            if self.profile is not None:
                raise ValidationError(
                    "DependencyAnalysisResult: profile must be None when succeeded is False"
                )
            if self.error_message is None:
                raise ValidationError(
                    "DependencyAnalysisResult: error_message is required when succeeded is False"
                )

    @classmethod
    def ok(cls, *, relative_path: str, profile: DependencyProfile) -> "DependencyAnalysisResult":
        """Build a successful result.

        Args:
            relative_path: The file that was analyzed.
            profile: The resulting dependency profile.

        Returns:
            A `DependencyAnalysisResult` with `succeeded=True`.
        """
        return cls(relative_path=relative_path, succeeded=True, profile=profile)

    @classmethod
    def failed(cls, *, relative_path: str, error_message: str) -> "DependencyAnalysisResult":
        """Build a failed result.

        Args:
            relative_path: The file that analysis was attempted against.
            error_message: Human-readable explanation of the failure.

        Returns:
            A `DependencyAnalysisResult` with `succeeded=False`.
        """
        _logger.debug("Dependency analysis failed for '%s': %s", relative_path, error_message)
        return cls(relative_path=relative_path, succeeded=False, error_message=error_message)


class DependencyAnalyzer(ABC):
    """Analyzes a single file's own dependency relationships from its already-extracted edges.

    A concrete implementation decides how to summarize a file's `DependencyEdge` entries into an
    internal/external breakdown; it does not resolve a target module to an actual file on disk
    and does not assemble edges from multiple files into a dependency graph -- both are separate,
    not-yet-scoped concerns belonging to the future `graph` phase.
    """

    @abstractmethod
    def analyze(self, extraction_result: ImportExtractionResult) -> DependencyAnalysisResult:
        """Analyze dependency relationships for the file described by `extraction_result`.

        Args:
            extraction_result: The outcome of extracting one file's normalized dependency edges,
                as produced by `src.extractors.imports`.

        Returns:
            A successful result carrying the file's `DependencyProfile`, or a failed result
            carrying an explanation, if a profile cannot be derived from `extraction_result`.

        Raises:
            ValidationError: If `extraction_result.succeeded` is False -- analysis requires a
                successful extraction.
        """
        ...


def require_successful_extraction(
    extraction_result: ImportExtractionResult,
) -> ImportExtractionResult:
    """Validate that `extraction_result` represents a successful extraction.

    Every `DependencyAnalyzer.analyze` implementation calls this first, so a caller error (an
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
            "cannot analyze dependencies from a failed ImportExtractionResult",
            details={"relative_path": extraction_result.relative_path},
        )
    return extraction_result


def summarize_external_targets(edges: Sequence[DependencyEdge]) -> tuple[str, ...]:
    """Derive the deduplicated, sorted external target modules from a sequence of edges.

    Args:
        edges: The file's normalized dependency edges, as produced by `ImportExtractor.extract`.

    Returns:
        The distinct `target_module` values of every edge with `is_internal=False`, sorted
        lexicographically so the result is deterministic regardless of `edges`'s order.
    """
    return tuple(sorted({edge.target_module for edge in edges if not edge.is_internal}))
