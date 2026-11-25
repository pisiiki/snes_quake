"""Read and verify the original Quake 1.06 shareware archive."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any, Callable, Iterator, Mapping
import zipfile

from snes_tooling.shared.evidence import sha256_file


RESOURCE_MEMBER = "resource.1"


@dataclass(frozen=True)
class FileIdentity:
    size: int
    sha256: str

    def verify(self, path: Path, label: str) -> None:
        actual_size = path.stat().st_size
        actual_sha256 = sha256_file(path)
        if actual_size != self.size or actual_sha256 != self.sha256:
            raise RuntimeError(
                f"{label} is not the canonical Quake shareware file: "
                f"{actual_size} bytes/{actual_sha256}, expected "
                f"{self.size} bytes/{self.sha256}"
            )


ARCHIVE_IDENTITY = FileIdentity(
    9_094_045,
    "ec6c9d34b1ae0252ac0066045b6611a7919c2a0d78a3a66d9387a8f597553239",
)
RESOURCE_IDENTITY = FileIdentity(
    9_086_574,
    "c192c9c71bee41750dd7d14c99378766d61e077977b9d13d1a457b8d9eabe34a",
)
LHA_MEMBERS: Mapping[str, FileIdentity] = {
    "ID1/PAK0.PAK": FileIdentity(
        18_689_235,
        "35a9c55e5e5a284a159ad2a62e0e8def23d829561fe2f54eb402dbc0a9a946af",
    ),
    "SLICNSE.TXT": FileIdentity(
        10_036,
        "070cdf6a6410adef8fb5f83a4e5ccdb9e2301d2e48d460bb3a67a0f5ba9d70a8",
    ),
    "README.TXT": FileIdentity(
        19_087,
        "9ade267c7e22a1c4c4aa8fa3dd58ad3354c173ae2cfc39344093cea534316d61",
    ),
}
TAR_TIMEOUT_SECONDS = 120
TAR_PROBE_TIMEOUT_SECONDS = 10


CommandRunner = Callable[..., subprocess.CompletedProcess[Any]]


@contextmanager
def atomic_path(destination: Path) -> Iterator[Path]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        yield temporary
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def _is_libarchive_bsdtar(executable: str) -> bool:
    try:
        result = subprocess.run(
            [executable, "--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
            text=True,
            timeout=TAR_PROBE_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    banner = str(result.stdout or "").casefold()
    return result.returncode == 0 and ("bsdtar" in banner or "libarchive" in banner)


def find_bsdtar() -> str:
    candidates = ("tar.exe", "bsdtar.exe") if os.name == "nt" else ("bsdtar", "tar")
    for candidate in candidates:
        executable = shutil.which(candidate)
        if executable is not None and _is_libarchive_bsdtar(executable):
            return executable
    raise FileNotFoundError(
        "libarchive bsdtar was not found; install a libarchive bsdtar package "
        "or pass its executable with --tar"
    )


class SharewareResource:
    """A verified DeICE/LHA resource opened without executing its installer."""

    def __init__(
        self,
        path: Path,
        *,
        tar_executable: str,
        member_identities: Mapping[str, FileIdentity],
        runner: CommandRunner,
    ) -> None:
        self.path = path
        self.tar_executable = tar_executable
        self.member_identities = member_identities
        self.runner = runner

    def extract_member(self, member: str, destination: Path) -> Path:
        identity = self.member_identities.get(member)
        if identity is None:
            raise ValueError(f"unsupported shareware member: {member}")
        destination = Path(destination)
        with atomic_path(destination) as temporary:
            with temporary.open("wb") as output:
                try:
                    result = self.runner(
                        [self.tar_executable, "-xOf", str(self.path), member],
                        stdout=output,
                        stderr=subprocess.PIPE,
                        check=False,
                        timeout=TAR_TIMEOUT_SECONDS,
                    )
                except subprocess.TimeoutExpired as error:
                    raise RuntimeError(
                        f"archive extractor timed out extracting {member} after "
                        f"{TAR_TIMEOUT_SECONDS} seconds"
                    ) from error
            if result.returncode:
                detail = (
                    bytes(result.stderr or b"")
                    .decode("utf-8", errors="replace")
                    .strip()
                )
                raise RuntimeError(
                    f"archive extractor could not extract {member} from resource.1"
                    + (f": {detail}" if detail else "")
                )
            identity.verify(temporary, member)
        return destination


class SharewareArchive:
    """Reader for the exact, complete Quake 1.06 shareware distribution."""

    def __init__(
        self,
        path: Path,
        *,
        tar_executable: str | None = None,
        archive_identity: FileIdentity = ARCHIVE_IDENTITY,
        resource_identity: FileIdentity = RESOURCE_IDENTITY,
        member_identities: Mapping[str, FileIdentity] = LHA_MEMBERS,
        runner: CommandRunner | None = None,
    ) -> None:
        self.path = Path(path)
        self.tar_executable = tar_executable
        self.archive_identity = archive_identity
        self.resource_identity = resource_identity
        self.member_identities = member_identities
        self.runner = runner or subprocess.run

    def verify(self) -> dict[str, object]:
        if not self.path.is_file():
            raise FileNotFoundError(f"Quake shareware archive not found: {self.path}")
        self.archive_identity.verify(self.path, "quake106.zip")
        return {
            "path": str(self.path.resolve()),
            "bytes": self.archive_identity.size,
            "sha256": self.archive_identity.sha256,
        }

    @contextmanager
    def open_resource(self) -> Iterator[SharewareResource]:
        self.verify()
        with tempfile.TemporaryDirectory(prefix="quake-shareware-") as temporary_dir:
            resource_path = Path(temporary_dir) / RESOURCE_MEMBER
            with zipfile.ZipFile(self.path) as archive:
                matches = [
                    item
                    for item in archive.infolist()
                    if item.filename == RESOURCE_MEMBER
                ]
                if len(matches) != 1:
                    raise RuntimeError(
                        f"quake106.zip must contain exactly one {RESOURCE_MEMBER}"
                    )
                if matches[0].file_size != self.resource_identity.size:
                    raise RuntimeError(
                        f"{RESOURCE_MEMBER} has unexpected ZIP size "
                        f"{matches[0].file_size}"
                    )
                with (
                    archive.open(matches[0]) as source,
                    resource_path.open("wb") as output,
                ):
                    shutil.copyfileobj(source, output, length=1024 * 1024)
            self.resource_identity.verify(resource_path, RESOURCE_MEMBER)
            yield SharewareResource(
                resource_path,
                tar_executable=self.tar_executable or find_bsdtar(),
                member_identities=self.member_identities,
                runner=self.runner,
            )


def extract_shareware_notices(
    archive: Path | SharewareArchive,
    destination: Path,
    *,
    tar_executable: str | None = None,
) -> tuple[Path, Path]:
    source = (
        archive
        if isinstance(archive, SharewareArchive)
        else SharewareArchive(archive, tar_executable=tar_executable)
    )
    destination = Path(destination)
    with source.open_resource() as resource:
        license_path = resource.extract_member(
            "SLICNSE.TXT", destination / "SLICNSE.TXT"
        )
        readme_path = resource.extract_member("README.TXT", destination / "README.TXT")
    return license_path, readme_path
