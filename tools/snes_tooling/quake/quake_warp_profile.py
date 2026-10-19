"""Compile a movable three-knot depth profile to the existing integer recurrences."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DepthProfile:
    depths: tuple[int, int, int] = (213, 205, 437)
    middle_y_q1: int = 223

    def __post_init__(self):
        if len(self.depths) != 3 or any(type(v) is not int or not 0 <= v <= 1024 for v in self.depths):
            raise ValueError('three integer inverse depths in Q16 0..1024 required')
        # Keeps every multiplier signed-16 and every arithmetic shift >=9.
        if type(self.middle_y_q1) is not int or not 57 <= self.middle_y_q1 <= 389:
            raise ValueError('middle anchor must be a half-row in 28.5..194.5')

    def coefficients(self, bands=32):
        if bands not in (16, 32):
            raise ValueError('only 16/32-band recurrences are supported')
        # Retain the already-qualified integer constants at the original knot.
        # Its step was rounded upward (16458), rather than nearest (16457).
        if self.middle_y_q1 == 223:
            return {'split': bands//2, 'leftStart': (28213, 12 if bands == 32 else 11),
                    'leftStep': (16458, 10 if bands == 32 else 9),
                    'rightStart': (16458 if bands == 32 else 30564, 11),
                    'rightStep': (16458, 10 if bands == 32 else 9)}
        ys = tuple((3 if bands == 32 else 6)+(224//bands)*i for i in range(bands))
        middle = self.middle_y_q1 / 2
        split = next(i for i, y in enumerate(ys) if y >= middle)

        def coefficient(fraction, max_shift):
            shift = max_shift
            while round(fraction * 256 * (1 << shift)) > 32767:
                shift -= 1
            if shift < 9:
                raise ValueError('profile requires an unsupported recurrence shift')
            return round(fraction * 256 * (1 << shift)), shift

        stride = 224 / bands
        return {
            'split': split,
            'leftStart': coefficient(ys[0]/middle, 12),
            'leftStep': coefficient(stride/middle, 10),
            'rightStart': coefficient((ys[split]-middle)/(223-middle), 11),
            'rightStep': coefficient(stride/(223-middle), 10),
        }

    def record(self):
        return {'inverseDepthQ16': list(self.depths), 'middleYQ1': self.middle_y_q1,
                'outerRows': [0, 223], 'coefficients': self.coefficients()}

    @classmethod
    def from_record(cls, value):
        return cls(tuple(value['inverseDepthQ16']), value['middleYQ1'])

    def assembly(self):
        lines = ['; Generated integer profile; no runtime fitting or divisions.']
        for i, q in enumerate(self.depths):
            lines.append(f'WARP_DEPTH_{i}_Q10 = {q*4}')
        for name, value in self.coefficients().items():
            if name == 'split':
                lines.append(f'WARP_DEPTH_SPLIT = {value*2}')
            else:
                lines.extend((f'WARP_DEPTH_{name.upper()} = {value[0]}',
                              f'WARP_DEPTH_{name.upper()}_SHIFT = {value[1]}'))
        return '\n'.join(lines)+'\n'
