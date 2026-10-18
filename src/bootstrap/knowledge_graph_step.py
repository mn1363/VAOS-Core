"""Opt-in Knowledge Graph pipeline step: a `CallableStep` factory for explicit, custom compositions.

`build_knowledge_graph_step` is this module's entire public surface: one function returning one
`CallableStep` that a caller deliberately appends to a custom sequence of steps -- typically
`bootstrap(config, extra_steps=[*build_analysis_steps(config), build_knowledge_graph_step()])`, or
any `Pipeline` the caller assembles. It does not construct a `Pipeline`, does not call
`Pipeline.run`, and is **not** part of `build_analysis_steps`: the default real-repository analysis
composition, its step order and count, and the CLI's `--analyze` behavior are unchanged by this
module's existence. Nothing in `src/bootstrap/analysis_steps.py` or `src/cli/main.py` imports it.

**Why it is opt-in.** The Knowledge Graph builder can reject a build (see
`graph.knowledge.structural.StructuralKnowledgeGraphBuilder.build`): a non-equivalent `SYMBOL` or
`CAPABILITY` identity group, or any `INTERFACE`/`PATTERN` collision, raises one `ValidationError`
and returns no graph. Source constructs such as a top-level class and function sharing a name can
trigger this in an otherwise valid repository. `Pipeline.run` is all-or-nothing -- a step that
raises ends the run with a `StepExecutionError` and no `PipelineResult` -- so wiring this step into
the default composition would turn such a repository's currently successful analysis into a
failed one. Whether to do that is a separate decision, to be made after broader evidence about how
often valid repositories hit those collisions. Until then, only a caller who explicitly asks for a
Knowledge Graph accepts that behavior.

**Dependencies and ordering.** The step reads four context keys, written by existing steps of
`build_analysis_steps`, and writes one:

- `symbol_results`, from `extract_symbols`;
- `interface_results`, from `extract_interfaces`;
- `foundation_results`, from `extract_foundation`;
- `architecture_graph`, from `build_architecture_graph`;
- writes `knowledge_graph`.

A caller must therefore append it **after all of these input-producing steps**; appending it last,
after `build_dependency_graph`, satisfies that and leaves the rest of the composition untouched.
`CallableStep` requires every declared input key, and `PipelineContext` has no optional-key support
(and is not extended here), so the step requires `architecture_graph` to be present. That matches
its intended standard-composition use; a custom composition that has no architecture steps would
fail with `NotFoundError` naming the missing key, and would need its own step instead.

**Keyword-only adapter.** `CallableStep` calls its function positionally, as `func(*args)`, in
`input_keys` order, but `KnowledgeGraphBuilder.build` takes keyword-only parameters. A small
closure, `_knowledge_graph_func`, receives the four positional values and calls `build` with the
right keywords -- the same plain-closure convention `analysis_steps._clone_repository_func`
follows. The positional order of the adapter's parameters and the order of `input_keys` are kept
identical, and are pinned by tests.

**No pattern results.** There is no concrete Pattern Extractor, so no `pattern_results` context
key exists in the standard composition. The adapter does not pass `pattern_results` at all, so the
builder's own default (`()`) applies. When a concrete Pattern Extractor is eventually wired, this
step needs its own, separately decided change; until then `PATTERN` collisions cannot occur.

**Failure behavior.** The step does not catch, suppress, or transform anything the builder raises:
a `ValidationError` (a failed extraction input, or a rejected identity group) propagates unchanged,
and `Pipeline.run` wraps it in the normal `StepExecutionError` (original exception as `__cause__`,
no later step run). There is no failure-as-data contract. On failure the step writes nothing, so no
`knowledge_graph` key exists; a caller that supplied its own `PipelineContext` still holds whatever
earlier steps wrote into it.

**No new abstraction.** No registry, service locator, dependency, module-level mutable state, or
second pipeline framework: the concrete builder is constructed once per factory call and bound
into the closure, exactly like `build_analysis_steps` binds its own concrete builders.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from src.extractors.foundation.base import FoundationExtractionResult
from src.extractors.interfaces.base import InterfaceExtractionResult
from src.extractors.symbols.base import SymbolExtractionResult
from src.graph.architecture.base import ArchitectureGraph
from src.graph.knowledge.base import KnowledgeGraph, KnowledgeGraphBuilder
from src.graph.knowledge.structural import StructuralKnowledgeGraphBuilder
from src.pipeline.steps import CallableStep


def _knowledge_graph_func(
    builder: KnowledgeGraphBuilder,
) -> Callable[
    [
        Sequence[SymbolExtractionResult],
        Sequence[InterfaceExtractionResult],
        Sequence[FoundationExtractionResult],
        ArchitectureGraph,
    ],
    KnowledgeGraph,
]:
    """Bind `builder` into a positional callable suitable for `CallableStep`.

    `KnowledgeGraphBuilder.build` is keyword-only, while `CallableStep` calls its function as
    `func(*args)`. This closure is the explicit adapter between the two: its parameters, in order,
    are exactly the step's `input_keys`, and it forwards each as the keyword `build` expects.
    `pattern_results` is deliberately not forwarded, so the builder's own default applies. The
    builder's exceptions are not caught here.

    Mirrors `analysis_steps._clone_repository_func`'s own closure-factory pattern. The builder
    arrives already constructed.

    Args:
        builder: Already-constructed `KnowledgeGraphBuilder` each call is delegated to.

    Returns:
        A sync callable `(symbol_results, interface_results, foundation_results,
        architecture_graph) -> KnowledgeGraph`.
    """

    def _build(
        symbol_results: Sequence[SymbolExtractionResult],
        interface_results: Sequence[InterfaceExtractionResult],
        foundation_results: Sequence[FoundationExtractionResult],
        architecture_graph: ArchitectureGraph,
    ) -> KnowledgeGraph:
        return builder.build(
            symbol_results=symbol_results,
            interface_results=interface_results,
            foundation_results=foundation_results,
            architecture_graph=architecture_graph,
        )

    return _build


def build_knowledge_graph_step() -> CallableStep:
    """Construct the opt-in `build_knowledge_graph` step for an explicitly built composition.

    The step reads `symbol_results`, `interface_results`, `foundation_results`, and
    `architecture_graph` from the `PipelineContext` (all four are required, per `CallableStep`'s
    own contract) and writes the resulting `KnowledgeGraph` under `knowledge_graph`. Append it
    only after the steps that produce those four keys -- see the module docstring. It is not part
    of `build_analysis_steps`, and nothing wires it in by default.

    Each call builds a fresh `StructuralKnowledgeGraphBuilder` and a fresh step; no state is
    shared between calls or between runs of one step.

    Returns:
        A synchronous `CallableStep` named `build_knowledge_graph`.

    Raises (when the returned step runs, never at construction):
        NotFoundError: If any of the four input keys is absent from the context.
        ValidationError: If the builder rejects its input -- a failed extraction result, or any
            rejected identity group -- exactly as `StructuralKnowledgeGraphBuilder.build` raises
            it. Neither is caught or altered here; `Pipeline.run` wraps it in `StepExecutionError`.
    """
    return CallableStep(
        "build_knowledge_graph",
        _knowledge_graph_func(StructuralKnowledgeGraphBuilder()),
        input_keys=(
            "symbol_results",
            "interface_results",
            "foundation_results",
            "architecture_graph",
        ),
        output_key="knowledge_graph",
    )
