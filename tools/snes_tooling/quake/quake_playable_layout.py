"""Deterministic playable-module ROM allocation, with MSU load images.

Addresses are explicit: a physical file offset, a CPU mirror, and an optional
GSU bank/address. CPU-only storage must never be admitted to a GSU pointer.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from random import Random
import re

from snes_tooling.shared.ld65_debug import load_debug_records, parse_debug_int
from snes_tooling.quake.quake_playable_maps import MAP_NAMES

HALFBANK = 0x8000
CPU_MODULE_CODE_BYTES = 0x6500
CPU_MODULE_METADATA_OFFSET = 0x7F00
CPU_MODULE_HEADER_OFFSET = 0x7FB0
ROM_BYTES = 0x400000
GSU_ROM_BYTES = 0x300000


def cpu_address(offset: int) -> int:
    if not 0 <= offset < ROM_BYTES:
        raise ValueError("CPU ROM offset outside the cartridge")
    return 0xC00000 + offset


def link_address(offset: int, *, cpu_code=False) -> int:
    if cpu_code:
        if not 0 <= offset < len(MAP_NAMES)*HALFBANK:
            raise ValueError("playable CPU module exceeds the registered bank range")
        return 0x808000 + (offset // HALFBANK) * 0x10000 + offset % HALFBANK
    if offset < 0x200000:
        return 0x808000 + (offset // HALFBANK) * 0x10000 + offset % HALFBANK
    if offset < GSU_ROM_BYTES:
        return 0x600000 + offset - 0x200000
    return cpu_address(offset)


def gsu_address(offset: int) -> tuple[int, int]:
    if not 0 <= offset < GSU_ROM_BYTES:
        raise ValueError("GSU cannot address CPU-only ROM storage")
    address = link_address(offset)
    return (address >> 16) & 0x7F, address & 0xFFFF


def gsu_offset(bank: int, address: int) -> int:
    if 0 <= bank < 0x40 and 0x8000 <= address <= 0xFFFF:
        return bank * HALFBANK + address - HALFBANK
    if 0x40 <= bank < 0x70 and 0 <= address <= 0xFFFF:
        return (bank - 0x40) * 0x10000 + address
    raise ValueError(f"invalid GSU ROM pointer {bank:02x}:{address:04x}")


@dataclass(frozen=True)
class Span:
    module: int
    name: str
    original_offset: int
    run: int
    payload: bytes

    @property
    def key(self):
        return self.module, self.name


@dataclass(frozen=True)
class Placement:
    offset: int
    size: int
    storage: str
    cpu_code: bool = False

    @property
    def link(self):
        if self.storage == "msu":
            return 0x400000 + self.offset - ROM_BYTES
        if self.storage == "cpu" and not self.cpu_code:
            return cpu_address(self.offset)
        return link_address(self.offset, cpu_code=self.cpu_code)

    @property
    def cpu(self):
        return self.link if self.storage == "msu" else cpu_address(self.offset)

    def summary(self):
        result = dict(offset=self.offset, bytes=self.size, storage=self.storage,
                      linkerAddress=self.link, cpuAddress=self.cpu)
        if self.storage == "gsu" or self.cpu_code:
            result["gsuBank"], result["gsuAddress"] = gsu_address(self.offset)
        return result


class RomAllocationError(ValueError):
    def __init__(self, message, *, low, high):
        super().__init__(message)
        self.region = (low, high)


class Allocator:
    def __init__(self):
        self.intervals = []
        self.preserve_texture_windows = False

    def reserve(self, start, size, key):
        end = start + size
        if size <= 0 or any(start < b and a < end for a, b, _ in self.intervals):
            raise ValueError(f"overlapping or empty ROM allocation: {key}")
        self.intervals.append((start, end, key))
        self.intervals.sort()
        return start

    def capacity_diagnostic(self, *, low, high, alignment=2, window=True, bank_bytes=HALFBANK):
        """Describe real free capacity separately from a bank-window limit."""
        gaps, cursor = [], low
        for begin, end, _ in sorted(self.intervals):
            if begin >= high:
                break
            if end <= cursor:
                continue
            if begin > cursor:
                gaps.append((cursor, min(begin, high)))
            cursor = max(cursor, min(end, high))
        if cursor < high:
            gaps.append((cursor, high))
        largest = 0
        for begin, end in gaps:
            at = (begin + alignment - 1) // alignment * alignment
            while at < end:
                stop = min(end, (at // bank_bytes + 1) * bank_bytes) if window else end
                largest = max(largest, stop - at)
                if not window:
                    break
                at = (stop + alignment - 1) // alignment * alignment
        return dict(totalFreeBytes=sum(end - begin for begin, end in gaps),
                    largestFreeGapBytes=max((end - begin for begin, end in gaps), default=0),
                    largestAlignedWindowBytes=largest, freeGapCount=len(gaps))

    def allocate(self, size, key, *, low, high, alignment=2, window=True, bank_bytes=HALFBANK):
        if size <= 0:
            raise ValueError("empty allocation")
        candidates = []
        cuts = [(low, low, "begin"),
                *((max(low, a), min(high, b), k) for a, b, k in self.intervals
                  if a < high and b > low), (high, high, "end")]
        cursor = low
        for begin, end, _ in sorted(cuts):
            if begin > cursor:
                at = (cursor + alignment - 1) & -alignment
                while at + size <= begin:
                    if not window:
                        candidates.append((begin - at - size, at))
                        break
                    bank_end = min(begin, ((at // bank_bytes) + 1) * bank_bytes)
                    if at + size <= bank_end:
                        candidates.append((bank_end - at - size, at))
                    at = ((at // bank_bytes) + 1) * bank_bytes
            cursor = max(cursor, end)
        if not candidates:
            detail = self.capacity_diagnostic(low=low, high=high, alignment=alignment,
                                              window=window, bank_bytes=bank_bytes)
            raise RomAllocationError(f"{key}: no {size}-byte allocation in {low:x}..{high:x}; "
                                     f"free={detail['totalFreeBytes']}, "
                                     f"largest aligned window={detail['largestAlignedWindowBytes']}",
                                     low=low, high=high)
        if self.preserve_texture_windows and high <= GSU_ROM_BYTES and size <= 12 * 1024:
            # Preserve 1 KiB texture slots first, then retain windows for
            # larger rasters when candidates use the same number of slots.
            def fit(candidate):
                remaining, offset = candidate
                windows_used = tuple((remaining + size) // length - remaining // length
                                     for length in (1024, 2048, 4096))
                return (*windows_used, remaining, offset)
        else:
            fit = None
        return self.reserve(min(candidates, key=fit)[1], size, key)


def read_spans(module: int, rom: Path, debug: Path) -> list[Span]:
    image = rom.read_bytes()
    records = load_debug_records(debug)
    result = []
    for row in records.get("seg", ()):
        if "ooffs" not in row or not (size := parse_debug_int(row["size"])):
            continue
        offset = parse_debug_int(row["ooffs"])
        data = image[offset:offset+size]
        if len(data) != size:
            raise ValueError("truncated module segment: " + row["name"])
        result.append(Span(module, row["name"], offset,
                           parse_debug_int(row["start"]), data))
    return result


CPU_PREFIXES = ("BSP_CPU_", "BSP_WALK_", "BSP_SHOT_", "BSP_QUAKEC",
                "BSP_COLLISION_", "BSP_WORLD_MARKSURFACES", "BSP_WORLD_VISIBILITY",
                "BSP_DEMO_", "BSP_WEAPON_TABLES", "BSP_SOUNDTRACK",
                "SMPCODE", "FLY_VIEWPORT_DATA", "HDMA_", "BSP_LIGHTMAP_COLORMAPS",
                "BSP_CAMERA_ANGLES", "LIBSFX_SMP")
CODE_NAMES = {"CODE", "RODATA", "LIBSFX", "LIBSFX_PKG", "HEADER", "VECTORS", "NULL"}
SHARED_PREFIXES = ("BSP_DIVIDE_Q12_RECIPROCAL_", "BSP_CPU_HDMA_",
                   "HDMA_", "BSP_LIGHTMAP_COLORMAPS", "BSP_CAMERA_ANGLES")
# QuakeC code/table operands are VM-relative; the map sound overlay is raw BRR.
SHARED_RAW_NAMES = frozenset(("BSPDATA", "BSP_CPU_MAP_TILEMAP", "BSP_WEAPON_DATA0",
                             "FLY_VIEWPORT_DATA", "SMPCODE", "BSP_CPU_MENU_FONT",
                             "BSP_QUAKEC_BYTECODE", "BSP_QUAKEC_FUNCTIONS", "BSP_CPU_MAP_SOUND",
                             "BSP_CPU_WEAPON_SOUND", "LIBSFX_SMP"))


def share_identity(span, address_class):
    """Only reviewed pointer-free assets may share exact prelink contents."""
    if span.name.startswith("BSP_SHARED_TEXEL_"):
        return address_class, "exact-material", span.payload
    if span.name not in SHARED_RAW_NAMES and not span.name.startswith(SHARED_PREFIXES):
        return None
    return address_class, span.name, span.payload


CLASSIC_PREFIXES = ("BSP_WORLD_TEXTURE_", "BSP_WORLD_TEXCOORD_",
                    "BSP_WORLD_LIGHTMAP_", "BSP_LIGHTMAP_COLORMAPS",
                    "BSP_DIVIDE_Q12_RECIPROCAL_", "GSU_", "F3_GSU_")
REFERENCE_ONLY_WORLD = frozenset(("BSP_WORLD_LEAVES", "BSP_WORLD_MARKSURFACES",
                                 "BSP_WORLD_VISIBILITY_0", "BSP_WORLD_VISIBILITY_1"))
WORLD_LIGHTMAP_SAMPLES = tuple(f"BSP_WORLD_LIGHTMAP_{i}" for i in range(5))


def brush_vertex_group(directory: Path, module: int):
    fragments = json.loads((directory/'QuakeBSPBrushAssets.json').read_bytes())['worldComposition']['fragments']
    vertices = fragments['bankRoles']['vertices']
    first, count = vertices['firstBank']-fragments['firstBank'], vertices['bankCount']
    if first < 0 or count < 1 or first+count > fragments['bankCount']:
        raise ValueError('brush vertex bank group escapes its fragment family')
    return tuple((module, f'BSP_BRUSH_FRAGMENTS_{first+index}') for index in range(count))


class LevelLayout:
    def __init__(self, spans: list[Span], *, classic_groups=(), reclaim_module_tails=False,
                 cpu_code_limits=(), hardware_weapon_obj=False):
        self.spans = {s.key: s for s in spans}
        self.modules = tuple(sorted({s.module for s in spans}))
        if any(module < 0 or module >= len(MAP_NAMES) for module in self.modules):
            raise ValueError("playable span has an unregistered module ID")
        self.cpu_module_count = max(2, max(self.modules, default=1) + 1)
        self.placements = {}
        self.allocator = Allocator()
        self.classic_groups = tuple(tuple(group) for group in classic_groups)
        self.reclaim_module_tails = reclaim_module_tails
        self.hardware_weapon_obj = hardware_weapon_obj
        self.cpu_code_limits = tuple(cpu_code_limits) or (CPU_MODULE_CODE_BYTES,) * self.cpu_module_count
        if (len(self.cpu_code_limits) != self.cpu_module_count
                or any(type(end) is not int or not 0 < end < CPU_MODULE_METADATA_OFFSET
                       for end in self.cpu_code_limits)):
            raise ValueError("invalid playable CPU code limits")
        for module in range(self.cpu_module_count):
            for first, end in self.cpu_module_ranges(module):
                self.allocator.reserve(module*HALFBANK+first, end-first, ("CPU module", module, first))

    def cpu_module_ranges(self, module=0):
        if self.reclaim_module_tails:
            # Only the first module carries the cartridge's boot table.
            metadata = CPU_MODULE_METADATA_OFFSET if module == 0 else CPU_MODULE_HEADER_OFFSET
            return ((0, self.cpu_code_limits[module]), (metadata, HALFBANK))
        return ((0, HALFBANK),)

    def relocate(self, module, bank, address):
        old = gsu_offset(bank, address)
        candidates = [s for s in self.spans.values() if s.module == module
                      and s.original_offset <= old < s.original_offset + len(s.payload)]
        if len(candidates) != 1:
            raise ValueError(f"unresolved map-{module} pointer {bank:02x}:{address:04x}")
        span = candidates[0]
        placement = self.placements[span.key]
        return gsu_address(placement.offset + old - span.original_offset)

    def allocate(self, *, preferred_seed=None):
        reserved = self.allocator.intervals.copy()
        try:
            if preferred_seed is None:
                return self._allocate()
            self.allocator.preserve_texture_windows = True
            try:
                return self._allocate(Random(preferred_seed))
            finally:
                self.allocator.preserve_texture_windows = False
        except RomAllocationError as error:
            if not self.reclaim_module_tails or error.region not in ((0, GSU_ROM_BYTES), (GSU_ROM_BYTES, ROM_BYTES)):
                raise
        # Try deterministic orders for similarly sized spans with both fit
        # policies. If needed, pack the bank-local presentation pages earlier
        # so their CPU spill does not compete with the last texture windows.
        attempts = 128
        try:
            policies = ((True, 0), (False, 0), (True, 1536), (False, 1536))
            for preserve_texture_windows, presentation_bias in policies:
                self.allocator.preserve_texture_windows = preserve_texture_windows
                for seed in range(attempts):
                    self.allocator.intervals = reserved.copy()
                    self.placements.clear()
                    try:
                        return self._allocate(Random(seed), presentation_bias=presentation_bias)
                    except RomAllocationError:
                        if (preserve_texture_windows, presentation_bias) == policies[-1] and seed == attempts - 1:
                            raise
        finally:
            self.allocator.preserve_texture_windows = False

    def _allocate(self, order=None, *, presentation_bias=0):
        def group_order(rows):
            return sorted(rows, key=lambda _: order.random()) if order else rows

        shared = {}
        msu_cursor = ROM_BYTES
        pending = []
        sidecar_data = []
        shared_weapon_tables = []
        for span in self.spans.values():
            key, size = span.key, len(span.payload)
            if self.hardware_weapon_obj and span.name == "BSP_WEAPON_TABLES" and span.module:
                shared_weapon_tables.append(span)
            elif span.name in CODE_NAMES:
                # All CPU segment offsets within their original bank remain
                # unchanged, including libSFX absolute/near entrypoints.
                self.placements[key] = Placement(span.module*HALFBANK
                    + span.original_offset % HALFBANK, size, "cpu", True)
            elif (span.name in REFERENCE_ONLY_WORLD or span.name.startswith("BSP_WORLD_PVS_")
                  or (span.name.startswith("BSP_WORLD_TEXCOORD_")
                      and span.module in getattr(self, "world_coordinate_modules", ()))
                  or (span.name in WORLD_LIGHTMAP_SAMPLES and
                      span.module in getattr(self, "world_lightmap_plans", {}))
                  or (span.name.startswith("BSP_ALIAS_") and span.name[10:].isdigit() and int(span.name[10:]) > 0)):
                sidecar_data.append(span)
            elif span.run >> 16 in (0x70, 0x71) and span.name != "GSU_AUX_CODE":
                msu_cursor = (msu_cursor + 15) & -16
                self.placements[key] = Placement(msu_cursor, size, "msu")
                msu_cursor += size
            else:
                pending.append(span)
        # Boot overlays use the bounded synthetic $40-$4F address range.
        # Streamed sprites use explicit MSU seeks and can follow the overlays.
        for span in sidecar_data:
            msu_cursor = (msu_cursor + 15) & -16
            self.placements[span.key] = Placement(msu_cursor, len(span.payload), "msu")
            msu_cursor += len(span.payload)
        for module in self.modules:
            members = sorted((s for s in pending if s.module == module
                              and s.name.startswith("BSP_COLLISION_PACKED_")),
                             key=lambda s: s.original_offset)
            if members:
                extent = sum(len(s.payload) for s in members)
                base = self.allocator.allocate(extent, (module, "collision"),
                    low=GSU_ROM_BYTES, high=ROM_BYTES, alignment=0x10000, window=False)
                cursor = base
                for span in members:
                    self.placements[span.key] = Placement(cursor, len(span.payload), "cpu")
                    cursor += len(span.payload)
                keys = {s.key for s in members}
                pending = [s for s in pending if s.key not in keys]
        # Allocate complete classic-bank runs first. Their readers advance
        # ROMB at 32 KiB boundaries, so arbitrary tail packing is invalid.
        for module in self.modules:
            names = [(module, "BSP_WORLD_LIGHTMAP_DIRECTORY"),
                     (module, "BSP_WORLD_LIGHTMAP_DIRECTORY_TAIL")]
            if all(key in self.spans for key in names):
                first, tail = (self.spans[key] for key in names)
                extent = HALFBANK + len(tail.payload)
                base = self.allocator.allocate(extent, (module, "lightmap-directory"),
                    low=0x200000, high=GSU_ROM_BYTES, alignment=0x10000, window=False)
                for key, offset in zip(names, (base, base+HALFBANK)):
                    self.placements[key] = Placement(offset, len(self.spans[key].payload), "gsu")
                pending = [s for s in pending if s.key not in names]
        cold_groups = {}
        for span in pending:
            if (span.name.startswith(("GSU_", "F3_GSU_"))
                    or span.name == "BSP_WEAPON_FX3_CODE"):
                cold_groups.setdefault((span.module, span.original_offset // HALFBANK), []).append(span)
        grouped = set()
        for key, members in group_order(cold_groups.items()):
            relative = []
            extent = 0
            for span in sorted(members, key=lambda item: item.original_offset):
                offset = (extent + 15) & -16
                relative.append((span, offset))
                extent = offset + len(span.payload)
            base = self.allocator.allocate(extent, ("cold", key), low=self.cpu_module_count*HALFBANK,
                high=0x200000, alignment=HALFBANK)
            # The relocated linker binds each image's symbols independently.
            # Cold calls need the common bank, so pack their aligned images together.
            for span, offset in relative:
                self.placements[span.key] = Placement(base + offset, len(span.payload), "gsu")
                grouped.add(span.key)
        pending = [s for s in pending if s.key not in grouped]
        groups = {}
        for span in pending:
            match = re.fullmatch(r"(BSP_WORLD_TEXTURE_|BSP_WORLD_TEXCOORD_|BSP_WORLD_INDICES_|BSP_DIVIDE_Q12_RECIPROCAL_)(\d+)", span.name)
            if match:
                groups.setdefault((span.module, match[1]), []).append((int(match[2]), span))
        grouped = set()
        for group_key, members in group_order(groups.items()):
            members.sort()
            extent = max(i*HALFBANK+len(s.payload) for i, s in members)
            identity = tuple(s.payload for _, s in members)
            shared_key = (group_key[1], identity) if group_key[1].startswith("BSP_DIVIDE") else None
            if shared_key in shared:
                base = shared[shared_key]
            else:
                base = self.allocator.allocate(extent, group_key, low=self.cpu_module_count*HALFBANK,
                    high=0x200000, alignment=HALFBANK, window=False)
                if shared_key:
                    shared[shared_key] = base
            for index, span in members:
                self.placements[span.key] = Placement(base+index*HALFBANK, len(span.payload), "gsu")
                grouped.add(span.key)
        pending = [s for s in pending if s.key not in grouped]
        # Harder regions first, then largest-first best fit. Explicitly
        # shared tables contain no relocatable pointers.
        grouped = set()
        for group in group_order(self.classic_groups):
            if not group or len(set(group)) != len(group) or any(key in grouped or key not in {s.key for s in pending} for key in group):
                raise ValueError('classic stream group is empty, repeated or already allocated')
            members = [self.spans[key] for key in group]
            extent = max(index*HALFBANK+len(span.payload) for index, span in enumerate(members))
            base = self.allocator.allocate(extent, ('classic-stream', group), low=self.cpu_module_count*HALFBANK,
                high=0x200000, alignment=HALFBANK, window=False)
            for index, span in enumerate(members):
                self.placements[span.key] = Placement(base+index*HALFBANK, len(span.payload), 'gsu')
                grouped.add(span.key)
        pending = [s for s in pending if s.key not in grouped]
        # Include bank-local presentation ROM alongside module code and tables in
        # the size-ordered fit. All use the same 64 KiB CPU mirror windows.
        pending.extend(Span(-1, name, 0, 0, data) for name, data in
                       getattr(self, "presentation_parts", {}).items())
        self.presentation_offsets = {}
        def region(s):
            if s.module == -1:
                return "cpu"
            return ("classic" if s.name.startswith("BSP_SHARED_TEXEL_") and len(s.payload) > HALFBANK else
                    "cpu" if (s.name.startswith(CPU_PREFIXES) and s.name != "BSP_DEMO_TIMING")
                             or (self.hardware_weapon_obj and s.name == "BSP_WEAPON_DATA0") else
                    "classic" if (s.name.startswith(CLASSIC_PREFIXES)
                                   and "DIRECTORY" not in s.name)
                                   or s.name == "BSP_BRUSH_RUNTIME_1" else "gsu")
        def pending_order(span):
            if span.name in ("LIBSFX_SMP", "BSP_CPU_SHOT_TAIL_MASK"):
                # Both CPU-only tables fit small tails. Place them after
                # the spans that require larger or GSU-readable windows.
                return True, HALFBANK, span.key
            variation = 512 * (order.random() - .5) if order else 0
            priority = presentation_bias if span.module == -1 else 0
            return region(span) != "classic", -len(span.payload) - priority + variation, span.key

        pending.sort(key=pending_order)
        for span in pending:
            kind, size = region(span), len(span.payload)
            identity = share_identity(span, kind)
            if identity is not None and identity in shared:
                offset = shared[identity]
            else:
                low, high = ((GSU_ROM_BYTES, ROM_BYTES) if kind == "cpu" else
                             (0, 0x200000 if kind == "classic" else GSU_ROM_BYTES))
                geometry = dict(alignment=HALFBANK if size > HALFBANK and span.name.startswith("BSP_SHARED_TEXEL_")
                                else 256 if span.name == "SMPCODE" else 2 if span.module == -1 else 16,
                                bank_bytes=0x10000 if kind == "cpu" else HALFBANK,
                                window=not (size > HALFBANK and span.name.startswith("BSP_SHARED_TEXEL_")))
                try:
                    offset = self.allocator.allocate(size, span.key, low=low, high=high, **geometry)
                except RomAllocationError:
                    if kind != "cpu":
                        raise
                    # CPU-only data uses the contiguous $C0..$FF CPU mirror.
                    # Physical capacity below 3 MiB supports either processor.
                    # Retain each CPU bank boundary and the original alignment.
                    offset = self.allocator.allocate(size, span.key, low=0, high=GSU_ROM_BYTES, **geometry)
                if identity is not None:
                    shared[identity] = offset
            if span.module == -1:
                self.presentation_offsets[span.name] = offset
            else:
                self.placements[span.key] = Placement(offset, size, "cpu" if kind == "cpu" else "gsu")
        # All playable maps assemble the same live weapon tables against the
        # same weapon pixel stream. Module zero also owns the trailing flash
        # palette. Compose independently compares every final linked byte.
        for span in shared_weapon_tables:
            master = self.placements[0, span.name]
            pixels = self.placements[span.module, "BSP_WEAPON_DATA0"]
            if (len(span.payload) + 512 != master.size or
                    pixels != self.placements[0, "BSP_WEAPON_DATA0"]):
                raise ValueError("playable weapon tables require one shared data extent and flash palette")
            self.placements[span.key] = Placement(master.offset, len(span.payload), "cpu")
        self.affine_descriptor_offsets = {
            module: self.allocator.allocate(
                len(plan.descriptor_bytes), (module, "world affine descriptors"),
                low=0, high=GSU_ROM_BYTES, alignment=2)
            for module, plan in getattr(self, "world_affine_uv", {}).items()
            if plan.descriptor_bytes
        }
        self._place_e1m1_vm_in_bytecode_bank()
        return self

    def _place_e1m1_vm_in_bytecode_bank(self):
        """Try a swap within CPU ROM after the renderer placements are fixed."""
        from snes_tooling.quake.quake_pickup_notice import pack_pickup_blend

        module = MAP_NAMES.index("e1m1")
        code_key = module, "BSP_QUAKEC"
        code = self.placements.get(code_key)
        bytecode = self.placements.get((module, "BSP_QUAKEC_BYTECODE"))
        if (code is None or bytecode is None or code.storage != "cpu" or bytecode.storage != "cpu"
                or code.offset < GSU_ROM_BYTES or bytecode.offset < GSU_ROM_BYTES):
            return
        bank = bytecode.offset >> 16
        if bank == code.offset >> 16:
            return
        blend = getattr(self, "pickup_blend", None)
        packed_blend = pack_pickup_blend(blend) if blend is not None else b""
        for key, hull in self.placements.items():
            if (key[1] not in ("BSP_WALK_HULL", "BSP_SHOT_HULL") or hull.storage != "cpu"
                    or hull.offset >> 16 != bank or hull.size > code.size):
                continue
            end = hull.offset + code.size
            blend_start = (code.offset + hull.size + 1) & -2
            if (end - 1) >> 16 != bank or blend_start + len(packed_blend) > code.offset + code.size:
                continue
            moved = (code_key, key)
            if packed_blend:
                moved += ((-1, "pickup-blend"),)
            remaining = [(a, b, owner) for a, b, owner in self.allocator.intervals
                         if owner not in moved]
            if any(hull.offset < b and a < end for a, b, _ in remaining):
                continue
            self.allocator.intervals = remaining
            self.allocator.reserve(hull.offset, code.size, code_key)
            self.allocator.reserve(code.offset, hull.size, key)
            self.placements[code_key] = Placement(hull.offset, code.size, "cpu")
            self.placements[key] = Placement(code.offset, hull.size, "cpu")
            if packed_blend:
                self.allocator.reserve(blend_start, len(packed_blend), (-1, "pickup-blend"))
                self.presentation_offsets["pickup-blend"] = blend_start
                self.presentation_parts["pickup-blend"] = self.pickup_blend = packed_blend
                self.pickup_blend_packed = True
            return

    def deduplication_summary(self):
        """Count explicit shared backing bytes; never infer sharing from a hash."""
        groups = {}
        for key, placement in self.placements.items():
            if key[1] in CODE_NAMES:
                continue
            identity = (placement.storage, placement.offset, placement.size, placement.cpu_code)
            groups.setdefault(identity, []).append(key)
        shared = []
        for (storage, offset, size, _), keys in sorted(groups.items()):
            if len(keys) < 2:
                continue
            payload = self.spans[keys[0]].payload
            if any(self.spans[key].payload != payload for key in keys[1:]):
                raise ValueError("shared backing has different original bytes: " + str(keys))
            shared.append(dict(storage=storage, offset=offset, bytesEach=size,
                               copies=len(keys), savedBytes=(len(keys)-1)*size,
                               sha256=sha256(payload).hexdigest(), segments=[list(key) for key in keys]))
        logical = sum(len(self.spans[key].payload) for keys in groups.values() for key in keys)
        unique = sum(identity[2] for identity in groups)
        return dict(scope="allocated non-CPU-bank loadable segments; exact placement aliases only",
                    logicalPayloadBytes=logical, uniqueBackingPayloadBytes=unique,
                    sharedPayloadBytes=logical-unique, sharedGroups=shared)

    def summary(self):
        return {f"{module}:{name}": p.summary()
                for (module, name), p in sorted(self.placements.items())}
