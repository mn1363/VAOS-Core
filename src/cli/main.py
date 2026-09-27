"""`main`: the CLI layer's synchronous process entry point.

Bridges a process invocation into the existing, async `bootstrap.bootstrap` flow: parses `argv`
via `build_parser` (the standard library's own `argparse` -- no new dependency), loads
`core.config.AppConfig` via `core.config.load_config`, and runs `bootstrap.bootstrap` inside
`asyncio.run`, since `main` itself must be callable synchronously from a plain process entry point
(`if __name__ == "__main__": sys.exit(main())`) while `bootstrap.bootstrap` is `async def`. See
this package's own `__init__.py` for the fuller architectural picture.

`--analyze` is the one addition beyond the pre-existing `--config`/`--help`/`--version` surface.
When given, `_run` passes `bootstrap.analysis_steps.build_analysis_steps(config)` straight through
as `bootstrap.bootstrap`'s own, already-existing `extra_steps` parameter, appending the eleven-step
real-repository analysis composition after the default three-step flow. `build_analysis_steps` is
constructed only inside that one branch; when `--analyze` is absent, `_run` calls `bootstrap(config)`
exactly as it always has, with no `extra_steps` -- the default flow's behavior is unchanged in
every case. Neither `bootstrap.bootstrap` nor `bootstrap.wiring.build_application` gains a new
parameter for this; `extra_steps` was already there.

Every `core.exceptions.VAOSError` that `core.config.load_config`/`bootstrap.bootstrap` may
themselves raise (`ConfigurationError`, `ValidationError`, `BootstrapError`,
`StorageConnectionError`, `QdrantOperationError`, `StepExecutionError` -- see their own
docstrings) is caught at this layer's own outer boundary, written to `stderr` as a plain message
(never a Python traceback), and mapped to exit code 1 -- as is any other, unexpected exception
that reaches this boundary. This already covers every failure mode `--analyze`'s own extra steps
can produce too: each one either raises an existing `VAOSError` subclass directly (e.g. the new
composition's own `BootstrapError` for more than one collected repository) or is wrapped into
`pipeline.base.StepExecutionError` by `Pipeline.run` -- itself a `VAOSError` -- so no new except
clause is added here for it. Neither `bootstrap.bootstrap`'s own exception types nor any
lower-layer exception type is modified, re-defined, or replaced here; this module only decides
what a process does once one reaches it. An `argparse` usage error (an unrecognized argument, a
missing value) is handled entirely by `argparse` itself, which writes its own usage message to
`stderr` and exits the process with status 2 -- `argparse`'s own established convention, not
reimplemented here.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence
from pathlib import Path

from src.bootstrap.analysis_steps import build_analysis_steps
from src.bootstrap.wiring import bootstrap
from src.core.config import load_config
from src.core.constants import APP_NAME, APP_VERSION
from src.core.exceptions import VAOSError
from src.pipeline.base import PipelineResult

#: Process exit code for a successful run.
_EXIT_SUCCESS = 0
#: Process exit code for a VAOS execution failure -- any `core.exceptions.VAOSError`, or an
#: unexpected non-VAOS exception -- that reaches this layer's own outer boundary. (An `argparse`
#: usage error exits with status 2 directly, via `argparse`'s own behavior; see `main`.)
_EXIT_EXECUTION_ERROR = 1


def build_parser() -> argparse.ArgumentParser:
    """Construct the CLI's argument parser.

    Returns:
        A configured `ArgumentParser` exposing `--config`, `--analyze`, and the standard
        `--help`/`--version` flags. `--version` reads `core.constants.APP_NAME`/`APP_VERSION`
        directly -- a clear, already-frozen source that requires no architectural change to
        expose. `--analyze` defaults to False (a plain `action="store_true"` flag); when absent,
        `main`/`_run` behave exactly as they did before this flag existed.
    """
    parser = argparse.ArgumentParser(
        prog=APP_NAME,
        description="Run the configured VAOS default analysis flow.",
    )
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {APP_VERSION}")
    parser.add_argument(
        "--config",
        metavar="PATH",
        type=Path,
        default=None,
        help="Path to a VAOS configuration YAML file (default: configs/config.yaml).",
    )
    parser.add_argument(
        "--analyze",
        action="store_true",
        default=False,
        help=(
            "Also run the real-repository analysis composition "
            "(clone, parse, and extract) after the default flow."
        ),
    )
    return parser


def _format_result(result: PipelineResult) -> str:
    """Render a successful `PipelineResult` as a concise, human-readable summary line.

    Args:
        result: The result returned by a successful `bootstrap.bootstrap` call.

    Returns:
        A one-line summary naming the pipeline and the steps that ran, in order. Does not render
        `result.context`'s own contents -- an internal detail of the flow, not something a CLI
        user needs to see to know the run succeeded.
    """
    steps = ", ".join(result.step_names())
    return (
        f"vaos: '{result.pipeline_name}' completed successfully "
        f"({result.step_count} step(s): {steps})"
    )


async def _run(config_path: Path | None, analyze: bool) -> int:
    """Load configuration and run the selected flow, translating the outcome into an exit code.

    Args:
        config_path: `--config`'s parsed value; `None` if not given, matching
            `core.config.load_config`'s own default-path behavior.
        analyze: `--analyze`'s parsed value. When True, `bootstrap.analysis_steps.
            build_analysis_steps(config)` is constructed and passed as `bootstrap`'s own
            `extra_steps` parameter, appending the real-repository analysis composition after
            the default three-step flow. When False, `bootstrap(config)` is called exactly as
            it was before this parameter existed, with no `extra_steps` -- the default flow's
            behavior is unchanged.

    Returns:
        `0` on success. `1` if `core.config.load_config` or `bootstrap.bootstrap` raises, for any
        reason -- a `core.exceptions.VAOSError` (written to `stderr` as `exc`'s own message) or
        any other, unexpected exception (written to `stderr` without a traceback). This already
        covers every failure mode reachable through `analyze=True`'s own extra steps; see this
        module's own docstring.
    """
    try:
        config = load_config(config_path)
        if analyze:
            result = await bootstrap(config, extra_steps=build_analysis_steps(config))
        else:
            result = await bootstrap(config)
    except VAOSError as exc:
        print(f"vaos: error: {exc}", file=sys.stderr)
        return _EXIT_EXECUTION_ERROR
    except Exception as exc:  # noqa: BLE001 -- this is the CLI's own outer boundary: an
        # unexpected, non-`VAOSError` exception must still map to a non-zero exit rather than a
        # raw traceback (see this module's own docstring), so it is deliberately caught broadly
        # and reported, not re-raised.
        print(f"vaos: unexpected error: {exc}", file=sys.stderr)
        return _EXIT_EXECUTION_ERROR

    print(_format_result(result))
    return _EXIT_SUCCESS


def main(argv: Sequence[str] | None = None) -> int:
    """Run the VAOS command-line interface: the process entry point this layer exposes.

    Args:
        argv: Command-line arguments to parse. Defaults to `sys.argv[1:]` (`argparse`'s own
            default) when `None`.

    Returns:
        The process exit code: `0` on success, `1` on a VAOS execution failure. An `argparse`
        usage error exits the process directly with status `2`, before this function returns, via
        `argparse`'s own `SystemExit` -- `argparse`'s own established convention.
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    config_path: Path | None = args.config
    analyze: bool = args.analyze
    return asyncio.run(_run(config_path, analyze))


if __name__ == "__main__":
    sys.exit(main())
