# Opt-in Knowledge Graph step (summary)

**Status:** implemented as an explicit, opt-in `CallableStep` factory. It is **not** part of the
default analysis composition, and it changes neither the CLI nor any pipeline contract.

- `src/bootstrap/knowledge_graph_step.py` — `build_knowledge_graph_step()`.
- `tests/unit/bootstrap/test_knowledge_graph_step.py` — unit tests (real `KnowledgeGraphBuilder`
  fakes, real extraction results, no I/O).
- `tests/integration/test_knowledge_graph_step.py` — an explicitly constructed pipeline over
  temporary local Git repositories (real `git`, real parsers and extractors, no network; skipped
  only if `git` is unavailable).

The builder itself, `graph.knowledge.structural.StructuralKnowledgeGraphBuilder`, and its duplicate
identity policy are unchanged; see `docs/knowledge_graph_builder_summary.md`.

## Using it

The factory returns one `CallableStep`. A caller who wants a Knowledge Graph appends it to a custom
sequence of steps, after every step that produces its inputs. The simplest composition appends it
last, after the default analysis steps:

```python
from src.bootstrap.analysis_steps import build_analysis_steps
from src.bootstrap.knowledge_graph_step import build_knowledge_graph_step
from src.bootstrap.wiring import bootstrap

result = await bootstrap(
    config,
    extra_steps=[*build_analysis_steps(config), build_knowledge_graph_step()],
)
graph = result.context.require("knowledge_graph")
```

The factory does not construct a `Pipeline` and does not run anything. Each call builds a fresh
`StructuralKnowledgeGraphBuilder` and a fresh step; nothing is shared between calls or between
runs of one step. There is no registry, service locator, dependency, module-level mutable state, or
second pipeline framework.

## Context dependencies and output

| Direction | Context key | Written by |
|---|---|---|
| reads | `symbol_results` | `extract_symbols` |
| reads | `interface_results` | `extract_interfaces` |
| reads | `foundation_results` | `extract_foundation` |
| reads | `architecture_graph` | `build_architecture_graph` |
| writes | `knowledge_graph` | this step |

The step is named `build_knowledge_graph` and is synchronous. It must come after all four
producers. `dependency_graph` and `import_results` are not consumed, so the position relative to
`build_dependency_graph` does not matter.

`CallableStep` requires every declared input key, and `PipelineContext` has no optional-key
support (it is not extended here). The step therefore **requires `architecture_graph`** — which is
what its intended standard composition provides. A composition without the architecture steps fails
with `NotFoundError` naming the missing key and would need its own step.

## Why a keyword-only adapter

`CallableStep` calls its function positionally, as `func(*args)` in `input_keys` order.
`KnowledgeGraphBuilder.build` takes keyword-only parameters, so binding `.build` directly fails at
run time with `TypeError` (a test demonstrates this). The module therefore binds the builder into a
small closure, `_knowledge_graph_func`, whose positional parameters are exactly the four input keys,
in order, and which forwards each as the keyword `build` expects. This follows the same
plain-closure convention as `analysis_steps._clone_repository_func`. The order of the closure's
parameters and of `input_keys` are pinned by tests.

## No pattern results

There is no concrete Pattern Extractor, so the standard composition has no `pattern_results` key.
The adapter does not pass `pattern_results` at all; the builder's own default (`()`) applies, and
`PATTERN` collisions cannot occur. When a concrete Pattern Extractor is wired, this step needs its
own, separately decided change.

## Fail-fast behavior

The step does not catch, suppress, or transform anything the builder raises. The builder can reject
a build: a failed extraction input, a non-equivalent `SYMBOL`/`CAPABILITY` identity group, any
`INTERFACE`/`PATTERN` collision, or a package identifier collision. Each is one `ValidationError`,
which `Pipeline.run` wraps in the normal `StepExecutionError` — the original exception as
`__cause__`, `details` naming the pipeline, the failed step, and the steps that had completed, and
no later step run. There is no failure-as-data contract.

Two consequences follow from the existing pipeline contract, not from this step:

- **All-or-nothing.** A failed run returns no `PipelineResult`, so a caller of `bootstrap` receives
  none of the outputs computed before the failure (extractions, architecture graph, dependency
  graph).
- **A caller-supplied context keeps them.** Steps mutate the context in place, so a caller that
  passes its own `PipelineContext` still holds whatever earlier steps wrote; `knowledge_graph` is
  simply absent. This is covered by the integration test.

The remaining collision cases occur in valid repositories: for example a top-level class and
function that share a name in Python, a class and a `const` in TypeScript, or a redefined `ABC`
(an `INTERFACE` collision). Such a repository fails an opted-in run; it still succeeds in the
default composition (also covered by the integration test).

## Why it is absent from the default composition

`build_analysis_steps` is unchanged: still thirteen steps, the same order, the same names, the same
context keys, and the same `--analyze` output. Appending a step that can reject a valid repository
would turn that repository's currently successful analysis into a failed one, because the pipeline
is all-or-nothing. Whether the default composition should accept that, or whether a failure-policy
contract is needed first, is a separate decision. It should be made after broader evidence on how
often valid repositories hit these collisions; collision frequency outside the repository's own
files has not been measured.

## CLI

This change does not touch `src/cli/main.py`, its arguments, or its output. No CLI flag exists for
the opt-in step; adding one would be a separate contract decision. Nothing in
`src/bootstrap/analysis_steps.py` or `src/cli/main.py` imports or mentions the new module, and a
unit test asserts that.
