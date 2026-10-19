"""Safe file identities for the locally generated Quake asset tree."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
import re


OWNED_DIRECTORIES = frozenset({"Warp", "Fly3x"})


def valid_asset_name(name: object) -> bool:
    """Accept canonical relative names within the owned runtime asset view."""
    if not isinstance(name, str) or not name or "\\" in name:
        return False
    path = PurePosixPath(name)
    return (
        path.as_posix() == name
        and not path.is_absolute()
        and all(re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*", part)
                and part not in {".", ".."} for part in path.parts)
        and (len(path.parts) == 1 or path.parts[0] == "Warp")
    )


def _require_local(path: Path, root: Path) -> None:
    reparse = getattr(path.lstat(), "st_file_attributes", 0) & 0x400
    if path.is_symlink() or reparse or not path.resolve().is_relative_to(root):
        raise ValueError(f"generated Data contains an unsafe link: {path}")


def generated_asset_files(data: Path, *, exclude_names=()) -> list[Path]:
    """Validate owned directories and return case-sensitive relative file order."""
    if not data.is_dir():
        raise ValueError("generated Data directory is missing")
    _require_local(data, data.resolve())
    root = data.resolve()
    files = []
    for path in data.rglob("*"):
        _require_local(path, root)
        relative = path.relative_to(data)
        if len(relative.parts) > 1 and relative.parts[0] not in OWNED_DIRECTORIES:
            raise ValueError(f"generated Data contains an unexpected directory: {path}")
        if path.is_dir():
            if len(relative.parts) == 1 and path.name not in OWNED_DIRECTORIES:
                raise ValueError(f"generated Data contains an unexpected directory: {path}")
            continue
        if not path.is_file():
            raise ValueError(f"generated Data contains an unsupported entry: {path}")
        if len(relative.parts) > 1 and relative.parts[0] == "Fly3x":
            continue
        name = relative.as_posix()
        if not valid_asset_name(name):
            raise ValueError(f"generated Data contains an invalid asset name: {name}")
        if name not in exclude_names:
            files.append(path)
    return sorted(files, key=lambda path: path.relative_to(data).as_posix())
