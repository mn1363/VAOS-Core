"""Atomic JSON-file implementation of the persistent memory Port."""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path
from typing import Any
from uuid import UUID

from src.memory.base import MemoryQuery, MemoryQueryResult, MemoryRecord, MemoryStore
from src.storage.base import StorageError
from src.storage.memory_base import (
    filter_memory_records,
    memory_record_from_dict,
    memory_record_to_dict,
)


class FilesystemMemoryStore(MemoryStore):
    """Persist memory records in one atomically replaced JSON collection."""

    def __init__(self, root: Path) -> None:
        self._path = root / "memory_records.json"
        self._lock = asyncio.Lock()
        self._closed = False
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def _read_sync(self) -> dict[str, dict[str, Any]]:
        if not self._path.exists():
            return {}
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise TypeError("memory collection must be a JSON object")
            return data
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise StorageError(
                f"could not read memory collection: {exc}", details={"path": str(self._path)}
            ) from exc

    def _write_sync(self, data: dict[str, dict[str, Any]]) -> None:
        temporary_path: str | None = None
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self._path.parent,
                prefix=f".{self._path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary_path = temporary.name
                json.dump(
                    data, temporary, ensure_ascii=False, allow_nan=False, separators=(",", ":")
                )
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_path, self._path)
        except (OSError, TypeError, ValueError) as exc:
            if temporary_path is not None:
                try:
                    os.unlink(temporary_path)
                except OSError:
                    pass
            raise StorageError(
                f"could not write memory collection: {exc}", details={"path": str(self._path)}
            ) from exc

    def _ensure_open(self) -> None:
        if self._closed:
            raise StorageError("memory store is closed")

    async def upsert(self, record: MemoryRecord) -> None:
        self._ensure_open()
        async with self._lock:
            data = await asyncio.to_thread(self._read_sync)
            data[str(record.id)] = memory_record_to_dict(record)
            await asyncio.to_thread(self._write_sync, data)

    async def get(self, record_id: UUID) -> MemoryRecord | None:
        self._ensure_open()
        async with self._lock:
            data = await asyncio.to_thread(self._read_sync)
        item = data.get(str(record_id))
        return memory_record_from_dict(item) if item is not None else None

    async def delete(self, record_id: UUID) -> None:
        self._ensure_open()
        async with self._lock:
            data = await asyncio.to_thread(self._read_sync)
            if data.pop(str(record_id), None) is not None:
                await asyncio.to_thread(self._write_sync, data)

    async def exists(self, record_id: UUID) -> bool:
        self._ensure_open()
        async with self._lock:
            data = await asyncio.to_thread(self._read_sync)
        return str(record_id) in data

    async def query(self, request: MemoryQuery) -> MemoryQueryResult:
        self._ensure_open()
        async with self._lock:
            data = await asyncio.to_thread(self._read_sync)
        records = [memory_record_from_dict(item) for item in data.values()]
        return MemoryQueryResult(records=filter_memory_records(records, request))

    async def aclose(self) -> None:
        self._closed = True
