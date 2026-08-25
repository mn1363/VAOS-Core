"""Import verification for `src.application`.

Every `application` module must import cleanly on its own -- this is checked separately from
`test_dependency_boundaries.py`'s static analysis, which inspects import *statements* without
executing them. Mirrors `tests/unit/pipeline/test_imports.py`'s own structure exactly.
"""

import importlib

import pytest


@pytest.mark.parametrize(
    "module_name",
    [
        "src.application",
        "src.application.runner",
    ],
)
def test_application_module_imports_successfully(module_name: str) -> None:
    """Every `application` module should import without raising."""
    importlib.import_module(module_name)
