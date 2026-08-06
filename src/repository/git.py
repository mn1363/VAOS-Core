"""Concrete `RepositoryClient` implementation using the system `git` executable.

Shells out via `asyncio.create_subprocess_exec` rather than a third-party
git library, keeping this package's only runtime dependency the `git`
binary itself -- already assumed to be present in any environment capable
of running the rest of this platform.
"""

import asyncio
from pathlib import Path

from src.core.logging import get_logger
from src.domain.entities import SourceRepository

from .base import GitCommandError, RepositoryClient

_logger = get_logger("repository.git")

#: Default ceiling on how long a single git subprocess may run before it
#: is killed and reported as failed.
_DEFAULT_TIMEOUT_SECONDS = 300.0


class GitRepositoryClient(RepositoryClient):
    """A `RepositoryClient` that drives the system `git` executable."""

    def __init__(
        self,
        git_executable: str = "git",
        *,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        """Initialize the client.

        Args:
            git_executable: Name or path of the git executable to invoke.
                Defaults to `"git"`, resolved via the process `PATH`.
            timeout_seconds: Maximum time, in seconds, to wait for any
                single git command before killing it and raising
                `GitCommandError`.
        """
        self._git_executable = git_executable
        self._timeout_seconds = timeout_seconds

    async def clone(
        self, repository: SourceRepository, destination: Path, *, shallow: bool = True
    ) -> None:
        """Clone `repository` into `destination`.

        Args:
            repository: The repository to clone.
            destination: Local directory to clone into.
            shallow: If True, clone with `--depth 1`.

        Raises:
            GitCommandError: If the clone fails for any reason.
        """
        args = [
            "clone",
            "--branch",
            repository.default_branch,
        ]
        if shallow:
            args += ["--depth", "1"]
        args += [repository.source_uri, str(destination)]
        await self._run_git(args, cwd=None)

    async def fetch(self, workspace_path: Path) -> None:
        """Fetch the latest refs for the repository at `workspace_path`.

        Args:
            workspace_path: Local directory containing an existing clone.

        Raises:
            GitCommandError: If the fetch fails.
        """
        await self._run_git(["fetch", "--all", "--prune"], cwd=workspace_path)

    async def checkout(self, workspace_path: Path, ref: str) -> None:
        """Check out `ref` in the repository at `workspace_path`.

        Args:
            workspace_path: Local directory containing an existing clone.
            ref: Branch name, tag name, or commit SHA to check out.

        Raises:
            GitCommandError: If the checkout fails.
        """
        await self._run_git(["checkout", ref], cwd=workspace_path)

    async def current_commit(self, workspace_path: Path) -> str:
        """Return the full commit SHA currently checked out at `workspace_path`.

        Args:
            workspace_path: Local directory containing an existing clone.

        Returns:
            The 40-character commit SHA of `HEAD`.

        Raises:
            GitCommandError: If the SHA cannot be resolved.
        """
        stdout = await self._run_git(["rev-parse", "HEAD"], cwd=workspace_path)
        return stdout.strip()

    async def default_branch(self, workspace_path: Path) -> str:
        """Return the repository's default branch, per the `origin` remote's `HEAD`.

        Args:
            workspace_path: Local directory containing an existing clone.

        Returns:
            The default branch name, e.g. `"main"`.

        Raises:
            GitCommandError: If the default branch cannot be resolved.
        """
        stdout = await self._run_git(
            ["symbolic-ref", "refs/remotes/origin/HEAD"], cwd=workspace_path
        )
        # Output looks like "refs/remotes/origin/main"; the branch name is
        # everything after the final "/".
        return stdout.strip().rsplit("/", 1)[-1]

    async def _run_git(self, args: list[str], *, cwd: Path | None) -> str:
        """Run a git subcommand and return its captured stdout.

        Args:
            args: Arguments to pass to the git executable, e.g.
                `["clone", "--depth", "1", url, dest]`.
            cwd: Working directory to run the command in, or None to use
                the current process's working directory.

        Returns:
            The command's stdout, decoded as UTF-8.

        Raises:
            GitCommandError: If the executable cannot be started, the
                command times out, or it exits with a non-zero status.
        """
        command = [self._git_executable, *args]
        _logger.debug("Running git command: %s (cwd=%s)", " ".join(command), cwd)

        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                cwd=str(cwd) if cwd is not None else None,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as exc:
            raise GitCommandError(
                f"failed to start git command: {' '.join(command)}",
                details={"command": command, "reason": str(exc)},
            ) from exc

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(), timeout=self._timeout_seconds
            )
        except TimeoutError as exc:
            process.kill()
            await process.wait()
            raise GitCommandError(
                f"git command timed out after {self._timeout_seconds}s: {' '.join(command)}",
                details={"command": command, "timeout_seconds": self._timeout_seconds},
            ) from exc

        if process.returncode != 0:
            raise GitCommandError(
                f"git command failed with exit code {process.returncode}: {' '.join(command)}",
                details={
                    "command": command,
                    "exit_code": process.returncode,
                    "stderr": stderr_bytes.decode("utf-8", errors="replace").strip(),
                },
            )

        return stdout_bytes.decode("utf-8", errors="replace")
