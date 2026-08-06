# VAOS Phase 3 — Repository Layer Summary

**Scope:** `src/repository/__init__.py`, `base.py`, `git.py`, `workspace.py`
(exactly the four files the frozen architecture specifies for this package).
**`src/core` and `src/domain` were not modified** — verified by checksum
before this phase and re-confirmed throughout.
**Generated:** 2026-08-06

## What this layer does

`repository` answers one question: *given a `SourceRepository` domain
entity, how do I get a real, local working copy of it on disk, and where
does that copy live?* It does **not** decide which repositories to collect
(that's `collectors`, a later phase) and does **not** persist domain
entities to a database (that's `storage`, also a later phase) — both are
deliberately out of scope here, matching the frozen separation between
these packages.

- **`base.py`** — two abstract Ports, per Dependency Inversion:
  `RepositoryClient` (async: `clone`, `fetch`, `checkout`, `current_commit`,
  `default_branch`) and `WorkspaceManager` (sync: `allocate`, `resolve`,
  `exists`, `remove`) — plus `GitCommandError`, a `core.exceptions.VAOSError`
  subclass for this package's own failure mode.
- **`git.py`** — `GitRepositoryClient`, a real implementation driving the
  system `git` executable via `asyncio.create_subprocess_exec` (not a
  third-party git library, keeping this package's only runtime dependency
  the `git` binary itself). Includes working timeout handling (kills the
  process and raises) and wraps every failure mode into `GitCommandError`.
- **`workspace.py`** — `FilesystemWorkspaceManager`, a real implementation
  allocating one deterministic subdirectory per repository UUID under a
  configurable root, reusing `core.utils.ensure_directory` rather than
  duplicating directory-creation logic.

## Counts

| Metric | Count |
|---|---|
| Repository source files (`src/repository/*.py`) | 4 |
| Repository test files (`test_*.py`) | 3 |
| Repository test functions | 26 |
| **Total project test count (Core + Domain + Repository)** | **122** |
| Total source files (`src/**/*.py`) | 16 |
| Total test files (`tests/**/*.py`) | 18 |
| Public API symbols in `repository` | 23 |

## Verification (all 7 steps)

1. **Import validation** — `py_compile` clean on every file; `src`,
   `src.core`, `src.domain`, `src.repository`, and its 3 submodules all
   import successfully.
2. **AST dependency validation** — every `import`/`from` statement in
   `src/repository/*.py` was walked: `base.py` → `core`, `domain`;
   `git.py` → `repository.base`, `core`, `domain`; `workspace.py` →
   `repository.base`, `core`. No other module is referenced.
3. **Architecture boundary validation** — checked against all 14 forbidden
   layers (`application`, `bootstrap`, `parsers`, `collectors`,
   `extractors`, `analyzers`, `graph`, `foundation`, `storage`, `memory`,
   `vector`, `pipeline`, `plugins`, `api`, `cli`). **Zero violations.**
4. **Circular dependency check** — package-level graph is
   `core → (nothing)`, `domain → core`, `repository → {core, domain}`. No
   cycles. Reverse-direction check confirmed `core` contains no reference
   to `domain` or `repository` (AST-level, not text search).
5. **Unit tests** — 26/26 pass for this layer (122/122 for the whole
   project). Notably, `test_git.py` exercises the **real** `git` binary
   against a throwaway local repository created per-test (git supports
   cloning from a `file://` URI just as it would a remote), proving
   `GitRepositoryClient` genuinely clones, fetches, checks out, and reports
   commit SHAs — not just that it builds the right subprocess arguments.
   The timeout path is tested deterministically by pointing
   `git_executable` at the Python interpreter itself running a `sleep`,
   avoiding any reliance on real git command timing.
6. **mypy --strict** — clean on `src/core` + `src/domain` + `src/repository`
   (15 files) and on the full `tests` tree (18 files, informational).
7. **Ruff** — **fully clean within this phase's scope**
   (`src/repository/` + `tests/unit/repository/`). One finding remains
   project-wide (`UP046` on `Repository`'s `Generic[EntityT]` base in
   `src/domain/interfaces.py`) — pre-existing from Phase 2, already
   reviewed and accepted there, and left untouched here per this phase's
   explicit instruction not to modify anything outside `src/repository/`.
   See `ruff_report.txt` for both the full and scoped runs.

Two real ruff findings *within this phase's scope* were found and fixed
properly (not suppressed): two test functions ran a blocking
`subprocess.run(...)` directly inside `async def` test bodies (`ASYNC221`)
— fixed by moving the blocking call into a small sync helper invoked via
`asyncio.to_thread`. A `# noqa: SLF001` comment turned out to be
unnecessary once checked against this project's actual (default) ruff rule
set, which doesn't enable `SLF001` — removed rather than left in place.

## Package contents added this phase

```
src/repository/
├── __init__.py
├── base.py        (RepositoryClient + WorkspaceManager Ports, GitCommandError)
├── git.py          (GitRepositoryClient — real git-CLI-backed implementation)
└── workspace.py     (FilesystemWorkspaceManager — real filesystem implementation)

tests/unit/repository/
├── __init__.py
├── test_base.py       (3 tests)
├── test_git.py          (15 tests, against a real local git repo)
└── test_workspace.py     (11 tests)

docs/
├── phase3_summary.md   (this file)
├── pytest_report.txt
├── mypy_report.txt
└── ruff_report.txt
```

## Not implemented this phase

Every other package (`application`, `storage`, `bootstrap`, `collectors`,
`parsers`, `extractors`, `analyzers`, `graph`, `scorers`, `foundation`,
`pipeline`, `api`, `cli`, `plugins`, `runtime`) — none were touched.

---

**Phase 3 complete. `src/core` and `src/domain` unmodified. Storage layer
(Phase 4) not started — awaiting your instruction.**
