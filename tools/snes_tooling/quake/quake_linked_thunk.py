"""Validate declared GSU operands against actual ld65 segment outputs."""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import time

from snes_tooling.shared.ld65_debug import load_debug_records, parse_debug_int


class _LinkedOutputs:
    """Resolve exact declarations and cache each stored output once per check."""
    def __init__(self, debug_path):
        self.path = Path(debug_path).resolve()
        self.records = load_debug_records(self.path)
        self.segments = {parse_debug_int(row['id']): row
                         for row in self.records.get('seg', ())}
        self.cache = {}

    def symbol(self, name):
        rows = [row for row in self.records.get('sym', ())
                if row.get('name') == name and 'val' in row and 'seg' in row]
        identities = {(parse_debug_int(row['val']), parse_debug_int(row['seg']))
                      for row in rows}
        if len(identities) != 1:
            raise ValueError(f'linked GSU thunk requires one declared symbol: {name}')
        address, owner = next(iter(identities))
        if owner not in self.segments:
            raise ValueError('linked GSU thunk references a missing segment')
        segment = self.segments[owner]
        start = parse_debug_int(segment['start'])
        if not start <= address < start + parse_debug_int(segment['size']):
            raise ValueError('linked GSU thunk target escapes its declared segment')
        return address, segment

    def read(self, name, size, *, relative=0):
        address, segment = self.symbol(name)
        if not all(key in segment for key in ('start', 'size', 'oname', 'ooffs')):
            raise ValueError('linked GSU thunk segment has no stored output')
        offset = address + relative - parse_debug_int(segment['start'])
        if not 0 <= offset <= parse_debug_int(segment['size']) - size:
            raise ValueError('linked GSU thunk escapes its declared segment')
        output = Path(segment['oname'])
        output = (output if output.is_absolute() else self.path.parent / output).resolve()
        file_offset = parse_debug_int(segment['ooffs']) + offset
        if file_offset < 0:
            raise ValueError('linked GSU thunk output offset is negative')
        if output not in self.cache:
            self.cache[output] = output.read_bytes()
        actual = self.cache[output][file_offset:file_offset + size]
        if len(actual) != size:
            raise ValueError('linked GSU thunk output file is truncated')
        return actual, dict(output=str(output), outputOffset=file_offset,
            instructionBytes=actual.hex(), instructionSha256=sha256(actual).hexdigest())


def _rom_pointer(address):
    bank, word = address >> 16, address & 65535
    if 0x80 <= bank < 0xC0 and word >= 0x8000:
        bank &= 127
    elif not 0x60 <= bank < 0x70:
        raise ValueError('linked GSU thunk target is not executable ROM')
    return bank, word


def validate_world_frustum_thunk(debug_path: Path) -> dict:
    """Check the established R1/R12 LJMP ABI using its linked target bank."""
    started = time.monotonic()
    linked = _LinkedOutputs(debug_path)
    thunk, _ = linked.symbol('TextureWorldFrustumProbeROM')
    target, _ = linked.symbol('TextureWorldFrustumROM')
    bank, address = _rom_pointer(target)
    expected = bytes((0xF1, address & 255, address >> 8, 0xAC, bank,
                      0xB1, 0x3D, 0x9C, 0x01))
    actual, evidence = linked.read('TextureWorldFrustumProbeROM', len(expected))
    if actual[:4] == expected[:4] and actual[5:] == expected[5:] and actual[4] != bank:
        raise ValueError('TextureWorldFrustumProbeROM bank mismatch: '
                         f'expected {bank:02X}, actual {actual[4]:02X}')
    if actual != expected:
        raise ValueError('TextureWorldFrustumProbeROM instruction/target mismatch: '
                         f'expected {expected.hex()}, actual {actual.hex()}')
    return dict(passed=True, thunk='TextureWorldFrustumProbeROM',
        target='TextureWorldFrustumROM', thunkAddress=thunk, targetAddress=target,
        targetGsuBank=bank, **evidence,
        elapsedSeconds=round(time.monotonic() - started, 3))


def validate_world_vertex_pointer(debug_path: Path) -> dict:
    """Check the shared selector decoder's actual bank/base in X2 and F3.

    Each declared PacketProjectWorldVertex owns a fixed decoder ABI at +10:
    IWT R4,#base; WITH R4; ADD R1; IBT R0,#bank; ALT3; ROMB. Derive the
    expected pointer from QuakeBSPWorldVertices, including a nonzero high-bank
    base. The shared macro serves normal and F3 selectors; check both outputs.
    """
    started = time.monotonic()
    linked = _LinkedOutputs(debug_path)
    target, _ = linked.symbol('QuakeBSPWorldVertices')
    bank, address = _rom_pointer(target)
    expected = bytes((0xF4, address & 255, address >> 8, 0x24, 0x51,
                      0xA0, bank, 0x3F, 0xDF))
    consumers = []
    names = ['PacketProjectWorldVertex']
    if any(row.get('name') == 'F3_PacketProjectWorldVertex'
           for row in linked.records.get('sym', ())):
        names.append('F3_PacketProjectWorldVertex')
    for name in names:
        source, _ = linked.symbol(name)
        actual, evidence = linked.read(name, len(expected), relative=10)
        if actual != expected:
            raise ValueError(f'{name} vertex pointer mismatch: '
                f'expected {bank:02X}:{address:04X} ({expected.hex()}), '
                f'actual {actual[6]:02X}:{int.from_bytes(actual[1:3], "little"):04X} ({actual.hex()})')
        consumers.append(dict(symbol=name, consumerAddress=source,
            pointerOperandOffset=10, **evidence))
    return dict(passed=True, target='QuakeBSPWorldVertices', targetAddress=target,
        targetGsuBank=bank, targetGsuAddress=address, consumers=consumers,
        elapsedSeconds=round(time.monotonic() - started, 3))
