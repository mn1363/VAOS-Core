"""Repository-layer Ports: abstract contracts `git.py` and `workspace.py`
implement, per Dependency Inversion -- consumers of this package should
depend on these abstractions, not on the concrete adapters directly.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from uuid import UUID

from src.core.exceptions import VAOSError
from src.domain.entities import SourceRepository


class GitCommandError(VAOSError):
    """Raised when an underlying `git` command fails or cannot be run.

    Attributes:
        message: Human-readable description of what went wrong.
        details: Structured context, typically including the command that
            was run and, when the process started but exited non-zero,
            its exit code and captured stderr.
    """


class RepositoryClient(ABC):
    """Abstract Port for obtaining and updating a local git working copy.

    Every method takes an explicit filesystem path rather than tracking
    state internally, so a single client instance can service any number
    of concurrently-managed workspaces.
    """

    @abstractmethod
    async def clone(
        self, repository: SourceRepository, destination: Path, *, shallow: bool = True
    ) -> None:
        """Clone `repository` into `destination`.

        Args:
            repository: The repository to clone; `source_uri` is the
                location cloned from and `default_branch` is the branch
                checked out.
            destination: Local directory to clone into. Must not already
                exist as a non-empty directory.
            shallow: If True (the default), clone with a truncated commit
                history (depth 1) to save bandwidth and disk space, which
                is sufficient for point-in-time analysis. Pass False when
                the full commit history is needed.

        Raises:
            GitCommandError: If the clone fails for any reason (network
                failure, invalid URL, authentication failure, timeout).
        """
        ...

    @abstractmethod
    async def fetch(self, workspace_path: Path) -> None:
        """Fetch the latest refs for the repository checked out at `workspace_path`.

        Args:
            workspace_path: Local directory containing an existing clone.

        Raises:
            GitCommandError: If the fetch fails, including when
                `workspace_path` is not a git repository.
        """
        ...

    @abstractmethod
    async def checkout(self, workspace_path: Path, ref: str) -> None:
        """Check out `ref` (branch, tag, or commit) in the repository at `workspace_path`.

        Args:
            workspace_path: Local directory containing an existing clone.
            ref: Branch name, tag name, or commit SHA to check out.

        Raises:
            GitCommandError: If the checkout fails, including when `ref`
                does not exist.
        """
        ...

    @abstractmethod
    async def current_commit(self, workspace_path: Path) -> str:
        """Return the full commit SHA currently checked out at `workspace_path`.

        Args:
            workspace_path: Local directory containing an existing clone.

        Returns:
            The 40-character commit SHA of `HEAD`.

        Raises:
            GitCommandError: If the SHA cannot be resolved, including when
                `workspace_path` is not a git repository.
        """
        ...

    @abstractmethod
    async def default_branch(self, workspace_path: Path) -> str:
        """Return the name of the repository's default branch.

        Args:
            workspace_path: Local directory containing an existing clone.

        Returns:
            The default branch name (e.g. `"main"`), as recorded by the
            `origin` remote's `HEAD`.

        Raises:
            GitCommandError: If the default branch cannot be resolved.
        """
        ...


class WorkspaceManager(ABC):
    """Abstract Port for allocating and managing local filesystem workspaces.

    Filesystem bookkeeping is fast and local, so -- unlike
    `RepositoryClient`, whose methods perform network I/O and subprocess
    execution -- every method here is synchronous.
    """

    @abstractmethod
    def allocate(self, repository_id: UUID) -> Path:
        """Allocate a workspace directory for `repository_id`, creating it if needed.

        Args:
            repository_id: Identifier of the repository the workspace is for.

        Returns:
            Path of the (now-existing) workspace directory. Calling this
            again with the same id returns the same path.
        """
        ...

    @abstractmethod
    def resolve(self, repository_id: UUID) -> Path | None:
        """Return the existing workspace path for `repository_id`, if any.

        Args:
            repository_id: Identifier of the repository to look up.

        Returns:
            The workspace path, or None if no workspace has been
            allocated for this id (or it was removed).
        """
        ...

    @abstractmethod
    def exists(self, repository_id: UUID) -> bool:
        """Report whether a workspace already exists for `repository_id`.

        Args:
            repository_id: Identifier of the repository to check.

        Returns:
            True if a workspace directory currently exists.
        """
        ...

    @abstractmethod
    def remove(self, repository_id: UUID) -> None:
        """Remove the workspace directory for `repository_id`, if it exists.

        Args:
            repository_id: Identifier of the repository whose workspace
                should be removed.

        A repository with no allocated workspace is not an error; this is
        a no-op in that case.
        """
        ...
