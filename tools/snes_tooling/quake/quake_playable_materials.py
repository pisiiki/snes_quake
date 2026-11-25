"""Exact immutable material spans for shared playable cartridges.

Original receipt-bound Data stays intact. Derived assembly emits independent
material spans plus the original embedded PVS directory. Native
texture records keep dimensions/flags and acquire only new bank/address words.
"""
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import json
import re
import struct

from snes_tooling.quake.quake_playable_layout import Span, gsu_offset, gsu_address

TEXTURE = struct.Struct("<BHHHB")
MATERIAL = "BSP_SHARED_TEXEL_"
PVS = "BSP_MATERIAL_PVS_"
POOLED = re.compile(r"(?:BSP_SHARED_TEXEL_|BSP_MATERIAL_PVS_)([0-9A-F]{6})")
PIXEL_SEGMENT = re.compile(r"BSP_(?:WORLD|BRUSH)_TEXTURE_\d+")


def identity(payload):
    return dict(bytes=len(payload), sha256=sha256(payload).hexdigest())


def material_name(offset):
    return MATERIAL + f"{offset:06X}"


def original_offset(name):
    match = POOLED.fullmatch(name)
    return int(match[1], 16) if match else None


@dataclass(frozen=True)
class MaterialPlan:
    module: int
    spans: tuple
    files: dict
    pvs: dict
    sources: dict

    def report(self):
        return dict(schema="quake-playable-material-pool-v1", module=self.module,
            materials=sum(span.name.startswith(MATERIAL) for span in self.spans),
            rawMaterialBytes=sum(len(span.payload) for span in self.spans if span.name.startswith(MATERIAL)),
            sourceFiles=self.sources, sourceTextureBytes=sum(row["bytes"] for row in self.sources.values()),
            originalDataUnchanged=True, embeddedPvsBytes=self.pvs["bytes"])


def plan_materials(directory, module, *, palette_map=None):
    """Admit exact declared texels and PVS only; prove every omitted byte FF."""
    directory = Path(directory)
    world = json.loads((directory / "QuakeBSPMetadata.json").read_bytes())
    brush = json.loads((directory / "QuakeBSPBrushAssets.json").read_bytes())
    exact = world["world"]["packing"]["exact_textures"]
    files = {}
    for item in exact["pixel_chunks"]:
        files[item["file"]] = gsu_offset(item["gsu_rom_bank"], item.get("gsu_rom_address", 32768))
    for index in range(brush["textures"]["reservedBankCount"]):
        files[f"QuakeBSPBrushTexturePixels{index}.bin"] = gsu_offset(brush["capacity"]["firstBrushBank"] + index, 32768)
    sources, blobs, coverage = {}, {}, {}
    for filename, offset in files.items():
        blob = (directory / filename).read_bytes()
        if len(blob) != 32768:
            raise ValueError("material pooling requires complete canonical source pixel banks")
        sources[filename], blobs[filename], coverage[filename] = identity(blob), blob, bytearray(len(blob))
    def extract(offset, size):
        output = bytearray()
        while size:
            owners = [(name, first) for name, first in files.items() if first <= offset < first + len(blobs[name])]
            if len(owners) != 1:
                raise ValueError("material extent escapes canonical source pixel banks")
            name, first = owners[0]
            begin = offset - first
            take = min(size, len(blobs[name]) - begin)
            coverage[name][begin:begin + take] = b"\x01" * take
            output += blobs[name][begin:begin + take]
            size -= take
            offset += take
        return bytes(output)
    rows = list(TEXTURE.iter_unpack((directory / "QuakeBSPWorldTextureDirectory.bin").read_bytes()))
    runtime = brush["runtime"]
    texdir = next(row for row in runtime["sections"] if row["name"] == "TEXDIR")
    data = (directory / f"QuakeBSPBrushRuntime{texdir['bank'] - runtime['firstBank']}.bin").read_bytes()
    table = data[texdir["address"] - 32768:texdir["address"] - 32768 + texdir["bytes"]]
    if identity(table) != {key: texdir[key] for key in ("bytes", "sha256")}:
        raise ValueError("source QBSA TEXDIR identity differs")
    rows += list(TEXTURE.iter_unpack(table))
    spans = {}
    for bank, address, width, height, flags in rows:
        size = width * height
        if not size or flags & 2 and address + size > 65536:
            raise ValueError("material falsely claims a single-bank source extent")
        if not flags & 2 and (bank >= 64 or address != 32768):
            raise ValueError("cross-bank material must begin at a classic bank boundary")
        if not flags & 2 and size <= 32768:
            raise ValueError("cross-bank flag on a small material is unsupported")
        offset = gsu_offset(bank, address)
        payload = extract(offset, size)
        if palette_map is not None:
            payload = payload.translate(palette_map)
        name = material_name(offset)
        candidate = Span(module, name, offset, 0, payload)
        if name in spans and spans[name] != candidate:
            raise ValueError("one source material pointer has incompatible extents")
        spans[name] = candidate
    pvs = brush["worldComposition"]["leafPvs"]
    offset = gsu_offset(pvs["directoryBank"], pvs["directoryAddress"])
    name = PVS + f"{offset:06X}"
    pvs_bytes = 0
    if any(first <= offset < first + len(blobs[filename]) for filename, first in files.items()):
        pvs_payload = extract(offset, pvs["directoryBytes"])
        pvs_bytes = len(pvs_payload)
        spans[name] = Span(module, name, offset, 0, pvs_payload)
    ordered = sorted(spans.values(), key=lambda span: span.original_offset)
    if any(a.original_offset + len(a.payload) > b.original_offset for a, b in zip(ordered, ordered[1:])):
        raise ValueError("material and residual extents overlap")
    for filename, blob in blobs.items():
        if any(value != 255 and not covered for value, covered in zip(blob, coverage[filename], strict=True)):
            raise ValueError("unclassified non-FF byte in source pixel bank: " + filename)
    return MaterialPlan(module, tuple(ordered), files,
        dict(name=name, offset=offset, bytes=pvs_bytes), sources)


def replace_pixel_spans(spans, plan):
    return [span for span in spans if span.module != plan.module or not PIXEL_SEGMENT.fullmatch(span.name)] + list(plan.spans)


def pooled(segments):
    return any(name.startswith(MATERIAL) for name in segments)


def recover_pixel_file(size, source_first, segments, read_segment):
    """Rebuild original complete bank; callers still require final source SHA."""
    output, occupied = bytearray(b"\xff" * size), bytearray(size)
    for name, row in segments.items():
        first = original_offset(name)
        if first is None or first >= source_first + size or first + row["bytes"] <= source_first:
            continue
        payload = read_segment(row)
        low, high = max(first, source_first), min(first + len(payload), source_first + size)
        begin, count = low - source_first, high - low
        if len(payload) != row["bytes"] or any(occupied[begin:begin + count]):
            raise ValueError("pooled source bank reconstruction overlaps or changed size")
        output[begin:begin + count] = payload[low - first:low - first + count]
        occupied[begin:begin + count] = b"\x01" * count
    return bytes(output)


def restore_texture_directory(payload, originals, segments):
    """Use row identity when one physical raster has several canonical sources."""
    rows = list(TEXTURE.iter_unpack(payload))
    if len(rows) != len(originals):
        raise ValueError("pooled texture directory source row count differs")
    output = bytearray()
    for row, (old_bank, old_address) in zip(rows, originals, strict=True):
        span = segments[material_name(gsu_offset(old_bank, old_address))]
        if (row[0], row[1], row[2] * row[3]) != (span["gsuBank"], span["gsuAddress"], span["bytes"]):
            raise ValueError("pooled texture pointer does not name its exact declared material")
        output += TEXTURE.pack(old_bank, old_address, *row[2:])
    return bytes(output)


def source_pixel_ranges(world, brush):
    result = {row["file"]: gsu_offset(row["gsu_rom_bank"], row.get("gsu_rom_address", 32768))
              for row in world["world"]["packing"]["exact_textures"]["pixel_chunks"]}
    result.update({f"QuakeBSPBrushTexturePixels{index}.bin": gsu_offset(brush["capacity"]["firstBrushBank"] + index, 32768)
                   for index in range(brush["textures"]["reservedBankCount"])})
    return result


def derived_material_files(example, layout, plan, files):
    """Replace only raw source-bank emission with checked material/PVS segments."""
    example = Path(example)
    output, assembly = {}, []
    names = []
    for span in plan.spans:
        placement = layout.placements[span.key]
        bank, address = gsu_address(placement.offset)
        cross = placement.size > 32768
        if (placement.storage != "gsu" or not cross and address + placement.size > 65536
                or cross and (bank >= 64 or address != 32768 or placement.offset + placement.size > 0x200000)):
            raise ValueError("pooled material/PVS escapes one GSU bank")
        filename = "Data/" + span.name + ".bin"
        payload = span.payload
        if span.name.startswith(PVS):
            source = next((name, first) for name, first in plan.files.items()
                          if first <= span.original_offset < first + 32768)
            name, first = source
            relative = "Data/" + name
            blob = files.get(relative, (example / relative).read_bytes())
            offset = span.original_offset - first
            payload = blob[offset:offset + placement.size]
        output[filename] = payload
        lines = [f'.segment "{span.name}"', f'        .incbin "{filename}"',
                 f'.assert __{span.name}_LOAD__ = ${placement.link:06X}, lderror, "Shared material load moved"',
                 f'.assert __{span.name}_SIZE__ = {placement.size}, lderror, "Shared material size changed"']
        output["Data/" + span.name + ".s"] = ("\n".join(lines) + "\n").encode("ascii")
        assembly.append(f'.include "Data/{span.name}.s"')
        names.append(span.name)
    output["Data/QuakeBSPSharedMaterials.s"] = ("\n".join(assembly) + "\n").encode("ascii")
    text = files.get("quake.s", (example / "quake.s").read_bytes()).decode("utf-8")
    begin = text.index('.segment "BSP_WORLD_TEXTURE_0"')
    end = text.index('.segment "BSP_WORLD_LIGHTMAP_DIRECTORY"', begin)
    text = text[:begin] + '.include "Data/QuakeBSPSharedMaterials.s"\n' + text[end:]
    text, count = re.subn(r'^\.assert __BSP_WORLD_TEXTURE_\d+_LOAD__[^\n]*\n', '', text, flags=re.M)
    if count != 6:
        raise ValueError("expected six replaced world texture load contracts")
    output["quake.s"] = text.encode("utf-8")
    relative = "quake/DynamicBrushAssets.s"
    text = files.get(relative, (example / relative).read_bytes()).decode("utf-8")
    begin = text.index('.segment "BSP_BRUSH_TEXTURE_0"')
    end = text.index('.segment "BSP_BRUSH_RUNTIME_0"', begin)
    text = text[:begin] + text[end:]
    text, count = re.subn(r'^\.assert __BSP_BRUSH_TEXTURE_\d+_(?:LOAD|SIZE)__[^\n]*\n', '', text, flags=re.M)
    if count != 8:
        raise ValueError("expected eight replaced brush texture bank contracts")
    output[relative] = text.encode("utf-8")
    return output, names


def declare_material_segments(template, plan):
    marker = re.search(r'(?m)^SEGMENTS\s*\{', template)
    if not marker:
        raise ValueError("missing linker SEGMENTS block")
    end = template.index('}', marker.end())
    declarations = ''.join(f'    {span.name}: load = ROM0, type = ro, optional = yes, define = yes;\n'
                           for span in plan.spans)
    return template[:end] + declarations + template[end:]
