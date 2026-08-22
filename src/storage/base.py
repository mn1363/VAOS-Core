"""Storage layer shared contracts: the error hierarchy and entity (de)serialization helpers
every entity-persisting backend (`filesystem`, `sqlite`, `postgres`) builds on.

Serialization lives here, rather than duplicated in each backend, so all three agree on exactly
one JSON-safe representation per entity type: `id`/foreign-key `UUID` fields as strings, `StrEnum`
fields as their string value, `datetime` fields as ISO-8601 strings, and `metadata`/`raw` dict
fields passed through unchanged. Each backend decides its own on-disk/on-wire encoding of that
dict (a whole-file JSON blob for `filesystem`, a JSON-encoded column for `sqlite`/`postgres`);
this module only fixes the shape, not the encoding.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from src.core.exceptions import NotFoundError, VAOSError
from src.domain.entities import (
    AnalysisRun,
    AnalysisRunStatus,
    Finding,
    FindingSeverity,
    RepositoryProvider,
    RepositoryStatus,
    SourceFile,
    SourceLanguage,
    SourceRepository,
)


class StorageError(VAOSError):
    """Base class for every exception explicitly raised by a concrete storage backend.

    Every `filesystem`/`sqlite`/`postgres`/`qdrant` driver raises one of the categories below --
    or a subclass of one defined in its own subpackage (e.g. `qdrant.driver.QdrantOperationError`)
    -- rather than letting a bare third-party exception (`sqlite3.Error`, `OSError`,
    `asyncpg.PostgresError`, a `qdrant_client` exception) propagate unwrapped, matching
    `core.exceptions.VAOSError`'s own role for the platform as a whole.
    """


class StorageConnectionError(StorageError):
    """Raised when a storage backend cannot establish, or loses, its underlying connection.

    Covers a `sqlite3`/`asyncpg`/Qdrant-client connection failure and, for `filesystem`, an
    unrecoverable I/O failure reading or writing its backing file(s).
    """


class StorageIntegrityError(StorageError):
    """Raised when a write would violate a storage backend's own integrity constraint.

    Raised by `add` when an entity with the same `id` (or another backend-enforced unique field,
    e.g. `SourceRepository.source_uri`) already exists.
    """


class EntityNotFoundError(NotFoundError):
    """Raised when `update` targets an entity id that does not currently exist.

    A `core.exceptions.NotFoundError` subclass rather than a `StorageError` subclass -- a missing
    entity is a `NotFoundError` regardless of which layer discovers it, matching
    `core.utils.read_yaml_file`'s own precedent of raising the shared `NotFoundError` for a
    missing resource rather than inventing a layer-specific one. `get`/`delete` do not raise this:
    per `domain.interfaces.Repository`'s own contract, `get` returns None and `delete` is a no-op
    for a missing id (mirroring `vector.base.VectorStore.delete`'s and
    `repository.base.WorkspaceManager.remove`'s own "missing is not an error" precedent) -- only
    `update`, which the Port's own docstring frames as "persist changes to an *existing* entity",
    treats a missing target as an error.
    """


def _entity_base_to_dict(entity_id: UUID, created_at: datetime, updated_at: datetime) -> dict[str, Any]:
    """Serialize the `Entity`-common fields (`id`, `created_at`, `updated_at`) shared by every
    domain entity.

    Args:
        entity_id: The entity's own `id`.
        created_at: The entity's `created_at` timestamp.
        updated_at: The entity's `updated_at` timestamp.

    Returns:
        A JSON-safe dict with `id` as a string and both timestamps as ISO-8601 strings.
    """
    return {
        "id": str(entity_id),
        "created_at": created_at.isoformat(),
        "updated_at": updated_at.isoformat(),
    }


def _optional_datetime_to_str(value: datetime | None) -> str | None:
    """Serialize an optional `datetime` to an ISO-8601 string, passing `None` through.

    Args:
        value: The timestamp to serialize, or None.

    Returns:
        The ISO-8601 string, or None if `value` was None.
    """
    return value.isoformat() if value is not None else None


def _optional_str_to_datetime(value: str | None) -> datetime | None:
    """Deserialize an optional ISO-8601 string back into a `datetime`, passing `None` through.

    Args:
        value: The ISO-8601 string to parse, or None.

    Returns:
        The parsed `datetime`, or None if `value` was None.
    """
    return datetime.fromisoformat(value) if value is not None else None


def source_repository_to_dict(entity: SourceRepository) -> dict[str, Any]:
    """Serialize a `SourceRepository` into a deterministic, JSON-safe dict.

    Args:
        entity: The repository to serialize.

    Returns:
        A dict with every field JSON-safe: `provider`/`status` as strings, `metadata` as a plain
        dict, everything else as in `_entity_base_to_dict`.
    """
    return {
        **_entity_base_to_dict(entity.id, entity.created_at, entity.updated_at),
        "name": entity.name,
        "source_uri": entity.source_uri,
        "provider": str(entity.provider),
        "default_branch": entity.default_branch,
        "status": str(entity.status),
        "metadata": dict(entity.metadata),
    }


def source_repository_from_dict(data: dict[str, Any]) -> SourceRepository:
    """Reconstruct a `SourceRepository` from a dict produced by `source_repository_to_dict`.

    Args:
        data: A dict in the shape `source_repository_to_dict` produces.

    Returns:
        The reconstructed `SourceRepository`.

    Raises:
        ValidationError: If a reconstructed field violates `SourceRepository`'s own invariants
            (see `SourceRepository.__post_init__`) -- a defensive guard against corrupted stored
            data, not expected in ordinary round-tripping.
    """
    return SourceRepository(
        id=UUID(data["id"]),
        created_at=datetime.fromisoformat(data["created_at"]),
        updated_at=datetime.fromisoformat(data["updated_at"]),
        name=data["name"],
        source_uri=data["source_uri"],
        provider=RepositoryProvider(data["provider"]),
        default_branch=data["default_branch"],
        status=RepositoryStatus(data["status"]),
        metadata=dict(data["metadata"]),
    )


def source_file_to_dict(entity: SourceFile) -> dict[str, Any]:
    """Serialize a `SourceFile` into a deterministic, JSON-safe dict.

    Args:
        entity: The file to serialize.

    Returns:
        A dict with every field JSON-safe: `repository_id` as a string, `language` as a string,
        `metadata` as a plain dict, everything else as in `_entity_base_to_dict`.
    """
    return {
        **_entity_base_to_dict(entity.id, entity.created_at, entity.updated_at),
        "repository_id": str(entity.repository_id),
        "relative_path": entity.relative_path,
        "language": str(entity.language),
        "size_bytes": entity.size_bytes,
        "metadata": dict(entity.metadata),
    }


def source_file_from_dict(data: dict[str, Any]) -> SourceFile:
    """Reconstruct a `SourceFile` from a dict produced by `source_file_to_dict`.

    Args:
        data: A dict in the shape `source_file_to_dict` produces.

    Returns:
        The reconstructed `SourceFile`.

    Raises:
        ValidationError: If a reconstructed field violates `SourceFile`'s own invariants (see
            `SourceFile.__post_init__`).
    """
    return SourceFile(
        id=UUID(data["id"]),
        created_at=datetime.fromisoformat(data["created_at"]),
        updated_at=datetime.fromisoformat(data["updated_at"]),
        repository_id=UUID(data["repository_id"]),
        relative_path=data["relative_path"],
        language=SourceLanguage(data["language"]),
        size_bytes=data["size_bytes"],
        metadata=dict(data["metadata"]),
    )


def analysis_run_to_dict(entity: AnalysisRun) -> dict[str, Any]:
    """Serialize an `AnalysisRun` into a deterministic, JSON-safe dict.

    Args:
        entity: The analysis run to serialize.

    Returns:
        A dict with every field JSON-safe: `repository_id` as a string, `status` as a string,
        `started_at`/`completed_at` as optional ISO-8601 strings, everything else as in
        `_entity_base_to_dict`.
    """
    return {
        **_entity_base_to_dict(entity.id, entity.created_at, entity.updated_at),
        "repository_id": str(entity.repository_id),
        "status": str(entity.status),
        "started_at": _optional_datetime_to_str(entity.started_at),
        "completed_at": _optional_datetime_to_str(entity.completed_at),
        "error_message": entity.error_message,
    }


def analysis_run_from_dict(data: dict[str, Any]) -> AnalysisRun:
    """Reconstruct an `AnalysisRun` from a dict produced by `analysis_run_to_dict`.

    Args:
        data: A dict in the shape `analysis_run_to_dict` produces.

    Returns:
        The reconstructed `AnalysisRun`.
    """
    return AnalysisRun(
        id=UUID(data["id"]),
        created_at=datetime.fromisoformat(data["created_at"]),
        updated_at=datetime.fromisoformat(data["updated_at"]),
        repository_id=UUID(data["repository_id"]),
        status=AnalysisRunStatus(data["status"]),
        started_at=_optional_str_to_datetime(data["started_at"]),
        completed_at=_optional_str_to_datetime(data["completed_at"]),
        error_message=data["error_message"],
    )


def finding_to_dict(entity: Finding) -> dict[str, Any]:
    """Serialize a `Finding` into a deterministic, JSON-safe dict.

    Args:
        entity: The finding to serialize.

    Returns:
        A dict with every field JSON-safe: `analysis_run_id` as a string, `source_file_id` as an
        optional string, `severity` as a string, `metadata` as a plain dict, everything else as
        in `_entity_base_to_dict`.
    """
    return {
        **_entity_base_to_dict(entity.id, entity.created_at, entity.updated_at),
        "analysis_run_id": str(entity.analysis_run_id),
        "category": entity.category,
        "message": entity.message,
        "source_file_id": str(entity.source_file_id) if entity.source_file_id is not None else None,
        "severity": str(entity.severity),
        "score": entity.score,
        "metadata": dict(entity.metadata),
    }


def finding_from_dict(data: dict[str, Any]) -> Finding:
    """Reconstruct a `Finding` from a dict produced by `finding_to_dict`.

    Args:
        data: A dict in the shape `finding_to_dict` produces.

    Returns:
        The reconstructed `Finding`.
    """
    source_file_id = data["source_file_id"]
    return Finding(
        id=UUID(data["id"]),
        created_at=datetime.fromisoformat(data["created_at"]),
        updated_at=datetime.fromisoformat(data["updated_at"]),
        analysis_run_id=UUID(data["analysis_run_id"]),
        category=data["category"],
        message=data["message"],
        source_file_id=UUID(source_file_id) if source_file_id is not None else None,
        severity=FindingSeverity(data["severity"]),
        score=data["score"],
        metadata=dict(data["metadata"]),
    )
