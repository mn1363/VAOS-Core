# Phase 17 Summary: API Layer

## Responsibility

`src.api` is the seventeenth layer -- the first built on top of the sixteen already-frozen
Phase 1-16 layers. Like `cli` (Phase 16), it introduces no business logic of its own: it only
translates an external invocation into and out of already-built machinery, this time an HTTP
request/response instead of a process invocation. Phase 17's confirmed initial scope is exactly
one operation, `GET /health`, which -- as a pure liveness probe -- calls nothing in any inner
layer at all; reaching its handler's body is the liveness signal itself.

This phase followed the same multi-pass discovery process every prior phase has:

1. **Contract discovery** narrowed the current, enforced candidate set to exactly two
   not-yet-built names, `api` and `plugins`, with no current evidence distinguishing between
   them -- concluding `PHASE 17 BLOCKED` pending an explicit decision.
2. Once `Phase 17 = API` was confirmed, a **targeted API contract pass** inventoried every piece
   of current evidence (`SupportsHealthCheck`, `domain.dtos`'s "future API" docstring,
   `VAOSError.details`'s "API error responses" docstring, the deleted Phase 2-3 scaffold) and
   found the framework, transport, and operation set all unresolved by current evidence --
   concluding `PHASE 17 API CONTRACT BLOCKED` rather than inventing them.
3. Implementation began only once the framework (FastAPI + Uvicorn), transport (HTTP), and
   initial operation (`GET /health`) were each confirmed by explicit, final architectural
   decisions.

## Public interface

One module, `src/api/main.py`, holds this layer's entire public surface:

```python
async def health() -> dict[str, str]
def create_app() -> FastAPI
```

plus the module-level ASGI object `app = create_app()` that `uvicorn` serves, and a
`uvicorn.run(app, ...)` call under `if __name__ == "__main__":` for direct local execution. Both
`health` and `create_app` are plain functions -- no service classes, no DI container, no route
controller hierarchy -- matching the plain-function convention every earlier phase already
established.

## Supported operation

Exactly one: `GET /health`. No request model (no path/query parameters, no body). Returns `200`
with a minimal JSON liveness body, `{"status": "healthy"}`. FastAPI's own auto-registered
`/docs`, `/redoc`, and `/openapi.json` routes are explicitly disabled
(`docs_url=None, redoc_url=None, openapi_url=None`) so "exactly one endpoint" holds literally, not
just for hand-written routes. No other method is registered on `/health` (`POST /health` ->
`405`, verified by test).

## Configuration

None needed. `core.config.AppConfig` was not touched -- an ASGI application object is
transport-agnostic; host/port binding is `uvicorn`'s own runtime concern, not something this
phase's confirmed scope requires modeling in `AppConfig`.

## Dependency rules

`src/api` imports nothing from any other `src.*` package -- `_ALLOWED_PREFIXES` in its own
dependency-boundary test is deliberately empty, and `_FORBIDDEN_PREFIXES` lists all sixteen other
named layers plus `src.plugins`. In practice `src/api/main.py` imports only `fastapi` (and
`uvicorn`, locally, inside the `__main__` block). Unlike Phases 14-16, **no existing
dependency-boundary test required correction** -- `GET /health` needs no `bootstrap`,
`application`, or `pipeline` import, so none of the seven other layers' forbid-lists (which
already named `src.api`) needed touching. No Phase 1-16 package imports `src.api`.

## Dependency decision: FastAPI + Uvicorn

Resolved empirically against live PyPI (not from memory) before any `pyproject.toml` change:
`fastapi==0.141.1` pulls `starlette`, `pydantic`, `pydantic-core`, `typing-extensions`,
`typing-inspection`, `annotated-doc`, `annotated-types`, `anyio`, `idna`; `uvicorn==0.52.4` (core,
no `[standard]` extras) pulls `click`, `h11`. Cross-checked against the existing
`pyproject.toml`: `qdrant-client` already transitively pulls `pydantic`, `pydantic-core`,
`anyio`, `idna`, `h11`, `typing-extensions`, `typing-inspection`, `annotated-types`, and `httpx`
(used by this phase's own tests' `fastapi.testclient.TestClient`, needing no new test dependency).
**Net-new packages: exactly five** -- `fastapi`, `starlette`, `annotated-doc`, `uvicorn`, `click`.
A full combined resolution (existing deps + `fastapi` + `uvicorn`) confirmed no version conflicts.
`pyproject.toml` now declares `"fastapi>=0.141.1"` and `"uvicorn>=0.52.4"` -- the only two lines
added; nothing else in the file changed.

## Explicitly not revived

A `src/api/` package existed once before, at Phase 2-3 (`git show 031c67c:src/api/`), built
around a FastAPI app wired through a `core.Container` dependency-injection container, an
`infrastructure.composition.register_infrastructure` call, and a `plugins.registry.PluginRegistry`
-- none of which exist in the current architecture, and none of which appear anywhere in this
phase's executable code (verified by grep: every occurrence of those names in `src/api/` is
inside `__init__.py`'s own prose explaining what was *not* revived). That scaffold was deleted in
the "Restore VAOS after stale module cleanup" commit. The current `create_app()` shares only the
universal FastAPI/Uvicorn module-level-`app` convention with the deleted version -- necessary so
`uvicorn module:app` can locate the ASGI callable at all -- not its DI/plugin/infrastructure
wiring.

## Documentation correction (this pass)

`src/api/__init__.py`'s opening line originally read *"`api` is the sixteenth of the now-sixteen
currently-frozen layers, and Phase 17's own package"* -- incorrect, since sixteen layers
(Phases 1-16) were already frozen *before* `api`, making it the seventeenth layer overall, not
the sixteenth of a sixteen-layer count. Corrected to *"`api` is the seventeenth layer -- the
first built on top of the sixteen already-frozen Phase 1-16 layers -- and Phase 17's own
package."* This was the only change made in this pass: no executable code, contract, test, or
`pyproject.toml` line was touched.

## Tests

`tests/unit/api/`:

- `test_imports.py` -- execution-based import verification for `src.api`/`src.api.main` (2 tests).
- `test_dependency_boundaries.py` -- static AST-based import checks: no forbidden layer imported,
  no `src.*` import appears at all, no other layer imports `src.api` back (5 tests).
- `test_main.py` -- `health` is a coroutine function and returns the expected liveness mapping;
  `create_app` registers exactly one route; a real `GET /health` request (via
  `fastapi.testclient.TestClient`, no network, no `uvicorn` process) returns `200` with the
  expected body; `POST /health` returns `405`; the module-level `app` behaves identically to a
  freshly-constructed one (6 tests).

13 new tests total.

## Verification results

```
pytest tests/unit/api/ -q      -> 13 passed
pytest -q                      -> 1261 passed (1248 pre-Phase-17 + 13 new)
mypy --strict src/             -> Success: no issues found in 114 source files
ruff check src/ tests/         -> 1 finding: UP046 in src/domain/interfaces.py
                                   (pre-existing, predates Phase 17 -- see below)
ruff check src/api tests/unit/api  -> All checks passed
```

`docs/pytest_report.txt`, `docs/mypy_report.txt`, and `docs/ruff_report.txt` remain Phase-16-era
snapshots (1248 passed / 112 source files) and were not regenerated in this pass -- doing so was
not part of this correction's requested scope. The numbers above are current as of this summary.

**Environment note:** `requires-python = ">=3.13"` could not be satisfied in the verification
sandbox -- only Python 3.12.3 was available through the allowed package sources. Verification ran
under 3.12 (installing the declared dependencies directly, via the project's own
`pythonpath = ["."]` pytest config, without weakening the frozen `requires-python` constraint).
All 1261 tests, `mypy --strict`, and `ruff` passed cleanly under this interpreter; re-verifying
under an actual 3.13 interpreter before tagging/release remains advisable.

## Pre-existing `ruff` finding: `UP046`

```
UP046 Generic class `Repository` uses `Generic` subclass instead of type parameters
 --> src/domain/interfaces.py:19:23
```

Verified, via a completely separate, untouched fresh clone of the original frozen HEAD
(`232af10`), to be identical there with zero Phase 17 changes present -- this predates Phase 17
entirely. It is Phase 2 (Domain layer) code, frozen; the finding reflects `ruff`-version drift
(a newer `ruff` than whatever verified Phase 2 originally now enables this rule against the
`requires-python = ">=3.13"`-inferred target), not anything introduced by this phase.
`src/domain/interfaces.py` was not modified -- doing so is outside this phase's authorization.

## Files created

```
src/api/__init__.py
src/api/main.py
tests/unit/api/__init__.py
tests/unit/api/test_imports.py
tests/unit/api/test_dependency_boundaries.py
tests/unit/api/test_main.py
docs/phase17_summary.md
```

## Files modified

```
pyproject.toml            (+2 lines: fastapi, uvicorn -- nothing else changed)
src/api/__init__.py       (this pass: one-sentence layer-count correction; see above)
```

## Frozen files left untouched

Every Phase 1-16 production file under `src/core`, `src/domain`, `src/repository`,
`src/collectors`, `src/parsers`, `src/extractors`, `src/analyzers`, `src/graph`,
`src/foundation`, `src/storage`, `src/vector`, `src/memory`, `src/pipeline`, `src/application`,
`src/bootstrap`, `src/cli`. Every existing dependency-boundary test, unmodified -- none required
correction (see "Dependency rules" above). No dependency other than `fastapi`/`uvicorn` was
added; no existing dependency's version constraint was changed.
