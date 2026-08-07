# VAOS Phase 4 — Collectors Layer Summary

**Scope:** `src/collectors/__init__.py`, `base.py`, `filesystem.py`, `local.py`,
`github.py`, `gitlab.py` (one file per `RepositoryProvider` value, plus the
shared Port/DTO module — exactly the four-provider split the frozen `domain`
layer's own `RepositoryProvider` docstring specifies for this package).
**`src/core`, `src/domain`, and `src/repository` were not modified.**
**Generated:** 2026-08-07

## What this layer does

`collectors` answers one question: *which `SourceRepository` entities exist
at a given source location?* It does **not** fetch a repository's contents
onto disk (that's `repository`, already built) and does **not** persist
entities to a store (that's `storage`, a later phase) — both are
deliberately out of scope here, matching the frozen separation between
these packages.

- **`base.py`** — the `Collector` Port (async `collect(source) ->
  CollectionResult`, plus an abstract `provider` property) and the
  `CollectionResult` outcome DTO. Unlike `repository`'s Ports, which raise
  `GitCommandError` for any failure, `collect` reports failure through the
  returned `CollectionResult` rather than raising — a single call commonly
  represents a directory *scan* that may legitimately encounter many
  invalid sources, and raising on the first one would abort discovery of
  everything else. `CollectionResult.__post_init__` enforces its own
  success/failure invariants, raising `core.exceptions.ValidationError` on
  an inconsistent construction, the same exception `collect` raises for a
  blank `source` argument — no new package-specific exception class was
  introduced, since `ValidationError` already covers both cases (the same
  reuse-over-invention principle `domain` follows for its own checks).
- **`filesystem.py`** — `FilesystemCollector`, which treats one already-known
  local directory as exactly one `SourceRepository`, git-managed or not.
- **`local.py`** — `LocalCollector`, which scans a directory tree for nested
  git repositories (a directory containing a `.git` entry). Discovered
  repositories are not descended into further, hidden directories are
  skipped, and the scan depth is bounded (`max_depth`, inclusive). The
  actual filesystem walk runs on a worker thread via `asyncio.to_thread` so
  a large tree doesn't block the event loop.
- **`github.py` / `gitlab.py`** — `GitHubCollector` and `GitLabCollector`,
  which validate and normalize a hosted-repository reference (an
  `owner/repo` slug, an `https://` URL, or a `git@...` SSH URL) into a
  canonical `SourceRepository`. Neither makes a network request — they only
  recognize well-formed references; existence is discovered later, when
  `repository.RepositoryClient.clone` is actually attempted. `GitLabCollector`
  additionally accepts arbitrarily nested `group/subgroup/project` paths,
  unlike GitHub's flat `owner/repo`, since that's how GitLab's own
  namespacing actually works.

`src.repository` is an allowed dependency per this phase's instructions, but
no file here imports it: collecting (deciding which repositories exist) has
no genuine need to invoke `RepositoryClient`/`WorkspaceManager` — actually
fetching a repository's contents is a separate, later step. This is a
deliberate scope decision, not an oversight.

## A pre-existing repository defect found before this phase started

Before writing any Collectors code, the initial clone of this repository
(prior to your cleanup) had `src/core` and `src/domain` each containing two
competing implementations of the same modules (`entities`, `exceptions`,
`config`, `logging`) — a stale nested-package version alongside the intended
flat-file version. Python resolves a same-named package over a module in the
same directory, so the stale versions silently shadowed the real ones, and
`src.repository.base` — Phase 3, supposedly frozen — could not actually be
imported (`ModuleNotFoundError: No module named 'core'`, from the stale
package's own unprefixed internal imports). This was reported and you
resolved it directly (commit `544eef4`, "Restore VAOS after stale module
cleanup") before this phase's work began. Re-verified as part of this
phase's own import validation, below: `src.core`, `src.domain`, and
`src.repository` now import cleanly and their existing 122 tests pass
unmodified.

## One dependency-manifest fix outside `src/collectors/`

`pyproject.toml`'s `dev` extra listed `pytest` but not `pytest-asyncio`,
even though the existing (Phase 3) test suite already depends on it —
17 async tests fail outright, not skip, without it installed (verified
directly). Since this phase adds its own async tests, the gap would only
get worse left alone. Added `pytest-asyncio>=0.24` to `[project.optional-
dependencies].dev`. This is the only change outside `src/collectors/` and
`tests/unit/collectors/`; no line of `src/core/`, `src/domain/`, or
`src/repository/` code was touched.

## Counts

| Metric | Count |
|---|---|
| Collectors source files (`src/collectors/*.py`) | 6 |
| Collectors test files (`test_*.py`) | 5 |
| Collectors test functions (test cases after parametrization) | 36 (53) |
| **Total project test count (Core + Domain + Repository + Collectors)** | **175** |
| Total source files (`src/**/*.py`) | 22 |
| Total test files (`tests/**/*.py`) | 24 |
| Public API symbols in `collectors` | 8 (`Collector`, `CollectionResult`, `require_source`, `strip_git_suffix`, `FilesystemCollector`, `LocalCollector`, `GitHubCollector`, `GitLabCollector`) |

## Verification (all 7 steps)

1. **Import validation** — every file in `src/collectors/` and its 5
   submodules import successfully under the project's `src.`-prefixed
   convention (`pythonpath = ["."]`), individually verified via
   `importlib.import_module`.
2. **AST dependency validation** — every `import`/`from` statement in
   `src/collectors/*.py` was walked (not text-searched): `base.py` →
   `core`, `domain`; `filesystem.py`, `local.py`, `github.py`, `gitlab.py`
   → `collectors.base` (relative), `domain`. No file imports `repository`
   or anything outside the allowed set.
3. **Architecture boundary validation** — checked against all 14 forbidden
   layers (`application`, `bootstrap`, `parsers`, `extractors`,
   `analyzers`, `graph`, `foundation`, `storage`, `memory`, `vector`,
   `pipeline`, `plugins`, `api`, `cli`). **Zero violations.**
4. **Circular dependency check** — package-level graph is
   `core → (nothing)`, `domain → core`, `repository → {core, domain}`,
   `collectors → {core, domain}`. No cycles. Reverse-direction check
   confirmed neither `core`, `domain`, nor `repository` reference
   `collectors` (AST-level).
5. **Unit tests** — 53/53 pass for this layer (175/175 for the whole
   project). `LocalCollector` is tested against a real filesystem tree
   built per-test with `tmp_path` (nested `.git` markers, hidden
   directories, depth boundaries) — not mocked. `GitHubCollector` and
   `GitLabCollector` are tested against every accepted reference form
   (slug, HTTPS, HTTPS+`.git`, SSH) plus a battery of rejected forms,
   including cross-provider confusion (a GitLab URL given to
   `GitHubCollector` and vice versa).
6. **mypy --strict** — clean on `src/core` + `src/domain` + `src/repository`
   + `src/collectors` (21 files) and on the full `tests` tree (24 files,
   informational).
7. **Ruff** — **fully clean within this phase's scope**
   (`src/collectors/` + `tests/unit/collectors/`). One finding remains
   project-wide (`UP046` on `Repository`'s `Generic[EntityT]` base in
   `src/domain/interfaces.py`) — pre-existing from Phase 2, already
   reviewed and accepted there, and left untouched here per this phase's
   explicit instruction not to modify `src/domain/`. See `ruff_report.txt`
   for both the full and scoped runs.

One real ruff finding within this phase's scope was found and fixed
properly (not suppressed): `strip_git_suffix`'s conditional slice
(`FURB188`) was rewritten to `str.removesuffix`, and import ordering
(`I001`) across the new files was corrected — both via `ruff check --fix`,
then re-verified with a clean re-run.

One test bug, unrelated to `src/collectors/` itself, was found and fixed
during verification: `test_collect_skips_hidden_directories` asserted no
discovered `source_uri` contained the substring `"hidden"`, but pytest's own
`tmp_path` fixture names its directory after the truncated test function
name — `test_collect_skips_hidden_dire0` — which itself contains "hidden",
producing a false-positive failure unrelated to `LocalCollector`'s actual
(correct) behavior. Fixed by asserting the exact discovered set instead of
a substring match.

## Package contents added this phase

```
src/collectors/
├── __init__.py
├── base.py          (Collector Port, CollectionResult DTO, require_source, strip_git_suffix)
├── filesystem.py      (FilesystemCollector — single directory as one repository)
├── local.py             (LocalCollector — recursive nested-repository scan)
├── github.py               (GitHubCollector — reference validation/normalization)
└── gitlab.py                 (GitLabCollector — reference validation/normalization)

tests/unit/collectors/
├── __init__.py
├── test_base.py         (11 test functions, 13 cases)
├── test_filesystem.py     (6 tests)
├── test_local.py            (11 tests)
├── test_github.py             (4 test functions, 13 cases)
└── test_gitlab.py                (4 test functions, 10 cases)

docs/
├── phase4_summary.md   (this file)
├── pytest_report.txt
├── mypy_report.txt
└── ruff_report.txt
```

## Not implemented this phase

Every other package (`application`, `storage`, `bootstrap`, `parsers`,
`extractors`, `analyzers`, `graph`, `scorers`, `foundation`, `pipeline`,
`api`, `cli`, `plugins`, `runtime`) — none were touched. No live network
calls to GitHub's or GitLab's APIs are made anywhere in this layer, by
design (see "What this layer does," above) — actual repository existence
is verified later, by `repository.RepositoryClient.clone`.

---

**Phase 4 complete. `src/core`, `src/domain`, and `src/repository`
unmodified. Next phase not started — awaiting your instruction.**
