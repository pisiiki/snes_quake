"""Derive E1M1 timed artifact pickup behavior from the shareware program."""

from array import array
from dataclasses import replace
from hashlib import sha256
from itertools import zip_longest
import sys

from snes_tooling.quake.quake_snes_realtime_sound import resample_wave_pcm
from snes_tooling.quake.quake_snes_soundtrack import parse_quake_wave
from snes_tooling.quake.quake_start_ambient import key_actor
from snes_tooling.quake.quakec_grunt import GruntReference
from snes_tooling.quake.quakec_reference import asi
from snes_tooling.quake.quakec_shell_pickups import floor_drop, pickup_eye_bounds


def stock_powerups(archive, bsp, entities, models, program, first_row):
    drop = floor_drop(bsp, models[0][10], supporting_roots=(models[3][10], models[4][10]))
    vm = GruntReference(program, models, archive, drop)
    vm.add(0, {"classname": "worldspawn"})
    fields = {"item_artifact_super_damage": ("quad", "super_damage_finished"),
              "item_artifact_envirosuit": ("suit", "radsuit_finished")}
    powerups = []
    for entity_number, entity in enumerate(entities, 1):
        if entity["classname"] not in fields:
            continue
        if int(entity.get("spawnflags", 0)) or any(entity.get(k) for k in ("target", "killtarget")):
            raise ValueError("unexpected stock E1M1 artifact spawn flags or targets")
        vm.t = 0
        vm.add(2, {**entity, "origin": tuple(map(float, entity["origin"].split()))})
        vm.event(2, entity["classname"])
        vm.t = vm.get(2, "nextthink")
        vm.set(2, "nextthink", 0)
        vm.event(2, "think")
        model, origin = vm.get(2, "model"), vm.get(2, "origin")
        props = key_actor(dict(entityNumber=entity_number, model=model, origin=origin), models)
        lower, upper = pickup_eye_bounds(origin, vm.get(2, "mins"), vm.get(2, "maxs"))
        vm.add(1, {"classname": "player", "max_health": 100, "health": 100})
        vm.t = 9
        vm.event(2, "touch", 1)
        kind, deadline = fields[entity["classname"]]
        powerups.append(dict(**props, kind=kind, bit=int(vm.get(1, "items")), sound=vm.events[-1][3],
                             duration=int(vm.get(1, deadline) - vm.t),
                             spriteRow=first_row + len(powerups), triggerEyeMinQ4=lower, triggerEyeMaxQ4=upper))
    if [(p["model"], p["bit"], p["duration"], p["sound"]) for p in powerups] != [
            ("progs/quaddama.mdl", 1 << 22, 30, "items/damage.wav"),
            ("progs/suit.mdl", 1 << 21, 30, "items/suit.wav")]:
        raise ValueError("unexpected stock E1M1 artifact inventory")
    return powerups


def powerup_constants(powerups, program):
    constants = {"QC_POWERUP_COUNT": len(powerups),
                 "QC_FIELD_RADSUIT_FINISHED": 2 * program.fields["radsuit_finished"][1],
                 "QC_FIELD_SUPER_SOUND": 2 * program.fields["super_sound"][1],
                 "QC_FIELD_SUPER_DAMAGE_FINISHED": 2 * program.fields["super_damage_finished"][1]}
    for index, p in enumerate(powerups):
        key = f"QC_POWERUP_{index}_"
        constants.update({key + "SPRITEROW": p["spriteRow"], key + "ITEM_HIGH": p["bit"] >> 16,
                          key + "SECONDS": p["duration"]})
        for axis, lo, hi, pos in zip("XYZ", p["triggerEyeMinQ4"], p["triggerEyeMaxQ4"], p["renderOriginQ2"], strict=True):
            constants.update({key + axis + "_MIN": lo, key + axis + "_MAX": hi, key + axis: pos})
    return constants

def cover_quad_damage(trace, program, models, archive):
    """Retain the real T_Damage multiplier branch in the cartridge program."""
    vm = GruntReference(program, models, archive, None)
    vm.t, vm.combat = 7, True
    vm.add(0, {"classname": "worldspawn"})
    for active, expected in ((False, 95), (True, 80)):
        vm.add(1, {"classname": "player", "health": 100, "super_damage_finished": 37 if active else 0})
        vm.add(2, {"classname": "monster_army", "health": 100, "takedamage": 1})
        vm.g[4], vm.g[7], vm.g[10], vm.g[13] = 2, 1, 1, asi(5)
        vm.event(1, "T_Damage")
        if vm.get(2, "health") != expected:
            raise ValueError("stock Quad damage multiplier changed")
    for tick, plays in ((7, True), (8, False), (8.015625, True), (37, False)):
        vm.t = tick
        first = len(vm.events)
        vm.event(1, "SuperDamageSound")
        if vm.events[first:] != ([("sound", 1, 4, "items/damage3.wav", 1, 1)] if plays else []):
            raise ValueError("stock Quad attack sound cadence changed")
    trace.pcs.update(vm.pcs)
    trace.stats.update(vm.stats)


ARTIFACT_TRACKS = {
    1: "items/damage.wav", 2: "items/damage2.wav", 3: "items/health1.wav",
    4: "items/suit.wav", 5: "items/suit2.wav",
    6: "buttons/airbut1.wav", 7: "doors/doormv1.wav", 8: "doors/drclos4.wav",
    9: "misc/trigger1.wav",
    10: "weapons/guncock.wav",
    11: "player/inh2o.wav", 12: "player/slimbrn2.wav", 13: "misc/outwater.wav",
    14: "items/r_item1.wav", 15: "weapons/r_exp3.wav", 21: "ambience/hum1.wav",
    **{15 + i: f"misc/r_tele{i}.wav" for i in range(1, 6)},
    22: "weapons/shotgn2.wav",
    23: "weapons/rocket1i.wav",
    24: "items/armor1.wav",
}


def write_artifact_tracks(archive, rom):
    """Build MSU-1 one-shot effects alongside the ROM from the user's original PAK."""
    records = []
    for track, name in ARTIFACT_TRACKS.items():
        source = archive.read("sound/" + name)
        wave = parse_quake_wave(source, name)
        if wave.loop_start is not None and track not in (7, 21):
            raise ValueError(f"unexpected looped artifact sound {name}")
        if track == 21:
            if wave.loop_start != 0:
                raise ValueError("E1M1 teleporter hum must loop from the first sample")
            # MSU PCM has no 16-sample BRR block boundary. Keep the original loop period.
            wave = replace(wave, loop_start=None)
        mono = resample_wave_pcm(wave, output_rate_hz=44100)
        extras = {}
        if track in (7, 8):
            # The relay and door have different emitters but share one MSU channel.
            # Keep the trigger tail under the door stop at the stock 11th Q6 tick.
            relay_name = "misc/trigger1.wav"
            relay_source = archive.read("sound/" + relay_name)
            relay = resample_wave_pcm(parse_quake_wave(relay_source, relay_name), output_rate_hz=44100)
            start = 0 if track == 7 else round(11 * 44100 / 64)
            relay = relay[start:]
            if wave.loop_start is not None:
                loop = round(wave.loop_start * 44100 / wave.sample_rate_hz)
                while len(mono) < len(relay):
                    mono += mono[loop:]
            # The stock additive peak exceeds full scale. Keep both cues at
            # the same gain across the transition, with room for that peak.
            mix_gain = 5 / 8
            mono = tuple(round((motor + trigger) * mix_gain)
                         for motor, trigger in zip_longest(mono, relay, fillvalue=0))
            extras = dict(relaySound=relay_name, relaySourceSha256=sha256(relay_source).hexdigest(),
                          relayStartSample=start, mixGain=mix_gain)
        stereo = array("h", (sample for value in mono for sample in (value, value)))
        if sys.byteorder != "little":
            stereo.byteswap()
        data = b"MSU1" + bytes(4) + stereo.tobytes()
        target = rom.with_name(f"{rom.stem}-{track}.pcm")
        target.write_bytes(data)
        records.append(dict(track=track, file=target.name, sound=name, bytes=len(data),
                            sha256=sha256(data).hexdigest(), sourceSha256=sha256(source).hexdigest(), **extras))
    return records
