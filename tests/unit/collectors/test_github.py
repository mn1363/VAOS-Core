"""Unit tests for `src.collectors.github`."""

import pytest
from src.collectors.github import GitHubCollector
from src.core.exceptions import ValidationError
from src.domain.entities import RepositoryProvider

_EXPECTED_URI = "https://github.com/octocat/Hello-World.git"


@pytest.mark.parametrize(
    "source",
    [
        "octocat/Hello-World",
        "https://github.com/octocat/Hello-World",
        "https://github.com/octocat/Hello-World/",
        "https://github.com/octocat/Hello-World.git",
        "git@github.com:octocat/Hello-World.git",
    ],
)
@pytest.mark.asyncio
async def test_collect_recognizes_every_accepted_form(source: str) -> None:
    """Every accepted reference form should normalize to the same canonical repository."""
    result = await GitHubCollector().collect(source)

    assert result.succeeded is True
    assert len(result.repositories) == 1
    repository = result.repositories[0]
    assert repository.source_uri == _EXPECTED_URI
    assert repository.name == "Hello-World"
    assert repository.provider is RepositoryProvider.GITHUB


@pytest.mark.parametrize(
    "source",
    [
        "not a url",
        "https://gitlab.com/octocat/Hello-World",
        "octocat",
        "octocat/",
        "/Hello-World",
        "https://github.com/octocat",
    ],
)
@pytest.mark.asyncio
async def test_collect_fails_for_unrecognized_references(source: str) -> None:
    """A string that is not a valid GitHub reference should return a failed result."""
    result = await GitHubCollector().collect(source)

    assert result.succeeded is False
    assert result.repositories == ()
    assert result.error_message is not None


@pytest.mark.asyncio
async def test_collect_raises_for_a_blank_source() -> None:
    """Collecting a blank source should raise `ValidationError`."""
    with pytest.raises(ValidationError):
        await GitHubCollector().collect("  ")


def test_provider_is_github() -> None:
    """`GitHubCollector.provider` should report `RepositoryProvider.GITHUB`."""
    assert GitHubCollector().provider is RepositoryProvider.GITHUB
