"""Exercise stock dog callbacks before packing reachable QuakeC bytecode."""
from snes_tooling.quake.quakec_reference import asf, asi


def cover_dog(vm, spawn, dog):
    edicts = {slot: cells.copy() for slot, cells in spawn.e.items()}
    globals_ = spawn.g.copy()
    saved = (vm.e, vm.g, vm.t, vm.client, vm.combat, vm.visible, vm.hits,
             vm.forced_random, vm.rng.getstate())

    def reset(distance, height, random):
        vm.e = {slot: cells.copy() for slot, cells in edicts.items()}
        vm.g = globals_.copy()
        vm.t = 5
        vm.client, vm.combat = 1, True
        vm.visible = vm.hits = True
        vm.forced_random = random
        vm.set(dog, "origin", (0, 0, 0))
        vm.set(1, "origin", (distance, 0, height))
        vm.set(dog, "angles", (0, 0, 0))
        vm.link(dog)
        vm.link(1)

    def animate(name, count):
        vm.event(dog, name)
        for _ in range(count - 1):
            vm.t = vm.get(dog, "nextthink")
            vm.event(dog, "think")

    try:
        # FacingIdeal can compare wrapped headings on either side of north.
        for angle in (-1, 361):
            vm.g[4] = asi(angle)
            vm.event(dog, "anglemod")
        reset(96, 0, 0.1)
        vm.set(dog, "ideal_yaw", 90)
        vm.event(dog, "FacingIdeal")
        for distance, height in ((40, 0), (96, 0), (150, 45), (190, 0), (96, -100), (96, 100)):
            reset(distance, height, 0.1)
            vm.event(dog, "FindTarget")
            vm.set(dog, "enemy", 1)
            vm.set(dog, "goalentity", 1)
            for frame in range(1, 13):
                vm.event(dog, f"dog_run{frame}")
            vm.event(dog, "DogCheckAttack")

        # A bite may already be scheduled when its target runs out of reach.
        reset(180, 0, 0.1)
        vm.set(dog, "enemy", 1)
        vm.event(dog, "dog_bite")
        vm.set(dog, "enemy", 0)
        vm.event(dog, "dog_bite")

        reset(40, 0, 0.1)
        vm.set(dog, "enemy", 1)
        vm.event(dog, "CheckDogJump")
        # When the center ray is blocked, CanDamage tries four corner rays.
        for blocked in range(1, 6):
            vm.g[4], vm.g[7] = 1, dog
            vm.trace_visibility = iter([False] * blocked + [True])
            vm.event(dog, "CanDamage")
            if bool(asf(vm.g[1])) != (blocked < 5):
                raise ValueError("stock dog bite corner trace result changed")
        vm.trace_visibility = iter([False] * 5)
        vm.event(dog, "dog_bite")
        vm.trace_visibility = None
        vm.set(dog, "health", 0)
        vm.event(dog, "Dog_JumpTouch", 1)

        reset(40, 0, 0.1)
        vm.visible = False
        animate("dog_stand1", 9)
        animate("dog_walk1", 8)
        for phase, count in (("stand", 9), ("walk", 8)):
            if any(f"dog_{phase}{frame}" not in vm.stats for frame in range(1, count + 1)):
                raise ValueError(f"stock dog {phase} animation was interrupted")
        vm.visible = True
        vm.set(dog, "enemy", 1)
        vm.set(dog, "goalentity", 1)
        animate("dog_atta1", 8)
        if vm.get(1, "health") >= 100:
            raise ValueError("stock dog bite did not damage the player")
        animate("dog_leap1", 9)
        vm.check_bottom = False
        vm.event(dog, "touch", 1)
        vm.set(dog, "flags", 8 | 512)
        vm.event(dog, "touch", 0)
        vm.check_bottom = True
        vm.event(dog, "Dog_JumpTouch", 0)

        for random, pain_frames in ((0.1, 16), (0.8, 6)):
            reset(40, 0, random)
            vm.set(dog, "enemy", 1)
            animate("dog_pain", pain_frames)
            vm.g[4:5], vm.g[7], vm.g[10], vm.g[13] = [dog], 1, 1, asi(30)
            vm.event(1, "T_Damage")
            if vm.get(dog, "health") > 0:
                raise ValueError("stock dog death callback was not reached")
            for _ in range(8):
                vm.t = vm.get(dog, "nextthink")
                vm.event(dog, "think")
    finally:
        (vm.e, vm.g, vm.t, vm.client, vm.combat, vm.visible, vm.hits,
         vm.forced_random, rng) = saved
        vm.rng.setstate(rng)
        vm.check_bottom = True
        vm.trace_visibility = None
