"""Four shared demo-camera gains, baked into integer toroidal OBJ phases.

Angles use pixels per turn; translations use pixels per 128 Quake units.
Only the camera track constructs features. Image targets never enter them.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib

import numpy as np

from snes_tooling.quake.quake_snes_hdma import sin
from snes_tooling.quake.quake_joint_ranges import BACKGROUND_GAINS, inclusive_bounds

GAIN_NAMES = ('yaw', 'pitch', 'strafe', 'elevation')
GAIN_BOUNDS = tuple(map(inclusive_bounds, BACKGROUND_GAINS))
YY, XX = np.indices((224, 256))


@dataclass(frozen=True)
class MotionProfile:
    gains: tuple[int, int, int, int] = (0, 0, 0, 0)

    def __post_init__(self):
        if len(self.gains) != 4 or any(type(g) is not int or not lo <= g <= hi
                                      for g, (lo, hi, _) in zip(self.gains, GAIN_BOUNDS)):
            raise ValueError('four bounded integer background motion gains required')

    @classmethod
    def from_record(cls, model):
        return cls(tuple(model.get('backgroundMotion', {}).get('gains', (0, 0, 0, 0))))

    def record(self):
        return {'backgroundMotion': {'schema': 'quake-background-motion-v1', 'gains': list(self.gains),
                'order': list(GAIN_NAMES), 'angleUnits': 'pixels per turn',
                'translationUnits': 'pixels per 128 Quake units',
                'rounding': 'floor Q16 then modulo 64', 'initialPhase': [0, 0]}}

    def phases(self, features):
        f = np.asarray(features, dtype=np.int64)
        if f.shape[-1] != 4:
            raise ValueError('four Q16 camera features required')
        x = f[..., 0]*self.gains[0]+f[..., 2]*self.gains[2]
        y = f[..., 1]*self.gains[1]+f[..., 3]*self.gains[3]
        return np.stack((x >> 16, y >> 16), axis=-1) % 64


def camera_features(track, pairs=()):
    """Integrate screen-right displacement, unwrap angles, and anchor pose zero.

    The recorded track contains Q3 world positions, yaw and negated pitch.
    Midpoint yaw projects each displacement onto the camera's screen-right
    axis. A replay loop deterministically restarts the same phase table.
    """
    raw = np.frombuffer(track, dtype='<i2').reshape(-1, 5).astype(np.int64)
    if len(raw) < 2:
        raise ValueError('a complete recorded camera track is required')
    angles = raw[:, 3:].copy()
    angles[:, 1] *= -1
    delta = (np.diff(angles, axis=0)+32768) % 65536-32768
    unwrapped = np.vstack((np.zeros((1, 2), dtype=np.int64), np.cumsum(delta, axis=0)))
    midpoint = (angles[:-1, 0]+delta[:, 0]//2) % 65536
    sy = np.array([sin(int(v)) for v in midpoint], dtype=np.int64)
    cy = np.array([sin(int(v)+16384) for v in midpoint], dtype=np.int64)
    displacement = np.diff(raw[:, :3], axis=0)
    right = np.r_[0, np.cumsum(-sy*displacement[:, 0]+cy*displacement[:, 1])]
    features = np.column_stack((unwrapped, right >> 6, (raw[:, 2]-raw[0, 2])*64))
    origin = None
    for pair in pairs:
        pose = pair['targetPose']
        if not 0 <= pose < len(raw):
            raise ValueError('pair target pose outside the bound motion track')
        native = np.asarray(pair['targetNativeCamera'], dtype=np.int64)
        offset = (raw[pose, :3]*2-native[:3]) % 65536
        if origin is None:
            origin = offset
        if (not np.array_equal(offset, origin)
                or not np.array_equal(angles[pose] % 65536, native[3:] % 65536)):
            raise ValueError('motion track differs from the captured presentation camera')
    return features.astype('<i8')


def texel_map(phase):
    x, y = map(int, phase)
    return ((YY-y) % 64)*64+(XX-x) % 64


def oam_bytes(phase=(0, 0), palette=5):
    """5 columns x 4 vertically wrapping rows; first column always has X9 set.

    Keeping X in -64..255 avoids the hardware's X=-256 evaluation erratum.
    The five high-table bytes are constant, so motion uploads just 80 bytes.
    """
    px, py = map(int, phase)
    if not 0 <= px < 64 or not 0 <= py < 64 or not 0 <= palette < 8:
        raise ValueError('six-bit phases and a valid OBJ palette required')
    data = bytearray(bytes((0, 240, 0, 0))*128+bytes(32))
    for i in range(20):
        row, col = divmod(i, 5)
        x, y = px-64+col*64, py+row*64
        data[i*4:i*4+4] = bytes((x & 255, y, 0, palette*2))
        data[512+i//4] |= (2+int(x < 0)) << (2*(i % 4))
    return bytes(data)


def motion_assets(model, track):
    features = camera_features(track)
    motion = MotionProfile.from_record(model)
    phases = motion.phases(features).astype(np.uint8)
    return phases.tobytes(), {'trackSha256': hashlib.sha256(track).hexdigest(),
                             'featureSha256': hashlib.sha256(features.tobytes()).hexdigest(),
                             'poses': len(phases), 'tableBytes': phases.size, 'oamBytesPerPhaseChange': 80,
                             **motion.record()}
