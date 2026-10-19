"""Run a discovered SNES tooling command, e.g. quake.generate-quake-bsp."""

from __future__ import annotations

import argparse
import importlib
import sys
import time
from collections.abc import Sequence

from snes_tooling.command_catalog import CommandError, discover_commands, resolve_command
from snes_tooling.workspace import Workspace, WorkspaceError


def main(argv: Sequence[str] | None = None) -> int:
    started = time.monotonic()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="list every discovered command")
    parser.add_argument("command", nargs="?")
    parser.add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    try:
        workspace = Workspace.discover()
        if args.list:
            print("\n".join(command.name for command in discover_commands(workspace)))
            print(f"elapsed={time.monotonic() - started:.3f}s", file=sys.stderr)
            return 0
        if args.command is None:
            parser.error("a command is required (use --list)")
        try:
            command = resolve_command(workspace, args.command)
        except CommandError as error:
            parser.error(str(error))
        original = sys.argv
        try:
            sys.argv = [args.command, *args.arguments]
            module = importlib.import_module(command.module)
            result = getattr(module, command.entry)()
            if command.exits:
                raise SystemExit(result)
        finally:
            sys.argv = original
        return 0
    except (CommandError, WorkspaceError) as error:
        print(f"ERROR SNES command: {error} elapsed={time.monotonic() - started:.3f}s", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
