"""Concrete SQLite-backed implementations of every `domain.interfaces` persistence Port.

Uses the standard library's `sqlite3` module -- no additional runtime dependency -- with every
blocking call offloaded via `asyncio.to_thread`, matching `storage.filesystem`'s own precedent
for keeping the event loop unblocked. A connection is always supplied by the caller, opened via
the module-level `open_connection` factory kept deliberately separate from every store's own
`__init__`; schema creation is likewise an explicit, separate `initialize_schema` step, never a
hidden side effect of construction -- matching this phase's "no hidden ... calls during object
construction unless the existing contract explicitly requires them" requirement, generalized
from Qdrant to every backend.

`open_connection` returns a `SqliteConnection`, not a bare `sqlite3.Connection`: a `sqlite3`
connection, even opened with `check_same_thread=False` (required here since every operation runs
in a worker thread via `asyncio.to_thread`, which is not guaranteed to be the thread that opened
it), is still not safe for *concurrent* use from more than one thread at once. `SqliteConnection`
pairs the connection with the single `asyncio.Lock` every operation -- from every one of the four
stores built on it -- acquires before touching it, so at most one thread ever uses the
connection at a time regardless of how many coroutines are concurrently awaited against it.

All four stores accept the *same* `SqliteConnection`, sharing one physical SQLite database -- so
no individual store owns its lifecycle; closing it is the caller's own responsibility via
`close_connection`, called once after every store built on it is done.

`add` raises `StorageIntegrityError` on a duplicate id (or `SourceRepository.source_uri`'s own
`UNIQUE` constraint), `update` raises `EntityNotFoundError` on a missing id, and `delete` is a
no-op on a missing id -- the same semantics `storage.filesystem` establishes, kept identical
across every entity-persisting backend so a caller can swap backends without observing a
behavior change.
"""

import asyncio
import json
import sqlite3
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from src.core.logging import get_logger
from src.domain.entities import AnalysisRun, Finding, SourceFile, SourceRepository
from src.domain.interfaces import (
    AnalysisRunRepository,
    FindingRepository,
    SourceFileRepository,
    SourceRepositoryStore,
)

from ..base import (
    EntityNotFoundError,
    StorageConnectionError,
    StorageIntegrityError,
    analysis_run_from_dict,
    analysis_run_to_dict,
    finding_from_dict,
    finding_to_dict,
    source_file_from_dict,
    source_file_to_dict,
    source_repository_from_dict,
    source_repository_to_dict,
)

_logger = get_logger("storage.sqlite")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS source_repositories (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    source_uri TEXT NOT NULL UNIQUE,
    provider TEXT NOT NULL,
    default_branch TEXT NOT NULL,
    status TEXT NOT NULL,
    metadata TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS source_files (
    id TEXT PRIMARY KEY,
    repository_id TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    language TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    metadata TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_source_files_repository_id ON source_files (repository_id);

CREATE TABLE IF NOT EXISTS analysis_runs (
    id TEXT PRIMARY KEY,
    repository_id TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_analysis_runs_repository_id ON analysis_runs (repository_id);

CREATE TABLE IF NOT EXISTS findings (
    id TEXT PRIMARY KEY,
    analysis_run_id TEXT NOT NULL,
    category TEXT NOT NULL,
    message TEXT NOT NULL,
    source_file_id TEXT,
    severity TEXT NOT NULL,
    score REAL,
    metadata TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_findings_analysis_run_id ON findings (analysis_run_id);
"""

_SOURCE_REPOSITORY_COLUMNS = (
    "id",
    "name",
    "source_uri",
    "provider",
    "default_branch",
    "status",
    "metadata",
    "created_at",
    "updated_at",
)
_SOURCE_FILE_COLUMNS = (
    "id",
    "repository_id",
    "relative_path",
    "language",
    "size_bytes",
    "metadata",
    "created_at",
    "updated_at",
)
_ANALYSIS_RUN_COLUMNS = (
    "id",
    "repository_id",
    "status",
    "started_at",
    "completed_at",
    "error_message",
    "created_at",
    "updated_at",
)
_FINDING_COLUMNS = (
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
)


@dataclass(slots=True)
class SqliteConnection:
    """A SQLite connection paired with the lock every operation against it must hold.

    `sqlite3.Connection` is not safe for concurrent use from more than one thread at once, even
    opened with `check_same_thread=False` -- so every store built on the same connection shares
    this one lock (see module docstring for the full rationale).

    Attributes:
        connection: The underlying, already-open connection.
        lock: Serializes every operation against `connection`, shared by every store built on
            it.
    """

    connection: sqlite3.Connection
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


def open_connection(path: str) -> SqliteConnection:
    """Open a new SQLite connection to `path`, configured for this package's own use.

    A convenience factory kept separate from every store's `__init__` -- a store's own
    constructor never opens a connection itself; the connection is always supplied by the
    caller, matching this phase's "no global client" and "explicit client/configuration
    injection" requirements.

    Args:
        path: Filesystem path of the SQLite database file, or `":memory:"` for a private,
            in-memory database (used by this package's own tests).

    Returns:
        A `SqliteConnection` wrapping an open connection (`row_factory` set to `sqlite3.Row` so
        query results are column-addressable by name; `check_same_thread=False` since every
        operation runs via `asyncio.to_thread`) and a fresh lock for it.

    Raises:
        StorageConnectionError: If the connection cannot be opened.
    """
    try:
        connection = sqlite3.connect(path, check_same_thread=False)
    except sqlite3.Error as exc:
        raise StorageConnectionError(
            f"could not open SQLite database at '{path}': {exc}", details={"path": path}
        ) from exc
    connection.row_factory = sqlite3.Row
    return SqliteConnection(connection=connection)


async def close_connection(conn: SqliteConnection) -> None:
    """Close a connection opened by `open_connection`.

    The caller's own responsibility, once every store built on `conn` is done with it -- no
    individual store closes the shared connection itself (see module docstring).

    Args:
        conn: The connection wrapper to close.
    """
    async with conn.lock:
        await asyncio.to_thread(conn.connection.close)


async def initialize_schema(conn: SqliteConnection) -> None:
    """Create every table and index this package's stores need, if not already present.

    Idempotent: safe to call against a database that already has this schema.

    Args:
        conn: A `SqliteConnection`, as returned by `open_connection`.

    Raises:
        StorageConnectionError: If schema creation fails.
    """

    def _run() -> None:
        try:
            conn.connection.executescript(_SCHEMA)
            conn.connection.commit()
        except sqlite3.Error as exc:
            conn.connection.rollback()
            raise StorageConnectionError(f"could not initialize SQLite schema: {exc}") from exc

    async with conn.lock:
        await asyncio.to_thread(_run)


def _encode_metadata(record: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of `record` with its `metadata` dict JSON-encoded for SQL storage.

    Args:
        record: A dict produced by one of `storage.base`'s `*_to_dict` functions, with
            `metadata` still a plain dict.

    Returns:
        A copy of `record` with `metadata` replaced by its JSON-encoded string form.
    """
    return {**record, "metadata": json.dumps(record["metadata"])}


def _decode_metadata(row: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of `row` with its `metadata` column JSON-decoded back into a dict.

    Args:
        row: A raw row dict read from a table with a `metadata` TEXT column.

    Returns:
        A copy of `row` with `metadata` replaced by the parsed dict, ready for one of
        `storage.base`'s `*_from_dict` functions.
    """
    return {**row, "metadata": json.loads(row["metadata"])}


class _SqliteTable:
    """Generic, thread-offloaded CRUD helper for one SQLite table keyed by a TEXT `id` column.

    Centralizes the add/update/delete semantics every concrete `Sqlite...` class below shares --
    the same semantics `storage.filesystem._JsonCollectionStore` establishes: `add` raises
    `StorageIntegrityError` on a duplicate id or other constraint violation, `update` raises
    `EntityNotFoundError` on a missing id, `delete` is a no-op on a missing id. `table` is always
    an internal constant fixed at construction, never derived from external input, so building
    SQL with an f-string here carries no injection risk despite the surface resemblance to one.
    """

    def __init__(
        self, conn: SqliteConnection, *, table: str, columns: tuple[str, ...], kind: str
    ) -> None:
        """Initialize the helper.

        Args:
            conn: A `SqliteConnection`; its schema must already exist (see
                `initialize_schema`).
            table: Name of the backing table.
            columns: Every column name, in the exact order records use -- must match the
                corresponding `storage.base.*_to_dict` function's keys, with `metadata` (if
                present) already JSON-encoded by the caller via `_encode_metadata`.
            kind: Human-readable entity type name, used only to compose error messages.
        """
        self._conn = conn
        self._table = table
        self._columns = columns
        self._kind = kind

    async def get(self, entity_id: str) -> dict[str, Any] | None:
        """Retrieve one row by its `id` column.

        Args:
            entity_id: String id to look up.

        Returns:
            The row as a plain dict, or None if no row has that id.
        """
        return await self.get_where("id", entity_id)

    async def get_where(self, column: str, value: str) -> dict[str, Any] | None:
        """Retrieve the first row where `column` equals `value`.

        Args:
            column: Name of the column to filter on; always an internal constant.
            value: Value to match.

        Returns:
            The matching row as a plain dict, or None if no row matches.

        Raises:
            StorageConnectionError: If the query fails.
        """

        def _query() -> sqlite3.Row | None:
            try:
                cursor = self._conn.connection.execute(
                    f"SELECT * FROM {self._table} WHERE {column} = ?", (value,)
                )
                row: sqlite3.Row | None = cursor.fetchone()
                return row
            except sqlite3.Error as exc:
                raise StorageConnectionError(
                    f"could not query '{self._table}': {exc}", details={"table": self._table}
                ) from exc

        async with self._conn.lock:
            row = await asyncio.to_thread(_query)
        return dict(row) if row is not None else None

    async def list_all(self) -> list[dict[str, Any]]:
        """Retrieve every row in the table.

        Returns:
            Every row as a plain dict, in the database's own storage order.
        """
        return await self.list_where(None, None)

    async def list_where(self, column: str | None, value: str | None) -> list[dict[str, Any]]:
        """Retrieve every row where `column` equals `value`, or every row if `column` is None.

        Args:
            column: Name of the column to filter on, or None to list every row.
            value: Value to match; ignored if `column` is None.

        Returns:
            Every matching row as a plain dict.

        Raises:
            StorageConnectionError: If the query fails.
        """

        def _query() -> list[sqlite3.Row]:
            try:
                if column is None:
                    cursor = self._conn.connection.execute(f"SELECT * FROM {self._table}")
                else:
                    cursor = self._conn.connection.execute(
                        f"SELECT * FROM {self._table} WHERE {column} = ?", (value,)
                    )
                return cursor.fetchall()
            except sqlite3.Error as exc:
                raise StorageConnectionError(
                    f"could not query '{self._table}': {exc}", details={"table": self._table}
                ) from exc

        async with self._conn.lock:
            rows = await asyncio.to_thread(_query)
        return [dict(r) for r in rows]

    async def add(self, entity_id: str, record: dict[str, Any]) -> None:
        """Insert a new row, or raise if `entity_id` (or another constraint) already conflicts.

        Args:
            entity_id: String id of the row to insert.
            record: Column values to insert, keyed by every name in `self._columns`.

        Raises:
            StorageIntegrityError: If a row with `entity_id`, or another `UNIQUE`-constrained
                value, already exists.
            StorageConnectionError: If the insert fails for any other reason.
        """
        column_list = ", ".join(self._columns)
        placeholders = ", ".join("?" for _ in self._columns)
        values = tuple(record[c] for c in self._columns)

        def _insert() -> None:
            try:
                self._conn.connection.execute(
                    f"INSERT INTO {self._table} ({column_list}) VALUES ({placeholders})", values
                )
                self._conn.connection.commit()
            except sqlite3.IntegrityError as exc:
                self._conn.connection.rollback()
                raise StorageIntegrityError(
                    f"{self._kind} with id '{entity_id}' violates a uniqueness constraint: {exc}",
                    details={"id": entity_id, "table": self._table},
                ) from exc
            except sqlite3.Error as exc:
                self._conn.connection.rollback()
                raise StorageConnectionError(
                    f"could not insert into '{self._table}': {exc}",
                    details={"table": self._table},
                ) from exc

        async with self._conn.lock:
            await asyncio.to_thread(_insert)

    async def update(self, entity_id: str, record: dict[str, Any]) -> None:
        """Overwrite an existing row, or raise if `entity_id` does not exist.

        Args:
            entity_id: String id of the row to overwrite.
            record: Column values to write, keyed by every name in `self._columns`.

        Raises:
            EntityNotFoundError: If no row with `entity_id` currently exists.
            StorageIntegrityError: If the update violates a constraint (e.g. a duplicate
                `source_uri`).
            StorageConnectionError: If the update fails for any other reason.
        """
        set_columns = [c for c in self._columns if c != "id"]
        assignments = ", ".join(f"{c} = ?" for c in set_columns)
        values = tuple(record[c] for c in set_columns) + (entity_id,)

        def _update() -> None:
            try:
                cursor = self._conn.connection.execute(
                    f"UPDATE {self._table} SET {assignments} WHERE id = ?", values
                )
                if cursor.rowcount == 0:
                    self._conn.connection.rollback()
                    raise EntityNotFoundError(
                        f"{self._kind} with id '{entity_id}' does not exist",
                        details={"id": entity_id, "table": self._table},
                    )
                self._conn.connection.commit()
            except sqlite3.IntegrityError as exc:
                self._conn.connection.rollback()
                raise StorageIntegrityError(
                    f"{self._kind} with id '{entity_id}' violates a uniqueness constraint: {exc}",
                    details={"id": entity_id, "table": self._table},
                ) from exc
            except sqlite3.Error as exc:
                self._conn.connection.rollback()
                raise StorageConnectionError(
                    f"could not update '{self._table}': {exc}", details={"table": self._table}
                ) from exc

        async with self._conn.lock:
            await asyncio.to_thread(_update)

    async def delete(self, entity_id: str) -> None:
        """Remove a row by `id`; a no-op if it does not exist.

        Args:
            entity_id: String id of the row to remove.

        Raises:
            StorageConnectionError: If the delete fails.
        """

        def _delete() -> None:
            try:
                self._conn.connection.execute(
                    f"DELETE FROM {self._table} WHERE id = ?", (entity_id,)
                )
                self._conn.connection.commit()
            except sqlite3.Error as exc:
                self._conn.connection.rollback()
                raise StorageConnectionError(
                    f"could not delete from '{self._table}': {exc}",
                    details={"table": self._table},
                ) from exc

        async with self._conn.lock:
            await asyncio.to_thread(_delete)


class SqliteSourceRepositoryStore(SourceRepositoryStore):
    """A `SourceRepositoryStore` backed by an injected SQLite connection."""

    def __init__(self, conn: SqliteConnection) -> None:
        """Initialize the store.

        Args:
            conn: A `SqliteConnection`, as returned by `open_connection`. The schema must
                already exist -- call `initialize_schema` once before using any store built on
                it.
        """
        self._table = _SqliteTable(
            conn,
            table="source_repositories",
            columns=_SOURCE_REPOSITORY_COLUMNS,
            kind="SourceRepository",
        )

    async def get(self, entity_id: UUID) -> SourceRepository | None:
        """Retrieve a repository by id."""
        row = await self._table.get(str(entity_id))
        return source_repository_from_dict(_decode_metadata(row)) if row is not None else None

    async def add(self, entity: SourceRepository) -> None:
        """Persist a new repository.

        Raises:
            StorageIntegrityError: If a repository with the same `id` or `source_uri` already
                exists.
        """
        await self._table.add(
            str(entity.id), _encode_metadata(source_repository_to_dict(entity))
        )

    async def update(self, entity: SourceRepository) -> None:
        """Persist changes to an existing repository.

        Raises:
            EntityNotFoundError: If no repository with `entity.id` currently exists.
        """
        await self._table.update(
            str(entity.id), _encode_metadata(source_repository_to_dict(entity))
        )

    async def delete(self, entity_id: UUID) -> None:
        """Remove a repository by id; a no-op if it does not exist."""
        await self._table.delete(str(entity_id))

    async def list(self) -> list[SourceRepository]:
        """Retrieve every stored repository."""
        return [source_repository_from_dict(_decode_metadata(r)) for r in await self._table.list_all()]

    async def get_by_source_uri(self, source_uri: str) -> SourceRepository | None:
        """Retrieve a repository by the location it was collected from."""
        row = await self._table.get_where("source_uri", source_uri)
        return source_repository_from_dict(_decode_metadata(row)) if row is not None else None


class SqliteSourceFileRepository(SourceFileRepository):
    """A `SourceFileRepository` backed by an injected SQLite connection."""

    def __init__(self, conn: SqliteConnection) -> None:
        """Initialize the store.

        Args:
            conn: A `SqliteConnection`, as returned by `open_connection`. The schema must
                already exist.
        """
        self._table = _SqliteTable(
            conn, table="source_files", columns=_SOURCE_FILE_COLUMNS, kind="SourceFile"
        )

    async def get(self, entity_id: UUID) -> SourceFile | None:
        """Retrieve a file by id."""
        row = await self._table.get(str(entity_id))
        return source_file_from_dict(_decode_metadata(row)) if row is not None else None

    async def add(self, entity: SourceFile) -> None:
        """Persist a new file.

        Raises:
            StorageIntegrityError: If a file with the same `id` already exists.
        """
        await self._table.add(str(entity.id), _encode_metadata(source_file_to_dict(entity)))

    async def update(self, entity: SourceFile) -> None:
        """Persist changes to an existing file.

        Raises:
            EntityNotFoundError: If no file with `entity.id` currently exists.
        """
        await self._table.update(str(entity.id), _encode_metadata(source_file_to_dict(entity)))

    async def delete(self, entity_id: UUID) -> None:
        """Remove a file by id; a no-op if it does not exist."""
        await self._table.delete(str(entity_id))

    async def list_by_repository(self, repository_id: UUID) -> list[SourceFile]:
        """Retrieve every file belonging to a given repository."""
        rows = await self._table.list_where("repository_id", str(repository_id))
        return [source_file_from_dict(_decode_metadata(r)) for r in rows]

    async def list(self) -> list[SourceFile]:
        """Retrieve every stored file."""
        return [source_file_from_dict(_decode_metadata(r)) for r in await self._table.list_all()]


class SqliteAnalysisRunRepository(AnalysisRunRepository):
    """An `AnalysisRunRepository` backed by an injected SQLite connection."""

    def __init__(self, conn: SqliteConnection) -> None:
        """Initialize the store.

        Args:
            conn: A `SqliteConnection`, as returned by `open_connection`. The schema must
                already exist.
        """
        self._table = _SqliteTable(
            conn, table="analysis_runs", columns=_ANALYSIS_RUN_COLUMNS, kind="AnalysisRun"
        )

    async def get(self, entity_id: UUID) -> AnalysisRun | None:
        """Retrieve an analysis run by id."""
        row = await self._table.get(str(entity_id))
        return analysis_run_from_dict(row) if row is not None else None

    async def add(self, entity: AnalysisRun) -> None:
        """Persist a new analysis run.

        Raises:
            StorageIntegrityError: If a run with the same `id` already exists.
        """
        await self._table.add(str(entity.id), analysis_run_to_dict(entity))

    async def update(self, entity: AnalysisRun) -> None:
        """Persist changes to an existing analysis run.

        Raises:
            EntityNotFoundError: If no run with `entity.id` currently exists.
        """
        await self._table.update(str(entity.id), analysis_run_to_dict(entity))

    async def delete(self, entity_id: UUID) -> None:
        """Remove an analysis run by id; a no-op if it does not exist."""
        await self._table.delete(str(entity_id))

    async def list_by_repository(self, repository_id: UUID) -> list[AnalysisRun]:
        """Retrieve every analysis run for a given repository."""
        rows = await self._table.list_where("repository_id", str(repository_id))
        return [analysis_run_from_dict(r) for r in rows]

    async def list(self) -> list[AnalysisRun]:
        """Retrieve every stored analysis run."""
        return [analysis_run_from_dict(r) for r in await self._table.list_all()]


class SqliteFindingRepository(FindingRepository):
    """A `FindingRepository` backed by an injected SQLite connection."""

    def __init__(self, conn: SqliteConnection) -> None:
        """Initialize the store.

        Args:
            conn: A `SqliteConnection`, as returned by `open_connection`. The schema must
                already exist.
        """
        self._table = _SqliteTable(
            conn, table="findings", columns=_FINDING_COLUMNS, kind="Finding"
        )

    async def get(self, entity_id: UUID) -> Finding | None:
        """Retrieve a finding by id."""
        row = await self._table.get(str(entity_id))
        return finding_from_dict(_decode_metadata(row)) if row is not None else None

    async def add(self, entity: Finding) -> None:
        """Persist a new finding.

        Raises:
            StorageIntegrityError: If a finding with the same `id` already exists.
        """
        await self._table.add(str(entity.id), _encode_metadata(finding_to_dict(entity)))

    async def update(self, entity: Finding) -> None:
        """Persist changes to an existing finding.

        Raises:
            EntityNotFoundError: If no finding with `entity.id` currently exists.
        """
        await self._table.update(str(entity.id), _encode_metadata(finding_to_dict(entity)))

    async def delete(self, entity_id: UUID) -> None:
        """Remove a finding by id; a no-op if it does not exist."""
        await self._table.delete(str(entity_id))

    async def list_by_analysis_run(self, analysis_run_id: UUID) -> list[Finding]:
        """Retrieve every finding produced by a given analysis run."""
        rows = await self._table.list_where("analysis_run_id", str(analysis_run_id))
        return [finding_from_dict(_decode_metadata(r)) for r in rows]

    async def list(self) -> list[Finding]:
        """Retrieve every stored finding."""
        return [finding_from_dict(_decode_metadata(r)) for r in await self._table.list_all()]
