"""Stock shotgun coverage and cartridge ABI for the E1M1 gameplay slice."""

from random import Random

from snes_tooling.quake.quakec_reference import ReferenceVM, asf, asi


SHOT_FIELDS = (
    "absmin", "size", "v_angle", "weapon", "ammo_shells", "currentammo",
    "attack_finished", "button0", "impulse", "super_damage_finished",
    "effects", "weaponframe", "punchangle",
)
SHOT_GLOBALS = {
    "FORWARD": 59, "RIGHT": 65, "UP": 62, "TRACE_FRACTION": 70,
    "TRACE_ENDPOS": 71, "TRACE_NORMAL": 74, "TRACE_ENT": 78,
}
# Statement and operand indexes refer to hash-verified progs.dat. The ray
# position operands are in units of eight Quake units (Q3 world precision);
# directions and ordinary scalar operands retain the VM's Q6 ABI. Quake's
# aim builtin does not use its speed argument.
SHOT_OPERANDS = {
    (3694, 0): 0, (3642, 1): 10 / 8, (3663, 1): 2048 / 8, (3608, 1): 4 / 8,
}


class ShotgunReference(ReferenceVM):
    """Cover stock control flow with deterministic hits and misses at the host ABI."""

    def __init__(self, program, models):
        super().__init__(program, models)
        self.rng = Random(810)
        self.rays = []
        self.effect = []

    def builtin(self, builtin_id, name):
        g = self.g
        if name == "aim":
            self.builtins[name, builtin_id] += 1
            g[1:4] = g[59:62]
        elif name == "random":
            self.builtins[name, builtin_id] += 1
            g[1] = asi(self.rng.random())
        elif name == "traceline":
            self.builtins[name, builtin_id] += 1
            start, end = (tuple(map(asf, g[i:i + 3])) for i in (4, 7))
            fraction = 0.25 if len(self.rays) % 2 == 0 else 1
            self.rays.append((start, end, fraction))
            g[70] = asi(fraction)
            g[71:74] = [asi(a + (b - a) * fraction) for a, b in zip(start, end, strict=True)]
            g[74:77] = [0, 0, asi(1)]
            g[78] = 0
        elif name in ("WriteByte", "WriteCoord"):
            self.builtins[name, builtin_id] += 1
            self.effect.append((name, asf(g[7])))
        else:
            super().builtin(builtin_id, name)

    def cover_shotgun(self, spawn):
        spawn.event(1, "SetNewParms")
        spawn.event(1, "DecodeLevelParms")
        initial = spawn.get(1, "ammo_shells")
        spawn.set(1, "currentammo", initial)
        self.e[1] = spawn.e[1].copy()
        self.s.update(spawn.s)
        self.set(1, "size", (32, 32, 56))
        self.set(1, "absmin", (-17, -17, -25))
        self.set(1, "button0", 1)
        self.t = 0
        self.event(1, "W_WeaponFrame")
        self.t = 0.49
        self.event(1, "W_WeaponFrame")
        if self.get(1, "ammo_shells") != initial - 1:
            raise ValueError("stock shotgun did not consume one shell or obey its cooldown")
        if len(self.rays) != 6 or len(self.effect) != 15:
            raise ValueError("stock shotgun trace and impact coverage changed")
        if self.get(1, "weaponframe") != 1 or self.get(1, "attack_finished") != 0.5:
            raise ValueError("stock shotgun recoil or cooldown changed")
        # Derive the view sequence without adding presentation callbacks to
        # the cartridge VM slice. The weapon's appearance has no world side
        # effects and only needs its frame at the moment of composition.
        view = ReferenceVM(self.program, self.models)
        view.e[1] = self.e[1].copy()
        sequence = []
        for _ in range(8):
            frame = view.get(1, "weaponframe")
            sequence.append((round(view.t * 60), int(frame)))
            if frame == 0:
                break
            view.t = view.get(1, "nextthink")
            view.event(1, "think")
        if sequence[-1][1] != 0 or any(a[0] >= b[0] for a, b in zip(sequence, sequence[1:])):
            raise ValueError("stock shotgun view sequence did not return to idle")
        return dict(startingShells=initial, pellets=len(self.rays), cooldownSeconds=0.5,
                    shotSound="weapons/guncock.wav", worldImpactEvents=len(self.effect) // 5,
                    viewSequence=sequence)
