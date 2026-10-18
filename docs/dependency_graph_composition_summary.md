# Dependency Graph Composition / Pipeline Integration — Milestone Summary

Baseline: `b375fe5` ("Add structural dependency graph builder"), `main`.

## Purpose

`StructuralDependencyGraphBuilder` (frozen, `src/graph/dependency/structural.py`) existed but
nothing in the real-repository analysis composition consumed it. This milestone appends exactly one
step to `build_analysis_steps()` in `src/bootstrap/analysis_steps.py` so that every `--analyze`
run also assembles the repository's `DependencyGraph` from the `import_results` it already
produces. It is a composition milestone only: no builder, extractor, path, or parsing behavior
changed.

## Exact 16-step sequence

The three default steps from `bootstrap.wiring.build_application`, followed by the thirteen steps
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
15. build_architecture_graph
16. build_dependency_graph        <- new
```

Steps 1-15 keep their names, order, and implementations. Only step 16 is appended.
`build_architecture_graph` remains the 15th step; it is no longer the final one.

## New context key

`dependency_graph`: a `DependencyGraph`, written by `build_dependency_graph`. `import_results` is
still written by `extract_imports` and is neither renamed, replaced, nor mutated. `architecture_graph`
and every other earlier context key are still present.

## Builder invocation

`build_dependency_graph` is a synchronous `CallableStep` (not a `MapStep`):

- name: `build_dependency_graph`
- `input_keys=("import_results",)`
- `output_key="dependency_graph"`
- callable: `StructuralDependencyGraphBuilder().build`, constructed directly and locally in
  `build_analysis_steps`, like every extractor and the architecture graph builder there
- `is_async=False`

## Why failed import results are not filtered

`import_results` is not filtered before the builder. The builder's own
`require_successful_extractions()` (called at the top of
`StructuralDependencyGraphBuilder.build`) remains the authoritative contract. In this pipeline the
check is not expected to fire: `StructuralImportExtractor.extract` either returns a successful
result or raises `ValidationError` for a failed `ParseResult` (via `require_successful_parse`), and
`select_successful_parse_results` already removes failed parses before extraction. A pre-filter
would be dead code and could mask a real defect that the builder would otherwise report.

## Default flow unchanged

`wiring.py` is untouched. `src/cli/main.py` changed in its module docstring only (the stale
step-count wording, "eleven-step" to "thirteen-step"); no CLI runtime code changed. Without
`--analyze`, `_run` still calls `bootstrap(config)` with no `extra_steps`, so the default flow is
still exactly `collect`, `unpack_repositories`, `persist_repositories` (3 steps), and
`build_analysis_steps` is still never constructed.

## `--analyze` output

`--analyze` now reports 16 steps instead of 15, because `_format_result` prints
`result.step_count` and `result.step_names()`, and the new step is one of them. No CLI code
changed for this. `_format_result` still does not render `result.context`, so graph contents are
not printed.

## No output, persistence, or API

The graph exists only as a value in `PipelineResult.context` for programmatic callers of
`bootstrap()`. This milestone adds no graph printing, persistence, export, API endpoint, or CLI
exposure.

## Files changed

Exactly eight files: seven modified, one new.

Source (2):

- `src/bootstrap/analysis_steps.py`: import the builder, add the step, append it to the returned
  list, update the "twelve" wording in its docstrings to "thirteen".
- `src/cli/main.py`: module-docstring step-count wording only.

Tests (5):

- `tests/unit/bootstrap/test_analysis_steps.py`: expected contract 12 to 13 steps; new tests for
  the exact input/output keys of every step, the previous twelve steps' names and order,
  `build_dependency_graph` being last and directly after `build_architecture_graph`, its
  `CallableStep` contract (type, `input_keys`, `output_key`, `is_async`, bound builder), and its
  execution against a `PipelineContext`; the architecture graph tests now address that step by
  its position (twelfth of the returned list) instead of "last".
- `tests/unit/cli/test_main.py`: the `--analyze` step-summary test now expects 16 steps and the
  new name (renamed from `..._fifteen_step_summary` to `..._sixteen_step_summary`), and asserts no
  `DependencyGraph` repr is printed.
- `tests/integration/test_real_repository_analysis.py`: expected sequence gains
  `build_dependency_graph`; the fixture repository gains one first-party import; a new test checks
  the `dependency_graph` written by the real composition; the determinism test also compares
  `dependency_graph`.
- `tests/integration/test_dependency_graph.py`: the "no dependency-graph step" premise removed;
  the helper asserts the exact 16-step sequence; the composition test asserts the written
  `dependency_graph` equals `StructuralDependencyGraphBuilder().build(import_results)`.
- `tests/integration/test_architecture_graph.py`: authorized correction of a task-scoping
  omission. This test hard-coded the 15-step flow. Now `_EXPECTED_STEP_NAMES` gains
  `build_dependency_graph`, the helper asserts 16 steps, and
  `test_composition_writes_architecture_graph_equal_to_direct_build` asserts
  `step_names()[-2] == "build_architecture_graph"` and `step_names()[-1] == "build_dependency_graph"`.
  `build_architecture_graph` stays the 15th step, and no architecture graph expectation changed.

Docs (1, new): this file.

## Verification

Run on Windows with CPython 3.13.14 (the pinned `requires-python = ">=3.13"` interpreter), against
the working tree on top of `b375fe5`.

| Command | Result |
| --- | --- |
| `python -m pytest -q -rs` over the five targeted files (`tests/unit/bootstrap/test_analysis_steps.py`, `tests/unit/cli/test_main.py`, `tests/integration/test_real_repository_analysis.py`, `tests/integration/test_dependency_graph.py`, `tests/integration/test_architecture_graph.py`) | 77 passed, 1 skipped (exit 0) |
| `python -m pytest -q -rs` (full suite) | 1746 passed, 2 failed, 1 skipped, 1 warning |
| `python -m mypy --strict src/` | Success: no issues found in 130 source files |
| `python -m ruff check src/ tests/` (ruff 0.15.20) | All checks passed |
| `git diff --check` | clean (only Git's informational LF-to-CRLF working-copy warnings) |

### Baseline comparison

The same full suite was run on a pristine extracted copy of baseline `b375fe5` (its tracked files
match the commit's tree blob-for-blob, apart from CRLF line endings in the working copy):

| Tree | Result |
| --- | --- |
| Baseline `b375fe5` | 1739 passed, 2 failed, 1 skipped, 1 warning |
| This milestone | 1746 passed, 2 failed, 1 skipped, 1 warning |

The difference is 7 additional passing tests (6 new in `tests/unit/bootstrap/test_analysis_steps.py`,
1 new in `tests/integration/test_real_repository_analysis.py`); the other changed tests were
extended or renamed in place.

The two failures are identical on the baseline and with this milestone's changes, both Windows
environment issues unrelated to composition, and are reported here, not fixed:

1. `tests/integration/test_architecture_extraction.py::test_architecture_is_extracted_from_a_real_local_repository`:
   `StopIteration` looking up `"pkg/widget.py"`. `_enumerate_files` yields backslash-separated
   relative paths on Windows, which the test's POSIX-style literal does not match.
2. `tests/unit/repository/test_git.py::test_default_branch_matches_the_origin`:
   `git symbolic-ref refs/remotes/origin/HEAD` exits 128 in the cloned test repository.

The one skip is also pre-existing and identical on both trees:
`tests/integration/test_architecture_graph.py` (exact path assertions assume POSIX separators).

## Architectural red lines preserved

- No DI framework, container, or service locator: the builder is constructed directly in a plain
  function.
- No registry, no dynamic discovery, no parser dispatch change: the parser tuple is untouched.
- No new graph DTO, abstraction, service, or top-level package.
- No persistence, export, API exposure, or graph printing.
- No frozen-contract change: `src/graph/dependency/base.py` and `structural.py`,
  `src/graph/architecture/**`, `src/parsers/**`, `src/extractors/**`, `src/analyzers/**`,
  `src/domain/**`, `src/bootstrap/wiring.py`, and `pyproject.toml` are unchanged.
