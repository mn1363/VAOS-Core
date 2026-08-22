"""Unit tests for `src.storage.sqlite.driver`.

Uses a private, in-memory SQLite database (`:memory:`) via `open_connection` -- a real SQLite
engine, not a fake, since `sqlite3` is a standard-library dependency with no external service to
fake around.
"""

import asyncio
from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
import pytest_asyncio
from src.storage.base import (
    EntityNotFoundError,
    StorageConnectionError,
    StorageError,
    StorageIntegrityError,
)
from src.storage.sqlite.driver import (
    SqliteAnalysisRunRepository,
    SqliteConnection,
    SqliteFindingRepository,
    SqliteSourceFileRepository,
    SqliteSourceRepositoryStore,
    close_connection,
    initialize_schema,
    open_connection,
)

from tests.unit.storage._fixtures import (
    make_analysis_run,
    make_finding,
    make_source_file,
    make_source_repository,
)


@pytest_asyncio.fixture
async def conn() -> AsyncIterator[SqliteConnection]:
    """An initialized, in-memory `SqliteConnection`, closed after the test."""
    connection = open_connection(":memory:")
    await initialize_schema(connection)
    yield connection
    await close_connection(connection)


# --- open_connection / initialize_schema -------------------------------------------------------


def test_open_connection_returns_a_sqlite_connection_wrapper() -> None:
    """`open_connection` should return a `SqliteConnection`, not a bare `sqlite3.Connection`."""
    connection = open_connection(":memory:")

    assert isinstance(connection, SqliteConnection)
    connection.connection.close()


@pytest.mark.asyncio
async def test_initialize_schema_is_idempotent(conn: SqliteConnection) -> None:
    """Calling `initialize_schema` a second time against the same connection should not raise."""
    await initialize_schema(conn)  # already initialized once by the fixture; should not raise


@pytest.mark.asyncio
async def test_open_connection_rejects_an_invalid_path() -> None:
    """Opening a connection to an unwritable path should raise `StorageConnectionError`."""
    with pytest.raises(StorageConnectionError):
        open_connection("/nonexistent-directory-xyz/db.sqlite")


# --- SqliteSourceRepositoryStore -----------------------------------------------------------


@pytest.mark.asyncio
async def test_get_returns_none_for_unknown_id(conn: SqliteConnection) -> None:
    """`get` on an empty table should return None, not raise."""
    store = SqliteSourceRepositoryStore(conn)

    assert await store.get(uuid4()) is None


@pytest.mark.asyncio
async def test_add_then_get_round_trips_every_field(conn: SqliteConnection) -> None:
    """A repository added, then retrieved, should have every field intact."""
    store = SqliteSourceRepositoryStore(conn)
    repository = make_source_repository()

    await store.add(repository)
    fetched = await store.get(repository.id)

    assert fetched is not None
    assert fetched.name == repository.name
    assert fetched.source_uri == repository.source_uri
    assert fetched.provider == repository.provider
    assert fetched.status == repository.status
    assert fetched.metadata == repository.metadata
    assert fetched.created_at == repository.created_at
    assert fetched.updated_at == repository.updated_at


@pytest.mark.asyncio
async def test_add_duplicate_id_raises_storage_integrity_error(conn: SqliteConnection) -> None:
    """Adding two repositories with the same `id` should raise, not silently overwrite."""
    store = SqliteSourceRepositoryStore(conn)
    await store.add(make_source_repository())

    with pytest.raises(StorageIntegrityError):
        await store.add(make_source_repository())


@pytest.mark.asyncio
async def test_add_duplicate_source_uri_raises_storage_integrity_error(
    conn: SqliteConnection,
) -> None:
    """A second repository with a different `id` but the same `source_uri` should also raise,
    exercising the schema's own `UNIQUE(source_uri)` constraint."""
    store = SqliteSourceRepositoryStore(conn)
    await store.add(make_source_repository())

    with pytest.raises(StorageIntegrityError):
        await store.add(make_source_repository(id=uuid4()))


@pytest.mark.asyncio
async def test_update_changes_are_visible_on_get(conn: SqliteConnection) -> None:
    """`update` should persist a change to an existing repository."""
    store = SqliteSourceRepositoryStore(conn)
    repository = make_source_repository()
    await store.add(repository)

    repository.name = "renamed"
    await store.update(repository)

    fetched = await store.get(repository.id)
    assert fetched is not None
    assert fetched.name == "renamed"


@pytest.mark.asyncio
async def test_update_unknown_id_raises_entity_not_found_error(conn: SqliteConnection) -> None:
    """`update` targeting an id that was never added should raise `EntityNotFoundError`."""
    store = SqliteSourceRepositoryStore(conn)

    with pytest.raises(EntityNotFoundError):
        await store.update(make_source_repository())


@pytest.mark.asyncio
async def test_delete_removes_the_row(conn: SqliteConnection) -> None:
    """After `delete`, `get` should return None."""
    store = SqliteSourceRepositoryStore(conn)
    repository = make_source_repository()
    await store.add(repository)

    await store.delete(repository.id)

    assert await store.get(repository.id) is None


@pytest.mark.asyncio
async def test_delete_unknown_id_is_a_no_op(conn: SqliteConnection) -> None:
    """`delete` on an id that was never added should not raise."""
    store = SqliteSourceRepositoryStore(conn)

    await store.delete(uuid4())  # should not raise


@pytest.mark.asyncio
async def test_list_returns_every_added_repository(conn: SqliteConnection) -> None:
    """`list` should return every repository that was added."""
    store = SqliteSourceRepositoryStore(conn)
    first = make_source_repository(id=uuid4(), source_uri="https://example.com/a")
    second = make_source_repository(id=uuid4(), source_uri="https://example.com/b")
    await store.add(first)
    await store.add(second)

    listed = await store.list()

    assert {r.id for r in listed} == {first.id, second.id}


@pytest.mark.asyncio
async def test_get_by_source_uri_finds_the_matching_repository(conn: SqliteConnection) -> None:
    """`get_by_source_uri` should find a repository by its collection location."""
    store = SqliteSourceRepositoryStore(conn)
    repository = make_source_repository()
    await store.add(repository)

    fetched = await store.get_by_source_uri(repository.source_uri)

    assert fetched is not None
    assert fetched.id == repository.id


@pytest.mark.asyncio
async def test_get_by_source_uri_returns_none_when_no_match(conn: SqliteConnection) -> None:
    """`get_by_source_uri` for a URI that was never added should return None."""
    store = SqliteSourceRepositoryStore(conn)

    assert await store.get_by_source_uri("https://example.com/nope") is None


# --- SqliteSourceFileRepository ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_source_file_add_get_delete_round_trip(conn: SqliteConnection) -> None:
    """Basic add/get/delete round trip for `SqliteSourceFileRepository`."""
    store = SqliteSourceFileRepository(conn)
    file = make_source_file()

    await store.add(file)
    fetched = await store.get(file.id)
    assert fetched is not None
    assert fetched.relative_path == file.relative_path
    assert fetched.language == file.language
    assert fetched.size_bytes == file.size_bytes

    await store.delete(file.id)
    assert await store.get(file.id) is None


@pytest.mark.asyncio
async def test_list_by_repository_filters_correctly(conn: SqliteConnection) -> None:
    """`list_by_repository` should return only files belonging to the given repository."""
    store = SqliteSourceFileRepository(conn)
    target_repo = uuid4()
    matching = make_source_file(id=uuid4(), repository_id=target_repo)
    other = make_source_file(id=uuid4(), repository_id=uuid4())
    await store.add(matching)
    await store.add(other)

    result = await store.list_by_repository(target_repo)

    assert [f.id for f in result] == [matching.id]


# --- SqliteAnalysisRunRepository ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_analysis_run_round_trips_optional_fields(conn: SqliteConnection) -> None:
    """An `AnalysisRun`'s optional fields should round trip through SQLite's `NULL`."""
    store = SqliteAnalysisRunRepository(conn)
    run = make_analysis_run(started_at=None, completed_at=None, error_message=None)

    await store.add(run)
    fetched = await store.get(run.id)

    assert fetched is not None
    assert fetched.started_at is None
    assert fetched.completed_at is None
    assert fetched.error_message is None


@pytest.mark.asyncio
async def test_list_by_repository_for_analysis_runs(conn: SqliteConnection) -> None:
    """`list_by_repository` should return only runs for the given repository."""
    store = SqliteAnalysisRunRepository(conn)
    target_repo = uuid4()
    matching = make_analysis_run(id=uuid4(), repository_id=target_repo)
    other = make_analysis_run(id=uuid4(), repository_id=uuid4())
    await store.add(matching)
    await store.add(other)

    result = await store.list_by_repository(target_repo)

    assert [r.id for r in result] == [matching.id]


# --- SqliteFindingRepository ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_finding_round_trips_optional_fields(conn: SqliteConnection) -> None:
    """A `Finding`'s optional `source_file_id`/`score` should round trip through `NULL`."""
    store = SqliteFindingRepository(conn)
    finding = make_finding(source_file_id=None, score=None)

    await store.add(finding)
    fetched = await store.get(finding.id)

    assert fetched is not None
    assert fetched.source_file_id is None
    assert fetched.score is None


@pytest.mark.asyncio
async def test_list_by_analysis_run_filters_correctly(conn: SqliteConnection) -> None:
    """`list_by_analysis_run` should return only findings for the given analysis run."""
    store = SqliteFindingRepository(conn)
    target_run = uuid4()
    matching = make_finding(id=uuid4(), analysis_run_id=target_run)
    other = make_finding(id=uuid4(), analysis_run_id=uuid4())
    await store.add(matching)
    await store.add(other)

    result = await store.list_by_analysis_run(target_run)

    assert [f.id for f in result] == [matching.id]


# --- Cross-store, shared-connection behavior -----------------------------------------------


@pytest.mark.asyncio
async def test_multiple_stores_share_one_connection(conn: SqliteConnection) -> None:
    """Different store types built on the same `SqliteConnection` should see each other's
    writes -- proof they share one physical database, not isolated in-memory state."""
    repos = SqliteSourceRepositoryStore(conn)
    files = SqliteSourceFileRepository(conn)
    repository = make_source_repository()
    await repos.add(repository)

    file = make_source_file(repository_id=repository.id)
    await files.add(file)

    assert (await files.list_by_repository(repository.id))[0].id == file.id


@pytest.mark.asyncio
async def test_concurrent_operations_on_one_connection_do_not_raise(
    conn: SqliteConnection,
) -> None:
    """Many concurrently-awaited operations against the same `SqliteConnection` should not
    raise `sqlite3.ProgrammingError` -- proof the shared lock genuinely serializes access."""
    store = SqliteSourceRepositoryStore(conn)
    repository = make_source_repository()
    await store.add(repository)

    results = await asyncio.gather(*(store.get(repository.id) for _ in range(25)))

    assert all(r is not None and r.id == repository.id for r in results)


@pytest.mark.asyncio
async def test_query_against_a_closed_connection_raises_storage_error() -> None:
    """A query issued after `close_connection` should raise `StorageError`, not a raw
    `sqlite3.ProgrammingError`."""
    connection = open_connection(":memory:")
    await initialize_schema(connection)
    store = SqliteSourceRepositoryStore(connection)
    await close_connection(connection)

    with pytest.raises(StorageError):
        await store.get(uuid4())
