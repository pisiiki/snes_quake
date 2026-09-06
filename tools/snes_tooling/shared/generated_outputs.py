"""Safely check and publish deterministic generated-output sets."""

from __future__ import annotations

import json
import os
import shutil
import stat
import time
import uuid
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any


TRANSACTION_DIRECTORY = ".generated-output-transaction"
JOURNAL_NAME = "journal.json"
COMMIT_MARKER = "COMMITTED"
JOURNAL_VERSION = 1
REPLACE_RETRY_ATTEMPTS = 4
REPLACE_RETRY_DELAY_SECONDS = 0.1


class GeneratedOutputError(RuntimeError):
    """Report an unsafe declaration or an output set that needs attention."""


def atomic_replace(source: Path, destination: Path) -> None:
    """Atomically replace a path, retrying transient Windows sharing failures."""
    for attempt in range(REPLACE_RETRY_ATTEMPTS):
        try:
            os.replace(source, destination)
            return
        except PermissionError:
            if attempt + 1 == REPLACE_RETRY_ATTEMPTS:
                raise
            time.sleep(REPLACE_RETRY_DELAY_SECONDS)


@dataclass(frozen=True, slots=True)
class OwnedFileFamily:
    """Own files matching ``directory / (prefix + '*' + suffix)``."""

    prefix: str
    suffix: str
    directory: Path = Path(".")
    numbered: bool = False

    def __post_init__(self) -> None:
        directory = _normalize_relative(self.directory, allow_root=True)
        if not self.prefix or not self.suffix:
            raise GeneratedOutputError(
                "owned-family prefix and suffix must be non-empty"
            )
        for label, value in (("prefix", self.prefix), ("suffix", self.suffix)):
            if value in {".", ".."} or "/" in value or "\\" in value:
                raise GeneratedOutputError(
                    f"owned-family {label} must be a filename fragment: {value!r}"
                )
        object.__setattr__(self, "directory", directory)

    def matches(self, relative: Path) -> bool:
        name_matches = (
            relative.parent == self.directory
            and relative.name.startswith(self.prefix)
            and relative.name.endswith(self.suffix)
        )
        if not name_matches or not self.numbered:
            return name_matches
        middle_end = len(relative.name) - len(self.suffix)
        middle = relative.name[len(self.prefix) : middle_end]
        return bool(middle) and middle.isascii() and middle.isdigit()


@dataclass(frozen=True, slots=True)
class _ExpectedState:
    relative: Path
    data: bytes
    existed: bool
    mtime_ns: int | None
    mode: int | None


StepHook = Callable[[str, Path], None]


def sync_generated_outputs(
    outputs: Mapping[Path, bytes] | Iterable[tuple[Path, bytes]],
    output_root: Path,
    *,
    check: bool,
    owned_families: Iterable[OwnedFileFamily] = (),
    _step_hook: StepHook | None = None,
) -> None:
    """Check or atomically publish one complete generated-output set.

    ``_step_hook`` is intentionally private. Tests use it to model failures and
    process interruption at deterministic transaction boundaries.
    """

    normalized = _normalize_outputs(outputs)
    families = _normalize_families(owned_families)
    root = Path(output_root).resolve()
    transaction = root / TRANSACTION_DIRECTORY

    if root.exists() and not root.is_dir():
        raise GeneratedOutputError(f"output root is not a directory: {root}")

    if transaction.exists() or transaction.is_symlink():
        if check:
            raise GeneratedOutputError(
                f"incomplete generated-output transaction at {transaction}; "
                "rerun without --check to recover it"
            )
        _recover_transaction(root)

    states, unexpected = _inspect_outputs(normalized, root, families)
    if check:
        _raise_if_stale(states, unexpected, root)
        return

    changed = [
        state
        for state in states
        if not state.existed or _read(root / state.relative) != state.data
    ]
    if not changed and not unexpected:
        return

    root.mkdir(parents=True, exist_ok=True)
    _publish_transaction(
        root,
        changed,
        unexpected,
        step_hook=_step_hook,
    )


def _normalize_relative(value: Path, *, allow_root: bool = False) -> Path:
    path = Path(value)
    if path.is_absolute() or path.drive or path.root:
        raise GeneratedOutputError(f"generated-output path must be relative: {path}")
    if any(part == ".." for part in path.parts):
        raise GeneratedOutputError(f"generated-output path contains traversal: {path}")
    parts = tuple(part for part in path.parts if part not in {"", "."})
    if not parts:
        if allow_root:
            return Path(".")
        raise GeneratedOutputError("generated-output path must name a file")
    normalized = Path(*parts)
    if normalized.parts[0].casefold() == TRANSACTION_DIRECTORY.casefold():
        raise GeneratedOutputError(
            f"generated-output path uses reserved transaction storage: {path}"
        )
    return normalized


def _path_key(path: Path) -> str:
    return path.as_posix().casefold()


def _normalize_outputs(
    outputs: Mapping[Path, bytes] | Iterable[tuple[Path, bytes]],
) -> dict[Path, bytes]:
    items = outputs.items() if isinstance(outputs, Mapping) else outputs
    normalized: dict[Path, bytes] = {}
    keys: set[str] = set()
    for raw_path, data in items:
        relative = _normalize_relative(raw_path)
        key = _path_key(relative)
        if key in keys:
            raise GeneratedOutputError(f"duplicate generated-output path: {relative}")
        if not isinstance(data, bytes):
            raise GeneratedOutputError(
                f"generated-output payload must be bytes: {relative}"
            )
        keys.add(key)
        normalized[relative] = data

    paths = sorted(normalized, key=lambda path: (len(path.parts), _path_key(path)))
    for index, parent in enumerate(paths):
        parent_key = tuple(part.casefold() for part in parent.parts)
        for child in paths[index + 1 :]:
            child_key = tuple(part.casefold() for part in child.parts)
            if child_key[: len(parent_key)] == parent_key:
                raise GeneratedOutputError(
                    f"generated-output file/directory collision: {parent} and {child}"
                )
    return normalized


def _normalize_families(
    families: Iterable[OwnedFileFamily],
) -> tuple[OwnedFileFamily, ...]:
    normalized = tuple(families)
    if not all(isinstance(family, OwnedFileFamily) for family in normalized):
        raise GeneratedOutputError("owned families must use OwnedFileFamily")
    keys = {
        (
            _path_key(family.directory),
            family.prefix.casefold(),
            family.suffix.casefold(),
            family.numbered,
        )
        for family in normalized
    }
    if len(keys) != len(normalized):
        raise GeneratedOutputError("duplicate owned-file family")
    return normalized


def _validate_parent_chain(root: Path, relative: Path) -> None:
    current = root
    for part in relative.parts[:-1]:
        current /= part
        if current.is_symlink():
            raise GeneratedOutputError(
                f"output directory cannot be a symlink: {current}"
            )
        if current.exists() and not current.is_dir():
            raise GeneratedOutputError(
                f"output path has a file as a directory: {current}"
            )


def _inspect_outputs(
    outputs: Mapping[Path, bytes],
    root: Path,
    families: tuple[OwnedFileFamily, ...],
) -> tuple[list[_ExpectedState], list[Path]]:
    states: list[_ExpectedState] = []
    expected_keys = {_path_key(relative) for relative in outputs}
    for relative, data in sorted(outputs.items(), key=lambda item: _path_key(item[0])):
        _validate_parent_chain(root, relative)
        destination = root / relative
        if destination.is_symlink():
            raise GeneratedOutputError(
                f"output file cannot be a symlink: {destination}"
            )
        if destination.exists() and not destination.is_file():
            raise GeneratedOutputError(f"output path is not a file: {destination}")
        if destination.is_file():
            metadata = destination.stat()
            states.append(
                _ExpectedState(
                    relative,
                    data,
                    True,
                    metadata.st_mtime_ns,
                    stat.S_IMODE(metadata.st_mode),
                )
            )
        else:
            states.append(_ExpectedState(relative, data, False, None, None))

    unexpected: dict[str, Path] = {}
    for family in families:
        _validate_parent_chain(root, family.directory / "placeholder")
        directory = root if family.directory == Path(".") else root / family.directory
        if directory.is_symlink():
            raise GeneratedOutputError(
                f"owned-family directory cannot be a symlink: {directory}"
            )
        if not directory.exists():
            continue
        if not directory.is_dir():
            raise GeneratedOutputError(
                f"owned-family directory is not a directory: {directory}"
            )
        for candidate in directory.iterdir():
            relative = candidate.relative_to(root)
            if not family.matches(relative) or _path_key(relative) in expected_keys:
                continue
            if candidate.is_symlink() or not candidate.is_file():
                raise GeneratedOutputError(
                    f"owned-family member is not a regular file: {candidate}"
                )
            unexpected[_path_key(relative)] = relative
    return states, sorted(unexpected.values(), key=_path_key)


def _read(path: Path) -> bytes:
    return path.read_bytes()


def _raise_if_stale(
    states: list[_ExpectedState], unexpected: list[Path], root: Path
) -> None:
    missing = [state.relative for state in states if not state.existed]
    mismatched = [
        state.relative
        for state in states
        if state.existed and _read(root / state.relative) != state.data
    ]
    if not missing and not mismatched and not unexpected:
        return

    sections: list[str] = []
    for label, paths in (
        ("missing", missing),
        ("mismatched", mismatched),
        ("unexpected", unexpected),
    ):
        if paths:
            sections.append(
                f"{label}:\n" + "\n".join(f"  {root / path}" for path in paths)
            )
    raise GeneratedOutputError("generated outputs are stale:\n" + "\n".join(sections))


def _created_directories(root: Path, changed: list[_ExpectedState]) -> list[Path]:
    created: set[Path] = set()
    for state in changed:
        current = state.relative.parent
        while current != Path("."):
            destination = root / current
            if destination.exists() or destination.is_symlink():
                break
            created.add(current)
            current = current.parent
    return sorted(created, key=lambda path: (len(path.parts), _path_key(path)))


def _operation_records(
    changed: list[_ExpectedState], unexpected: list[Path], token: str
) -> list[dict[str, Any]]:
    operations: list[dict[str, Any]] = []
    for index, state in enumerate(
        sorted(changed, key=lambda item: _path_key(item.relative))
    ):
        stage_name = f".{state.relative.name}.generated-output-{token}-{index:04d}.tmp"
        operations.append(
            {
                "action": "replace",
                "path": state.relative.as_posix(),
                "stage": (state.relative.parent / stage_name).as_posix(),
                "backup": f"backups/{index:04d}.bin" if state.existed else None,
                "existed": state.existed,
                "mtime_ns": state.mtime_ns,
                "mode": state.mode,
            }
        )
    offset = len(operations)
    for index, relative in enumerate(sorted(unexpected, key=_path_key), start=offset):
        destination = relative
        metadata = None
        operations.append(
            {
                "action": "delete",
                "path": destination.as_posix(),
                "stage": None,
                "backup": f"backups/{index:04d}.bin",
                "existed": True,
                "mtime_ns": metadata,
                "mode": None,
            }
        )
    return operations


def _write_fsynced(path: Path, data: bytes, *, exclusive: bool = False) -> None:
    mode = "xb" if exclusive else "wb"
    with path.open(mode) as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def _write_journal(transaction: Path, journal: dict[str, Any]) -> None:
    temporary = transaction / f".{JOURNAL_NAME}.tmp"
    payload = (json.dumps(journal, indent=2, sort_keys=True) + "\n").encode("utf-8")
    _write_fsynced(temporary, payload)
    atomic_replace(temporary, transaction / JOURNAL_NAME)


def _publish_transaction(
    root: Path,
    changed: list[_ExpectedState],
    unexpected: list[Path],
    *,
    step_hook: StepHook | None,
) -> None:
    transaction = root / TRANSACTION_DIRECTORY
    token = uuid.uuid4().hex
    created = _created_directories(root, changed)
    operations = _operation_records(changed, unexpected, token)
    state_by_path = {_path_key(state.relative): state for state in changed}

    transaction.mkdir()
    journal: dict[str, Any] = {
        "version": JOURNAL_VERSION,
        "phase": "preparing",
        "created_directories": [path.as_posix() for path in created],
        "operations": operations,
    }
    try:
        _write_journal(transaction, journal)
        for relative in created:
            (root / relative).mkdir(exist_ok=True)

        for operation in operations:
            if operation["action"] != "replace":
                continue
            relative = _journal_path(operation["path"])
            stage = root / _journal_path(operation["stage"])
            stage.parent.mkdir(parents=True, exist_ok=True)
            _write_fsynced(
                stage,
                state_by_path[_path_key(relative)].data,
                exclusive=True,
            )
            if step_hook:
                step_hook("stage", relative)

        backups = transaction / "backups"
        backups.mkdir()
        for operation in operations:
            if not operation["existed"]:
                continue
            relative = _journal_path(operation["path"])
            source = root / relative
            metadata = source.stat()
            operation["mtime_ns"] = metadata.st_mtime_ns
            operation["mode"] = stat.S_IMODE(metadata.st_mode)
            _write_fsynced(
                transaction / operation["backup"],
                source.read_bytes(),
                exclusive=True,
            )

        journal["phase"] = "publishing"
        _write_journal(transaction, journal)

        for operation in operations:
            relative = _journal_path(operation["path"])
            destination = root / relative
            if operation["action"] == "replace":
                atomic_replace(root / _journal_path(operation["stage"]), destination)
                event = "replace"
            else:
                destination.unlink()
                event = "delete"
            if step_hook:
                step_hook(event, relative)

        _write_fsynced(transaction / COMMIT_MARKER, b"", exclusive=True)
    except Exception:
        try:
            _rollback_transaction(root)
        except Exception as rollback_error:
            raise GeneratedOutputError(
                f"generated-output publication failed and rollback also failed; "
                f"recover {transaction} before continuing"
            ) from rollback_error
        raise
    _cleanup_transaction(transaction)


def _load_journal(transaction: Path) -> dict[str, Any]:
    try:
        journal = json.loads((transaction / JOURNAL_NAME).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise GeneratedOutputError(
            f"cannot read generated-output transaction journal at {transaction}"
        ) from error
    if journal.get("version") != JOURNAL_VERSION:
        raise GeneratedOutputError(
            f"unsupported generated-output journal at {transaction}"
        )
    if journal.get("phase") not in {"preparing", "publishing"}:
        raise GeneratedOutputError(f"invalid generated-output journal at {transaction}")
    if not isinstance(journal.get("operations"), list) or not isinstance(
        journal.get("created_directories"), list
    ):
        raise GeneratedOutputError(f"invalid generated-output journal at {transaction}")
    return journal


def _journal_path(value: str) -> Path:
    if not isinstance(value, str):
        raise GeneratedOutputError("invalid path in generated-output journal")
    return _normalize_relative(Path(value), allow_root=False)


def _recover_transaction(root: Path) -> None:
    transaction = root / TRANSACTION_DIRECTORY
    if transaction.is_symlink() or not transaction.is_dir():
        raise GeneratedOutputError(
            f"generated-output transaction storage is unsafe: {transaction}"
        )
    if (transaction / COMMIT_MARKER).is_file():
        _cleanup_transaction(transaction)
        return
    if not (transaction / JOURNAL_NAME).is_file():
        # The transaction directory is created before its initial journal. No
        # destination is touched until that journal exists.
        _cleanup_transaction(transaction)
        return
    journal = _load_journal(transaction)
    if journal["phase"] == "publishing":
        _rollback_transaction(root, journal)
    else:
        _discard_prepared_transaction(root, journal)


def _restore_backup(
    root: Path, transaction: Path, operation: Mapping[str, Any], index: int
) -> None:
    relative = _journal_path(operation["path"])
    destination = root / relative
    backup = transaction / _journal_path(operation["backup"])
    if not backup.is_file():
        raise GeneratedOutputError(f"transaction backup is missing: {backup}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.parent / (
        f".{destination.name}.generated-output-recovery-{index:04d}.tmp"
    )
    _write_fsynced(temporary, backup.read_bytes())
    atomic_replace(temporary, destination)
    mode = operation.get("mode")
    mtime_ns = operation.get("mtime_ns")
    if isinstance(mode, int):
        os.chmod(destination, mode)
    if isinstance(mtime_ns, int):
        os.utime(destination, ns=(mtime_ns, mtime_ns))


def _rollback_transaction(root: Path, journal: dict[str, Any] | None = None) -> None:
    transaction = root / TRANSACTION_DIRECTORY
    journal = journal or _load_journal(transaction)
    if journal["phase"] == "publishing":
        for index, operation in enumerate(journal["operations"]):
            relative = _journal_path(operation["path"])
            destination = root / relative
            if operation["existed"]:
                _restore_backup(root, transaction, operation, index)
            elif destination.exists() or destination.is_symlink():
                if destination.is_dir() and not destination.is_symlink():
                    raise GeneratedOutputError(
                        f"cannot remove directory created over output file: {destination}"
                    )
                destination.unlink()
    _discard_prepared_transaction(root, journal)


def _discard_prepared_transaction(root: Path, journal: Mapping[str, Any]) -> None:
    transaction = root / TRANSACTION_DIRECTORY
    for operation in journal["operations"]:
        stage_value = operation.get("stage")
        if not stage_value:
            continue
        stage = root / _journal_path(stage_value)
        if stage.exists() or stage.is_symlink():
            if stage.is_dir() and not stage.is_symlink():
                raise GeneratedOutputError(f"transaction stage is a directory: {stage}")
            stage.unlink()
    for value in sorted(
        journal["created_directories"],
        key=lambda path: len(_journal_path(path).parts),
        reverse=True,
    ):
        directory = root / _journal_path(value)
        if directory.is_dir() and not directory.is_symlink():
            try:
                directory.rmdir()
            except OSError:
                pass
    _cleanup_transaction(transaction)


def _cleanup_transaction(transaction: Path) -> None:
    shutil.rmtree(transaction)
