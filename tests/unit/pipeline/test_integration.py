"""Integration tests proving `Pipeline`/`CallableStep`/`MapStep` genuinely coordinate real,
already-frozen lower-layer Ports -- `src.collectors.base.Collector` and `src.parsers.base.Parser`
-- rather than only ever being exercised against throwaway fakes defined purely for
`test_pipeline.py`/`test_steps.py`'s own unit tests.

Every Port below is a minimal, hand-written, in-memory fake that subclasses the *real* frozen
ABC -- never a mock -- matching this repository's own established testing convention (see e.g.
`tests/unit/foundation/test_dependency_boundaries.py`'s own fakes). No network, filesystem, or
external process is used anywhere in this file, matching this phase's "Tests must not require
GitHub, PostgreSQL, Qdrant, external APIs, network access" requirement.
"""

import pytest
from src.collectors.base import CollectionResult, Collector
from src.core.protocols import SupportsAsyncClose
from src.domain.entities import RepositoryProvider, SourceLanguage, SourceRepository
from src.parsers.base import FileMetadata, Parser, ParseResult, require_relative_path
from src.pipeline.base import StepExecutionError
from src.pipeline.context import PipelineContext
from src.pipeline.pipeline import Pipeline
from src.pipeline.steps import CallableStep, MapStep


class _FakeFilesystemCollector(Collector):
    """A real `Collector` implementation, seeded with fixed `SourceRepository` entities."""

    def __init__(self, repositories: tuple[SourceRepository, ...]) -> None:
        self._repositories = repositories

    @property
    def provider(self) -> RepositoryProvider:
        return RepositoryProvider.FILESYSTEM

    async def collect(self, source: str) -> CollectionResult:
        return CollectionResult.ok(source=source, repositories=self._repositories)


class _FakePythonParser(Parser):
    """A real `Parser` implementation that always reports a successful, empty parse."""

    @property
    def language(self) -> SourceLanguage:
        return SourceLanguage.PYTHON

    def supports(self, relative_path: str) -> bool:
        return relative_path.endswith(".py")

    def parse(self, *, relative_path: str, content: str) -> ParseResult:
        require_relative_path(relative_path)
        metadata = FileMetadata(
            relative_path=relative_path,
            language=SourceLanguage.PYTHON,
            size_bytes=len(content.encode()),
            line_count=content.count("\n") + 1,
            content_hash="deadbeef",
        )
        return ParseResult.ok(
            relative_path=relative_path, language=SourceLanguage.PYTHON, metadata=metadata
        )


class _FakeVectorStore:
    """A minimal `SupportsAsyncClose` resource, standing in for a real `VectorStore`."""

    def __init__(self) -> None:
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


def _assert_supports_async_close(resource: object) -> None:
    """Confirm `resource` genuinely satisfies `core.protocols.SupportsAsyncClose`."""
    assert isinstance(resource, SupportsAsyncClose)


@pytest.mark.asyncio
async def test_pipeline_coordinates_a_real_collector_and_parser() -> None:
    """A `Pipeline` built entirely from `CallableStep`/`MapStep` around real `Collector`/`Parser`
    instances runs collection, then maps parsing across every collected file, without this
    package reimplementing either Port's own logic."""
    repository = SourceRepository(
        name="demo", source_uri="/tmp/demo", provider=RepositoryProvider.FILESYSTEM
    )
    collector = _FakeFilesystemCollector(repositories=(repository,))
    parser = _FakePythonParser()

    collect_step = CallableStep(
        "collect",
        collector.collect,
        input_keys=("source",),
        output_key="collection_result",
        is_async=True,
    )

    def _extract_repositories(collection_result: CollectionResult) -> tuple[SourceRepository, ...]:
        return collection_result.repositories

    unpack_step = CallableStep(
        "unpack_repositories",
        _extract_repositories,
        input_keys=("collection_result",),
        output_key="repositories",
    )

    def _files_for(repositories: tuple[SourceRepository, ...]) -> tuple[str, ...]:
        return tuple(f"{repo.name}/main.py" for repo in repositories)

    list_files_step = CallableStep(
        "list_files",
        _files_for,
        input_keys=("repositories",),
        output_key="relative_paths",
    )

    def _parse_one(relative_path: str) -> ParseResult:
        return parser.parse(relative_path=relative_path, content="x = 1\n")

    parse_step = MapStep(
        "parse", _parse_one, input_key="relative_paths", output_key="parse_results"
    )

    pipeline = Pipeline(
        "collect_and_parse",
        [collect_step, unpack_step, list_files_step, parse_step],
    )
    context = PipelineContext(values={"source": "/tmp/demo"})
    result = await pipeline.run(context)

    assert result.step_names() == (
        "collect",
        "unpack_repositories",
        "list_files",
        "parse",
    )
    collection_result = result.context.require("collection_result")
    assert isinstance(collection_result, CollectionResult)
    assert collection_result.repositories == (repository,)

    parse_results = result.context.require("parse_results")
    assert len(parse_results) == 1
    assert parse_results[0].relative_path == "demo/main.py"
    assert parse_results[0].succeeded is True
    assert parse_results[0].language == SourceLanguage.PYTHON


@pytest.mark.asyncio
async def test_pipeline_propagates_a_real_ports_own_validation_error() -> None:
    """A `ValidationError` raised by a real Port's own contract (here, `Parser.parse`'s blank-
    `relative_path` check) propagates through `MapStep`/`Pipeline.run` as a `StepExecutionError`,
    exactly like any other step failure -- Pipeline does not special-case or reinterpret a lower
    layer's own exception type."""
    parser = _FakePythonParser()

    def _parse_one(relative_path: str) -> ParseResult:
        return parser.parse(relative_path=relative_path, content="")

    parse_step = MapStep(
        "parse", _parse_one, input_key="relative_paths", output_key="parse_results"
    )
    pipeline = Pipeline("parse_only", [parse_step])
    context = PipelineContext(values={"relative_paths": ["ok.py", "  "]})

    with pytest.raises(StepExecutionError) as excinfo:
        await pipeline.run(context)
    assert excinfo.value.details["failed_step"] == "parse"
    assert type(excinfo.value.__cause__).__name__ == "ValidationError"


@pytest.mark.asyncio
async def test_pipeline_closes_an_injected_vector_store_like_resource_after_run() -> None:
    """A resource satisfying `core.protocols.SupportsAsyncClose` -- the same Protocol a real
    `VectorStore`/`MemoryStore`/`Storage` Port implements -- is closed after `run`, whether or
    not any step actually reads or writes from it."""
    resource = _FakeVectorStore()
    _assert_supports_async_close(resource)

    noop_step = CallableStep("noop", lambda: None, output_key="unused")
    pipeline = Pipeline("with_resource", [noop_step], resources=[resource])
    await pipeline.run()
    assert resource.closed is True
