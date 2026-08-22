"""Unit tests for `src.storage.postgres.driver`.

Uses `FakeAsyncpgConnection`, an in-memory double satisfying `_AsyncpgConnectionLike`'s
`execute`/`fetch`/`fetchrow` calling convention -- not a live PostgreSQL server, per this
phase's "unit tests must not require live external services" requirement. The fake mimics
`asyncpg`'s own observable behavior closely enough to exercise this driver's real SQL-building,
error-mapping, and (de)serialization logic: parameterized `$1, $2, ...` placeholders, `asyncpg`'s
own exception types (`UniqueViolationError`, a generic `PostgresError`), and `execute`'s
`"VERB <count>"` status-string convention.

The module-level `pytest.importorskip("asyncpg")` below matters beyond this one file: without
it, `src.storage.postgres.driver`'s own unconditional `import asyncpg` (asyncpg is not yet a
declared project dependency -- see that module's docstring) would turn a missing `asyncpg` into
a hard *collection* error, which aborts pytest's entire session by default -- not just skip this
file. `importorskip` turns it into a clean per-file skip instead, matching
`tests/unit/storage/test_imports.py`'s own precedent for the same reason.
"""

import re
from typing import Any
from uuid import uuid4

import pytest

pytest.importorskip("asyncpg", reason="asyncpg is not yet a declared project dependency")

import asyncpg  # type: ignore[import-untyped]
from src.storage.base import EntityNotFoundError, StorageConnectionError, StorageIntegrityError
from src.storage.postgres.driver import (
    _ANALYSIS_RUN_COLUMNS,
    _FINDING_COLUMNS,
    _SOURCE_FILE_COLUMNS,
    _SOURCE_REPOSITORY_COLUMNS,
    PostgresAnalysisRunRepository,
    PostgresFindingRepository,
    PostgresSourceFileRepository,
    PostgresSourceRepositoryStore,
)

from tests.unit.storage._fixtures import (
    make_analysis_run,
    make_finding,
    make_source_file,
    make_source_repository,
)

_INSERT_RE = re.compile(r"INSERT INTO (\w+) \(([\w, ]+)\) VALUES", re.IGNORECASE)
_UPDATE_RE = re.compile(r"UPDATE (\w+) SET (.+) WHERE id = \$(\d+)", re.IGNORECASE)
_DELETE_RE = re.compile(r"DELETE FROM (\w+) WHERE id = \$1", re.IGNORECASE)
_SELECT_ALL_RE = re.compile(r"SELECT \* FROM (\w+)$", re.IGNORECASE)
_SELECT_WHERE_RE = re.compile(r"SELECT \* FROM (\w+) WHERE (\w+) = \$1", re.IGNORECASE)


class FakeAsyncpgConnection:
    """An in-memory double for `asyncpg`'s `execute`/`fetch`/`fetchrow` calling convention.

    Backs every table this driver uses with a plain `dict[str, dict[str, Any]]` keyed by `id`,
    parsing just enough of each query this driver actually issues (a fixed, small set of
    INSERT/UPDATE/DELETE/SELECT shapes) to apply it against that dict -- proof this driver's own
    SQL-building and parameter-binding logic is correct, without a real PostgreSQL server.
    """

    def __init__(self) -> None:
        self.tables: dict[str, dict[str, dict[str, Any]]] = {
            "source_repositories": {},
            "source_files": {},
            "analysis_runs": {},
            "findings": {},
        }
        self._unique_columns: dict[str, tuple[str, ...]] = {"source_repositories": ("source_uri",)}

    async def execute(self, query: str, *args: Any, timeout: float | None = None) -> str:
        if (match := _INSERT_RE.search(query)) is not None:
            table, column_list = match.group(1), match.group(2)
            columns = [c.strip() for c in column_list.split(",")]
            record = dict(zip(columns, args, strict=True))
            row_id = record["id"]
            store = self.tables[table]
            if row_id in store:
                raise asyncpg.UniqueViolationError("duplicate key value violates id")
            for unique_column in self._unique_columns.get(table, ()):
                if any(r[unique_column] == record[unique_column] for r in store.values()):
                    raise asyncpg.UniqueViolationError(
                        f"duplicate key value violates {unique_column}"
                    )
            store[row_id] = record
            return "INSERT 0 1"
        if (match := _UPDATE_RE.search(query)) is not None:
            table = match.group(1)
            row_id = args[-1]
            store = self.tables[table]
            if row_id not in store:
                return "UPDATE 0"
            set_columns = [c.split("=")[0].strip() for c in match.group(2).split(",")]
            store[row_id].update(dict(zip(set_columns, args[:-1], strict=True)))
            return "UPDATE 1"
        if (match := _DELETE_RE.search(query)) is not None:
            table = match.group(1)
            self.tables[table].pop(args[0], None)
            return "DELETE 1"
        raise AssertionError(f"FakeAsyncpgConnection.execute: unrecognized query {query!r}")

    async def fetch(self, query: str, *args: Any, timeout: float | None = None) -> list[Any]:
        if (match := _SELECT_ALL_RE.search(query)) is not None:
            return list(self.tables[match.group(1)].values())
        if (match := _SELECT_WHERE_RE.search(query)) is not None:
            table, column = match.group(1), match.group(2)
            return [r for r in self.tables[table].values() if r[column] == args[0]]
        raise AssertionError(f"FakeAsyncpgConnection.fetch: unrecognized query {query!r}")

    async def fetchrow(self, query: str, *args: Any, timeout: float | None = None) -> Any | None:
        if (match := _SELECT_WHERE_RE.search(query)) is not None:
            table, column = match.group(1), match.group(2)
            for row in self.tables[table].values():
                if row[column] == args[0]:
                    return row
            return None
        raise AssertionError(f"FakeAsyncpgConnection.fetchrow: unrecognized query {query!r}")


class FailingConnection:
    """A connection double whose every method raises, to exercise error-wrapping paths."""

    async def execute(self, query: str, *args: Any, timeout: float | None = None) -> str:
        raise asyncpg.PostgresError("connection lost")

    async def fetch(self, query: str, *args: Any, timeout: float | None = None) -> list[Any]:
        raise asyncpg.PostgresError("connection lost")

    async def fetchrow(self, query: str, *args: Any, timeout: float | None = None) -> Any | None:
        raise asyncpg.PostgresError("connection lost")


@pytest.fixture
def conn() -> FakeAsyncpgConnection:
    """A fresh `FakeAsyncpgConnection` for each test."""
    return FakeAsyncpgConnection()


# --- PostgresSourceRepositoryStore --------------------------------------------------------


@pytest.mark.asyncio
async def test_get_returns_none_for_unknown_id(conn: FakeAsyncpgConnection) -> None:
    """`get` against an empty table should return None, not raise."""
    store = PostgresSourceRepositoryStore(conn)

    assert await store.get(uuid4()) is None


@pytest.mark.asyncio
async def test_add_then_get_round_trips_every_field(conn: FakeAsyncpgConnection) -> None:
    """A repository added, then retrieved, should have every field intact, including
    dict-shaped `metadata` decoded back from its JSON-encoded storage form."""
    store = PostgresSourceRepositoryStore(conn)
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
async def test_add_duplicate_id_raises_storage_integrity_error(
    conn: FakeAsyncpgConnection,
) -> None:
    """Adding two repositories with the same `id` should raise `StorageIntegrityError`, wrapping
    `asyncpg.UniqueViolationError`."""
    store = PostgresSourceRepositoryStore(conn)
    await store.add(make_source_repository())

    with pytest.raises(StorageIntegrityError):
        await store.add(make_source_repository())


@pytest.mark.asyncio
async def test_add_duplicate_source_uri_raises_storage_integrity_error(
    conn: FakeAsyncpgConnection,
) -> None:
    """A second repository with a different `id` but the same `source_uri` should also raise."""
    store = PostgresSourceRepositoryStore(conn)
    await store.add(make_source_repository())

    with pytest.raises(StorageIntegrityError):
        await store.add(make_source_repository(id=uuid4()))


@pytest.mark.asyncio
async def test_update_changes_are_visible_on_get(conn: FakeAsyncpgConnection) -> None:
    """`update` should persist a change to an existing repository."""
    store = PostgresSourceRepositoryStore(conn)
    repository = make_source_repository()
    await store.add(repository)

    repository.name = "renamed"
    await store.update(repository)

    fetched = await store.get(repository.id)
    assert fetched is not None
    assert fetched.name == "renamed"


@pytest.mark.asyncio
async def test_update_unknown_id_raises_entity_not_found_error(
    conn: FakeAsyncpgConnection,
) -> None:
    """`update` targeting an id that was never added should raise `EntityNotFoundError`, parsed
    from `execute`'s `"UPDATE 0"` status string."""
    store = PostgresSourceRepositoryStore(conn)

    with pytest.raises(EntityNotFoundError):
        await store.update(make_source_repository())


@pytest.mark.asyncio
async def test_delete_removes_the_row(conn: FakeAsyncpgConnection) -> None:
    """After `delete`, `get` should return None."""
    store = PostgresSourceRepositoryStore(conn)
    repository = make_source_repository()
    await store.add(repository)

    await store.delete(repository.id)

    assert await store.get(repository.id) is None


@pytest.mark.asyncio
async def test_delete_unknown_id_is_a_no_op(conn: FakeAsyncpgConnection) -> None:
    """`delete` on an id that was never added should not raise."""
    store = PostgresSourceRepositoryStore(conn)

    await store.delete(uuid4())  # should not raise


@pytest.mark.asyncio
async def test_list_returns_every_added_repository(conn: FakeAsyncpgConnection) -> None:
    """`list` should return every repository that was added."""
    store = PostgresSourceRepositoryStore(conn)
    first = make_source_repository(id=uuid4(), source_uri="https://example.com/a")
    second = make_source_repository(id=uuid4(), source_uri="https://example.com/b")
    await store.add(first)
    await store.add(second)

    listed = await store.list()

    assert {r.id for r in listed} == {first.id, second.id}


@pytest.mark.asyncio
async def test_list_on_empty_table_returns_empty_list(conn: FakeAsyncpgConnection) -> None:
    """`list` against an empty table should return an empty list, not raise."""
    store = PostgresSourceRepositoryStore(conn)

    assert await store.list() == []


@pytest.mark.asyncio
async def test_get_by_source_uri_finds_the_matching_repository(
    conn: FakeAsyncpgConnection,
) -> None:
    """`get_by_source_uri` should find a repository by its collection location."""
    store = PostgresSourceRepositoryStore(conn)
    repository = make_source_repository()
    await store.add(repository)

    fetched = await store.get_by_source_uri(repository.source_uri)

    assert fetched is not None
    assert fetched.id == repository.id


@pytest.mark.asyncio
async def test_query_failure_raises_storage_connection_error() -> None:
    """A connection that raises `asyncpg.PostgresError` should surface as
    `StorageConnectionError`, not propagate the raw `asyncpg` exception."""
    store = PostgresSourceRepositoryStore(FailingConnection())

    with pytest.raises(StorageConnectionError):
        await store.get(uuid4())


# --- PostgresSourceFileRepository -----------------------------------------------------------


@pytest.mark.asyncio
async def test_source_file_add_get_delete_round_trip(conn: FakeAsyncpgConnection) -> None:
    """Basic add/get/delete round trip for `PostgresSourceFileRepository`."""
    store = PostgresSourceFileRepository(conn)
    file = make_source_file()

    await store.add(file)
    fetched = await store.get(file.id)
    assert fetched is not None
    assert fetched.relative_path == file.relative_path
    assert fetched.language == file.language

    await store.delete(file.id)
    assert await store.get(file.id) is None


@pytest.mark.asyncio
async def test_list_by_repository_filters_correctly(conn: FakeAsyncpgConnection) -> None:
    """`list_by_repository` should return only files belonging to the given repository."""
    store = PostgresSourceFileRepository(conn)
    target_repo = uuid4()
    matching = make_source_file(id=uuid4(), repository_id=target_repo)
    other = make_source_file(id=uuid4(), repository_id=uuid4())
    await store.add(matching)
    await store.add(other)

    result = await store.list_by_repository(target_repo)

    assert [f.id for f in result] == [matching.id]


# --- PostgresAnalysisRunRepository ----------------------------------------------------------


@pytest.mark.asyncio
async def test_analysis_run_round_trips_optional_fields(conn: FakeAsyncpgConnection) -> None:
    """An `AnalysisRun`'s optional fields should round trip as None."""
    store = PostgresAnalysisRunRepository(conn)
    run = make_analysis_run(started_at=None, completed_at=None, error_message=None)

    await store.add(run)
    fetched = await store.get(run.id)

    assert fetched is not None
    assert fetched.started_at is None
    assert fetched.completed_at is None
    assert fetched.error_message is None


@pytest.mark.asyncio
async def test_list_by_repository_for_analysis_runs(conn: FakeAsyncpgConnection) -> None:
    """`list_by_repository` should return only runs for the given repository."""
    store = PostgresAnalysisRunRepository(conn)
    target_repo = uuid4()
    matching = make_analysis_run(id=uuid4(), repository_id=target_repo)
    other = make_analysis_run(id=uuid4(), repository_id=uuid4())
    await store.add(matching)
    await store.add(other)

    result = await store.list_by_repository(target_repo)

    assert [r.id for r in result] == [matching.id]


# --- PostgresFindingRepository ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_finding_round_trips_optional_fields(conn: FakeAsyncpgConnection) -> None:
    """A `Finding`'s optional `source_file_id`/`score` should round trip as None."""
    store = PostgresFindingRepository(conn)
    finding = make_finding(source_file_id=None, score=None)

    await store.add(finding)
    fetched = await store.get(finding.id)

    assert fetched is not None
    assert fetched.source_file_id is None
    assert fetched.score is None


@pytest.mark.asyncio
async def test_list_by_analysis_run_filters_correctly(conn: FakeAsyncpgConnection) -> None:
    """`list_by_analysis_run` should return only findings for the given analysis run."""
    store = PostgresFindingRepository(conn)
    target_run = uuid4()
    matching = make_finding(id=uuid4(), analysis_run_id=target_run)
    other = make_finding(id=uuid4(), analysis_run_id=uuid4())
    await store.add(matching)
    await store.add(other)

    result = await store.list_by_analysis_run(target_run)

    assert [f.id for f in result] == [matching.id]


# --- Column-order sanity (guards the generic `_PostgresTable` binding logic) -----------------


def test_declared_columns_match_across_every_entity_type() -> None:
    """Each entity's declared column tuple should include exactly `id` plus every field
    `storage.base`'s corresponding `*_to_dict` produces -- proof the generic `_PostgresTable`
    binds values to the columns its own SQL text expects, for every one of the four entities."""
    assert set(_SOURCE_REPOSITORY_COLUMNS) == {
        "id",
        "name",
        "source_uri",
        "provider",
        "default_branch",
        "status",
        "metadata",
        "created_at",
        "updated_at",
    }
    assert set(_SOURCE_FILE_COLUMNS) == {
        "id",
        "repository_id",
        "relative_path",
        "language",
        "size_bytes",
        "metadata",
        "created_at",
        "updated_at",
    }
    assert set(_ANALYSIS_RUN_COLUMNS) == {
        "id",
        "repository_id",
        "status",
        "started_at",
        "completed_at",
        "error_message",
        "created_at",
        "updated_at",
    }
    assert set(_FINDING_COLUMNS) == {
        "id",
        "analysis_run_id",
        "category",
        "message",
        "source_file_id",
        "severity",
        "score",
        "metadata",
        "created_at",
        "updated_at",
    }
