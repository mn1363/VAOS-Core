"""Unit tests for `src.repository.git`.

These tests exercise the real system `git` executable against a
throwaway, local git repository created in a pytest `tmp_path` fixture --
this proves `GitRepositoryClient` genuinely works end-to-end, not just
that it builds the right subprocess arguments, while remaining fully
offline and deterministic (git supports cloning from a local filesystem
path just as it would a remote URL).
"""

import asyncio
import subprocess
import sys
from pathlib import Path

import pytest
from src.domain.entities import RepositoryProvider, SourceRepository
from src.repository.base import GitCommandError
from src.repository.git import GitRepositoryClient


def _rev_list_count(cwd: Path) -> str:
    """Return the number of commits reachable from HEAD; test helper only."""
    result = subprocess.run(
        ["git", "rev-list", "--count", "HEAD"],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _run(*args: str, cwd: Path) -> None:
    """Run a git command synchronously, raising on failure; test setup helper only."""
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def local_origin(tmp_path: Path) -> Path:
    """Create a small, throwaway local git repository to act as a clone source."""
    origin = tmp_path / "origin"
    origin.mkdir()
    _run("init", "--initial-branch=main", cwd=origin)
    _run("config", "user.email", "test@example.com", cwd=origin)
    _run("config", "user.name", "Test", cwd=origin)
    (origin / "README.md").write_text("hello\n", encoding="utf-8")
    _run("add", "README.md", cwd=origin)
    _run("commit", "-m", "initial commit", cwd=origin)
    return origin


@pytest.fixture
def repository(local_origin: Path) -> SourceRepository:
    """A `SourceRepository` entity pointing at the local throwaway origin.

    Uses a `file://` URI rather than a bare filesystem path: a bare path
    makes git take a "local clone" shortcut that behaves differently from
    a real remote (notably, it restricts the fetch refspec regardless of
    flags), which would make these tests pass or fail for the wrong
    reasons. `file://` exercises the same code path a real HTTPS/SSH
    remote would.
    """
    return SourceRepository(
        name="test-repo",
        source_uri=f"file://{local_origin}",
        provider=RepositoryProvider.LOCAL,
        default_branch="main",
    )


@pytest.mark.asyncio
async def test_clone_creates_a_working_copy(repository: SourceRepository, tmp_path: Path) -> None:
    """`clone` should produce a working copy containing the origin's committed files."""
    client = GitRepositoryClient()
    destination = tmp_path / "clone"

    await client.clone(repository, destination)

    assert (destination / "README.md").is_file()
    assert (destination / ".git").is_dir()


@pytest.mark.asyncio
async def test_clone_is_shallow_by_default(repository: SourceRepository, tmp_path: Path) -> None:
    """A default (shallow) clone should record exactly one commit."""
    client = GitRepositoryClient()
    destination = tmp_path / "clone"

    await client.clone(repository, destination)

    commit_count = await asyncio.to_thread(_rev_list_count, destination)
    assert commit_count == "1"


@pytest.mark.asyncio
async def test_clone_full_history_when_not_shallow(
    local_origin: Path, repository: SourceRepository, tmp_path: Path
) -> None:
    """`shallow=False` should preserve the full commit history."""
    _run("commit", "--allow-empty", "-m", "second commit", cwd=local_origin)
    client = GitRepositoryClient()
    destination = tmp_path / "clone"

    await client.clone(repository, destination, shallow=False)

    commit_count = await asyncio.to_thread(_rev_list_count, destination)
    assert commit_count == "2"


@pytest.mark.asyncio
async def test_clone_invalid_source_raises_git_command_error(tmp_path: Path) -> None:
    """Cloning a nonexistent source should raise `GitCommandError`, not leak a raw error."""
    bad_repository = SourceRepository(
        name="nope",
        source_uri=str(tmp_path / "does-not-exist"),
        provider=RepositoryProvider.LOCAL,
    )
    client = GitRepositoryClient()

    with pytest.raises(GitCommandError) as exc_info:
        await client.clone(bad_repository, tmp_path / "clone")

    assert exc_info.value.details["exit_code"] != 0


@pytest.mark.asyncio
async def test_current_commit_returns_the_full_sha(
    repository: SourceRepository, tmp_path: Path
) -> None:
    """`current_commit` should return the 40-character SHA of HEAD."""
    client = GitRepositoryClient()
    destination = tmp_path / "clone"
    await client.clone(repository, destination)

    sha = await client.current_commit(destination)

    assert len(sha) == 40
    assert all(c in "0123456789abcdef" for c in sha)


@pytest.mark.asyncio
async def test_default_branch_matches_the_origin(
    repository: SourceRepository, tmp_path: Path
) -> None:
    """`default_branch` should report the branch the origin's HEAD points at."""
    client = GitRepositoryClient()
    destination = tmp_path / "clone"
    await client.clone(repository, destination)

    branch = await client.default_branch(destination)

    assert branch == "main"


@pytest.mark.asyncio
async def test_checkout_switches_to_a_fetched_branch(
    local_origin: Path, repository: SourceRepository, tmp_path: Path
) -> None:
    """`checkout` should switch the working copy to a different, existing ref."""
    _run("checkout", "-b", "feature", cwd=local_origin)
    (local_origin / "feature.txt").write_text("x\n", encoding="utf-8")
    _run("add", "feature.txt", cwd=local_origin)
    _run("commit", "-m", "feature commit", cwd=local_origin)
    _run("checkout", "main", cwd=local_origin)
    client = GitRepositoryClient()
    destination = tmp_path / "clone"
    await client.clone(repository, destination, shallow=False)
    await client.fetch(destination)

    await client.checkout(destination, "origin/feature")

    assert (destination / "feature.txt").is_file()


@pytest.mark.asyncio
async def test_checkout_unknown_ref_raises_git_command_error(
    repository: SourceRepository, tmp_path: Path
) -> None:
    """Checking out a ref that does not exist should raise `GitCommandError`."""
    client = GitRepositoryClient()
    destination = tmp_path / "clone"
    await client.clone(repository, destination)

    with pytest.raises(GitCommandError):
        await client.checkout(destination, "this-ref-does-not-exist")


@pytest.mark.asyncio
async def test_fetch_succeeds_against_an_existing_clone(
    repository: SourceRepository, tmp_path: Path
) -> None:
    """`fetch` should succeed against a valid, already-cloned workspace."""
    client = GitRepositoryClient()
    destination = tmp_path / "clone"
    await client.clone(repository, destination, shallow=False)

    await client.fetch(destination)  # should not raise


@pytest.mark.asyncio
async def test_fetch_on_a_non_git_directory_raises_git_command_error(tmp_path: Path) -> None:
    """`fetch` against a directory that is not a git repository should raise `GitCommandError`."""
    not_a_repo = tmp_path / "not-a-repo"
    not_a_repo.mkdir()
    client = GitRepositoryClient()

    with pytest.raises(GitCommandError):
        await client.fetch(not_a_repo)


@pytest.mark.asyncio
async def test_missing_executable_raises_git_command_error(tmp_path: Path) -> None:
    """An executable that cannot be started at all should raise `GitCommandError`."""
    client = GitRepositoryClient(git_executable="this-executable-does-not-exist-anywhere")

    with pytest.raises(GitCommandError):
        await client.fetch(tmp_path)


@pytest.mark.asyncio
async def test_timeout_kills_the_process_and_raises_git_command_error() -> None:
    """A command that runs past `timeout_seconds` should be killed and raise `GitCommandError`."""
    client = GitRepositoryClient(git_executable=sys.executable, timeout_seconds=0.05)

    with pytest.raises(GitCommandError) as exc_info:
        await client._run_git(["-c", "import time; time.sleep(5)"], cwd=None)

    assert "timed out" in exc_info.value.message
