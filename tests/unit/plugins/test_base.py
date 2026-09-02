"""Unit and integration tests for `src.plugins.base`.

`test_a_concrete_plugin_can_be_supplied_as_an_existing_extra_step` is this package's own
integration test: it proves a `Plugin` instance flows through `bootstrap.wiring.
build_application`'s already-existing `extra_steps` parameter and executes for real inside a
`Pipeline.run`, without any change to `src.bootstrap` or `src.pipeline` production code. Mirrors
`tests/unit/bootstrap/test_wiring.py::test_build_application_appends_extra_steps`'s own fixture
and configuration shape, substituting a concrete `Plugin` for that test's bare `Step` -- see
`docs/phase18_summary.md` for the full contract this demonstrates.
"""

from typing import Any

import pytest
from src.bootstrap.wiring import build_application
from src.core.config import AppConfig
from src.pipeline.base import Step
from src.pipeline.context import PipelineContext
from src.plugins.base import Plugin


def _config(raw: dict[str, Any]) -> AppConfig:
    """Build an `AppConfig` directly from a raw mapping, bypassing `load_config`/YAML/env."""
    return AppConfig(raw=raw)


class _RecordingPlugin(Plugin):
    """A minimal, concrete `Plugin`, tracking whether it ran."""

    def __init__(self) -> None:
        self.ran = False

    @property
    def name(self) -> str:
        return "recording_plugin"

    async def execute(self, context: PipelineContext) -> PipelineContext:
        self.ran = True
        return context


def test_plugin_is_a_step() -> None:
    """`Plugin` is a `pipeline.base.Step` subtype, adding no new abstract members."""
    assert issubclass(Plugin, Step)


def test_plugin_adds_no_new_abstract_methods() -> None:
    """`Plugin.__abstractmethods__` is exactly `Step`'s own set -- `name` and `execute` -- so
    Phase 18 has added no new required member beyond what Phase 13 already declared."""
    assert Plugin.__abstractmethods__ == Step.__abstractmethods__


def test_concrete_plugin_satisfies_step() -> None:
    """A concrete `Plugin` instance is, by inheritance, already a valid `Step`."""
    plugin = _RecordingPlugin()
    assert isinstance(plugin, Step)
    assert isinstance(plugin, Plugin)


@pytest.mark.asyncio
async def test_a_concrete_plugin_can_be_supplied_as_an_existing_extra_step(
    tmp_path: Any,
) -> None:
    """A `Plugin` flows through `bootstrap.build_application`'s existing `extra_steps` parameter
    and executes for real inside a `Pipeline.run` -- the whole contract this phase adds, proven
    end-to-end with zero change to `src.bootstrap` or `src.pipeline` production code."""
    plugin = _RecordingPlugin()
    config = _config(
        {
            "collectors": {"backend": "filesystem"},
            "storage": {"backend": "filesystem", "filesystem": {"root": str(tmp_path / "s")}},
        }
    )
    pipeline = await build_application(config, extra_steps=[plugin])
    context = PipelineContext(values={"source": str(tmp_path)})
    result = await pipeline.run(context)
    assert result.step_names()[-1] == "recording_plugin"
    assert plugin.ran is True
