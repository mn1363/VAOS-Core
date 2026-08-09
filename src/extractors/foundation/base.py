"""Foundation extractor Port: foundation candidate extraction.

`FoundationExtractor` turns a single file's `parsers.base.ParseResult` into a list of
`FoundationCandidate` entries -- classes and functions that carry the raw, observable signals a
later phase would want when deciding what is worth reusing (public visibility, a docstring,
freedom from file-local coupling). Surfacing these signals is this Port's whole job; combining
them into a score and *selecting* which candidates actually become part of a foundation is a
separate concern belonging to the future `foundation` phase (a different, not-yet-built package
from this one, despite the shared name), which this Port does not perform.
"""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum, auto

from src.core.exceptions import ValidationError
from src.core.logging import get_logger
from src.parsers.base import ParseResult

_logger = get_logger("extractors.foundation")


class FoundationCandidateKind(StrEnum):
    """The kind of construct a single `FoundationCandidate` represents."""

    CLASS = auto()
    FUNCTION = auto()


@dataclass(frozen=True, slots=True)
class FoundationCandidate:
    """A single class or function carrying raw signals relevant to future reuse decisions.

    Attributes:
        name: The candidate's name.
        kind: What kind of construct this candidate is.
        relative_path: Path of the file the candidate was found in.
        is_public: Whether the construct is visible outside its declaring file (e.g. present in
            the file's `ParseResult.exports`, or not prefixed with a language's private-naming
            convention).
        has_docstring: Whether the construct carries its own documentation comment or docstring.
        signals: Freeform, human-readable observations supporting (or complicating) this
            construct's candidacy (e.g. `"no base classes"`, `"decorated with @dataclass"`),
            for a consumer that wants to know *why* without re-deriving it. Deliberately not a
            numeric score: combining these into one is a decision for the future `foundation`
            phase, not this extraction step.
        line_number: 1-indexed line the candidate is declared on. 0 if unknown.
    """

    name: str
    kind: FoundationCandidateKind
    relative_path: str
    is_public: bool = False
    has_docstring: bool = False
    signals: tuple[str, ...] = ()
    line_number: int = 0


@dataclass(frozen=True, slots=True)
class FoundationExtractionResult:
    """Outcome of a single `FoundationExtractor.extract` call.

    Attributes:
        relative_path: The file extraction was attempted against.
        succeeded: Whether extraction completed successfully.
        candidates: The file's extracted foundation candidates. Always empty when `succeeded` is
            False; may legitimately be empty when `succeeded` is True too (a file with no
            candidates worth surfacing).
        error_message: Explanation of the failure. Always None when `succeeded` is True, always
            set when `succeeded` is False.
    """

    relative_path: str
    succeeded: bool
    candidates: tuple[FoundationCandidate, ...] = ()
    error_message: str | None = None

    def __post_init__(self) -> None:
        """Validate that `succeeded`, `candidates`, and `error_message` are consistent.

        Raises:
            ValidationError: If a successful result carries an error message, or a failed
                result carries candidates or no error message.
        """
        if self.succeeded and self.error_message is not None:
            raise ValidationError(
                "FoundationExtractionResult: error_message must be None when succeeded is True"
            )
        if not self.succeeded and self.candidates:
            raise ValidationError(
                "FoundationExtractionResult: candidates must be empty when succeeded is False"
            )
        if not self.succeeded and self.error_message is None:
            raise ValidationError(
                "FoundationExtractionResult: error_message is required when succeeded is False"
            )

    @classmethod
    def ok(
        cls, *, relative_path: str, candidates: Sequence[FoundationCandidate] = ()
    ) -> "FoundationExtractionResult":
        """Build a successful result.

        Args:
            relative_path: The file that was extracted from.
            candidates: Foundation candidates found in the file, possibly empty.

        Returns:
            A `FoundationExtractionResult` with `succeeded=True`.
        """
        return cls(relative_path=relative_path, succeeded=True, candidates=tuple(candidates))

    @classmethod
    def failed(cls, *, relative_path: str, error_message: str) -> "FoundationExtractionResult":
        """Build a failed result.

        Args:
            relative_path: The file that extraction was attempted against.
            error_message: Human-readable explanation of the failure.

        Returns:
            A `FoundationExtractionResult` with `succeeded=False`.
        """
        _logger.debug("Foundation extraction failed for '%s': %s", relative_path, error_message)
        return cls(relative_path=relative_path, succeeded=False, error_message=error_message)


class FoundationExtractor(ABC):
    """Extracts raw foundation-candidacy signals from a single file's already-parsed structure.

    A concrete implementation decides which observable signals apply to each class and function
    in a file; it does not combine those signals into a score and does not select which
    candidates actually belong in a foundation -- both are separate, not-yet-scoped concerns
    belonging to the future `foundation` phase.
    """

    @abstractmethod
    def extract(self, parse_result: ParseResult) -> FoundationExtractionResult:
        """Extract foundation candidates for the file described by `parse_result`.

        Args:
            parse_result: The outcome of parsing one file, as produced by `src.parsers`.

        Returns:
            A successful result carrying the file's `FoundationCandidate` entries, or a failed
            result carrying an explanation, if candidates cannot be derived from `parse_result`.

        Raises:
            ValidationError: If `parse_result.succeeded` is False -- extraction requires a
                successfully parsed file.
        """
        ...


def require_successful_parse(parse_result: ParseResult) -> ParseResult:
    """Validate that `parse_result` represents a successful parse.

    Every `FoundationExtractor.extract` implementation calls this first, so a caller error (a
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
            "cannot extract foundation candidates from a failed ParseResult",
            details={"relative_path": parse_result.relative_path},
        )
    return parse_result
