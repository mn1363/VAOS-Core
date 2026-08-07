"""Unit tests for `src.collectors.local`."""

from pathlib import Path

import pytest
from src.collectors.local import LocalCollector
from src.core.exceptions import ValidationError
from src.domain.entities import RepositoryProvider


def test_provider_is_local() -> None:
    """`LocalCollector.provider` should report `RepositoryProvider.LOCAL`."""
    assert LocalCollector().provider is RepositoryProvider.LOCAL


@pytest.mark.asyncio
async def test_collect_finds_a_top_level_repository(tmp_path: Path) -> None:
    """A repository directly under the scan root should be discovered."""
    (tmp_path / "repo-a" / ".git").mkdir(parents=True)

    result = await LocalCollector().collect(str(tmp_path))

    assert result.succeeded is True
    assert [r.source_uri for r in result.repositories] == [str((tmp_path / "repo-a").resolve())]
    assert result.repositories[0].provider is RepositoryProvider.LOCAL


@pytest.mark.asyncio
async def test_collect_finds_repositories_at_different_nesting_levels(tmp_path: Path) -> None:
    """Repositories nested at different depths should both be discovered."""
    (tmp_path / "repo-a" / ".git").mkdir(parents=True)
    (tmp_path / "group" / "repo-b" / ".git").mkdir(parents=True)

    result = await LocalCollector().collect(str(tmp_path))

    found = [r.source_uri for r in result.repositories]
    assert str((tmp_path / "repo-a").resolve()) in found
    assert str((tmp_path / "group" / "repo-b").resolve()) in found
    assert len(found) == 2


@pytest.mark.asyncio
async def test_collect_does_not_descend_into_a_discovered_repository(tmp_path: Path) -> None:
    """A `.git` directory nested inside an already-discovered repository is not double-counted."""
    (tmp_path / "repo-a" / ".git").mkdir(parents=True)
    (tmp_path / "repo-a" / "vendor" / "nested" / ".git").mkdir(parents=True)

    result = await LocalCollector().collect(str(tmp_path))

    assert len(result.repositories) == 1
    assert result.repositories[0].source_uri == str((tmp_path / "repo-a").resolve())


@pytest.mark.asyncio
async def test_collect_skips_hidden_directories(tmp_path: Path) -> None:
    """A repository under a dot-prefixed directory should not be traversed into."""
    (tmp_path / ".hidden" / "repo-a" / ".git").mkdir(parents=True)
    (tmp_path / "visible" / ".git").mkdir(parents=True)

    result = await LocalCollector().collect(str(tmp_path))

    found = {r.source_uri for r in result.repositories}
    assert found == {str((tmp_path / "visible").resolve())}


@pytest.mark.asyncio
async def test_collect_respects_max_depth(tmp_path: Path) -> None:
    """A repository beyond `max_depth` levels below the root should not be found."""
    (tmp_path / "a" / "b" / "c" / "repo-deep" / ".git").mkdir(parents=True)

    shallow = await LocalCollector(max_depth=2).collect(str(tmp_path))
    deep_enough = await LocalCollector(max_depth=4).collect(str(tmp_path))

    assert shallow.repositories == ()
    assert len(deep_enough.repositories) == 1


@pytest.mark.asyncio
async def test_collect_finds_a_repository_sitting_exactly_at_max_depth(tmp_path: Path) -> None:
    """A repository exactly `max_depth` levels below the root is still within bounds."""
    (tmp_path / "a" / "repo-a" / ".git").mkdir(parents=True)

    result = await LocalCollector(max_depth=2).collect(str(tmp_path))

    assert len(result.repositories) == 1


@pytest.mark.asyncio
async def test_collect_succeeds_with_no_repositories_found(tmp_path: Path) -> None:
    """Scanning a tree with no git repositories should succeed with an empty result."""
    (tmp_path / "just-a-folder").mkdir()

    result = await LocalCollector().collect(str(tmp_path))

    assert result.succeeded is True
    assert result.repositories == ()


@pytest.mark.asyncio
async def test_collect_fails_for_a_missing_root(tmp_path: Path) -> None:
    """Scanning a root that does not exist should return a failed result."""
    missing = tmp_path / "does-not-exist"

    result = await LocalCollector().collect(str(missing))

    assert result.succeeded is False
    assert result.error_message is not None


@pytest.mark.asyncio
async def test_collect_raises_for_a_blank_source() -> None:
    """Scanning a blank source should raise `ValidationError`."""
    with pytest.raises(ValidationError):
        await LocalCollector().collect("")


@pytest.mark.asyncio
async def test_collect_results_are_sorted_by_source_uri(tmp_path: Path) -> None:
    """Discovered repositories should come back sorted by `source_uri`."""
    (tmp_path / "zeta" / ".git").mkdir(parents=True)
    (tmp_path / "alpha" / ".git").mkdir(parents=True)

    result = await LocalCollector().collect(str(tmp_path))

    uris = [r.source_uri for r in result.repositories]
    assert uris == sorted(uris)
