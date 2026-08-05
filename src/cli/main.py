"""CLI application bootstrap: the command-line layer's composition root."""

import argparse
import sys
from collections.abc import Mapping, Sequence

from cli.commands.plugins_cmd import add_plugins_parser, handle_plugins_command
from core.bootstrap import bootstrap
from infrastructure.composition import register_infrastructure
from plugins.registry import PluginRegistry

_VERSION = "0.1.0"


def build_parser() -> argparse.ArgumentParser:
    """Construct the top-level CLI argument parser.

    Returns:
        A configured `ArgumentParser` with every command group attached.
    """
    parser = argparse.ArgumentParser(prog="vaos", description="VAOS command-line interface")
    parser.add_argument("--version", action="version", version=f"vaos {_VERSION}")
    subparsers = parser.add_subparsers(dest="command")
    add_plugins_parser(subparsers)
    return parser


def main(argv: Sequence[str] | None = None, env: Mapping[str, str] | None = None) -> int:
    """Run the VAOS command-line interface.

    As the CLI layer's composition root, this function runs the core
    bootstrap sequence, registers infrastructure and plugin services, then
    dispatches to the requested command handler.

    Args:
        argv: Command-line arguments to parse. Defaults to `sys.argv[1:]`.
        env: Optional environment mapping used to load settings from.

    Returns:
        Process exit code.
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    settings, container = bootstrap(env)
    register_infrastructure(container, settings)
    container.register_singleton(PluginRegistry, PluginRegistry())
    registry = container.resolve(PluginRegistry)

    if args.command == "plugins":
        return handle_plugins_command(args, registry)

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
