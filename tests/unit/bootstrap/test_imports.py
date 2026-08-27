"""Import verification for `src.bootstrap`.

Every `bootstrap` module must import cleanly on its own -- this is checked separately from
`test_dependency_boundaries.py`'s static analysis, which inspects import *statements* without
executing them. Mirrors `tests/unit/application/test_imports.py`'s own structure exactly.
"""

import importlib

import pytest


@pytest.mark.parametrize(
    "module_name",
    [
        "src.bootstrap",
        "src.bootstrap.errors",
        "src.bootstrap.wiring",
    ],
)
def test_bootstrap_module_imports_successfully(module_name: str) -> None:
    """Every `bootstrap` module should import without raising."""
    importlib.import_module(module_name)
