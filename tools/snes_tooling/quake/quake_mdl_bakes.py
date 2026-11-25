"""Retain complete quarter-unit MDL masters independently of ROM residency."""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, replace
from functools import lru_cache
import hashlib
import inspect
import json
import math
import os
from pathlib import Path
import pickle
import struct
import tempfile
import time
import zlib

import numpy as np

from snes_tooling import Workspace
from snes_tooling.quake.quake_assets import decode_positions
from snes_tooling.quake.quake_mdl_conversion import convert_master, CONVERSION_VERSION
from snes_tooling.shared.host_resources import physical_core_count

HEADER = struct.Struct('<4sHHhhHH32s32s')


@dataclass(frozen=True)
class MdlBakeContext:
    palette_words: tuple[int, ...]
    cache_root: str
    model_key: str = ''

    @classmethod
    def from_palette(cls, palette, cache_root=None):
        if len(palette) != 768:
            raise ValueError('MDL bakes require the original 256-color Quake palette')
        words = tuple(sum(round(palette[i + n] * 31 / 255) << shift
                          for n, shift in enumerate((0, 5, 10)))
                      for i in range(0, 768, 3))
        root = cache_root or os.environ.get('SNES_MDL_BAKE_CACHE') or (
            Workspace.discover().root / 'tmp/cache/quake-mdl-bakes')
        return cls(words, str(Path(root).resolve()))

    def for_model(self, model):
        # Bind decoded geometry/UVs/skins/frames, independently of palette and
        # conversion parameters; parser changes cannot alias a different model.
        key = hashlib.sha256(pickle.dumps(model, protocol=5)).hexdigest()
        return replace(self, model_key=key)


def rasterize_master(model, frame_index, view, *, factor=4):
    """Sample original geometry/UVs at exactly 1/factor world units."""
    from snes_tooling.quake.quake_billboard_assets import MDL_VIEW_BASES
    positions = decode_positions(model, model.frames[frame_index])
    cosine, sine = MDL_VIEW_BASES[view & 7]
    points = [(sine*x - cosine*y, z) for x, y, z in positions]
    depths = [cosine*x + sine*y for x, y, z in positions]
    minx = math.floor(min(p[0] for p in points))
    maxx = math.ceil(max(p[0] for p in points))
    miny = math.floor(min(p[1] for p in points))
    maxy = math.ceil(max(p[1] for p in points))
    ww, wh = maxx-minx, maxy-miny
    if not 0 < ww <= 255 or not 0 < wh <= 255:
        raise ValueError('MDL world extent escapes the sprite ABI')
    w, h = ww*factor, wh*factor
    pixels = np.zeros((h, w), dtype=np.uint8)
    depth = np.full((h, w), -np.inf)
    skin = np.frombuffer(model.skins[0], dtype=np.uint8).reshape(
        model.header.skin_height, model.header.skin_width)

    def edge(a, b, x, y):
        return (x-a[0])*(b[1]-a[1]) - (y-a[1])*(b[0]-a[0])

    def sum3(a, b, c):
        # Match Python 3.13's compensated scalar sum at exact UV boundaries.
        first = a + b
        correction = np.where(np.abs(a) >= np.abs(b), (a-first)+b, (b-first)+a)
        second = first + c
        correction += np.where(np.abs(first) >= np.abs(c), (first-second)+c, (c-second)+first)
        return second + correction

    for tri in model.triangles:
        ids = tri.vertices
        p = [points[i] for i in ids]
        area = edge(p[0], p[1], p[2][0], p[2][1])
        if abs(area) <= 1e-9:
            continue
        st = []
        for i in ids:
            uv = model.st_vertices[i]
            s = uv.s + (model.header.skin_width//2 if not tri.faces_front and uv.on_seam else 0)
            st.append((float(s), float(uv.t)))
        x0 = max(0, math.floor((min(a[0] for a in p)-minx)*factor))
        x1 = min(w-1, math.ceil((max(a[0] for a in p)-minx)*factor)-1)
        y0 = max(0, math.floor((min(a[1] for a in p)-miny)*factor))
        y1 = min(h-1, math.ceil((max(a[1] for a in p)-miny)*factor)-1)
        if x1 < x0 or y1 < y0:
            continue
        xx, yy = np.meshgrid(minx+(np.arange(x0, x1+1)+.5)/factor,
                             miny+(np.arange(y0, y1+1)+.5)/factor)
        a = edge(p[1], p[2], xx, yy)/area
        b = edge(p[2], p[0], xx, yy)/area
        c = edge(p[0], p[1], xx, yy)/area
        d = sum3(a*depths[ids[0]], b*depths[ids[1]], c*depths[ids[2]])
        old = depth[y0:y1+1, x0:x1+1]
        mask = (np.minimum(np.minimum(a, b), c) >= -1e-8) & (d > old)
        sx = np.clip(np.floor(sum3(a*st[0][0], b*st[1][0], c*st[2][0])), 0, skin.shape[1]-1).astype(int)
        sy = np.clip(np.floor(sum3(a*st[0][1], b*st[1][1], c*st[2][1])), 0, skin.shape[0]-1).astype(int)
        values = skin[sy[mask], sx[mask]]
        if np.any(values == 255):
            raise ValueError('opaque MDL index 255 escapes biased-byte storage')
        old[mask] = d[mask]
        region = pixels[y0:y1+1, x0:x1+1]
        region[mask] = values + 1
    if not pixels.any():
        raise ValueError('MDL projection produced an empty master')
    return pixels[::-1].copy(), minx, maxy


@lru_cache(maxsize=1)
def rasterizer_key():
    from snes_tooling.quake.quake_billboard_assets import MDL_VIEW_BASES
    return hashlib.sha256((inspect.getsource(rasterize_master) + inspect.getsource(decode_positions)
                           + repr(MDL_VIEW_BASES) + HEADER.format).encode()).hexdigest()


def master_path(context, frame, view):
    return Path(context.cache_root) / context.model_key / rasterizer_key() / f'{frame:04d}-{view}.qmb'


CACHE_READ_ATTEMPTS = 41
CACHE_READ_DELAY = 0.05


def read_bake(path):
    """Windows can briefly deny opening an already-published cache file."""
    for attempt in range(CACHE_READ_ATTEMPTS):
        try:
            return path.read_bytes()
        except PermissionError as error:
            if os.name != 'nt' or attempt + 1 == CACHE_READ_ATTEMPTS:
                error.add_note(f'model bake read failed after {attempt + 1} attempts: {path}')
                raise
            time.sleep(CACHE_READ_DELAY)


def publish_bake(path, blob):
    """Publish an immutable cache entry without replacing an open reader's file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, suffix='.tmp')
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(blob)
        try:
            if os.name == 'nt':
                os.rename(temporary, path)  # Windows refuses to replace an existing name.
            else:
                os.link(temporary, path)
        except FileExistsError:
            if read_bake(path) != blob:
                raise ValueError(f'conflicting model bake for cache key: {path}') from None
    finally:
        Path(temporary).unlink(missing_ok=True)


def load_master(model, frame, view, context):
    if not context.model_key:
        context = context.for_model(model)
    path = master_path(context, frame, view)
    if path.exists():
        blob = read_bake(path)
        expected, compressed = blob[:32], blob[32:]
        payload = zlib.decompress(compressed)
        if hashlib.sha256(payload).digest() != expected:
            raise ValueError(f'retained MDL master hash mismatch: {path}')
        magic, w, h, left, top, stored_frame, stored_view, source, producer = HEADER.unpack_from(payload)
        if (magic != b'QMB1' or w % 4 or h % 4 or len(payload) != HEADER.size+w*h
                or (stored_frame, stored_view) != (frame, view)
                or source.hex() != context.model_key or producer.hex() != rasterizer_key()):
            raise ValueError(f'invalid retained MDL master: {path}')
        pixels = np.frombuffer(payload[HEADER.size:], dtype=np.uint8).reshape(h, w)
        return pixels, left, top, hashlib.sha256(blob).hexdigest()
    pixels, left, top = rasterize_master(model, frame, view)
    payload = HEADER.pack(b'QMB1', pixels.shape[1], pixels.shape[0], left, top, frame, view,
                          bytes.fromhex(context.model_key), bytes.fromhex(rasterizer_key()))+pixels.tobytes()
    blob = hashlib.sha256(payload).digest()+zlib.compress(payload, level=1)
    publish_bake(path, blob)
    return pixels, left, top, hashlib.sha256(blob).hexdigest()


@lru_cache(maxsize=32)
def converter_key(words, density):
    from snes_tooling.quake import quake_mdl_conversion
    producer = Path(quake_mdl_conversion.__file__).read_bytes()
    return hashlib.sha256(producer + struct.pack('<256H', *words) + str(density).encode()).hexdigest()


def load_conversion(model, frame, view, density, context, *, master_bundle=None):
    from snes_tooling.quake.quake_billboard_assets import _density_fraction, _density_output_extent
    context = context if context.model_key else context.for_model(model)
    master, left, top, master_sha = master_bundle or load_master(model, frame, view, context)
    wh, ww = master.shape[0]//4, master.shape[1]//4
    fraction = _density_fraction(density)
    width, height = _density_output_extent(ww, fraction), _density_output_extent(wh, fraction)
    key = converter_key(context.palette_words, density)
    path = (Path(context.cache_root)/context.model_key/rasterizer_key()
            / f'converted-{key}' / f'{frame:04d}-{view}.qsc')
    if path.exists():
        blob = read_bake(path)
        payload = zlib.decompress(blob[32:])
        if hashlib.sha256(payload).digest() != blob[:32]:
            raise ValueError(f'retained MDL conversion hash mismatch: {path}')
        record = json.loads(payload)
        if (record['masterSha256'] != master_sha or record['converterSha256'] != key
                or record['finalDimensions'] != [width, height]
                or (record['frame'], record['view']) != (frame, view)):
            raise ValueError(f'retained MDL conversion binding mismatch: {path}')
        encoded = np.frombuffer(bytes.fromhex(record['pixels']), dtype=np.uint8).reshape(height, width)
    else:
        encoded, metrics = convert_master(master, (width, height), context.palette_words)
        record = dict(schema=CONVERSION_VERSION, masterSha256=master_sha, converterSha256=key,
                      frame=frame, view=view, finalDimensions=[width, height],
                      metrics=metrics, pixels=encoded.tobytes().hex())
        payload = (json.dumps(record, sort_keys=True, separators=(',', ':'))+'\n').encode()
        blob = hashlib.sha256(payload).digest()+zlib.compress(payload, level=1)
        publish_bake(path, blob)
    return encoded, record['metrics'], (left, top, ww, wh), hashlib.sha256(blob).hexdigest()


def converted_billboard(model, frame, view, density, model_id, context):
    from snes_tooling.quake.quake_billboard_assets import BillboardSprite
    encoded, _, (left, top, ww, wh), _ = load_conversion(model, frame, view, density, context)
    height, width = encoded.shape
    pixels = tuple(0 if value == 0 else 0x100 | (int(value)-1) for value in encoded.flat)
    # Visibility defaults to these actual converted pixels. Offline occlusion
    # must never cull a newly covered cell using the old coarse projection.
    return BillboardSprite(width, height, left, top, pixels, ww, wh, model_id, frame, view)


def _retain_model(task):
    name, model, context, density = task
    context = context.for_model(model)
    records = []
    conversions = []
    for frame in range(len(model.frames)):
        for view in range(8):
            bundle = load_master(model, frame, view, context)
            pixels, left, top, digest = bundle
            records.append(dict(frame=frame, view=view, sha256=digest,
                                width=pixels.shape[1], height=pixels.shape[0], left=left, top=top))
            encoded, metrics, _, converted_sha = load_conversion(
                model, frame, view, density, context, master_bundle=bundle)
            conversions.append(dict(frame=frame, view=view, sha256=converted_sha,
                                    masterSha256=digest, width=encoded.shape[1], height=encoded.shape[0],
                                    **metrics))
    return dict(name=name, modelSha256=context.model_key, sourceFrames=len(model.frames),
                rasterizerSha256=rasterizer_key(), masters=records, conversions=conversions)


def retain_complete_bakes(models, context, *, density=1, workers=None):
    from snes_tooling.quake.quake_billboard_assets import SprModel
    tasks = [(name, model, context, density) for name, model in sorted(models.items()) if not isinstance(model, SprModel)]
    count = min(workers or physical_core_count(), len(tasks))
    if count > 1:
        with ProcessPoolExecutor(max_workers=count) as pool:
            records = list(pool.map(_retain_model, tasks))
    else:
        records = list(map(_retain_model, tasks))
    converted_records = [dict(name=r['name'], modelSha256=r['modelSha256'],
                              sourceFrames=r['sourceFrames'], conversions=r.pop('conversions')) for r in records]
    inventory = dict(schema='quake-mdl-quarter-unit-masters-v1', worldUnitsPerSample=.25,
                     modelCount=len(records), frameCount=sum(r['sourceFrames'] for r in records),
                     masterCount=sum(len(r['masters']) for r in records), models=records)
    payload = (json.dumps(inventory, sort_keys=True, separators=(',', ':'))+'\n').encode()
    digest = hashlib.sha256(payload).hexdigest()
    path = Path(context.cache_root)/'inventories'/f'{digest}.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_bytes(payload)
    converted = dict(schema=CONVERSION_VERSION, masterInventorySha256=digest,
                     converterSha256=converter_key(context.palette_words, density),
                     worldUnitsPerStoredTexel=density, models=converted_records)
    converted_payload = (json.dumps(converted, sort_keys=True, separators=(',', ':'))+'\n').encode()
    converted_digest = hashlib.sha256(converted_payload).hexdigest()
    converted_path = Path(context.cache_root)/'inventories'/f'{converted_digest}.json'
    if not converted_path.exists():
        converted_path.write_bytes(converted_payload)
    return dict(schema=inventory['schema'], worldUnitsPerSample=.25,
                modelCount=inventory['modelCount'], frameCount=inventory['frameCount'],
                masterCount=inventory['masterCount'], inventorySha256=digest,
                conversion=dict(schema=CONVERSION_VERSION, variantCount=inventory['masterCount'],
                                inventorySha256=converted_digest, contrast=.5, coverageThreshold=.5))


def summarize_conversion(sprites, models, context):
    """Versioned high-resolution audit replaces obsolete modal assertions."""
    contexts = {i: context.for_model(model) for i, model in enumerate(models)}
    total = dict(variantCount=0, storageTexelCount=0, storageOpaqueTexelCount=0,
                 masterTexelCount=0, projectedOpaqueArea=0., alphaSquaredError=0., tinyCoverageFallback=0)
    for sprite in sprites:
        model = models[sprite.model]
        ctx = contexts[sprite.model]
        master, left, top, _ = load_master(model, sprite.frame, sprite.view, ctx)
        # Independently audit the exact final dimensions and conversion.
        expected, metrics = convert_master(master, (sprite.width, sprite.height), context.palette_words)
        if sprite.encoded_pixels != expected.tobytes() or (left, top) != (sprite.left, sprite.top):
            raise AssertionError('converted MDL differs from retained-master conversion')
        if sprite.visibility_raster != (sprite.width, sprite.height, sprite.pixels):
            raise AssertionError('MDL visibility must cover actual converted pixels')
        if not expected.any():
            raise AssertionError('converted MDL unexpectedly became empty')
        total['variantCount'] += 1
        total['storageTexelCount'] += int(expected.size)
        total['storageOpaqueTexelCount'] += metrics['opaquePixels']
        total['masterTexelCount'] += int(master.size)
        for field in ('projectedOpaqueArea', 'alphaSquaredError', 'tinyCoverageFallback'):
            total[field] += metrics[field]
    return dict(schema=CONVERSION_VERSION, **total, coverageThreshold=.5, contrast=.5,
                visibility='actual converted opaque cells', sourcePaletteOnly=True,
                emptyStorageRasterCount=0, alphaMSE=total['alphaSquaredError']/max(total['storageTexelCount'], 1))
