"""`main`: the CLI layer's synchronous process entry point.

Bridges a process invocation into the existing, async `bootstrap.bootstrap` flow: parses `argv`
via `build_parser` (the standard library's own `argparse` -- no new dependency), loads
`core.config.AppConfig` via `core.config.load_config`, and runs `bootstrap.bootstrap` inside
`asyncio.run`, since `main` itself must be callable synchronously from a plain process entry point
(`if __name__ == "__main__": sys.exit(main())`) while `bootstrap.bootstrap` is `async def`. See
this package's own `__init__.py` for the fuller architectural picture.

Every `core.exceptions.VAOSError` that `core.config.load_config`/`bootstrap.bootstrap` may
themselves raise (`ConfigurationError`, `ValidationError`, `BootstrapError`,
`StorageConnectionError`, `QdrantOperationError`, `StepExecutionError` -- see their own
docstrings) is caught at this layer's own outer boundary, written to `stderr` as a plain message
(never a Python traceback), and mapped to exit code 1 -- as is any other, unexpected exception
that reaches this boundary. Neither `bootstrap.bootstrap`'s own exception types nor any
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
        A configured `ArgumentParser` exposing `--config` and the standard `--help`/`--version`
        flags. `--version` reads `core.constants.APP_NAME`/`APP_VERSION` directly -- a clear,
        already-frozen source that requires no architectural change to expose.
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


async def _run(config_path: Path | None) -> int:
    """Load configuration and run the default flow, translating the outcome into an exit code.

    Args:
        config_path: `--config`'s parsed value; `None` if not given, matching
            `core.config.load_config`'s own default-path behavior.

    Returns:
        `0` on success. `1` if `core.config.load_config` or `bootstrap.bootstrap` raises, for any
        reason -- a `core.exceptions.VAOSError` (written to `stderr` as `exc`'s own message) or
        any other, unexpected exception (written to `stderr` without a traceback).
    """
    try:
        config = load_config(config_path)
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
    return asyncio.run(_run(config_path))


if __name__ == "__main__":
    sys.exit(main())
