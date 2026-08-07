"""Unit tests for `src.collectors.gitlab`."""

import pytest
from src.collectors.gitlab import GitLabCollector
from src.core.exceptions import ValidationError
from src.domain.entities import RepositoryProvider


@pytest.mark.parametrize(
    ("source", "expected_uri", "expected_name"),
    [
        ("group/project", "https://gitlab.com/group/project.git", "project"),
        (
            "group/subgroup/project",
            "https://gitlab.com/group/subgroup/project.git",
            "project",
        ),
        (
            "https://gitlab.com/group/subgroup/project",
            "https://gitlab.com/group/subgroup/project.git",
            "project",
        ),
        (
            "https://gitlab.com/group/subgroup/project.git",
            "https://gitlab.com/group/subgroup/project.git",
            "project",
        ),
        (
            "git@gitlab.com:group/subgroup/project.git",
            "https://gitlab.com/group/subgroup/project.git",
            "project",
        ),
    ],
)
@pytest.mark.asyncio
async def test_collect_recognizes_every_accepted_form(
    source: str, expected_uri: str, expected_name: str
) -> None:
    """Every accepted reference form, including nested namespaces, should normalize correctly."""
    result = await GitLabCollector().collect(source)

    assert result.succeeded is True
    assert len(result.repositories) == 1
    repository = result.repositories[0]
    assert repository.source_uri == expected_uri
    assert repository.name == expected_name
    assert repository.provider is RepositoryProvider.GITLAB


@pytest.mark.parametrize(
    "source",
    [
        "not a url",
        "just-one-segment",
        "https://github.com/group/project",
    ],
)
@pytest.mark.asyncio
async def test_collect_fails_for_unrecognized_references(source: str) -> None:
    """A string that is not a valid GitLab reference should return a failed result."""
    result = await GitLabCollector().collect(source)

    assert result.succeeded is False
    assert result.repositories == ()
    assert result.error_message is not None


@pytest.mark.asyncio
async def test_collect_raises_for_a_blank_source() -> None:
    """Collecting a blank source should raise `ValidationError`."""
    with pytest.raises(ValidationError):
        await GitLabCollector().collect("")


def test_provider_is_gitlab() -> None:
    """`GitLabCollector.provider` should report `RepositoryProvider.GITLAB`."""
    assert GitLabCollector().provider is RepositoryProvider.GITLAB
