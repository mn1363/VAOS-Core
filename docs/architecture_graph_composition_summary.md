# Architecture Graph Composition / Pipeline Integration — Milestone Summary

Baseline: `e777d97` ("Add structural architecture graph builder"), `main`.

## Purpose

`StructuralArchitectureGraphBuilder` (frozen, `src/graph/architecture/structural.py`) existed but
nothing in the real-repository analysis composition consumed it. This milestone appends exactly one
step to `build_analysis_steps()` in `src/bootstrap/analysis_steps.py` so that every `--analyze`
run also assembles the repository's `ArchitectureGraph` from the `architecture_results` it already
produces. It is a composition milestone only: no builder, extractor, path, or parsing behavior
changed.

## Exact 15-step sequence

The three default steps from `bootstrap.wiring.build_application`, followed by the twelve steps
`build_analysis_steps()` now returns:

```text
 1. collect
 2. unpack_repositories
 3. persist_repositories
 4. require_single_repository
 5. clone_repositories
 6. enumerate_files
 7. parse_files
 8. select_successful_parse_results
 9. extract_imports
10. extract_ast
11. extract_symbols
12. extract_architecture
13. extract_interfaces
14. extract_foundation
15. build_architecture_graph      <- new
```

Steps 1-14 keep their names, order, and implementations. Only step 15 is appended.

## New context key

`architecture_graph`: an `ArchitectureGraph`, written by `build_architecture_graph`.
`architecture_results` is still written by `extract_architecture` and is neither renamed,
replaced, nor mutated.

## Builder invocation

`build_architecture_graph` is a synchronous `CallableStep`:

- name: `build_architecture_graph`
- `input_keys=("architecture_results",)`
- `output_key="architecture_graph"`
- callable: `StructuralArchitectureGraphBuilder().build`, constructed directly and locally in
  `build_analysis_steps`, like every extractor there
- `is_async=False`

## Why failed architecture results are not filtered

`architecture_results` is not filtered before the builder. The builder's own
`require_successful_extractions()` remains the authoritative contract. In this pipeline the check
can never fire: `StructuralArchitectureExtractor.extract` either returns a successful result or
raises `ValidationError` for a failed `ParseResult`, and `select_successful_parse_results` already
removes failed parses before extraction. A pre-filter would be dead code and could mask a real
defect that the builder would otherwise report.

## Default flow unchanged

`wiring.py` and `src/cli/main.py` are untouched. Without `--analyze`, `_run` still calls
`bootstrap(config)` with no `extra_steps`, so the default flow is still exactly
`collect`, `unpack_repositories`, `persist_repositories` (3 steps), and
`build_analysis_steps` is still never constructed.

## `--analyze` output

`--analyze` now reports 15 steps instead of 14, because `_format_result` prints
`result.step_count` and `result.step_names()`, and the new step is one of them. No CLI code
changed for this. `_format_result` still does not render `result.context`, so graph contents are
not printed.

## No output, persistence, or API

The graph exists only as a value in `PipelineResult.context` for programmatic callers of
`bootstrap()`. This milestone adds no graph printing, persistence, export, API endpoint, or CLI
exposure. `ArchitectureGraph.to_mapping()` remains unused by production code.

## Windows limitation remains accepted

`_enumerate_files` yields platform-native (backslash-separated on Windows) relative paths, while
`StructuralArchitectureExtractor` derives `package_path` by splitting on `/` only. On Windows the
real graph therefore collapses to a single root node with no edges. This limitation is unchanged
and deliberately not fixed here, as recorded in `docs/graph_architecture_summary.md`. The
integration tests keep their platform-aware behavior: exact nested-graph assertions run only when
`os.sep == "/"`, and every other assertion derives from the real units' own values.

## Files changed

Source (1):

- `src/bootstrap/analysis_steps.py`: import the builder, add the step, append it to the returned
  list, update the "eleven" wording in its docstrings to "twelve".

Tests (4):

- `tests/unit/bootstrap/test_analysis_steps.py`: expected contract 11 to 12 steps; new tests for
  last position, `CallableStep` type, `input_keys`, `output_key`, `is_async`, bound builder, and
  the previous 11 steps' exact names and order.
- `tests/unit/cli/test_main.py`: the `--analyze` step-summary test now expects 15 steps and the
  new name (renamed from `..._fourteen_step_summary` to `..._fifteen_step_summary`).
- `tests/integration/test_real_repository_analysis.py`: expected sequence gains
  `build_architecture_graph`.
- `tests/integration/test_architecture_graph.py`: the "no step is added" premise removed; the
  helper asserts the exact 15-step sequence; new tests assert the context's `architecture_graph`
  is an `ArchitectureGraph` equal to `StructuralArchitectureGraphBuilder().build(
  architecture_results)`, that `architecture_results` remains available and unchanged, and that
  two independent runs give equal graphs.

Docs (1, new): this file.

## Verification

Run on Linux with CPython 3.13.13 (the pinned `requires-python = ">=3.13"` interpreter).

| Command | Result |
| --- | --- |
| `python -m pytest tests/unit/bootstrap/test_analysis_steps.py tests/unit/cli/test_main.py tests/integration/test_real_repository_analysis.py tests/integration/test_architecture_graph.py -q` | 60 passed |
| `python -m pytest -q` | 1524 passed, 0 failed, 1 pre-existing unrelated warning (`starlette`/`httpx`). 1519 (baseline) + 5 new tests |
| `python -m mypy src` | Success: no issues found in 129 source files |
| `python -m ruff check src tests` | 1 pre-existing, unrelated finding: `UP046` in `src/domain/interfaces.py` (file untouched); no findings in changed files |
| `git diff --check` | clean |

## Architectural red lines preserved

- No DI framework, container, or service locator: the builder is constructed directly in a plain
  function.
- No registry, no dynamic discovery, no parser dispatch change: the parser tuple is untouched.
- No new graph DTO, abstraction, service, or top-level package.
- No persistence, export, API exposure, or graph printing.
- No `DependencyGraphBuilder`, `CallGraphBuilder`, or `KnowledgeGraphBuilder` work.
- No frozen-contract change: `src/graph/architecture/structural.py`, `base.py`,
  `src/extractors/**`, `src/analyzers/**`, `src/repository/**`, `src/cli/main.py`, and
  `src/bootstrap/wiring.py` are byte-for-byte unchanged, as are all earlier milestone summaries.
