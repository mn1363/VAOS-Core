"""Atomic JSON-file implementation of the persistent memory Port."""

from __future__ import annotations

import asyncio
import importlib
import json
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, cast
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

    @contextmanager
    def _process_lock(self) -> Iterator[None]:
        """Lock mutations across store instances and processes on the same host."""
        lock_path = self._path.with_suffix(self._path.suffix + ".lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+b") as lock_file:
            lock_file.seek(0, os.SEEK_END)
            if lock_file.tell() == 0:
                lock_file.write(b"\\0")
                lock_file.flush()
            lock_file.seek(0)
            if os.name == "nt":
                msvcrt = cast(Any, importlib.import_module('msvcrt'))

                msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
                try:
                    yield
                finally:
                    lock_file.seek(0)
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl = cast(Any, importlib.import_module('fcntl'))

                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

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

        def _upsert() -> None:
            with self._process_lock():
                data = self._read_sync()
                data[str(record.id)] = memory_record_to_dict(record)
                self._write_sync(data)

        async with self._lock:
            await asyncio.to_thread(_upsert)

    async def create_if_no_active_scope_conflict(self, record: MemoryRecord) -> bool:
        """Atomically check active scope and insert under the instance lock."""
        self._ensure_open()
        def _create() -> bool:
            with self._process_lock():
                data = self._read_sync()
                current = data.get(str(record.id))
                if current is not None:
                    if memory_record_from_dict(current) == record:
                        return True
                    raise ValueError("memory record id already exists with different content")
                scope = (
                    record.memory_type, record.entity_id,
                    record.content.get("expected_package_path"),
                )
                for item in data.values():
                    candidate = memory_record_from_dict(item)
                    if candidate.metadata.get("status") != "active":
                        continue
                    candidate_scope = (
                        candidate.memory_type, candidate.entity_id,
                        candidate.content.get("expected_package_path"),
                    )
                    if candidate_scope == scope:
                        return False
                updated = dict(data)
                updated[str(record.id)] = memory_record_to_dict(record)
                self._write_sync(updated)
                return True

        async with self._lock:
            return await asyncio.to_thread(_create)

    async def atomic_replace(
        self, expected: MemoryRecord, updates: tuple[MemoryRecord, ...]
    ) -> bool:
        """Compare and replace a group in one atomic JSON-file rewrite.

        The asyncio lock protects callers that share this store instance. It does not
        coordinate separate processes or separate store instances.
        """
        self._ensure_open()
        def _replace() -> bool:
            with self._process_lock():
                data = self._read_sync()
                current = data.get(str(expected.id))
                if current is None or memory_record_from_dict(current) != expected:
                    return False
                update_ids = [str(record.id) for record in updates]
                if len(update_ids) != len(set(update_ids)):
                    raise ValueError("atomic replacement contains duplicate record ids")
                if any(
                    record_id != str(expected.id) and record_id in data
                    for record_id in update_ids
                ):
                    raise ValueError("atomic replacement target id already exists")
                updated = dict(data)
                updated.pop(str(expected.id), None)
                for record in updates:
                    updated[str(record.id)] = memory_record_to_dict(record)
                self._write_sync(updated)
                return True

        async with self._lock:
            return await asyncio.to_thread(_replace)

    async def get(self, record_id: UUID) -> MemoryRecord | None:
        self._ensure_open()
        async with self._lock:
            data = await asyncio.to_thread(self._read_sync)
        item = data.get(str(record_id))
        return memory_record_from_dict(item) if item is not None else None

    async def delete(self, record_id: UUID) -> None:
        self._ensure_open()
        def _delete() -> None:
            with self._process_lock():
                data = self._read_sync()
                if data.pop(str(record_id), None) is not None:
                    self._write_sync(data)

        async with self._lock:
            await asyncio.to_thread(_delete)

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
