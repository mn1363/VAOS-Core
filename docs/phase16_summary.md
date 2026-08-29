# Phase 16 Summary: CLI Layer

## Responsibility

`src.cli` is the outermost of sixteen now-frozen layers. It is a thin command-line process entry
point over the existing, already-frozen `bootstrap.bootstrap` flow -- it contains no business
logic, no Pipeline logic, no direct construction of any lower-layer Port, and no Application or
Bootstrap logic of its own. Its entire job is translating a process invocation (`argv`, a process
exit code, stdout/stderr) into and out of one existing call: parse `--config`/`--help`/`--version`,
load `core.config.AppConfig` via `core.config.load_config`, call `bootstrap.bootstrap`, and render
its `PipelineResult` (or a raised `core.exceptions.VAOSError`) to the terminal with a matching exit
code.

This phase followed the two-pass discovery process every prior phase has: a first pass
("PHASE 16 CONTRACT DISCOVERY") established that the current, enforced candidate set narrowed to
`{api, cli, plugins}` and that `cli` had the only current, frozen, responsibility-level evidence
of the three -- but concluded the evidence was not sufficient to select `cli` over the other two
without an explicit decision. A second pass ("PHASE 16 CLI CONTRACT") inventoried every piece of
current evidence for what a CLI contract would actually contain and concluded the public
interface, command structure, framework, output format, and exit-code convention were all
unresolved by current evidence -- correctly reporting `PHASE 16 CLI CONTRACT BLOCKED` rather than
inventing them. Implementation began only once both were resolved by explicit, final architectural
decisions.

## Public interface

One module, `src/cli/main.py`, holds this layer's entire public surface:

```python
def build_parser() -> argparse.ArgumentParser
def main(argv: Sequence[str] | None = None) -> int
```

plus one private async execution helper, `async def _run(config_path: Path | None) -> int`, and
one private formatting helper, `def _format_result(result: PipelineResult) -> str`. All are plain
functions -- no service classes, no CLI controller class, no CQRS hierarchy, no DI container, no
service locator, matching the plain-function convention every earlier phase already established.

## Command structure

A single default command: `vaos [--config PATH]` runs the configured default analysis flow. No
subcommands. `--help` and `--version` are `argparse`'s own built-in `action="help"`/`action=
"version"` behavior; `--version` reads `core.constants.APP_NAME`/`APP_VERSION` directly, requiring
no architectural change. The historical `vaos plugins list` command was deliberately not
recreated: `plugins`/`PluginRegistry` do not exist in the current architecture.

## Configuration

`--config PATH` is passed directly into the existing, frozen `core.config.load_config(path)`
mechanism, unmodified. No per-key configuration flags were invented; `load_config`'s own YAML +
`VAOS_*`-env-var-override mechanism is the only configuration surface exposed.

## Output

Human-readable terminal output only. On success, a one-line summary naming the pipeline and the
steps that ran (`_format_result`), written to stdout; `result.context`'s own contents are never
rendered. No JSON output, no table framework, no `rich`/`click`/`typer` -- stdlib `argparse` only,
no new dependency, `pyproject.toml` unmodified.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Successful execution |
| 1 | A `core.exceptions.VAOSError` (or subclass) raised by `load_config`/`bootstrap`, or any other unexpected exception, reaching this layer's own outer boundary |
| 2 | An `argparse` usage/argument error -- handled entirely by `argparse` itself (`parser.error()` -> `SystemExit(2)`), not reimplemented here |

## Error handling

`_run` catches at the outer boundary: `VAOSError` is written to `stderr` as `vaos: error: <exc>`
(`exc`'s own `__str__`, i.e. its `.message`); any other exception is written to `stderr` as
`vaos: unexpected error: <exc>`. Neither case writes a Python traceback. No lower-layer exception
class was modified; exception chaining is preserved internally (`raise ... from` is never broken --
nothing here re-raises). The broad `except Exception` is a single, explicitly commented
`# noqa: BLE001` at the one line this pattern is architecturally required -- ruff's
`flake8-blind-except` rule flags catching-without-re-raising by design; a process entry point that
must map *any* unexpected exception to a non-zero exit rather than crash is exactly the
legitimate case that check exists to let a caller consciously accept, matching the "smallest
possible, explicitly justified accommodation" pattern Phase 15 already established for its own
`type: ignore[arg-type]`.

## Async boundary

`bootstrap.bootstrap` (and `core.config.load_config`, implicitly awaited as part of `_run`) is
`async def`; `main` is `main`'s own synchronous process entry point, bridging via
`asyncio.run(_run(config_path))`. `_run` is the coroutine function; `main` is verified (by test)
to be safely callable with no event loop already running, matching how a plain
`if __name__ == "__main__": sys.exit(main())` invokes it.

## Dependency rules

`src/cli` may import every already-frozen layer through `src.bootstrap` (`core`, `domain`,
`repository`, `collectors`, `parsers`, `extractors`, `analyzers`, `graph`, `foundation`,
`storage`, `vector`, `memory`, `pipeline`, `application`, `bootstrap`) but not `src.api` or
`src.plugins` -- neither of which exists. In practice `src/cli/main.py` imports only
`src.bootstrap.wiring.bootstrap`, `src.core.config.load_config`, `src.core.constants`,
`src.core.exceptions.VAOSError`, and `src.pipeline.base.PipelineResult` (the last for a type
annotation only). No Phase 1-15 package imports `src.cli`.

### Frozen-phase conflict, reported and authorized before correction

Full-repository verification exposed two objectively necessary conflicts, both reported and
explicitly approved before any frozen test was touched:

- `tests/unit/bootstrap/test_dependency_boundaries.py::test_no_other_layer_imports_bootstrap`
  scanned the whole `src/` tree with no exemption for `src/cli`, and `src/cli/main.py`'s
  `cli -> bootstrap` import (required by this phase's own architecture) tripped it.
- `tests/unit/pipeline/test_dependency_boundaries.py::test_no_other_layer_imports_pipeline`
  already carried Phase 14's (`src/application`) and Phase 15's (`src/bootstrap`) own identical
  corrections, and needed the same, third exemption for `src/cli`'s `PipelineResult` type import.

Both were corrected with the minimal possible change -- one additive directory exclusion plus a
docstring note in each, following the exact pattern the two prior corrections already established.
No assertion was removed or weakened; no Phase 1-15 production code was touched; `pyproject.toml`
was not touched; no dependency was added.

## Tests

`tests/unit/cli/`:

- `test_imports.py` -- execution-based import verification for `src.cli`/`src.cli.main` (2 tests).
- `test_dependency_boundaries.py` -- static AST-based import checks: no forbidden layer
  (`src.api`, `src.plugins`) imported, every `src.*` import resolves to an allowed layer, no
  other layer imports `src.cli` back (5 tests).
- `test_main.py` -- argument parsing (`--config`, `--help`, `--version`, an unrecognized flag),
  exit-code and stdout/stderr mapping for success, a `VAOSError` from `bootstrap`, a `VAOSError`
  from `load_config`, and an unexpected non-VAOS exception, `--config`'s path flowing through to
  `load_config`, the sync/async bridge (`_run` is a coroutine function; `main` is callable with
  no event loop running), and one real, end-to-end run of the actual `load_config`/`bootstrap`
  call against the `"filesystem"` collector/storage backends in a `tmp_path` -- no network, no
  external process, no `unittest.mock`, matching this repository's own established fakes-only
  testing convention (14 tests).

21 new tests total. None duplicate `tests/unit/bootstrap/`'s or `tests/unit/core/`'s own coverage
of `bootstrap.bootstrap`'s or `load_config`'s internal behavior; every non-end-to-end test
substitutes `src.cli.main.load_config`/`src.cli.main.bootstrap` directly via `monkeypatch`.

## Verification results

```
pytest -q                      -> 1248 passed (1227 pre-Phase-16 + 21 new)
pytest tests/unit/cli/ -q      -> 21 passed
mypy --strict src/             -> Success: no issues found in 112 source files
mypy --strict src/cli/ tests/unit/cli/  -> Success: no issues found in 6 source files
ruff check src/ tests/         -> 1 finding: UP046 in src/domain/interfaces.py
                                   (pre-existing, predates Phase 16 -- unrelated to this phase)
ruff check src/cli/ tests/unit/cli/     -> All checks passed
whole-tree import check (112 modules, individually) -> all import cleanly, no circular imports
```

Full reports: `docs/pytest_report.txt`, `docs/mypy_report.txt`, `docs/ruff_report.txt`.

## Files created

```
src/cli/__init__.py
src/cli/main.py
tests/unit/cli/__init__.py
tests/unit/cli/test_imports.py
tests/unit/cli/test_dependency_boundaries.py
tests/unit/cli/test_main.py
docs/phase16_summary.md
```

## Files modified (authorized corrections only)

```
tests/unit/bootstrap/test_dependency_boundaries.py   (src/cli exemption; see above)
tests/unit/pipeline/test_dependency_boundaries.py    (src/cli exemption; see above)
docs/pytest_report.txt   (regenerated: full-repo run including Phase 16)
docs/mypy_report.txt     (regenerated: full-repo run including Phase 16)
docs/ruff_report.txt     (regenerated: full-repo run including Phase 16)
```

## Frozen files left untouched

Every Phase 1-15 production file under `src/core`, `src/domain`, `src/repository`,
`src/collectors`, `src/parsers`, `src/extractors`, `src/analyzers`, `src/graph`,
`src/foundation`, `src/storage`, `src/vector`, `src/memory`, `src/pipeline`, `src/application`,
`src/bootstrap`. `pyproject.toml`. Every dependency-boundary test other than the two named above.
No new dependency was added; no existing dependency was changed.
