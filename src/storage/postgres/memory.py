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

    async def create_if_no_active_scope_conflict(self, record: MemoryRecord) -> bool:
        """Serialize competing inserts for the same scope with a transaction lock."""
        data = memory_record_to_dict(record)
        try:
            if hasattr(self._conn, "acquire"):
                async with self._conn.acquire() as connection:
                    return await self._create_scoped_on_connection(connection, record, data)
            return await self._create_scoped_on_connection(self._conn, record, data)
        except asyncpg.PostgresError as exc:
            raise StorageConnectionError(
                f"could not atomically create scoped memory record: {exc}"
            ) from exc

    @staticmethod
    async def _create_scoped_on_connection(
        connection: Any, record: MemoryRecord, data: dict[str, Any]
    ) -> bool:
        scope_key = json.dumps(
            [record.memory_type, str(record.entity_id) if record.entity_id else None,
             record.content.get("expected_package_path")],
            ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        )
        async with connection.transaction():
            await connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))", scope_key
            )
            existing = await connection.fetchrow(
                "SELECT * FROM memory_records WHERE id = $1", data["id"]
            )
            if existing is not None:
                if PostgresMemoryStore._decode_row(dict(existing)) == record:
                    return True
                raise ValueError("memory record id already exists with different content")
            rows = await connection.fetch(
                """SELECT * FROM memory_records
                WHERE memory_type = $1 AND entity_id IS NOT DISTINCT FROM $2""",
                data["memory_type"], data["entity_id"],
            )
            scope = (
                record.memory_type, record.entity_id,
                record.content.get("expected_package_path"),
            )
            for row in rows:
                candidate = PostgresMemoryStore._decode_row(dict(row))
                if candidate.metadata.get("status") == "active" and (
                    candidate.memory_type, candidate.entity_id,
                    candidate.content.get("expected_package_path"),
                ) == scope:
                    return False
            await connection.execute(
                """INSERT INTO memory_records
                (id, memory_type, content, metadata, entity_id, created_at, updated_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7)""",
                data["id"], data["memory_type"],
                json.dumps(data["content"], ensure_ascii=False, allow_nan=False),
                json.dumps(data["metadata"], ensure_ascii=False, allow_nan=False),
                data["entity_id"], data["created_at"], data["updated_at"],
            )
            return True

    async def atomic_replace(
        self, expected: MemoryRecord, updates: tuple[MemoryRecord, ...]
    ) -> bool:
        """Compare and replace records in one PostgreSQL transaction."""
        update_data = [memory_record_to_dict(record) for record in updates]
        ids = [item["id"] for item in update_data]
        if len(ids) != len(set(ids)):
            raise ValueError("atomic replacement contains duplicate record ids")
        try:
            # asyncpg pools expose acquire(); bare connections expose transaction().
            if hasattr(self._conn, "acquire"):
                async with self._conn.acquire() as connection:
                    return await self._atomic_replace_on_connection(
                        connection, expected, update_data
                    )
            return await self._atomic_replace_on_connection(self._conn, expected, update_data)
        except asyncpg.PostgresError as exc:
            raise StorageConnectionError(f"could not atomically replace memory records: {exc}") from exc

    @staticmethod
    async def _atomic_replace_on_connection(
        connection: Any, expected: MemoryRecord, updates: list[dict[str, Any]]
    ) -> bool:
        async with connection.transaction():
            row = await connection.fetchrow(
                "SELECT * FROM memory_records WHERE id = $1 FOR UPDATE", str(expected.id)
            )
            if row is None or PostgresMemoryStore._decode_row(dict(row)) != expected:
                return False
            for item in updates:
                if item["id"] != str(expected.id):
                    exists = await connection.fetchrow(
                        "SELECT 1 FROM memory_records WHERE id = $1", item["id"]
                    )
                    if exists is not None:
                        raise ValueError("atomic replacement target id already exists")
            await connection.execute("DELETE FROM memory_records WHERE id = $1", str(expected.id))
            for item in updates:
                await connection.execute(
                    """INSERT INTO memory_records
                    (id, memory_type, content, metadata, entity_id, created_at, updated_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)""",
                    item["id"], item["memory_type"],
                    json.dumps(item["content"], ensure_ascii=False, allow_nan=False),
                    json.dumps(item["metadata"], ensure_ascii=False, allow_nan=False),
                    item["entity_id"], item["created_at"], item["updated_at"],
                )
            return True

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
