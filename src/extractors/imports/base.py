"""Import extractor Port: dependency/import extraction.

`ImportExtractor` turns a single file's `parsers.base.ParseResult` into a normalized list of
`DependencyEdge` entries -- one per import statement the file contains, classified as internal
(same-project) or external, with its imported names and alias carried through. This is a
reusable, per-file dependency listing; assembling many files' edges into a repository-wide
dependency graph is a `graph` concern, a later, not-yet-built phase this Port does not perform.
"""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass

from src.core.exceptions import ValidationError
from src.core.logging import get_logger
from src.parsers.base import ParseResult

_logger = get_logger("extractors.imports")


@dataclass(frozen=True, slots=True)
class DependencyEdge:
    """A single normalized dependency, derived from one file's one import statement.

    Attributes:
        source_path: Path of the file the import statement was found in.
        target_module: The imported module, path, or header, exactly as it identifies the thing
            being imported (carried through from `parsers.base.ParsedImport.module`).
        imported_names: Specific names pulled from `target_module`, if the import form names
            them individually. Empty when the statement imports the module as a whole.
        alias: The local alias the import is bound to, if any.
        is_internal: Whether `target_module` refers to another file within the same project (a
            relative or local path) rather than an external package, crate, or system library --
            carried through from `ParsedImport.is_relative`.
        line_number: 1-indexed line the statement starts on in `source_path`. 0 if unknown.
    """

    source_path: str
    target_module: str
    imported_names: tuple[str, ...] = ()
    alias: str | None = None
    is_internal: bool = False
    line_number: int = 0


@dataclass(frozen=True, slots=True)
class ImportExtractionResult:
    """Outcome of a single `ImportExtractor.extract` call.

    Attributes:
        relative_path: The file extraction was attempted against.
        succeeded: Whether extraction completed successfully.
        edges: The file's normalized dependency edges. Always empty when `succeeded` is False;
            may legitimately be empty when `succeeded` is True too (a file with no imports).
        error_message: Explanation of the failure. Always None when `succeeded` is True, always
            set when `succeeded` is False.
    """

    relative_path: str
    succeeded: bool
    edges: tuple[DependencyEdge, ...] = ()
    error_message: str | None = None

    def __post_init__(self) -> None:
        """Validate that `succeeded`, `edges`, and `error_message` are consistent.

        Raises:
            ValidationError: If a successful result carries an error message, or a failed
                result carries edges or no error message.
        """
        if self.succeeded and self.error_message is not None:
            raise ValidationError(
                "ImportExtractionResult: error_message must be None when succeeded is True"
            )
        if not self.succeeded and self.edges:
            raise ValidationError(
                "ImportExtractionResult: edges must be empty when succeeded is False"
            )
        if not self.succeeded and self.error_message is None:
            raise ValidationError(
                "ImportExtractionResult: error_message is required when succeeded is False"
            )

    @classmethod
    def ok(
        cls, *, relative_path: str, edges: Sequence[DependencyEdge] = ()
    ) -> "ImportExtractionResult":
        """Build a successful result.

        Args:
            relative_path: The file that was extracted from.
            edges: Normalized dependency edges found in the file, possibly empty.

        Returns:
            An `ImportExtractionResult` with `succeeded=True`.
        """
        return cls(relative_path=relative_path, succeeded=True, edges=tuple(edges))

    @classmethod
    def failed(cls, *, relative_path: str, error_message: str) -> "ImportExtractionResult":
        """Build a failed result.

        Args:
            relative_path: The file that extraction was attempted against.
            error_message: Human-readable explanation of the failure.

        Returns:
            An `ImportExtractionResult` with `succeeded=False`.
        """
        _logger.debug("Import extraction failed for '%s': %s", relative_path, error_message)
        return cls(relative_path=relative_path, succeeded=False, error_message=error_message)


class ImportExtractor(ABC):
    """Extracts a single file's normalized dependency edges from its already-parsed imports.

    A concrete implementation decides how a file's raw `parsers.base.ParsedImport` entries map
    onto reusable `DependencyEdge` values; it does not resolve a target module to an actual file
    on disk, and does not assemble edges from multiple files into a dependency graph -- both are
    separate, not-yet-scoped concerns belonging to the future `graph` phase.
    """

    @abstractmethod
    def extract(self, parse_result: ParseResult) -> ImportExtractionResult:
        """Extract normalized dependency edges for the file described by `parse_result`.

        Args:
            parse_result: The outcome of parsing one file, as produced by `src.parsers`.

        Returns:
            A successful result carrying the file's `DependencyEdge` entries, or a failed
            result carrying an explanation, if edges cannot be derived from `parse_result`.

        Raises:
            ValidationError: If `parse_result.succeeded` is False -- extraction requires a
                successfully parsed file.
        """
        ...


def require_successful_parse(parse_result: ParseResult) -> ParseResult:
    """Validate that `parse_result` represents a successful parse.

    Every `ImportExtractor.extract` implementation calls this first, so a caller error (a
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
            "cannot extract imports from a failed ParseResult",
            details={"relative_path": parse_result.relative_path},
        )
    return parse_result
