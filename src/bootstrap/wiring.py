"""Construct concrete Ports from `AppConfig` and assemble them into a runnable flow.

This module reads `core.config.AppConfig`, selects and constructs the concrete lower-layer Port
implementations a configured analysis flow needs, wraps the ones this layer's own default flow
uses into `Step`s via `pipeline.steps.CallableStep`/`MapStep`, and calls
`application.build_pipeline`/`application.run_flow` -- never `Pipeline.run` directly. See this
package's own `__init__.py` for the fuller architectural picture (relationship to `application`,
the lifecycle decision, and the dependency-boundary rules this module observes).

**Scope of the default flow.** `build_application`'s own default `Step` sequence is deliberately
narrow: collect `SourceRepository` entities from one configured `source`, then persist each one
via the configured storage backend's `SourceRepositoryStore`. It does not clone a repository's
contents onto disk, walk its files, parse anything, extract anything, analyze anything, build a
graph, or make a Foundation decision -- each of those pulls in a genuine business choice (which
of five parser languages, which of seven extractor concerns, which of eight analyzer categories,
in what order) that nothing in the frozen architecture specifies, and inventing one would be
exactly the "business logic belonging to lower layers" this phase's own brief forbids. What this
module *does* construct beyond the default flow's own needs -- `build_repository_client`,
`build_workspace_manager` -- are exposed as independently callable, independently tested
functions so a caller assembling a richer flow via `build_application`'s `extra_steps` can wire
repository access the same way this module wires collection/storage, without this module forcing
a specific choice of what that richer flow should be.

**Storage resource cleanup.** `storage.sqlite.driver`/`storage.postgres.driver` each keep opening
a connection separate from every store's own `__init__` and document that closing it is "the
caller's own responsibility" (see each driver's own module docstring). `_CallbackCloser` is the
minimal adapter that lets this module hand that responsibility to `pipeline.pipeline.Pipeline`'s
own already-existing, already-frozen per-run resource release, instead of building a second
lifecycle mechanism -- see this package's `__init__.py` for why no `start`/`stop` pair or
`core.protocols.SupportsLifecycle` implementation exists anywhere in this module.
"""

from __future__ import annotations

import functools
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from qdrant_client import AsyncQdrantClient

from src.application.runner import build_pipeline as _application_build_pipeline
from src.application.runner import run_flow as _application_run_flow
from src.collectors.base import CollectionResult, Collector
from src.collectors.filesystem import FilesystemCollector
from src.collectors.github import GitHubCollector
from src.collectors.gitlab import GitLabCollector
from src.collectors.local import LocalCollector
from src.core.config import AppConfig, load_config
from src.core.protocols import SupportsAsyncClose
from src.core.utils import ensure_directory
from src.domain.entities import AnalysisRunStatus, SourceRepository
from src.domain.interfaces import (
    AnalysisArtifactStore,
    AnalysisRunRepository,
    FindingRepository,
    SourceFileRepository,
    SourceRepositoryStore,
)
from src.memory.base import MemoryStore
from src.pipeline.base import PipelineResult, Step
from src.pipeline.context import PipelineContext
from src.pipeline.pipeline import Pipeline
from src.pipeline.steps import CallableStep, MapStep
from src.repository.git import GitRepositoryClient
from src.repository.workspace import FilesystemWorkspaceManager
from src.storage.filesystem.driver import (
    FilesystemAnalysisArtifactStore,
    FilesystemAnalysisRunRepository,
    FilesystemFindingRepository,
    FilesystemSourceFileRepository,
    FilesystemSourceRepositoryStore,
)
from src.storage.filesystem.memory import FilesystemMemoryStore
from src.storage.postgres.driver import (
    PostgresAnalysisArtifactStore,
    PostgresAnalysisRunRepository,
    PostgresFindingRepository,
    PostgresSourceFileRepository,
    PostgresSourceRepositoryStore,
)
from src.storage.postgres.driver import close_connection as _postgres_close_connection
from src.storage.postgres.driver import connect as _postgres_connect
from src.storage.postgres.driver import initialize_schema as _postgres_initialize_schema
from src.storage.postgres.memory import PostgresMemoryStore
from src.storage.qdrant.driver import QdrantVectorStore
from src.storage.sqlite.driver import (
    SqliteAnalysisArtifactStore,
    SqliteAnalysisRunRepository,
    SqliteFindingRepository,
    SqliteSourceFileRepository,
    SqliteSourceRepositoryStore,
)
from src.storage.sqlite.driver import close_connection as _sqlite_close_connection
from src.storage.sqlite.driver import initialize_schema as _sqlite_initialize_schema
from src.storage.sqlite.driver import open_connection as _sqlite_open_connection
from src.storage.sqlite.memory import SqliteMemoryStore
from src.vector.base import VectorStore

from .errors import BootstrapError
from .memory_steps import build_memory_aware_step

#: Default `storage.backend` when configuration does not specify one.
_DEFAULT_STORAGE_BACKEND = "filesystem"
#: Default `storage.filesystem.root` when configuration does not specify one.
_DEFAULT_STORAGE_FILESYSTEM_ROOT = "data/storage"
#: Default `storage.sqlite.path` when configuration does not specify one.
_DEFAULT_STORAGE_SQLITE_PATH = "data/vaos.db"
#: Default `collectors.backend` when configuration does not specify one.
_DEFAULT_COLLECTOR_BACKEND = "filesystem"
#: Default `collectors.source` when configuration does not specify one.
_DEFAULT_COLLECTOR_SOURCE = "."
#: Default `repository.workspace_root` when configuration does not specify one.
_DEFAULT_REPOSITORY_WORKSPACE_ROOT = "data/workspaces"
#: Default `repository.git_executable` when configuration does not specify one.
_DEFAULT_GIT_EXECUTABLE = "git"
#: Default `repository.timeout_seconds` when configuration does not specify one.
_DEFAULT_REPOSITORY_TIMEOUT_SECONDS = 300.0
#: Default `vector.qdrant.collection_name` when configuration does not specify one.
_DEFAULT_VECTOR_COLLECTION = "vaos"
#: Default `vector.qdrant.vector_size` when configuration does not specify one.
_DEFAULT_VECTOR_SIZE = 384
#: Name given to every `Pipeline` this module assembles.
_PIPELINE_NAME = "bootstrap_default_flow"


class _CallbackCloser:
    """Adapts a zero-argument async close callback into `core.protocols.SupportsAsyncClose`.

    Bridges an already-existing, backend-specific close function -- `close_connection`,
    `close_pool` -- which takes the connection as an argument, not `SupportsAsyncClose`'s own
    no-argument `aclose(self)` shape, into `pipeline.pipeline.Pipeline`'s existing per-run
    resource-release mechanism. See this module's own docstring for why this is the only
    resource-lifecycle machinery this layer introduces.
    """

    def __init__(self, close: Callable[[], Awaitable[None]]) -> None:
        """Initialize the adapter.

        Args:
            close: A zero-argument callable that releases the wrapped resource when awaited --
                typically `functools.partial` over a driver's own close function, bound to one
                specific connection.
        """
        self._close = close

    async def aclose(self) -> None:
        """Release the wrapped resource by calling the bound close callback."""
        await self._close()


_ANALYSIS_RUN_STALE_AFTER = timedelta(hours=1)


async def _recover_interrupted_analysis_runs(store: AnalysisRunRepository) -> int:
    """Fail runs left active for more than one hour by a prior process."""
    cutoff = datetime.now(UTC) - _ANALYSIS_RUN_STALE_AFTER
    recovered = 0
    for run in await store.list():
        if (
            run.status is AnalysisRunStatus.RUNNING
            and run.started_at is not None
            and run.started_at < cutoff
        ):
            run.fail("Analysis process stopped before the run reached a terminal state")
            await store.update(run)
            recovered += 1
    return recovered


class _AnalysisRunFailureGuard(Step):
    """Mark active analysis runs as failed when a wrapped step raises."""

    def __init__(self, step: Step, store: AnalysisRunRepository) -> None:
        self._step = step
        self._store = store

    @property
    def name(self) -> str:
        return self._step.name

    async def execute(self, context: PipelineContext) -> PipelineContext:
        try:
            return await self._step.execute(context)
        except Exception as exc:
            run_ids = context.get("analysis_run_ids", {})
            for run_id in run_ids.values():
                run = await self._store.get(run_id)
                if run is not None and run.status.value in ("pending", "running"):
                    run.fail(f"{self._step.name}: {exc}")
                    await self._store.update(run)
            raise


@dataclass(frozen=True, slots=True)
class StorageBundle:
    """The concrete persistence Ports for one configured storage backend.

    Attributes:
        source_repository_store: Concrete `SourceRepositoryStore` for the selected backend.
        source_file_repository: Concrete `SourceFileRepository` for the selected backend.
        analysis_run_repository: Concrete `AnalysisRunRepository` for the selected backend.
        finding_repository: Concrete `FindingRepository` for the selected backend.
        analysis_artifact_store: Concrete `AnalysisArtifactStore` for the selected backend.
        memory_store: Concrete `MemoryStore` for the selected backend.
        resource: A `SupportsAsyncClose` adapter for the backend's own backing connection, or
            None for a backend (`"filesystem"`) with no connection to release.
    """

    source_repository_store: SourceRepositoryStore
    source_file_repository: SourceFileRepository
    analysis_run_repository: AnalysisRunRepository
    finding_repository: FindingRepository
    analysis_artifact_store: AnalysisArtifactStore
    memory_store: MemoryStore
    resource: SupportsAsyncClose | None


def build_repository_client(config: AppConfig) -> GitRepositoryClient:
    """Construct the concrete `RepositoryClient` for `config`.

    Args:
        config: Resolved application configuration. Reads `repository.git_executable` (default
            `"git"`) and `repository.timeout_seconds` (default 300.0).

    Returns:
        A `GitRepositoryClient` invoking the configured `git` executable. Performs no I/O
        itself; `git` is only ever invoked by a later `.clone()` call.
    """
    git_executable = str(config.get("repository.git_executable", _DEFAULT_GIT_EXECUTABLE))
    timeout_seconds = float(
        config.get("repository.timeout_seconds", _DEFAULT_REPOSITORY_TIMEOUT_SECONDS)
    )
    return GitRepositoryClient(git_executable, timeout_seconds=timeout_seconds)


def build_workspace_manager(config: AppConfig) -> FilesystemWorkspaceManager:
    """Construct the concrete `WorkspaceManager` for `config`.

    Args:
        config: Resolved application configuration. Reads `repository.workspace_root` (default
            `"data/workspaces"`).

    Returns:
        A `FilesystemWorkspaceManager` rooted at the configured directory, created if it does
        not already exist -- the same local, synchronous side effect
        `FilesystemWorkspaceManager.__init__` itself already performs.
    """
    root = Path(str(config.get("repository.workspace_root", _DEFAULT_REPOSITORY_WORKSPACE_ROOT)))
    return FilesystemWorkspaceManager(root)


def build_collector(config: AppConfig) -> Collector:
    """Construct the concrete `Collector` for `config`.

    Args:
        config: Resolved application configuration. Reads `collectors.backend` (default
            `"filesystem"`; one of `"filesystem"`, `"local"`, `"github"`, `"gitlab"`) and, only
            for `"local"`, `collectors.local.max_depth`.

    Returns:
        The concrete `Collector` matching the configured backend.

    Raises:
        BootstrapError: If `collectors.backend` is not a recognized value.
    """
    backend = str(config.get("collectors.backend", _DEFAULT_COLLECTOR_BACKEND))
    if backend == "filesystem":
        return FilesystemCollector()
    if backend == "local":
        max_depth = config.get("collectors.local.max_depth")
        return LocalCollector() if max_depth is None else LocalCollector(max_depth=int(max_depth))
    if backend == "github":
        return GitHubCollector()
    if backend == "gitlab":
        return GitLabCollector()
    raise BootstrapError(
        f"unknown collectors.backend '{backend}'; expected one of "
        "'filesystem', 'local', 'github', 'gitlab'",
        details={"backend": backend},
    )


async def build_storage(config: AppConfig) -> StorageBundle:
    """Construct the concrete `Storage` Ports for `config`.

    Performs whichever backend-specific connect/initialize-schema sequence the selected backend
    requires, then constructs the five `Repository` Ports around the resulting connection (or,
    for `"filesystem"`, around the configured root directory directly). See
    `storage.sqlite.driver`/`storage.postgres.driver`'s own module docstrings for why this
    sequence is kept separate from each store's own `__init__`.

    Args:
        config: Resolved application configuration. Reads `storage.backend` (default
            `"filesystem"`; one of `"filesystem"`, `"sqlite"`, `"postgres"`) and, depending on
            the backend selected, `storage.filesystem.root` (default `"data/storage"`),
            `storage.sqlite.path` (default `"data/vaos.db"`), or `storage.postgres.dsn`
            (required, no default).

    Returns:
        A `StorageBundle` holding the concrete Ports and, for `"sqlite"`/`"postgres"`, a
        `SupportsAsyncClose` resource wrapping the backing connection.

    Raises:
        BootstrapError: If `storage.backend` is not a recognized value, or if `"postgres"` is
            selected without `storage.postgres.dsn` configured.
        StorageConnectionError: If the selected backend's own connection cannot be opened.
    """
    backend = str(config.get("storage.backend", _DEFAULT_STORAGE_BACKEND))

    if backend == "filesystem":
        root = Path(str(config.get("storage.filesystem.root", _DEFAULT_STORAGE_FILESYSTEM_ROOT)))
        ensure_directory(root)
        return StorageBundle(
            source_repository_store=FilesystemSourceRepositoryStore(root),
            source_file_repository=FilesystemSourceFileRepository(root),
            analysis_run_repository=FilesystemAnalysisRunRepository(root),
            finding_repository=FilesystemFindingRepository(root),
            analysis_artifact_store=FilesystemAnalysisArtifactStore(root),
            memory_store=FilesystemMemoryStore(root),
            resource=None,
        )

    if backend == "sqlite":
        path = str(config.get("storage.sqlite.path", _DEFAULT_STORAGE_SQLITE_PATH))
        ensure_directory(Path(path).parent)
        sqlite_connection = _sqlite_open_connection(path)
        await _sqlite_initialize_schema(sqlite_connection)
        return StorageBundle(
            source_repository_store=SqliteSourceRepositoryStore(sqlite_connection),
            source_file_repository=SqliteSourceFileRepository(sqlite_connection),
            analysis_run_repository=SqliteAnalysisRunRepository(sqlite_connection),
            finding_repository=SqliteFindingRepository(sqlite_connection),
            analysis_artifact_store=SqliteAnalysisArtifactStore(sqlite_connection),
            memory_store=SqliteMemoryStore(sqlite_connection),
            resource=_CallbackCloser(
                functools.partial(_sqlite_close_connection, sqlite_connection)
            ),
        )

    if backend == "postgres":
        dsn = config.get("storage.postgres.dsn")
        if not dsn:
            raise BootstrapError(
                "storage.backend is 'postgres' but 'storage.postgres.dsn' is not configured",
                details={"backend": backend},
            )
        postgres_connection = await _postgres_connect(str(dsn))
        await _postgres_initialize_schema(postgres_connection)
        return StorageBundle(
            source_repository_store=PostgresSourceRepositoryStore(postgres_connection),
            source_file_repository=PostgresSourceFileRepository(postgres_connection),
            analysis_run_repository=PostgresAnalysisRunRepository(postgres_connection),
            finding_repository=PostgresFindingRepository(postgres_connection),
            analysis_artifact_store=PostgresAnalysisArtifactStore(postgres_connection),
            memory_store=PostgresMemoryStore(postgres_connection),
            resource=_CallbackCloser(
                functools.partial(_postgres_close_connection, postgres_connection)
            ),
        )

    raise BootstrapError(
        f"unknown storage.backend '{backend}'; expected one of 'filesystem', 'sqlite', 'postgres'",
        details={"backend": backend},
    )


async def build_vector_store(config: AppConfig) -> VectorStore | None:
    """Construct the concrete `VectorStore` for `config`, if vector storage is configured.

    Args:
        config: Resolved application configuration. Reads `vector.enabled` (default False) and,
            only if true, `vector.qdrant.url` (required), `vector.qdrant.collection_name`
            (default `"vaos"`), `vector.qdrant.vector_size` (default 384), and
            `vector.qdrant.api_key` (optional).

    Returns:
        A `QdrantVectorStore`, with `ensure_collection` already awaited, if `vector.enabled` is
        true; otherwise None. `QdrantVectorStore` already implements
        `core.protocols.SupportsAsyncClose` itself, so no `_CallbackCloser` adapter is needed
        here the way `build_storage`'s `"sqlite"`/`"postgres"` branches require one.

    Raises:
        BootstrapError: If `vector.enabled` is true but `vector.qdrant.url` is not configured.
        QdrantOperationError: If checking for or creating the configured collection fails.
    """
    if not bool(config.get("vector.enabled", False)):
        return None
    url = config.get("vector.qdrant.url")
    if not url:
        raise BootstrapError(
            "vector.enabled is true but 'vector.qdrant.url' is not configured",
            details={},
        )
    collection_name = str(config.get("vector.qdrant.collection_name", _DEFAULT_VECTOR_COLLECTION))
    vector_size = int(config.get("vector.qdrant.vector_size", _DEFAULT_VECTOR_SIZE))
    api_key = config.get("vector.qdrant.api_key")
    client = AsyncQdrantClient(url=str(url), api_key=str(api_key) if api_key else None)
    # FROZEN-PHASE CONFLICT (see docs/phase15_summary.md): `storage.qdrant.driver`'s own
    # `_QdrantClientLike` Protocol docstring claims "`AsyncQdrantClient` itself satisfies this
    # Protocol", but under mypy --strict, the real `AsyncQdrantClient.search`'s `query_vector`
    # parameter type (a union including `Sequence[float]`, `ndarray`, ...) is not recognized as
    # satisfying the Protocol's own, narrower `query_vector: list[float]`. This is a latent gap
    # in that frozen, Phase 10 Protocol -- never exercised there, since Phase 10 never
    # constructed a real client itself -- not a genuine runtime incompatibility: `list[float]`
    # is itself a `Sequence[float]`, so a real `AsyncQdrantClient` works correctly here. Fixing
    # the root cause means widening `_QdrantClientLike.search`'s parameter type in that frozen
    # file, which this phase's own brief forbids modifying; this `type: ignore` is scoped to
    # this one, evidence-verified-safe construction site rather than left unaddressed.
    store = QdrantVectorStore(
        client,  # type: ignore[arg-type]
        collection_name=collection_name,
        vector_size=vector_size,
    )
    await store.ensure_collection()
    return store


def _unpack_repositories(result: CollectionResult) -> tuple[SourceRepository, ...]:
    """Translate a `CollectionResult`'s own "failure reported as data" outcome into a raised
    exception, matching `pipeline`'s "failure reported by raising" convention.

    Args:
        result: The outcome of the one `Collector.collect` call this layer's own default flow
            makes.

    Returns:
        `result.repositories`, unchanged, if `result.succeeded` is True.

    Raises:
        BootstrapError: If `result.succeeded` is False.
    """
    if not result.succeeded:
        raise BootstrapError(
            f"collection failed for source '{result.source}': {result.error_message}",
            details={"source": result.source},
        )
    return result.repositories


def _persist_repository_func(
    store: SourceRepositoryStore,
) -> Callable[[SourceRepository], Awaitable[UUID]]:
    """Bind `store` into a single-item callable suitable for `MapStep`.

    Args:
        store: The already-constructed `SourceRepositoryStore` each mapped item is persisted
            to.

    Returns:
        An async callable that persists one `SourceRepository` and returns its `id`, matching
        `pipeline.steps.MapStep`'s "func is supplied already bound" contract.
    """

    async def _persist(entity: SourceRepository) -> UUID:
        await store.add(entity)
        return entity.id

    return _persist


async def build_application(
    config: AppConfig | None = None,
    *,
    memory_store: MemoryStore | None = None,
    extra_steps: Sequence[Step] = (),
    persist_analysis_artifacts: bool = False,
) -> Pipeline:
    """Construct every concrete Port this layer's default flow needs and assemble a `Pipeline`.

    Constructs a `Collector` and a storage backend from `config`, wraps them into `Step`s
    (`collect`, `unpack_repositories`, `persist_repositories`), appends `extra_steps`, and calls
    `application.build_pipeline` with every closeable resource (the storage connection, if any;
    a configured `VectorStore`; `memory_store`, if supplied) so `Pipeline.run`'s own existing
    per-run release mechanism -- not a mechanism this layer introduces -- closes them. Never
    calls `Pipeline.run` itself; see `bootstrap` for that.

    Args:
        config: Resolved application configuration. Defaults to `core.config.load_config()`.
        memory_store: An already-constructed `MemoryStore`, if the caller has one. This layer
            never constructs a concrete `MemoryStore` itself -- see this package's own
            `__init__.py` for why. Passed straight into the assembled `Pipeline`'s `resources`.
        extra_steps: Additional `Step`s appended, in order, after this layer's own three
            default steps.
        persist_analysis_artifacts: If True, create one `AnalysisRun` per collected repository
            before `extra_steps`, then persist their analyzer outputs and mark successful runs
            completed after `extra_steps`. Requires the analysis steps to write all eight result
            groups to the pipeline context. Defaults to False.

    Returns:
        A `Pipeline` ready to run against a `PipelineContext` seeded with `"source"` -- see
        `bootstrap`, which does exactly that.

    Raises:
        BootstrapError: If a configured backend name is not recognized, or a backend's own
            required configuration is missing.
        StorageConnectionError: If the selected storage backend's connection cannot be opened.
        QdrantOperationError: If vector storage is configured but its collection cannot be
            ensured.
        ValidationError: If `Pipeline.__init__`'s own validation fails (e.g. a duplicate step
            name introduced via `extra_steps`).
    """
    resolved_config = config if config is not None else load_config()

    collector = build_collector(resolved_config)
    storage = await build_storage(resolved_config)
    if persist_analysis_artifacts:
        await _recover_interrupted_analysis_runs(storage.analysis_run_repository)
    vector_store = await build_vector_store(resolved_config)

    collect_step: Step = CallableStep(
        "collect",
        collector.collect,
        input_keys=("source",),
        output_key="collection_result",
        is_async=True,
    )
    unpack_step: Step = CallableStep(
        "unpack_repositories",
        _unpack_repositories,
        input_keys=("collection_result",),
        output_key="repositories",
    )
    persist_step: Step = MapStep(
        "persist_repositories",
        _persist_repository_func(storage.source_repository_store),
        input_key="repositories",
        output_key="persisted_repository_ids",
        is_async=True,
    )
    selected_memory_store = memory_store if memory_store is not None else storage.memory_store
    selected_analysis_steps = list(extra_steps)
    if selected_analysis_steps:
        selected_analysis_steps[0] = build_memory_aware_step(
            selected_analysis_steps[0], selected_memory_store
        )

    steps: list[Step] = [collect_step, unpack_step, persist_step]
    if persist_analysis_artifacts:
        from src.bootstrap.analysis_steps import (
            build_analysis_artifact_persistence_step,
            build_analysis_run_creation_step,
        )

        steps.append(build_analysis_run_creation_step(storage.analysis_run_repository))
    if persist_analysis_artifacts:
        steps.extend(
            _AnalysisRunFailureGuard(step, storage.analysis_run_repository)
            for step in selected_analysis_steps
        )
        steps.append(
            _AnalysisRunFailureGuard(
                build_analysis_artifact_persistence_step(
                    storage.analysis_artifact_store, storage.analysis_run_repository
                ),
                storage.analysis_run_repository,
            )
        )
    else:
        steps.extend(selected_analysis_steps)

    resources: list[SupportsAsyncClose] = []
    if storage.resource is not None:
        resources.append(storage.resource)
    if vector_store is not None:
        resources.append(vector_store)
    resources.append(selected_memory_store)

    return _application_build_pipeline(_PIPELINE_NAME, steps, resources=resources)


async def bootstrap(
    config: AppConfig | None = None,
    *,
    memory_store: MemoryStore | None = None,
    extra_steps: Sequence[Step] = (),
    persist_analysis_artifacts: bool = False,
    context: PipelineContext | None = None,
) -> PipelineResult:
    """Construct and run one complete, `bootstrap`-composed analysis flow.

    Calls `build_application` to construct every concrete Port `config` selects and assemble
    them into a `Pipeline`, then `application.run_flow` to execute it -- this layer never calls
    `Pipeline.run` directly.

    Args:
        config: Resolved application configuration. Defaults to `core.config.load_config()`.
        memory_store: An already-constructed `MemoryStore`, if the caller has one. Passed
            through to `build_application` unchanged.
        extra_steps: Additional `Step`s appended after this layer's own default steps. Passed
            through to `build_application` unchanged.
        persist_analysis_artifacts: Passed to `build_application`; creates and completes analysis
            runs and persists analyzer results when enabled. The supplied `extra_steps` must
            populate the analysis result context keys. Defaults to False.
        context: Initial `PipelineContext` the assembled `Pipeline` runs against. Defaults to a
            fresh `PipelineContext` seeded with `"source"`, read from `collectors.source`
            (default `"."`) -- the one value the default flow's `collect` step requires.

    Returns:
        The `PipelineResult` `application.run_flow` returns.

    Raises:
        BootstrapError: See `build_application`.
        StepExecutionError: If any step of the assembled `Pipeline` raises while running (see
            `application.run_flow`/`pipeline.pipeline.Pipeline.run`).
    """
    resolved_config = config if config is not None else load_config()
    pipeline = await build_application(
        resolved_config,
        memory_store=memory_store,
        extra_steps=extra_steps,
        persist_analysis_artifacts=persist_analysis_artifacts,
    )
    resolved_context = (
        context
        if context is not None
        else PipelineContext(
            values={
                "source": str(resolved_config.get("collectors.source", _DEFAULT_COLLECTOR_SOURCE))
            }
        )
    )
    return await _application_run_flow(pipeline, resolved_context)
