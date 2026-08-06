"""Concrete `WorkspaceManager` implementation using local filesystem directories.

Allocates one subdirectory, named after the repository's UUID, under a
configurable root directory -- deterministic and collision-free without
needing any external bookkeeping (a database, an index file, etc.).
"""

import shutil
from pathlib import Path
from uuid import UUID

from src.core.logging import get_logger
from src.core.utils import ensure_directory

from .base import WorkspaceManager

_logger = get_logger("repository.workspace")


class FilesystemWorkspaceManager(WorkspaceManager):
    """A `WorkspaceManager` that allocates one directory per repository under a root."""

    def __init__(self, root: Path) -> None:
        """Initialize the manager, creating `root` if it does not exist.

        Args:
            root: Base directory under which one subdirectory per
                repository is allocated.
        """
        self._root = ensure_directory(root)

    def allocate(self, repository_id: UUID) -> Path:
        """Allocate a workspace directory for `repository_id`, creating it if needed.

        Args:
            repository_id: Identifier of the repository the workspace is for.

        Returns:
            Path of the (now-existing) workspace directory.
        """
        path = self._path_for(repository_id)
        ensure_directory(path)
        _logger.debug("Allocated workspace for %s at %s", repository_id, path)
        return path

    def resolve(self, repository_id: UUID) -> Path | None:
        """Return the existing workspace path for `repository_id`, if any.

        Args:
            repository_id: Identifier of the repository to look up.

        Returns:
            The workspace path, or None if it does not exist.
        """
        path = self._path_for(repository_id)
        return path if path.is_dir() else None

    def exists(self, repository_id: UUID) -> bool:
        """Report whether a workspace already exists for `repository_id`.

        Args:
            repository_id: Identifier of the repository to check.

        Returns:
            True if a workspace directory currently exists.
        """
        return self._path_for(repository_id).is_dir()

    def remove(self, repository_id: UUID) -> None:
        """Remove the workspace directory for `repository_id`, if it exists.

        Args:
            repository_id: Identifier of the repository whose workspace
                should be removed.
        """
        path = self._path_for(repository_id)
        if path.is_dir():
            shutil.rmtree(path)
            _logger.debug("Removed workspace for %s at %s", repository_id, path)

    def _path_for(self, repository_id: UUID) -> Path:
        """Compute the deterministic workspace path for `repository_id`.

        Args:
            repository_id: Identifier of the repository.

        Returns:
            `root / str(repository_id)`, not guaranteed to exist.
        """
        return self._root / str(repository_id)
