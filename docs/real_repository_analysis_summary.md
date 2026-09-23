# Real Repository Analysis Composition Summary

Not a numbered phase. An additive milestone, built entirely from already-frozen Phase 1-20
Ports plus the six existing concrete extractors, approved and scoped by the Post-Extractor
Architecture Review and the Real Repository Analysis Composition Final Contract Discovery this
implements.

## Goal

Promote the already-proven Reference Flow composition (`collect -> clone -> enumerate files ->
parse -> ParseResults`) out of its seven duplicated test-local copies, into one additive
production module under `src/bootstrap`, extended with a failed-parse bridge and all six
existing concrete extractors -- without changing any frozen contract or the default 3-step CLI
flow.

## Exact composition

Composed via `bootstrap(config, extra_steps=build_analysis_steps(config))`, which always runs
its existing three default steps first, unmodified, before the eleven new steps
`build_analysis_steps` returns:

1. `collect` *(existing, untouched)*
2. `unpack_repositories` *(existing, untouched)*
3. `persist_repositories` *(existing, untouched)*
4. `require_single_repository` *(new)* -- `CallableStep` over `repositories`; raises
   `BootstrapError` if more than one repository was collected, otherwise returns `repositories`
   unchanged (zero or one repository is not an error).
5. `clone_repositories` *(new, promoted)* -- `MapStep` over `repositories`; per item,
   `workspace_manager.allocate(repository.id)` then `await repository_client.clone(repository,
   destination)`; writes `workspaces`.
6. `enumerate_files` *(new, promoted)* -- `CallableStep` over `workspaces`; walks each
   workspace (`.git` and every other dot-directory excluded), reading every text-decodable file;
   writes `files_to_parse` as `(relative_path, content)` pairs.
7. `parse_files` *(new, promoted)* -- `MapStep` over `files_to_parse`; per item, the first of
   the five existing `Parser`s for which `.supports(relative_path)` is `True` parses it, or
   `ParseResult.failed(...)` is produced if none does; writes `parse_results` -- retained,
   unmodified, successes and failures both.
8. `select_successful_parse_results` *(new)* -- `CallableStep` over `parse_results`; writes
   `successful_parse_results`, the subset with `succeeded is True`, in the same relative order.
9. `extract_imports` *(new, promoted)* -- `MapStep` over `successful_parse_results`;
   `StructuralImportExtractor().extract`; writes `import_results`.
10. `extract_ast` *(new, promoted)* -- `StructuralAstExtractor().extract`; writes `ast_results`.
11. `extract_symbols` *(new, promoted)* -- `StructuralSymbolExtractor().extract`; writes
    `symbol_results`.
12. `extract_architecture` *(new, promoted)* -- `StructuralArchitectureExtractor().extract`;
    writes `architecture_results`.
13. `extract_interfaces` *(new, promoted)* -- `StructuralInterfaceExtractor().extract`; writes
    `interface_results`.
14. `extract_foundation` *(new, promoted)* -- `StructuralFoundationExtractor().extract`; writes
    `foundation_results`.

## Context keys

| Key | Written by | Contents |
|---|---|---|
| `repositories` | `unpack_repositories`, re-written by `require_single_repository` | `tuple[SourceRepository, ...]`, 0 or 1 entries past step 4 |
| `workspaces` | `clone_repositories` | `tuple[Path, ...]` |
| `files_to_parse` | `enumerate_files` | `tuple[tuple[str, str], ...]` |
| `parse_results` | `parse_files` | `tuple[ParseResult, ...]`, successes and failures both, retained unmodified |
| `successful_parse_results` | `select_successful_parse_results` | `tuple[ParseResult, ...]`, `succeeded is True` only, same relative order |
| `import_results` / `ast_results` / `symbol_results` / `architecture_results` / `interface_results` / `foundation_results` | the six `extract_*` steps | not renamed from the names each single-extractor integration test already established |

## Failed-parse retention and filtering

`parse_files` still produces `ParseResult.failed(...)` for an unsupported file (a `README.md`,
for instance) -- unchanged Reference Flow behavior. Every concrete extractor already rejects a
failed `ParseResult` via its own `require_successful_parse`, so composing all six directly
against `parse_results` (as each extractor's own single-extractor integration test does, whose
fixtures happen to contain no unsupported file) would abort the whole pipeline the first time a
realistic repository is analyzed. `select_successful_parse_results` bridges this: `parse_results`
is retained under its own key, complete and unmodified; `successful_parse_results` is a new,
filtered tuple, in the same relative order, that every extractor step reads instead.

## One-repository restriction

Real-repository analysis composition is explicitly one-repository scoped, matching the
restriction `docs/reference_flow_summary.md` itself already named and left unresolved. Of the
four collectors, `FilesystemCollector`/`GitHubCollector`/`GitLabCollector` each always return
exactly one repository or a failed result, by construction; only `LocalCollector` can return more
than one, when its scan root contains several nested git repositories. `require_single_repository`
closes this gap by raising the existing `BootstrapError` -- reused, not replaced -- whenever more
than one repository reaches it; zero or one repository is not an error. No repository-aggregation
DTO, ownership field, or cross-repository identity is introduced.

## File enumeration behavior

Unchanged from the Reference Flow: recursive `os.walk`, `topdown=True`, any directory whose name
starts with `.` pruned (not only `.git`), sorted directory and file traversal at every level, UTF-8
decoding with `UnicodeDecodeError`/`OSError` silently skipped. No rule anywhere in the frozen
architecture excludes `node_modules`, `vendor`, or `target`, so none was added.

## Parser dispatch behavior

Unchanged from the Reference Flow: a fixed, five-element tuple of already-constructed parsers
(`PythonParser`, `RustParser`, `GoParser`, `TypeScriptParser`, `CppParser`), tried in that order via
each one's own existing `supports(relative_path)` method. No registry or dispatcher was
introduced.

## Six-extractor composition

All six existing concrete extractors are wired in this one milestone, each unmodified, each
reading `successful_parse_results` instead of `parse_results`. Verified together, twice, against
an independent workspace each time, with identical results both times (see the integration test's
own determinism case).

## Why the default CLI flow remains unchanged

`bootstrap.wiring.build_application`'s own three-step default flow, `cli/main.py`, and
`api/main.py` are all frozen and untouched. This milestone is reachable only through
`bootstrap(config, extra_steps=build_analysis_steps(config))`; `build_application` itself is
never modified, so `python -m src.cli.main` still runs exactly the same three steps it always
has. Exposing this composition through the CLI is a separate, later decision this milestone does
not make.

## Why `patterns` remains unimplemented

Nothing in this milestone constructs a `PatternExtractor`. `graph.knowledge.base.
KnowledgeGraphBuilder.build`'s `pattern_results` parameter already defaults to `()`, so a future
knowledge graph built from this milestone's six extraction results simply contains no `PATTERN`
nodes -- consistent with the earlier Patterns Final Contract Discovery's own `NOT READY` verdict,
which this milestone does not revisit or reverse.

## Architectural red-line protections

- No Container, DI framework, or service locator: `build_analysis_steps(config)` is a plain
  function; every dependency is either a parameter or a direct, local construction.
- No PluginRegistry or dynamic discovery: no `entry_points`, `importlib`, `pkgutil`, or
  `__subclasses__` use anywhere in the new module.
- No parser registry/dispatcher: dispatch stays `next(p for p in parsers if p.supports(path))`
  over a fixed, closed-over tuple.
- No old scorer architecture, no `src/infrastructure`, no speculative module resolution: none of
  `foundation`, `analyzers`, `graph`, or import-to-file resolution is touched.
- No new top-level package: one new file (`analysis_steps.py`) inside the existing
  `src/bootstrap` package, alongside its existing `wiring.py`/`errors.py`.
- No frozen-contract change: `wiring.py`, `cli/main.py`, `api/main.py`, every parser, every
  existing extractor, and `domain` are all byte-for-byte unchanged.

## Tests

`tests/unit/bootstrap/test_analysis_steps.py`, 22 tests, using real Ports and hand-written fakes
(never `unittest.mock`), covering `_require_single_repository` (zero/one/multiple repositories,
exact `BootstrapError` details), `_clone_repository_func` (closure behavior against a fake
`RepositoryClient`), `_enumerate_files` (determinism, dot-directory exclusion, sorted directory
and file order, UTF-8 decoding, undecodable-file skipping), `_all_parsers`/`_parse_files_func`
(all five parsers present, dispatch by `supports`, unsupported-file failure),
`_select_successful_parse_results` (order preservation, failure exclusion, non-mutation of the
original tuple), and `build_analysis_steps` itself (exact 11 step names, exact order, exact
`is_async` per step, exact extractor output keys, exactly 11 steps returned).

`tests/integration/test_real_repository_analysis.py`, 6 tests: the full 14-step end-to-end run
against a real local repository covering every required case (Python class/function, Go source,
TypeScript interface/class, a nested directory, a dot-directory, an unsupported `README.md`, and
an undecodable-byte file); a determinism case running the same composition twice; a
multi-repository rejection case via `LocalCollector`; and three equivalence cases proving
`_enumerate_files`/`_parse_files_func`/`_clone_repository_func` behave identically to the
Reference Flow's own already-frozen, test-local helpers. Requires the real `git` executable;
skipped (not failed) if none is found on `PATH`.

## Verification results

Run against this checkout (`HEAD` = `6dbc02e`), under Python 3.12.3 (the interpreter available in
this sandbox; `pyproject.toml` declares `>=3.13` -- the same discrepancy
`docs/reference_flow_summary.md` already noted and left as a separate, unrelated check):

- `pytest tests/unit/bootstrap/test_analysis_steps.py` -- **22 passed**.
- `pytest tests/integration/test_real_repository_analysis.py` -- **6 passed**.
- `pytest` (full suite) -- **1472 passed**, 0 failed (1442 pre-existing + 28 new tests (22 unit +
  6 integration) + 2 new parametrized cases automatically added by
  `test_bootstrap_module_imports_no_forbidden_layer`/`test_bootstrap_module_imports_only_allowed_
  layers`, which already walk every file under `src/bootstrap` and so picked up
  `analysis_steps.py` without any edit to that test), 2 pre-existing unrelated deprecation
  warnings (`starlette`/`anyio`, present before this milestone).
- `mypy --strict src/` -- **Success: no issues found in 128 source files**.
- `ruff check src/ tests/` -- **1 error** (the pre-existing, unrelated `UP046` in
  `src/domain/interfaces.py`, left untouched as instructed); zero findings in any new file.

## Files created

```
src/bootstrap/analysis_steps.py
tests/unit/bootstrap/test_analysis_steps.py
tests/integration/test_real_repository_analysis.py
docs/real_repository_analysis_summary.md
```

## Files modified

None under `src/`, and none anywhere else in the repository. `git status --short` shows only
these four new, untracked files. `src/bootstrap/wiring.py`, `src/bootstrap/__init__.py`, every
parser, every existing extractor, `domain`, `cli`, `api`, `patterns`, `pyproject.toml`, and
`tests/integration/test_reference_flow.py` are all byte-for-byte unchanged.

## Frozen files left untouched

Every file under `src/` from Phase 1 through the six extractor milestones, including
`bootstrap/wiring.py`'s existing three-step default flow, is byte-for-byte unchanged. Every
existing test file is byte-for-byte unchanged, including all seven pre-existing integration
tests, whose own duplicated test-local helpers were deliberately left in place rather than
refactored, per this milestone's own locked scope. No dependency-boundary exemption was added
anywhere: `tests/unit/bootstrap/test_dependency_boundaries.py` already allows every layer this
new module imports (`src.parsers`, `src.extractors`, `src.repository`, `src.collectors` were
already in its `_ALLOWED_PREFIXES`), so it required no change and was re-run, unmodified, against
the changed tree.

## Known, pre-existing documentation drift (not addressed by this milestone)

`src/bootstrap/__init__.py` states "One module, `wiring.py`, holding this layer's entire public
surface." This was already inaccurate before this milestone -- `errors.py` already exists as a
second, un-mentioned file -- and remains so now that `analysis_steps.py` exists as a third. No
test enforces this line, and this milestone's own contract discovery explicitly declined to edit
any frozen file's prose without a driving requirement to do so. A future documentation-accuracy
pass could reconcile it; this milestone does not.
