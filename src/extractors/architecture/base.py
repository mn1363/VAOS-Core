"""Architecture extractor Port: package/module structure extraction.

`ArchitectureExtractor` turns a single file's `parsers.base.ParseResult` into a normalized
description of where that file sits in its repository's package/module structure -- which
package it belongs to, whether it is that package's own root marker, and which nested
modules/namespaces it declares -- without judging whether that structure is *good*. Layering
violations, cohesion, and reuse-worthiness are `analyzers`/`foundation` concerns; assembling many
files' units into a full package tree or dependency graph is a `graph` concern. Both are later,
not-yet-built phases -- this Port only describes one file's own placement.

Like `parsers.base.Parser.parse`, `extract` operates on already-produced, in-memory data -- here
a `ParseResult` rather than raw file content -- and performs no I/O, no cross-file aggregation,
and no scoring of its own.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from src.core.exceptions import ValidationError
from src.core.logging import get_logger
from src.parsers.base import ParsedModule, ParseResult

_logger = get_logger("extractors.architecture")

#: Filenames that conventionally mark the directory containing them as a package, across the
#: languages `src.parsers` supports. Matched against the final `/`-separated segment of a
#: `relative_path`, case-sensitively, since a file's own name is not itself normalized.
_PACKAGE_ROOT_MARKERS = ("__init__.py", "__init__.pyi", "mod.rs", "index.ts")


@dataclass(frozen=True, slots=True)
class PackageUnit:
    """The architectural placement of a single parsed file.

    Attributes:
        relative_path: Path of the source file this unit was derived from, exactly as carried
            by the originating `ParseResult`.
        package_path: The file's package/namespace path, as a tuple of directory segments (e.g.
            `("src", "extractors", "architecture")` for `src/extractors/architecture/base.py`),
            derived from `relative_path`'s directory portion rather than re-parsed from source.
        is_package_root: Whether `relative_path` itself is the conventional marker file that
            makes `package_path` a package (e.g. an `__init__.py`), rather than an ordinary
            member of it.
        declared_modules: Nested module, package-clause, or namespace declarations the file
            itself contains, taken directly from the originating `ParseResult.modules`.
    """

    relative_path: str
    package_path: tuple[str, ...]
    is_package_root: bool = False
    declared_modules: tuple[ParsedModule, ...] = ()


@dataclass(frozen=True, slots=True)
class ArchitectureExtractionResult:
    """Outcome of a single `ArchitectureExtractor.extract` call.

    Attributes:
        relative_path: The file extraction was attempted against.
        succeeded: Whether extraction completed successfully.
        unit: The extracted package/module unit. Always present when `succeeded` is True, always
            None when `succeeded` is False.
        error_message: Explanation of the failure. Always None when `succeeded` is True, always
            set when `succeeded` is False.
    """

    relative_path: str
    succeeded: bool
    unit: PackageUnit | None = None
    error_message: str | None = None

    def __post_init__(self) -> None:
        """Validate that `succeeded`, `unit`, and `error_message` are consistent.

        Raises:
            ValidationError: If a successful result is missing `unit` or carries an error
                message, or a failed result carries a `unit` or no error message.
        """
        if self.succeeded:
            if self.error_message is not None:
                raise ValidationError(
                    "ArchitectureExtractionResult: error_message must be None when succeeded "
                    "is True"
                )
            if self.unit is None:
                raise ValidationError(
                    "ArchitectureExtractionResult: unit is required when succeeded is True"
                )
        else:
            if self.unit is not None:
                raise ValidationError(
                    "ArchitectureExtractionResult: unit must be None when succeeded is False"
                )
            if self.error_message is None:
                raise ValidationError(
                    "ArchitectureExtractionResult: error_message is required when succeeded "
                    "is False"
                )

    @classmethod
    def ok(cls, *, relative_path: str, unit: PackageUnit) -> "ArchitectureExtractionResult":
        """Build a successful result.

        Args:
            relative_path: The file that was extracted from.
            unit: The extracted package/module unit.

        Returns:
            An `ArchitectureExtractionResult` with `succeeded=True`.
        """
        return cls(relative_path=relative_path, succeeded=True, unit=unit)

    @classmethod
    def failed(cls, *, relative_path: str, error_message: str) -> "ArchitectureExtractionResult":
        """Build a failed result.

        Args:
            relative_path: The file that extraction was attempted against.
            error_message: Human-readable explanation of the failure.

        Returns:
            An `ArchitectureExtractionResult` with `succeeded=False`.
        """
        _logger.debug("Architecture extraction failed for '%s': %s", relative_path, error_message)
        return cls(relative_path=relative_path, succeeded=False, error_message=error_message)


class ArchitectureExtractor(ABC):
    """Extracts a single file's package/module placement from its already-parsed structure.

    A concrete implementation decides *where a file sits* in its repository's package/module
    structure; it does not decide whether that structure is well-designed (see the future
    `analyzers` phase) nor assemble multiple files' units into a repository-wide tree (see the
    future `graph` phase) -- both are separate, not-yet-scoped concerns belonging to other
    layers.
    """

    @abstractmethod
    def extract(self, parse_result: ParseResult) -> ArchitectureExtractionResult:
        """Extract the package/module unit for the file described by `parse_result`.

        Args:
            parse_result: The outcome of parsing one file, as produced by `src.parsers`.

        Returns:
            A successful result carrying the file's `PackageUnit`, or a failed result carrying
            an explanation, if a unit cannot be derived from `parse_result`.

        Raises:
            ValidationError: If `parse_result.succeeded` is False -- extraction requires a
                successfully parsed file; a parser failure is the parser's own reported outcome,
                not something this layer re-derives structure from.
        """
        ...


def require_successful_parse(parse_result: ParseResult) -> ParseResult:
    """Validate that `parse_result` represents a successful parse.

    Every `ArchitectureExtractor.extract` implementation calls this first, so a caller error (a
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
            "cannot extract architecture from a failed ParseResult",
            details={"relative_path": parse_result.relative_path},
        )
    return parse_result


def is_package_root_marker(relative_path: str) -> bool:
    """Report whether `relative_path`'s final segment is a conventional package-root marker.

    Args:
        relative_path: Path of the candidate file, typically relative to a repository root.

    Returns:
        True if the file's own name (the last `/`-separated segment) exactly matches one of the
        conventional marker filenames this Port recognizes (e.g. `__init__.py`).
    """
    name = relative_path.rsplit("/", 1)[-1]
    return name in _PACKAGE_ROOT_MARKERS
