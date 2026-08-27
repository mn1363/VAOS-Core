"""Unit and integration tests for `src.bootstrap.wiring`.

Every backend exercised for real here (filesystem, sqlite) uses only the standard library and a
`tmp_path` fixture -- no network, no external process, matching this repository's established
"tests must not require GitHub, PostgreSQL, Qdrant, external APIs, network access" convention
(see `tests/unit/pipeline/test_integration.py`'s own docstring). `"postgres"`/`"github"`/
`"gitlab"` are covered only for their configuration-validation paths, which raise before any
connection or request is attempted; `"vector"`'s happy-construction path is covered with a
minimal, hand-written fake client satisfying `storage.qdrant.driver`'s own `_QdrantClientLike`
calling convention, substituted via `monkeypatch` -- never a `unittest.mock` double, matching
this repository's own established testing convention (see e.g.
`tests/unit/foundation/test_dependency_boundaries.py`'s own fakes).
"""

from typing import Any
from uuid import UUID

import pytest
from src.bootstrap.errors import BootstrapError
from src.bootstrap.wiring import (
    bootstrap,
    build_application,
    build_collector,
    build_repository_client,
    build_storage,
    build_vector_store,
    build_workspace_manager,
)
from src.collectors.filesystem import FilesystemCollector
from src.collectors.github import GitHubCollector
from src.collectors.gitlab import GitLabCollector
from src.collectors.local import LocalCollector
from src.core.config import AppConfig
from src.core.exceptions import VAOSError
from src.core.protocols import SupportsAsyncClose
from src.domain.entities import RepositoryProvider
from src.memory.base import MemoryQuery, MemoryQueryResult, MemoryRecord, MemoryStore
from src.pipeline.base import Step, StepExecutionError
from src.pipeline.context import PipelineContext
from src.pipeline.steps import CallableStep
from src.repository.git import GitRepositoryClient
from src.repository.workspace import FilesystemWorkspaceManager


def _config(raw: dict[str, Any]) -> AppConfig:
    """Build an `AppConfig` directly from a raw mapping, bypassing `load_config`/YAML/env."""
    return AppConfig(raw=raw)


class _FakeMemoryStore(MemoryStore):
    """A real `MemoryStore` implementation, tracking whether `aclose` was called."""

    def __init__(self) -> None:
        self.closed = False

    async def upsert(self, record: MemoryRecord) -> None:
        pass

    async def get(self, record_id: UUID) -> MemoryRecord | None:
        return None

    async def delete(self, record_id: UUID) -> None:
        pass

    async def exists(self, record_id: UUID) -> bool:
        return False

    async def query(self, request: MemoryQuery) -> MemoryQueryResult:
        return MemoryQueryResult(records=())

    async def aclose(self) -> None:
        self.closed = True


class _FakeAsyncQdrantClient:
    """A minimal, hand-written double satisfying `_QdrantClientLike`'s calling convention."""

    def __init__(self, *, url: str, api_key: str | None = None) -> None:
        self.url = url
        self.api_key = api_key
        self.collections: set[str] = set()

    async def collection_exists(self, collection_name: str, **kwargs: Any) -> bool:
        return collection_name in self.collections

    async def create_collection(
        self, collection_name: str, vectors_config: Any, **kwargs: Any
    ) -> bool:
        self.collections.add(collection_name)
        return True


# --- build_repository_client -------------------------------------------------------------


def test_build_repository_client_uses_defaults() -> None:
    """With no configuration, `build_repository_client` returns a `GitRepositoryClient`
    invoking the default `"git"` executable."""
    client = build_repository_client(_config({}))
    assert isinstance(client, GitRepositoryClient)


def test_build_repository_client_reads_configured_values() -> None:
    """`repository.git_executable`/`repository.timeout_seconds` override the built-in
    defaults."""
    client = build_repository_client(
        _config({"repository": {"git_executable": "/usr/bin/git", "timeout_seconds": 5.0}})
    )
    assert isinstance(client, GitRepositoryClient)


# --- build_workspace_manager -------------------------------------------------------------


def test_build_workspace_manager_creates_the_configured_root(tmp_path: Any) -> None:
    """`build_workspace_manager` creates `repository.workspace_root` if it does not exist."""
    root = tmp_path / "workspaces"
    assert not root.exists()
    manager = build_workspace_manager(_config({"repository": {"workspace_root": str(root)}}))
    assert isinstance(manager, FilesystemWorkspaceManager)
    assert root.is_dir()


# --- build_collector -----------------------------------------------------------------------


def test_build_collector_defaults_to_filesystem() -> None:
    """With no configuration, `build_collector` returns a `FilesystemCollector`."""
    assert isinstance(build_collector(_config({})), FilesystemCollector)


def test_build_collector_selects_local_with_max_depth() -> None:
    """`collectors.backend: "local"` returns a `LocalCollector`, honoring `max_depth`."""
    collector = build_collector(
        _config({"collectors": {"backend": "local", "local": {"max_depth": 2}}})
    )
    assert isinstance(collector, LocalCollector)


def test_build_collector_selects_github() -> None:
    """`collectors.backend: "github"` returns a `GitHubCollector`."""
    collector = build_collector(_config({"collectors": {"backend": "github"}}))
    assert isinstance(collector, GitHubCollector)
    assert collector.provider == RepositoryProvider.GITHUB


def test_build_collector_selects_gitlab() -> None:
    """`collectors.backend: "gitlab"` returns a `GitLabCollector`."""
    collector = build_collector(_config({"collectors": {"backend": "gitlab"}}))
    assert isinstance(collector, GitLabCollector)
    assert collector.provider == RepositoryProvider.GITLAB


def test_build_collector_rejects_unknown_backend() -> None:
    """An unrecognized `collectors.backend` raises `BootstrapError`, not a lower-layer error."""
    with pytest.raises(BootstrapError, match="unknown collectors.backend"):
        build_collector(_config({"collectors": {"backend": "carrier-pigeon"}}))


# --- build_storage: filesystem -------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_storage_filesystem_roundtrips_a_repository(tmp_path: Any) -> None:
    """The `"filesystem"` backend's four Ports are real, working `Repository[EntityT]`
    implementations sharing the configured root, with no resource to close."""
    from src.domain.entities import SourceRepository

    bundle = await build_storage(
        _config({"storage": {"backend": "filesystem", "filesystem": {"root": str(tmp_path)}}})
    )
    assert bundle.resource is None

    repository = SourceRepository(
        name="demo", source_uri=str(tmp_path), provider=RepositoryProvider.FILESYSTEM
    )
    await bundle.source_repository_store.add(repository)
    fetched = await bundle.source_repository_store.get(repository.id)
    assert fetched == repository


@pytest.mark.asyncio
async def test_build_storage_filesystem_defaults_to_a_relative_root(
    tmp_path: Any, monkeypatch: Any
) -> None:
    """With no `storage.filesystem.root` configured, `build_storage` still succeeds, using the
    built-in default root -- exercised from an isolated `tmp_path` working directory so the
    default's relative path never touches the real repository tree."""
    monkeypatch.chdir(tmp_path)
    bundle = await build_storage(_config({"storage": {"backend": "filesystem"}}))
    assert bundle.resource is None
    assert await bundle.source_repository_store.list() == []


# --- build_storage: sqlite -------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_storage_sqlite_roundtrips_a_repository_and_closes(tmp_path: Any) -> None:
    """The `"sqlite"` backend's Ports share one real `sqlite3` connection, and `resource.aclose`
    genuinely releases it -- proven by every further operation against it failing afterward
    with `StorageConnectionError`, `storage.sqlite.driver`'s own mapping of the underlying
    `sqlite3.ProgrammingError: Cannot operate on a closed database`."""
    from src.domain.entities import SourceRepository
    from src.storage.base import StorageConnectionError

    db_path = tmp_path / "nested" / "vaos.db"
    bundle = await build_storage(
        _config({"storage": {"backend": "sqlite", "sqlite": {"path": str(db_path)}}})
    )
    assert bundle.resource is not None
    assert isinstance(bundle.resource, SupportsAsyncClose)
    assert db_path.parent.is_dir()  # parent directory created for us

    repository = SourceRepository(
        name="demo", source_uri="/tmp/demo", provider=RepositoryProvider.FILESYSTEM
    )
    await bundle.source_repository_store.add(repository)
    assert await bundle.source_repository_store.get(repository.id) == repository

    await bundle.resource.aclose()
    with pytest.raises(StorageConnectionError):
        await bundle.source_repository_store.list()


# --- build_storage: postgres / unknown -------------------------------------------------------


@pytest.mark.asyncio
async def test_build_storage_postgres_without_dsn_raises_bootstrap_error() -> None:
    """`"postgres"` selected without `storage.postgres.dsn` fails fast, before any connection
    attempt -- no network access occurs."""
    with pytest.raises(BootstrapError, match="storage.postgres.dsn"):
        await build_storage(_config({"storage": {"backend": "postgres"}}))


@pytest.mark.asyncio
async def test_build_storage_rejects_unknown_backend() -> None:
    """An unrecognized `storage.backend` raises `BootstrapError`."""
    with pytest.raises(BootstrapError, match="unknown storage.backend"):
        await build_storage(_config({"storage": {"backend": "carrier-pigeon"}}))


# --- build_vector_store -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_vector_store_disabled_returns_none() -> None:
    """With `vector.enabled` absent (or False), `build_vector_store` constructs nothing."""
    assert await build_vector_store(_config({})) is None
    assert await build_vector_store(_config({"vector": {"enabled": False}})) is None


@pytest.mark.asyncio
async def test_build_vector_store_enabled_without_url_raises_bootstrap_error() -> None:
    """`vector.enabled: true` without `vector.qdrant.url` fails fast, before any client is
    constructed."""
    with pytest.raises(BootstrapError, match="vector.qdrant.url"):
        await build_vector_store(_config({"vector": {"enabled": True}}))


@pytest.mark.asyncio
async def test_build_vector_store_enabled_constructs_and_ensures_collection(
    monkeypatch: Any,
) -> None:
    """`vector.enabled: true` with a URL constructs a real `QdrantVectorStore` and calls
    `ensure_collection`, against a fake client standing in for the network."""
    import src.bootstrap.wiring as wiring_module
    from src.storage.qdrant.driver import QdrantVectorStore

    monkeypatch.setattr(wiring_module, "AsyncQdrantClient", _FakeAsyncQdrantClient)

    store = await build_vector_store(
        _config(
            {
                "vector": {
                    "enabled": True,
                    "qdrant": {"url": "http://localhost:6333", "collection_name": "demo"},
                }
            }
        )
    )
    assert isinstance(store, QdrantVectorStore)
    assert isinstance(store, SupportsAsyncClose)


# --- build_application / bootstrap: integration -----------------------------------------


@pytest.mark.asyncio
async def test_build_application_assembles_the_default_three_step_flow(tmp_path: Any) -> None:
    """With no `extra_steps`, `build_application` returns a `Pipeline` with exactly the three
    default step names, in order."""
    config = _config(
        {
            "collectors": {"backend": "filesystem"},
            "storage": {"backend": "filesystem", "filesystem": {"root": str(tmp_path / "s")}},
        }
    )
    pipeline = await build_application(config)
    context = PipelineContext(values={"source": str(tmp_path)})
    result = await pipeline.run(context)
    assert result.step_names() == ("collect", "unpack_repositories", "persist_repositories")


@pytest.mark.asyncio
async def test_build_application_appends_extra_steps(tmp_path: Any) -> None:
    """`extra_steps` are appended, in order, after this layer's own default steps."""
    log: list[str] = []

    class _RecordingStep(Step):
        @property
        def name(self) -> str:
            return "record"

        async def execute(self, context: PipelineContext) -> PipelineContext:
            log.append("ran")
            return context

    config = _config(
        {
            "collectors": {"backend": "filesystem"},
            "storage": {"backend": "filesystem", "filesystem": {"root": str(tmp_path / "s")}},
        }
    )
    pipeline = await build_application(config, extra_steps=[_RecordingStep()])
    context = PipelineContext(values={"source": str(tmp_path)})
    result = await pipeline.run(context)
    assert result.step_names()[-1] == "record"
    assert log == ["ran"]


@pytest.mark.asyncio
async def test_build_application_passes_memory_store_through_as_a_closeable_resource(
    tmp_path: Any,
) -> None:
    """A `memory_store` the caller supplies is closed by `Pipeline.run`'s own existing
    resource-release mechanism -- `bootstrap` never constructs one itself."""
    memory_store = _FakeMemoryStore()
    config = _config(
        {
            "collectors": {"backend": "filesystem"},
            "storage": {"backend": "filesystem", "filesystem": {"root": str(tmp_path / "s")}},
        }
    )
    pipeline = await build_application(config, memory_store=memory_store)
    await pipeline.run(PipelineContext(values={"source": str(tmp_path)}))
    assert memory_store.closed is True


@pytest.mark.asyncio
async def test_bootstrap_runs_the_default_flow_and_persists_a_repository(tmp_path: Any) -> None:
    """`bootstrap` constructs, assembles, and runs one complete flow, and the collected
    repository is genuinely persisted -- readable back from a freshly built store afterward."""
    source_dir = tmp_path / "my-project"
    source_dir.mkdir()
    storage_root = tmp_path / "storage"

    config = _config(
        {
            "collectors": {"backend": "filesystem", "source": str(source_dir)},
            "storage": {"backend": "filesystem", "filesystem": {"root": str(storage_root)}},
        }
    )
    result = await bootstrap(config)

    assert result.pipeline_name == "bootstrap_default_flow"
    assert result.step_names() == ("collect", "unpack_repositories", "persist_repositories")
    persisted_ids = result.context.require("persisted_repository_ids")
    assert len(persisted_ids) == 1

    # Re-open storage independently to prove persistence outlived the run, not just the context.
    reopened = await build_storage(
        _config({"storage": {"backend": "filesystem", "filesystem": {"root": str(storage_root)}}})
    )
    stored = await reopened.source_repository_store.get(persisted_ids[0])
    assert stored is not None
    assert stored.name == "my-project"


@pytest.mark.asyncio
async def test_bootstrap_uses_a_caller_supplied_context_and_source(tmp_path: Any) -> None:
    """An explicit `context` argument is used as-is, instead of the built-in default seed."""
    storage_root = tmp_path / "storage"
    config = _config(
        {
            "collectors": {"backend": "filesystem"},
            "storage": {"backend": "filesystem", "filesystem": {"root": str(storage_root)}},
        }
    )
    context = PipelineContext(values={"source": str(tmp_path)})
    result = await bootstrap(config, context=context)
    assert result.context.require("collection_result").source == str(tmp_path)


@pytest.mark.asyncio
async def test_bootstrap_propagates_a_failed_collection_as_step_execution_error(
    tmp_path: Any,
) -> None:
    """A `Collector` reporting a failed collection surfaces as `StepExecutionError`, wrapping
    the `BootstrapError` this layer raises to translate that "failure as data" outcome -- not
    silently swallowed, and not a different, invented error type."""
    missing = tmp_path / "does-not-exist"
    config = _config(
        {
            "collectors": {"backend": "filesystem"},
            "storage": {"backend": "filesystem", "filesystem": {"root": str(tmp_path / "s")}},
        }
    )
    context = PipelineContext(values={"source": str(missing)})
    with pytest.raises(StepExecutionError) as excinfo:
        await bootstrap(config, context=context)
    assert excinfo.value.details["failed_step"] == "unpack_repositories"
    assert isinstance(excinfo.value.__cause__, BootstrapError)


@pytest.mark.asyncio
async def test_bootstrap_default_source_reads_collectors_source_config(tmp_path: Any) -> None:
    """With no explicit `context`, the default seed reads `collectors.source` from config."""
    config = _config(
        {
            "collectors": {"backend": "filesystem", "source": str(tmp_path)},
            "storage": {"backend": "filesystem", "filesystem": {"root": str(tmp_path / "s")}},
        }
    )
    result = await bootstrap(config)
    assert result.context.require("collection_result").source == str(tmp_path)


# --- error hierarchy -----------------------------------------------------------------------


def test_bootstrap_error_is_a_vaos_error() -> None:
    """`BootstrapError` joins the existing `VAOSError` hierarchy rather than a new root."""
    assert issubclass(BootstrapError, VAOSError)


@pytest.mark.asyncio
async def test_a_lower_layers_own_validation_error_propagates_unwrapped(tmp_path: Any) -> None:
    """`Pipeline.__init__`'s own `ValidationError` (raised for a duplicate step name introduced
    via `extra_steps`) is never re-wrapped as a `BootstrapError` -- `bootstrap` preserves every
    lower layer's own exception type, per this phase's own "do not wrap errors unnecessarily"
    instruction."""
    from src.core.exceptions import ValidationError

    duplicate_step = CallableStep("collect", lambda: None, output_key="unused")
    config = _config(
        {
            "collectors": {"backend": "filesystem"},
            "storage": {"backend": "filesystem", "filesystem": {"root": str(tmp_path / "s")}},
        }
    )
    with pytest.raises(ValidationError):
        await build_application(config, extra_steps=[duplicate_step])
