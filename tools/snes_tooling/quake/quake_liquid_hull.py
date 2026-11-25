"""Compile the E1M1 world BSP into a small point-contents tree for player fluids."""

from functools import lru_cache
from struct import iter_unpack, pack

from snes_tooling.quake.quake_bsp_assets import lump_data, lump_ranges


def liquid_hull(bsp, world_origin):
    lumps = lump_ranges(bsp)
    leaves = tuple(iter_unpack("<ii6h2H4B", lump_data(bsp, lumps, 10)))
    nodes = tuple(iter_unpack("<ihh6h2H", lump_data(bsp, lumps, 5)))
    planes = tuple(iter_unpack("<4fi", lump_data(bsp, lumps, 1)))
    root = next(iter_unpack("<9f7i", lump_data(bsp, lumps, 14)))[9]
    records = []
    intern = {}

    @lru_cache(None)
    def visit(node):
        if node < 0:
            contents = leaves[~node][0]
            if contents not in (-1, -2, -3, -4):
                raise ValueError(f"unsupported E1M1 contents {contents}")
            return contents
        plane, front, back = nodes[node][:3]
        front, back = visit(front), visit(back)
        # Feet, waist and eyes are inside the valid player hull. Solid leaves
        # never supply a liquid type, so their adjacent child can own this side.
        if front == back or back == -2:
            return front
        if front == -2:
            return back
        x, y, z, distance, _ = planes[plane]
        unit = min(abs(n) for n in (x, y, z) if n)
        normal = tuple(round(n / unit) for n in (x, y, z))
        axial_distance = round(distance / unit)
        if (any(abs(n / unit - i) > 1e-5 for n, i in zip((x, y, z), normal))
                or abs(distance / unit - axial_distance) > 0.001):
            raise ValueError("liquid BSP plane is not representable on the stock integer grid")
        local = 16 * (axial_distance - sum(n * pos for n, pos in zip(normal, world_origin)))
        row = (*normal, local, front, back)
        if row not in intern:
            intern[row] = len(records)
            records.append(row)
        return intern[row]

    start = visit(root)
    ceiling = max(row[7] for row in leaves if row[0] in (-3, -4))
    data = bytearray()
    for nx, ny, nz, distance, front, back in records:
        axis = {(1, 0, 0): 0, (0, 1, 0): 2, (0, 0, 1): 4}.get((nx, ny, nz), 6)
        if axis < 6:
            if not -32768 <= distance <= 32767:
                raise ValueError("axial liquid plane exceeds signed Q4")
            distance = (distance & 65535) ^ 32768
        data.extend(pack("<hhHhhhi", front * 16 if front >= 0 else front,
                         back * 16 if back >= 0 else back, axis, nx, ny, nz, distance))
    return dict(root=start, ceilingQ4=(ceiling - world_origin[2]) * 16, nodes=records), bytes(data)
