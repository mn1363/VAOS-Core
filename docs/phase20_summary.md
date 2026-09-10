# Phase 20 Summary: Health Layer

## Responsibility

`health` orchestrates a fixed, constructor-injected sequence of `core.protocols.
SupportsHealthCheck` services: checking every one, in registration order, and reporting whether
all of them are healthy. It does not construct, discover, or configure any concrete
`SupportsHealthCheck` service, does not decide how `health` is wired into `bootstrap`, `cli`, or
`api` at runtime, and does not reference `core.protocols.SupportsLifecycle` or `runtime` -- those
remain later, not-yet-decided concerns.

## Contract discovery

Two discovery passes preceded implementation (a fresh, repository-wide discovery pass, followed
by a final targeted pass resolving the three points it left open):

1. **Layer identification.** `core.protocols.SupportsHealthCheck` (Phase 1) was found with zero
   concrete implementers and zero orchestrator anywhere in the frozen codebase through Phase 19,
   independently corroborated by `api/main.py` (Phase 17 -- a readiness check "is a genuinely
   different, larger contract that Phase 17's confirmed scope does not include") and by
   `runtime/__init__.py` (Phase 19 -- `SupportsHealthCheck` "carries no 'future `X` package'
   attribution anywhere in the frozen codebase", unlike `SupportsLifecycle`). Confirmed absent
   from the deleted Phase 2-3 scaffold and from this repository's history at every point
   (`git log --all -- src/health tests/unit/health` returns nothing prior to this phase) --
   this phase revives nothing.
2. **Targeted contract discovery**, resolving the three points the initial discovery report left
   open:
   - **Package name** -- `health`, matching the domain vocabulary `api/main.py` and
     `api/__init__.py` already use for this exact concern, and the package-name-equals-class-
     name convention `pipeline.pipeline.Pipeline`/`runtime.runtime.Runtime` both establish.
   - **Result shape** -- a single aggregate `bool`, the same shape `SupportsHealthCheck.
     health_check` itself already returns for one service, extended to many; no per-service
     report, since `SupportsHealthCheck` has no identity field for one to be built against
     without inventing it.
   - **Failure semantics** -- convert a raising service to `False` rather than propagate,
     grounded directly in `pipeline/base.py`'s own module docstring distinguishing a single,
     ordered, all-or-nothing execution (`Pipeline.run`, `Runtime.start`/`stop` -- fail-fast) from
     "a per-item scan that may legitimately encounter many independent failures"
     (`collectors.base.CollectionResult`, `parsers.base.ParseResult`, every
     extractor/analyzer/graph/foundation Port -- convert to a value). Checking several
     independent services' health is the latter shape.
   - **Concurrency** -- sequential, in registration order. Zero concurrency precedent
     (`asyncio.gather`/`TaskGroup`/`create_task`) exists anywhere in the orchestration layer of
     this codebase; both existing orchestrators (`Pipeline.run`, `Runtime.start`/`stop`) execute
     strictly sequentially, and nothing in the frozen codebase endorses departing from that.

## Public interface

```
src/health/health.py :: Health
    def __init__(self, services: Sequence[SupportsHealthCheck]) -> None
    @property
    def services(self) -> tuple[SupportsHealthCheck, ...]
    async def health_check(self) -> bool
```

No `errors.py`: under this contract, `Health.health_check()` never raises, so there is no
failure mode of this layer's own to define an exception for.

## Failure semantics (locked contract, as implemented)

**`health_check()`** -- registration order, no short-circuit. Every registered service is
checked, in order, regardless of any earlier result. A service that returns `False` contributes
`False` to the overall result and does not stop the scan. A service whose own `health_check()`
raises is treated identically: the exception is caught at the point of that single call, treated
as `False`, never propagates out of `Health.health_check()`, and the scan continues with the
next service.

**Empty `services`:** `health_check()` returns `True` (the aggregate of zero checks is trivially
"all healthy").

## Explicitly out of scope

`core.protocols.SupportsLifecycle` and `runtime` are not referenced anywhere in `src/health`.
No dynamic discovery, entry-point loading, configuration schema, `Container`, registry, service
locator, or `cli`/`api`/`bootstrap` integration is implemented anywhere in this phase. No
concrete health check (network, storage, vector, or otherwise) is implemented -- this layer only
calls `health_check()` on whatever `SupportsHealthCheck` objects it is given.

## Dependency rules

`src/health` may import `core` only. Forbidden: `domain`, `repository`, `collectors`, `parsers`,
`extractors`, `analyzers`, `graph`, `foundation`, `storage`, `vector`, `memory`, `pipeline`,
`application`, `bootstrap`, `cli`, `api`, `plugins`, and `runtime` -- including `runtime`,
despite the shared "orchestrates a `Sequence` of a `core.protocols` shape" family resemblance,
the same standard `runtime/__init__.py` already applied to reject `bootstrap`/`pipeline` despite
documentary pairing. No exemption was added to any other layer's dependency-boundary test: this
phase's accepted responsibility needs no import beyond `core`, and no other layer imports
`src.health` back.

## Explicitly not revived

No `src/health` package existed at any point in this repository's history, including the deleted
Phase 2-3 scaffold. This phase revives nothing; it is a genuinely new package.

## Tests

- `tests/unit/health/test_imports.py` -- both modules import cleanly.
- `tests/unit/health/test_dependency_boundaries.py` -- only `core` imported; every other layer
  forbidden (including `runtime`, despite the family resemblance); no layer anywhere in `src/`
  imports `src.health` back (no exemption granted -- this phase does not wire itself into any
  caller).
- `tests/unit/health/test_health.py` -- 10 tests covering: the test double genuinely satisfies
  `SupportsHealthCheck`; `services` returns the exact constructed tuple, by identity; empty
  `services` returns `True`; all-healthy returns `True`; one unhealthy returns `False`; every
  service is still checked after an earlier `False` (no short-circuit); a raising service is
  treated as unhealthy; the raised exception does not escape `health_check()`; every service is
  still checked after an earlier exception; calls occur in registration order; and a mixed
  healthy/unhealthy/raising sequence still checks every service, in order, and reports the
  correct overall result.

## Verification results

Run against this checkout (`HEAD` = `a2024d1`, `v0.19.0`), under genuine Python 3.13.10 (a
`python-build-standalone` CPython 3.13.10 build, since no 3.13 interpreter was preinstalled in
the verification sandbox) -- every test below ran and passed against the actual frozen Phase
1-19 codebase, unmodified:

- `pytest tests/unit/health/` -- **18 passed**.
- `pytest` (full suite) -- **1312 passed** (1294 pre-existing + 18 new), 0 failed, 2 pre-existing
  unrelated deprecation warnings (`starlette`/`httpx`, present before this phase).
- `mypy --strict src/health` -- Success: no issues found in 2 source files.
- `ruff check src/health tests/unit/health` -- All checks passed.
- `ruff check .` (whole repository) -- exactly the one pre-existing, unrelated `UP046` finding in
  `src/domain/interfaces.py` (documented since Phase 17); no new finding introduced.

`docs/pytest_report.txt`, `docs/mypy_report.txt`, and `docs/ruff_report.txt` were not
regenerated/overwritten as part of this phase -- outside this phase's authorized file set, so
left untouched; the results above are recorded here instead.

## Files created

```
src/health/__init__.py
src/health/health.py
tests/unit/health/__init__.py
tests/unit/health/test_imports.py
tests/unit/health/test_dependency_boundaries.py
tests/unit/health/test_health.py
docs/phase20_summary.md
```

## Files modified

None. No Phase 1-19 production file and no Phase 1-19 test file was touched -- confirmed via
`git diff --stat` against `HEAD` (`v0.19.0`) showing no change to any tracked file; only the new,
untracked `src/health/` and `tests/unit/health/` directories appear in `git status`.

## Frozen files left untouched

Every file under `src/` outside `src/health/` -- all of Phase 1 through Phase 19's production
code -- is byte-for-byte unchanged. Every test file outside `tests/unit/health/` is byte-for-byte
unchanged. No dependency-boundary exemption was added anywhere, so no file in
`tests/unit/runtime/`, `tests/unit/pipeline/`, `tests/unit/bootstrap/`, or any other existing
test directory was touched either.
