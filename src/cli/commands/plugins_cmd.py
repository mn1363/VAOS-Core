"""The `plugins` CLI command group."""

import argparse

from plugins.registry import PluginRegistry


def add_plugins_parser(subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    """Register the `plugins` command group on the CLI parser.

    Args:
        subparsers: The parent parser's subparsers action to attach to.
    """
    plugins_parser = subparsers.add_parser("plugins", help="Inspect registered plugins")
    plugins_subparsers = plugins_parser.add_subparsers(dest="plugins_command", required=True)
    plugins_subparsers.add_parser("list", help="List every registered plugin")


def handle_plugins_command(args: argparse.Namespace, registry: PluginRegistry) -> int:
    """Execute the `plugins` command group.

    Args:
        args: Parsed CLI arguments.
        registry: The plugin registry to inspect.

    Returns:
        Process exit code: 0 on success.
    """
    if args.plugins_command == "list":
        for plugin in registry.list_plugins():
            print(f"{plugin.name} v{plugin.version}")
    return 0
