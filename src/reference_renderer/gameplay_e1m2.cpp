#include "gameplay_internal.hpp"

#include <algorithm>

namespace quake_bsp_reference {
namespace {
bool touches_box(const GamePoint& point, const Json& box)
{
    for (std::size_t axis = 0; axis < point.size(); ++axis)
        if (point[axis] < box.at("eyeMinQ4").at(axis).get<int>() ||
            point[axis] > box.at("eyeMaxQ4").at(axis).get<int>())
            return false;
    return true;
}
} // namespace

void GameplaySession::Impl::e1m3_mover_tick(std::size_t index, const Json& mover, int age)
{
    const int ticks = mover.at("ticksQ6").get<int>();
    const int return_at = mover.contains("returnWaitQ6") ? ticks + mover.at("returnWaitQ6").get<int>() : 0;
    if (return_at && age > return_at)
        age = ticks - (age - return_at);
    age = std::clamp(age, 0, ticks);
    const int start = mover.at("positionsQ4").front().get<int>();
    const int end = mover.at("positionsQ4").back().get<int>();
    const int numerator = (end - start) * age;
    const int next = mover.contains("trajectoryQ4") ? mover.at("trajectoryQ4").at(std::size_t(age)).get<int>()
        : start + (numerator - (numerator < 0 ? ticks - 1 : 0)) / ticks;
    auto& offset = exit_offsets_q4.at(index);
    const int delta = next - offset;
    if (delta && mover.contains("rider") && walk.grounded && gs(player("HEALTH")) > 0)
    {
        const auto& rider = mover.at("rider");
        const auto point = walk.pending ? walk.pending_xyz : camera;
        if (point[0] >= rider.at("eyeMinQ4").at(0).get<int>()
            && point[0] < rider.at("eyeMaxQ4").at(0).get<int>()
            && point[1] >= rider.at("eyeMinQ4").at(1).get<int>()
            && point[1] < rider.at("eyeMaxQ4").at(1).get<int>())
        {
            auto below = point;
            below[2] = gs(point[2] - 5);
            const auto support = trace(point, below);
            const auto plane = (support.plane & 0x1ff8U) |
                (constant("WALK_HULL_EXTENDED_PLANES") ? (support.plane & 2U) << 12 : 0U);
            const auto base = std::size_t(constant("WALK_HULL_PLANES"));
            if (support.hit && (support.plane & 0xe004) == 0xa004
                && game_u16(bytes("QuakeBSPWalkHull.bin"), base + plane) == index + 1)
            {
                auto lifted = point;
                lifted[2] = gs(point[2] + delta);
                if (delta < 0)
                    offset = next;
                const auto obstruction = trace(point, lifted);
                if (obstruction.hit)
                {
                    if (delta < 0)
                        offset -= delta;
                    return;
                }
                walk.from = walk.pending_xyz = lifted;
                walk.pending = true;
            }
        }
    }
    if (delta)
    {
        offset = next;
        walk.support_valid = false;
    }
    if (mover.contains("secondTrajectoryQ4"))
    {
        auto& secondary = exit_offsets_q4.at(std::size_t(constant("QC_EXIT_MOVER_COUNT")) + index);
        const auto position = mover.at("secondTrajectoryQ4").at(std::size_t(age)).get<int>();
        if (secondary != position)
        {
            secondary = position;
            walk.support_valid = false;
        }
    }
    GameWord pose = 0;
    for (const auto& threshold : mover.at("poseThresholds"))
        if (age >= threshold.get<int>())
            ++pose;
    exit_poses.at(index) = pose;
}

void GameplaySession::Impl::e1m2_machinery_tick()
{
    const auto& machinery = metadata().at("stockExitMachinery");
    const auto& groups = machinery.at("groups");
    const auto& movers = machinery.at("movers");
    const auto point = walk.pending ? walk.pending_xyz : camera;
    const bool alive = gs(player("HEALTH")) > 0;
    const bool e1m3 = constant("QC_E1M3_GOLD_KEY");
    const auto key_name = e1m3 ? "goldKey" : "silverKey";
    if (alive && !e1m2_key && touches_box(point, machinery.at(key_name).at("trigger")))
        e1m2_key = 1;
    for (std::size_t i = 0; i < groups.size(); ++i)
    {
        const auto& group = groups.at(i);
        const auto bit = GameWord(1U << i);
        const bool permanent = group.at("waitQ6") == -1;
        const bool silver = i == std::size_t(constant("QC_E1M2_SILVER_GROUP"));
        const bool shot = e1m3 && i == std::size_t(constant("QC_E1M3_SHOT_GROUP"));
        auto& age = e1m2_group_age.at(i);
        auto& wait = e1m2_group_wait.at(i);
        const auto duration = group.at("durationQ6").get<GameWord>();
        if (alive && (!permanent || !(exit_targets & bit)) && (!silver || e1m2_key == 1)
            && (shot ? e1m3_stair_button_hit : touches_box(point, group.at("trigger"))))
        {
            exit_targets |= bit;
            if (!permanent)
                wait = group.at("waitQ6").get<GameWord>();
            if (silver)
                e1m2_key = 2;
        }
        if (exit_targets & bit)
        {
            if (age < duration)
                ++age;
            else
            {
                if (!permanent && wait && !--wait)
                    exit_targets &= ~bit;
                if (e1m3)
                    continue;
            }
        }
        else if (age)
            --age;
        else
            continue;
        for (const auto& index : group.at("movers"))
        {
            const auto j = index.get<std::size_t>();
            const auto& mover = movers.at(j);
            auto& pose = exit_poses.at(j);
            const auto elapsed = int(age) - mover.at("delayQ6").get<int>();
            if (e1m3)
            {
                e1m3_mover_tick(j, mover, elapsed);
                continue;
            }
            GameWord next = 0;
            for (const auto& threshold : mover.at("poseThresholds"))
                if (elapsed >= threshold.get<int>())
                    ++next;
            if (pose != next)
            {
                pose = next;
                walk.support_valid = false;
            }
        }
    }
    if (e1m3)
    {
        const auto index = std::size_t(constant("QC_E1M3_PLATFORM"));
        const auto& platform = movers.at(index);
        const auto limit = platform.at("ticksQ6").get<unsigned>();
        if (!key_platform_phase && alive &&
            (touches_box(point, platform.at("useTriggers").at(0)) ||
             touches_box(point, platform.at("useTriggers").at(1))))
        {
            key_platform_phase = 1;
            exit_targets |= GameWord(1U << groups.size());
        }
        if (key_platform_phase == 4 && !--key_platform_wait)
            key_platform_phase = 1;
        if (key_platform_phase == 2 && alive && touches_box(point, platform.at("centerTouch")))
            key_platform_phase = 3;
        if (key_platform_phase == 1)
        {
            if (++key_platform_age == limit)
                key_platform_phase = 2;
            e1m3_mover_tick(index, platform, int(key_platform_age));
        }
        else if (key_platform_phase == 3)
        {
            if (!--key_platform_age)
            {
                key_platform_phase = 4;
                key_platform_wait = 3 * 64;
            }
            e1m3_mover_tick(index, platform, int(key_platform_age));
        }
    }
}

} // namespace quake_bsp_reference
