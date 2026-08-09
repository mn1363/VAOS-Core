"""AST extractor Port: AST metadata extraction.

`AstExtractor` turns a single file's `parsers.base.ParseResult` into a compact set of structural
counts and facts about its parsed content -- how many classes, functions, methods, imports,
exports, and symbols it declares, how many of its functions are asynchronous, and how many of
its classes and functions carry a docstring. These are reusable structural *facts*, not a
judgment of whether the file is well-written, well-tested, or reusable -- quality scoring
belongs to the future `analyzers` phase, and foundation-worthiness to `extractors.foundation`,
neither of which this Port performs.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from src.core.exceptions import ValidationError
from src.core.logging import get_logger
from src.parsers.base import ParseResult

_logger = get_logger("extractors.ast")

#: Names of every non-negative count field on `AstMetadata`, used to validate them uniformly.
_COUNT_FIELDS = (
    "class_count",
    "function_count",
    "method_count",
    "import_count",
    "export_count",
    "symbol_count",
    "module_count",
    "async_function_count",
    "documented_class_count",
    "documented_function_count",
    "line_count",
)


@dataclass(frozen=True, slots=True)
class AstMetadata:
    """Structural counts and facts derived from a single file's parsed content.

    Attributes:
        relative_path: Path of the source file this metadata was derived from.
        class_count: Number of classes found in the file.
        function_count: Number of free functions found in the file (methods are counted
            separately, in `method_count`).
        method_count: Number of methods found across every class in the file.
        import_count: Number of import statements found in the file.
        export_count: Number of explicitly exported names found in the file.
        symbol_count: Total number of entries in the file's flat symbol table.
        module_count: Number of nested module/namespace declarations found in the file.
        async_function_count: Number of functions and methods declared `async`.
        documented_class_count: Number of classes carrying a docstring.
        documented_function_count: Number of functions and methods carrying a docstring.
        line_count: Number of lines in the file's content, taken from `FileMetadata`.
    """

    relative_path: str
    class_count: int = 0
    function_count: int = 0
    method_count: int = 0
    import_count: int = 0
    export_count: int = 0
    symbol_count: int = 0
    module_count: int = 0
    async_function_count: int = 0
    documented_class_count: int = 0
    documented_function_count: int = 0
    line_count: int = 0

    def __post_init__(self) -> None:
        """Validate that every count field is non-negative.

        Raises:
            ValidationError: If any count field is negative.
        """
        for field_name in _COUNT_FIELDS:
            if getattr(self, field_name) < 0:
                raise ValidationError(f"AstMetadata: {field_name} must not be negative")


@dataclass(frozen=True, slots=True)
class AstExtractionResult:
    """Outcome of a single `AstExtractor.extract` call.

    Attributes:
        relative_path: The file extraction was attempted against.
        succeeded: Whether extraction completed successfully.
        metadata: The extracted structural metadata. Always present when `succeeded` is True,
            always None when `succeeded` is False.
        error_message: Explanation of the failure. Always None when `succeeded` is True, always
            set when `succeeded` is False.
    """

    relative_path: str
    succeeded: bool
    metadata: AstMetadata | None = None
    error_message: str | None = None

    def __post_init__(self) -> None:
        """Validate that `succeeded`, `metadata`, and `error_message` are consistent.

        Raises:
            ValidationError: If a successful result is missing `metadata` or carries an error
                message, or a failed result carries `metadata` or no error message.
        """
        if self.succeeded:
            if self.error_message is not None:
                raise ValidationError(
                    "AstExtractionResult: error_message must be None when succeeded is True"
                )
            if self.metadata is None:
                raise ValidationError(
                    "AstExtractionResult: metadata is required when succeeded is True"
                )
        else:
            if self.metadata is not None:
                raise ValidationError(
                    "AstExtractionResult: metadata must be None when succeeded is False"
                )
            if self.error_message is None:
                raise ValidationError(
                    "AstExtractionResult: error_message is required when succeeded is False"
                )

    @classmethod
    def ok(cls, *, relative_path: str, metadata: AstMetadata) -> "AstExtractionResult":
        """Build a successful result.

        Args:
            relative_path: The file that was extracted from.
            metadata: The extracted structural metadata.

        Returns:
            An `AstExtractionResult` with `succeeded=True`.
        """
        return cls(relative_path=relative_path, succeeded=True, metadata=metadata)

    @classmethod
    def failed(cls, *, relative_path: str, error_message: str) -> "AstExtractionResult":
        """Build a failed result.

        Args:
            relative_path: The file that extraction was attempted against.
            error_message: Human-readable explanation of the failure.

        Returns:
            An `AstExtractionResult` with `succeeded=False`.
        """
        _logger.debug("AST extraction failed for '%s': %s", relative_path, error_message)
        return cls(relative_path=relative_path, succeeded=False, error_message=error_message)


class AstExtractor(ABC):
    """Extracts structural counts and facts from a single file's already-parsed content.

    A concrete implementation decides *how much* structure a file contains -- counts, not
    judgments. It does not score complexity or quality (see the future `analyzers` phase) and
    does not decide whether any individual construct is foundation-worthy (see
    `extractors.foundation`) -- both are separate concerns belonging elsewhere.
    """

    @abstractmethod
    def extract(self, parse_result: ParseResult) -> AstExtractionResult:
        """Extract structural metadata for the file described by `parse_result`.

        Args:
            parse_result: The outcome of parsing one file, as produced by `src.parsers`.

        Returns:
            A successful result carrying the file's `AstMetadata`, or a failed result carrying
            an explanation, if metadata cannot be derived from `parse_result`.

        Raises:
            ValidationError: If `parse_result.succeeded` is False -- extraction requires a
                successfully parsed file.
        """
        ...


def require_successful_parse(parse_result: ParseResult) -> ParseResult:
    """Validate that `parse_result` represents a successful parse.

    Every `AstExtractor.extract` implementation calls this first, so a caller error (a
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
            "cannot extract AST metadata from a failed ParseResult",
            details={"relative_path": parse_result.relative_path},
        )
    return parse_result
