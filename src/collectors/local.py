"""`Collector` that scans a local directory tree for nested git repositories."""

import asyncio
import os
from pathlib import Path

from src.domain.entities import RepositoryProvider, SourceRepository

from .base import CollectionResult, Collector, require_source

#: Default ceiling on how many directory levels below the scan root are visited.
_DEFAULT_MAX_DEPTH = 5


class LocalCollector(Collector):
    """Scans a local directory tree for nested git repositories.

    A directory is recognized as a repository when it directly contains a `.git` entry.
    Discovered repositories are not descended into further -- nested worktrees and submodules
    are a `repository`-layer concern, not a discovery concern -- and any directory whose name
    starts with `.` is skipped, so common hidden directories are never traversed. The scan runs
    on a worker thread via `asyncio.to_thread`, since a large tree can take long enough to walk
    that running it directly on the event loop would block every other coroutine.
    """

    def __init__(self, *, max_depth: int = _DEFAULT_MAX_DEPTH) -> None:
        """Initialize the collector.

        Args:
            max_depth: Maximum number of directory levels below the scan root to visit. The
                root itself is depth 0, so a repository sitting exactly `max_depth` levels
                below the root is still found; only deeper directories are skipped.
        """
        self._max_depth = max_depth

    @property
    def provider(self) -> RepositoryProvider:
        """The provider this collector produces entities for.

        Returns:
            `RepositoryProvider.LOCAL`.
        """
        return RepositoryProvider.LOCAL

    async def collect(self, source: str) -> CollectionResult:
        """Scan the directory tree rooted at `source` for git repositories.

        Args:
            source: Filesystem path of the directory to scan.

        Returns:
            A result containing every repository found under `source`, sorted by resolved path.
            Succeeds with zero repositories when `source` contains none.

        Raises:
            ValidationError: If `source` is blank.
        """
        require_source(source)
        root = Path(source).expanduser()
        if not root.is_dir():
            return CollectionResult.failed(source, f"not a directory: '{root}'")
        repositories = await asyncio.to_thread(self._scan, root.resolve())
        return CollectionResult.ok(source, repositories)

    def _scan(self, root: Path) -> list[SourceRepository]:
        """Walk `root`, collecting one `SourceRepository` per nested git repository.

        Args:
            root: Already-resolved directory to scan.

        Returns:
            Discovered repositories, sorted by `source_uri`.
        """
        discovered: list[SourceRepository] = []
        root_depth = len(root.parts)
        for dirpath, dirnames, _filenames in os.walk(root, topdown=True):
            current = Path(dirpath)
            depth = len(current.parts) - root_depth
            if ".git" in dirnames:
                discovered.append(
                    SourceRepository(
                        name=current.name or str(current),
                        source_uri=str(current),
                        provider=RepositoryProvider.LOCAL,
                    )
                )
                dirnames.clear()
                continue
            if depth >= self._max_depth:
                dirnames.clear()
                continue
            dirnames[:] = [name for name in dirnames if not name.startswith(".")]
        return sorted(discovered, key=lambda repository: repository.source_uri)
