"""Structural architecture extractor: the first concrete `ArchitectureExtractor`
implementation.

`StructuralArchitectureExtractor` derives a file's `PackageUnit` directly from its
already-parsed `parsers.base.ParseResult` and its own `relative_path`: `package_path` is a
pure string split of `relative_path`'s directory portion, `is_package_root` is a direct
call-through to the already-frozen `is_package_root_marker`, and `declared_modules` is a
verbatim copy of `parse_result.modules`. It performs no naming-convention inference, no Go
package-root invention, no cross-file analysis, and no module resolution; see
`ArchitectureExtractor`'s own docstring in `base.py` for what is deliberately out of scope.
"""

from src.extractors.architecture.base import (
    ArchitectureExtractionResult,
    ArchitectureExtractor,
    PackageUnit,
    is_package_root_marker,
    require_successful_parse,
)
from src.parsers.base import ParseResult


class StructuralArchitectureExtractor(ArchitectureExtractor):
    """Maps a file's already-parsed structure onto its `PackageUnit`, one for one.

    Stateless and dependency-free: a single instance handles `ParseResult`s from every one of
    the five existing `Parser` implementations, since `package_path` and `is_package_root` are
    derived from `relative_path` alone and `declared_modules` is copied straight from
    `parse_result.modules`, which each parser already normalizes into the same shape before
    this extractor ever sees it.
    """

    def extract(self, parse_result: ParseResult) -> ArchitectureExtractionResult:
        """Extract the package/module unit for the file described by `parse_result`.

        Args:
            parse_result: The outcome of parsing one file, as produced by `src.parsers`.

        Returns:
            A successful result carrying the file's `PackageUnit`: `package_path` derived from
            `relative_path`'s directory portion, `is_package_root` from
            `is_package_root_marker`, and `declared_modules` copied verbatim from
            `parse_result.modules`, source order preserved, duplicates included.

        Raises:
            ValidationError: If `parse_result.succeeded` is False.
        """
        require_successful_parse(parse_result)

        unit = PackageUnit(
            relative_path=parse_result.relative_path,
            package_path=_package_path(parse_result.relative_path),
            is_package_root=is_package_root_marker(parse_result.relative_path),
            declared_modules=parse_result.modules,
        )
        return ArchitectureExtractionResult.ok(
            relative_path=parse_result.relative_path, unit=unit
        )


def _package_path(relative_path: str) -> tuple[str, ...]:
    """Derive a file's package/namespace path from the directory portion of `relative_path`.

    Args:
        relative_path: Path of the file, `/`-separated, typically relative to a repository
            root.

    Returns:
        `relative_path`'s directory portion, split on `/`, as a tuple of segments -- e.g.
        `("src", "extractors", "architecture")` for `src/extractors/architecture/base.py`.
        `()` for a root-level file with no `/` in `relative_path`.
    """
    if "/" not in relative_path:
        return ()
    directory = relative_path.rsplit("/", 1)[0]
    return tuple(directory.split("/"))
