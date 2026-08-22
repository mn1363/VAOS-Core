"""Unit tests for `src.storage.filesystem.driver`.

Uses a real filesystem via pytest's `tmp_path` fixture -- no mocking needed, since this backend
has no external service to fake.
"""

import json
from pathlib import Path
from uuid import uuid4

import pytest
from src.storage.base import EntityNotFoundError, StorageError, StorageIntegrityError
from src.storage.filesystem.driver import (
    FilesystemAnalysisRunRepository,
    FilesystemFindingRepository,
    FilesystemSourceFileRepository,
    FilesystemSourceRepositoryStore,
)

from tests.unit.storage._fixtures import (
    make_analysis_run,
    make_finding,
    make_source_file,
    make_source_repository,
)

# --- FilesystemSourceRepositoryStore ----------------------------------------------------------


@pytest.mark.asyncio
async def test_get_returns_none_for_unknown_id(tmp_path: Path) -> None:
    """`get` on an empty store should return None, not raise."""
    store = FilesystemSourceRepositoryStore(tmp_path)

    assert await store.get(uuid4()) is None


@pytest.mark.asyncio
async def test_add_then_get_round_trips_every_field(tmp_path: Path) -> None:
    """A repository added, then retrieved, should have every field intact."""
    store = FilesystemSourceRepositoryStore(tmp_path)
    repository = make_source_repository()

    await store.add(repository)
    fetched = await store.get(repository.id)

    assert fetched is not None
    assert fetched.name == repository.name
    assert fetched.source_uri == repository.source_uri
    assert fetched.provider == repository.provider
    assert fetched.status == repository.status
    assert fetched.metadata == repository.metadata


@pytest.mark.asyncio
async def test_add_persists_across_new_store_instances(tmp_path: Path) -> None:
    """Data should survive re-opening a fresh store instance against the same root -- proof
    this is a real filesystem backend, not in-memory state on the store object."""
    await FilesystemSourceRepositoryStore(tmp_path).add(make_source_repository())

    reopened = FilesystemSourceRepositoryStore(tmp_path)
    fetched = await reopened.get(make_source_repository().id)

    assert fetched is not None
    assert fetched.name == make_source_repository().name


@pytest.mark.asyncio
async def test_add_duplicate_id_raises_storage_integrity_error(tmp_path: Path) -> None:
    """Adding two repositories with the same `id` should raise, not silently overwrite."""
    store = FilesystemSourceRepositoryStore(tmp_path)
    await store.add(make_source_repository())

    with pytest.raises(StorageIntegrityError):
        await store.add(make_source_repository())


@pytest.mark.asyncio
async def test_update_changes_are_visible_on_get(tmp_path: Path) -> None:
    """`update` should persist a change to an existing repository."""
    store = FilesystemSourceRepositoryStore(tmp_path)
    repository = make_source_repository()
    await store.add(repository)

    repository.name = "renamed"
    await store.update(repository)

    fetched = await store.get(repository.id)
    assert fetched is not None
    assert fetched.name == "renamed"


@pytest.mark.asyncio
async def test_update_unknown_id_raises_entity_not_found_error(tmp_path: Path) -> None:
    """`update` targeting an id that was never added should raise `EntityNotFoundError`."""
    store = FilesystemSourceRepositoryStore(tmp_path)

    with pytest.raises(EntityNotFoundError):
        await store.update(make_source_repository())


@pytest.mark.asyncio
async def test_delete_removes_the_entry(tmp_path: Path) -> None:
    """After `delete`, `get` should return None."""
    store = FilesystemSourceRepositoryStore(tmp_path)
    repository = make_source_repository()
    await store.add(repository)

    await store.delete(repository.id)

    assert await store.get(repository.id) is None


@pytest.mark.asyncio
async def test_delete_unknown_id_is_a_no_op(tmp_path: Path) -> None:
    """`delete` on an id that was never added should not raise."""
    store = FilesystemSourceRepositoryStore(tmp_path)

    await store.delete(uuid4())  # should not raise


@pytest.mark.asyncio
async def test_list_returns_every_added_repository(tmp_path: Path) -> None:
    """`list` should return every repository that was added."""
    store = FilesystemSourceRepositoryStore(tmp_path)
    first = make_source_repository(id=uuid4(), source_uri="https://example.com/a")
    second = make_source_repository(id=uuid4(), source_uri="https://example.com/b")
    await store.add(first)
    await store.add(second)

    listed = await store.list()

    assert {r.id for r in listed} == {first.id, second.id}


@pytest.mark.asyncio
async def test_list_on_empty_store_returns_empty_list(tmp_path: Path) -> None:
    """`list` on a store with nothing added should return an empty list, not raise."""
    store = FilesystemSourceRepositoryStore(tmp_path)

    assert await store.list() == []


@pytest.mark.asyncio
async def test_get_by_source_uri_finds_the_matching_repository(tmp_path: Path) -> None:
    """`get_by_source_uri` should find a repository by its collection location."""
    store = FilesystemSourceRepositoryStore(tmp_path)
    repository = make_source_repository()
    await store.add(repository)

    fetched = await store.get_by_source_uri(repository.source_uri)

    assert fetched is not None
    assert fetched.id == repository.id


@pytest.mark.asyncio
async def test_get_by_source_uri_returns_none_when_no_match(tmp_path: Path) -> None:
    """`get_by_source_uri` for a URI that was never added should return None."""
    store = FilesystemSourceRepositoryStore(tmp_path)

    assert await store.get_by_source_uri("https://example.com/nope") is None


@pytest.mark.asyncio
async def test_corrupted_json_file_raises_storage_error(tmp_path: Path) -> None:
    """A backing file that is not valid JSON should raise `StorageError`, not a raw
    `json.JSONDecodeError` or crash silently."""
    (tmp_path / "source_repositories.json").write_text("not valid json{{{", encoding="utf-8")
    store = FilesystemSourceRepositoryStore(tmp_path)

    with pytest.raises(StorageError):
        await store.list()


@pytest.mark.asyncio
async def test_backing_file_is_valid_json_after_add(tmp_path: Path) -> None:
    """The backing file should be genuinely readable, well-formed JSON after a write --
    verifies the atomic-write path actually completes and leaves no partial/temp file behind."""
    store = FilesystemSourceRepositoryStore(tmp_path)
    await store.add(make_source_repository())

    backing_file = tmp_path / "source_repositories.json"
    data = json.loads(backing_file.read_text(encoding="utf-8"))
    assert str(make_source_repository().id) in data
    leftover_temp_files = list(tmp_path.glob(".*.tmp"))
    assert leftover_temp_files == []


# --- FilesystemSourceFileRepository -----------------------------------------------------------


@pytest.mark.asyncio
async def test_source_file_add_get_delete_round_trip(tmp_path: Path) -> None:
    """Basic add/get/delete round trip for `FilesystemSourceFileRepository`."""
    store = FilesystemSourceFileRepository(tmp_path)
    file = make_source_file()

    await store.add(file)
    fetched = await store.get(file.id)
    assert fetched is not None
    assert fetched.relative_path == file.relative_path
    assert fetched.language == file.language

    await store.delete(file.id)
    assert await store.get(file.id) is None


@pytest.mark.asyncio
async def test_list_by_repository_filters_correctly(tmp_path: Path) -> None:
    """`list_by_repository` should return only files belonging to the given repository."""
    store = FilesystemSourceFileRepository(tmp_path)
    target_repo = uuid4()
    other_repo = uuid4()
    matching = make_source_file(id=uuid4(), repository_id=target_repo)
    other = make_source_file(id=uuid4(), repository_id=other_repo)
    await store.add(matching)
    await store.add(other)

    result = await store.list_by_repository(target_repo)

    assert [f.id for f in result] == [matching.id]


@pytest.mark.asyncio
async def test_list_by_repository_with_no_matches_returns_empty_list(tmp_path: Path) -> None:
    """`list_by_repository` for a repository with no files should return an empty list."""
    store = FilesystemSourceFileRepository(tmp_path)

    assert await store.list_by_repository(uuid4()) == []


# --- FilesystemAnalysisRunRepository ----------------------------------------------------------


@pytest.mark.asyncio
async def test_analysis_run_round_trips_optional_fields(tmp_path: Path) -> None:
    """An `AnalysisRun`'s optional `started_at`/`completed_at`/`error_message` should survive a
    filesystem round trip."""
    store = FilesystemAnalysisRunRepository(tmp_path)
    run = make_analysis_run(started_at=None, completed_at=None, error_message=None)

    await store.add(run)
    fetched = await store.get(run.id)

    assert fetched is not None
    assert fetched.started_at is None
    assert fetched.completed_at is None
    assert fetched.error_message is None


@pytest.mark.asyncio
async def test_list_by_repository_for_analysis_runs(tmp_path: Path) -> None:
    """`list_by_repository` should return only runs for the given repository."""
    store = FilesystemAnalysisRunRepository(tmp_path)
    target_repo = uuid4()
    matching = make_analysis_run(id=uuid4(), repository_id=target_repo)
    other = make_analysis_run(id=uuid4(), repository_id=uuid4())
    await store.add(matching)
    await store.add(other)

    result = await store.list_by_repository(target_repo)

    assert [r.id for r in result] == [matching.id]


# --- FilesystemFindingRepository --------------------------------------------------------------


@pytest.mark.asyncio
async def test_finding_round_trips_optional_fields(tmp_path: Path) -> None:
    """A `Finding`'s optional `source_file_id`/`score` should survive a filesystem round trip
    when None."""
    store = FilesystemFindingRepository(tmp_path)
    finding = make_finding(source_file_id=None, score=None)

    await store.add(finding)
    fetched = await store.get(finding.id)

    assert fetched is not None
    assert fetched.source_file_id is None
    assert fetched.score is None


@pytest.mark.asyncio
async def test_list_by_analysis_run_filters_correctly(tmp_path: Path) -> None:
    """`list_by_analysis_run` should return only findings for the given analysis run."""
    store = FilesystemFindingRepository(tmp_path)
    target_run = uuid4()
    matching = make_finding(id=uuid4(), analysis_run_id=target_run)
    other = make_finding(id=uuid4(), analysis_run_id=uuid4())
    await store.add(matching)
    await store.add(other)

    result = await store.list_by_analysis_run(target_run)

    assert [f.id for f in result] == [matching.id]
