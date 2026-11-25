#include "gameplay_internal.hpp"

namespace quake_bsp_reference {
namespace {

bool touches_door(const GamePoint& eye, const Json& bounds, const char* low, const char* high)
{
    for (std::size_t axis = 0; axis < eye.size(); ++axis)
        if (eye[axis] < bounds.at(low).at(axis).get<int>() || eye[axis] > bounds.at(high).at(axis).get<int>())
            return false;
    return true;
}

// SUB_CalcMove waits 0.1s with zero velocity when the remaining trip is too short.
void hydraulic_reversal(const Json& door, bool outward, int offset, GameWord& age, GameWord& wait)
{
    const int target = door.at(outward ? "endQ4" : "startQ4").get<int>();
    const int distance = std::abs(target - offset);
    const int step = door.at("speed").get<int>() * 16 / 64;
    wait = distance < step * 64 / 10;
    const int ticks = wait ? 7 : (distance + step - 1) / step;
    age = gw(door.at("durationQ6").get<int>() - ticks);
}

} // namespace

void GameplaySession::Impl::ordinary_door_use(std::size_t index)
{
    const auto& door = metadata().at("stockExitMachinery").at("ordinaryDoors").at(index);
    auto& motion = ordinary_phase.at(index);
    const auto duration = door.at("durationQ6").get<GameWord>();
    if (motion == 2 && index == 0)
        ordinary_wait[index] = door.at("waitQ6").get<GameWord>();
    if (motion != 0 && !(motion == 3 && index == 0))
        return;
    if (motion == 3 && door.contains("riderBounds"))
        hydraulic_reversal(door, true, ordinary_offset[index], ordinary_age[index], ordinary_wait[index]);
    else
        ordinary_age[index] = motion == 3 ? std::min<GameWord>(duration - 1, duration - ordinary_age[index]) : 0;
    motion = 1;
    if (!door.at("lightStyles").empty())
    {
        ordinary_lights |= gw(std::int64_t(1) << (door.at("lightStyles").at(0).get<unsigned>() - 33));
        ++sounds;
    }
    if (door.at("sounds").at(0) != "misc/null.wav")
    {
        ++sounds;
        play_sound(door.at("sounds").at(0).get_ref<const std::string&>(), gw(0xf000 + index), 2);
    }
}

void GameplaySession::Impl::ordinary_doors_tick()
{
    const auto& doors = metadata().at("stockExitMachinery").at("ordinaryDoors");
    const auto& eye = walk.pending ? walk.pending_xyz : camera;
    if (ordinary_shot_cooldown)
        --ordinary_shot_cooldown;
    if (ordinary_hint_wait)
        --ordinary_hint_wait;
    for (std::size_t i = 0; i < doors.size(); ++i)
    {
        const auto& door = doors.at(i);
        const auto duration = door.at("durationQ6").get<GameWord>();
        auto& motion = ordinary_phase.at(i);
        auto& age = ordinary_age.at(i);
        if (gs(player("HEALTH")) > 0)
        {
            if (!motion && !door.at("shotHealth").get<int>() &&
                touches_door(eye, door, "triggerEyeMinQ4", "triggerEyeMaxQ4"))
                ordinary_door_use(i);
            if (!motion && !ordinary_hint_wait && door.contains("hintBounds") &&
                touches_door(eye, door.at("hintBounds"), "triggerEyeMinQ4", "triggerEyeMaxQ4"))
            {
                ordinary_hint_wait = hub_warning_ticks = 128;
                hub_warning_gate = gw(constant("QC_ORD_DOOR_HINT_GATE"));
                ++hub_warning_events;
                ++sounds;
            }
        }
        if (motion == 2)
        {
            if (!--ordinary_wait[i])
            {
                motion = 3;
                age = 0;
                if (!door.at("button").get<bool>())
                {
                    ++sounds;
                    play_sound(door.at("sounds").at(0).get_ref<const std::string&>(), gw(0xf000 + i), 2);
                }
            }
            continue;
        }
        if (motion != 1 && motion != 3)
            continue;
        const auto& path = door.at(motion == 1 ? "outwardQ4" : "returnQ4");
        ++age;
        const int previous = ordinary_offset[i];
        int current = path.at(age).get<int>();
        if (door.contains("riderBounds"))
        {
            const bool outward = motion == 1;
            const int target = door.at(outward ? "endQ4" : "startQ4").get<int>();
            const int step = door.at("speed").get<int>() * 16 / 64;
            if (ordinary_wait[i])
                current = age == duration ? target : previous;
            else
            {
                current = previous + std::clamp(target - previous, -step, step);
                const auto selector = metadata().at("stockExitMachinery").at("movers").size() + i;
                if (vertical_pusher_blocked(eye, door, selector, ordinary_offset[i], current))
                {
                    field(512, "HEALTH") = gw(gs(player("HEALTH")) - environmental_damage(door.at("damage").get<int>()));
                    damage_flash = 4;
                    motion = outward ? 3 : 1;
                    hydraulic_reversal(door, !outward, previous, age, ordinary_wait[i]);
                    ++sounds;
                    play_sound(door.at("sounds").at(0).get_ref<const std::string&>(), gw(0xf000 + i), 2);
                    continue;
                }
            }
            if (age == duration)
                ordinary_wait[i] = 0;
        }
        if (current != previous)
        {
            ordinary_offset[i] = current;
            const auto displacement = std::abs(current - door.at("startQ4").get<int>());
            ordinary_pose[i] = gw((displacement + 32) / 64);
            walk.support_valid = false;
        }
        if (age != duration)
            continue;
        if (door.at("button").get<bool>() && motion == 1)
        {
            ++activations;
            const auto lift = gw(constant("QC_DOOR"));
            event(lift, 512, field(lift, "USE"));
        }
        else if (!door.at("button").get<bool>() && door.at("sounds").at(1) != "misc/null.wav")
        {
            ++sounds;
            play_sound(door.at("sounds").at(1).get_ref<const std::string&>(), gw(0xf000 + i), 2);
        }
        if (motion == 3)
            motion = 0;
        else if (const auto wait = door.at("waitQ6").get<int>(); wait > 0)
        {
            motion = 2;
            ordinary_wait[i] = gw(wait);
        }
        else
            motion = 4;
    }
}

} // namespace quake_bsp_reference
