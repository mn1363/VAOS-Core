"""`Collector` for a single local directory treated directly as one repository."""

from pathlib import Path

from src.domain.entities import RepositoryProvider, SourceRepository

from .base import CollectionResult, Collector, require_source


class FilesystemCollector(Collector):
    """Treats one local directory as a single `SourceRepository`, git-managed or not.

    Use this when the caller already knows exactly which directory to analyze. Unlike
    `LocalCollector`, which scans a directory *tree* for however many git repositories it
    contains, this always produces at most one repository and does not require `.git` to be
    present -- a plain, unversioned folder of source code is a valid `source`.
    """

    @property
    def provider(self) -> RepositoryProvider:
        """The provider this collector produces entities for.

        Returns:
            `RepositoryProvider.FILESYSTEM`.
        """
        return RepositoryProvider.FILESYSTEM

    async def collect(self, source: str) -> CollectionResult:
        """Describe the directory at `source` as a `SourceRepository`.

        Args:
            source: Filesystem path of the directory to treat as a repository.

        Returns:
            A result containing exactly one repository if `source` is an existing directory, or
            a failed result if it is not.

        Raises:
            ValidationError: If `source` is blank.
        """
        require_source(source)
        path = Path(source).expanduser()
        if not path.is_dir():
            return CollectionResult.failed(source, f"not a directory: '{path}'")
        resolved = path.resolve()
        repository = SourceRepository(
            name=resolved.name or str(resolved),
            source_uri=str(resolved),
            provider=RepositoryProvider.FILESYSTEM,
        )
        return CollectionResult.ok(source, [repository])
