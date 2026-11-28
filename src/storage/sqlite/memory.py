"""SQLite implementation of the persistent memory Port."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from typing import Any
from uuid import UUID

from src.memory.base import MemoryQuery, MemoryQueryResult, MemoryRecord, MemoryStore
from src.storage.base import StorageConnectionError
from src.storage.memory_base import (
    filter_memory_records,
    memory_record_from_dict,
    memory_record_to_dict,
)

from .driver import SqliteConnection


class SqliteMemoryStore(MemoryStore):
    """Persist memory records in the shared SQLite database connection."""

    def __init__(self, conn: SqliteConnection) -> None:
        self._conn = conn

    async def upsert(self, record: MemoryRecord) -> None:
        data = memory_record_to_dict(record)
        values = (
            data["id"],
            data["memory_type"],
            json.dumps(data["content"], ensure_ascii=False, allow_nan=False),
            json.dumps(data["metadata"], ensure_ascii=False, allow_nan=False),
            data["entity_id"],
            data["created_at"],
            data["updated_at"],
        )

        def _write() -> None:
            try:
                self._conn.connection.execute(
                    """INSERT INTO memory_records
                    (id, memory_type, content, metadata, entity_id, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                    memory_type=excluded.memory_type, content=excluded.content,
                    metadata=excluded.metadata, entity_id=excluded.entity_id,
                    created_at=excluded.created_at, updated_at=excluded.updated_at""",
                    values,
                )
                self._conn.connection.commit()
            except sqlite3.Error as exc:
                self._conn.connection.rollback()
                raise StorageConnectionError(f"could not upsert memory record: {exc}") from exc

        async with self._conn.lock:
            await asyncio.to_thread(_write)

    async def get(self, record_id: UUID) -> MemoryRecord | None:
        def _read() -> dict[str, Any] | None:
            try:
                row = self._conn.connection.execute(
                    "SELECT * FROM memory_records WHERE id = ?", (str(record_id),)
                ).fetchone()
                return dict(row) if row is not None else None
            except sqlite3.Error as exc:
                raise StorageConnectionError(f"could not read memory record: {exc}") from exc

        async with self._conn.lock:
            row = await asyncio.to_thread(_read)
        return self._decode_row(row) if row is not None else None

    async def delete(self, record_id: UUID) -> None:
        def _delete() -> None:
            try:
                self._conn.connection.execute(
                    "DELETE FROM memory_records WHERE id = ?", (str(record_id),)
                )
                self._conn.connection.commit()
            except sqlite3.Error as exc:
                self._conn.connection.rollback()
                raise StorageConnectionError(f"could not delete memory record: {exc}") from exc

        async with self._conn.lock:
            await asyncio.to_thread(_delete)

    async def exists(self, record_id: UUID) -> bool:
        def _exists() -> bool:
            try:
                row = self._conn.connection.execute(
                    "SELECT 1 FROM memory_records WHERE id = ?", (str(record_id),)
                ).fetchone()
                return row is not None
            except sqlite3.Error as exc:
                raise StorageConnectionError(f"could not check memory record: {exc}") from exc

        async with self._conn.lock:
            return await asyncio.to_thread(_exists)

    async def query(self, request: MemoryQuery) -> MemoryQueryResult:
        def _read() -> list[dict[str, Any]]:
            try:
                rows = self._conn.connection.execute("SELECT * FROM memory_records").fetchall()
                return [dict(row) for row in rows]
            except sqlite3.Error as exc:
                raise StorageConnectionError(f"could not query memory records: {exc}") from exc

        async with self._conn.lock:
            rows = await asyncio.to_thread(_read)
        records = [self._decode_row(row) for row in rows]
        return MemoryQueryResult(records=filter_memory_records(records, request))

    @staticmethod
    def _decode_row(row: dict[str, Any]) -> MemoryRecord:
        data = dict(row)
        data["content"] = json.loads(data["content"])
        data["metadata"] = json.loads(data["metadata"])
        return memory_record_from_dict(data)

    async def aclose(self) -> None:
        """The shared SQLite connection is closed by the StorageBundle resource."""
