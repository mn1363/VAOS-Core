"""Integration tests proving `build_pipeline`/`run_flow` genuinely coordinate real, already-frozen
lower-layer Ports -- `src.collectors.base.Collector` and `src.parsers.base.Parser` -- through
`src.pipeline.steps.CallableStep`/`MapStep`, exactly as `tests/unit/pipeline/test_integration.py`
already establishes for `Pipeline` directly. This file exists to confirm that going through this
layer's own public functions changes nothing about that established behavior.

Every Port below is a minimal, hand-written, in-memory fake that subclasses the *real* frozen ABC,
never a mock, matching this repository's own established testing convention. No network,
filesystem, or external process is used anywhere in this file.
"""

import pytest
from src.application.runner import build_pipeline, run_flow
from src.collectors.base import CollectionResult, Collector
from src.core.protocols import SupportsAsyncClose
from src.domain.entities import RepositoryProvider, SourceLanguage, SourceRepository
from src.parsers.base import FileMetadata, Parser, ParseResult, require_relative_path
from src.pipeline.context import PipelineContext
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


@pytest.mark.asyncio
async def test_application_layer_coordinates_a_real_collector_and_parser() -> None:
    """A flow built via `build_pipeline`/`run_flow`, out of `CallableStep`/`MapStep` around real
    `Collector`/`Parser` instances, runs collection then maps parsing across every collected file
    -- without `src.application` reimplementing either Port's own logic, and without constructing
    either Port itself."""
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
        "list_files", _files_for, input_keys=("repositories",), output_key="relative_paths"
    )

    def _parse_one(relative_path: str) -> ParseResult:
        return parser.parse(relative_path=relative_path, content="x = 1\n")

    parse_step = MapStep(
        "parse", _parse_one, input_key="relative_paths", output_key="parse_results"
    )

    # This is `src.application`'s own job: assemble already-built Steps into a Pipeline, and run
    # it -- the four Steps above were built by this test, the caller, exactly as
    # `tests/unit/pipeline/test_integration.py` already establishes.
    pipeline = build_pipeline(
        "collect_and_parse", [collect_step, unpack_step, list_files_step, parse_step]
    )
    context = PipelineContext(values={"source": "/tmp/demo"})
    result = await run_flow(pipeline, context)

    assert result.step_names() == ("collect", "unpack_repositories", "list_files", "parse")
    collection_result = result.context.require("collection_result")
    assert isinstance(collection_result, CollectionResult)
    assert collection_result.repositories == (repository,)

    parse_results = result.context.require("parse_results")
    assert len(parse_results) == 1
    assert parse_results[0].relative_path == "demo/main.py"
    assert parse_results[0].succeeded is True
    assert parse_results[0].language == SourceLanguage.PYTHON


@pytest.mark.asyncio
async def test_application_layer_closes_an_injected_vector_store_like_resource_after_run() -> (
    None
):
    """A resource satisfying `core.protocols.SupportsAsyncClose` -- the same Protocol a real
    `VectorStore`/`MemoryStore`/`Storage` Port implements -- is closed after `run_flow`, exactly
    as `Pipeline.run` itself already guarantees."""
    resource = _FakeVectorStore()
    assert isinstance(resource, SupportsAsyncClose)

    noop_step = CallableStep("noop", lambda: None, output_key="unused")
    pipeline = build_pipeline("with_resource", [noop_step], resources=[resource])
    await run_flow(pipeline)
    assert resource.closed is True
