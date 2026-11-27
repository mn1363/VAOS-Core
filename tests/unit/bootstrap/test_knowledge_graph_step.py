"""Unit tests for `src.bootstrap.knowledge_graph_step`.

Every fake here is a real `KnowledgeGraphBuilder` implementation, never a `unittest.mock` double,
matching this repository's established testing convention (see
`tests/unit/bootstrap/test_analysis_steps.py`). Real extraction results come from the real
parsers/extractors on in-memory sources. No test here performs I/O, clones a repository, or uses
the network -- see `tests/integration/test_knowledge_graph_step.py` for the real-repository run.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path
from typing import Any

import pytest
import src.bootstrap.analysis_steps as analysis_steps_module
import src.bootstrap.knowledge_graph_step as step_module
import src.cli.main as cli_main_module
from src.bootstrap.analysis_steps import build_analysis_steps
from src.bootstrap.knowledge_graph_step import _knowledge_graph_func, build_knowledge_graph_step
from src.core.config import AppConfig
from src.core.exceptions import NotFoundError, ValidationError
from src.extractors.architecture.structural import StructuralArchitectureExtractor
from src.extractors.foundation.structural import StructuralFoundationExtractor
from src.extractors.interfaces.structural import StructuralInterfaceExtractor
from src.extractors.symbols.structural import StructuralSymbolExtractor
from src.graph.architecture.structural import StructuralArchitectureGraphBuilder
from src.graph.knowledge.base import KnowledgeGraph, KnowledgeGraphBuilder, KnowledgeNodeKind
from src.graph.knowledge.structural import StructuralKnowledgeGraphBuilder
from src.parsers.python.parser import PythonParser
from src.pipeline.base import Step, StepExecutionError
from src.pipeline.context import PipelineContext
from src.pipeline.pipeline import Pipeline
from src.pipeline.steps import CallableStep

_STEP_NAME = "build_knowledge_graph"
_INPUT_KEYS = ("symbol_results", "interface_results", "foundation_results", "architecture_graph")
_OUTPUT_KEY = "knowledge_graph"

_DEFAULT_STEP_NAMES = [
    "require_single_repository",
    "clone_repositories",
    "enumerate_files",
    "parse_files",
    "select_successful_parse_results",
    "extract_imports",
    "extract_ast",
    "extract_symbols",
    "extract_architecture",
    "extract_interfaces",
    "extract_foundation",
    "analyze_architecture",
    "analyze_complexity",
    "analyze_dependencies",
    "analyze_documentation",
    "analyze_metrics",
    "analyze_quality",
    "analyze_security",
    "analyze_tests",
    "build_architecture_graph",
    "build_dependency_graph",
]

_SOURCES = {
    "pkg/a.py": (
        "class Shape:\n    def area(self):\n        return 0\n\n\ndef helper():\n    return 1\n"
    ),
    "pkg/b.py": (
        "from abc import ABC, abstractmethod\n\n\n"
        "class Base(ABC):\n    @abstractmethod\n    def run(self): ...\n"
    ),
}
_CONFLICTING_SOURCES = {"m.py": "class Foo:\n    pass\n\n\ndef Foo():\n    return 1\n"}


def _context_values(sources: dict[str, str]) -> dict[str, Any]:
    """Real extraction results and a real architecture graph for in-memory `sources`."""
    parser = PythonParser()
    parse_results = [parser.parse(relative_path=p, content=c) for p, c in sources.items()]
    assert all(result.succeeded for result in parse_results)
    architecture_results = tuple(
        StructuralArchitectureExtractor().extract(result) for result in parse_results
    )
    return {
        "symbol_results": tuple(StructuralSymbolExtractor().extract(r) for r in parse_results),
        "interface_results": tuple(
            StructuralInterfaceExtractor().extract(r) for r in parse_results
        ),
        "foundation_results": tuple(
            StructuralFoundationExtractor().extract(r) for r in parse_results
        ),
        "architecture_graph": StructuralArchitectureGraphBuilder().build(architecture_results),
    }


def _direct_graph(values: dict[str, Any]) -> KnowledgeGraph:
    """What calling the real builder directly, with keywords, produces for `values`."""
    return StructuralKnowledgeGraphBuilder().build(
        symbol_results=values["symbol_results"],
        interface_results=values["interface_results"],
        foundation_results=values["foundation_results"],
        architecture_graph=values["architecture_graph"],
    )


class _RecordingBuilder(KnowledgeGraphBuilder):
    """A real `KnowledgeGraphBuilder` that records exactly how `build` was called.

    `build` takes `*args, **kwargs` so a test can tell positional from keyword calls, and can tell
    an omitted keyword from one passed with its default value.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        self.result = KnowledgeGraph(nodes=(), relations=())

    def build(self, *args: Any, **kwargs: Any) -> KnowledgeGraph:  # type: ignore[override]
        self.calls.append((args, kwargs))
        return self.result


class _RaisingBuilder(KnowledgeGraphBuilder):
    """A real `KnowledgeGraphBuilder` whose `build` raises `error`."""

    def __init__(self, error: BaseException) -> None:
        self.error = error

    def build(self, *args: Any, **kwargs: Any) -> KnowledgeGraph:  # type: ignore[override]
        raise self.error


def _install_builder(monkeypatch: pytest.MonkeyPatch, builder: KnowledgeGraphBuilder) -> None:
    """Make the factory construct `builder` instead of the concrete structural builder."""
    monkeypatch.setattr(step_module, "StructuralKnowledgeGraphBuilder", lambda: builder)


def _sentinel_values() -> dict[str, object]:
    """Four distinct, unrelated objects, one per input key, to track which goes where."""
    return {key: object() for key in _INPUT_KEYS}


# -- Factory and metadata (1, 2) -------------------------------------------------------------


def test_the_factory_returns_a_synchronous_callable_step_named_build_knowledge_graph() -> None:
    """The factory returns a `CallableStep` (and therefore a `Step`) with the expected metadata."""
    step = build_knowledge_graph_step()
    assert isinstance(step, CallableStep)
    assert isinstance(step, Step)
    assert step.name == _STEP_NAME
    assert step._is_async is False  # type: ignore[attr-defined]


def test_the_input_keys_and_output_key_are_exact() -> None:
    """Four input keys, in this order, and one output key -- nothing else."""
    step = build_knowledge_graph_step()
    assert step._input_keys == _INPUT_KEYS  # type: ignore[attr-defined]
    assert step._output_key == _OUTPUT_KEY  # type: ignore[attr-defined]
    assert "pattern_results" not in step._input_keys  # type: ignore[attr-defined]


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", _INPUT_KEYS)
async def test_every_declared_input_key_is_required(missing: str) -> None:
    """A context lacking any one of the four keys fails with `NotFoundError` naming that key."""
    values = _context_values(_SOURCES)
    del values[missing]
    context = PipelineContext(values=values)
    with pytest.raises(NotFoundError) as excinfo:
        await build_knowledge_graph_step().execute(context)
    assert excinfo.value.details == {"key": missing}
    assert not context.has(_OUTPUT_KEY)


@pytest.mark.asyncio
async def test_exactly_the_four_inputs_suffice_and_exactly_one_key_is_written() -> None:
    """With the four keys present (and no `pattern_results`), only `knowledge_graph` is added."""
    values = _context_values(_SOURCES)
    context = PipelineContext(values=dict(values))
    await build_knowledge_graph_step().execute(context)
    assert set(context.values) == {*values, _OUTPUT_KEY}
    assert all(context.values[key] is values[key] for key in values)


# -- Keyword adapter (3, 4, 5) ---------------------------------------------------------------


def test_the_builders_build_method_is_keyword_only_so_the_adapter_is_needed() -> None:
    """The real builder rejects positional arguments, which is all `CallableStep` can supply."""
    values = _context_values(_SOURCES)
    with pytest.raises(TypeError):
        StructuralKnowledgeGraphBuilder().build(  # type: ignore[call-arg, misc]
            *(values[key] for key in _INPUT_KEYS)
        )


@pytest.mark.asyncio
async def test_a_step_bound_directly_to_the_builder_fails_where_the_adapter_succeeds() -> None:
    """Binding `build` straight into a `CallableStep` fails at run time; the factory's step works."""
    values = _context_values(_SOURCES)
    direct = CallableStep(
        "direct",
        StructuralKnowledgeGraphBuilder().build,
        input_keys=_INPUT_KEYS,
        output_key=_OUTPUT_KEY,
    )
    with pytest.raises(TypeError):
        await direct.execute(PipelineContext(values=dict(values)))

    context = PipelineContext(values=dict(values))
    await build_knowledge_graph_step().execute(context)
    assert isinstance(context.require(_OUTPUT_KEY), KnowledgeGraph)


@pytest.mark.asyncio
async def test_the_adapter_calls_build_with_keywords_despite_the_positional_step_interface(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The four positional values reach `build` as the matching keywords, with no positionals."""
    builder = _RecordingBuilder()
    _install_builder(monkeypatch, builder)
    values = _sentinel_values()

    await build_knowledge_graph_step().execute(PipelineContext(values=dict(values)))

    ((args, kwargs),) = builder.calls
    assert args == ()
    assert set(kwargs) == set(_INPUT_KEYS)
    for key in _INPUT_KEYS:
        assert kwargs[key] is values[key]


@pytest.mark.asyncio
async def test_pattern_results_is_not_passed_so_the_builder_default_applies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`pattern_results` is omitted entirely, and a context never needs to hold it."""
    builder = _RecordingBuilder()
    _install_builder(monkeypatch, builder)
    context = PipelineContext(values=dict(_sentinel_values()))
    assert not context.has("pattern_results")

    await build_knowledge_graph_step().execute(context)

    ((_, kwargs),) = builder.calls
    assert "pattern_results" not in kwargs


@pytest.mark.asyncio
async def test_a_real_run_with_no_pattern_results_matches_the_builders_own_default() -> None:
    """Omitting `pattern_results` is the same as the builder's explicit default of `()`."""
    values = _context_values(_SOURCES)
    context = PipelineContext(values=dict(values))
    await build_knowledge_graph_step().execute(context)
    explicit = StructuralKnowledgeGraphBuilder().build(
        symbol_results=values["symbol_results"],
        pattern_results=(),
        interface_results=values["interface_results"],
        foundation_results=values["foundation_results"],
        architecture_graph=values["architecture_graph"],
    )
    assert context.require(_OUTPUT_KEY) == explicit


@pytest.mark.asyncio
async def test_architecture_graph_is_passed_through_unchanged() -> None:
    """The very object under `architecture_graph` reaches the builder, and is not altered."""
    recording = _RecordingBuilder()
    values = _context_values(_SOURCES)
    architecture_graph = values["architecture_graph"]
    nodes_before = architecture_graph.nodes

    step = CallableStep(
        _STEP_NAME,
        _knowledge_graph_func(recording),
        input_keys=_INPUT_KEYS,
        output_key=_OUTPUT_KEY,
    )
    await step.execute(PipelineContext(values=dict(values)))

    ((_, kwargs),) = recording.calls
    assert kwargs["architecture_graph"] is architecture_graph
    assert architecture_graph.nodes == nodes_before


def test_the_adapter_forwards_each_positional_value_to_its_matching_keyword() -> None:
    """`_knowledge_graph_func`'s positional order is exactly `input_keys` order."""
    recording = _RecordingBuilder()
    values = _sentinel_values()
    result = _knowledge_graph_func(recording)(*(values[key] for key in _INPUT_KEYS))  # type: ignore[arg-type]
    ((args, kwargs),) = recording.calls
    assert args == ()
    assert {key: kwargs[key] is values[key] for key in _INPUT_KEYS} == dict.fromkeys(
        _INPUT_KEYS, True
    )
    assert result is recording.result


# -- Successful build (6) --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_successful_build_writes_the_knowledge_graph_under_knowledge_graph() -> None:
    """The graph equals what the real builder gives for the same inputs, packages included."""
    values = _context_values(_SOURCES)
    context = PipelineContext(values=dict(values))

    returned = await build_knowledge_graph_step().execute(context)

    assert returned is context
    graph = context.require(_OUTPUT_KEY)
    assert isinstance(graph, KnowledgeGraph)
    assert graph == _direct_graph(values)
    assert graph.to_mapping() == _direct_graph(values).to_mapping()
    kinds = {node.kind for node in graph.nodes}
    assert {
        KnowledgeNodeKind.ENTITY,
        KnowledgeNodeKind.SYMBOL,
        KnowledgeNodeKind.INTERFACE,
        KnowledgeNodeKind.CAPABILITY,
        KnowledgeNodeKind.PACKAGE,
    } <= kinds
    assert KnowledgeNodeKind.PATTERN not in kinds


@pytest.mark.asyncio
async def test_a_successful_build_runs_inside_a_pipeline() -> None:
    """The step participates in `Pipeline.run` like any other and appears in its outcomes."""
    values = _context_values(_SOURCES)
    result = await Pipeline("opt-in", [build_knowledge_graph_step()]).run(
        PipelineContext(values=dict(values))
    )
    assert result.step_names() == (_STEP_NAME,)
    assert result.context.require(_OUTPUT_KEY) == _direct_graph(values)


# -- Failure contract (7) --------------------------------------------------------------------


class _Boom(Exception):
    """A test-local ordinary exception."""


class _Interrupt(BaseException):
    """A test-local `BaseException` that is not an `Exception`."""


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [
        ValidationError("rejected", details={"collision_count": 1}),
        _Boom("ordinary failure"),
        _Interrupt("not an Exception"),
    ],
    ids=["validation-error", "ordinary-exception", "base-exception"],
)
async def test_the_step_does_not_catch_suppress_or_transform_builder_exceptions(
    monkeypatch: pytest.MonkeyPatch, error: BaseException
) -> None:
    """Whatever the builder raises leaves `execute` as the very same object, writing nothing."""
    _install_builder(monkeypatch, _RaisingBuilder(error))
    context = PipelineContext(values=dict(_sentinel_values()))
    before = set(context.values)

    with pytest.raises(type(error)) as excinfo:
        await build_knowledge_graph_step().execute(context)

    assert excinfo.value is error
    assert set(context.values) == before
    assert not context.has(_OUTPUT_KEY)


@pytest.mark.asyncio
async def test_a_builder_exception_becomes_the_normal_step_execution_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Through `Pipeline.run`, the failure is wrapped exactly as for every other step."""
    error = ValidationError("rejected", details={"collision_count": 3})
    _install_builder(monkeypatch, _RaisingBuilder(error))
    earlier = CallableStep("earlier", lambda: "ok", output_key="earlier_output")
    context = PipelineContext(values=dict(_sentinel_values()))

    with pytest.raises(StepExecutionError) as excinfo:
        await Pipeline("opt-in", [earlier, build_knowledge_graph_step()]).run(context)

    assert excinfo.value.__cause__ is error
    assert excinfo.value.details == {
        "pipeline": "opt-in",
        "failed_step": _STEP_NAME,
        "completed_steps": ["earlier"],
    }
    assert str(excinfo.value) == f"pipeline 'opt-in' failed at step '{_STEP_NAME}': rejected"
    # Fail-fast: no result, nothing written for this step, earlier outputs left on the context.
    assert not context.has(_OUTPUT_KEY)
    assert context.require("earlier_output") == "ok"
    assert all(context.has(key) for key in _INPUT_KEYS)


@pytest.mark.asyncio
async def test_a_real_identity_collision_fails_fast_with_the_builders_own_diagnostic() -> None:
    """A valid-source class/function name clash is the builder's `ValidationError`, unchanged."""
    values = _context_values(_CONFLICTING_SOURCES)
    context = PipelineContext(values=dict(values))

    with pytest.raises(StepExecutionError) as excinfo:
        await Pipeline("opt-in", [build_knowledge_graph_step()]).run(context)

    cause = excinfo.value.__cause__
    assert isinstance(cause, ValidationError)
    assert str(cause) == (
        "KnowledgeGraph: nodes must not contain duplicate identifiers; "
        "2 colliding identifier(s) rejected: 'capability:m.py::Foo', 'symbol:m.py::Foo'"
    )
    assert cause.details["collision_count"] == 2
    assert str(cause) in str(excinfo.value)
    assert not context.has(_OUTPUT_KEY)


@pytest.mark.asyncio
async def test_a_failed_extraction_result_is_rejected_by_the_builder_not_the_step() -> None:
    """The builder's existing successful-extraction check is not bypassed or pre-empted."""
    from src.extractors.symbols.base import SymbolExtractionResult

    values = _context_values(_SOURCES)
    values["symbol_results"] = (
        *values["symbol_results"],
        SymbolExtractionResult.failed(relative_path="bad.py", error_message="boom"),
    )
    with pytest.raises(ValidationError):
        await build_knowledge_graph_step().execute(PipelineContext(values=values))


# -- No retained state (8) -------------------------------------------------------------------


def test_the_module_defines_no_mutable_module_state_classes_or_globals() -> None:
    """No module-level mutable containers, no `global` statements, no registry-like classes."""
    mutable = {
        name: type(value).__name__
        for name, value in vars(step_module).items()
        if not name.startswith("__") and isinstance(value, (list, dict, set, bytearray))
    }
    assert mutable == {}
    tree = ast.parse(inspect.getsource(step_module))
    assert [node for node in ast.walk(tree) if isinstance(node, ast.Global)] == []
    assert [node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)] == []
    public = [name for name in vars(step_module) if not name.startswith("_")]
    assert "build_knowledge_graph_step" in public


@pytest.mark.asyncio
async def test_repeated_runs_of_one_step_retain_no_state_between_them() -> None:
    """Interleaved runs over different inputs give the same answers as fresh runs would."""
    step = build_knowledge_graph_step()
    values_a = _context_values(_SOURCES)
    values_b = _context_values(_CONFLICTING_SOURCES | {"pkg/c.py": "def other():\n    return 2\n"})

    context_a1 = PipelineContext(values=dict(values_a))
    context_a1_keys = set(context_a1.values)
    await step.execute(context_a1)
    context_b = PipelineContext(values=dict(values_b))
    with pytest.raises(ValidationError):
        await step.execute(context_b)
    context_a2 = PipelineContext(values=dict(values_a))
    await step.execute(context_a2)

    assert context_a2.require(_OUTPUT_KEY) == context_a1.require(_OUTPUT_KEY)
    assert context_a2.require(_OUTPUT_KEY) == _direct_graph(values_a)
    assert set(context_a1.values) == {*context_a1_keys, _OUTPUT_KEY}
    assert not context_b.has(_OUTPUT_KEY)


def test_each_factory_call_builds_an_independent_step() -> None:
    """Two calls share nothing: distinct steps with distinct bound callables."""
    first, second = build_knowledge_graph_step(), build_knowledge_graph_step()
    assert first is not second
    assert first._func is not second._func  # type: ignore[attr-defined]
    assert first.name == second.name


# -- The default composition is untouched (9) ------------------------------------------------


def test_the_default_composition_is_unchanged_and_does_not_contain_the_step(tmp_path: Path) -> None:
    """`build_analysis_steps` still returns exactly its twenty-one steps, in the pinned order."""
    config = AppConfig(raw={"repository": {"workspace_root": str(tmp_path)}})
    steps = build_analysis_steps(config)
    assert [step.name for step in steps] == _DEFAULT_STEP_NAMES
    assert _STEP_NAME not in [step.name for step in steps]
    assert _OUTPUT_KEY not in [step._output_key for step in steps]  # type: ignore[attr-defined]
    assert steps[-1].name == "build_dependency_graph"


def test_the_default_modules_do_not_reference_the_opt_in_step() -> None:
    """Neither the analysis composition nor the CLI imports or mentions the new step."""
    for module in (analysis_steps_module, cli_main_module):
        source = inspect.getsource(module)
        assert "knowledge_graph_step" not in source
        assert "build_knowledge_graph_step" not in source
        assert "StructuralKnowledgeGraphBuilder" not in source


def test_the_opt_in_step_composes_with_the_default_steps_in_a_valid_pipeline(
    tmp_path: Path,
) -> None:
    """Appending the step to the default steps gives unique names and a valid `Pipeline`."""
    config = AppConfig(raw={"repository": {"workspace_root": str(tmp_path)}})
    steps = [*build_analysis_steps(config), build_knowledge_graph_step()]
    pipeline = Pipeline("opt-in", steps)
    names = [step.name for step in pipeline.steps]
    assert len(names) == len(set(names))
    assert names[:-1] == _DEFAULT_STEP_NAMES
    assert names[-1] == _STEP_NAME
