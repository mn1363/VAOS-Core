"""Unit tests for `src.collectors.filesystem`."""

from pathlib import Path

import pytest
from src.collectors.filesystem import FilesystemCollector
from src.core.exceptions import ValidationError
from src.domain.entities import RepositoryProvider


def test_provider_is_filesystem() -> None:
    """`FilesystemCollector.provider` should report `RepositoryProvider.FILESYSTEM`."""
    assert FilesystemCollector().provider is RepositoryProvider.FILESYSTEM


@pytest.mark.asyncio
async def test_collect_describes_an_existing_directory(tmp_path: Path) -> None:
    """Collecting an existing directory should return exactly one matching repository."""
    target = tmp_path / "my-project"
    target.mkdir()

    result = await FilesystemCollector().collect(str(target))

    assert result.succeeded is True
    assert len(result.repositories) == 1
    repository = result.repositories[0]
    assert repository.name == "my-project"
    assert repository.source_uri == str(target.resolve())
    assert repository.provider is RepositoryProvider.FILESYSTEM


@pytest.mark.asyncio
async def test_collect_works_without_a_git_directory(tmp_path: Path) -> None:
    """A directory with no `.git` entry should still be collected successfully."""
    target = tmp_path / "plain-folder"
    target.mkdir()

    result = await FilesystemCollector().collect(str(target))

    assert result.succeeded is True


@pytest.mark.asyncio
async def test_collect_fails_for_a_missing_path(tmp_path: Path) -> None:
    """Collecting a path that does not exist should return a failed result."""
    missing = tmp_path / "does-not-exist"

    result = await FilesystemCollector().collect(str(missing))

    assert result.succeeded is False
    assert result.repositories == ()
    assert result.error_message is not None
    assert "does-not-exist" in result.error_message


@pytest.mark.asyncio
async def test_collect_fails_when_source_is_a_file(tmp_path: Path) -> None:
    """Collecting a path that is a file, not a directory, should return a failed result."""
    file_path = tmp_path / "a_file.txt"
    file_path.write_text("data", encoding="utf-8")

    result = await FilesystemCollector().collect(str(file_path))

    assert result.succeeded is False


@pytest.mark.asyncio
async def test_collect_raises_for_a_blank_source() -> None:
    """Collecting a blank source should raise `ValidationError` rather than return a result."""
    with pytest.raises(ValidationError):
        await FilesystemCollector().collect("   ")
