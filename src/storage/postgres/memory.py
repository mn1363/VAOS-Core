"""PostgreSQL implementation of the persistent memory Port."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import asyncpg  # type: ignore[import-untyped]

from src.memory.base import MemoryQuery, MemoryQueryResult, MemoryRecord, MemoryStore
from src.storage.base import StorageConnectionError
from src.storage.memory_base import (
    filter_memory_records,
    memory_record_from_dict,
    memory_record_to_dict,
)

from .driver import _AsyncpgConnectionLike


class PostgresMemoryStore(MemoryStore):
    """Persist memory records in an injected PostgreSQL connection or pool."""

    def __init__(self, conn: _AsyncpgConnectionLike) -> None:
        self._conn = conn

    async def upsert(self, record: MemoryRecord) -> None:
        data = memory_record_to_dict(record)
        try:
            await self._conn.execute(
                """INSERT INTO memory_records
                (id, memory_type, content, metadata, entity_id, created_at, updated_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                ON CONFLICT (id) DO UPDATE SET
                memory_type=EXCLUDED.memory_type, content=EXCLUDED.content,
                metadata=EXCLUDED.metadata, entity_id=EXCLUDED.entity_id,
                created_at=EXCLUDED.created_at, updated_at=EXCLUDED.updated_at""",
                data["id"],
                data["memory_type"],
                json.dumps(data["content"], ensure_ascii=False, allow_nan=False),
                json.dumps(data["metadata"], ensure_ascii=False, allow_nan=False),
                data["entity_id"],
                data["created_at"],
                data["updated_at"],
            )
        except asyncpg.PostgresError as exc:
            raise StorageConnectionError(f"could not upsert memory record: {exc}") from exc

    async def get(self, record_id: UUID) -> MemoryRecord | None:
        try:
            row = await self._conn.fetchrow(
                "SELECT * FROM memory_records WHERE id = $1", str(record_id)
            )
        except asyncpg.PostgresError as exc:
            raise StorageConnectionError(f"could not read memory record: {exc}") from exc
        return self._decode_row(dict(row)) if row is not None else None

    async def delete(self, record_id: UUID) -> None:
        try:
            await self._conn.execute("DELETE FROM memory_records WHERE id = $1", str(record_id))
        except asyncpg.PostgresError as exc:
            raise StorageConnectionError(f"could not delete memory record: {exc}") from exc

    async def exists(self, record_id: UUID) -> bool:
        try:
            row = await self._conn.fetchrow(
                "SELECT 1 FROM memory_records WHERE id = $1", str(record_id)
            )
        except asyncpg.PostgresError as exc:
            raise StorageConnectionError(f"could not check memory record: {exc}") from exc
        return row is not None

    async def query(self, request: MemoryQuery) -> MemoryQueryResult:
        try:
            rows = await self._conn.fetch("SELECT * FROM memory_records")
        except asyncpg.PostgresError as exc:
            raise StorageConnectionError(f"could not query memory records: {exc}") from exc
        records = [self._decode_row(dict(row)) for row in rows]
        return MemoryQueryResult(records=filter_memory_records(records, request))

    @staticmethod
    def _decode_row(row: dict[str, Any]) -> MemoryRecord:
        data = dict(row)
        data["content"] = json.loads(data["content"])
        data["metadata"] = json.loads(data["metadata"])
        return memory_record_from_dict(data)

    async def aclose(self) -> None:
        """The shared PostgreSQL connection is closed by the StorageBundle resource."""
