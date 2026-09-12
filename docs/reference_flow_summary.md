# Reference Flow Summary

Not a numbered phase. An additive, integration-test-only composition milestone, built entirely
from already-frozen Phase 1-20 Ports, approved and scoped by the Reference Flow Contract
Discovery this implements.

## Objective

Prove that `collect -> clone -> enumerate files -> parse -> ParseResults` can be composed from
existing, unmodified Ports alone, with zero change to any file under `src/`, and produce real
`ParseResult` data from one real, local repository.

## Exact flow

Composed via `bootstrap(config, extra_steps=[...])`, which always runs its existing three
default steps first, unmodified, before the three new steps appended after them:

1. `collect` *(existing, untouched)*
2. `unpack_repositories` *(existing, untouched)*
3. `persist_repositories` *(existing, untouched)*
4. `clone_repositories` *(new, test-local)* -- `MapStep` over `repositories`; per item,
   `workspace_manager.allocate(repository.id)` then `await repository_client.clone(repository,
   destination)`; writes `workspaces`.
5. `enumerate_files` *(new, test-local)* -- `CallableStep` over `workspaces`; walks each
   workspace (`.git` excluded), reading every text-decodable file; writes `files_to_parse` as
   `(relative_path, content)` pairs.
6. `parse_files` *(new, test-local)* -- `MapStep` over `files_to_parse`; per item, the first of
   the five existing `Parser`s for which `.supports(relative_path)` is `True` parses it, or
   `ParseResult.failed(...)` is produced if none does; writes `parse_results`.

## Reused components

Every Port below is used exactly as already frozen -- no signature, contract, or behavior
change:

- `FilesystemCollector` (`src.collectors.filesystem`)
- `GitRepositoryClient` / `FilesystemWorkspaceManager`, constructed via the already-exported,
  already-tested `bootstrap.wiring.build_repository_client` / `build_workspace_manager`
- All five `Parser` implementations: `PythonParser`, `RustParser`, `GoParser`,
  `TypeScriptParser`, `CppParser` -- dispatched purely via each one's own existing
  `supports(relative_path)` method; no registry or dispatcher was introduced
- `CallableStep` / `MapStep` (`src.pipeline.steps`)
- `PipelineContext`'s existing schema-free `dict[str, Any]` storage -- three new string keys
  (`workspaces`, `files_to_parse`, `parse_results`), no new DTO
- `bootstrap.wiring.bootstrap`'s existing `extra_steps` parameter -- the flow's only attachment
  point to the rest of the system

## One-repository scope

As scoped: no multi-repository aggregation, no repository-to-file ownership DTO. `collect` may
in principle return more than one `SourceRepository`, but nothing downstream disambiguates which
`ParseResult` belongs to which repository -- correct only for the one-repository-per-run case
this milestone targets. Extending to N repositories is an explicit, separate design question,
not resolved here.

## Tests

`tests/integration/test_reference_flow.py`, 5 tests:

- `test_collector_output_reaches_clone` -- a real `FilesystemCollector` output flows through
  `unpack_repositories` into a `clone_repositories` `MapStep`, verified against a hand-written
  `_RecordingRepositoryClient` (a real `RepositoryClient` implementation, not a mock, matching
  this repository's own established fake convention) that the exact same entity (by identity)
  reaches the clone closure.
- `test_enumerate_files_lists_expected_paths` -- a workspace with a nested file and a `.git`
  directory; asserts exactly the two real files are listed, `.git` excluded, with real content
  read back.
- `test_parser_dispatch_selects_correct_parser` -- `.py`/`.go`/`.rs` each route to the correct
  parser via `.supports()` alone; an unsupported extension produces `ParseResult.failed(...)`
  rather than raising.
- `test_parse_results_are_real` -- a parsed Python file's `ParseResult.functions` contains the
  actual function the real `PythonParser` found, not just `succeeded=True`.
- `test_reference_flow_executes_against_one_real_local_repository` -- the end-to-end proof: a
  real git repository created under `tmp_path` (`git init`, a `main` branch, two supported
  source files plus one unsupported file, `git add`/`commit`), run through the real
  `bootstrap(config, extra_steps=[...])`. Asserts the full six-step name sequence, three
  `parse_results`, the Python and Go files parsed successfully with real structural content
  found, and the unsupported file reported as a failed result without aborting the run. Requires
  the real `git` executable; skipped (not failed) if none is found on `PATH`. Cloning a local
  filesystem path is ordinary `git` behavior, so no network access is needed.

## Verification results

Run against this checkout (`HEAD` = `ccb4d85`, `v0.20.0`), under Python 3.12.3 (the interpreter
available in this sandbox; `pyproject.toml` declares `>=3.13` -- worth a separate check on
whether that constraint is enforced elsewhere, unrelated to this milestone):

- `pytest tests/integration/test_reference_flow.py` -- **5 passed**.
- `pytest` (full suite) -- **1317 passed**, 0 failed, 2 pre-existing unrelated deprecation
  warnings (`starlette`/`httpx`, present before this milestone).
- `mypy --strict src/` -- Success: no issues found in 121 source files (unchanged from before
  this milestone -- no file under `src/` was touched).
- `ruff check src/ tests/` -- exactly the one pre-existing, unrelated `UP046` finding in
  `src/domain/interfaces.py`; no new finding introduced.

**Baseline discrepancy, noted rather than silently reconciled:** the approved plan's stated
baseline was 1294 tests. The actual, freshly-measured baseline at `HEAD` (before this milestone,
with no files changed) was **1312**, not 1294 -- 1294 was Phase 19's own pre-Phase-20 count
(see `docs/phase20_summary.md`'s "1294 pre-existing + 18 new" note); Phase 20 (Health, 18 tests)
brought the true pre-Reference-Flow baseline to 1312, and this was independently re-verified by
running the suite fresh against the untouched `HEAD` earlier in this same review before writing
any new file. 1312 + 5 new Reference Flow tests = the 1317 reported above.

`docs/pytest_report.txt`, `docs/mypy_report.txt`, and `docs/ruff_report.txt` were **not**
regenerated as part of this milestone -- they were already stale relative to Phases 19-20 before
this work started (documented in the prior architecture review), and regenerating them is
outside this milestone's authorized file set. The verified results above are recorded here
instead.

## Files created

```
tests/integration/__init__.py
tests/integration/test_reference_flow.py
docs/reference_flow_summary.md
```

## Files modified

None under `src/`, and none anywhere else in the repository. Confirmed via `git diff --stat`
against `HEAD` (`v0.20.0`) showing no change to any tracked file; `git status --short` shows only
the new, untracked `tests/integration/` directory (plus this doc). No `pyproject.toml` change was
needed -- `@pytest.mark.asyncio` is already a recognized marker from the existing
`pytest-asyncio` dependency, so no new marker registration was required either.

## Frozen files left untouched

Every file under `src/` -- all of Phase 1 through Phase 20's production code, including
`bootstrap/wiring.py`'s existing three-step default flow -- is byte-for-byte unchanged. Every
existing test file outside the new `tests/integration/` directory is byte-for-byte unchanged. No
dependency-boundary exemption was added anywhere: `tests/unit/bootstrap/test_dependency_
boundaries.py`, `tests/unit/application/test_dependency_boundaries.py`, and `tests/unit/pipeline/
test_dependency_boundaries.py` were re-run against the changed tree and all 42 of their cases
still pass, unmodified.
