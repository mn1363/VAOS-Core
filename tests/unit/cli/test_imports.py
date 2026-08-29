"""Import verification for `src.cli`.

Every `cli` module must import cleanly on its own -- this is checked separately from
`test_dependency_boundaries.py`'s static analysis, which inspects import *statements* without
executing them. Mirrors `tests/unit/bootstrap/test_imports.py`'s own structure exactly.
"""

import importlib

import pytest


@pytest.mark.parametrize(
    "module_name",
    [
        "src.cli",
        "src.cli.main",
    ],
)
def test_cli_module_imports_successfully(module_name: str) -> None:
    """Every `cli` module should import without raising."""
    importlib.import_module(module_name)
