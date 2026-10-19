"""Discover executable package modules without importing their implementation."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

from snes_tooling.workspace import Workspace


class CommandError(ValueError):
    """A command cannot be discovered or invoked unambiguously."""


@dataclass(frozen=True)
class Command:
    name: str
    module: str
    source: Path
    entry: str
    exits: bool


def is_main_guard(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.If)
        and isinstance(node.test, ast.Compare)
        and isinstance(node.test.left, ast.Name)
        and node.test.left.id == "__name__"
        and len(node.test.ops) == 1
        and isinstance(node.test.ops[0], ast.Eq)
        and len(node.test.comparators) == 1
        and isinstance(node.test.comparators[0], ast.Constant)
        and node.test.comparators[0].value == "__main__"
    )


def command_entry(tree: ast.Module) -> tuple[str, bool]:
    guards = [node for node in tree.body if is_main_guard(node)]
    if len(guards) != 1 or len(guards[0].body) != 1:
        raise CommandError("a command requires one logic-free main guard")
    statement = guards[0].body[0]
    exits = isinstance(statement, ast.Raise)
    call = statement.exc if exits else statement.value if isinstance(statement, ast.Expr) else None
    if exits:
        if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
                and call.func.id == "SystemExit" and len(call.args) == 1):
            raise CommandError("a command must exit through its entry function")
        call = call.args[0]
    if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
            and not call.args and not call.keywords):
        raise CommandError("a command requires a no-argument entry function")
    return call.func.id, exits


def discover_commands(workspace: Workspace) -> tuple[Command, ...]:
    """Every executable owned module gets exactly one stable command name."""
    root = workspace.package_path()
    commands = []
    for source in sorted(root.rglob("*.py")):
        relative = source.relative_to(root).with_suffix("")
        if relative.as_posix() in {"__main__", "cli"}:
            continue
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        if any(is_main_guard(node) for node in tree.body):
            suffix = ".".join(relative.parts)
            commands.append(Command(suffix.replace("_", "-"), f"snes_tooling.{suffix}", source, *command_entry(tree)))
    names = [command.name for command in commands]
    if len(names) != len(set(names)):
        raise CommandError("duplicate discovered command names")
    return tuple(commands)


def resolve_command(workspace: Workspace, name: str) -> Command:
    """Resolve one canonical name without scanning unrelated command sources."""
    parts = name.replace("-", "_").split(".")
    if not parts or any(not part.isidentifier() or part.startswith("_") for part in parts):
        raise CommandError(f"unknown command {name!r} (use --list)")
    source = workspace.package_path(*parts).with_suffix(".py")
    if source.is_file() and name != "cli":
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        if any(is_main_guard(node) for node in tree.body):
            return Command(name, "snes_tooling." + ".".join(parts), source, *command_entry(tree))
    raise CommandError(f"unknown command {name!r} (use --list)")


def discover_wrappers(workspace: Workspace) -> dict[str, str]:
    """Require all retained command scripts to contain only a package delegate."""
    local_bootstrap = ast.parse(
        'from pathlib import Path\nimport sys\n'
        'sys.path.insert(0, str(Path(__file__).resolve().parents[2]))\n'
    ).body
    wrappers = {}
    for root in (workspace.shared_tools, workspace.quake_tools):
        for source in sorted(root.glob("*.py")):
            tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
            body = list(tree.body)
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                body.pop(0)
            # Detached dashboard delegates pin imports to their own checkout.
            # Accept only this exact bootstrap, never arbitrary wrapper logic.
            if [ast.dump(node) for node in body[:3]] == [ast.dump(node) for node in local_bootstrap]:
                body = body[3:]
            if (len(body) != 2 or not isinstance(body[0], ast.ImportFrom)
                    or not body[0].module or not body[0].module.startswith("snes_tooling.")
                    or len(body[0].names) != 1 or not is_main_guard(body[1])):
                raise CommandError(f"command wrapper retains implementation: {source}")
            entry = body[0].names[0].asname or body[0].names[0].name
            expected = ast.parse(f'if __name__ == "__main__":\n    raise SystemExit({entry}())').body[0]
            if ast.dump(body[1]) != ast.dump(expected):
                raise CommandError(f"command wrapper has non-delegating behavior: {source}")
            wrappers[source.relative_to(workspace.root).as_posix()] = body[0].module
    return wrappers
