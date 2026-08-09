"""Pattern extractor Port: reusable code pattern extraction.

`PatternExtractor` turns a single file's `parsers.base.ParseResult` into a list of
`ExtractedPattern` entries -- recognizable, named structural patterns found among its classes
and functions (e.g. a decorator-based extension point, a factory-style constructor, a
dataclass-style value object). Recognizing that a pattern is *present* is this Port's whole job;
judging whether applying it here was a *good* choice is analysis, which belongs to the future
`analyzers` phase, not this one.
"""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass

from src.core.exceptions import ValidationError
from src.core.logging import get_logger
from src.parsers.base import ParseResult

_logger = get_logger("extractors.patterns")


@dataclass(frozen=True, slots=True)
class ExtractedPattern:
    """A single recognizable code pattern found in a file.

    Attributes:
        name: A short, stable identifier for the pattern (e.g. `"factory_method"`,
            `"dataclass_value_object"`). Freeform, like `domain.entities.Finding.category`,
            since the exact pattern taxonomy is an implementation concern of whichever concrete
            `PatternExtractor` recognized it, not a fixed enum this Port dictates.
        relative_path: Path of the file the pattern was found in.
        subject_name: Name of the class or function the pattern was recognized in.
        description: Human-readable explanation of why this pattern was recognized here.
        line_number: 1-indexed line the pattern's subject is declared on. 0 if unknown.
        evidence: Freeform supporting details about the match (e.g. which decorator or naming
            convention triggered recognition), for a consumer that wants to know *why* without
            re-deriving it.
    """

    name: str
    relative_path: str
    subject_name: str
    description: str
    line_number: int = 0
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PatternExtractionResult:
    """Outcome of a single `PatternExtractor.extract` call.

    Attributes:
        relative_path: The file extraction was attempted against.
        succeeded: Whether extraction completed successfully.
        patterns: The file's extracted code patterns. Always empty when `succeeded` is False;
            may legitimately be empty when `succeeded` is True too (a file matching no known
            pattern).
        error_message: Explanation of the failure. Always None when `succeeded` is True, always
            set when `succeeded` is False.
    """

    relative_path: str
    succeeded: bool
    patterns: tuple[ExtractedPattern, ...] = ()
    error_message: str | None = None

    def __post_init__(self) -> None:
        """Validate that `succeeded`, `patterns`, and `error_message` are consistent.

        Raises:
            ValidationError: If a successful result carries an error message, or a failed
                result carries patterns or no error message.
        """
        if self.succeeded and self.error_message is not None:
            raise ValidationError(
                "PatternExtractionResult: error_message must be None when succeeded is True"
            )
        if not self.succeeded and self.patterns:
            raise ValidationError(
                "PatternExtractionResult: patterns must be empty when succeeded is False"
            )
        if not self.succeeded and self.error_message is None:
            raise ValidationError(
                "PatternExtractionResult: error_message is required when succeeded is False"
            )

    @classmethod
    def ok(
        cls, *, relative_path: str, patterns: Sequence[ExtractedPattern] = ()
    ) -> "PatternExtractionResult":
        """Build a successful result.

        Args:
            relative_path: The file that was extracted from.
            patterns: Code patterns recognized in the file, possibly empty.

        Returns:
            A `PatternExtractionResult` with `succeeded=True`.
        """
        return cls(relative_path=relative_path, succeeded=True, patterns=tuple(patterns))

    @classmethod
    def failed(cls, *, relative_path: str, error_message: str) -> "PatternExtractionResult":
        """Build a failed result.

        Args:
            relative_path: The file that extraction was attempted against.
            error_message: Human-readable explanation of the failure.

        Returns:
            A `PatternExtractionResult` with `succeeded=False`.
        """
        _logger.debug("Pattern extraction failed for '%s': %s", relative_path, error_message)
        return cls(relative_path=relative_path, succeeded=False, error_message=error_message)


class PatternExtractor(ABC):
    """Extracts recognizable, reusable code patterns from a single file's already-parsed
    structure.

    A concrete implementation decides which named patterns a file's classes and functions
    match; it does not judge whether using a given pattern was appropriate here (see the future
    `analyzers` phase) and does not decide whether a matched pattern is itself worth reusing
    elsewhere (see `extractors.foundation`).
    """

    @abstractmethod
    def extract(self, parse_result: ParseResult) -> PatternExtractionResult:
        """Extract recognizable code patterns for the file described by `parse_result`.

        Args:
            parse_result: The outcome of parsing one file, as produced by `src.parsers`.

        Returns:
            A successful result carrying the file's `ExtractedPattern` entries, or a failed
            result carrying an explanation, if patterns cannot be derived from `parse_result`.

        Raises:
            ValidationError: If `parse_result.succeeded` is False -- extraction requires a
                successfully parsed file.
        """
        ...


def require_successful_parse(parse_result: ParseResult) -> ParseResult:
    """Validate that `parse_result` represents a successful parse.

    Every `PatternExtractor.extract` implementation calls this first, so a caller error (a
    `ParseResult` with `succeeded=False`) is reported the same way -- as an immediate
    `ValidationError` -- across every implementation.

    Args:
        parse_result: The raw `parse_result` argument passed to `extract`.

    Returns:
        `parse_result`, unchanged.

    Raises:
        ValidationError: If `parse_result.succeeded` is False.
    """
    if not parse_result.succeeded:
        _logger.debug(
            "Rejected extraction from an unsuccessful parse of '%s'", parse_result.relative_path
        )
        raise ValidationError(
            "cannot extract patterns from a failed ParseResult",
            details={"relative_path": parse_result.relative_path},
        )
    return parse_result
