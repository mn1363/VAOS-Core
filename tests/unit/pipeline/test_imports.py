"""Import verification for `src.pipeline`.

Every `pipeline` module must import cleanly on its own -- this is checked separately from
`test_dependency_boundaries.py`'s static analysis, which inspects import *statements* without
executing them. Mirrors `tests/unit/memory/test_imports.py`'s own structure exactly.
"""

import importlib

import pytest


@pytest.mark.parametrize(
    "module_name",
    [
        "src.pipeline",
        "src.pipeline.context",
        "src.pipeline.base",
        "src.pipeline.pipeline",
        "src.pipeline.steps",
    ],
)
def test_pipeline_module_imports_successfully(module_name: str) -> None:
    """Every `pipeline` module should import without raising."""
    importlib.import_module(module_name)
