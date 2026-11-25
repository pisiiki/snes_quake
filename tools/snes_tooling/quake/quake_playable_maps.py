"""Stable module identities shared by the playable packer and its consumers."""

from dataclasses import dataclass
from hashlib import sha256
import json

MAP_NAMES = ("e1m1", "e1m3", "start", "e1m2", "e1m4")
DEFAULT_MAP = "start"


@dataclass(frozen=True)
class TapeBoot:
    initial_map: str
    skill: int
    always_run: bool
    tape_sha256: str

    def report(self):
        return dict(initialMap=self.initial_map, skill=self.skill,
                    alwaysRun=self.always_run, tapeSha256=self.tape_sha256)


def read_tape_boot(path) -> TapeBoot:
    """Read boot settings without importing any future tape input into the ROM."""
    raw = path.read_bytes()
    tape = json.loads(raw)
    if (not isinstance(tape, dict) or tape.get("schema") != "quake-gameplay-tape-v1"
            or tape.get("clock") != "video"):
        raise ValueError("tape boot requires a recorded video-clock gameplay tape")
    initial_map, skill, always_run = (tape.get(key) for key in ("initialMap", "skill", "alwaysRun"))
    if initial_map not in MAP_NAMES or type(skill) is not int or skill not in range(4) or type(always_run) is not bool:
        raise ValueError("invalid tape boot map, skill or Always Run setting")
    return TapeBoot(initial_map, skill, always_run, sha256(raw).hexdigest())


def id_for(name: str) -> int:
    try:
        return MAP_NAMES.index(name)
    except ValueError:
        raise ValueError(f"unsupported playable map: {name}") from None


def default_map_for_count(count: int, *, tape_boot: TapeBoot | None = None) -> str:
    if type(count) is not int or not 2 <= count <= len(MAP_NAMES):
        raise ValueError("invalid playable module count")
    if tape_boot is not None:
        if tape_boot.initial_map not in MAP_NAMES[:count]:
            raise ValueError("recorded tape's initial map is absent from the playable package")
        return tape_boot.initial_map
    return DEFAULT_MAP if DEFAULT_MAP in MAP_NAMES[:count] else MAP_NAMES[0]


def right_menu_path(count: int, target: str) -> tuple[str, ...]:
    """Cold map followed by each native Right transition through the target."""
    default = default_map_for_count(count)
    names = MAP_NAMES[:count]
    first = names.index(default)
    if target not in names:
        raise ValueError(f"playable package does not contain {target}")
    distance = (names.index(target) - first) % count
    return tuple(names[(first + step) % count] for step in range(distance + 1))


def config_for(name: str) -> str:
    id_for(name)
    return f"fly-{name}.json"


def native_constants(count=len(MAP_NAMES), *, tape_boot: TapeBoot | None = None) -> str:
    lines = [f"PLAYABLE_MAP_COUNT = {count}",
             f"PLAYABLE_DEFAULT_MAP_ID = {id_for(default_map_for_count(count, tape_boot=tape_boot))}"]
    lines.extend(f"PLAYABLE_{name.upper()}_MAP_ID = {index}"
                 for index, name in enumerate(MAP_NAMES))
    if tape_boot is not None:
        lines += [f"PLAYABLE_TAPE_BOOT_SKILL = {tape_boot.skill}",
                  f"PLAYABLE_TAPE_BOOT_ALWAYS_RUN = {int(tape_boot.always_run)}"]
    return "\n".join(lines) + "\n"
