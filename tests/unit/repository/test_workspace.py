"""Unit tests for `src.repository.workspace`."""

from pathlib import Path
from uuid import uuid4

from src.repository.workspace import FilesystemWorkspaceManager


def test_constructor_creates_root_if_missing(tmp_path: Path) -> None:
    """The manager should create its root directory on construction if absent."""
    root = tmp_path / "workspaces"
    assert not root.exists()

    FilesystemWorkspaceManager(root)

    assert root.is_dir()


def test_constructor_is_fine_with_an_already_existing_root(tmp_path: Path) -> None:
    """Constructing against an already-existing root should not raise."""
    root = tmp_path / "workspaces"
    root.mkdir()

    FilesystemWorkspaceManager(root)  # should not raise

    assert root.is_dir()


def test_allocate_creates_a_new_directory(tmp_path: Path) -> None:
    """`allocate` should create and return a new workspace directory."""
    manager = FilesystemWorkspaceManager(tmp_path / "workspaces")
    repo_id = uuid4()

    path = manager.allocate(repo_id)

    assert path.is_dir()
    assert path.name == str(repo_id)


def test_allocate_is_idempotent(tmp_path: Path) -> None:
    """Calling `allocate` twice for the same id should return the same path without error."""
    manager = FilesystemWorkspaceManager(tmp_path / "workspaces")
    repo_id = uuid4()

    first = manager.allocate(repo_id)
    second = manager.allocate(repo_id)

    assert first == second
    assert first.is_dir()


def test_allocate_gives_different_repositories_different_paths(tmp_path: Path) -> None:
    """Two different repository ids should never collide on the same path."""
    manager = FilesystemWorkspaceManager(tmp_path / "workspaces")

    first = manager.allocate(uuid4())
    second = manager.allocate(uuid4())

    assert first != second


def test_resolve_returns_none_before_allocation(tmp_path: Path) -> None:
    """`resolve` should return None for a repository with no workspace yet."""
    manager = FilesystemWorkspaceManager(tmp_path / "workspaces")

    assert manager.resolve(uuid4()) is None


def test_resolve_returns_the_path_after_allocation(tmp_path: Path) -> None:
    """`resolve` should return the same path `allocate` created."""
    manager = FilesystemWorkspaceManager(tmp_path / "workspaces")
    repo_id = uuid4()

    allocated = manager.allocate(repo_id)

    assert manager.resolve(repo_id) == allocated


def test_exists_reflects_allocation_state(tmp_path: Path) -> None:
    """`exists` should be False before allocation and True after."""
    manager = FilesystemWorkspaceManager(tmp_path / "workspaces")
    repo_id = uuid4()

    assert manager.exists(repo_id) is False

    manager.allocate(repo_id)

    assert manager.exists(repo_id) is True


def test_remove_deletes_an_allocated_workspace(tmp_path: Path) -> None:
    """`remove` should delete a previously-allocated workspace directory."""
    manager = FilesystemWorkspaceManager(tmp_path / "workspaces")
    repo_id = uuid4()
    path = manager.allocate(repo_id)
    (path / "some_file.txt").write_text("data", encoding="utf-8")

    manager.remove(repo_id)

    assert not path.exists()
    assert manager.exists(repo_id) is False
    assert manager.resolve(repo_id) is None


def test_remove_on_a_never_allocated_repository_is_a_silent_no_op(tmp_path: Path) -> None:
    """`remove` should not raise when called for a repository with no workspace."""
    manager = FilesystemWorkspaceManager(tmp_path / "workspaces")

    manager.remove(uuid4())  # should not raise


def test_remove_does_not_affect_other_workspaces(tmp_path: Path) -> None:
    """Removing one repository's workspace should leave others intact."""
    manager = FilesystemWorkspaceManager(tmp_path / "workspaces")
    kept_id, removed_id = uuid4(), uuid4()
    kept_path = manager.allocate(kept_id)
    manager.allocate(removed_id)

    manager.remove(removed_id)

    assert kept_path.is_dir()
    assert manager.exists(kept_id) is True
