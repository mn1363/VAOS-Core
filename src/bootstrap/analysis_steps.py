"""Real Repository Analysis Composition: production `Step` builders for clone -> enumerate ->
parse -> extract, promoted from the Reference Flow's own test-local composition (see
`tests/integration/test_reference_flow.py`, "frozen as a milestone") into `src/bootstrap`.

`build_analysis_steps` is this module's entire public surface: one function returning the thirteen
additional `Step`s a caller appends via `bootstrap.wiring.bootstrap`/`build_application`'s own
`extra_steps` parameter -- the only attachment point this module uses. It does not construct a
`Pipeline` itself, does not call `Pipeline.run`, and does not modify `wiring.py`'s own three-step
default flow (`collect`, `unpack_repositories`, `persist_repositories`): every step here is
additive, appended strictly after `persist_repositories`.

**Repository scope.** Any number of repositories can pass through this composition.
Each cloned workspace, file, parser result and extractor result carries its owning repository UUID
in a small immutable wrapper. Relative paths stay unchanged inside each repository. Graph builders
receive only the results for one repository, so identical paths in different repositories cannot
collide and imports cannot resolve across repository boundaries. The single-repository graph
context values retain their original graph type for compatibility; multi-repository graph values
are tuples of `RepositoryGraph` records.

**Failed parses.** `parse_files` still produces `ParseResult.failed(...)` for a file no parser
supports (a `README.md`, for instance) -- unchanged Parser behavior. The repository-scoped parse
wrapper keeps the repository UUID attached to both successful and failed outcomes.
`_select_successful_repository_parse_results` filters failures while preserving that UUID and
the original order.

**Extractors.** All six existing concrete extractors (`imports`, `ast`, `symbols`, `architecture`,
`interfaces`, `foundation`) keep their existing Parser and Extractor contracts. Small closure
adapters unwrap each parse result for the existing extractor, then attach the same repository UUID
to its output. `patterns` is not wired: it remains intentionally Port-only; the Knowledge Graph
builder accepts an empty `pattern_results` tuple.

**No service layer.** Repository scoping uses immutable data records and plain functions or
closures. It adds no registry, dispatcher, DI container or service locator. Parser dispatch is
still `Parser.supports()` over a fixed, five-element tuple constructed once by `_all_parsers`,
tried in a fixed order.
"""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from src.core.config import AppConfig
from src.domain.entities import SourceLanguage, SourceRepository
from src.extractors.architecture.structural import StructuralArchitectureExtractor
from src.extractors.ast.structural import StructuralAstExtractor
from src.extractors.foundation.structural import StructuralFoundationExtractor
from src.extractors.imports.structural import StructuralImportExtractor
from src.extractors.interfaces.structural import StructuralInterfaceExtractor
from src.extractors.symbols.structural import StructuralSymbolExtractor
from src.graph.architecture.structural import StructuralArchitectureGraphBuilder
from src.graph.dependency.structural import StructuralDependencyGraphBuilder
from src.parsers.base import Parser, ParseResult
from src.parsers.cpp.parser import CppParser
from src.parsers.go.parser import GoParser
from src.parsers.python.parser import PythonParser
from src.parsers.rust.parser import RustParser
from src.parsers.typescript.parser import TypeScriptParser
from src.pipeline.base import Step
from src.pipeline.steps import CallableStep, MapStep
from src.repository.base import RepositoryClient, WorkspaceManager

from .wiring import build_repository_client, build_workspace_manager


@dataclass(frozen=True, slots=True)
class RepositoryWorkspace:
    """A cloned workspace with the identity of its owning repository."""

    repository_id: UUID
    path: Path


@dataclass(frozen=True, slots=True)
class RepositoryFile:
    """A decoded file with repository-scoped path identity."""

    repository_id: UUID
    relative_path: str
    content: str

    def __iter__(self) -> Iterator[str]:
        """Keep legacy two-value unpacking available for single-repository callers."""
        yield self.relative_path
        yield self.content


@dataclass(frozen=True, slots=True, eq=False)
class RepositoryScoped[ResultT]:
    """An existing parser or extractor result paired with its repository identity."""

    repository_id: UUID
    result: ResultT

    def __getattr__(self, name: str) -> Any:
        """Expose the wrapped result's attributes for existing read-only consumers."""
        return getattr(self.result, name)

    def __eq__(self, other: object) -> bool:
        """Compare both owner identity and wrapped value."""
        if not isinstance(other, RepositoryScoped):
            return False
        return self.repository_id == other.repository_id and self.result == other.result


@dataclass(frozen=True, slots=True)
class RepositoryGraph[ResultT]:
    """A graph and the repository whose files were used to build it."""

    repository_id: UUID
    graph: ResultT


def _require_single_repository(
    repositories: tuple[SourceRepository, ...],
) -> tuple[SourceRepository, ...]:
    """Accept any number of repositories for repository-scoped analysis.

    Later steps carry each repository UUID beside its workspace, file, parser result and
    extractor result. Equal relative paths from different repositories therefore remain
    separate.

    Args:
        repositories: Repositories produced by the collection and persistence steps.

    Returns:
        The original repository tuple, unchanged.
    """
    return repositories


def _all_parsers() -> tuple[Parser, ...]:
    """The five existing concrete `Parser` implementations, freshly constructed.

    A fixed, tried-in-order tuple -- not a registry, and not dynamically discovered. Mirrors
    `tests/integration/test_reference_flow.py`'s own `_all_parsers` exactly.
    """
    return (PythonParser(), RustParser(), GoParser(), TypeScriptParser(), CppParser())


def _clone_repository_func(
    repository_client: RepositoryClient, workspace_manager: WorkspaceManager
) -> Callable[[SourceRepository], Awaitable[Path]]:
    """Bind `repository_client`/`workspace_manager` into a single-item callable for `MapStep`.

    Neither Port is constructed here -- both arrive already built, via `wiring.py`'s own
    `build_repository_client`/`build_workspace_manager`. Mirrors
    `bootstrap.wiring._persist_repository_func`'s own closure-factory pattern.

    Args:
        repository_client: Already-constructed `RepositoryClient` each mapped repository is
            cloned through.
        workspace_manager: Already-constructed `WorkspaceManager` each mapped repository's
            destination directory is allocated from.

    Returns:
        An async callable suitable for `MapStep`: allocates a workspace for one repository,
        clones into it, and returns the resulting path.
    """

    async def _clone(repository: SourceRepository) -> Path:
        destination = workspace_manager.allocate(repository.id)
        await repository_client.clone(repository, destination)
        return destination

    return _clone


def _clone_repository_scoped_func(
    repository_client: RepositoryClient, workspace_manager: WorkspaceManager
) -> Callable[[SourceRepository], Awaitable[RepositoryWorkspace]]:
    """Clone one repository and retain its identity beside the workspace path."""
    clone = _clone_repository_func(repository_client, workspace_manager)

    async def _clone_scoped(repository: SourceRepository) -> RepositoryWorkspace:
        path = await clone(repository)
        return RepositoryWorkspace(repository_id=repository.id, path=path)

    return _clone_scoped


def _enumerate_repository_files(
    workspaces: tuple[RepositoryWorkspace, ...],
) -> tuple[RepositoryFile, ...]:
    """Enumerate text files while retaining the owning repository UUID."""
    files: list[RepositoryFile] = []
    for workspace in workspaces:
        for relative_path, content in _enumerate_files((workspace.path,)):
            files.append(
                RepositoryFile(
                    repository_id=workspace.repository_id,
                    relative_path=relative_path,
                    content=content,
                )
            )
    return tuple(files)


def _parse_repository_file_func(
    parsers: tuple[Parser, ...],
) -> Callable[[RepositoryFile], RepositoryScoped[ParseResult]]:
    """Parse one file and preserve its repository identity in the outcome."""
    parse = _parse_files_func(parsers)

    def _parse_scoped(file: RepositoryFile) -> RepositoryScoped[ParseResult]:
        result = parse((file.relative_path, file.content))
        return RepositoryScoped(repository_id=file.repository_id, result=result)

    return _parse_scoped


def _select_successful_repository_parse_results(
    parse_results: tuple[RepositoryScoped[ParseResult], ...],
) -> tuple[RepositoryScoped[ParseResult], ...]:
    """Filter failed parses without dropping repository ownership."""
    return tuple(item for item in parse_results if item.result.succeeded)


def _extract_repository_result_func[ResultT](
    extractor: Callable[[ParseResult], ResultT],
) -> Callable[[RepositoryScoped[ParseResult]], RepositoryScoped[ResultT]]:
    """Adapt an existing single-file extractor to repository-scoped parse results."""

    def _extract(item: RepositoryScoped[ParseResult]) -> RepositoryScoped[ResultT]:
        return RepositoryScoped(
            repository_id=item.repository_id,
            result=extractor(item.result),
        )

    return _extract


def _build_repository_graphs[ResultT](
    repositories: tuple[SourceRepository, ...],
    extraction_results: tuple[RepositoryScoped[ResultT], ...],
    builder: Callable[[Sequence[ResultT]], ResultT],
) -> ResultT | tuple[RepositoryGraph[ResultT], ...]:
    """Build one graph per repository, including repositories with no parsed files."""
    grouped: dict[UUID, list[ResultT]] = {repository.id: [] for repository in repositories}
    for item in extraction_results:
        grouped.setdefault(item.repository_id, []).append(item.result)
    if len(grouped) <= 1:
        only_results = next(iter(grouped.values()), [])
        return builder(tuple(only_results))
    return tuple(
        RepositoryGraph(repository_id=repository_id, graph=builder(tuple(results)))
        for repository_id, results in grouped.items()
    )


def _enumerate_files(workspaces: tuple[Path, ...]) -> tuple[tuple[str, str], ...]:
    """List every regular, text-decodable file under each workspace, `.git` excluded.

    Mirrors `collectors.local.LocalCollector._scan`'s own established convention: `os.walk` with
    `topdown=True`, pruning any directory whose name starts with `.` by clearing it from
    `dirnames` in place. Traversal is sorted at each level for deterministic output. No special
    exclusion exists anywhere in the frozen architecture for `node_modules`, `vendor`, or
    `target`, so none is added here.

    Args:
        workspaces: Root directories to walk, typically one per cloned repository.

    Returns:
        `(relative_path, content)` pairs, in sorted directory-walk order. A file that cannot be
        decoded as UTF-8 text is silently skipped rather than raising -- the same "one item's
        failure is not exceptional for the whole scan" convention `Collector.collect`/
        `Parser.parse` already use for their own per-item failures.
    """
    files: list[tuple[str, str]] = []
    for workspace in workspaces:
        for dirpath, dirnames, filenames in os.walk(workspace, topdown=True):
            dirnames[:] = sorted(name for name in dirnames if not name.startswith("."))
            current = Path(dirpath)
            for filename in sorted(filenames):
                absolute = current / filename
                try:
                    content = absolute.read_text(encoding="utf-8")
                except (UnicodeDecodeError, OSError):
                    continue
                files.append((str(absolute.relative_to(workspace)), content))
    return tuple(files)


def _parse_files_func(
    parsers: tuple[Parser, ...],
) -> Callable[[tuple[str, str]], ParseResult]:
    """Bind `parsers` into a single-item callable for `MapStep`.

    Dispatch is exactly `Parser.supports()`, already part of the frozen `Parser` Port, tried in
    `parsers`' own fixed order -- no registry or dispatcher of any kind is introduced.

    Args:
        parsers: Already-constructed `Parser` instances, tried in order.

    Returns:
        A sync callable suitable for `MapStep`: parses one `(relative_path, content)` pair with
        the first parser that supports it, or reports a failed `ParseResult` if none does.
    """

    def _parse_one(item: tuple[str, str]) -> ParseResult:
        relative_path, content = item
        parser = next(
            (candidate for candidate in parsers if candidate.supports(relative_path)), None
        )
        if parser is None:
            return ParseResult.failed(
                relative_path=relative_path,
                language=SourceLanguage.UNKNOWN,
                error_message=f"no parser supports '{relative_path}'",
            )
        return parser.parse(relative_path=relative_path, content=content)

    return _parse_one


def _select_successful_parse_results(
    parse_results: tuple[ParseResult, ...],
) -> tuple[ParseResult, ...]:
    """Filter `parse_results` down to only the results that succeeded, preserving relative order.

    `parse_results` itself is never mutated or replaced -- it is written, unchanged, under its
    own context key by `parse_files`, and remains readable there after this step runs. This
    function only ever reads it and returns a new, filtered tuple.

    Args:
        parse_results: Every `ParseResult` `parse_files` produced, successes and failures alike,
            in `files_to_parse` order.

    Returns:
        The subset of `parse_results` with `succeeded is True`, in the same relative order --
        a stable filter, not a sort.
    """
    return tuple(result for result in parse_results if result.succeeded)


def build_analysis_steps(config: AppConfig) -> list[Step]:
    """Construct the thirteen additional `Step`s real-repository analysis composition needs.

    Every Port this milestone needs is constructed here from already-existing, already-frozen
    builders -- `wiring.build_repository_client`/`build_workspace_manager` -- or from direct
    construction of already-frozen, concrete classes (the five parsers, the six extractors); none
    is looked up through a registry or service locator. The returned steps are meant to be passed
    straight through as `bootstrap(config, extra_steps=build_analysis_steps(config))`; this
    function never constructs a `Pipeline` and never calls `Pipeline.run` itself.

    Args:
        config: Resolved application configuration. Passed straight through to
            `build_repository_client`/`build_workspace_manager`, exactly as `wiring.py`'s own
            `build_application` already does for its own three default steps.

    Returns:
        The thirteen new `Step`s, in the fixed order: `require_single_repository`,
        `clone_repositories`, `enumerate_files`, `parse_files`, `select_successful_parse_results`,
        `extract_imports`, `extract_ast`, `extract_symbols`, `extract_architecture`,
        `extract_interfaces`, `extract_foundation`, `build_architecture_graph`,
        `build_dependency_graph`. File, parse and extraction outputs retain repository UUIDs.
        Both graph steps group inputs by UUID before calling the existing graph builder. For one
        repository, each graph key retains its original graph type. For multiple repositories, each
        graph key contains a tuple of `RepositoryGraph` values.
    """
    repository_client = build_repository_client(config)
    workspace_manager = build_workspace_manager(config)
    parsers = _all_parsers()

    require_single_repository_step: Step = CallableStep(
        "require_single_repository",
        _require_single_repository,
        input_keys=("repositories",),
        output_key="repositories",
    )
    clone_step: Step = MapStep(
        "clone_repositories",
        _clone_repository_scoped_func(repository_client, workspace_manager),
        input_key="repositories",
        output_key="workspaces",
        is_async=True,
    )
    enumerate_step: Step = CallableStep(
        "enumerate_files",
        _enumerate_repository_files,
        input_keys=("workspaces",),
        output_key="files_to_parse",
    )
    parse_step: Step = MapStep(
        "parse_files",
        _parse_repository_file_func(parsers),
        input_key="files_to_parse",
        output_key="parse_results",
    )
    select_successful_parse_results_step: Step = CallableStep(
        "select_successful_parse_results",
        _select_successful_repository_parse_results,
        input_keys=("parse_results",),
        output_key="successful_parse_results",
    )
    extract_imports_step: Step = MapStep(
        "extract_imports",
        _extract_repository_result_func(StructuralImportExtractor().extract),
        input_key="successful_parse_results",
        output_key="import_results",
    )
    extract_ast_step: Step = MapStep(
        "extract_ast",
        _extract_repository_result_func(StructuralAstExtractor().extract),
        input_key="successful_parse_results",
        output_key="ast_results",
    )
    extract_symbols_step: Step = MapStep(
        "extract_symbols",
        _extract_repository_result_func(StructuralSymbolExtractor().extract),
        input_key="successful_parse_results",
        output_key="symbol_results",
    )
    extract_architecture_step: Step = MapStep(
        "extract_architecture",
        _extract_repository_result_func(StructuralArchitectureExtractor().extract),
        input_key="successful_parse_results",
        output_key="architecture_results",
    )
    extract_interfaces_step: Step = MapStep(
        "extract_interfaces",
        _extract_repository_result_func(StructuralInterfaceExtractor().extract),
        input_key="successful_parse_results",
        output_key="interface_results",
    )
    extract_foundation_step: Step = MapStep(
        "extract_foundation",
        _extract_repository_result_func(StructuralFoundationExtractor().extract),
        input_key="successful_parse_results",
        output_key="foundation_results",
    )
    build_architecture_graph_step: Step = CallableStep(
        "build_architecture_graph",
        lambda repositories, results: _build_repository_graphs(
            repositories, results, StructuralArchitectureGraphBuilder().build
        ),
        input_keys=("repositories", "architecture_results"),
        output_key="architecture_graph",
    )
    build_dependency_graph_step: Step = CallableStep(
        "build_dependency_graph",
        lambda repositories, results: _build_repository_graphs(
            repositories, results, StructuralDependencyGraphBuilder().build
        ),
        input_keys=("repositories", "import_results"),
        output_key="dependency_graph",
    )

    return [
        require_single_repository_step,
        clone_step,
        enumerate_step,
        parse_step,
        select_successful_parse_results_step,
        extract_imports_step,
        extract_ast_step,
        extract_symbols_step,
        extract_architecture_step,
        extract_interfaces_step,
        extract_foundation_step,
        build_architecture_graph_step,
        build_dependency_graph_step,
    ]
