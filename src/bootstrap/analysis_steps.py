"""Real Repository Analysis Composition: production `Step` builders for clone -> enumerate ->
parse -> extract, promoted from the Reference Flow's own test-local composition (see
`tests/integration/test_reference_flow.py`, "frozen as a milestone") into `src/bootstrap`.

`build_analysis_steps` is this module's entire public surface: one function returning the eleven
additional `Step`s a caller appends via `bootstrap.wiring.bootstrap`/`build_application`'s own
`extra_steps` parameter -- the only attachment point this module uses. It does not construct a
`Pipeline` itself, does not call `Pipeline.run`, and does not modify `wiring.py`'s own three-step
default flow (`collect`, `unpack_repositories`, `persist_repositories`): every step here is
additive, appended strictly after `persist_repositories`.

**Scope.** Real-repository analysis composition is explicitly one-repository scoped, exactly as
the Reference Flow itself already documented as an open question it left unresolved
(`docs/reference_flow_summary.md`'s own "Extending to N repositories is an explicit, separate
design question, not resolved here"). `_require_single_repository` closes that question the same
way `bootstrap.wiring._unpack_repositories` already turns a `CollectionResult`'s own "failure
reported as data" outcome into a raised exception: more than one collected repository is a wiring
decision turning out to be invalid for this flow -- exactly `bootstrap.errors.BootstrapError`'s
own documented scope -- so it is reused here, not replaced with a new exception type.

**Failed parses.** `parse_files` still produces `ParseResult.failed(...)` for a file no parser
supports (a `README.md`, for instance) -- unchanged Reference Flow behavior. Every concrete
extractor already rejects a failed `ParseResult` (`require_successful_parse`), so
`_select_successful_parse_results` bridges the two: it reads `parse_results` (retained, unchanged,
successes and failures both, under its own key) and writes a second, filtered
`successful_parse_results` tuple, preserving relative order, for every extractor step to consume.

**Extractors.** All six existing concrete extractors (`imports`, `ast`, `symbols`, `architecture`,
`interfaces`, `foundation`) are wired in this one milestone -- each already independently tested,
and already proven, together, to consume `successful_parse_results` deterministically. `patterns`
is not wired: it remains intentionally Port-only (see this milestone's own Patterns Final Contract
Discovery); no field of `graph.knowledge.base.KnowledgeGraphBuilder.build` requires it, since its
`pattern_results` parameter already defaults to `()`.

**No new abstraction.** `_require_single_repository`, `_clone_repository_func`,
`_enumerate_files`, `_parse_files_func`, and `_select_successful_parse_results` are plain
functions/closure factories, matching `wiring.py`'s own `_persist_repository_func` convention --
no service class, no registry, no dispatcher, no DI container, no service locator. Parser dispatch
is `Parser.supports()` over a fixed, five-element tuple constructed once by `_all_parsers`, tried
in a fixed order -- the same shape the Reference Flow itself already approved, not a registry.
"""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from pathlib import Path

from src.core.config import AppConfig
from src.domain.entities import SourceLanguage, SourceRepository
from src.extractors.architecture.structural import StructuralArchitectureExtractor
from src.extractors.ast.structural import StructuralAstExtractor
from src.extractors.foundation.structural import StructuralFoundationExtractor
from src.extractors.imports.structural import StructuralImportExtractor
from src.extractors.interfaces.structural import StructuralInterfaceExtractor
from src.extractors.symbols.structural import StructuralSymbolExtractor
from src.parsers.base import Parser, ParseResult
from src.parsers.cpp.parser import CppParser
from src.parsers.go.parser import GoParser
from src.parsers.python.parser import PythonParser
from src.parsers.rust.parser import RustParser
from src.parsers.typescript.parser import TypeScriptParser
from src.pipeline.base import Step
from src.pipeline.steps import CallableStep, MapStep
from src.repository.base import RepositoryClient, WorkspaceManager

from .errors import BootstrapError
from .wiring import build_repository_client, build_workspace_manager


def _require_single_repository(
    repositories: tuple[SourceRepository, ...],
) -> tuple[SourceRepository, ...]:
    """Reject more than one collected repository; this composition is one-repository scoped.

    Zero or one repository is returned unchanged -- this milestone does not require a repository
    to be present, matching every other "empty is not an error" step already in the frozen
    architecture (`Pipeline.run` on an empty `steps`, `Runtime.start`/`stop` on empty `services`,
    `PatternExtractionResult.ok` with empty `patterns`).

    Args:
        repositories: The repositories `unpack_repositories` (the existing, frozen default step)
            already produced.

    Returns:
        `repositories`, unchanged.

    Raises:
        BootstrapError: If more than one repository is present. Real-repository analysis
            composition has no repository-ownership DTO for disambiguating which downstream
            `ParseResult`/extraction result belongs to which of several repositories -- exactly
            the gap `docs/reference_flow_summary.md` already named and explicitly left
            unresolved -- so more than one collected repository is rejected here rather than
            silently analyzed as if it were one.
    """
    if len(repositories) > 1:
        raise BootstrapError(
            "real-repository analysis composition is one-repository scoped, but "
            f"{len(repositories)} repositories were collected",
            details={
                "repository_count": len(repositories),
                "repository_names": [repository.name for repository in repositories],
            },
        )
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
    """Construct the eleven additional `Step`s real-repository analysis composition needs.

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
        The eleven new `Step`s, in the fixed order: `require_single_repository`,
        `clone_repositories`, `enumerate_files`, `parse_files`, `select_successful_parse_results`,
        `extract_imports`, `extract_ast`, `extract_symbols`, `extract_architecture`,
        `extract_interfaces`, `extract_foundation`.
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
        _clone_repository_func(repository_client, workspace_manager),
        input_key="repositories",
        output_key="workspaces",
        is_async=True,
    )
    enumerate_step: Step = CallableStep(
        "enumerate_files",
        _enumerate_files,
        input_keys=("workspaces",),
        output_key="files_to_parse",
    )
    parse_step: Step = MapStep(
        "parse_files",
        _parse_files_func(parsers),
        input_key="files_to_parse",
        output_key="parse_results",
    )
    select_successful_parse_results_step: Step = CallableStep(
        "select_successful_parse_results",
        _select_successful_parse_results,
        input_keys=("parse_results",),
        output_key="successful_parse_results",
    )
    extract_imports_step: Step = MapStep(
        "extract_imports",
        StructuralImportExtractor().extract,
        input_key="successful_parse_results",
        output_key="import_results",
    )
    extract_ast_step: Step = MapStep(
        "extract_ast",
        StructuralAstExtractor().extract,
        input_key="successful_parse_results",
        output_key="ast_results",
    )
    extract_symbols_step: Step = MapStep(
        "extract_symbols",
        StructuralSymbolExtractor().extract,
        input_key="successful_parse_results",
        output_key="symbol_results",
    )
    extract_architecture_step: Step = MapStep(
        "extract_architecture",
        StructuralArchitectureExtractor().extract,
        input_key="successful_parse_results",
        output_key="architecture_results",
    )
    extract_interfaces_step: Step = MapStep(
        "extract_interfaces",
        StructuralInterfaceExtractor().extract,
        input_key="successful_parse_results",
        output_key="interface_results",
    )
    extract_foundation_step: Step = MapStep(
        "extract_foundation",
        StructuralFoundationExtractor().extract,
        input_key="successful_parse_results",
        output_key="foundation_results",
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
    ]
