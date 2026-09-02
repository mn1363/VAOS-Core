# Phase 18 Summary: Plugins Layer

## Responsibility

`plugins` defines the Phase 18 contract a caller-supplied extension implements: a `Plugin`, a
named subtype of the already-frozen `pipeline.base.Step` adding zero new abstract members. It
does not decide what any given plugin does, how one is discovered, registered, versioned, given a
lifecycle, or wired into `bootstrap`, `cli`, or `api` at runtime -- those remain later,
not-yet-decided concerns, exactly as `parsers`/`extractors`/`analyzers`/`graph`/`foundation`
remain fully built but unwired into any live flow as of Phase 17.

## Extension points evaluated

Every layer named in this phase's own brief was inspected for an existing, caller-extensible
attachment point before any contract was chosen:

| Candidate | Finding |
|---|---|
| `Collector` (implementation of `collectors.base.Collector`) | 4 fixed providers, selected by a hardcoded branch in `bootstrap.wiring.build_collector`, keyed to a frozen `domain.entities.RepositoryProvider` enum. No registry. |
| `Parser` | 5 fixed languages, same closed-enum pattern (`SourceLanguage`); additionally not wired into any live flow at all. |
| `Extractor` | 7 fixed concerns, no registry. |
| `Analyzer` | 8 fixed concerns, no registry. |
| Graph `Builder` | 4 fixed concerns, no registry. |
| Foundation Port | 5 fixed concerns, no registry. |
| Generic dynamic discovery (`importlib`/`pkgutil`/entry points) | Zero precedent anywhere in `src/` -- confirmed by direct search. Building one would be a new capability, not a derivable contract. |
| `pipeline.base.Step` + `bootstrap.wiring.build_application`'s `extra_steps: Sequence[Step]` | The one existing, generic, caller-extensible attachment point already present in the frozen architecture, and confirmed unused by every current caller (`cli`, `api`). **Selected.** |

## Public interface

One class, `src/plugins/base.py::Plugin(Step, ABC)`. Adds no new abstract members; a concrete
plugin implements exactly `Step`'s own two members:

- `name: str` (property)
- `async execute(context: PipelineContext) -> PipelineContext`

Any `Plugin` instance already satisfies `Step` by inheritance and is therefore already a valid
member of `bootstrap.wiring.build_application`'s existing `extra_steps` parameter.

## Explicitly out of scope

No dynamic discovery, entry-point loading, directory scanning, configuration schema, lifecycle
(`start`/`stop`), plugin manager, or `cli`/`api` integration is implemented anywhere in this
phase. Each was evaluated (see above) and found to be either unevidenced by the current repository
or outside this phase's approved contract.

## Dependency rules

`src/plugins` may import `core` and `pipeline` only. Forbidden: `domain`, `repository`,
`collectors`, `parsers`, `extractors`, `analyzers`, `graph`, `foundation`, `storage`, `vector`,
`memory`, `application`, `bootstrap`, `cli`, `api`.

## Boundary-test correction (Phase 18)

`tests/unit/pipeline/test_dependency_boundaries.py::test_no_other_layer_imports_pipeline` now
also exempts `src/plugins`, for a different reason than its three existing exemptions
(`application`, `bootstrap`, `cli`, each an assembler sharing pipeline's "assemble a flow" gap):
`Plugin(Step, ABC)` is a named subtype of `pipeline.base.Step` and must import it to subclass it.
This phase's approved contract explicitly authorizes exactly this one edge, `Plugins -> Pipeline`,
and nothing else `src/plugins` imports. This is a correction to what this one test checks, not to
Phase 13's own dependency rule or any Phase 1-17 production code -- neither was touched. It is the
only change made to any file outside `src/plugins/`, `tests/unit/plugins/`, and this document.

## Explicitly not revived

A `src/plugins/` package existed once before, at Phase 2-3 (commit `031c67c`), deleted in the
"Restore VAOS after stale module cleanup" commit (`544eef4`) that preceded Phase 4. It was built
around:

- `core.container.container.Container`
- `plugins.interface.Plugin(ABC)` -- `name`, `version`, `async setup(container: Container)`,
  `async teardown()`
- `plugins.registry.PluginRegistry` -- a name-keyed registry backed by that `Container`
- `core.exceptions.infrastructure_exceptions.PluginError`
- `domain.entities.plugin` (a `Plugin` domain entity)
- `cli.commands.plugins_cmd`
- `infrastructure.composition.register_infrastructure`

None of it exists in this phase. It is structurally incompatible with the plain-function,
no-DI-container, no-service-locator convention every layer since Phase 4 has followed, independent
of the general rule against reviving deleted architecture.

## Tests

- `tests/unit/plugins/test_imports.py` -- both modules import cleanly.
- `tests/unit/plugins/test_dependency_boundaries.py` -- only `core`/`pipeline` imported; every
  other layer forbidden; no layer anywhere in `src/` imports `src.plugins` back (no exemption
  granted -- this phase does not wire itself into any caller).
- `tests/unit/plugins/test_base.py` -- `Plugin` is a `Step` subtype adding no new abstract
  members; a concrete `Plugin` satisfies both `Step` and `Plugin`; an integration test constructs
  a concrete `Plugin`, passes it to `bootstrap.wiring.build_application`'s existing `extra_steps`
  parameter, and runs it inside a real `Pipeline.run` -- proving the whole contract end-to-end
  with zero change to `src.bootstrap` or `src.pipeline` production code.

## Verification results

See `docs/pytest_report.txt`, `docs/mypy_report.txt`, `docs/ruff_report.txt` (regenerated this
phase).

## Files created

```
src/plugins/__init__.py
src/plugins/base.py
tests/unit/plugins/__init__.py
tests/unit/plugins/test_imports.py
tests/unit/plugins/test_dependency_boundaries.py
tests/unit/plugins/test_base.py
docs/phase18_summary.md
```

## Files modified (authorized correction only)

```
tests/unit/pipeline/test_dependency_boundaries.py
```

One exemption added to `test_no_other_layer_imports_pipeline` and its docstring, plus one
paragraph added to the module's own docstring, documenting the correction. No other line in this
file was touched; no Phase 13 production code was touched.

## Frozen files left untouched

Every file under `src/` outside `src/plugins/` -- all of Phase 1 through Phase 17's production
code -- is byte-for-byte unchanged. Every test file outside `tests/unit/plugins/` and the one
documented exemption above is byte-for-byte unchanged.
