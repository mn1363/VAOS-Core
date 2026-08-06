# VAOS Phase 1 — Architecture Audit

**Scope:** `src/core` (the only package implemented in Phase 1), plus its tests.
**Status:** All checks pass. Three production-safety defects found during this
audit were fixed in-place before this baseline was frozen; details below.

---

## 1. Core files match the frozen architecture exactly

Frozen `src/core/` contents (per `ARCHITECTURE_FREEZE.md`):
`__init__.py`, `config.py`, `logging.py`, `exceptions.py`, `constants.py`,
`protocols.py`, `utils.py`.

Verified by direct directory listing against that exact set: **match, zero
missing, zero extra.** No files renamed, moved, added, or removed relative to
the frozen tree.

## 2. Every public API has type hints

AST-walked every function, method, and class across all 7 files, checking:
every non-`self`/`cls` parameter is annotated, every function has a return
annotation, every class and function has a docstring.

**Result: 0 issues.** 100% of public (and private) callables are fully
annotated.

## 3. Every module has complete docstrings

Same AST walk: module-level docstring present in all 7 files; every class,
function, and method has a docstring.

**Result: 0 issues.**

## 4. No dead imports

Cross-checked with two independent methods — a custom AST name-usage walk,
and `ruff check --select F401,F811,F841` — to rule out blind spots in either
method alone.

**Result: 0 dead imports, 0 redefinitions, 0 unused locals**, confirmed by
both methods independently.

## 5. No duplicated utilities

Searched for the four categories of logic that would be a duplication risk
across a multi-file package: YAML parsing, filesystem directory creation,
dict-merging, and logger-namespace construction.

| Logic | Canonical owner | Occurrences elsewhere |
|---|---|---|
| `yaml.safe_load(...)` | `utils.read_yaml_file` | 0 |
| `Path.mkdir(...)` | `utils.ensure_directory` | 0 |
| Recursive dict merge | `utils.deep_merge` | 0 |
| `logging.getLogger(f"{APP_NAME}...")` | `logging.get_logger` | 0 |

`config.py` and `logging.py` both call into `utils.py` for YAML loading
rather than each re-implementing it — this is *why* the directory-traversal
and encoding fixes below (found in `utils.py`) automatically protected both
callers at once.

**Result: 0 duplicated implementations.**

## 6. Configuration loading is production-safe

Three real defects were found by deliberately reproducing edge cases against
the running code (not by inspection alone), and fixed:

1. **A directory in place of the config file** (`configs/config.yaml`
   accidentally being a directory, e.g. from a bad deploy/mount) previously
   leaked a raw `IsADirectoryError`. **Fixed:** `read_yaml_file` now catches
   `OSError` around the read and re-raises as the documented
   `ConfigurationError`.
2. **A config file with invalid UTF-8 bytes** previously leaked a raw
   `UnicodeDecodeError`. **Fixed:** the same `OSError`/`UnicodeDecodeError`
   catch above covers this too.
3. **An explicit YAML `null`** for `app_name`, `app_version`, or
   `environment` (e.g. a bare `environment:` key with no value) previously
   became the literal string `"None"` instead of falling back to the
   default, because `Mapping.get(key, default)` only falls back when the key
   is *absent*, not when it is present-but-null. **Fixed:** added `_get_str`,
   which treats "absent" and "present but null" identically.

Confirmed already safe by design (no fix needed):
- YAML is loaded with `yaml.safe_load` (never `yaml.load`/`unsafe_load`), so
  arbitrary Python object deserialization via YAML tags is not possible.
- Environment overrides are pulled through an explicit 4-key whitelist
  (`_ENV_OVERRIDES`), not a blanket copy of `os.environ` — no risk of
  incidentally leaking unrelated environment variables (secrets, etc.) into
  `AppConfig.raw`.
- `load_config` is a pure function with no shared mutable state — safe to
  call concurrently.

All three fixes are covered by dedicated regression tests (`test_utils.py`,
`test_config.py`) that reproduce the original failure and assert the new,
documented behavior.

## 7. Logging initialization is production-safe

Same reproduce-then-fix methodology; two additional real defects found:

4. **An invalid `level_override` string** (e.g. `"NOT_A_REAL_LEVEL"`)
   previously leaked a raw `ValueError` from `Logger.setLevel`. **Fixed:**
   wrapped in a try/except that re-raises as `ConfigurationError`.
5. **A `logging.yaml` that omits `disable_existing_loggers`** previously
   inherited the stdlib `dictConfig` default of `True`, which silently
   disables every logger created *before* `configure_logging()` runs — a
   well-known, easy-to-hit footgun (any module that grabs a logger at import
   time, before bootstrap, would go silent). **Fixed:**
   `schema.setdefault("disable_existing_loggers", False)` is applied before
   calling `dictConfig`, but only when the schema doesn't already decide the
   key explicitly — a deliberate choice is still respected.

Confirmed already safe by design:
- Repeated calls to `configure_logging()` are idempotent — handler counts do
  not accumulate across calls (verified empirically, not just by
  inspection), for both the default fallback path and a real `dictConfig`
  file.
- `configure_logging()` never requires `configs/logging.yaml` to exist — a
  missing file falls back to a working console handler rather than failing
  the application's startup.

Both fixes are covered by dedicated regression tests in `test_logging.py`.

## 8. Exception hierarchy is complete

Every `raise` site across all 7 files raises `NotFoundError`,
`ConfigurationError`, or `ValidationError` — all subclasses of `VAOSError`.
Every `except` clause that catches a raw stdlib exception
(`OSError`, `UnicodeDecodeError`, `yaml.YAMLError`, `ValueError`, `TypeError`,
`AttributeError`, `ImportError`) immediately re-raises it as one of those
three, chained with `from exc`. **No raw exception can escape Core's public
API** — confirmed both by static grep of every raise/except site and by the
five empirical reproductions in §6–7 above.

The four-class hierarchy (`VAOSError` → `ConfigurationError`,
`ValidationError`, `NotFoundError`) is complete for Core's current scope.
`exceptions.py`'s module docstring documents that future layers are expected
to subclass these categories rather than Core pre-inventing
package-specific exceptions (e.g. a future `ParsingError` belongs to
`parsers`, not `core`) — consistent with not redesigning ahead of a phase
that hasn't started.

## 9. Tests cover every public API

Enumerated every public class, function, method, and typed constant across
all 7 files (30 symbols) and cross-checked each name against the full test
suite. Two initial gaps were found and closed:

- `AppConfig` (the class itself) was only ever exercised indirectly through
  `load_config()`'s return value — never constructed directly, and its
  frozen/immutable contract was never actually tested. **Added:**
  `test_appconfig_is_directly_constructible_and_immutable`, which also
  asserts mutation raises `dataclasses.FrozenInstanceError`.
- `ENCODING_UTF8` was exercised in effect (every YAML fixture in the test
  suite is UTF-8) but never asserted as a specific value. **Added:**
  `test_encoding_constant_is_utf8`.

**Result: 30/30 public symbols now directly referenced by the test suite.**
Total test count: **48**, up from 41 before this audit (7 new tests: 2 for
the coverage gaps above, 5 as regression tests for the production-safety
fixes in §6–7).

---

## Summary of changes made during this audit

| File | Change |
|---|---|
| `src/core/utils.py` | `read_yaml_file` now catches `OSError`/`UnicodeDecodeError` around the file read, not just `yaml.YAMLError` around the parse |
| `src/core/config.py` | Added `_get_str` so an explicit YAML `null` falls back to the default instead of becoming the string `"None"` |
| `src/core/logging.py` | `level_override` application wrapped to raise `ConfigurationError` instead of a raw `ValueError`; `disable_existing_loggers` now safely defaults to `False` when the schema omits it |
| `tests/unit/core/test_utils.py` | +2 regression tests (directory-as-file, invalid encoding) |
| `tests/unit/core/test_config.py` | +2 tests (null-value fallback, direct `AppConfig` construction/immutability) |
| `tests/unit/core/test_logging.py` | +2 regression tests (invalid `level_override`, `disable_existing_loggers` footgun) |
| `tests/unit/core/test_constants.py` | +1 test (`ENCODING_UTF8`) |

No package outside `core` was touched. No folder was renamed or moved. No
new top-level package was introduced. No public API was removed or
renamed — only three genuine defects were fixed and one coverage gap closed,
all within the frozen `core` file set.
