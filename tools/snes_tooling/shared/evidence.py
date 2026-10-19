"""Versioned, fail-closed evidence identities and publication.

The provenance reader accepts only :data:`PROVENANCE_SCHEMA`. Historical or
future schemas must gain an explicit adapter before they can be compared; an
unknown schema is never interpreted as the current contract.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import time
from typing import Any
import uuid

from snes_tooling.shared.generated_outputs import atomic_replace


PROVENANCE_SCHEMA = "snes-evidence-provenance-v1"
PROVENANCE_REQUIRED_FIELDS = (
    "schema",
    "source",
    "producer",
    "inputs",
    "configuration",
    "featureState",
    "schedule",
    "measurement",
    "nestedEvidence",
)
PROVENANCE_OPTIONAL_FIELDS = ("rom", "symbols", "emulator")
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
COMMIT_PATTERN = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
DEFAULT_JSON_LIMIT_BYTES = 16 * 1024 * 1024
DEFAULT_HASH_CHUNK_BYTES = 1024 * 1024
_MISSING = "<missing>"


class EvidenceError(ValueError):
    """Evidence is malformed, unstable, or unsafe to publish."""


class UnsupportedProvenanceError(EvidenceError):
    """A provenance schema has no explicit deterministic adapter."""


class EvidenceCompatibilityError(EvidenceError):
    """Two valid provenance records describe incompatible evidence."""

    def __init__(self, issues: Sequence[CompatibilityIssue]) -> None:
        self.issues = tuple(issues)
        details = "\n".join(
            f"- {issue.field}: expected {_display(issue.expected)}; "
            f"got {_display(issue.actual)}"
            for issue in self.issues
        )
        super().__init__(f"incompatible evidence provenance:\n{details}")


@dataclass(frozen=True, slots=True)
class ArtifactIdentity:
    """A content identity with a normalized path relative to its repository."""

    path: str
    bytes: int
    sha256: str

    @classmethod
    def from_path(cls, path: Path, repository: Path) -> ArtifactIdentity:
        resolved = _regular_file(path)
        root = Path(repository).resolve(strict=True)
        if not root.is_dir():
            raise EvidenceError(f"repository is not a directory: {root}")
        try:
            relative = resolved.relative_to(root)
        except ValueError as error:
            raise EvidenceError(
                f"artifact is outside repository {root}: {resolved}"
            ) from error
        size, digest = _stable_file_digest(resolved)
        return cls(relative.as_posix(), size, digest)

    def as_dict(self) -> dict[str, object]:
        return {"path": self.path, "bytes": self.bytes, "sha256": self.sha256}


@dataclass(frozen=True, slots=True)
class CompatibilityIssue:
    """One incompatible provenance field."""

    field: str
    expected: object
    actual: object


@dataclass(frozen=True, slots=True)
class ElapsedTimer:
    """Monotonic elapsed wall-clock summary shared by host-side producers."""

    started: float

    @classmethod
    def start(cls) -> ElapsedTimer:
        return cls(time.perf_counter())

    def seconds(self, digits: int = 3) -> float:
        if digits < 0:
            raise EvidenceError("elapsed precision must be nonnegative")
        return round(max(0.0, time.perf_counter() - self.started), digits)

    def summary(self, label: str, status: str, **fields: object) -> str:
        suffix = " ".join(f"{name}={fields[name]}" for name in sorted(fields))
        result = f"{label}: {status} elapsed={self.seconds():.3f}s"
        return f"{result} {suffix}" if suffix else result


def sha256_bytes(payload: bytes) -> str:
    """Return the lowercase SHA-256 of one in-memory payload."""
    if not isinstance(payload, bytes):
        raise TypeError("SHA-256 payload must be bytes")
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path, *, chunk_bytes: int = DEFAULT_HASH_CHUNK_BYTES) -> str:
    """Stream one regular file into SHA-256 without loading it into memory."""
    if isinstance(chunk_bytes, bool) or not isinstance(chunk_bytes, int):
        raise TypeError("hash chunk size must be an integer")
    if chunk_bytes <= 0:
        raise EvidenceError("hash chunk size must be positive")
    resolved = _regular_file(path)
    digest = hashlib.sha256()
    with resolved.open("rb") as stream:
        while block := stream.read(chunk_bytes):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha256(value: object) -> str:
    """Hash the compact, key-sorted JSON representation of a value."""
    try:
        payload = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeEncodeError) as error:
        raise EvidenceError(f"value is not deterministic JSON: {error}") from error
    return sha256_bytes(payload)


def artifact_identity(path: Path, repository: Path) -> dict[str, object]:
    """Return a normalized repository-relative identity for one artifact."""
    return ArtifactIdentity.from_path(path, repository).as_dict()


def validate_artifact_identity(
    value: object, *, context: str = "artifact"
) -> dict[str, object]:
    """Validate and normalize one serialized artifact identity."""
    return _artifact(value, context)


def validate_artifact_identities(
    value: object, *, context: str = "artifacts"
) -> dict[str, object]:
    """Validate and normalize a named map of serialized artifact identities."""
    return _identity_map(value, context)


def absolute_file_record(path: Path, *, size_field: str) -> dict[str, object]:
    """Shape a stable identity for an unchanged legacy absolute-path schema."""
    if size_field not in {"bytes", "byteCount"}:
        raise EvidenceError(f"unsupported legacy size field: {size_field}")
    resolved = _regular_file(path)
    size, digest = _stable_file_digest(resolved)
    return {"path": str(resolved), size_field: size, "sha256": digest}


def load_json_object(
    path: Path,
    *,
    context: str = "JSON document",
    max_bytes: int = DEFAULT_JSON_LIMIT_BYTES,
) -> dict[str, Any]:
    """Load one bounded UTF-8 JSON object, rejecting arrays and scalars."""
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int):
        raise TypeError("JSON byte limit must be an integer")
    if max_bytes <= 0:
        raise EvidenceError("JSON byte limit must be positive")
    resolved = _regular_file(path)
    size = resolved.stat().st_size
    if size > max_bytes:
        raise EvidenceError(f"{context} exceeds {max_bytes} bytes: {resolved}")
    try:
        payload = resolved.read_bytes()
        value = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
    except (OSError, UnicodeDecodeError, ValueError) as error:
        raise EvidenceError(f"cannot read {context}: {resolved}: {error}") from error
    if not isinstance(value, dict):
        raise EvidenceError(f"{context} must be a JSON object: {resolved}")
    return value


def deterministic_json_bytes(document: Mapping[str, Any]) -> bytes:
    """Serialize a JSON object with the workspace's stable report formatting."""
    if not isinstance(document, Mapping):
        raise EvidenceError("published JSON must be an object")
    try:
        return (
            json.dumps(
                dict(document),
                indent=2,
                sort_keys=True,
                ensure_ascii=True,
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise EvidenceError(
            f"published value is not deterministic JSON: {error}"
        ) from error


def publish_json_object(
    path: Path,
    document: Mapping[str, Any],
    *,
    max_bytes: int = DEFAULT_JSON_LIMIT_BYTES,
    replace: bool = False,
    expected_schema: str | None = None,
    expected_existing_sha256: str | None = None,
) -> None:
    """Atomically publish deterministic JSON under an exclusive destination lock.

    Existing differing bytes are rejected by default. Replacement must be
    constrained by the existing schema or by its exact prior digest, preventing
    a producer from silently taking ownership of unrelated historical evidence.
    """
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int):
        raise TypeError("JSON byte limit must be an integer")
    if max_bytes <= 0:
        raise EvidenceError("JSON byte limit must be positive")
    payload = deterministic_json_bytes(document)
    if len(payload) > max_bytes:
        raise EvidenceError(f"published JSON exceeds {max_bytes} bytes: {path}")
    if expected_existing_sha256 is not None:
        _require_sha256(expected_existing_sha256, "expected existing SHA-256")
    if expected_schema is not None:
        if not expected_schema:
            raise EvidenceError("expected schema must be nonempty")
        if document.get("schema") != expected_schema:
            raise EvidenceError(
                f"new document schema is not {expected_schema!r}: {path}"
            )
    if replace and expected_schema is None and expected_existing_sha256 is None:
        raise EvidenceError(
            "replacement requires an expected schema or existing SHA-256"
        )

    requested = Path(path)
    if requested.is_symlink():
        raise EvidenceError(f"publication destination is a symlink: {requested}")
    target = requested.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_symlink() or (target.exists() and not target.is_file()):
        raise EvidenceError(f"publication destination is not a regular file: {target}")
    lock = target.with_name(f".{target.name}.evidence.lock")
    token = uuid.uuid4().hex
    descriptor: int | None = None
    owns_lock = False
    temporary = target.with_name(f".{target.name}.evidence-{token}.tmp")
    try:
        try:
            descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as error:
            raise EvidenceError(
                f"evidence publication is already active: {target}"
            ) from error
        owns_lock = True
        os.write(descriptor, token.encode("ascii"))
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None

        if target.exists():
            existing = target.read_bytes()
            if existing == payload:
                return
            if not replace:
                raise EvidenceError(
                    f"refusing to replace existing evidence without ownership: {target}"
                )
            if expected_existing_sha256 is not None and (
                sha256_bytes(existing) != expected_existing_sha256
            ):
                raise EvidenceError(f"existing evidence SHA-256 changed: {target}")
            if expected_schema is not None:
                current = load_json_object(
                    target,
                    context="existing evidence",
                    max_bytes=max(max_bytes, len(existing)),
                )
                if current.get("schema") != expected_schema:
                    raise EvidenceError(
                        "refusing to replace unrelated evidence schema "
                        f"{current.get('schema')!r} at {target}"
                    )

        with temporary.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        atomic_replace(temporary, target)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)
        if owns_lock:
            lock.unlink(missing_ok=True)


def git_source_identity(
    repository: Path, *, tracked_only: bool = False
) -> dict[str, object]:
    """Return the current commit and worktree dirty state for a repository."""
    root = Path(repository).resolve(strict=True)
    commit = _run_git(root, "rev-parse", "HEAD").strip()
    if COMMIT_PATTERN.fullmatch(commit) is None:
        raise EvidenceError(f"cannot identify source commit at {root}")
    untracked = "no" if tracked_only else "all"
    status = _run_git(root, "status", "--porcelain", f"--untracked-files={untracked}")
    return {"commit": commit, "dirty": bool(status.strip())}


def provenance_record(
    *,
    source: Mapping[str, object],
    producer: Mapping[str, object],
    inputs: Mapping[str, object],
    configuration: Mapping[str, object],
    feature_state: Mapping[str, object],
    schedule: Mapping[str, object],
    measurement: Mapping[str, object],
    nested_evidence: Mapping[str, object],
    rom: Mapping[str, object] | None = None,
    symbols: Mapping[str, object] | None = None,
    emulator: Mapping[str, object] | None = None,
) -> dict[str, Any]:
    """Build and validate one current provenance record."""
    document: dict[str, object] = {
        "schema": PROVENANCE_SCHEMA,
        "source": source,
        "producer": producer,
        "inputs": inputs,
        "configuration": configuration,
        "featureState": feature_state,
        "schedule": schedule,
        "measurement": measurement,
        "nestedEvidence": nested_evidence,
    }
    for name, value in (("rom", rom), ("symbols", symbols), ("emulator", emulator)):
        if value is not None:
            document[name] = value
    return validate_provenance(document)


def load_provenance(
    path: Path, *, max_bytes: int = DEFAULT_JSON_LIMIT_BYTES
) -> dict[str, Any]:
    """Load and validate current provenance, rejecting unsupported schemas."""
    return validate_provenance(
        load_json_object(path, context="evidence provenance", max_bytes=max_bytes)
    )


def validate_provenance(document: Mapping[str, object]) -> dict[str, Any]:
    """Validate and normalize the complete v1 provenance contract."""
    value = _object(document, "provenance")
    schema = value.get("schema")
    if schema != PROVENANCE_SCHEMA:
        raise UnsupportedProvenanceError(
            f"unsupported evidence provenance schema {schema!r}; "
            "an explicit deterministic adapter is required"
        )
    _exact_fields(
        value,
        required=set(PROVENANCE_REQUIRED_FIELDS),
        optional=set(PROVENANCE_OPTIONAL_FIELDS),
        context="provenance",
    )

    normalized: dict[str, Any] = {"schema": PROVENANCE_SCHEMA}
    normalized["source"] = _source(value["source"])
    normalized["producer"] = _producer(value["producer"])
    normalized["inputs"] = _identity_map(value["inputs"], "inputs")
    normalized["configuration"] = _hash_map(value["configuration"], "configuration")
    normalized["featureState"] = _json_object(value["featureState"], "featureState")
    normalized["schedule"] = _schedule(value["schedule"])
    normalized["measurement"] = _measurement(value["measurement"])
    normalized["nestedEvidence"] = _identity_map(
        value["nestedEvidence"], "nestedEvidence"
    )
    for name in ("rom", "symbols"):
        if name in value:
            normalized[name] = _artifact(value[name], name)
    if "emulator" in value:
        normalized["emulator"] = _emulator(value["emulator"])
    return normalized


def provenance_incompatibilities(
    reference: Mapping[str, object], candidate: Mapping[str, object]
) -> tuple[CompatibilityIssue, ...]:
    """Return every leaf field that differs between valid provenance records."""
    expected = validate_provenance(reference)
    actual = validate_provenance(candidate)
    issues: list[CompatibilityIssue] = []
    _compare_values(expected, actual, "", issues)
    return tuple(issues)


def check_provenance_compatibility(
    reference: Mapping[str, object], candidate: Mapping[str, object]
) -> None:
    """Reject incompatible provenance while reporting every differing field."""
    issues = provenance_incompatibilities(reference, candidate)
    if issues:
        raise EvidenceCompatibilityError(issues)


def _regular_file(path: Path) -> Path:
    try:
        resolved = Path(path).resolve(strict=True)
    except OSError as error:
        raise EvidenceError(f"cannot resolve file {path}: {error}") from error
    if not resolved.is_file():
        raise EvidenceError(f"not a regular file: {resolved}")
    return resolved


def _stable_file_digest(path: Path) -> tuple[int, str]:
    before = path.stat()
    digest = sha256_file(path)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise EvidenceError(f"artifact changed while hashing: {path}")
    return after.st_size, digest


def _run_git(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ("git", "-C", str(root), *arguments),
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        detail = result.stderr.strip() or "git command failed"
        raise EvidenceError(f"cannot inspect source repository {root}: {detail}")
    return result.stdout


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object key: {key!r}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> object:
    raise ValueError(f"non-finite JSON number: {value}")


def _object(value: object, context: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise EvidenceError(f"{context} must be an object")
    if not all(isinstance(key, str) for key in value):
        raise EvidenceError(f"{context} keys must be strings")
    return value


def _exact_fields(
    value: Mapping[str, object], *, required: set[str], optional: set[str], context: str
) -> None:
    missing = sorted(required - value.keys())
    extra = sorted(value.keys() - required - optional)
    if missing:
        raise EvidenceError(f"{context} is missing fields: {', '.join(missing)}")
    if extra:
        raise EvidenceError(f"{context} has unsupported fields: {', '.join(extra)}")


def _string(value: object, context: str) -> str:
    if not isinstance(value, str) or not value:
        raise EvidenceError(f"{context} must be a nonempty string")
    return value


def _require_sha256(value: object, context: str) -> str:
    if not isinstance(value, str) or SHA256_PATTERN.fullmatch(value) is None:
        raise EvidenceError(f"{context} must be a lowercase SHA-256")
    return value


def _source(value: object) -> dict[str, object]:
    source = _object(value, "source")
    _exact_fields(
        source,
        required={"commit", "dirty"},
        optional={"diffSha256"},
        context="source",
    )
    commit = _string(source["commit"], "source.commit")
    if COMMIT_PATTERN.fullmatch(commit) is None:
        raise EvidenceError("source.commit must be a 40- or 64-character object ID")
    dirty = source["dirty"]
    if not isinstance(dirty, bool):
        raise EvidenceError("source.dirty must be a boolean")
    result: dict[str, object] = {"commit": commit, "dirty": dirty}
    if "diffSha256" in source:
        result["diffSha256"] = _require_sha256(
            source["diffSha256"], "source.diffSha256"
        )
    return result


def _producer(value: object) -> dict[str, object]:
    producer = _object(value, "producer")
    _exact_fields(
        producer,
        required={"name", "artifact"},
        optional={"version"},
        context="producer",
    )
    result: dict[str, object] = {
        "name": _string(producer["name"], "producer.name"),
        "artifact": _artifact(producer["artifact"], "producer.artifact"),
    }
    if "version" in producer:
        result["version"] = _string(producer["version"], "producer.version")
    return result


def _artifact(value: object, context: str) -> dict[str, object]:
    artifact = _object(value, context)
    _exact_fields(
        artifact,
        required={"path", "bytes", "sha256"},
        optional=set(),
        context=context,
    )
    raw_path = _string(artifact["path"], f"{context}.path")
    path = PurePosixPath(raw_path)
    if (
        not path.parts
        or "\\" in raw_path
        or path.is_absolute()
        or path.as_posix() != raw_path
        or any(part in {".", ".."} for part in path.parts)
        or (path.parts and ":" in path.parts[0])
    ):
        raise EvidenceError(
            f"{context}.path must be normalized and repository-relative"
        )
    byte_count = artifact["bytes"]
    if (
        isinstance(byte_count, bool)
        or not isinstance(byte_count, int)
        or byte_count < 0
    ):
        raise EvidenceError(f"{context}.bytes must be a nonnegative integer")
    return {
        "path": raw_path,
        "bytes": byte_count,
        "sha256": _require_sha256(artifact["sha256"], f"{context}.sha256"),
    }


def _identity_map(value: object, context: str) -> dict[str, object]:
    identities = _object(value, context)
    result: dict[str, object] = {}
    for name in sorted(identities):
        _string(name, f"{context} name")
        result[name] = _artifact(identities[name], f"{context}.{name}")
    return result


def _hash_map(value: object, context: str) -> dict[str, str]:
    hashes = _object(value, context)
    result: dict[str, str] = {}
    for name in sorted(hashes):
        _string(name, f"{context} name")
        result[name] = _require_sha256(hashes[name], f"{context}.{name}")
    return result


def _json_object(value: object, context: str) -> dict[str, Any]:
    document = _object(value, context)
    try:
        payload = json.dumps(
            document, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
        normalized = json.loads(payload)
    except (TypeError, ValueError) as error:
        raise EvidenceError(
            f"{context} must contain only finite JSON: {error}"
        ) from error
    if not isinstance(normalized, dict):
        raise EvidenceError(f"{context} must be an object")
    return normalized


def _schedule(value: object) -> dict[str, object]:
    schedule = _object(value, "schedule")
    _exact_fields(
        schedule,
        required={"name", "parameters"},
        optional=set(),
        context="schedule",
    )
    return {
        "name": _string(schedule["name"], "schedule.name"),
        "parameters": _json_object(schedule["parameters"], "schedule.parameters"),
    }


def _measurement(value: object) -> dict[str, object]:
    measurement = _object(value, "measurement")
    _exact_fields(
        measurement,
        required={"model"},
        optional={"claim", "parameters"},
        context="measurement",
    )
    result: dict[str, object] = {
        "model": _string(measurement["model"], "measurement.model")
    }
    if "claim" in measurement:
        result["claim"] = _string(measurement["claim"], "measurement.claim")
    if "parameters" in measurement:
        result["parameters"] = _json_object(
            measurement["parameters"], "measurement.parameters"
        )
    return result


def _emulator(value: object) -> dict[str, object]:
    emulator = _object(value, "emulator")
    _exact_fields(
        emulator,
        required={"build", "capabilities"},
        optional=set(),
        context="emulator",
    )
    capabilities = emulator["capabilities"]
    if isinstance(capabilities, (str, bytes)) or not isinstance(capabilities, Sequence):
        raise EvidenceError("emulator.capabilities must be an array")
    names = [_string(name, "emulator capability") for name in capabilities]
    if len(names) != len(set(names)):
        raise EvidenceError("emulator.capabilities must not contain duplicates")
    return {
        "build": _artifact(emulator["build"], "emulator.build"),
        "capabilities": sorted(names),
    }


def _compare_values(
    expected: object,
    actual: object,
    path: str,
    issues: list[CompatibilityIssue],
) -> None:
    if isinstance(expected, Mapping) and isinstance(actual, Mapping):
        for key in sorted(expected.keys() | actual.keys()):
            field = f"{path}.{key}" if path else key
            if key not in expected:
                issues.append(CompatibilityIssue(field, _MISSING, actual[key]))
            elif key not in actual:
                issues.append(CompatibilityIssue(field, expected[key], _MISSING))
            else:
                _compare_values(expected[key], actual[key], field, issues)
        return
    if (
        isinstance(expected, Sequence)
        and not isinstance(expected, (str, bytes))
        and isinstance(actual, Sequence)
        and not isinstance(actual, (str, bytes))
    ):
        if len(expected) != len(actual):
            issues.append(CompatibilityIssue(path, expected, actual))
            return
        for index, (expected_item, actual_item) in enumerate(
            zip(expected, actual, strict=True)
        ):
            _compare_values(expected_item, actual_item, f"{path}[{index}]", issues)
        return
    if expected != actual or type(expected) is not type(actual):
        issues.append(CompatibilityIssue(path, expected, actual))


def _display(value: object) -> str:
    if value == _MISSING:
        return _MISSING
    return json.dumps(value, sort_keys=True, ensure_ascii=True)
