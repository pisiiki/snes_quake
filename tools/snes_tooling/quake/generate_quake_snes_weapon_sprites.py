"""Generate native-resolution X2 weapon blit frames from the configured Quake demo."""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import time
from bisect import bisect_right
from collections import Counter
from math import ceil, floor, hypot, pi, sin
from pathlib import Path

from snes_tooling import Workspace
from snes_tooling.quake.quake_assets import MdlModel, decode_positions, parse_mdl
from snes_tooling.quake.quake_brush_replay import encode_precise_camera_samples
from snes_tooling.quake.quake_bsp_assets import (
    PakArchive, locate_quake_pak, snes_color, texture_coordinate_map,
)
from snes_tooling.quake.quake_camera_sampling import sample_camera_track
from snes_tooling.quake.quake_demo import decode_camera_entity_track
from snes_tooling.quake.quake_rom_config import (
    DEFAULT_CONFIG,
    configured_playback_sample_rate,
    resolve_configured_demo,
)
from snes_tooling.quake.quake_status_hud import HEIGHT as HUD_HEIGHT
from snes_tooling.quake.quake_scene_palette import FLASH_TINT, FLASH_DENOMINATOR, flash_palette
from snes_tooling.shared.generated_outputs import (
    GeneratedOutputError,
    OwnedFileFamily,
    sync_generated_outputs,
)


DEFAULT_OUTPUT = Workspace.discover().quake_example / "Data"
PREFIX = "QuakeBSPWeaponSprites"
OWNED_OUTPUTS = (
    OwnedFileFamily(PREFIX, ".i"),
    OwnedFileFamily(PREFIX, ".json"),
    OwnedFileFamily(PREFIX, ".qwv"),
    OwnedFileFamily(PREFIX + "Mask", ".i"),
    OwnedFileFamily(PREFIX + "Data", ".bin", numbered=True),
)
WIDTH = 128
HEIGHT = 112
PLAYABLE_WEAPON_HEIGHT = HEIGHT - HUD_HEIGHT // 2
# WinQuake, viewsize 110 and fov 90, 320x200 with the 24-line bar.
STOCK_VIEW_WIDTH = 320
STOCK_VIEW_HEIGHT = 200 - HUD_HEIGHT
STOCK_X_FOCAL = STOCK_VIEW_WIDTH / 2
STOCK_Y_FOCAL = STOCK_X_FOCAL * (5 / 6)
BOB_LIMIT = 3
BOB_OFFSETS = range(-BOB_LIMIT, BOB_LIMIT + 1)
FOCAL = 160 * (5 / 6) * HEIGHT / 152
NEAR = 5
FULLBRIGHT_FIRST = 224
RECORD8 = struct.Struct("<HB4H")
HALFBANK_BYTES = 0x8000
# Existing tails in ROM6 (blitter), ROM7 (faces), ROM4 (vertices).
DATA_CHUNK_LIMITS = (0x6000, 0x2400, 0x2100)
# The lookup bank also contains the CPU camera angle tables.
LOOKUP_BYTES_LIMIT = 0x7800
INVISIBILITY = 1 << 19

FrameKey = tuple[str, int]
Pixels = dict[tuple[int, int], int]


def demo_weapon_frames(demo: bytes, map_entry: str, rate: int, camera_track: bytes):
    """Sample the current weapon/frame and movement bob at each camera pose."""
    track = decode_camera_entity_track(demo, map_entry)
    cameras = sample_camera_track([sample.camera for sample in track.samples], rate)
    if encode_precise_camera_samples(cameras) != camera_track:
        raise ValueError("weapon frames do not reproduce the generated camera track")
    snapshots = track.entity_frames
    times = [frame.server_time for frame in snapshots]
    frames: list[tuple[FrameKey | None, int]] = []
    for camera in cameras:
        snapshot = snapshots[max(0, bisect_right(times, camera.server_time) - 1)]
        state = snapshot.client_view
        if not state.weapon or state.health <= 0 or state.items & INVISIBILITY or state.intermission:
            frames.append((None, 0))
            continue
        if not 0 < state.weapon < len(snapshot.model_precache):
            raise ValueError(f"demo weapon {state.weapon} is outside the model precache")
        name = snapshot.model_precache[state.weapon].lower()
        if not name.startswith("progs/v_") or not name.endswith(".mdl"):
            raise ValueError(f"demo view weapon is not a supported MDL: {name}")
        phase = (camera.server_time % 0.6) / 0.6
        bob = max(-7.0, min(4.0, hypot(*state.velocity[:2]) * 0.02 * (0.3 + 0.7 * sin(2 * pi * phase))))
        # Approximate the projected motion at the lower center of the sprite.
        # Quantizing here lets both renderers reuse one sprite per MDL frame.
        offset = max(-BOB_LIMIT, min(BOB_LIMIT, round(48 * (24 / (24 + 0.4 * bob) - 1))))
        frames.append(((name, state.weapon_frame), offset))
    return frames


def clip_near(vertices):
    clipped = []
    previous = vertices[-1]
    for current in vertices:
        if (previous[0] >= NEAR) != (current[0] >= NEAR):
            fraction = (NEAR - previous[0]) / (current[0] - previous[0])
            clipped.append(tuple(a + (b - a) * fraction for a, b in zip(previous, current)))
        if current[0] >= NEAR:
            clipped.append(current)
        previous = current
    return clipped


def edge(a, b, x, y):
    return (b[0] - a[0]) * (y - a[1]) - (b[1] - a[1]) * (x - a[0])


def rasterize(model: MdlModel, frame_index: int, *, playable: bool = False) -> Pixels:
    """Rasterize the level WinQuake eye mount into the X2 logical viewport."""
    if not 0 <= frame_index < len(model.frames):
        raise ValueError(f"demo weapon frame {frame_index} is outside its MDL")
    width, height = model.header.skin_width, model.header.skin_height
    skin = model.skins[0]
    view_height = PLAYABLE_WEAPON_HEIGHT if playable else HEIGHT
    x_focal = STOCK_X_FOCAL * WIDTH / STOCK_VIEW_WIDTH if playable else FOCAL
    y_focal = STOCK_Y_FOCAL * view_height / STOCK_VIEW_HEIGHT if playable else FOCAL
    mount_height = 1 if playable else 2
    points = [
        (x - 1 / 32, -y + 1 / 32, -z - mount_height + 1 / 32)
        for x, y, z in decode_positions(model, model.frames[frame_index])
    ]
    visible = {}
    for triangle in model.triangles:
        vertices = []
        for index in triangle.vertices:
            uv = model.st_vertices[index]
            s = uv.s + (width // 2 if uv.on_seam and not triangle.faces_front else 0)
            vertices.append((*points[index], s, uv.t))
        projected = [
            ((WIDTH - 1) / 2 + x_focal * x / z, (view_height - 1) / 2 + y_focal * y / z, 1 / z, s, t)
            for z, x, y, s, t in clip_near(vertices)
        ]
        for index in range(2, len(projected)):
            a, b, c = projected[0], projected[index - 1], projected[index]
            area = edge(a, b, c[0], c[1])
            if area <= 0:
                continue
            left = max(0, ceil(min(a[0], b[0], c[0])))
            right = min(WIDTH - 1, floor(max(a[0], b[0], c[0])))
            top = max(0, ceil(min(a[1], b[1], c[1])))
            bottom = min(view_height + BOB_LIMIT - 1, floor(max(a[1], b[1], c[1])))
            for y in range(top, bottom + 1):
                for x in range(left, right + 1):
                    wa = edge(b, c, x, y) / area
                    wb = edge(c, a, x, y) / area
                    wc = edge(a, b, x, y) / area
                    if min(wa, wb, wc) < 0:
                        continue
                    depth = wa * a[2] + wb * b[2] + wc * c[2]
                    if depth < visible.get((x, y), (0, 0))[0]:
                        continue
                    s = int(max(0, min(width - 1, wa * a[3] + wb * b[3] + wc * c[3])))
                    t = int(max(0, min(height - 1, wa * a[4] + wb * b[4] + wc * c[4])))
                    visible[x, y] = depth, skin[t * width + s]
    return {position: color for position, (_, color) in visible.items()}


def encode_frame(pixels: Pixels, remap: tuple[int, ...]) -> bytes:
    """Encode opaque pixels as masked planar rows on the logical 128×112 grid."""
    rows: dict[int, list[int]] = {}
    coordinates = texture_coordinate_map()
    for (x, y), color in pixels.items():
        x, y = coordinates[x], coordinates[y]
        address = ((y & ~7) << 7) + ((x & ~7) << 3) + (y & 7) * 2
        bit = 0x80 >> (x & 7)
        row = rows.setdefault(address, [0] * 9)
        row[0] |= bit
        index = remap[color]
        for plane in range(8):
            if index & (1 << plane):
                row[plane + 1] |= bit
    physical_to_logical = {physical: logical for logical, physical in enumerate(coordinates[:8])}
    return b"".join(
        RECORD8.pack(address, mask, *(bits[i] | bits[i + 1] << 8 for i in range(0, 8, 2)))
        for address, (mask, *bits) in sorted(
            rows.items(), key=lambda row: (row[0] >> 10, physical_to_logical[(row[0] >> 1) & 7], row[0])
        )
    )


def visible_row_count(payload: bytes, offset: int, *, height: int = HEIGHT) -> int:
    coordinates = texture_coordinate_map()
    inverse = {physical: logical for logical, physical in enumerate(coordinates[:8])}
    return sum(
        ((address >> 10) * 8 + inverse[(address >> 1) & 7] + offset) < height
        for address, *_ in RECORD8.iter_unpack(payload)
    )


def bob_address_deltas() -> list[int]:
    coordinates = texture_coordinate_map()[:8]
    inverse = {physical: logical for logical, physical in enumerate(coordinates)}
    return [
        (logical // 8 * 1024 + (coordinates[logical % 8] - physical) * 2) & 0xFFFF
        for offset in BOB_OFFSETS
        for physical in range(8)
        for logical in (inverse[physical] + offset,)
    ]


def encode_reference_frame(pixels: Pixels, *, flash: bool) -> bytes:
    """Store the same texels in a tight bounding box for the C++ reference."""
    if not pixels:
        return bytes(4) + bytes((flash,))
    x0, y0 = map(min, zip(*pixels))
    x1, y1 = map(max, zip(*pixels))
    width, height = x1 + 1 - x0, y1 + 1 - y0
    logical = bytearray(width * height)
    for (x, y), color in pixels.items():
        logical[(y - y0) * width + x - x0] = color
    return bytes((x0, y0, width, height, flash)) + logical


def common_opaque_rectangle(frames: list[Pixels], *, hidden: bool) -> tuple[int, int, int, int]:
    """Return the largest rectangle covered by every displayed weapon frame."""
    if hidden or not frames:
        return (0, 0, 0, 0)
    common = set(frames[0]).intersection(*frames[1:])
    rows = [0] * HEIGHT
    for x, y in common:
        rows[y] |= 1 << x
    best = (0, 0, 0, 0)
    best_area = 0
    for y0, top in enumerate(rows):
        columns = top
        for y1 in range(y0, HEIGHT):
            columns &= rows[y1]
            if not columns:
                break
            runs = columns
            while runs:
                x0 = (runs & -runs).bit_length() - 1
                x1 = x0
                while runs & (1 << x1):
                    runs ^= 1 << x1
                    x1 += 1
                area = (x1 - x0) * (y1 + 1 - y0)
                if area > best_area:
                    best = (x0, y0, x1, y1 + 1)
                    best_area = area
    return best


def asm_bytes(label: str, values: bytes) -> list[str]:
    return [label + ":"] + [
        "        .byte " + ",".join(f"${value:02X}" for value in values[start : start + 24])
        for start in range(0, len(values), 24)
    ]


def pack_frame_data(payloads):
    """Keep every frame contiguous within the existing GSU-readable bank tails."""
    chunks = [bytearray() for _ in DATA_CHUNK_LIMITS]
    locations = [None] * len(payloads)
    for frame, payload in sorted(enumerate(payloads), key=lambda pair: (-len(pair[1]), pair[0])):
        for chunk, limit in enumerate(DATA_CHUNK_LIMITS):
            if len(chunks[chunk]) + len(payload) <= limit:
                locations[frame] = (chunk, len(chunks[chunk]))
                chunks[chunk].extend(payload)
                break
        else:
            raise ValueError("weapon frames exceed the available FX3 ROM bank tails")
    while chunks and not chunks[-1]:
        chunks.pop()
    return chunks, locations


def assembly(poses: bytes, idle: bytes, entries, bob_counts, *, live=b"", axe=b"", chunks=1) -> bytes:
    source = [
        ("; Generated from stock live view models. Do not edit." if live
         else "; Generated from the configured demo. Do not edit."),
        *([f"BSP_WEAPON_LIVE_TICKS = {len(live) - 1}"] if live else []),
        *([f"BSP_WEAPON_AXE_TICKS = {len(axe) - 1}",
           f"BSP_WEAPON_AXE_IDLE = {axe[-1]}"] if axe else []),
        f"BSP_WEAPON_POSE_COUNT = {len(poses) // 2}",
        f"BSP_WEAPON_BOB_LIMIT = {BOB_LIMIT}",
        f"BSP_WEAPON_FRAME_COUNT = {len(entries)}",
        f"BSP_WEAPON_MAX_ROWS = {max((max(counts) for counts in bob_counts), default=0)}",
        ".pushseg",
        '.segment "BSP_WEAPON_TABLES"',
        *(asm_bytes("QuakeBSPWeaponLiveFrames", live) if live else []),
        *(asm_bytes("QuakeBSPWeaponAxeFrames", axe) if axe else []),
        *asm_bytes("QuakeBSPWeaponPoses", poses),
        *asm_bytes("QuakeBSPWeaponIdleFrames", idle),
        "QuakeBSPWeaponDescriptors:",
        "        .res 8, 0",
    ]
    for chunk, offset, count, flash in entries:
        label = f"QuakeBSPWeaponData{chunk}"
        source.extend((
            f"        .word .loword({label} + ${offset:04X}), ${count:04X}, {int(flash)}, ^{label} & $7F",
        ))
    source.extend(("QuakeBSPWeaponBobRows:", "        .res 16, 0"))
    for counts in bob_counts:
        source.append("        .word " + ",".join(map(str, (*counts, 0))))
    source.append("QuakeBSPWeaponBobDeltas:")
    deltas = bob_address_deltas()
    for start in range(0, len(deltas), 8):
        source.append("        .word " + ",".join(f"${delta:04X}" for delta in deltas[start:start + 8]))
    for chunk in range(chunks):
        label = f"QuakeBSPWeaponData{chunk}"
        source.extend((
            f'.segment "BSP_WEAPON_DATA{chunk}"',
            label + ":",
            f'        .incbin "Data/{PREFIX}Data{chunk}.bin"',
            label + "End:",
            f'.assert ^({label}End-1) = ^{label}, lderror, "Weapon rows cross their FX3 ROM bank"',
        ))
    return ("\n".join((*source, ".popseg", ""))).encode("ascii")


LIVE_MODEL = "progs/v_shot.mdl"
AXE_MODEL = "progs/v_axe.mdl"
LIVE_OPAQUE_BLACK = 48


def live_pixels(model, frame, colors, *, playable=False):
    """Use the stock scene palette, including its opaque copy of black."""
    if colors[0] != colors[LIVE_OPAQUE_BLACK]:
        raise ValueError("stock weapon needs the scene's opaque black index")
    art = rasterize(model, frame, playable=playable)
    return {(x, y): index or LIVE_OPAQUE_BLACK for (x, y), index in art.items()}


def live_axe_pixels(pixels):
    # Keep the stock axe crop in the lower right. The smaller view sprite
    # fits the START compositor's 176-row undo buffer at every swing pose.
    x0, y0 = WIDTH - 1, 99
    source_x = [x0 + round((x - x0) * 8 / 5) for x in range(WIDTH)]
    source_y = [y0 + round((y - y0) * 8 / 5) for y in range(y0 + 1)]
    return {(x, y): pixels[sx, sy] for y, sy in enumerate(source_y)
            for x, sx in enumerate(source_x) if (sx, sy) in pixels}


def build_live_outputs(pak: PakArchive, sequence, *, axe_sequence=(), playable=False, nailgun=False):
    model_bytes = pak.read(LIVE_MODEL)
    model = parse_mdl(model_bytes)
    colors = tuple(snes_color(rgb) for rgb in struct.iter_unpack("<BBB", pak.read("gfx/palette.lmp")))
    frames = sorted({frame for _, frame in sequence})
    ids = {frame: index + 1 for index, frame in enumerate(frames)}
    if frames[0] != 0 or not 30 <= sequence[-1][0] < 128:
        raise ValueError("unsupported stock shotgun frame schedule")
    live = bytes(ids[frame] for i, (start, frame) in enumerate(sequence)
                 for _ in range(start, sequence[i+1][0] if i+1 < len(sequence) else start+1))
    height = PLAYABLE_WEAPON_HEIGHT if playable else HEIGHT
    art = [(LIVE_MODEL, frame, live_pixels(model, frame, colors, playable=playable))
           for frame in frames]
    axe = b""
    if axe_sequence:
        axe_bytes = pak.read(AXE_MODEL)
        axe_model = parse_mdl(axe_bytes)
        axe_frames = sorted({frame for _, frame in axe_sequence})
        axe_ids = {frame: len(art) + index + 1 for index, frame in enumerate(axe_frames)}
        axe = bytes(axe_ids[frame] for i, (start, frame) in enumerate(axe_sequence)
                    for _ in range(start, axe_sequence[i+1][0] if i+1 < len(axe_sequence) else start+1))
        art.extend((AXE_MODEL, frame, live_axe_pixels(live_pixels(axe_model, frame, colors)))
                   for frame in axe_frames)
    nail_idle = 0
    if nailgun:
        nail_model = parse_mdl(pak.read("progs/v_nail.mdl"))
        if len(nail_model.frames) != 9:
            raise ValueError("stock Nailgun must have an idle and eight firing frames")
        nail_idle = len(art) + 1
        art.extend(("progs/v_nail.mdl", frame, live_pixels(nail_model, frame, colors, playable=playable))
                   for frame in range(len(nail_model.frames)))
        super_idle = len(art) + 1
        super_model = parse_mdl(pak.read("progs/v_shot2.mdl"))
        if len(super_model.frames) != len(frames):
            raise ValueError("stock Super Shotgun requires seven weapon frames")
        art.extend(("progs/v_shot2.mdl", frame, live_pixels(super_model, frame, colors, playable=playable))
                   for frame in frames)
    chunks = [bytearray()]
    entries, bob_counts, records = [], [], []
    for frame_id, (name, frame, pixels) in enumerate(art, 1):
        # X2 reverses the packed page at presentation. Store the weapon
        # mirrored in the producer's coordinates.
        packed_pixels = {(WIDTH - 1 - x, y): index for (x, y), index in pixels.items()}
        payload = encode_frame(packed_pixels, tuple(range(256)))
        if any(y < BOB_LIMIT or y >= height + BOB_LIMIT for _, y in pixels):
            raise ValueError("live weapon frame exceeds the viewport bob margin")
        counts = [visible_row_count(payload, bob, height=height) for bob in BOB_OFFSETS]
        bob_counts.append(counts)
        flash = name in (LIVE_MODEL, "progs/v_nail.mdl", "progs/v_shot2.mdl") and any(index >= FULLBRIGHT_FIRST for index in pixels.values())
        if len(chunks[-1]) + len(payload) > HALFBANK_BYTES:
            chunks.append(bytearray())
        entries.append((len(chunks) - 1, len(chunks[-1]), counts[BOB_LIMIT], flash))
        chunks[-1].extend(payload)
        records.append(dict(id=frame_id, model=name, animationFrame=frame,
                            flash=entries[-1][3],
                            visiblePixels=sum(y < height for _, y in pixels), rowCount=counts[BOB_LIMIT]))
    if len(chunks) > (1 if playable else 2):
        raise ValueError("live weapon sprite rows exceed the configured FX3 ROM banks")
    data = b"".join(chunks)
    report = dict(schema="quake-live-x2-weapon-v1", model=LIVE_MODEL,
                  modelSha256=hashlib.sha256(model_bytes).hexdigest(), frames=records,
                  viewSequence=sequence, rowBytes=RECORD8.size, spriteBytes=len(data),
                  canonicalUsedIndices=sorted({i for _, _, pixels in art for i in pixels.values()}),
                  dataSha256=hashlib.sha256(data).hexdigest())
    if playable:
        report["viewportHeight"] = height
    if axe:
        report.update(axeModelSha256=hashlib.sha256(axe_bytes).hexdigest(), axeViewSequence=axe_sequence)
    return {
        Path(PREFIX + ".i"): (
            (f"BSP_WEAPON_PLAYABLE_HEIGHT = {height}\n".encode("ascii") if playable else b"")
            + (f"BSP_WEAPON_NAIL_IDLE = {nail_idle}\nBSP_WEAPON_SSG_IDLE = {super_idle}\n".encode("ascii") if nailgun else b"")
            + assembly(b"", b"", entries, bob_counts, live=live, axe=axe, chunks=len(chunks))
        ),
        **{Path(f"{PREFIX}Data{i}.bin"): bytes(chunk) for i, chunk in enumerate(chunks)},
        Path(PREFIX + ".json"): (json.dumps(report, indent=2, sort_keys=True) + "\n").encode("ascii"),
    }


def build_outputs(pak_path: Path, config_path: Path, camera_track: Path):
    pak = PakArchive(pak_path)
    demo = resolve_configured_demo(pak.read, config_path)
    rate = configured_playback_sample_rate(config_path)
    camera = camera_track.read_bytes()
    rows = demo_weapon_frames(demo.payload, demo.map_entry, rate, camera)
    keys = sorted({key for key, _ in rows if key is not None})
    if len(keys) > 255:
        raise ValueError("demo exceeds 255 distinct weapon frames")
    frame_ids = {key: index + 1 for index, key in enumerate(keys)}
    models = {}
    idle_ids = {}
    art = {}
    colors = tuple(snes_color(rgb) for rgb in struct.iter_unpack("<BBB", pak.read("gfx/palette.lmp")))
    if len(colors) != 256:
        raise ValueError("Quake weapon sprites require a 256-color palette")
    for name, frame in keys:
        if name not in models:
            model = parse_mdl(pak.read(name))
            if len(model.frames) != model.header.frame_count or len(model.skins) != model.header.skin_count:
                raise ValueError(f"demo weapon needs grouped MDL frame or skin timing: {name}")
            models[name] = model
            # Frame zero sorts first if the demo actually displayed it.
            idle_ids[name] = frame_ids[(name, frame)]
        pixels = live_pixels(models[name], frame, colors)
        art[name, frame] = pixels
    payloads = []
    entries = []
    frame_report = []
    bob_counts = []
    reference_frames = bytearray()
    for name, frame in keys:
        pixels = art[name, frame]
        has_fullbright = any(color >= FULLBRIGHT_FIRST and y < HEIGHT for (_, y), color in pixels.items())
        payload = encode_frame(pixels, tuple(range(256)))
        reference_frames.extend(encode_reference_frame(pixels, flash=has_fullbright))
        if any(y < BOB_LIMIT for _, y in pixels):
            raise ValueError("weapon bob could cross the top of the viewport")
        counts = [visible_row_count(payload, offset) for offset in BOB_OFFSETS]
        bob_counts.append(counts)
        count = counts[BOB_LIMIT]
        entries.append((count, has_fullbright))
        payloads.append(payload)
        frame_report.append({
            "id": frame_ids[name, frame], "model": name, "animationFrame": frame,
            "opaquePixels": len(pixels), "rowCount": count,
            "flash": has_fullbright,
            "fullbrightPixels": sum(color >= FULLBRIGHT_FIRST for color in pixels.values()),
        })
    chunks, locations = pack_frame_data(payloads)
    entries = [(*location, *entry) for location, entry in zip(locations, entries, strict=True)]
    for record, (chunk, offset) in zip(frame_report, locations, strict=True):
        record.update(chunk=chunk, offset=offset)
    poses = bytes(value for key, offset in rows for value in (frame_ids.get(key, 0), offset & 0xFF))
    idle = bytes((0, *(idle_ids[name] for name, _ in keys)))
    states = {(key, offset) for key, offset in rows if key is not None}
    states.update((key, 0) for key in keys)
    opaque_rect = common_opaque_rectangle(
        [{(x, y + offset): color for (x, y), color in art[key].items() if y + offset < HEIGHT}
         for key, offset in states],
        hidden=any(key is None for key, _ in rows),
    )
    lookup_bytes = len(poses) + len(idle) + 24 * (1 + len(entries)) + 16 * len(BOB_OFFSETS)
    if lookup_bytes > LOOKUP_BYTES_LIMIT:
        raise ValueError("demo weapon lookup tables exceed their CPU ROM halfbank")
    outputs = {Path(f"{PREFIX}Data{i}.bin"): bytes(data) for i, data in enumerate(chunks)}
    outputs[Path(PREFIX + ".i")] = assembly(poses, idle, entries, bob_counts, chunks=len(chunks))
    mask = dict(zip(("X_FIRST", "Y_FIRST", "X_END", "Y_END"), opaque_rect))
    outputs[Path(PREFIX + "Mask.i")] = (
        "; Generated common weapon coverage. End coordinates are exclusive.\n"
        f"BSP_X2_WEAPON_COMMON_CORE_PROVEN = {int(bool(opaque_rect[2]))}\n"
        + "".join(f"BSP_X2_WEAPON_OPAQUE_{axis} = {value}\n" for axis, value in mask.items())
    ).encode("ascii")
    outputs[Path(PREFIX + ".qwv")] = (
        struct.pack("<4s4H", b"QWV4", WIDTH, HEIGHT, len(rows), len(entries))
        + poses + idle + struct.pack("<256H", *colors)
        + flash_palette(struct.pack("<256H", *colors)) + reference_frames
    )
    report = {
        "schema": "quake-snes-weapon-sprites-v4",
        "width": WIDTH, "height": HEIGHT,
        "demo": demo.source.locator,
        "demoSha256": demo.sha256,
        "map": demo.map_entry,
        "cameraTrackSha256": hashlib.sha256(camera).hexdigest(),
        "poseCount": len(rows),
        "sampleRate": rate,
        "hiddenPoses": sum(key is None for key, _ in rows),
        "bobOffsets": dict(sorted(Counter(offset for _, offset in rows).items())),
        "frameCount": len(keys),
        "commonOpaqueRectangle": list(opaque_rect),
        "rowBytes": RECORD8.size,
        "canonicalUsedIndices": sorted({i for pixels in art.values() for i in pixels.values()}),
        "flashTint": {"rgb5": list(FLASH_TINT), "blendDenominator": FLASH_DENOMINATOR},
        "flashPoses": sum(bool(key) and entries[frame_ids[key] - 1][3] for key, _ in rows),
        "bankBytes": [len(data) for data in chunks],
        "romPayloadBytes": sum(map(len, chunks)) + lookup_bytes,
        "frames": frame_report,
        "outputs": {path.name: hashlib.sha256(payload).hexdigest() for path, payload in outputs.items()},
    }
    outputs[Path(PREFIX + ".json")] = (json.dumps(report, indent=2, sort_keys=True) + "\n").encode("ascii")
    return outputs, report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pak", type=Path)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--camera-track", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    started = time.monotonic()
    try:
        camera = args.camera_track or args.output / "QuakeBSPDemoPrecise.bin"
        outputs, report = build_outputs(locate_quake_pak(args.pak), args.config, camera)
        sync_generated_outputs(outputs, args.output, check=args.check, owned_families=OWNED_OUTPUTS)
    except (OSError, ValueError, GeneratedOutputError) as error:
        print(f"Quake X2 weapon sprites failed in {time.monotonic() - started:.3f}s: {error}")
        return 1
    action = "checked" if args.check else "generated"
    print(
        f"Quake X2 weapon sprites {action}: {report['frameCount']} frames, "
        f"{report['poseCount']} poses, {report['romPayloadBytes']} ROM bytes "
        f"in {time.monotonic() - started:.3f}s"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
