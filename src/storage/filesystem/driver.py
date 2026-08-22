"""Concrete filesystem-backed implementations of every `domain.interfaces` persistence Port.

Each store keeps one JSON file per entity collection under an injected root directory (e.g.
`<root>/source_repositories.json`), holding a `{id: serialized-entity}` mapping. Every
read-modify-write cycle is serialized by a per-collection `asyncio.Lock` and written atomically
(a temporary file, then an OS-level rename) so a crash mid-write can never leave a collection
file truncated or partially overwritten. File I/O itself runs off the event loop via
`asyncio.to_thread`, since `Path.read_text`/`write_text` are blocking calls -- matching every
other `async` Port implementation's own precedent (e.g. `repository.git.GitRepositoryClient`'s
subprocess-based I/O) of never blocking the event loop for real I/O.

`add` raises `StorageIntegrityError` on a duplicate id, `update` raises `EntityNotFoundError` on
a missing id, and `delete` is a no-op on a missing id -- see `storage.base.EntityNotFoundError`
for why this split exists.
"""

import asyncio
import json
import os
import tempfile
from pathlib import Path
from typing import Any
from uuid import UUID

from src.core.logging import get_logger
from src.core.utils import ensure_directory
from src.domain.entities import AnalysisRun, Finding, SourceFile, SourceRepository
from src.domain.interfaces import (
    AnalysisRunRepository,
    FindingRepository,
    SourceFileRepository,
    SourceRepositoryStore,
)

from ..base import (
    EntityNotFoundError,
    StorageError,
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

_logger = get_logger("storage.filesystem")


class _JsonCollectionStore:
    """Generic, thread-offloaded, atomic-write JSON-file backing store keyed by string id.

    Centralizes the add/update/delete semantics every concrete `Filesystem...` class below
    shares: `add` raises `StorageIntegrityError` on a duplicate id, `update` raises
    `EntityNotFoundError` on a missing id, `delete` is a no-op on a missing id. Not itself a
    `domain.interfaces.Repository` implementation.
    """

    def __init__(self, path: Path, *, kind: str) -> None:
        """Initialize the store, ensuring `path`'s parent directory exists.

        Args:
            path: The JSON file this store reads from and writes to. Not created until the
                first write; reading treats a missing file as an empty collection.
            kind: Human-readable entity type name (e.g. `"SourceRepository"`), used only to
                compose error messages.
        """
        self._path = path
        self._kind = kind
        self._lock = asyncio.Lock()
        ensure_directory(path.parent)

    async def get(self, entity_id: str) -> dict[str, Any] | None:
        """Retrieve one serialized entity by string id.

        Args:
            entity_id: String id of the entry to retrieve.

        Returns:
            The stored record, or None if no entry exists with that id.
        """
        async with self._lock:
            data = await asyncio.to_thread(self._read_sync)
        return data.get(entity_id)

    async def list_all(self) -> list[dict[str, Any]]:
        """Retrieve every serialized entity currently in the collection.

        Returns:
            Every stored record, in the collection file's own key order.
        """
        async with self._lock:
            data = await asyncio.to_thread(self._read_sync)
        return list(data.values())

    async def add(self, entity_id: str, record: dict[str, Any]) -> None:
        """Insert a new entry, or raise if `entity_id` already exists.

        Args:
            entity_id: String id of the entry to insert.
            record: The serialized entity to store.

        Raises:
            StorageIntegrityError: If an entry with `entity_id` already exists.
            StorageError: If the backing file cannot be read or written.
        """
        async with self._lock:
            data = await asyncio.to_thread(self._read_sync)
            if entity_id in data:
                raise StorageIntegrityError(
                    f"{self._kind} with id '{entity_id}' already exists",
                    details={"id": entity_id, "path": str(self._path)},
                )
            data[entity_id] = record
            await asyncio.to_thread(self._write_sync, data)

    async def update(self, entity_id: str, record: dict[str, Any]) -> None:
        """Overwrite an existing entry, or raise if `entity_id` does not exist.

        Args:
            entity_id: String id of the entry to overwrite.
            record: The serialized entity to store.

        Raises:
            EntityNotFoundError: If no entry with `entity_id` currently exists.
            StorageError: If the backing file cannot be read or written.
        """
        async with self._lock:
            data = await asyncio.to_thread(self._read_sync)
            if entity_id not in data:
                raise EntityNotFoundError(
                    f"{self._kind} with id '{entity_id}' does not exist",
                    details={"id": entity_id, "path": str(self._path)},
                )
            data[entity_id] = record
            await asyncio.to_thread(self._write_sync, data)

    async def delete(self, entity_id: str) -> None:
        """Remove an entry by string id; a no-op if it does not exist.

        Args:
            entity_id: String id of the entry to remove.

        Raises:
            StorageError: If the backing file cannot be read or written.
        """
        async with self._lock:
            data = await asyncio.to_thread(self._read_sync)
            if entity_id in data:
                del data[entity_id]
                await asyncio.to_thread(self._write_sync, data)

    def _read_sync(self) -> dict[str, Any]:
        """Blocking read of the backing JSON file.

        Returns:
            The parsed `{id: serialized-entity}` mapping, or an empty dict if the file is
            missing or empty.

        Raises:
            StorageError: If the file exists but is not valid JSON, is not UTF-8-decodable, or
                its top-level structure is not a JSON object.
        """
        if not self._path.exists():
            return {}
        try:
            content = self._path.read_text(encoding="utf-8")
        except OSError as exc:
            raise StorageError(
                f"could not read '{self._path}': {exc}", details={"path": str(self._path)}
            ) from exc
        if not content.strip():
            return {}
        try:
            data = json.loads(content)
        except json.JSONDecodeError as exc:
            raise StorageError(
                f"invalid JSON in '{self._path}': {exc}", details={"path": str(self._path)}
            ) from exc
        if not isinstance(data, dict):
            raise StorageError(
                f"expected a JSON object at the top level of '{self._path}', got "
                f"{type(data).__name__}",
                details={"path": str(self._path)},
            )
        return data

    def _write_sync(self, data: dict[str, Any]) -> None:
        """Blocking, atomic write of `data` to the backing JSON file.

        Writes to a temporary file in the same directory, then `os.replace`s it over the
        target -- atomic on every platform this runs on, so a crash mid-write can never leave
        `self._path` truncated or partially written.

        Args:
            data: The full `{id: serialized-entity}` mapping to persist.

        Raises:
            StorageError: If the write or atomic replace fails.
        """
        tmp_name: str | None = None
        try:
            fd, tmp_name = tempfile.mkstemp(
                dir=str(self._path.parent), prefix=f".{self._path.name}.", suffix=".tmp"
            )
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=2, sort_keys=True)
            os.replace(tmp_name, self._path)
        except OSError as exc:
            if tmp_name is not None:
                Path(tmp_name).unlink(missing_ok=True)
            raise StorageError(
                f"could not write '{self._path}': {exc}", details={"path": str(self._path)}
            ) from exc


class FilesystemSourceRepositoryStore(SourceRepositoryStore):
    """A `SourceRepositoryStore` backed by one JSON file under an injected root directory."""

    def __init__(self, root: Path) -> None:
        """Initialize the store.

        Args:
            root: Directory the backing `source_repositories.json` file is created under.
                Creating `root` itself is a local, synchronous side effect (matching
                `repository.workspace.FilesystemWorkspaceManager`'s own precedent), not the
                "hidden network call" a driver must avoid during construction.
        """
        self._collection = _JsonCollectionStore(
            root / "source_repositories.json", kind="SourceRepository"
        )

    async def get(self, entity_id: UUID) -> SourceRepository | None:
        """Retrieve a repository by id.

        Args:
            entity_id: Identifier of the repository to retrieve.

        Returns:
            The matching repository, or None if no repository exists with that id.
        """
        record = await self._collection.get(str(entity_id))
        return source_repository_from_dict(record) if record is not None else None

    async def add(self, entity: SourceRepository) -> None:
        """Persist a new repository.

        Args:
            entity: The repository to add.

        Raises:
            StorageIntegrityError: If a repository with the same `id` already exists.
        """
        await self._collection.add(str(entity.id), source_repository_to_dict(entity))

    async def update(self, entity: SourceRepository) -> None:
        """Persist changes to an existing repository.

        Args:
            entity: The repository, with updated field values, to save.

        Raises:
            EntityNotFoundError: If no repository with `entity.id` currently exists.
        """
        await self._collection.update(str(entity.id), source_repository_to_dict(entity))

    async def delete(self, entity_id: UUID) -> None:
        """Remove a repository by id; a no-op if it does not exist.

        Args:
            entity_id: Identifier of the repository to remove.
        """
        await self._collection.delete(str(entity_id))

    async def list(self) -> list[SourceRepository]:
        """Retrieve every stored repository.

        Returns:
            Every persisted `SourceRepository`.
        """
        return [source_repository_from_dict(r) for r in await self._collection.list_all()]

    async def get_by_source_uri(self, source_uri: str) -> SourceRepository | None:
        """Retrieve a repository by the location it was collected from.

        Args:
            source_uri: Location to look up.

        Returns:
            The matching repository, or None if none has that source URI.
        """
        for record in await self._collection.list_all():
            if record["source_uri"] == source_uri:
                return source_repository_from_dict(record)
        return None


class FilesystemSourceFileRepository(SourceFileRepository):
    """A `SourceFileRepository` backed by one JSON file under an injected root directory."""

    def __init__(self, root: Path) -> None:
        """Initialize the store.

        Args:
            root: Directory the backing `source_files.json` file is created under.
        """
        self._collection = _JsonCollectionStore(root / "source_files.json", kind="SourceFile")

    async def get(self, entity_id: UUID) -> SourceFile | None:
        """Retrieve a file by id.

        Args:
            entity_id: Identifier of the file to retrieve.

        Returns:
            The matching file, or None if no file exists with that id.
        """
        record = await self._collection.get(str(entity_id))
        return source_file_from_dict(record) if record is not None else None

    async def add(self, entity: SourceFile) -> None:
        """Persist a new file.

        Args:
            entity: The file to add.

        Raises:
            StorageIntegrityError: If a file with the same `id` already exists.
        """
        await self._collection.add(str(entity.id), source_file_to_dict(entity))

    async def update(self, entity: SourceFile) -> None:
        """Persist changes to an existing file.

        Args:
            entity: The file, with updated field values, to save.

        Raises:
            EntityNotFoundError: If no file with `entity.id` currently exists.
        """
        await self._collection.update(str(entity.id), source_file_to_dict(entity))

    async def delete(self, entity_id: UUID) -> None:
        """Remove a file by id; a no-op if it does not exist.

        Args:
            entity_id: Identifier of the file to remove.
        """
        await self._collection.delete(str(entity_id))

    async def list_by_repository(self, repository_id: UUID) -> list[SourceFile]:
        """Retrieve every file belonging to a given repository.

        Args:
            repository_id: Identifier of the owning repository.

        Returns:
            Every `SourceFile` whose `repository_id` matches.
        """
        return [
            source_file_from_dict(r)
            for r in await self._collection.list_all()
            if r["repository_id"] == str(repository_id)
        ]

    async def list(self) -> list[SourceFile]:
        """Retrieve every stored file.

        Returns:
            Every persisted `SourceFile`.
        """
        return [source_file_from_dict(r) for r in await self._collection.list_all()]


class FilesystemAnalysisRunRepository(AnalysisRunRepository):
    """An `AnalysisRunRepository` backed by one JSON file under an injected root directory."""

    def __init__(self, root: Path) -> None:
        """Initialize the store.

        Args:
            root: Directory the backing `analysis_runs.json` file is created under.
        """
        self._collection = _JsonCollectionStore(root / "analysis_runs.json", kind="AnalysisRun")

    async def get(self, entity_id: UUID) -> AnalysisRun | None:
        """Retrieve an analysis run by id.

        Args:
            entity_id: Identifier of the run to retrieve.

        Returns:
            The matching run, or None if no run exists with that id.
        """
        record = await self._collection.get(str(entity_id))
        return analysis_run_from_dict(record) if record is not None else None

    async def add(self, entity: AnalysisRun) -> None:
        """Persist a new analysis run.

        Args:
            entity: The run to add.

        Raises:
            StorageIntegrityError: If a run with the same `id` already exists.
        """
        await self._collection.add(str(entity.id), analysis_run_to_dict(entity))

    async def update(self, entity: AnalysisRun) -> None:
        """Persist changes to an existing analysis run.

        Args:
            entity: The run, with updated field values, to save.

        Raises:
            EntityNotFoundError: If no run with `entity.id` currently exists.
        """
        await self._collection.update(str(entity.id), analysis_run_to_dict(entity))

    async def delete(self, entity_id: UUID) -> None:
        """Remove an analysis run by id; a no-op if it does not exist.

        Args:
            entity_id: Identifier of the run to remove.
        """
        await self._collection.delete(str(entity_id))

    async def list_by_repository(self, repository_id: UUID) -> list[AnalysisRun]:
        """Retrieve every analysis run for a given repository.

        Args:
            repository_id: Identifier of the analyzed repository.

        Returns:
            Every `AnalysisRun` whose `repository_id` matches.
        """
        return [
            analysis_run_from_dict(r)
            for r in await self._collection.list_all()
            if r["repository_id"] == str(repository_id)
        ]

    async def list(self) -> list[AnalysisRun]:
        """Retrieve every stored analysis run.

        Returns:
            Every persisted `AnalysisRun`.
        """
        return [analysis_run_from_dict(r) for r in await self._collection.list_all()]


class FilesystemFindingRepository(FindingRepository):
    """A `FindingRepository` backed by one JSON file under an injected root directory."""

    def __init__(self, root: Path) -> None:
        """Initialize the store.

        Args:
            root: Directory the backing `findings.json` file is created under.
        """
        self._collection = _JsonCollectionStore(root / "findings.json", kind="Finding")

    async def get(self, entity_id: UUID) -> Finding | None:
        """Retrieve a finding by id.

        Args:
            entity_id: Identifier of the finding to retrieve.

        Returns:
            The matching finding, or None if no finding exists with that id.
        """
        record = await self._collection.get(str(entity_id))
        return finding_from_dict(record) if record is not None else None

    async def add(self, entity: Finding) -> None:
        """Persist a new finding.

        Args:
            entity: The finding to add.

        Raises:
            StorageIntegrityError: If a finding with the same `id` already exists.
        """
        await self._collection.add(str(entity.id), finding_to_dict(entity))

    async def update(self, entity: Finding) -> None:
        """Persist changes to an existing finding.

        Args:
            entity: The finding, with updated field values, to save.

        Raises:
            EntityNotFoundError: If no finding with `entity.id` currently exists.
        """
        await self._collection.update(str(entity.id), finding_to_dict(entity))

    async def delete(self, entity_id: UUID) -> None:
        """Remove a finding by id; a no-op if it does not exist.

        Args:
            entity_id: Identifier of the finding to remove.
        """
        await self._collection.delete(str(entity_id))

    async def list_by_analysis_run(self, analysis_run_id: UUID) -> list[Finding]:
        """Retrieve every finding produced by a given analysis run.

        Args:
            analysis_run_id: Identifier of the owning analysis run.

        Returns:
            Every `Finding` whose `analysis_run_id` matches.
        """
        return [
            finding_from_dict(r)
            for r in await self._collection.list_all()
            if r["analysis_run_id"] == str(analysis_run_id)
        ]

    async def list(self) -> list[Finding]:
        """Retrieve every stored finding.

        Returns:
            Every persisted `Finding`.
        """
        return [finding_from_dict(r) for r in await self._collection.list_all()]
