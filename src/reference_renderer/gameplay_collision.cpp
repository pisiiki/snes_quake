#include "gameplay_internal.hpp"

#include <cmath>
#include <numbers>

namespace quake_bsp_reference {
namespace {
const std::array<unsigned, 8> axis_a{0, 0, 1, 0, 1, 2, 2, 0};
const std::array<unsigned, 8> axis_b{1, 2, 2, 0, 1, 2, 2, 0};
std::size_t plane_offset(GameWord reference, bool extended)
{
    return (reference & 0x1ff8) | (extended ? (reference & 2) << 12 : 0);
}

GamePoint interpolate(const GamePoint& a, const GamePoint& b, GameWord t)
{
    GamePoint result{};
    for (unsigned i = 0; i < 3; ++i)
        result[i] = gs(a[i] + game_asr(std::int64_t(gs(b[i] - a[i])) * t, 12));
    return result;
}
GamePoint add_point(const GamePoint& a, const GamePoint& b)
{
    GamePoint result{};
    for (unsigned i = 0; i < 3; ++i)
    {
        auto v = int(a[i]) + b[i];
        result[i] = v >= -32768 && v <= 32767 ? gs(v) : a[i];
    }
    return result;
}
} // namespace

std::int64_t GameplaySession::Impl::plane_distance(GameWord ref, const GamePoint& p, bool shot)
{
    const std::string prefix = shot ? "SHOT" : "WALK";
    const auto& data = bytes(shot ? "QuakeBSPShotHull.bin" : "QuakeBSPWalkHull.bin");
    const auto offset = plane_offset(ref, constant(prefix + "_HULL_EXTENDED_PLANES", 0) != 0);
    const auto pos = std::size_t(constant(prefix + "_HULL_PLANES")) + offset;
    const unsigned tag = ref >> 13;
    auto distance = std::int64_t(game_s32(data, pos + 4));
    if (basic() && tag == 6)
    {
        const auto c = game_s16(data, std::size_t(constant(prefix + "_HULL_THIRD_COEFFICIENTS")) + offset / 4);
        return std::int64_t(p[0]) * game_s16(data, pos) + std::int64_t(p[1]) * game_s16(data, pos + 2) +
               std::int64_t(p[2]) * c - distance;
    }
    if (basic() && (ref & 4))
    {
        if (constant("QC_E1M3_GOLD_KEY"))
        {
            auto mover = std::int64_t(game_u16(data, pos)) - 1;
            std::int64_t coefficient = 1;
            if (tag < 3)
            {
                const auto count = constant(prefix + "_MOVING_BEVEL_COUNT");
                for (int i = 0; i < count; ++i)
                {
                    const auto plane = prefix + "_MOVING_BEVEL_" + std::to_string(i);
                    if (std::size_t(constant(plane + "_OFFSET")) == offset)
                    {
                        mover = constant(plane + "_MOVER");
                        coefficient = constant(plane + "_COEFFICIENT");
                        break;
                    }
                }
            }
            const auto delta = exit_offsets_q4.at(std::size_t(mover));
            distance += coefficient * (shot ? game_asr(delta, 1) : delta);
        }
        else
        {
            const auto mover = game_u16(data, pos) - 1;
            const auto& row = metadata().at("stockExitMachinery").at("movers").at(mover);
            distance += row.at(shot ? "positionsQ3" : "positionsQ4").at(exit_poses.at(mover)).get<int>();
        }
    }
    if (!basic() && (ref & 6) == 6)
    {
        const auto first = constant(prefix + "_EXIT_PLANE_FIRST");
        const auto table = constant(prefix + "_EXIT_PLANE_TABLE");
        if (offset < static_cast<std::size_t>(first))
            throw std::runtime_error("exit plane lies before its selector table");
        const auto selector = data.at(static_cast<std::size_t>(constant(prefix + "_HULL_PLANES") + table) +
                                      (offset - static_cast<std::size_t>(first)) / 8);
        const auto& movers = assets().manifest.at("metadata").at("gameplay").at("stockExitMachinery").at("movers");
        if (selector >= 128)
        {
            const auto delta = secret_door_xy.at(selector - 128);
            distance += shot ? game_asr(delta, 1) : delta;
            return std::int64_t(p.at(tag - 3)) - distance;
        }
        const auto mover = static_cast<std::size_t>(selector) / 4;
        const auto lane = selector % 4;
        int delta;
        if (mover >= movers.size() || movers.at(mover).contains("platformTouch"))
        {
            delta = mover >= movers.size() ? ordinary_offset.at(mover - movers.size()) : exit_offsets_q4.at(mover);
            if (shot)
                delta = game_asr(delta, 1);
        }
        else
            delta = movers.at(mover).at(shot ? "positionsQ3" : "positionsQ4").at(exit_poses.at(mover)).get<int>();
        if (lane == 0 && tag >= 3)
            distance += delta;
        else if ((lane == 1 || lane == 2) && tag < 3)
            distance += std::int64_t(delta) * game_s16(data, pos + (lane - 1) * 2);
        else
            throw std::runtime_error("exit plane has an invalid translation selector");
    }
    else if (!basic() && (ref & 6))
    {
        const unsigned owner = ref & 6;
        const unsigned leaf = owner == 2 ? 0 : 1;
        const auto travel = constant("QC_ENTRANCE_" + std::to_string(leaf) + "_TRAVEL");
        auto delta = std::int64_t(entrance_pose[leaf]) * travel / (constant("QC_ENTRANCE_STEPS") * 4);
        if (leaf == 0)
            delta = -delta;
        if (shot)
            delta = game_asr(delta, 1);
        if (tag < 3)
        {
            if (axis_a[tag] == 1)
                distance += delta * game_s16(data, pos);
            else if (axis_b[tag] == 1)
                distance += delta * game_s16(data, pos + 2);
        }
        else if (tag == 4)
            distance += delta;
    }
    if (tag < 3)
        return std::int64_t(p[axis_a[tag]]) * game_s16(data, pos) +
               std::int64_t(p[axis_b[tag]]) * game_s16(data, pos + 2) - distance;
    auto translated = distance;
    if (tag >= 6)
    {
        const auto pose = tag == 6 ? door_pose : button_pose;
        const auto travel = constant(tag == 6 ? "QC_DOOR_TRAVEL" : "QC_BUTTON_TRAVEL");
        const auto steps = constant(tag == 6 ? "QC_DOOR_STEPS" : "QC_BUTTON_STEPS");
        auto delta = -std::int64_t(pose) * travel / (steps * 4);
        if (shot)
            delta = game_asr(delta, 1);
        translated += static_cast<std::int32_t>(delta);
    }
    return std::int64_t(p[axis_a[tag]]) - translated;
}

GamePoint GameplaySession::Impl::plane_normal(GameWord ref, bool shot)
{
    const std::string prefix = shot ? "SHOT" : "WALK";
    const auto& data = bytes(shot ? "QuakeBSPShotHull.bin" : "QuakeBSPWalkHull.bin");
    const auto offset = plane_offset(ref, constant(prefix + "_HULL_EXTENDED_PLANES", 0) != 0);
    const auto pos = std::size_t(constant(prefix + "_HULL_PLANES")) + offset;
    const unsigned tag = ref >> 13;
    GamePoint normal{};
    if (basic() && tag == 6)
    {
        normal = {
            game_s16(data, pos),
            game_s16(data, pos + 2),
            game_s16(data, std::size_t(constant(prefix + "_HULL_THIRD_COEFFICIENTS")) + offset / 4)
        };
    }
    else if (tag < 3)
    {
        normal[axis_a[tag]] = game_s16(data, pos);
        normal[axis_b[tag]] = game_s16(data, pos + 2);
    }
    else
        normal[axis_a[tag]] = 16384;
    if (ref & 1)
        for (auto& v : normal)
            v = gs(-v);
    return normal;
}

bool GameplaySession::Impl::entrance_contains_player(unsigned leaf, GameWord candidate_pose, const GamePoint& point)
{
    if (basic() || leaf > 1)
        return false;
    const auto steps = constant("QC_ENTRANCE_STEPS");
    if (candidate_pose > steps)
        throw std::runtime_error("entrance collision pose exceeds its table");
    const auto prefix = "WALK_ENTRANCE_" + std::to_string(leaf);
    const auto begin = gw(constant(prefix + "_NODE_BEGIN"));
    const auto end = gw(constant(prefix + "_NODE_END"));
    auto node = gw(constant(prefix + "_ROOT"));
    const auto travel = constant("QC_ENTRANCE_" + std::to_string(leaf) + "_TRAVEL");
    const auto sign = leaf == 0 ? -1 : 1;
    const auto change = sign * (std::int64_t(candidate_pose) - entrance_pose[leaf]) * travel / (steps * 4);
    const auto& data = bytes("QuakeBSPWalkHull.bin");
    for (unsigned visited = 0; visited < 4096; ++visited)
    {
        if (gs(node) < 0)
            return node == 0xfffe;
        // EMPTY edges in the union can enter the next model. Query only this leaf.
        if (node < begin || node >= end)
            return false;
        const auto ref = game_u16(data, node);
        if ((ref & 6) != (leaf == 0 ? 2 : 4))
            throw std::runtime_error("entrance hull has another model's plane");
        auto distance = plane_distance(ref, point, false);
        const auto tag = ref >> 13;
        const auto pos = std::size_t(constant("WALK_HULL_PLANES")) + (ref & 0x1ff8);
        if (tag < 3)
        {
            if (axis_a[tag] == 1)
                distance -= change * game_s16(data, pos);
            else if (axis_b[tag] == 1)
                distance -= change * game_s16(data, pos + 2);
        }
        else if (tag == 4)
            distance -= change;
        node = game_u16(data, node + (distance < 0 ? 4 : 2));
    }
    throw std::runtime_error("entrance point query exceeded its node bound");
}

bool GameplaySession::Impl::point_solid(const GamePoint& point)
{
    const auto& data = bytes("QuakeBSPWalkHull.bin");
    const auto box = constant("QC_EXPLOBOX");
    auto node = gw(constant(box && field(box, "SOLID") ? "WALK_EXPLOBOX_ROOT" : "WALK_HULL_ROOT"));
    for (unsigned i = 0; i < 4096; ++i)
    {
        if (gs(node) < 0)
            return node == 0xfffe;
        const auto ref = game_u16(data, node);
        node = game_u16(data, node + (plane_distance(ref, point, false) < 0 ? 4 : 2));
    }
    throw std::runtime_error("gameplay point hull exceeded node bound");
}

GameplayTrace GameplaySession::Impl::trace(const GamePoint& from, const GamePoint& to, bool shot, bool skin)
{
    const auto& data = bytes(shot ? "QuakeBSPShotHull.bin" : "QuakeBSPWalkHull.bin");
    const std::string prefix = shot ? "SHOT" : "WALK";
    struct Interval
    {
        GameWord node, lo, hi, enter;
    };
    std::vector<Interval> stack;
    const auto box = constant("QC_EXPLOBOX");
    const auto root = !shot && box && field(box, "SOLID") ? "WALK_EXPLOBOX_ROOT" : prefix + "_HULL_ROOT";
    Interval current{gw(constant(root)), 0, 4096, 0xffff};
    unsigned limit = shot || basic() ? 4096 : 512;
    bool exhausted = false;
    for (;;)
    {
        if (--limit == 0)
        {
            exhausted = true;
            current.enter = 0xffff;
            current.lo = 0;
            current.node = 0xfffe;
        }
        if (gs(current.node) < 0)
        {
            const bool solid = shot ? current.node != 0xffff : current.node == 0xfffe;
            if (solid || exhausted)
            {
                GameplayTrace hit;
                hit.hit = true;
                hit.fraction = current.lo;
                hit.plane = current.enter;
                hit.terminal = current.node;
                if (exhausted)
                {
                    if (shot)
                        ++fault;
                    else
                        ++walk.trace_fault;
                }
                if (!shot)
                    ++walk.impacts;
                if (current.enter == 0xffff)
                {
                    hit.start_solid = true;
                    if (!shot)
                        ++walk.startsolid;
                    hit.result = from;
                    return hit;
                }
                hit.normal = plane_normal(current.enter, shot);
                auto safe = current.lo;
                if (!shot && skin)
                {
                    unsigned dominant = 0;
                    for (unsigned i = 0; i < 3; ++i)
                        dominant = std::max(dominant, unsigned(std::abs(int(gs(to[i] - from[i])))));
                    const auto inset = dominant > 2 ? game_fraction(2, dominant) : 4096;
                    safe = current.lo >= inset ? gw(current.lo - inset) : 0;
                    for (unsigned tries = 0; safe && tries < 7; ++tries)
                    {
                        if (!point_solid(interpolate(from, to, safe)))
                            break;
                        safe = gw(safe >> 1);
                        if (tries == 6)
                            safe = 0;
                    }
                }
                hit.result = interpolate(from, to, safe);
                return hit;
            }
            if (stack.empty())
                return GameplayTrace{to, {}, 4096, 0xffff, current.node, false, false};
            current = stack.back();
            stack.pop_back();
            continue;
        }
        const auto ref = game_u16(data, current.node);
        const auto front = game_u16(data, current.node + 2), back = game_u16(data, current.node + 4);
        const auto d0 = plane_distance(ref, from, shot), d1 = plane_distance(ref, to, shot);
        if (d0 >= 0 && d1 >= 0)
        {
            current.node = front;
            continue;
        }
        if (d0 < 0 && d1 < 0)
        {
            current.node = back;
            continue;
        }
        const auto mid = game_fraction(
            static_cast<std::uint32_t>(std::abs(d0)),
            static_cast<std::uint32_t>(std::abs(d0) + std::abs(d1))
        );
        const auto near_node = d0 >= 0 ? front : back, far_node = d0 >= 0 ? back : front;
        const auto oriented = gw(ref | (d0 < 0 ? 1 : 0));
        if (mid <= current.lo)
        {
            if (mid == current.lo)
                current.enter = oriented;
            current.node = far_node;
            continue;
        }
        if (mid > current.hi)
        {
            current.node = near_node;
            continue;
        }
        if (stack.size() >= std::size_t(constant(prefix + "_HULL_STACK_ENTRIES")))
        {
            exhausted = true;
            current.enter = 0xffff;
            current.lo = 0;
            current.node = 0xfffe;
            continue;
        }
        stack.push_back({far_node, mid, current.hi, oriented});
        current.node = near_node;
        current.hi = mid;
    }
}

void GameplaySession::Impl::walk_gravity(int previous_velocity)
{
    int displacement = 0;
    const auto increments = queued_input ? input_vblanks : 1;
    for (unsigned i = 0; i < increments; ++i)
    {
        walk.velocity_z = std::max<std::int16_t>(-4096, gs(walk.velocity_z - 57));
        displacement += queued_input ? walk.velocity_z : game_asr(walk.velocity_z, 4);
    }
    walk_vertical(queued_input ? game_asr(displacement + 8, 4) : displacement, previous_velocity);
}

void GameplaySession::Impl::walk_vertical(int displacement, int previous_velocity)
{
    auto to = walk.from;
    const int z = int(to[2]) + displacement;
    if (z >= -32768 && z <= 32767)
        to[2] = gs(z);
    const auto hit = trace(walk.from, to);
    walk.from = hit.result;
    walk.grounded = 0;
    if (hit.hit)
    {
        walk.velocity_z = 0;
        if (hit.plane != 0xffff && (hit.plane & 0x1ff8) >= constant("WALK_BUTTON_PLANE") &&
            (hit.plane & 0x1ff8) < constant("WALK_BUTTON_PLANE_END"))
            walk.button_contact = 1;
        if (hit.normal[2] >= 11469)
        {
            walk.grounded = 1;
            queue_landing(previous_velocity);
        }
    }
}

bool GameplaySession::Impl::landing_in_water() const
{
    const auto& data = bytes("QuakeBSPLandingWater.bin");
    auto node = gw(constant("WALK_LANDING_WATER_ROOT"));
    for (std::size_t remaining = data.size() / 14 + 1; remaining; --remaining)
    {
        if (gs(node) < 0)
            return node == 0xffff;
        auto distance = std::int64_t(game_s32(data, node + 10));
        for (std::size_t axis = 0; axis < 3; ++axis)
            distance += int(gs(game_u16(data, node + 4 + 2 * axis))) * walk.from[axis];
        node = game_u16(data, node + (distance < 0 ? 2 : 0));
    }
    throw std::runtime_error("landing point-contents tree exceeded its node bound");
}

void GameplaySession::Impl::queue_landing(int previous_velocity)
{
    if (previous_velocity >= -(300 * 256 / 60) ||
        !assets().constants.contains("WALK_LANDING_WATER_ROOT"))
        return;
    if (landing_in_water())
        walk.landing = LandingCue::water;
    else
        walk.landing = previous_velocity < -(650 * 256 / 60) ? LandingCue::hard : LandingCue::normal;
}

void GameplaySession::Impl::finish_landing()
{
    const auto landing = walk.landing;
    walk.landing = LandingCue::none;
    if (landing == LandingCue::none || gs(player("HEALTH")) <= 0)
        return;
    if (landing == LandingCue::hard)
    {
        field(512, "HEALTH") = gw(gs(player("HEALTH")) - environmental_damage(5));
        damage_flash = 4;
    }
    ++sounds;
    play_sound(landing == LandingCue::water ? "player/h2ojump.wav" :
        landing == LandingCue::hard ? "player/land2.wav" : "player/land.wav", 512, 2);
}

// Horizontal velocity uses signed Q4 units per admitted three-VBlank step.
// Keep the player's velocity separate from the displacement left after impact.
GamePoint GameplaySession::Impl::walk_run(GamePoint wish, int target_speed)
{
    auto& velocity = walk.velocity_xy;
    if (walk.grounded && (velocity[0] || velocity[1]))
    {
        const int speed = int(std::sqrt(velocity[0] * velocity[0] + velocity[1] * velocity[1]));
        GamePoint feet{};
        for (unsigned axis = 0; axis < 2; ++axis)
        {
            const auto ratio = game_fraction(std::abs(velocity[axis]), speed);
            const int offset = (ratio + 16) >> 5;
            feet[axis] = gs(game_asr(walk.from[axis], 1) + (velocity[axis] < 0 ? -offset : offset));
        }
        feet[2] = gs(game_asr(walk.from[2], 1) - 24 * 8);
        auto below = feet;
        below[2] = gs(below[2] - 34 * 8);
        const int friction_factor = trace(feet, below, true, false).hit ? 1 : 2;
        const int drop = (std::max(speed, 80) * friction_factor + 2) / 5;
        if (drop >= speed)
            velocity = {};
        else
        {
            const auto ratio = game_fraction(speed - drop, speed);
            for (auto& axis : velocity)
                axis = gs(game_asr(axis * ratio + 2048, 12));
        }
    }
    if (wish[0] || wish[1])
    {
        const int projection = game_asr(velocity[0] * wish[0] + velocity[1] * wish[1] + 128, 8);
        const int gain = std::clamp((walk.grounded ? target_speed : 24) - projection, 0, target_speed / 2);
        for (unsigned axis = 0; axis < 2; ++axis)
            velocity[axis] = gs(std::clamp(velocity[axis] + game_asr(wish[axis] * gain + 128, 8), -1600, 1600));
    }
    return {velocity[0], velocity[1], 0};
}

static GamePoint clip_walk_velocity(GamePoint velocity, const GameplayTrace& hit)
{
    if (hit.start_solid)
        return {};
    const auto into = game_asr(velocity[0] * hit.normal[0] + velocity[1] * hit.normal[1], 14);
    if (into < 0)
        for (unsigned axis = 0; axis < 2; ++axis)
            velocity[axis] = gs(std::clamp(velocity[axis] - game_asr(into * hit.normal[axis], 14), -1600, 1600));
    return velocity;
}

GamePoint GameplaySession::Impl::walk_horizontal(GamePoint wish, bool& can_step, GameWord& step_plane)
{
    auto to = add_point(walk.from, wish);
    auto hit = trace(walk.from, to);
    if (!hit.hit)
    {
        walk.from = hit.result;
        return wish;
    }
    auto velocity = clip_walk_velocity(wish, hit);
    if (hit.plane != 0xffff && (hit.plane & 0x1ff8) >= constant("WALK_BUTTON_PLANE") &&
        (hit.plane & 0x1ff8) < constant("WALK_BUTTON_PLANE_END"))
        walk.button_contact = 1;
    const auto plane = hit.plane & 0x1ff8;
    const bool step_face = constant("QC_E1M1_PLATFORM_FIRST")
        ? plane < constant("WALK_BUTTON_PLANE") || plane >= constant("WALK_EXIT_PLANE_FIRST")
        : plane < constant("WALK_DOOR_PLANE");
    if (hit.plane != 0xffff && step_face && hit.normal[2] >= -11469 && hit.normal[2] < 11469)
    {
        can_step = true;
        step_plane = hit.plane;
    }
    GamePoint residual{};
    std::int64_t dot = 0;
    for (unsigned i = 0; i < 3; ++i)
    {
        residual[i] = gs(to[i] - hit.result[i]);
        dot += std::int64_t(residual[i]) * hit.normal[i];
    }
    walk.from = hit.result;
    if (dot >= 0)
        return velocity;
    const auto projected = gs(game_asr(dot, 14));
    bool nonzero = false;
    for (unsigned i = 0; i < 3; ++i)
    {
        residual[i] = gs(residual[i] - game_asr(std::int64_t(projected) * hit.normal[i], 14));
        nonzero |= residual[i] != 0;
    }
    if (nonzero)
    {
        ++walk.slides;
        hit = trace(walk.from, add_point(walk.from, residual));
        walk.from = hit.result;
        if (hit.hit)
            velocity = clip_walk_velocity(velocity, hit);
        if (hit.hit && hit.plane != 0xffff && (hit.plane & 0x1ff8) >= constant("WALK_BUTTON_PLANE") &&
            (hit.plane & 0x1ff8) < constant("WALK_BUTTON_PLANE_END"))
            walk.button_contact = 1;
    }
    return velocity;
}

int GameplaySession::Impl::liquid_contents(const GamePoint& eye, int height) const
{
    const int z = eye[2] + height * 16;
    if (z >= liquid_ceiling)
        return -1;
    int node = liquid_root;
    while (node >= 0)
    {
        const auto [nx, ny, nz, distance, front, back] = liquid_nodes.at(std::size_t(node));
        node = nx * eye[0] + ny * eye[1] + nz * z >= distance ? front : back;
    }
    return node;
}

void GameplaySession::Impl::liquid_effects()
{
    if (liquid_type == -4 && !player("RADSUIT_FINISHED") && slime_damage_next < clock)
    {
        slime_damage_next = gw(clock + 64);
        field(512, "HEALTH") = gw(gs(player("HEALTH")) - environmental_damage(4 * water_level));
        damage_flash = 4;
    }
    if (in_water != (water_level > 0))
    {
        in_water = water_level > 0;
        if (in_water)
            slime_damage_next = 0;
        ++sounds;
    }
}

void GameplaySession::Impl::walk_breath_tick(bool submerged, int vblanks)
{
    const int air_limit = 12 * 60 / vblanks;
    if (!submerged)
    {
        // The surfacing tick follows the last submerged tick.
        if (air_ticks >= 3 * 60 / vblanks)
            ++sounds;
        air_ticks = drown_cooldown = drown_damage = 0;
        return;
    }
    if (!liquid_nodes.empty() && player("RADSUIT_FINISHED"))
    {
        air_ticks = 0;
        return;
    }
    if (air_ticks < air_limit + 1)
        ++air_ticks;
    if (air_ticks <= air_limit)
        return;
    if (drown_cooldown)
    {
        --drown_cooldown;
        return;
    }
    drown_cooldown = 60 / vblanks;
    drown_damage = std::max(drown_damage, 2) + 2;
    if (drown_damage > 15)
        drown_damage = 10;
    field(512, "HEALTH") = gw(gs(player("HEALTH")) - environmental_damage(drown_damage));
    damage_flash = 4;
}

// SV_WaterMove normalizes the three-axis wish, applies friction to the full
// current velocity, then accelerates by the difference in speeds. QuakeC's
// WaterMove applies its waterlevel-dependent drag after the engine movement.
GamePoint GameplaySession::Impl::swim_move(int forward, int side, int yaw_angle, int pitch_angle, bool slow)
{
    // Q4 displacement at the playable 20 Hz step. The stored Z velocity
    // uses Q8 units per VBlank and is converted once on entry and exit.
    const auto sine = [](int angle) {
        return int(std::lround(256 * std::sin((angle & 255) * (2 * std::numbers::pi / 256))));
    };
    const auto project = [](int value, int factor) { return game_asr(value * factor + 128, 8); };
    const auto length = [](const GamePoint& v) {
        const int squared = v[0] * v[0] + v[1] * v[1] + v[2] * v[2];
        return int(std::sqrt(double(squared)));
    };
    const int command = forward * (slow ? 160 : 320);
    const int horizontal = project(command, sine(pitch_angle + 64));
    const int cy = sine(yaw_angle + 64), sy = sine(yaw_angle);
    GamePoint wish{gs(project(horizontal, cy) - project(side * 280, sy)),
                   gs(project(horizontal, sy) + project(side * 280, cy)),
                   gs(forward || side ? project(command, sine(pitch_angle)) : -48)};
    GamePoint velocity{walk.velocity_xy[0], walk.velocity_xy[1], gs(game_asr(walk.velocity_z * 3 + 8, 4))};
    for (auto& component : velocity)
        component = gs(int(component) * 4 / 5);
    const int magnitude = length(wish);
    const int target = (std::min(256, magnitude) * 179 + 128) / 256;
    const int add = std::clamp(target - length(velocity), 0, target / 2);
    const int ratio = magnitude ? add * 4096 / magnitude : 0;
    const int drag = water_level == 3 ? 14418 : 15073;
    for (unsigned i = 0; i < 3; ++i)
    {
        const int accelerated = velocity[i] + game_asr(wish[i] * ratio + 2048, 12);
        velocity[i] = gs(accelerated * drag / 16384);
    }
    walk.velocity_xy = {velocity[0], velocity[1]};
    walk.velocity_z = gs(int(velocity[2]) * 16 / 3);
    return velocity;
}

// Stock CheckWaterJump traces from eight and thirty-two units above the edict origin.
// The packed point hull uses Q3 positions relative to that origin.
bool GameplaySession::Impl::water_jump(int facing_yaw, int facing_pitch, int vblanks)
{
    if (water_level == 0)
        walk.water_jump_ticks = 0;
    if (!walk.water_jump_ticks)
    {
        if (water_level != 2)
            return false;
        GamePoint start{}, end{};
        for (unsigned axis = 0; axis < 3; ++axis)
            start[axis] = gs(game_asr(walk.from[axis], 1));
        start[2] = gs(start[2] + 8 * 8);
        end = start;
        const auto pitch_cos = move_cosine(facing_pitch);
        const std::array facing{move_cosine(facing_yaw), move_sine(facing_yaw)};
        for (unsigned axis = 0; axis < 2; ++axis)
            end[axis] = gs(start[axis] + game_asr(facing[axis] * pitch_cos * 6 + 16, 5));
        const auto lower = trace(start, end, true, false);
        if (!lower.hit || lower.start_solid)
            return false;
        start[2] = gs(start[2] + 24 * 8);
        end[2] = start[2];
        if (trace(start, end, true, false).hit)
            return false;
        for (unsigned axis = 0; axis < 2; ++axis)
            walk.water_jump_move[axis] = gs(game_asr(-lower.normal[axis] * (50 * vblanks * 16 / 60), 14));
        walk.velocity_z = 225 * 256 / 60;
        walk.water_jump_ticks = 2 * 60 / vblanks;
        walk.jump_consumed = true;
    }
    --walk.water_jump_ticks;
    return true;
}

void GameplaySession::Impl::walk_tick()
{
    const auto yaw_pending = pending_yaw_valid;
    checkpoint("walk.yawGate");
    if (yaw_pending)
        return;
    const auto menu_value = gameplay_menu();
    checkpoint("walk.menu");
    const auto blocked = menu_value || gameplay_release();
    checkpoint("walk.gate");
    if (blocked || gs(player("HEALTH")) <= 0)
        return;
    walk.from = walk.pending ? walk.pending_xyz : camera;
    ++walk.ticks;
    walk.button_contact = 0;
    const int previous_velocity = walk.velocity_z;
    const auto latched_buttons = gameplay_buttons(), latched_yaw = yaw;
    const auto latched_pitch = pitch;
    const bool walk_speed = input_clock.active.walk_speed;
    checkpoint("walk.input");
    GamePoint wish{};
    const auto fb = latched_buttons & (0x40 | 0x8000), lr = latched_buttons & (0x4000 | 0x80);
    if (!liquid_nodes.empty())
    {
        liquid_type = liquid_contents(walk.from, -45);
        water_level = liquid_type < -2 ? 1 : 0;
        if (water_level && liquid_contents(walk.from, -18) < -2)
            water_level = liquid_contents(walk.from, 0) < -2 ? 3 : 2;
    }
    const bool swimming = liquid_nodes.empty() ? hub_can_swim(walk.from) : water_level >= 2;
    const bool block_reverse = hub_teleport_cooldown && hub_skills.empty() && !hub_teleporters.empty();
    const int forward = (fb == 0x40) - (fb == 0x8000 && !block_reverse);
    const int side = (lr == 0x4000) - (lr == 0x80);
    int swim_wish_z = 0;
    int target_speed = 256;
    if (queued_input && !swimming)
    {
        if (forward || side)
        {
            // Quake uses 400 or 200 forward/back input and 350 strafe.
            // The 320-unit cap still applies to strafing and diagonal input.
            if (walk_speed && !side)
                target_speed = 160;
            const int diagonal = walk_speed ? 43 : 29;
            const int angle = latched_yaw + (forward < 0 ? 128 : 0) +
                              (forward ? diagonal * side * forward : 64 * side);
            const auto radians = (angle & 255) * (2 * std::numbers::pi / 256);
            wish[0] = gs(std::lround(256 * std::cos(radians)));
            wish[1] = gs(std::lround(256 * std::sin(radians)));
        }
    }
    else
    {
        wish[0] = gs(forward * move_cosine(latched_yaw));
        wish[1] = gs(forward * move_sine(latched_yaw));
        if (forward && swimming && latched_pitch)
        {
            const auto cosine_pitch = move_cosine(latched_pitch);
            for (unsigned axis = 0; axis < 2; ++axis)
            {
                const int scaled = (std::abs(wish[axis]) * cosine_pitch + 16) >> 5;
                wish[axis] = gs(wish[axis] < 0 ? -scaled : scaled);
            }
            swim_wish_z = forward * move_sine(latched_pitch) * 16;
        }
        wish[0] = gs(wish[0] - side * move_sine(latched_yaw));
        wish[1] = gs(wish[1] + side * move_cosine(latched_yaw));
        if (queued_input)
            for (auto& axis : wish)
                axis = gs(axis * int(input_vblanks));
    }
    walk.jump_held = latched_buttons & 0x10;
    if (!walk.jump_held)
        walk.jump_consumed = false;
    if (swim_sound_cooldown)
        --swim_sound_cooldown;
    const int vblanks = queued_input ? input_vblanks : 1;
    auto eye_probe = walk.from;
    eye_probe[2] = gs(eye_probe[2] + 18 * 16);
    const bool submerged = liquid_nodes.empty() ? swimming && hub_can_swim(eye_probe) : water_level == 3;
    if (!hub_swim_zones.empty() || !liquid_nodes.empty())
        walk_breath_tick(submerged, vblanks);
    const bool ledge_jump = !liquid_nodes.empty() && water_jump(latched_yaw, latched_pitch, vblanks);
    if (queued_input && !swimming && !ledge_jump)
        wish = walk_run(wish, target_speed);
    if (ledge_jump)
    {
        walk.support_valid = false;
        walk.velocity_xy = walk.water_jump_move;
        wish = {walk.velocity_xy[0], walk.velocity_xy[1], 0};
        walk_vertical(game_asr(walk.velocity_z * vblanks + 8, 4), previous_velocity);
    }
    else if (swimming)
    {
        const bool stock_swim = queued_input && !liquid_nodes.empty();
        int displacement_z = 0;
        if (stock_swim)
        {
            wish = swim_move(forward, side, latched_yaw, latched_pitch, walk_speed);
            displacement_z = wish[2];
            wish[2] = 0;
        }
        else
            walk.velocity_xy = {};
        walk.grounded = 0;
        walk.support_valid = false;
        if (walk.jump_held)
        {
            if (!swim_sound_cooldown)
            {
                swim_sound_cooldown = gw(60 / vblanks + 1);
                ++sounds;
            }
            const int speed = liquid_type == -4 ? 80 : 100;
            walk.velocity_z = gs((speed * 256 + 30) / 60);
            walk_vertical(speed * 16 * vblanks / 60, previous_velocity);
        }
        else if (stock_swim)
            walk_vertical(displacement_z, previous_velocity);
        else
        {
            const int water_friction = ((60 - 4 * vblanks) * 16384 + 30) / 60;
            auto velocity = game_asr(walk.velocity_z * water_friction, 14);
            if (swim_wish_z)
            {
                const int direction = swim_wish_z > 0 ? 1 : -1;
                const int target = std::abs(swim_wish_z);
                const int steer_accel = (10 * vblanks * 16384 + 30) / 60;
                const int impulse = game_asr(target * steer_accel, 14);
                velocity += direction * std::clamp(target - direction * velocity, 0, impulse);
            }
            else if (!wish[0] && !wish[1])
            {
                constexpr int idle_speed = (42 * 256 + 30) / 60;
                const int idle_accel = (42 * 256 * 10 * vblanks + 1800) / 3600;
                velocity -= std::clamp(idle_speed - std::abs(velocity), 0, idle_accel);
            }
            const int water_drag = submerged ? 24 : 16;
            const int retention = ((600 - water_drag * vblanks) * 16384 + 300) / 600;
            walk.velocity_z = gs(game_asr(velocity * retention, 14));
            walk_vertical(game_asr(walk.velocity_z * vblanks + 8, 4), previous_velocity);
        }
    }
    else if (walk.jump_held && !walk.jump_consumed && walk.grounded)
    {
        auto to = walk.from;
        to[2] = gs(to[2] - 4);
        const auto support = trace(walk.from, to);
        if (support.hit && support.normal[2] >= 11469)
        {
            walk.velocity_z = 1152;
            walk.jump_consumed = true;
            walk.grounded = 0;
            walk.support_valid = false;
            ++sounds;
            play_sound("player/plyrjmp8.wav", 512, 2);
        }
    }
    if (!wish[0] && !wish[1])
    {
        if (!swimming && !ledge_jump && (!walk.support_valid || walk.support_pose != support_pose_key() || walk.support_xyz != walk.from))
        {
            walk_gravity(previous_velocity);
            walk.support_valid = walk.grounded != 0;
            walk.support_pose = support_pose_key();
            walk.support_xyz = walk.from;
        }
    }
    else
    {
        walk.support_valid = false;
        if (!swimming && !ledge_jump)
            walk_gravity(previous_velocity);
        const auto base = walk.from;
        const auto saved_contact = walk.button_contact;
        bool can_step = false;
        GameWord step_plane = 0;
        auto velocity = walk_horizontal(wish, can_step, step_plane);
        if (can_step && walk.grounded &&
            (step_plane != walk.failed_step_plane || gw(walk.ticks - 1) != walk.failed_step_tick))
        {
            walk.failed_step_plane = step_plane;
            walk.failed_step_tick = walk.ticks;
            const auto unstepped = walk.from;
            const auto unstepped_contact = walk.button_contact;
            walk.from = base;
            walk.button_contact = saved_contact;
            auto to = walk.from;
            to[2] = gs(to[2] + 288);
            auto up = trace(walk.from, to);
            walk.from = up.result;
            bool accepted = false;
            if (!up.hit)
            {
                bool ignored = false;
                GameWord ignored_plane = 0;
                const auto raised_velocity = walk_horizontal(wish, ignored, ignored_plane);
                const auto progress =
                    std::int32_t(gs(walk.from[0] - unstepped[0])) * wish[0] +
                    std::int32_t(gs(walk.from[1] - unstepped[1])) * wish[1];
                if (progress > 0)
                {
                    to = walk.from;
                    to[2] = gs(to[2] - 292);
                    auto down = trace(walk.from, to);
                    walk.from = down.result;
                    if (down.hit && down.normal[2] >= 11469 && gs(walk.from[2] - base[2]) > 0)
                    {
                        accepted = true;
                        velocity = raised_velocity;
                        walk.failed_step_plane = 0xffff;
                        ++walk.stairs;
                        if (down.plane != 0xffff && (down.plane & 0x1ff8) >= constant("WALK_BUTTON_PLANE") &&
                            (down.plane & 0x1ff8) < constant("WALK_BUTTON_PLANE_END"))
                            walk.button_contact = 1;
                    }
                }
            }
            if (!accepted)
            {
                walk.from = unstepped;
                walk.button_contact = unstepped_contact;
            }
        }
        if (queued_input && (!swimming || !liquid_nodes.empty()) && !ledge_jump)
            walk.velocity_xy = {velocity[0], velocity[1]};
    }
    checkpoint("walk.publish");
    if (walk.button_contact)
        contact = 1;
    bool changed = walk.from[0] != camera[0];
    checkpoint("walk.compareX");
    if (!changed)
    {
        changed = walk.from[1] != camera[1];
        checkpoint("walk.compareY");
    }
    if (!changed)
    {
        changed = walk.from[2] != camera[2];
        checkpoint("walk.compareZ");
    }
    if (changed)
    {
        checkpoint("walk.commit");
        walk.pending = false;
        checkpoint("walk.clear");
        walk.pending_xyz = walk.from;
        checkpoint("walk.readyBefore");
        walk.pending = true;
    }
    checkpoint("walk.end");
}

} // namespace quake_bsp_reference
