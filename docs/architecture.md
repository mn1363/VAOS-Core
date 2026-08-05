# VAOS -- Phase 1 Architecture: Core Skeleton

Status: **Architecture-only.** No business, extraction, analysis, or scoring
logic is implemented. This document describes exactly what Phase 1 ships:
interfaces (Ports), dataclasses (entities, value objects, DTOs), and wiring
(DI container, plugin registry, pipeline orchestrator, bootstrap sequence).

---

## 1. Folder tree

```
vaos/
├── README.md
├── pyproject.toml
├── .gitignore
├── src/
│   ├── core/                      # cross-cutting technical concerns, zero outward deps
│   │   ├── config/                # Settings dataclasses + env-based loader
│   │   │   ├── settings.py
│   │   │   └── loader.py
│   │   ├── container/             # DI container + core provider registration
│   │   │   ├── container.py
│   │   │   └── providers.py
│   │   ├── logging/                # stdlib-based logging setup
│   │   │   └── logger.py
│   │   ├── exceptions/            # VAOSError hierarchy (domain/application/infra)
│   │   │   ├── base.py
│   │   │   ├── domain_exceptions.py
│   │   │   ├── application_exceptions.py
│   │   │   └── infrastructure_exceptions.py
│   │   ├── types/                 # shared TypeVars and type aliases
│   │   │   └── common.py
│   │   └── bootstrap.py           # core bootstrap sequence (see §4)
│   │
│   ├── domain/                    # entities, value objects, enums, events, Ports
│   │   ├── entities/               # Entity, Artifact, AnalysisResult, Task, PluginDescriptor
│   │   ├── value_objects/          # Metadata, Score, strongly-typed identifiers
│   │   ├── enums/                  # ArtifactStatus, TaskStatus, PipelineStageStatus, AnalysisStage
│   │   ├── events/                 # DomainEvent base
│   │   └── repositories/           # Repository[T] Port (persistence abstraction)
│   │
│   ├── application/                # use cases, DTOs, orchestration Ports
│   │   ├── dto/                    # ArtifactDTO, AnalysisResultDTO, TaskDTO
│   │   ├── interfaces/             # Pipeline, PipelineStage, TaskHandler, UnitOfWork, UseCase
│   │   ├── use_cases/              # BaseUseCase scaffolding
│   │   └── pipeline/                # sequential.py (SequentialPipeline), stage.py (BasePipelineStage)
│   │
│   ├── infrastructure/             # adapters implementing domain/application Ports
│   │   ├── persistence/            # (empty in Phase 1 -- future DB adapters)
│   │   ├── messaging/              # (empty in Phase 1 -- future queue adapters)
│   │   └── composition.py          # register_infrastructure() extension point
│   │
│   ├── collectors/                 # interfaces.py: Collector Port | models.py: CollectionResult DTO
│   ├── analyzers/                  # interfaces.py: Analyzer Port | models.py: AnalysisOutcome DTO
│   ├── extractors/                 # interfaces.py: Extractor Port | models.py: ExtractionOutcome DTO
│   ├── scorers/                    # interfaces.py: Scorer Port | models.py: ScoringOutcome DTO
│   │
│   ├── foundation/                 # FoundationService Port -- composes the above end-to-end
│   ├── memory/                     # MemoryStore Port + MemoryEntry DTO
│   ├── repository/                 # Repository Port (re-exported from domain) + AbstractRepository scaffolding
│   ├── graph/                      # GraphStore Port + GraphNode/GraphEdge DTOs
│   ├── vector/                     # VectorStore Port + VectorRecord/VectorMatch DTOs
│   │
│   ├── plugins/                    # Plugin Port + PluginRegistry (concrete, functioning)
│   │
│   ├── api/                        # FastAPI composition root
│   │   ├── main.py                 # create_app()
│   │   ├── dependencies.py         # request-scoped DI glue
│   │   └── routers/health.py       # GET /health
│   │
│   └── cli/                        # argparse composition root
│       ├── main.py                 # build_parser() / main()
│       └── commands/plugins_cmd.py # `vaos plugins list`
│
├── tests/
│   ├── conftest.py
│   ├── unit/                       # container, plugin registry, pipeline, bootstrap
│   └── integration/                 # (structure only in Phase 1)
│
├── configs/
│   └── .env.example                # every VAOS_* variable Settings understands
│
├── docs/
│   └── architecture.md             # this file
│
└── scripts/
    ├── dev_setup.sh                 # venv + editable install
    ├── run_api.sh                   # uvicorn runner
    └── run_cli.sh                   # CLI runner
```

Every package under `src/` is a **top-level, independently importable
package** (`core`, `domain`, `application`, ... `cli`) rather than being
nested under a single `vaos` namespace package. This matches the tree given
in the Phase 1 brief literally: `src/core/`, `src/domain/`, etc. are direct
children of `src/`. `pyproject.toml` maps this via
`[tool.setuptools.packages.find] where = ["src"]`.

---

## 2. Layer responsibilities

| Package | Responsibility | May import |
|---|---|---|
| `core` | Config, DI container, logging, exceptions, shared types | nothing else in VAOS |
| `domain` | Entities, value objects, enums, events, repository Port | `core` |
| `application` | Use case / pipeline / task / unit-of-work Ports, DTOs, concrete pipeline runner | `domain`, `core` |
| `infrastructure` | Adapters implementing domain/application Ports (empty in Phase 1) | `domain`, `application`, `core` |
| `collectors` / `analyzers` / `extractors` / `scorers` | One Port + result DTO per plugin category | `domain`, `core` |
| `foundation` | `FoundationService` Port composing the four categories above | `domain`, `core` |
| `memory` / `graph` / `vector` | Storage Ports for AI memory, knowledge graph, embeddings | `core` (+ own `models.py`) |
| `repository` | Re-exported `Repository[T]` Port + `AbstractRepository` scaffolding for adapters | `domain`, `core` |
| `plugins` | `Plugin` Port + concrete `PluginRegistry` | `core` |
| `api` | FastAPI composition root | every layer |
| `cli` | argparse composition root | every layer |

**Rule enforced throughout:** dependencies point inward. `core` depends on
nothing; `domain` depends only on `core`; `application` depends on `domain`
and `core`; every plugin-category and storage package depends only on
`domain`/`core`; only `api` and `cli` -- the outermost composition roots --
are allowed to import from every other layer. This is why `core/bootstrap.py`
stops after wiring settings, logging and the container: it deliberately does
not know about plugins, infrastructure, or storage adapters.

---

## 3. Dependency graph

```
                         ┌─────────┐
                         │  core   │  (config, DI container, logging, exceptions, types)
                         └────┬────┘
                              │
                         ┌────▼────┐
                         │ domain  │  (entities, value objects, enums, events, Repository Port)
                         └────┬────┘
                              │
                        ┌─────▼──────┐
                        │ application │  (DTOs, Pipeline/UseCase/TaskHandler/UoW Ports, SequentialPipeline)
                        └─────┬──────┘
                              │
        ┌───────────┬─────────┼─────────┬────────────┬───────────┬──────────┐
        │            │         │         │            │           │          │
   ┌────▼───┐  ┌─────▼───┐┌────▼────┐┌───▼─────┐ ┌────▼─────┐┌────▼────┐┌────▼─────┐
   │collectors│ │analyzers││extractors││ scorers │ │foundation││  memory ││infrastructure│
   └────┬───┘  └─────┬───┘└────┬────┘└───┬─────┘ └────┬─────┘└─────────┘└──────────┘
        │            │         │         │            │
        └────────────┴─────────┴─────────┴────────────┘
                              │
                    (graph, vector, repository -- same
                     depth as memory: depend on domain/core only)

                         ┌─────────┐
                         │ plugins │  (depends on core only: Plugin Port + PluginRegistry)
                         └────┬────┘
                              │
                    ┌─────────┴─────────┐
                    │                   │
               ┌────▼────┐         ┌────▼────┐
               │   api   │         │   cli   │   composition roots -- may import everything
               └─────────┘         └─────────┘
```

No cycles exist: `core` never imports `domain`; `domain` never imports
`application`; none of `collectors/analyzers/extractors/scorers/foundation/
memory/graph/vector/repository/plugins` import each other or `infrastructure`.
Only `api` and `cli` tie every layer together, each in its own composition
function (`api.main.create_app`, `cli.main.main`).

---

## 4. Bootstrap order

### 4.1 Core bootstrap (`core.bootstrap.bootstrap`)

1. Load `Settings` from environment variables (`core.config.loader.load_settings`).
2. Configure the `vaos` root logger from `Settings.logging` (`core.logging.logger.configure_logging`).
3. Create an empty `Container`.
4. Register core singletons only: `Settings`, `logging.Logger`
   (`core.container.providers.register_core_services`).
5. Return `(settings, container)` to the caller.

### 4.2 API composition root (`api.main.create_app`)

1. Run core bootstrap (§4.1).
2. `register_infrastructure(container, settings)` -- extension point, currently a no-op.
3. Register a `PluginRegistry` singleton into the container.
4. Construct the `FastAPI` app, attach `settings` and `container` to `app.state`.
5. Include `health_router` (`GET /health`).
6. Return the app. Module-level `app = create_app()` makes `api.main:app`
   a valid `uvicorn` target.

### 4.3 CLI composition root (`cli.main.main`)

1. Build the `argparse` parser (`--version`, `plugins list`).
2. Parse `argv`.
3. Run core bootstrap (§4.1).
4. `register_infrastructure(container, settings)`.
5. Register and resolve `PluginRegistry`.
6. Dispatch to the matching command handler (currently only `plugins list`);
   otherwise print help.

Both composition roots repeat steps 2-3 independently rather than sharing a
combined "outer bootstrap" function, so that adding an API-only or CLI-only
service later does not force the other entrypoint to depend on it.

---

## 5. Extension points for later phases

- `infrastructure.composition.register_infrastructure` -- add concrete
  adapters (SQL repository, vector DB client, graph DB client) and register
  them against the Ports in `domain.repositories.interfaces`,
  `memory.interfaces`, `graph.interfaces`, `vector.interfaces`.
- `repository.base.AbstractRepository` -- subclass per concrete store.
- `plugins.registry.PluginRegistry` -- `api.main.create_app` and
  `cli.main.main` both create an empty registry; a future phase adds plugin
  discovery (e.g. entry-point scanning) and calls `plugin.setup(container)`
  for each discovered `Plugin` before the app/CLI is returned.
- `foundation.interfaces.FoundationService` -- the future implementation
  composes `Collector` → `Extractor` → `Analyzer` → `Scorer` into a
  `SequentialPipeline` and returns a `FoundationReport`.

## 6. Key design decisions

- **No third-party DI framework.** `core.container.Container` is a ~40-line
  singleton/factory registry keyed by type. It is real, functioning wiring
  code (explicitly permitted by the Phase 1 brief), not a placeholder.
- **No ORM / settings framework dependency.** `Settings` is a tree of frozen
  dataclasses populated by `core.config.loader.load_settings` reading
  `os.environ`; this keeps `core` dependency-free and avoids pinning a
  settings library before Phase 2 requirements are known.
- **`repository`, `memory`, `graph`, `vector`, `foundation` ship Ports and
  DTOs only.** Per the brief's "no placeholder fake implementations" rule,
  none of these packages contain an in-memory or SQLite stand-in; concrete
  adapters are deferred to `infrastructure` in a later phase.
- **Entity identity vs. value equality.** `domain.entities.base.Entity`
  defines identity-based `__eq__`/`__hash__` (by `id`). Every subclass is
  declared `@dataclass(eq=False, kw_only=True)` so it inherits that identity
  semantics instead of generating a field-by-field equality method.
- **`interfaces.py` vs. `base.py` naming rule (established in the Freeze
  Audit, §7).** `interfaces.py` holds Port/ABC contracts only, with no
  concrete logic: `collectors`, `analyzers`, `extractors`, `scorers`,
  `domain.repositories`, `foundation`, `memory`, `graph`, `vector`.
  `base.py` holds a concrete base/scaffolding class meant to be subclassed
  for shared plumbing: `domain.entities.base.Entity`,
  `domain.events.base.DomainEvent`, `core.exceptions.base.VAOSError`,
  `application.use_cases.base.BaseUseCase`,
  `repository.base.AbstractRepository`. No file mixes both roles.
- **Verification performed on this skeleton:** every file passes
  `python -m py_compile`; every module across `core`, `domain`,
  `application`, `infrastructure`, the four plugin categories, `foundation`,
  `memory`, `repository`, `graph`, `vector`, and `plugins` imports
  successfully; `api.main.create_app()` builds a working FastAPI app whose
  `/health` endpoint returns `200`; `cli.main.main` correctly handles
  `--version`, `plugins list`, and no-args/help; the full `pytest` suite
  (10 tests covering bootstrap, the container, the plugin registry, and the
  pipeline orchestrator) passes.

---

## 7. Freeze Audit (post-Phase-1 architecture review)

A full audit was run against the frozen architecture: an automated,
AST-based import graph was built for all 16 top-level packages and checked
for cycles (DFS) and for violations of the layering table in §2; every
package's exported surface (`__init__.py` `__all__`) was diffed before and
after each fix. Verified clean, no action needed:

- **Circular dependencies: none.** Confirmed by automated cycle detection
  over the real import graph, not by inspection.
- **Dependency direction: clean.** `core` imports nothing in-repo; `domain`
  imports only `core`; `application` imports only `domain`/`core`; every
  plugin category and storage package imports only `domain`/`core`; `api`
  and `cli` are the only packages that import across every layer.

Issues found and fixed (all internal, zero `__init__.py` export changes):

1. **Type inconsistency -- `artifact_id`.** `AnalysisOutcome`,
   `ExtractionOutcome`, and `ScoringOutcome` typed `artifact_id: str` while
   every other reference to the same identifier (`AnalysisResult.artifact_id`,
   `FoundationReport.artifact_id`, and `Artifact.id` itself, inherited from
   `Entity.id: UUID`) is `UUID`. Fixed: all three now use `UUID`.
2. **Duplicate responsibility -- `repository/interfaces.py`.** This file
   only re-exported `domain.repositories`'s `Repository` Port with no
   distinct behavior. Fixed: deleted; `repository/__init__.py` and
   `repository/base.py` now import `Repository` from `domain.repositories`
   directly. `repository`'s public surface (`Repository`,
   `AbstractRepository`) is unchanged.
3. **Naming inconsistency -- Port-definition files.** The same role (a
   file containing only a Port/ABC, no concrete logic) was named `base.py`
   in five packages and `interfaces.py` in five others. Fixed: standardized
   on `interfaces.py` for that role everywhere (see the rule in §6). Renamed
   `collectors/base.py`, `analyzers/base.py`, `extractors/base.py`,
   `scorers/base.py`, `domain/repositories/base.py` to `interfaces.py`. Each
   package's `__init__.py` export is unchanged; only the internal module
   path moved, and only within its own already-frozen folder.
4. **Naming smell -- `application/pipeline/pipeline.py`.** A
   package/module-name stutter (`application.pipeline.pipeline`). Fixed:
   renamed to `sequential.py`, matching the sibling `stage.py` convention
   (file named after its class, `SequentialPipeline`). Verified low blast
   radius before renaming: only 2 in-tree call sites (`application/pipeline/
   __init__.py` and one test), both updated.

Issues found and deliberately **not** fixed, logged as Phase 2 items:

5. **Unused value objects.** `ArtifactId`, `AnalysisResultId`, `TaskId`,
   `PluginId` in `domain/value_objects/identifiers.py` are exported but
   consumed nowhere in the tree. Not fixed: wiring them into every entity/DTO
   id field is a non-minimal change, and removing the exports would violate
   the "never change public API" constraint of this review. Needs an
   explicit Phase 2 decision (wire in, or formally deprecate).
6. **`CollectionResult` vs. sibling `*Outcome` naming.** `collectors`'s
   result DTO is suffixed `Result`; `analyzers`/`extractors`/`scorers` use
   `Outcome`. Not fixed: renaming an exported class is a public API change
   and needs explicit sign-off, not a silent audit fix.
7. **`core/logging` shadows the stdlib `logging` module name.** Verified
   this causes no actual collision (`core.logging` is only reachable by its
   dotted path; every `import logging` inside it correctly resolves to the
   stdlib module -- confirmed by the full import-graph run in this audit).
   Not fixed: renaming the folder would touch `core`, `application`,
   `plugins`, `api`, `cli`, and `tests` for a non-bug, purely hygienic
   concern -- not minimal.

**Re-verification after fixes:** `py_compile` clean on all files; the same
AST-based import graph re-run shows zero cycles and unchanged layering;
every module in every package imports successfully; `api.main.create_app()`
`/health` still returns `200`; `cli.main.main` still handles all three
commands; all 10 `pytest` tests still pass.

**Architecture Freeze: APPROVED**, with items 5-7 above logged as
non-blocking Phase 2 watch-items.
