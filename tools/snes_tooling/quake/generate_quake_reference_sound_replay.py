#!/usr/bin/env python3
"""Generate the configured reference-renderer Quake sound replay."""

from __future__ import annotations

from snes_tooling import Workspace

import argparse
import hashlib
import json
import sys
import time
from collections import Counter
from pathlib import Path

from typing import Any, Sequence


TOOLS = Workspace.discover().path('tools', 'snes_tooling', 'quake')
SHARED_TOOLS = Workspace.discover().shared_tools


from snes_tooling.shared.generated_outputs import (  # noqa: E402
    GeneratedOutputError,
    OwnedFileFamily,
    sync_generated_outputs,
)
import snes_tooling.quake.generate_quake_bsp as bsp_tools  # noqa: E402
from snes_tooling.quake.quake_rom_config import (  # noqa: E402
    DEFAULT_CONFIG,
    configured_playback_sample_rate,
    resolve_configured_demo,
)
from snes_tooling.quake.quake_sound_replay import (  # noqa: E402
    SOUND_EVENT_START,
    SOUND_EVENT_STATIC,
    SOUND_EVENT_STOP,
    SOUND_REPLAY_EVENT,
    SOUND_REPLAY_HEADER,
    SOUND_REPLAY_MAGIC,
    SOUND_REPLAY_SOUND,
    SOUND_REPLAY_VERSION,
    decode_sound_replay,
    encode_sound_replay,
    extract_canonical_sound_replay,
    pak_sound_entry,
)


DEFAULT_OUTPUT = Workspace.discover().root / "src/snes_quake/Data"
STREAM_NAME = Path("QuakeBSPReferenceSoundReplay.bin")
METADATA_NAME = Path("QuakeBSPReferenceSoundReplay.json")
OWNED_OUTPUTS = (
    OwnedFileFamily(prefix="QuakeBSPReferenceSoundReplay", suffix=".bin"),
    OwnedFileFamily(prefix="QuakeBSPReferenceSoundReplay", suffix=".json"),
)
EVENT_NAMES = {
    SOUND_EVENT_START: "start",
    SOUND_EVENT_STOP: "stop",
    SOUND_EVENT_STATIC: "static",
}


def build_outputs(
    pak_path: Path, *, config_path: Path = DEFAULT_CONFIG
) -> tuple[dict[Path, bytes], dict[str, Any]]:
    archive = bsp_tools.PakArchive(pak_path)
    selected_demo = resolve_configured_demo(archive.read, config_path)
    sample_rate = configured_playback_sample_rate(config_path)
    replay = extract_canonical_sound_replay(
        selected_demo.payload, selected_demo.map_entry, sample_rate
    )
    payload = encode_sound_replay(replay)
    decoded = decode_sound_replay(payload)
    if decoded.events != replay.events:
        raise AssertionError("sound replay codec did not round-trip")
    waveform_audit = []
    for slot, (precache_index, name) in enumerate(
        zip(replay.sound_precache_indices, replay.sound_names, strict=True)
    ):
        entry = pak_sound_entry(name)
        waveform = archive.read(entry)
        waveform_audit.append(
            {
                "slot": slot,
                "soundPrecacheIndex": precache_index,
                "name": name,
                "pakEntry": entry,
                "bytes": len(waveform),
                "sha256": hashlib.sha256(waveform).hexdigest(),
            }
        )
    event_counts = Counter(EVENT_NAMES[event.kind] for event in replay.events)
    metadata: dict[str, Any] = {
        "schema": "quake-reference-sound-replay-v1",
        "version": SOUND_REPLAY_VERSION,
        "source": {
            "pakPathHint": bsp_tools.QUAKE_PAK_PATH_HINT,
            "mapEntry": selected_demo.map_entry,
            "demoEntry": selected_demo.label,
            "demoSource": selected_demo.source.kind,
            "demoLocator": selected_demo.source.locator,
            "demoSha256": selected_demo.sha256,
        },
        "timeline": {
            "sampleRateHz": replay.sample_rate_hz,
            "firstSourceServerTime": replay.first_server_time,
            "cameraRowCount": replay.camera_row_count,
            "cameraTrackFnv1a64": f"{replay.camera_track_fnv1a64:016x}",
            "viewEntity": replay.view_entity,
        },
        "format": {
            "magic": SOUND_REPLAY_MAGIC.decode("ascii"),
            "headerBytes": SOUND_REPLAY_HEADER.size,
            "soundRecordBytes": SOUND_REPLAY_SOUND.size,
            "eventRecordBytes": SOUND_REPLAY_EVENT.size,
            "timeEncoding": "signed Q16 seconds relative to first camera row",
            "coordinateEncoding": "signed Q3",
        },
        "coverage": {
            "precacheSoundCount": len(replay.sound_names),
            "sounds": waveform_audit,
            "sourceEventCount": replay.source_event_count,
            "eventCount": len(replay.events),
            "eventCounts": dict(sorted(event_counts.items())),
            "eventsBeforeFirstCamera": sum(
                event.due_q16 < 0 for event in replay.events
            ),
        },
        "output": {
            "path": STREAM_NAME.as_posix(),
            "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        },
    }
    rendered = (json.dumps(metadata, indent=2, sort_keys=True) + "\n").encode(
        "ascii"
    )
    return {STREAM_NAME: payload, METADATA_NAME: rendered}, metadata


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pak", type=Path)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    started = time.monotonic()
    args = parse_args(argv)
    try:
        outputs, metadata = build_outputs(
            bsp_tools.locate_quake_pak(args.pak), config_path=args.config
        )
        sync_generated_outputs(
            outputs,
            args.output,
            check=args.check,
            owned_families=OWNED_OUTPUTS,
        )
    except KeyboardInterrupt:
        print(
            "reference sound replay interrupted: "
            f"elapsed={time.monotonic() - started:.3f}s",
            file=sys.stderr,
        )
        return 130
    except (GeneratedOutputError, OSError, RuntimeError, ValueError) as error:
        print(
            f"error: {error}; elapsed={time.monotonic() - started:.3f}s",
            file=sys.stderr,
        )
        return 1
    action = "verified" if args.check else "generated"
    coverage = metadata["coverage"]
    print(
        f"reference sound replay {action}: "
        f"sounds={coverage['precacheSoundCount']} "
        f"events={coverage['eventCount']} "
        f"rows={metadata['timeline']['cameraRowCount']} "
        f"elapsed={time.monotonic() - started:.3f}s"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
