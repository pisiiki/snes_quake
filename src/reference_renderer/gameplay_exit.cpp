#include "gameplay_internal.hpp"

namespace quake_bsp_reference {
namespace {
bool touches_exit_box(const GamePoint& point, const Json& box)
{
    const auto& lo = box.at("eyeMinQ4");
    const auto& hi = box.at("eyeMaxQ4");
    for (std::size_t axis = 0; axis < point.size(); ++axis)
        if (point[axis] < lo.at(axis).get<int>() || point[axis] > hi.at(axis).get<int>())
            return false;
    return true;
}
} // namespace

void GameplaySession::Impl::exit_tick()
{
    if (!constant("QC_EXIT_MOVER_COUNT"))
        return;
    const auto point = walk.pending ? walk.pending_xyz : camera;
    if (!exit_started && point[1] < constant("QC_EXIT_FIRST_Y"))
        return;
    exit_started = true;
    const auto& machinery = assets().manifest.at("metadata").at("gameplay").at("stockExitMachinery");
    const auto& movers = machinery.at("movers");
    if (movers.size() != exit_ages.size() + platform_phase.size())
        throw std::runtime_error("E1M1 exit mover roster differs from its asset contract");
    if (exit_wait)
        --exit_wait;
    if (gs(player("HEALTH")) > 0)
    {
        if (touches_exit_box(point, machinery.at("doorTouch")))
            exit_wait = gw(constant("QC_EXIT_DOOR_WAIT"));
        for (unsigned i = 3; i < 7; ++i)
            if (!(exit_targets & (1U << i)) && touches_exit_box(point, movers.at(i).at("touch")))
                exit_targets = gw(exit_targets | (1U << i));
    }
    exit_targets = gw(exit_wait ? exit_targets | 3 : exit_targets & ~3);
    const auto at_stop = [&](std::size_t i) { return exit_ages[i] == movers.at(i).at("ticksQ6").get<GameWord>(); };
    if (at_stop(3))
        exit_targets |= 4;
    if (at_stop(4) && at_stop(5) && at_stop(6))
        exit_targets |= 128;
    for (std::size_t i = 0; i < exit_ages.size(); ++i)
    {
        if (exit_targets & (1U << i))
        {
            if (at_stop(i))
                continue;
            ++exit_ages[i];
        }
        else
        {
            if (!exit_ages[i])
                continue;
            --exit_ages[i];
        }
        GameWord pose = 0;
        for (const auto& threshold : movers.at(i).at("poseThresholds"))
            if (exit_ages[i] >= threshold.get<GameWord>())
                ++pose;
        if (pose != exit_poses[i])
        {
            exit_poses[i] = pose;
            walk.support_valid = false;
        }
    }
    platforms_tick(walk.pending ? walk.pending_xyz : camera, movers);
}


void GameplaySession::Impl::secret_door_start(std::size_t index)
{
    if (!secret_door_phase.at(index))
    {
        secret_door_phase[index] = 1;
        sounds += 2; // Stock latch and motor on the same channel.
        if (collect_sound)
        {
            const auto& cues = metadata().at("stockExitMachinery").at("secretDoors").at(index).at("sounds");
            play_sound(cues.at(0).get_ref<const std::string&>(), gw(0xf080 + index), 2);
            play_sound(cues.at(1).get_ref<const std::string&>(), gw(0xf080 + index), 2);
        }
    }
}

void GameplaySession::Impl::secret_door_shot(GameWord terminal)
{
    const auto index = unsigned(gw(0xffc0 - terminal));
    const auto& doors = metadata().at("stockExitMachinery").at("secretDoors");
    if (index < doors.size() && doors.at(index).at("shootable").get<bool>())
        secret_door_start(index);
    else if (index == doors.size())
        for (std::size_t i = 0; i < doors.size(); ++i)
            for (const auto& link : doors.at(i).at("links"))
                if (link.at("shot").get<bool>())
                    secret_door_start(i);
}

void GameplaySession::Impl::secret_doors_tick()
{
    const auto& doors = metadata().at("stockExitMachinery").at("secretDoors");
    const auto& eye = walk.pending ? walk.pending_xyz : camera;
    const auto touches = [&](const Json& box) {
        for (std::size_t axis = 0; axis < eye.size(); ++axis)
            if (eye[axis] < box.at("triggerEyeMinQ4").at(axis).get<int>() ||
                eye[axis] > box.at("triggerEyeMaxQ4").at(axis).get<int>())
                return false;
        return true;
    };
    if (secret_door_hint_wait)
        --secret_door_hint_wait;
    for (std::size_t i = 0; i < doors.size(); ++i)
    {
        const auto& door = doors.at(i);
        auto& motion = secret_door_phase.at(i);
        if (gs(player("HEALTH")) > 0)
        {
            for (const auto& link : door.at("links"))
                if (!link.at("shot").get<bool>() && touches(link))
                {
                    if (const unsigned bit = link.value("t3TriggerBit", 0U))
                    {
                        if (t3_trigger_state & bit)
                            continue;
                        t3_trigger_state = gw((t3_trigger_state | bit) ^ 16U);
                        ++sounds;
                    }
                    secret_door_start(i);
                }
            if (!motion && !secret_door_hint_wait && !door.at("touchMessage").get_ref<const std::string&>().empty() && touches(door))
            {
                secret_door_hint_wait = hub_warning_ticks = 128;
                hub_warning_gate = gw(constant("QC_SECRET_DOOR_HINT_GATE"));
                ++hub_warning_events;
                ++sounds;
            }
        }
        if (!motion || motion == 8)
            continue;
        auto& wait = secret_door_wait[i];
        if (!(motion & 1))
        {
            if (!--wait)
            {
                ++motion;
                ++sounds;
                play_sound(door.at("sounds").at(1).get_ref<const std::string&>(), gw(0xf080 + i), 2);
            }
            continue;
        }
        const auto& legs = door.at("legs");
        const int first_length = std::abs(legs.at(0).at("travelQ4").get<int>());
        const int total = first_length + std::abs(legs.at(1).at("travelQ4").get<int>());
        auto& travel = secret_door_travel[i];
        const int target = motion == 3 ? 2 * total : motion == 7 ? 0 : 2 * first_length;
        travel = gw(motion < 5 ? std::min(target, travel + 25) : std::max(target, travel - 25));
        if (travel == target)
        {
            ++motion;
            if (motion == 8)
                motion = 0;
            else if (motion == 4 && door.at("permanent").get<bool>())
                motion = 8;
            else
                wait = door.at(motion == 4 ? "openWaitQ6" : "cornerWaitQ6").get<GameWord>();
            ++sounds;
            play_sound(door.at("sounds").at(2).get_ref<const std::string&>(), gw(0xf080 + i), 2);
        }
        int distance = travel / 2;
        distance += (travel & distance & 1);
        secret_door_pose[i] = gw((distance + 32) / 64);
        int remaining = distance;
        for (const auto& leg : legs)
        {
            const int full = leg.at("travelQ4").get<int>();
            const int step = std::min(remaining, std::abs(full));
            secret_door_xy.at(2*i + leg.at("axis").get<std::size_t>()) = full < 0 ? -step : step;
            remaining -= step;
        }
        walk.support_valid = false;
    }
}

bool GameplaySession::Impl::vertical_pusher_blocked(const GamePoint& eye, const Json& mover,
                                                     std::size_t index, int& offset, int next)
{
    const auto& bounds = mover.at("riderBounds");
    if (gs(player("HEALTH")) <= 0 || eye[0] < bounds.at("eyeMinQ4").at(0).get<int>() ||
        eye[0] > bounds.at("eyeMaxQ4").at(0).get<int>() || eye[1] < bounds.at("eyeMinQ4").at(1).get<int>() ||
        eye[1] > bounds.at("eyeMaxQ4").at(1).get<int>())
        return false;
    const int delta = next - offset;
    const bool on_top = walk.grounded && std::abs(eye[2] - offset - mover.at("floorEyeQ4").get<int>()) <= 4;
    auto relative = eye;
    relative[2] = gs(eye[2] - (on_top ? 5 : delta));
    const auto surface = trace(eye, relative);
    const auto first = std::size_t(constant("WALK_EXIT_PLANE_FIRST"));
    const auto plane = std::size_t(surface.plane & 0x1ff8);
    const auto table = std::size_t(constant("WALK_HULL_PLANES") + constant("WALK_EXIT_PLANE_TABLE"));
    if (!surface.hit || (surface.plane & 0xe006) != 0xa006 || plane < first ||
        bytes("QuakeBSPWalkHull.bin").at(table + (plane - first) / 8) / 4 != index)
        return false;
    auto pushed = eye;
    pushed[2] = gs(eye[2] + delta);
    const int previous = offset;
    if (delta < 0 && on_top)
        offset = next;
    const auto sweep = trace(eye, pushed);
    if (sweep.hit)
    {
        offset = next;
        // SV_PushEntity may stop short on a ledge. A hydraulic door is
        // blocked only if the clipped player still overlaps the moved hull.
        if (!mover.contains("shotHealth") || trace(sweep.result, sweep.result).hit)
        {
            offset = previous;
            return true;
        }
        pushed = sweep.result;
    }
    walk.from = walk.pending_xyz = pushed;
    walk.pending = true;
    return false;
}

void GameplaySession::Impl::platforms_tick(const GamePoint& eye, const Json& movers)
{
    const auto first = std::size_t(constant("QC_E1M1_PLATFORM_FIRST"));
    for (std::size_t slot = 0; slot < platform_phase.size(); ++slot)
    {
        const std::size_t index = first + slot;
        const auto& mover = movers.at(index);
        auto& motion = platform_phase[slot];
        auto& age = platform_age[slot];
        auto& wait = platform_wait[slot];
        const bool touched = gs(player("HEALTH")) > 0 && touches_exit_box(eye, mover.at("platformTouch"));
        const auto play_platform = [&](const char* key, const char* fallback) {
            if (collect_sound)
                play_sound(mover.value(key, fallback), gw(0xf100 + slot), 2);
        };
        if (motion == 0)
        {
            if (!touched)
                continue;
            motion = 1;
            age = 0;
            play_platform("moveSound", "plats/plat1.wav");
        }
        else if (motion == 2)
        {
            if (touched)
                wait = mover.at("occupiedWaitQ6").get<GameWord>();
            if (--wait)
                continue;
            motion = 3;
            age = 0;
            play_platform("moveSound", "plats/plat1.wav");
            continue;
        }
        const auto& path = mover.at(motion == 1 ? "ascentQ4" : "descentQ4");
        const auto next = path.at(age + 1).get<int>();
        auto& offset = exit_offsets_q4.at(index);
        if (vertical_pusher_blocked(eye, mover, index, offset, next))
        {
            field(512, "HEALTH") = gw(gs(player("HEALTH")) - environmental_damage(1));
            damage_flash = 4;
            motion = motion == 1 ? 3 : 1;
            const auto duration = mover.at("ticksQ6").get<GameWord>();
            age = std::min<GameWord>(gw(duration - age), gw(duration - 1));
            play_platform("moveSound", "plats/plat1.wav");
            continue;
        }
        offset = next;
        walk.support_valid = false;
        ++age;
        auto& pose = exit_poses[index];
        const auto duration = mover.at("ticksQ6").get<GameWord>();
        if (mover.contains("visualRows"))
            pose = gw((offset - mover.at("positionsQ4").at(0).get<int>() + 32) / 64);
        else
        {
            const auto elapsed = motion == 1 ? age : duration - age;
            pose = 0;
            for (const auto& threshold : mover.at("poseThresholds"))
                if (elapsed >= threshold.get<int>())
                    ++pose;
        }
        if (age == duration)
        {
            motion = motion == 1 ? 2 : 0;
            wait = mover.at("waitQ6").get<GameWord>();
            play_platform("stopSound", "plats/plat2.wav");
        }
    }
}

std::uint32_t GameplaySession::Impl::exit_pose_word() const
{
    std::uint32_t result = 0;
    if (constant("QC_E1M3_GOLD_KEY"))
    {
        const auto& movers = metadata().at("stockExitMachinery").at("movers");
        for (std::size_t i = 0; i < movers.size(); ++i)
            result |= std::uint32_t(exit_poses[i]) << (2 * movers.at(i).at("poseSlot").get<unsigned>());
    }
    else if (metadata().at("stockExitMachinery").at("movers").back().contains("visualRows"))
    {
        for (std::size_t i = 0; i < 8; ++i)
            result |= std::uint32_t(exit_poses[i]) << (2 * i);
        result |= std::uint32_t(exit_poses[8]) << 16;
        result |= std::uint32_t(exit_poses[9]) << 24;
    }
    else
        for (std::size_t i = 0; i < 16; ++i)
            result |= std::uint32_t(exit_poses[i]) << (2 * i);
    return result;
}

} // namespace quake_bsp_reference
