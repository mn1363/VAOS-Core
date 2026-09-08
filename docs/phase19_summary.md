# Phase 19 Summary: Runtime Layer

## Responsibility

`runtime` orchestrates a fixed, constructor-injected sequence of `core.protocols.
SupportsLifecycle` services: starting them in registration order, and stopping them in reverse
registration order. It does not construct, discover, or configure any concrete `SupportsLifecycle`
service, does not decide how `runtime` is wired into `bootstrap`, `cli`, or `api` at runtime, and
does not implement `core.protocols.SupportsHealthCheck` -- those remain later, not-yet-decided
concerns.

## Contract discovery

Three discovery passes preceded implementation:

1. **Layer identification.** `runtime` was named as a still-open, not-yet-built package by
   `core.protocols.SupportsLifecycle` (Phase 1), `storage.__init__` (Phase 10), and
   `bootstrap.__init__` (Phase 15) -- the sole remaining member of the six historically-named-
   but-unbuilt candidates Phase 14's own contract discovery first surfaced (`application`,
   `bootstrap`, `runtime`, `plugins`, `api`, `cli`), the other five of which have each already
   been implemented, in sequence, as exactly the phase their name predicted. Confirmed absent
   from the deleted Phase 2-3 scaffold (`git ls-tree -r 031c67c` contains no `src/runtime` at any
   point in this repository's history).
2. **Targeted contract discovery.** Evaluated public API shape (function pair vs. class vs.
   async context manager -- selected a small `Runtime` class, the only option matching an
   existing precedent: `pipeline.pipeline.Pipeline`'s own "small class wrapping an immutable,
   constructor-injected `Sequence`" shape; zero context-manager precedent exists anywhere in the
   repository), sync/async (forced async by `SupportsLifecycle`'s own existing signature),
   failure semantics (modeled on `Pipeline.run`'s own `try`/`finally` precedent -- see below),
   registration model (explicit constructor injection only, matching every layer's own "no
   registry, no service locator" rule), and two rejected dependencies: `bootstrap` and `pipeline`
   (both plausible from documentation pairing alone, both rejected because the accepted
   responsibility is fully satisfiable importing `core` alone, and no concrete current-code
   requirement proved otherwise).
3. **Owner sign-off** on the one point current evidence did not fully determine: shutdown
   failure semantics (`stop()` mirrors `Pipeline.run`'s un-isolated `finally` loop exactly --
   fail-fast, unwrapped, no aggregation -- rather than a stronger, unprecedented best-effort
   guarantee).

## Public interface

```
src/runtime/errors.py :: RuntimeLifecycleError(VAOSError)
src/runtime/runtime.py :: Runtime
    def __init__(self, services: Sequence[SupportsLifecycle]) -> None
    @property
    def services(self) -> tuple[SupportsLifecycle, ...]
    async def start(self) -> None
    async def stop(self) -> None
```

## Failure semantics (locked contract, as implemented)

**`start()`** -- registration order, fail-fast. The first `service.start()` to raise stops
further startup immediately. Every already-started service is then stopped, in reverse order
(rollback). The original startup exception is wrapped as `RuntimeLifecycleError` via
`raise ... from exc`, with `details` naming `"failed_index"` and `"rolled_back_indices"` (by
position -- `SupportsLifecycle` has no name/identity field for `pipeline.base.StepExecutionError`'s
own name-based `details` convention to carry over). If a rollback `stop()` itself raises, that
exception propagates completely unwrapped in its place, and any remaining rollback stops are not
attempted.

**`stop()`** -- reverse registration order, fail-fast. The first `service.stop()` to raise
propagates completely unwrapped. Remaining services (earlier in reverse order) are not attempted.
No aggregation, no suppression, no best-effort shutdown -- this mirrors `pipeline.pipeline.
Pipeline.run`'s own resource-release `finally` loop exactly, which has no per-item isolation
either, rather than introducing a stronger guarantee unprecedented anywhere else in the codebase.

**Empty `services`:** `start()` and `stop()` are both no-ops.

## Explicitly out of scope

`core.protocols.SupportsHealthCheck` is not referenced anywhere in `src/runtime` -- unlike
`SupportsLifecycle`, it carries no "future `X` package" attribution anywhere in the frozen
codebase. No dynamic discovery, entry-point loading, configuration schema, `Container`, registry,
service locator, or `cli`/`api` integration is implemented anywhere in this phase.

## Dependency rules

`src/runtime` may import `core` only. Forbidden: `domain`, `repository`, `collectors`, `parsers`,
`extractors`, `analyzers`, `graph`, `foundation`, `storage`, `vector`, `memory`, `pipeline`,
`application`, `bootstrap`, `cli`, `api`, `plugins`. No exemption was added to any other layer's
dependency-boundary test: unlike Phase 18 (`Plugin(Step, ABC)` required a `plugins -> pipeline`
edge and one authorized exemption in `tests/unit/pipeline/test_dependency_boundaries.py`), Phase
19's accepted responsibility needs no import beyond `core`, so no correction to any existing test
file was necessary or made.

## Explicitly not revived

No `src/runtime` package existed at any point in this repository's history, including the deleted
Phase 2-3 scaffold (`Container`, `PluginRegistry`, `infrastructure.composition.
register_infrastructure`, ...). This phase revives nothing; it is a genuinely new package.

## Tests

- `tests/unit/runtime/test_imports.py` -- all three modules import cleanly.
- `tests/unit/runtime/test_dependency_boundaries.py` -- only `core` imported; every other layer
  forbidden (including `bootstrap` and `pipeline`, despite each appearing alongside `runtime` in
  prior phases' own documentation); no layer anywhere in `src/` imports `src.runtime` back (no
  exemption granted -- this phase does not wire itself into any caller).
- `tests/unit/runtime/test_runtime.py` -- 12 tests covering: registration-order start,
  reverse-order stop, empty-`services` no-ops for both, fail-fast startup (no service starts
  after the failing one), reverse-order rollback of already-started services on a start failure,
  `__cause__` chaining via `raise ... from exc`, `details` identifying the failed and
  rolled-back indices, a rollback-stop failure propagating unwrapped and halting further
  rollback, and a `stop()` failure propagating unwrapped while leaving earlier (in reverse
  order) services unattempted.

## Verification results

Run against this checkout (Python 3.12.3 -- Python 3.13 was unavailable in the verification
sandbox; nothing in `src/runtime` uses any syntax or stdlib feature specific to 3.13, and every
test below ran and passed against the actual frozen Phase 1-18 codebase unmodified):

- `pytest tests/unit/runtime/` -- 22 passed.
- `pytest` (full suite) -- **1294 passed** (1272 pre-existing + 22 new), 0 failed.
- `mypy --strict src/runtime` -- Success: no issues found in 3 source files.
- `ruff check src/runtime tests/unit/runtime` -- All checks passed.
- `ruff check .` (whole repository) -- exactly the one pre-existing, unrelated `UP046` finding in
  `src/domain/interfaces.py` (documented since Phase 17); no new finding introduced.

`docs/pytest_report.txt`, `docs/mypy_report.txt`, and `docs/ruff_report.txt` were not
regenerated/overwritten as part of this phase -- outside this phase's authorized file set, so
left untouched; the results above are recorded here instead.

## Files created

```
src/runtime/__init__.py
src/runtime/errors.py
src/runtime/runtime.py
tests/unit/runtime/__init__.py
tests/unit/runtime/test_imports.py
tests/unit/runtime/test_dependency_boundaries.py
tests/unit/runtime/test_runtime.py
docs/phase19_summary.md
```

## Files modified

None. No Phase 1-18 production file and no Phase 1-18 test file was touched -- confirmed via
`git diff --stat` against `HEAD` (`v0.18.0`) showing no change to any tracked file; only the new,
untracked `src/runtime/` and `tests/unit/runtime/` directories appear in `git status`.

## Frozen files left untouched

Every file under `src/` outside `src/runtime/` -- all of Phase 1 through Phase 18's production
code -- is byte-for-byte unchanged. Every test file outside `tests/unit/runtime/` is byte-for-byte
unchanged. Unlike Phase 18, no dependency-boundary exemption was added anywhere, so no file in
`tests/unit/pipeline/`, `tests/unit/bootstrap/`, or any other existing test directory was touched
either.
