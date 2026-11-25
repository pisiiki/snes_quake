"""Pack shared visibility rows without occupying the directory's ROM tail."""
from __future__ import annotations

import struct


def pack_rows(rows, *, guard_bytes, first_bank=0x10, bank_count=4, directory_bank=2):
    """Preserve the native eight-byte directory and existing row codec.

    The directory and guards share the tail of directory_bank. Reserve that
    space before allocating any row; later banks remain available. Identical
    encoded rows share immutable bytes, with their directory metadata intact.
    """
    rows = tuple(rows)
    if not rows:
        raise ValueError('visibility requires at least the solid fallback row')
    if (type(guard_bytes) is not int or guard_bytes < 0
            or type(first_bank) is not int or not 0 <= first_bank <= 255
            or type(bank_count) is not int or bank_count < 1
            or first_bank + bank_count > 256
            or type(directory_bank) is not int or not 0 <= directory_bank < bank_count):
        raise ValueError('invalid visibility bank/directory reservation')
    bank_bytes = 32768
    directory_bytes = len(rows) * 8
    tail_start = ((bank_bytes - directory_bytes - guard_bytes) // 8) * 8
    if tail_start < 0:
        raise ValueError('visibility directory and guards exceed one ROM bank')
    capacities = [bank_bytes] * bank_count
    capacities[directory_bank] = tail_start
    chunks = [bytearray() for _ in range(bank_count)]
    directory, shared = bytearray(), {}
    bank = input_bytes = 0
    for encoded, face_count in rows:
        if (type(encoded) is not bytes or not 0 < len(encoded) <= bank_bytes
                or type(face_count) is not int or not 0 <= face_count <= 65535):
            raise ValueError('invalid encoded visibility row or face count')
        input_bytes += len(encoded)
        key = (encoded, face_count)
        if key not in shared:
            while bank < bank_count and len(chunks[bank]) + len(encoded) > capacities[bank]:
                bank += 1
            if bank == bank_count:
                raise ValueError('visibility payload exceeds reserved ROM banks')
            shared[key] = (bank, len(chunks[bank]))
            chunks[bank].extend(encoded)
        row_bank, offset = shared[key]
        directory.extend(struct.pack('<HHHBB', 0x8000 + offset, len(encoded),
                                     face_count, first_bank + row_bank, 0))
    directory_address = 0x8000 + ((len(chunks[directory_bank]) + 7) & ~7)
    guard_address = directory_address + directory_bytes
    if guard_address + guard_bytes > 0x10000:
        raise AssertionError('reserved visibility directory tail was overwritten')
    return dict(chunks=tuple(bytes(c) for c in chunks), directory=bytes(directory),
        directoryAddress=directory_address, guardAddress=guard_address,
        chunkCount=max(i + 1 for i, chunk in enumerate(chunks) if chunk),
        rowCount=len(rows), uniqueRows=len(shared), encodedBytes=sum(map(len, chunks)),
        savedBytes=input_bytes - sum(map(len, chunks)))
