"""Integration test: the opt-in Knowledge Graph step inside an explicitly constructed pipeline.

Runs the real repository-analysis composition (`bootstrap(config, extra_steps=...)`) over temporary
local Git repositories -- real `git`, real parsers and extractors, no network -- in two
compositions:

- the **default** one, `build_analysis_steps(config)` alone, exactly as `--analyze` runs it; and
- an **explicit opt-in** one, `[*build_analysis_steps(config), build_knowledge_graph_step()]`.

It verifies the opt-in step's output and determinism, that it is purely additive to the default
outputs, and that fail-fast behavior on a remaining identity collision is confined to the
explicitly opted-in pipeline. The default composition is never modified, and these tests do not
touch `tests/integration/test_knowledge_graph.py` or any Duplicate Identity test.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from src.bootstrap.analysis_steps import build_analysis_steps
from src.bootstrap.knowledge_graph_step import build_knowledge_graph_step
from src.bootstrap.wiring import bootstrap
from src.core.config import AppConfig
from src.core.exceptions import ValidationError
from src.graph.knowledge.base import KnowledgeGraph, KnowledgeNodeKind, KnowledgeRelationKind
from src.graph.knowledge.structural import StructuralKnowledgeGraphBuilder
from src.pipeline.base import PipelineResult, StepExecutionError
from src.pipeline.context import PipelineContext

_STEP_NAME = "build_knowledge_graph"
_BASE_STEP_NAMES = ("collect", "unpack_repositories", "persist_repositories")

_ACCESSORS_PY = '''\
from typing import overload


class A:
    @property
    def x(self):
        return 1

    @x.setter
    def x(self, value):
        pass


@overload
def f(a: int) -> int: ...
@overload
def f(a: str) -> str: ...
def f(a):
    """Documented only on the implementation."""
    return a


def g():
    return 1


def g():
    return 2
'''

# Valid sources whose duplicate declarations are all equivalent: every one coalesces.
_ACCEPTED_FILES: dict[str, str] = {
    "accessors.py": _ACCESSORS_PY,
    "init.go": "package main\n\nfunc init() {}\n\nfunc init() {}\n",
    "overloads.ts": (
        "function f(a: string): string;\n"
        "function f(a: number): number;\n"
        "function f(a: any): any { return a; }\n"
    ),
}

# Valid sources with a remaining collision case: a class and a function sharing one name.
_CONFLICT_FILES: dict[str, str] = {
    "m.py": "class Foo:\n    pass\n\n\ndef Foo():\n    return 1\n",
    "ok.py": "def fine():\n    return 1\n",
}

_CONFLICT_MESSAGE = (
    "KnowledgeGraph: nodes must not contain duplicate identifiers; "
    "2 colliding identifier(s) rejected: 'capability:m.py::Foo', 'symbol:m.py::Foo'"
)

# Context keys the default composition writes whose values are independent of workspace paths.
_DETERMINISTIC_KEYS = (
    "symbol_results",
    "interface_results",
    "foundation_results",
    "architecture_results",
    "import_results",
    "architecture_graph",
    "dependency_graph",
)


def _run_git(*args: str, cwd: Path) -> None:
    """Run a `git` subcommand in `cwd`, raising if it fails."""
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _skip_without_git() -> None:
    """Skip the calling test if the real `git` executable is unavailable."""
    if shutil.which("git") is None:
        pytest.skip("git executable not found on PATH")


def _make_source_repository(tmp_path: Path, name: str, files: dict[str, str]) -> Path:
    """Create a local Git repository under `tmp_path` holding `files`, with one commit."""
    source_repo = tmp_path / name
    source_repo.mkdir()
    _run_git("init", cwd=source_repo)
    _run_git("config", "user.email", "test@example.com", cwd=source_repo)
    _run_git("config", "user.name", "Test", cwd=source_repo)
    _run_git("checkout", "-b", "main", cwd=source_repo)
    for relative_path, content in files.items():
        (source_repo / relative_path).write_text(content, encoding="utf-8")
    _run_git("add", "-A", cwd=source_repo)
    _run_git("commit", "-m", "fixture repository", cwd=source_repo)
    return source_repo


def _config(source_repo: Path, tmp_path: Path, tag: str) -> AppConfig:
    """A config for one run: its own storage and workspace roots keyed by `tag`."""
    return AppConfig(
        raw={
            "collectors": {"backend": "filesystem", "source": str(source_repo)},
            "storage": {
                "backend": "filesystem",
                "filesystem": {"root": str(tmp_path / f"storage-{tag}")},
            },
            "repository": {"workspace_root": str(tmp_path / f"workspaces-{tag}")},
        }
    )


async def _run(
    source_repo: Path,
    tmp_path: Path,
    tag: str,
    *,
    opt_in: bool,
    context: PipelineContext | None = None,
) -> PipelineResult:
    """Run the real composition, with the opt-in step explicitly appended only if `opt_in`."""
    config = _config(source_repo, tmp_path, tag)
    steps = build_analysis_steps(config)
    if opt_in:
        steps = [*steps, build_knowledge_graph_step()]
    return await bootstrap(config, extra_steps=steps, context=context)


def _identifiers(graph: KnowledgeGraph) -> list[str]:
    """Every node identifier in `graph`, in graph order."""
    return [node.identifier for node in graph.nodes]


def _direct_graph(context: PipelineContext) -> KnowledgeGraph:
    """What the real builder produces, called directly, from `context`'s own producer outputs."""
    return StructuralKnowledgeGraphBuilder().build(
        symbol_results=context.require("symbol_results"),
        interface_results=context.require("interface_results"),
        foundation_results=context.require("foundation_results"),
        architecture_graph=context.require("architecture_graph"),
    )


@pytest.mark.asyncio
async def test_an_explicit_opt_in_pipeline_builds_the_graph_after_every_producer_step(
    tmp_path: Path,
) -> None:
    """The step runs last, after its four producers, and writes the real builder's graph."""
    _skip_without_git()
    repo = _make_source_repository(tmp_path, "accepted_repo", _ACCEPTED_FILES)

    result = await _run(repo, tmp_path, "opt-in", opt_in=True)

    default_analysis_names = [
        step.name for step in build_analysis_steps(_config(repo, tmp_path, "names"))
    ]
    names = result.step_names()
    assert names == (*_BASE_STEP_NAMES, *default_analysis_names, _STEP_NAME)
    for producer in (
        "extract_symbols",
        "extract_interfaces",
        "extract_foundation",
        "build_architecture_graph",
    ):
        assert names.index(producer) < names.index(_STEP_NAME)

    context = result.context
    graph = context.require("knowledge_graph")
    assert isinstance(graph, KnowledgeGraph)
    assert graph == _direct_graph(context)
    assert graph.to_mapping() == _direct_graph(context).to_mapping()

    # Real duplicates existed in the extractor output and became one node each.
    symbols = [s for r in context.require("symbol_results") for s in r.symbols]
    assert [s.qualified_name for s in symbols].count("accessors.py::f") == 3
    assert [s.qualified_name for s in symbols].count("accessors.py::A.x") == 2
    identifiers = _identifiers(graph)
    declares = [r for r in graph.relations if r.kind is KnowledgeRelationKind.DECLARES]
    for identifier in (
        "symbol:accessors.py::A.x",
        "symbol:accessors.py::f",
        "capability:accessors.py::f",
        "symbol:accessors.py::g",
        "symbol:init.go::init",
        "capability:init.go::init",
        "symbol:overloads.ts::f",
        "capability:overloads.ts::f",
    ):
        assert identifiers.count(identifier) == 1, identifier
        assert len([r for r in declares if r.target == identifier]) == 1, identifier

    # The architecture graph was used, and no pattern results exist in the standard composition.
    assert any(node.kind is KnowledgeNodeKind.PACKAGE for node in graph.nodes)
    assert not any(node.kind is KnowledgeNodeKind.PATTERN for node in graph.nodes)
    assert not context.has("pattern_results")


@pytest.mark.asyncio
async def test_the_opt_in_step_is_deterministic_and_purely_additive(tmp_path: Path) -> None:
    """Independent opt-in runs agree, and add only `knowledge_graph` to the default outputs."""
    _skip_without_git()
    repo = _make_source_repository(tmp_path, "accepted_repo", _ACCEPTED_FILES)

    default = await _run(repo, tmp_path, "default", opt_in=False)
    first = await _run(repo, tmp_path, "first", opt_in=True)
    second = await _run(repo, tmp_path, "second", opt_in=True)

    # Deterministic across independent runs, and across repeated builds of one run's results.
    graph = first.context.require("knowledge_graph")
    assert second.context.require("knowledge_graph") == graph
    assert second.context.require("knowledge_graph").to_mapping() == graph.to_mapping()
    for _ in range(3):
        assert _direct_graph(first.context).to_mapping() == graph.to_mapping()

    # Purely additive: the default composition never writes the key, and everything the default
    # composition produces is unchanged when the step is appended.
    assert not default.context.has("knowledge_graph")
    assert set(first.context.values) == {*default.context.values, "knowledge_graph"}
    assert first.step_names()[:-1] == default.step_names()
    assert first.step_names()[-1] == _STEP_NAME
    for key in _DETERMINISTIC_KEYS:
        assert first.context.require(key) == default.context.require(key), key


@pytest.mark.asyncio
async def test_a_conflicting_valid_source_fails_fast_only_in_the_opted_in_pipeline(
    tmp_path: Path,
) -> None:
    """A class/function name clash fails the opt-in run; the default run on it still succeeds."""
    _skip_without_git()
    repo = _make_source_repository(tmp_path, "conflict_repo", _CONFLICT_FILES)

    # The default composition -- what `--analyze` runs -- is unaffected by the remaining case.
    default = await _run(repo, tmp_path, "default", opt_in=False)
    assert not default.context.has("knowledge_graph")
    assert default.context.has("architecture_graph")
    assert default.context.has("dependency_graph")

    # The explicitly opted-in pipeline fails fast, with the normal pipeline failure contract.
    with pytest.raises(StepExecutionError) as excinfo:
        await _run(repo, tmp_path, "opt-in", opt_in=True)
    error = excinfo.value
    assert error.details["failed_step"] == _STEP_NAME
    completed = error.details["completed_steps"]
    assert completed[-1] == "build_dependency_graph"
    assert {"extract_symbols", "extract_interfaces", "extract_foundation"} <= set(completed)
    assert _STEP_NAME not in completed

    cause = error.__cause__
    assert isinstance(cause, ValidationError)
    assert str(cause) == _CONFLICT_MESSAGE
    assert cause.details["collision_count"] == 2
    assert _CONFLICT_MESSAGE in str(error)


@pytest.mark.asyncio
async def test_a_failed_opt_in_run_leaves_a_caller_supplied_context_with_earlier_outputs(
    tmp_path: Path,
) -> None:
    """Steps mutate the context in place, so a caller holding it keeps what ran before failure."""
    _skip_without_git()
    repo = _make_source_repository(tmp_path, "conflict_repo", _CONFLICT_FILES)
    context = PipelineContext(values={"source": str(repo)})

    with pytest.raises(StepExecutionError):
        await _run(repo, tmp_path, "opt-in", opt_in=True, context=context)

    for key in ("symbol_results", "architecture_graph", "dependency_graph"):
        assert context.has(key), key
    assert not context.has("knowledge_graph")
