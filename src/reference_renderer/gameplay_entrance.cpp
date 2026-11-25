#include "gameplay_internal.hpp"

namespace quake_bsp_reference {
std::array<GameWord, 2> GameplaySession::Impl::entrance_render_rows(std::array<GameWord, 2> poses) const
{
    const auto leaves = metadata().at("stockEntranceDoors");
    if (constant("QC_ENTRANCE_COUNT") != 2 || !leaves.is_array() || leaves.size() != 2)
        throw std::runtime_error("entrance visual roster differs from its linked pair");
    std::array<GameWord, 2> result{};
    for (unsigned leaf = 0; leaf < result.size(); ++leaf)
    {
        const auto& rows = leaves.at(leaf).at("poseRows");
        if (poses[leaf] > 16 || !rows.is_array() || rows.size() != 17)
            throw std::runtime_error("entrance visual pose escapes its seventeen rows");
        for (const auto& row : rows)
            if (!row.is_number_integer() || row.get<std::int64_t>() < 0 || row.get<std::uint64_t>() > 65535 ||
                row.get<std::uint64_t>() >= assets().manifest.at("brushRows").size())
                throw std::runtime_error("entrance visual row escapes the brush replay");
        result[leaf] = rows.at(poses[leaf]).get<GameWord>();
    }
    return result;
}

GameWord GameplaySession::Impl::entrance_quantized_pose(unsigned leaf, GameWord origin) const
{
    const auto stem = "QC_ENTRANCE_" + std::to_string(leaf);
    const auto steps = constant("QC_ENTRANCE_STEPS", 16);
    const auto travel = constant(stem + "_TRAVEL");
    const auto direction = constant(stem + "_DIRECTION");
    if (leaf >= entrance_pose.size() || steps <= 0 || travel <= 0 || travel % steps ||
        (direction != -1 && direction != 1))
        throw std::runtime_error("invalid entrance pusher quantization contract");
    const auto distance = std::max<std::int64_t>(0, std::int64_t(gs(origin)) * direction);
    const auto interval = travel / steps;
    return gw(std::min(steps, (distance + interval / 2) / interval));
}

GameWord GameplaySession::Impl::support_pose_key() const
{
    if (basic() || !constant("QC_ENTRANCE_COUNT"))
        return brush_row;
    const auto rows = (constant("QC_DOOR_STEPS") + 1) * (constant("QC_BUTTON_STEPS") + 1);
    const auto states = constant("QC_ENTRANCE_STEPS", 16) + 1;
    return gw(brush_row + rows * (entrance_pose[0] + states * entrance_pose[1]));
}

void GameplaySession::Impl::entrance_tick()
{
    if (basic() || !constant("QC_ENTRANCE_COUNT"))
        return;
    if (constant("QC_ENTRANCE_COUNT") != 2)
        throw std::runtime_error("entrance gameplay requires the linked two-leaf contract");
    const auto point = walk.pending ? walk.pending_xyz : camera;
    bool touches = true;
    for (unsigned axis = 0; axis < 3; ++axis)
    {
        const auto name = "QC_ENTRANCE_TRIGGER_" + std::string(1, "XYZ"[axis]);
        const auto low = constant(name + "_MIN");
        const auto high = constant(name + "_MAX");
        touches &= gw(point[axis] - low) <= gw(high - low);
    }
    if (touches)
    {
        const auto trigger = gw(constant("QC_ENTRANCE_TRIGGER"));
        // The stock callback owns cooldown, living-player checks and team use.
        event(trigger, 512, field(trigger, "TOUCH"));
    }
    for (unsigned leaf = 0; leaf < entrance_pose.size(); ++leaf)
        entrance_pusher(leaf);
}

void GameplaySession::Impl::entrance_pusher(unsigned leaf)
{
    const auto actor = gw(constant("QC_ENTRANCE_" + std::to_string(leaf)));
    auto& deadline = field(actor, "NEXTTHINK");
    if (gs(deadline) <= 0)
        return;
    --deadline;
    const auto velocity = gs(field(actor, "VELOCITY", 1));
    if (velocity)
    {
        const auto total = gs(e(actor, 400) + velocity);
        const auto fraction = gw(total) & 63;
        auto candidate = gs(field(actor, "ORIGIN", 1) + game_asr(total, 6));
        if (!deadline)
            candidate = gs(field(actor, "FINALDEST", 1));
        const auto pose = entrance_quantized_pose(leaf, gw(candidate));
        if (pose != entrance_pose[leaf])
        {
            const auto point = walk.pending ? walk.pending_xyz : camera;
            if (entrance_contains_player(leaf, pose, point) &&
                !entrance_contains_player(leaf, entrance_pose[leaf], point))
            {
                ++deadline;
                ++door_blocks;
                event(actor, 512, field(actor, "BLOCKED"));
                return;
            }
            entrance_pose[leaf] = pose;
        }
        field(actor, "ORIGIN", 1) = gw(candidate);
        e(actor, 400) = gw(fraction);
    }
    if (!deadline)
        event(actor, 0, field(actor, "THINK"));
}

} // namespace quake_bsp_reference
