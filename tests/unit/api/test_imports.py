"""Import verification for `src.api`.

Every `api` module must import cleanly on its own -- this is checked separately from
`test_dependency_boundaries.py`'s static analysis, which inspects import *statements* without
executing them. Mirrors `tests/unit/cli/test_imports.py`'s own structure exactly.
"""

import importlib

import pytest


@pytest.mark.parametrize(
    "module_name",
    [
        "src.api",
        "src.api.main",
    ],
)
def test_api_module_imports_successfully(module_name: str) -> None:
    """Every `api` module should import without raising."""
    importlib.import_module(module_name)
