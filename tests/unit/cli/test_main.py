"""Unit and integration tests for `src.cli.main`.

The one true end-to-end test below (`test_main_runs_the_real_default_flow_...`) runs the real
`core.config.load_config`/`bootstrap.bootstrap` call end-to-end against the `"filesystem"`
collector/storage backends inside a `tmp_path` -- no network, no external process, matching this
repository's own established "tests must not require GitHub, PostgreSQL, Qdrant, external APIs,
network access" convention (see `tests/unit/pipeline/test_integration.py`'s own docstring). Every
other test substitutes `src.cli.main.load_config`/`src.cli.main.bootstrap` directly via
`monkeypatch`, never a `unittest.mock` double, matching this repository's own established testing
convention (see e.g. `tests/unit/bootstrap/test_wiring.py`'s own docstring).

This file does not re-test `bootstrap.bootstrap`'s or `core.config.load_config`'s own internal
behavior in detail -- that is `tests/unit/bootstrap/`'s and `tests/unit/core/`'s own concern. It
tests only what `src.cli.main` itself adds: argument parsing, the sync/async bridge, and the
exit-code/stderr mapping at this layer's own outer boundary.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
import src.cli.main as cli_main
from src.core.config import AppConfig
from src.core.exceptions import ValidationError
from src.pipeline.base import PipelineResult, StepOutcome
from src.pipeline.context import PipelineContext


def _result(pipeline_name: str = "bootstrap_default_flow") -> PipelineResult:
    """Build a minimal, real `PipelineResult` for a fake `bootstrap` to return."""
    return PipelineResult(
        pipeline_name=pipeline_name,
        step_outcomes=(StepOutcome.ok("collect"), StepOutcome.ok("persist_repositories")),
        context=PipelineContext(),
    )


# --------------------------------------------------------------------------------------
# Argument parsing
# --------------------------------------------------------------------------------------


def test_build_parser_accepts_no_arguments() -> None:
    """With no `argv`, `--config` parses to `None` -- `load_config`'s own default-path case."""
    args = cli_main.build_parser().parse_args([])
    assert args.config is None


def test_build_parser_accepts_config_flag() -> None:
    """`--config PATH` parses to a `pathlib.Path`, matching `load_config`'s own `path` type."""
    args = cli_main.build_parser().parse_args(["--config", "configs/config.yaml"])
    assert args.config == Path("configs/config.yaml")


def test_build_parser_version_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    """`--version` is `argparse`'s own built-in `action="version"` behavior: prints and exits 0
    without this module writing any code of its own to do so."""
    with pytest.raises(SystemExit) as exc_info:
        cli_main.build_parser().parse_args(["--version"])
    assert exc_info.value.code == 0
    from src.core.constants import APP_NAME, APP_VERSION

    assert f"{APP_NAME} {APP_VERSION}" in capsys.readouterr().out


def test_build_parser_help_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    """`--help` is `argparse`'s own built-in behavior; the printed usage mentions `--config`."""
    with pytest.raises(SystemExit) as exc_info:
        cli_main.build_parser().parse_args(["--help"])
    assert exc_info.value.code == 0
    assert "--config" in capsys.readouterr().out


def test_build_parser_rejects_unknown_argument_with_usage_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An unrecognized flag is `argparse`'s own usage-error path: exit code 2, a message on
    `stderr` -- not this module's own exit-code-1 execution-error path."""
    with pytest.raises(SystemExit) as exc_info:
        cli_main.build_parser().parse_args(["--not-a-real-flag"])
    assert exc_info.value.code == 2
    assert "vaos: error:" in capsys.readouterr().err


# --------------------------------------------------------------------------------------
# main() -- exit codes and stderr/stdout routing, via a fake `bootstrap`/`load_config`
# --------------------------------------------------------------------------------------


def test_main_returns_zero_and_prints_summary_on_success(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    async def _fake_bootstrap(config: AppConfig) -> PipelineResult:
        return _result()

    monkeypatch.setattr(cli_main, "load_config", lambda path: AppConfig())
    monkeypatch.setattr(cli_main, "bootstrap", _fake_bootstrap)

    exit_code = cli_main.main([])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "bootstrap_default_flow" in captured.out
    assert "completed successfully" in captured.out
    assert captured.err == ""


def test_main_returns_one_and_writes_stderr_on_vaos_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    async def _raising_bootstrap(config: AppConfig) -> PipelineResult:
        raise ValidationError("something about the configured flow is invalid")

    monkeypatch.setattr(cli_main, "load_config", lambda path: AppConfig())
    monkeypatch.setattr(cli_main, "bootstrap", _raising_bootstrap)

    exit_code = cli_main.main([])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert "vaos: error:" in captured.err
    assert "something about the configured flow is invalid" in captured.err


def test_main_returns_one_and_writes_stderr_on_load_config_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def _raising_load_config(path: Path | None) -> AppConfig:
        raise ValidationError("bad configuration file")

    monkeypatch.setattr(cli_main, "load_config", _raising_load_config)

    exit_code = cli_main.main([])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "vaos: error:" in captured.err
    assert "bad configuration file" in captured.err


def test_main_returns_one_without_traceback_on_unexpected_exception(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    async def _raising_bootstrap(config: AppConfig) -> PipelineResult:
        raise RuntimeError("something unrelated to VAOS broke")

    monkeypatch.setattr(cli_main, "load_config", lambda path: AppConfig())
    monkeypatch.setattr(cli_main, "bootstrap", _raising_bootstrap)

    exit_code = cli_main.main([])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "vaos: unexpected error:" in captured.err
    assert "something unrelated to VAOS broke" in captured.err
    assert "Traceback" not in captured.err
    assert "Traceback" not in captured.out


def test_main_passes_parsed_config_path_through_to_load_config(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen: list[Path | None] = []

    def _recording_load_config(path: Path | None) -> AppConfig:
        seen.append(path)
        return AppConfig()

    async def _fake_bootstrap(config: AppConfig) -> PipelineResult:
        return _result()

    monkeypatch.setattr(cli_main, "load_config", _recording_load_config)
    monkeypatch.setattr(cli_main, "bootstrap", _fake_bootstrap)

    config_path = tmp_path / "custom_config.yaml"
    exit_code = cli_main.main(["--config", str(config_path)])

    assert exit_code == 0
    assert seen == [config_path]


def test_main_defaults_config_path_to_none_when_flag_omitted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[Path | None] = []

    def _recording_load_config(path: Path | None) -> AppConfig:
        seen.append(path)
        return AppConfig()

    async def _fake_bootstrap(config: AppConfig) -> PipelineResult:
        return _result()

    monkeypatch.setattr(cli_main, "load_config", _recording_load_config)
    monkeypatch.setattr(cli_main, "bootstrap", _fake_bootstrap)

    cli_main.main([])

    assert seen == [None]


# --------------------------------------------------------------------------------------
# Sync/async bridge
# --------------------------------------------------------------------------------------


def test_run_is_an_async_function() -> None:
    """`_run` must itself be a coroutine function -- `main` is the sync/async bridge over it,
    not the other way around."""
    assert asyncio.iscoroutinefunction(cli_main._run)


def test_main_is_callable_with_no_running_event_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    """`main` must be safely callable from a plain, synchronous process entry point -- i.e.
    outside of any already-running event loop -- since that's how `if __name__ == "__main__":
    sys.exit(main())` invokes it."""
    with pytest.raises(RuntimeError):
        asyncio.get_running_loop()  # sanity check: no loop is running in this test itself

    async def _fake_bootstrap(config: AppConfig) -> PipelineResult:
        return _result()

    monkeypatch.setattr(cli_main, "load_config", lambda path: AppConfig())
    monkeypatch.setattr(cli_main, "bootstrap", _fake_bootstrap)

    assert cli_main.main([]) == 0


# --------------------------------------------------------------------------------------
# Real, end-to-end execution against the filesystem backend (no network, no mocks)
# --------------------------------------------------------------------------------------


def test_main_runs_the_real_default_flow_against_the_filesystem_backend(tmp_path: Path) -> None:
    """One true end-to-end test: exercises the real `load_config`/`bootstrap.bootstrap` call
    `src.cli.main` wires together, against the `"filesystem"` collector and storage backends
    only -- no network, no external process, matching `tests/unit/bootstrap/test_wiring.py`'s
    own established convention. Does not re-verify `bootstrap`'s or any lower layer's own
    behavior in detail; that is already covered by `tests/unit/bootstrap/` and below.
    """
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "example.txt").write_text("hello")
    storage_dir = tmp_path / "storage"

    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "collectors:\n"
        "  backend: filesystem\n"
        f"  source: {source_dir}\n"
        "storage:\n"
        "  backend: filesystem\n"
        "  filesystem:\n"
        f"    root: {storage_dir}\n"
    )

    exit_code = cli_main.main(["--config", str(config_path)])

    assert exit_code == 0
    assert storage_dir.exists()
