# VAOS Phase 1 — Release Summary

**Package:** Phase 1 (Core) — frozen baseline
**Scope:** `src/core` only, per the frozen architecture (`ARCHITECTURE_FREEZE.md`)
**Generated:** 2026-08-03

This package is the frozen Phase-1 baseline for VAOS. No source code was
modified while assembling it; the numbers below reflect exactly what
`architecture_audit.md`, `dependency_graph.md`, `ruff_report.txt`,
`mypy_report.txt`, and `pytest_report.txt` in this same `docs/` folder
independently show.

## Counts

| Metric | Count |
|---|---|
| Source files (`src/core/*.py`) | 7 |
| Source files (`src/` total, incl. `src/__init__.py`) | 8 |
| Test module files (`tests/unit/core/test_*.py`) | 6 |
| Test files total (incl. `__init__.py`/`conftest.py`) | 10 |
| **Total test count (collected by pytest)** | **48** |
| Config files (`configs/*.yaml`) | 2 |
| Public API symbols (functions, classes, methods, typed constants) | 30 |

## Tool status

| Tool | Command | Status |
|---|---|---|
| **ruff** | `ruff check src tests --line-length 100` | ✅ **All checks passed** (0 issues) |
| **mypy** | `mypy src/core --strict` | ✅ **Success: no issues found in 7 source files** |
| **mypy** | `mypy tests --strict` (informational) | ✅ **Success: no issues found in 10 source files** |
| **pytest** | `pytest -v` | ✅ **48 passed, 0 failed, 0 errors, 0 skipped** |

Full raw output for each is in `ruff_report.txt`, `mypy_report.txt`, and
`pytest_report.txt` in this folder.

## Dependency graph summary

- **Cycles: none.** `constants`, `exceptions`, and `protocols` are leaves;
  `utils` depends on `constants` + `exceptions`; `config` and `logging` each
  depend on `constants` + `exceptions` + `utils`, and not on each other.
- **Package-boundary violations: none.** `core` imports nothing from any of
  the other 19 frozen top-level packages (`domain`, `application`,
  `bootstrap`, `parsers`, `collectors`, `extractors`, `analyzers`,
  `scorers`, `graph`, `foundation`, `repository`, `storage`, `memory`,
  `vector`, `pipeline`, `plugins`, `runtime`, `api`, `cli`) — verified by an
  AST walk of every import statement, not by inspection.
- Full graph, edge list, and the reproducible methodology are in
  `dependency_graph.md`.

## Architecture verification

- **File set:** `src/core/` contains exactly the 7 files the frozen
  architecture specifies — no more, no fewer, none renamed or moved.
- **Type hints:** 100% of functions/methods have fully annotated parameters
  and return types (AST-verified).
- **Docstrings:** 100% of modules, classes, functions, and methods have a
  docstring (AST-verified).
- **Dead imports:** none (verified by two independent methods).
- **Duplicated utilities:** none — YAML parsing, directory creation, dict
  merging, and logger-namespace construction each exist in exactly one
  place.
- **Configuration & logging production-safety:** 5 real defects were found
  by reproducing edge cases against the running code and fixed before this
  baseline was frozen (a directory in place of a config file, invalid UTF-8
  content, explicit YAML `null` values collapsing to the string `"None"`,
  an invalid `level_override` leaking a raw `ValueError`, and
  `dictConfig`'s `disable_existing_loggers` footgun). Every fix has a
  dedicated regression test. Full detail in `architecture_audit.md`.
- **Exception hierarchy:** complete for Core's current scope
  (`VAOSError` → `ConfigurationError`, `ValidationError`, `NotFoundError`);
  every raise/except site in the package was enumerated and confirmed to
  use it — no raw stdlib exception can escape Core's public API.
- **Test coverage of public APIs:** 30/30 public symbols are directly
  referenced by the test suite (2 initial gaps — `AppConfig` itself and
  `ENCODING_UTF8` — were found and closed during this audit).

## Package contents

```
vaos/
├── .env.example
├── .gitignore
├── pyproject.toml
├── configs/
│   ├── config.yaml
│   └── logging.yaml
├── docs/
│   ├── architecture_audit.md
│   ├── dependency_graph.md
│   ├── ruff_report.txt
│   ├── mypy_report.txt
│   ├── pytest_report.txt
│   └── phase1_summary.md
├── src/
│   ├── __init__.py
│   └── core/
│       ├── __init__.py
│       ├── config.py
│       ├── constants.py
│       ├── exceptions.py
│       ├── logging.py
│       ├── protocols.py
│       └── utils.py
└── tests/
    ├── __init__.py
    ├── conftest.py
    └── unit/
        ├── __init__.py
        └── core/
            ├── __init__.py
            ├── test_config.py
            ├── test_constants.py
            ├── test_exceptions.py
            ├── test_logging.py
            ├── test_protocols.py
            └── test_utils.py
```

## Not included in this baseline

Every package other than `core` (`domain`, `application`, `repository`,
`storage`, `bootstrap`, `collectors`, `parsers`, `extractors`, `analyzers`,
`graph`, `scorers`, `foundation`, `pipeline`, `api`, `cli`, `plugins`,
`runtime`), plus `scripts/`, `LICENSE`, `configs/plugins.yaml`, and the
remaining `docs/` files named in the frozen tree
(`ARCHITECTURE_FREEZE.md`, `BOOTSTRAP_ORDER.md`, `DEPENDENCY_GRAPH.md`,
`CODING_RULES.md`, `EXTENSION_GUIDE.md`, `FOUNDATION_GUIDE.md`) are
deliberately absent — they belong to their own later phases.

---

**This baseline is frozen. Phase 2 (Domain) has not been started.**
