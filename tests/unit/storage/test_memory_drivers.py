"""Contract tests for the filesystem, SQLite and PostgreSQL memory drivers."""

from __future__ import annotations

import json
import multiprocessing
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from src.core.config import AppConfig
from src.memory.base import MemoryQuery, MemoryRecord
from src.storage.filesystem.memory import FilesystemMemoryStore
from src.storage.postgres.memory import PostgresMemoryStore
from src.storage.sqlite.driver import close_connection, initialize_schema, open_connection
from src.storage.sqlite.memory import SqliteMemoryStore

ENTITY_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")


def make_record(
    record_id: UUID, *, memory_type: str = "decision", label: str = "alpha"
) -> MemoryRecord:
    now = datetime(2026, 11, 1, tzinfo=UTC)
    return MemoryRecord(
        id=record_id,
        memory_type=memory_type,
        content={"label": label, "nested": {"enabled": True}},
        metadata={"scope": "project", "rank": 1},
        entity_id=ENTITY_ID,
        created_at=now,
        updated_at=now + timedelta(minutes=1),
    )


class FakePostgresConnection:
    """Small asyncpg-shaped fake for deterministic driver tests."""

    def __init__(self) -> None:
        self.records: dict[str, dict[str, Any]] = {}

    @asynccontextmanager
    async def transaction(self):
        yield

    async def execute(self, query: str, *args: Any, timeout: float | None = None) -> str:
        del timeout
        if query.startswith("INSERT INTO memory_records"):
            keys = (
                "id",
                "memory_type",
                "content",
                "metadata",
                "entity_id",
                "created_at",
                "updated_at",
            )
            self.records[str(args[0])] = dict(zip(keys, args, strict=True))
            return "INSERT 0 1"
        if query.startswith("DELETE FROM memory_records"):
            self.records.pop(str(args[0]), None)
            return "DELETE 1"
        if query.startswith("SELECT pg_advisory_xact_lock"):
            return "SELECT 1"
        raise AssertionError(f"unexpected SQL: {query}")

    async def fetchrow(
        self, query: str, *args: Any, timeout: float | None = None
    ) -> dict[str, Any] | None:
        del timeout
        record = self.records.get(str(args[0]))
        if query.startswith("SELECT 1"):
            return {"exists": 1} if record is not None else None
        return dict(record) if record is not None else None

    async def fetch(self, query: str, *args: Any, timeout: float | None = None) -> list[Any]:
        del timeout
        if query == "SELECT * FROM memory_records":
            return [dict(record) for record in self.records.values()]
        if "WHERE memory_type = $1 AND entity_id IS NOT DISTINCT FROM $2" in query:
            return [
                dict(record) for record in self.records.values()
                if record["memory_type"] == args[0] and record["entity_id"] == args[1]
            ]
        raise AssertionError(f"unexpected SQL: {query}")


def _filesystem_create_worker(
    root: str, record: MemoryRecord, result_queue: Any
) -> None:
    async def _run() -> None:
        store = FilesystemMemoryStore(Path(root))
        result_queue.put(await store.create_if_no_active_scope_conflict(record))
        await store.aclose()

    __import__("asyncio").run(_run())


def make_scoped_architecture_record(record_id: UUID, *, path: tuple[str, ...]) -> MemoryRecord:
    now = datetime.now(UTC)
    return MemoryRecord(
        id=record_id,
        memory_type="architecture_decision",
        content={"expected_package_path": list(path)},
        metadata={"status": "active", "confidence": 0.95, "analysis_scopes": ["architecture"]},
        entity_id=ENTITY_ID,
        created_at=now,
        updated_at=now,
    )


async def assert_memory_contract(store: Any) -> None:
    first = make_record(UUID("00000000-0000-0000-0000-000000000002"))
    second = make_record(
        UUID("00000000-0000-0000-0000-000000000001"),
        memory_type="observation",
        label="beta",
    )
    await store.upsert(first)
    await store.upsert(second)

    assert await store.get(first.id) == first
    assert await store.exists(first.id)
    assert not await store.exists(uuid4())

    all_records = await store.query(MemoryQuery())
    assert [item.id for item in all_records.records] == [second.id, first.id]
    assert all_records.record_count == 2

    filtered = await store.query(
        MemoryQuery(
            memory_type="decision", entity_id=ENTITY_ID, metadata_filter={"scope": "project"}
        )
    )
    assert filtered.records == (first,)

    unassociated = await store.query(MemoryQuery(entity_id_is_null=True))
    assert unassociated.record_count == 0

    limited = await store.query(MemoryQuery(limit=1))
    assert limited.records == (second,)

    updated = make_record(first.id, label="updated")
    await store.upsert(updated)
    assert (await store.get(first.id)).content["label"] == "updated"

    await store.delete(first.id)
    await store.delete(first.id)
    assert not await store.exists(first.id)
    assert (await store.query(MemoryQuery())).record_count == 1

    project_record = MemoryRecord(
        id=uuid4(),
        memory_type="project_decision",
        content={"decision": "keep project-wide knowledge"},
    )
    await store.upsert(project_record)
    unassociated = await store.query(MemoryQuery(entity_id_is_null=True))
    assert unassociated.records == (project_record,)


@pytest.mark.asyncio
async def test_filesystem_memory_store_contract_and_persistence(tmp_path: Path) -> None:
    store = FilesystemMemoryStore(tmp_path)
    await assert_memory_contract(store)

    reopened = FilesystemMemoryStore(tmp_path)
    remaining = await reopened.query(MemoryQuery())
    assert remaining.record_count == 2
    assert any(record.content.get("label") == "beta" for record in remaining.records)
    assert any(record.memory_type == "project_decision" for record in remaining.records)
    assert json.loads((tmp_path / "memory_records.json").read_text(encoding="utf-8"))
    await store.aclose()
    await reopened.aclose()


@pytest.mark.asyncio
async def test_sqlite_memory_store_contract_and_schema(tmp_path: Path) -> None:
    connection = open_connection(str(tmp_path / "memory.db"))
    try:
        await initialize_schema(connection)
        store = SqliteMemoryStore(connection)
        await assert_memory_contract(store)
        async with connection.lock:
            tables = await __import__("asyncio").to_thread(
                lambda: {
                    row["name"]
                    for row in connection.connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                }
            )
        assert "memory_records" in tables
        await store.aclose()

        await close_connection(connection)
        connection = open_connection(str(tmp_path / "memory.db"))
        await initialize_schema(connection)
        reopened = SqliteMemoryStore(connection)
        persisted = await reopened.query(MemoryQuery())
        assert persisted.record_count == 2
        assert any(record.content.get("label") == "beta" for record in persisted.records)
        assert any(record.memory_type == "project_decision" for record in persisted.records)
    finally:
        await close_connection(connection)


@pytest.mark.asyncio
async def test_postgres_memory_store_contract() -> None:
    store = PostgresMemoryStore(FakePostgresConnection())
    await assert_memory_contract(store)
    await store.aclose()


@pytest.mark.asyncio
async def test_build_storage_constructs_memory_store_for_filesystem_and_sqlite(
    tmp_path: Path,
) -> None:
    from src.bootstrap.wiring import build_storage

    filesystem = await build_storage(
        AppConfig(
            raw={"storage": {"backend": "filesystem", "filesystem": {"root": str(tmp_path / "fs")}}}
        )
    )
    assert isinstance(filesystem.memory_store, FilesystemMemoryStore)

    sqlite = await build_storage(
        AppConfig(
            raw={"storage": {"backend": "sqlite", "sqlite": {"path": str(tmp_path / "db.sqlite")}}}
        )
    )
    assert isinstance(sqlite.memory_store, SqliteMemoryStore)
    assert sqlite.resource is not None
    await sqlite.resource.aclose()


@pytest.mark.asyncio
async def test_sqlite_atomic_memory_replace_is_compare_and_swap(tmp_path: Path) -> None:
    connection = open_connection(str(tmp_path / "atomic-memory.db"))
    try:
        await initialize_schema(connection)
        store = SqliteMemoryStore(connection)
        original = make_record(uuid4())
        replacement = make_record(uuid4(), label="replacement")
        superseded = MemoryRecord(
            id=original.id,
            memory_type=original.memory_type,
            content=dict(original.content),
            metadata={**original.metadata, "status": "superseded"},
            entity_id=original.entity_id,
            created_at=original.created_at,
            updated_at=datetime.now(UTC),
        )
        await store.upsert(original)
        assert await store.atomic_replace(original, (superseded, replacement))
        assert await store.get(original.id) == superseded
        assert await store.get(replacement.id) == replacement
        assert not await store.atomic_replace(original, (original,))
    finally:
        await close_connection(connection)


@pytest.mark.asyncio
async def test_postgres_atomic_memory_replace_uses_transaction() -> None:
    store = PostgresMemoryStore(FakePostgresConnection())
    original = make_record(uuid4())
    replacement = make_record(uuid4(), label="replacement")
    superseded = MemoryRecord(
        id=original.id,
        memory_type=original.memory_type,
        content=dict(original.content),
        metadata={**original.metadata, "status": "superseded"},
        entity_id=original.entity_id,
        created_at=original.created_at,
        updated_at=datetime.now(UTC),
    )
    await store.upsert(original)
    assert await store.atomic_replace(original, (superseded, replacement))
    assert await store.get(original.id) == superseded
    assert await store.get(replacement.id) == replacement
    assert not await store.atomic_replace(original, (original,))


@pytest.mark.asyncio
async def test_filesystem_scoped_create_rejects_concurrent_conflict(tmp_path: Path) -> None:
    store = FilesystemMemoryStore(tmp_path)
    first = make_scoped_architecture_record(uuid4(), path=("src", "domain"))
    second = make_scoped_architecture_record(uuid4(), path=("src", "domain"))
    results = await __import__("asyncio").gather(
        store.create_if_no_active_scope_conflict(first),
        store.create_if_no_active_scope_conflict(second),
    )
    assert sorted(results) == [False, True]
    winner = first if await store.exists(first.id) else second
    assert await store.create_if_no_active_scope_conflict(winner)


def test_filesystem_scoped_create_is_safe_across_processes(tmp_path: Path) -> None:
    context = multiprocessing.get_context("spawn")
    result_queue = context.Queue()
    first = make_scoped_architecture_record(uuid4(), path=("src", "domain"))
    second = make_scoped_architecture_record(uuid4(), path=("src", "domain"))
    processes = [
        context.Process(
            target=_filesystem_create_worker,
            args=(str(tmp_path), record, result_queue),
        )
        for record in (first, second)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=20)
    try:
        assert [process.exitcode for process in processes] == [0, 0]
        assert sorted([result_queue.get(timeout=2), result_queue.get(timeout=2)]) == [False, True]
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
        result_queue.close()


@pytest.mark.asyncio
async def test_sqlite_scoped_create_rejects_concurrent_conflict(tmp_path: Path) -> None:
    connection = open_connection(str(tmp_path / "scoped-memory.db"))
    try:
        await initialize_schema(connection)
        store = SqliteMemoryStore(connection)
        first = make_scoped_architecture_record(uuid4(), path=("src", "domain"))
        second = make_scoped_architecture_record(uuid4(), path=("src", "domain"))
        results = await __import__("asyncio").gather(
            store.create_if_no_active_scope_conflict(first),
            store.create_if_no_active_scope_conflict(second),
        )
        assert sorted(results) == [False, True]
        winner = first if await store.exists(first.id) else second
        assert await store.create_if_no_active_scope_conflict(winner)
    finally:
        await close_connection(connection)


@pytest.mark.asyncio
async def test_postgres_scoped_create_rejects_conflict_and_is_idempotent() -> None:
    store = PostgresMemoryStore(FakePostgresConnection())
    first = make_scoped_architecture_record(uuid4(), path=("src", "domain"))
    second = make_scoped_architecture_record(uuid4(), path=("src", "domain"))
    assert await store.create_if_no_active_scope_conflict(first)
    assert not await store.create_if_no_active_scope_conflict(second)
    assert await store.create_if_no_active_scope_conflict(first)
