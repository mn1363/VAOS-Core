"""Import verification for `src.storage`.

Every `storage` module must import cleanly on its own -- this is checked separately from
`test_dependency_boundaries.py`'s static analysis, which inspects import *statements* without
executing them.

`storage.postgres.driver` and `storage.qdrant.driver` each import a third-party client
(`asyncpg`, `qdrant_client`) directly, and neither is yet a declared project dependency (see
`docs/phase10_summary.md`). `pytest.importorskip` marks those two as skipped, not failed, in
whatever environment does not have them installed -- an accurate signal either way, rather than
this test suite silently assuming they're present or hard-failing a clean install that never
opted into them.
"""

import importlib

import pytest


@pytest.mark.parametrize(
    "module_name",
    [
        "src.storage",
        "src.storage.base",
        "src.storage.filesystem",
        "src.storage.filesystem.driver",
        "src.storage.sqlite",
        "src.storage.sqlite.driver",
    ],
)
def test_storage_module_imports_successfully(module_name: str) -> None:
    """Every dependency-free `storage` module should import without raising."""
    importlib.import_module(module_name)


@pytest.mark.parametrize(
    "module_name",
    [
        "src.storage.postgres",
        "src.storage.postgres.driver",
    ],
)
def test_storage_postgres_module_imports_successfully(module_name: str) -> None:
    """`storage.postgres` should import without raising, given `asyncpg` is installed."""
    pytest.importorskip("asyncpg", reason="asyncpg is not yet a declared project dependency")
    importlib.import_module(module_name)


@pytest.mark.parametrize(
    "module_name",
    [
        "src.storage.qdrant",
        "src.storage.qdrant.driver",
    ],
)
def test_storage_qdrant_module_imports_successfully(module_name: str) -> None:
    """`storage.qdrant` should import without raising, given `qdrant_client` is installed."""
    pytest.importorskip(
        "qdrant_client", reason="qdrant-client is not yet a declared project dependency"
    )
    importlib.import_module(module_name)
