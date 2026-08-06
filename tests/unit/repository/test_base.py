"""Unit tests for `src.repository.base`."""

import pytest
from src.core.exceptions import VAOSError
from src.repository.base import GitCommandError, RepositoryClient, WorkspaceManager


def test_repository_client_cannot_be_instantiated_directly() -> None:
    """The abstract `RepositoryClient` Port must not be instantiable."""
    with pytest.raises(TypeError):
        RepositoryClient()  # type: ignore[abstract]


def test_workspace_manager_cannot_be_instantiated_directly() -> None:
    """The abstract `WorkspaceManager` Port must not be instantiable."""
    with pytest.raises(TypeError):
        WorkspaceManager()  # type: ignore[abstract]


def test_git_command_error_is_a_vaos_error() -> None:
    """`GitCommandError` should be catchable as `VAOSError`, per the shared hierarchy."""
    error = GitCommandError("git failed", details={"command": ["git", "clone"]})

    assert isinstance(error, VAOSError)
    assert error.message == "git failed"
    assert error.details == {"command": ["git", "clone"]}
    assert str(error) == "git failed"
