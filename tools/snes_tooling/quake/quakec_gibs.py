"""Stock overkill callbacks and fixed-point bindings for E1M1."""
from snes_tooling.quake.quakec_grunt import GRUNT_SLOT, GruntReference

MODELS = ("progs/h_guard.mdl", "progs/h_dog.mdl", "progs/gib1.mdl", "progs/gib2.mdl", "progs/gib3.mdl")
DEATH_SOUND = "player/udeath.wav"

# Edict positions, linear velocity and angular velocity use signed Q3.
# Scalar damage, random fractions, time and the three damage multipliers stay Q6.
OPERANDS = {
    (7964, 0): 100 * 8, (7967, 0): 100 * 8, (7970, 0): 100 * 8, (7971, 0): 200 * 8,
    (8009, 1): 600 * 8, (8013, 1): 600 * 8, (8017, 1): 600 * 8,
    (8059, 1): 24 * 8, (8064, 1): 512,
}
GLOBAL_WORDS = {5229: 8 * 8, 5245: 600 * 8}

class OverkillOracle(GruntReference):
    """Give each original spawn() a different edict, as the Quake server does."""

    def builtin(self, number, name):
        if name == "spawn":
            self.drop_slot += 1
        return super().builtin(number, name)


def trace_death(program, models, archive, name, health, random):
    vm = OverkillOracle(program, models, archive, lambda origin, mins: origin)
    for slot in (0, 1, GRUNT_SLOT):
        vm.add(slot, {})
    vm.drop_slot = GRUNT_SLOT
    vm.t = 20
    vm.forced_random = random
    vm.set(GRUNT_SLOT, "origin", (100, 200, 40))
    vm.set(GRUNT_SLOT, "health", health)
    vm.event(GRUNT_SLOT, name)
    return vm


def cover_overkill(trace, program, models, archive):
    contracts = []
    for name, head, fragments in (
        ("army_die", MODELS[0], MODELS[2:]), ("dog_die", MODELS[1], (MODELS[4],) * 3),
    ):
        for health in (-36, -50, -199, -200):
            vm = trace_death(program, models, archive, name, health, 0.75)
            pieces = range(GRUNT_SLOT, GRUNT_SLOT + 4)
            if tuple(vm.get(i, "model") for i in pieces) != (head, *fragments):
                raise ValueError("stock overkill models changed")
            if vm.events[-1][3] != DEATH_SOUND or "DropBackpack" in vm.stats:
                raise ValueError("stock overkill sound or inventory changed")
            trace.pcs.update(vm.pcs)
            trace.stats.update(vm.stats)
            trace.builtins.update(vm.builtins)
        contracts.append(dict(function=name, head=head, fragments=list(fragments), sound=DEATH_SOUND))
    return contracts
