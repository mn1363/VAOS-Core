"""Import verification for `src.plugins`.

Every `plugins` module must import cleanly on its own -- this is checked separately from
`test_dependency_boundaries.py`'s static analysis, which inspects import *statements* without
executing them.
"""

import importlib

import pytest


@pytest.mark.parametrize(
    "module_name",
    [
        "src.plugins",
        "src.plugins.base",
    ],
)
def test_plugins_module_imports_successfully(module_name: str) -> None:
    """Every `plugins` module should import without raising."""
    importlib.import_module(module_name)
