"""Contract tests for the filesystem, SQLite and PostgreSQL memory drivers."""

from __future__ import annotations

import json
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
        del args, timeout
        if query == "SELECT * FROM memory_records":
            return [dict(record) for record in self.records.values()]
        raise AssertionError(f"unexpected SQL: {query}")


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

    limited = await store.query(MemoryQuery(limit=1))
    assert limited.records == (second,)

    updated = make_record(first.id, label="updated")
    await store.upsert(updated)
    assert (await store.get(first.id)).content["label"] == "updated"

    await store.delete(first.id)
    await store.delete(first.id)
    assert not await store.exists(first.id)
    assert (await store.query(MemoryQuery())).record_count == 1


@pytest.mark.asyncio
async def test_filesystem_memory_store_contract_and_persistence(tmp_path: Path) -> None:
    store = FilesystemMemoryStore(tmp_path)
    await assert_memory_contract(store)

    reopened = FilesystemMemoryStore(tmp_path)
    remaining = await reopened.query(MemoryQuery())
    assert remaining.record_count == 1
    assert remaining.records[0].content["label"] == "beta"
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
        assert persisted.record_count == 1
        assert persisted.records[0].content["label"] == "beta"
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
