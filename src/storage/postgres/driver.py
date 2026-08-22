"""Concrete PostgreSQL-backed implementations of every `domain.interfaces` persistence Port.

Requires the `asyncpg` client. **`asyncpg` is not yet a declared dependency of this project --
see the dependency note in `docs/phase10_summary.md` for exactly what to add to `pyproject.toml`
and why; `pyproject.toml` itself was deliberately left untouched, per this phase's own "STOP
before modifying pyproject.toml" instruction.** This module imports `asyncpg` directly (a
genuine driver against the real client, not a further abstraction over it), so it cannot be
imported in an environment that has not separately installed it.

A connection or pool is always supplied by the caller -- via the module-level `connect`/
`create_pool` factories, kept deliberately separate from every store's own `__init__` -- never
opened implicitly; schema creation is likewise an explicit, separate `initialize_schema` step.
This matches `storage.sqlite`'s own precedent and this phase's "no hidden ... calls during
object construction" requirement, generalized from Qdrant to every backend.

Every store accepts anything satisfying `asyncpg`'s own `execute`/`fetch`/`fetchrow` calling
convention (`_AsyncpgConnectionLike`) -- a single `asyncpg.Connection`, suitable for simple,
non-concurrent use, or an `asyncpg.Pool` for concurrent access across multiple stores or
coroutines. Unlike `sqlite3`, `asyncpg` itself refuses concurrent operations on a single bare
`Connection` (raising `asyncpg.InterfaceError`, wrapped here as `StorageConnectionError`) rather
than risking silent corruption, so this module -- unlike `storage.sqlite` -- does not need its
own additional locking layer; a `Pool` manages concurrent access safely on its own.

Every id/foreign-key/timestamp column is `TEXT`, and `metadata` is `TEXT` holding a JSON-encoded
string -- not native `UUID`/`TIMESTAMPTZ`/`JSONB` -- a deliberate choice trading native
PostgreSQL typing for byte-for-byte reuse of `storage.base`'s existing (de)serialization
functions, unmodified, across all three entity-persisting backends (see
`docs/phase10_summary.md` for the full rationale).

`add` raises `StorageIntegrityError` on a duplicate id (or a `UNIQUE` constraint violation),
`update` raises `EntityNotFoundError` on a missing id, and `delete` is a no-op on a missing id --
the same semantics `storage.filesystem` and `storage.sqlite` establish.
"""

import json
from typing import Any, Protocol
from uuid import UUID

import asyncpg  # type: ignore[import-untyped]  # no py.typed marker; see module docstring

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

_logger = get_logger("storage.postgres")

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
    size_bytes BIGINT NOT NULL,
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
    score DOUBLE PRECISION,
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


class _AsyncpgConnectionLike(Protocol):
    """Structural shape of the `asyncpg.Connection`/`asyncpg.Pool` calling convention this
    driver uses.

    Both `asyncpg.Connection` and `asyncpg.Pool` satisfy this Protocol with an identical calling
    convention, so either may be injected without this module needing to know which -- a
    `Connection` for simple, non-concurrent use, or a `Pool` when concurrent access is needed.
    """

    async def execute(self, query: str, *args: Any, timeout: float | None = None) -> str:
        """Execute a single SQL command and return its status string (e.g. `"UPDATE 1"`)."""
        ...

    async def fetch(self, query: str, *args: Any, timeout: float | None = None) -> list[Any]:
        """Execute a query and return every matching row as a list of `asyncpg.Record`."""
        ...

    async def fetchrow(
        self, query: str, *args: Any, timeout: float | None = None
    ) -> Any | None:
        """Execute a query and return its first matching row, or None."""
        ...


async def connect(dsn: str, **kwargs: Any) -> asyncpg.Connection:
    """Open a single `asyncpg.Connection` to `dsn`.

    A convenience factory kept separate from every store's `__init__` -- a store's own
    constructor never opens a connection itself; a connection or pool is always supplied by the
    caller, matching this phase's "no global client" and "explicit client/configuration
    injection" requirements. Suitable for simple, non-concurrent use; use `create_pool` instead
    for concurrent access.

    Args:
        dsn: PostgreSQL connection string, e.g. `"postgresql://user:pass@host/db"`.
        **kwargs: Forwarded to `asyncpg.connect`.

    Returns:
        An open connection.

    Raises:
        StorageConnectionError: If the connection cannot be established.
    """
    try:
        return await asyncpg.connect(dsn, **kwargs)
    except (OSError, asyncpg.PostgresError) as exc:
        raise StorageConnectionError(
            f"could not connect to PostgreSQL: {exc}", details={"dsn": dsn}
        ) from exc


async def create_pool(dsn: str, **kwargs: Any) -> asyncpg.Pool:
    """Open an `asyncpg.Pool` to `dsn`, for concurrent use across multiple stores or coroutines.

    Args:
        dsn: PostgreSQL connection string.
        **kwargs: Forwarded to `asyncpg.create_pool`.

    Returns:
        An open connection pool.

    Raises:
        StorageConnectionError: If the pool cannot be established.
    """
    try:
        pool = await asyncpg.create_pool(dsn, **kwargs)
    except (OSError, asyncpg.PostgresError) as exc:
        raise StorageConnectionError(
            f"could not create a PostgreSQL pool: {exc}", details={"dsn": dsn}
        ) from exc
    if pool is None:
        raise StorageConnectionError(
            "asyncpg.create_pool returned no pool", details={"dsn": dsn}
        )
    return pool


async def close_connection(connection: asyncpg.Connection) -> None:
    """Close a connection opened by `connect`.

    Args:
        connection: The connection to close.
    """
    await connection.close()


async def close_pool(pool: asyncpg.Pool) -> None:
    """Close a pool opened by `create_pool`.

    Args:
        pool: The pool to close.
    """
    await pool.close()


async def initialize_schema(conn: _AsyncpgConnectionLike) -> None:
    """Create every table and index this package's stores need, if not already present.

    Idempotent: safe to call against a database that already has this schema.

    Args:
        conn: An open connection or pool, as returned by `connect`/`create_pool`.

    Raises:
        StorageConnectionError: If schema creation fails.
    """
    try:
        await conn.execute(_SCHEMA)
    except asyncpg.PostgresError as exc:
        raise StorageConnectionError(f"could not initialize PostgreSQL schema: {exc}") from exc


def _encode_metadata(record: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of `record` with its `metadata` dict JSON-encoded for storage.

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
        row: A raw row dict read from a table with a JSON-encoded `metadata` column.

    Returns:
        A copy of `row` with `metadata` replaced by the parsed dict, ready for one of
        `storage.base`'s `*_from_dict` functions.
    """
    return {**row, "metadata": json.loads(row["metadata"])}


def _affected_rows(status: str) -> int:
    """Parse the row count from an `asyncpg` command-completion status string.

    Args:
        status: The string `execute()` returns, e.g. `"UPDATE 1"`, `"DELETE 0"`,
            `"INSERT 0 1"`.

    Returns:
        The trailing integer count, e.g. `1` for `"UPDATE 1"`.
    """
    return int(status.rsplit(" ", 1)[-1])


class _PostgresTable:
    """Generic CRUD helper for one PostgreSQL table keyed by a TEXT `id` column.

    Centralizes the same add/update/delete semantics `storage.filesystem._JsonCollectionStore`
    and `storage.sqlite._SqliteTable` establish: `add` raises `StorageIntegrityError` on a
    duplicate id or other constraint violation, `update` raises `EntityNotFoundError` on a
    missing id, `delete` is a no-op on a missing id. `table` is always an internal constant fixed
    at construction, never derived from external input, so building SQL with an f-string here
    carries no injection risk despite the surface resemblance to one.
    """

    def __init__(
        self,
        conn: _AsyncpgConnectionLike,
        *,
        table: str,
        columns: tuple[str, ...],
        kind: str,
    ) -> None:
        """Initialize the helper.

        Args:
            conn: An open connection or pool; schema must already exist (see
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
        try:
            record = await self._conn.fetchrow(
                f"SELECT * FROM {self._table} WHERE {column} = $1", value
            )
        except asyncpg.PostgresError as exc:
            raise StorageConnectionError(
                f"could not query '{self._table}': {exc}", details={"table": self._table}
            ) from exc
        return dict(record) if record is not None else None

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
        try:
            if column is None:
                records = await self._conn.fetch(f"SELECT * FROM {self._table}")
            else:
                records = await self._conn.fetch(
                    f"SELECT * FROM {self._table} WHERE {column} = $1", value
                )
        except asyncpg.PostgresError as exc:
            raise StorageConnectionError(
                f"could not query '{self._table}': {exc}", details={"table": self._table}
            ) from exc
        return [dict(r) for r in records]

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
        placeholders = ", ".join(f"${i + 1}" for i in range(len(self._columns)))
        values = [record[c] for c in self._columns]
        try:
            await self._conn.execute(
                f"INSERT INTO {self._table} ({column_list}) VALUES ({placeholders})", *values
            )
        except asyncpg.UniqueViolationError as exc:
            raise StorageIntegrityError(
                f"{self._kind} with id '{entity_id}' violates a uniqueness constraint: {exc}",
                details={"id": entity_id, "table": self._table},
            ) from exc
        except asyncpg.PostgresError as exc:
            raise StorageConnectionError(
                f"could not insert into '{self._table}': {exc}",
                details={"table": self._table},
            ) from exc

    async def update(self, entity_id: str, record: dict[str, Any]) -> None:
        """Overwrite an existing row, or raise if `entity_id` does not exist.

        Args:
            entity_id: String id of the row to overwrite.
            record: Column values to write, keyed by every name in `self._columns`.

        Raises:
            EntityNotFoundError: If no row with `entity_id` currently exists.
            StorageIntegrityError: If the update violates a constraint.
            StorageConnectionError: If the update fails for any other reason.
        """
        set_columns = [c for c in self._columns if c != "id"]
        assignments = ", ".join(f"{c} = ${i + 1}" for i, c in enumerate(set_columns))
        id_placeholder = f"${len(set_columns) + 1}"
        values = [record[c] for c in set_columns] + [entity_id]
        try:
            status = await self._conn.execute(
                f"UPDATE {self._table} SET {assignments} WHERE id = {id_placeholder}", *values
            )
        except asyncpg.UniqueViolationError as exc:
            raise StorageIntegrityError(
                f"{self._kind} with id '{entity_id}' violates a uniqueness constraint: {exc}",
                details={"id": entity_id, "table": self._table},
            ) from exc
        except asyncpg.PostgresError as exc:
            raise StorageConnectionError(
                f"could not update '{self._table}': {exc}", details={"table": self._table}
            ) from exc
        if _affected_rows(status) == 0:
            raise EntityNotFoundError(
                f"{self._kind} with id '{entity_id}' does not exist",
                details={"id": entity_id, "table": self._table},
            )

    async def delete(self, entity_id: str) -> None:
        """Remove a row by `id`; a no-op if it does not exist.

        Args:
            entity_id: String id of the row to remove.

        Raises:
            StorageConnectionError: If the delete fails.
        """
        try:
            await self._conn.execute(f"DELETE FROM {self._table} WHERE id = $1", entity_id)
        except asyncpg.PostgresError as exc:
            raise StorageConnectionError(
                f"could not delete from '{self._table}': {exc}",
                details={"table": self._table},
            ) from exc


class PostgresSourceRepositoryStore(SourceRepositoryStore):
    """A `SourceRepositoryStore` backed by an injected PostgreSQL connection or pool."""

    def __init__(self, conn: _AsyncpgConnectionLike) -> None:
        """Initialize the store.

        Args:
            conn: An open `asyncpg.Connection` or `asyncpg.Pool`. The schema must already
                exist -- call `initialize_schema` once before using any store built on it.
        """
        self._table = _PostgresTable(
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

    async def get_by_source_uri(self, source_uri: str) -> SourceRepository | None:
        """Retrieve a repository by the location it was collected from."""
        row = await self._table.get_where("source_uri", source_uri)
        return source_repository_from_dict(_decode_metadata(row)) if row is not None else None

    async def list(self) -> list[SourceRepository]:
        """Retrieve every stored repository."""
        return [
            source_repository_from_dict(_decode_metadata(r)) for r in await self._table.list_all()
        ]


class PostgresSourceFileRepository(SourceFileRepository):
    """A `SourceFileRepository` backed by an injected PostgreSQL connection or pool."""

    def __init__(self, conn: _AsyncpgConnectionLike) -> None:
        """Initialize the store.

        Args:
            conn: An open `asyncpg.Connection` or `asyncpg.Pool`. The schema must already exist.
        """
        self._table = _PostgresTable(
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


class PostgresAnalysisRunRepository(AnalysisRunRepository):
    """An `AnalysisRunRepository` backed by an injected PostgreSQL connection or pool."""

    def __init__(self, conn: _AsyncpgConnectionLike) -> None:
        """Initialize the store.

        Args:
            conn: An open `asyncpg.Connection` or `asyncpg.Pool`. The schema must already exist.
        """
        self._table = _PostgresTable(
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


class PostgresFindingRepository(FindingRepository):
    """A `FindingRepository` backed by an injected PostgreSQL connection or pool."""

    def __init__(self, conn: _AsyncpgConnectionLike) -> None:
        """Initialize the store.

        Args:
            conn: An open `asyncpg.Connection` or `asyncpg.Pool`. The schema must already exist.
        """
        self._table = _PostgresTable(
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
