"""Host oracle for the original E1M1 button and door callback slice."""
from collections import Counter
from math import ceil, cos, pi, sin, sqrt
import operator
from struct import pack, unpack_from

# Opcode numbers are from Quake's version-6 pr_comp.h.
_SCALAR_OPS = {
    1: operator.mul, 5: operator.truediv, 6: operator.add, 8: operator.sub,
    10: operator.eq, 15: operator.ne, 20: operator.le, 21: operator.ge,
    22: operator.lt, 23: operator.gt, 62: lambda x, y: bool(x and y),
    63: lambda x, y: bool(x or y), 64: lambda x, y: int(x) & int(y),
    65: lambda x, y: int(x) | int(y),
}


def asf(x):
    return unpack_from('<f', pack('<I', x))[0]

def asi(x):
    return unpack_from('<I', pack('<f', x))[0]

class ReferenceVM:
    """Execute stock spawn and lifecycle callbacks with an isolated host world."""

    def __init__(self, program, models):
        self.program = program
        self.models = models
        self.g = list(program.initial)
        self.e = {}
        self.s = {}
        self.events = []
        self.stats = Counter()
        self.pcs = set()
        self.statement_count = 0
        self.builtins = Counter()
        self.t = 0
        self.pusher_slots = (2, 3)

    def key(self, n):
        x = self.program.strings.find(n.encode() + bytes(1))
        if x >= 0:
            return x
        for x, y in self.s.items():
            if y == n:
                return x
        x = len(self.program.strings) + len(self.s)
        self.s[x] = n
        return x

    def string(self, x):
        return self.s[x] if x in self.s else self.program.string(x)

    def get(self, i, n):
        t, a = self.program.fields[n]
        e = self.e[i]
        if t == 3:
            return tuple((asf(x) for x in e[a:a + 3]))
        x = e[a]
        return asf(x) if t == 2 else self.string(x) if t == 1 else x

    def set(self, i, n, v):
        t, a = self.program.fields[n]
        e = self.e[i]
        if t == 3:
            e[a:a + 3] = map(asi, v)
        else:
            e[a] = asi(v) if t == 2 else self.key(v) if t == 1 else v

    def add(self, i, d):
        self.e[i] = [0] * self.program.entity_fields
        for n, v in d.items():
            if n == 'angle':
                self.set(i, 'angles', (0, float(v), 0))
                continue
            t, _ = self.program.fields[n]
            self.set(i, n, float(v) if t == 2 else v)

    def link(self, i):
        org = self.get(i, 'origin')
        lo = self.get(i, 'mins')
        hi = self.get(i, 'maxs')
        self.set(i, 'absmin', (x + y - 1 for x, y in zip(org, lo)))
        self.set(i, 'absmax', (x + y + 1 for x, y in zip(org, hi)))

    def builtin(self, builtin_id, n):
        g = self.g
        self.builtins[n, builtin_id] += 1
        if n == 'makevectors':
            x, y, z = (asf(asi(asf(v) * pi / 180)) for v in g[4:7])
            cp, sp = cos(x), sin(x)
            cy, sy = cos(y), sin(y)
            cr, sr = cos(z), sin(z)
            vectors = (
                (cp * cy, cp * sy, -sp),
                (cr * sy - sr * sp * cy, -cr * cy - sr * sp * sy, -sr * cp),
                (cr * sp * cy + sr * sy, cr * sp * sy - sr * cy, cr * cp),
            )
            for name, v in zip(("v_forward", "v_right", "v_up"), vectors, strict=True):
                a = self.program.globals[name]
                g[a:a + 3] = map(asi, v)
        elif n == 'setorigin':
            self.e[g[4]][10:13] = g[7:10]
            self.link(g[4])
        elif n == 'setmodel':
            i = g[4]
            m = self.string(g[7])
            j = int(m[1:])
            mod = self.models[j]
            lo = [x - 1 for x in mod[:3]]
            hi = [x + 1 for x in mod[3:6]]
            self.set(i, 'model', m)
            self.set(i, 'modelindex', j + 1)
            self.set(i, 'mins', lo)
            self.set(i, 'maxs', hi)
            self.set(i, 'size', (y - x for x, y in zip(lo, hi)))
            self.link(i)
        elif n == 'vlen':
            g[1] = asi(sqrt(sum((asf(x) ** 2 for x in g[4:7]))))
        elif n == 'fabs':
            g[1] = g[4] & 2147483647
        elif n == 'precache_sound':
            g[1] = g[4]
            self.events.append(('precache', self.string(g[4])))
        elif n == 'sound':
            self.events.append(('sound', g[4], asf(g[7]), self.string(g[10]), asf(g[13]), asf(g[16])))
        elif n == 'lightstyle':
            self.events.append(('lightstyle', int(asf(g[4])), self.string(g[7])))
        elif n == 'find':
            x = g[4]
            a = g[7]
            sought = self.string(g[10])
            g[1] = next((i for i in sorted(self.e) if i > x and self.e[i][a] and (self.string(self.e[i][a]) == sought)), 0)
        elif n == 'ceil':
            g[1] = asi(ceil(asf(g[4])))
        elif n == 'normalize':
            v = [asf(x) for x in g[4:7]]
            mag = sqrt(sum((x * x for x in v)))
            g[1:4] = map(asi, [x / mag for x in v] if mag else v)
        else:
            raise ValueError('builtin', n, builtin_id)

    def exec(self, function_id):
        g = self.g
        pc, start, nloc, _, _, _, nparms, *widths = self.program.functions[function_id]
        n = self.program.names[function_id]
        self.stats[n] += 1
        if pc < 0:
            return self.builtin(-pc, n)
        old = g[start:start + nloc]
        p = start
        for j, z in enumerate(widths[:nparms]):
            g[p:p + z] = g[4 + j * 3:4 + j * 3 + z]
            p += z
        try:
            while True:
                o, a, b, c = self.program.statements[pc]
                self.pcs.add(pc)
                self.statement_count += 1
                if o in (0, 43):
                    g[1:4] = g[a:a + 3]
                    return
                if o == 61:
                    pc += a
                    continue
                if o in (49, 50):
                    pc += b if bool(g[a]) == (o == 49) else 1
                    continue
                if 51 <= o <= 59:
                    self.exec(g[a])
                elif o == 60:  # STATE: schedule the next animation callback.
                    i = g[28]
                    self.set(i, 'frame', asf(g[a]))
                    self.set(i, 'nextthink', asf(g[31]) + 0.1)
                    self.set(i, 'think', g[b])
                elif o in _SCALAR_OPS:
                    x = asf(g[a])
                    y = asf(g[b])
                    g[c] = asi(_SCALAR_OPS[o](x, y))
                elif o in (2, 3, 4, 7, 9, 11, 16):
                    x = list(map(asf, g[a:a + 3]))
                    y = list(map(asf, g[b:b + 3]))
                    if o == 2:
                        g[c] = asi(sum((asf(asi(p * q)) for p, q in zip(x, y))))
                    elif o in (11, 16):
                        g[c] = asi((x == y) == (o == 11))
                    elif o in (3, 4):
                        g[c:c + 3] = map(asi, [x[0] * q for q in y] if o == 3 else [p * y[0] for p in x])
                    else:
                        g[c:c + 3] = map(asi, [p + q if o == 7 else p - q for p, q in zip(x, y)])
                elif o in (12, 17):
                    g[c] = asi((self.string(g[a]) == self.string(g[b])) == (o == 12))
                elif o in (13, 14, 18, 19):
                    g[c] = asi((g[a] == g[b]) == (o in (13, 14)))
                elif 24 <= o <= 29:
                    f = g[b]
                    z = 3 if o == 25 else 1
                    g[c:c + z] = self.e[g[a]][f:f + z]
                elif o == 30:
                    g[c] = g[a] * 256 + g[b]
                elif 31 <= o <= 36:
                    z = 3 if o == 32 else 1
                    g[b:b + z] = g[a:a + z]
                elif 37 <= o <= 42:
                    i, f = divmod(g[b], 256)
                    z = 3 if o == 38 else 1
                    self.e[i][f:f + z] = g[a:a + z]
                elif 44 <= o <= 48:
                    result = {44: lambda: not asf(g[a]), 45: lambda: not any(map(asf, g[a:a + 3])), 46: lambda: not self.string(g[a]), 47: lambda: not g[a], 48: lambda: not g[a]}[o]()
                    g[c] = asi(result)
                else:
                    raise ValueError(pc, o, n)
                pc += 1
        finally:
            g[start:start + nloc] = old

    def event(self, i, f, other=0):
        self.g[28:32] = [i, other, 0, asi(self.t)]
        return self.exec(self.get(i, f) if f in self.program.fields else self.program.function_ids[f])

    def step(self, dt, block=False, *, blocked_actor=None):
        for i in self.pusher_slots:
            old = self.get(i, 'ltime')
            nt = self.get(i, 'nextthink')
            mov = max(0, min(dt, nt - old))
            v = self.get(i, 'velocity')
            if ((block and i == 2) or blocked_actor == i) and mov and any(v):
                self.event(i, 'blocked', 1)
                continue
            self.set(i, 'origin', [x + y * mov for x, y in zip(self.get(i, 'origin'), v)])
            self.set(i, 'ltime', old + mov)
            self.link(i)
            if old < nt <= self.get(i, 'ltime'):
                self.set(i, 'nextthink', 0)
                self.event(i, 'think')
        self.t += dt
