#include "gameplay_internal.hpp"

namespace quake_bsp_reference {
namespace {
GameWord abs_word(GameWord value)
{
    return gs(value) < 0 ? gw(-value) : value;
}
unsigned angle_index(GameWord angle)
{
    return std::min(255u, unsigned(angle) / 90u);
}
GameWord rebase_time(GameWord value)
{
    return value >= 0x4000 ? gw(value - 0x4000) : 0;
}
} // namespace

GameWord GameplaySession::Impl::vector_length(bool normalize)
{
    std::array<GameWord, 3> vector{};
    for (unsigned axis = 0; axis < 3; ++axis)
        vector[axis] = abs_word(g(8 + 2 * axis));
    unsigned shift = 0;
    while ((vector[0] | vector[1] | vector[2]) >= 0x2000)
    {
        for (auto& component : vector)
            component >>= 1;
        ++shift;
    }
    std::uint32_t sum = 0;
    for (const auto component : vector)
        sum += std::uint32_t(component) * component;
    GameWord root = 0;
    for (GameWord bit = 0x2000; bit; bit >>= 1)
    {
        const auto trial = gw(root | bit);
        if (std::uint32_t(trial) * trial <= sum)
            root = trial;
    }
    if (normalize)
    {
        for (unsigned axis = 0; axis < 3; ++axis)
        {
            GameWord component = root ? gw((game_fraction(vector[axis], root) + 32) >> 6) : GameWord{0};
            if (gs(g(8 + 2 * axis)) < 0)
                component = gw(-component);
            g(2 + 2 * axis) = component;
        }
        return root;
    }
    while (shift--)
    {
        root = gw(root << 1);
        if (root & 0x8000)
            return 0x7fff;
    }
    return root;
}

void GameplaySession::Impl::player_aim()
{
    const auto forward_offset = constant("QC_GLOBAL_FORWARD");
    GamePoint emitter{}, start{}, forward{}, end{};
    for (unsigned ax = 0; ax < 3; ++ax)
    {
        emitter[ax] = gs(field(512, "ORIGIN", ax));
        start[ax] = gs(emitter[ax] + (ax == 2 ? 20 * 8 : 0));
        forward[ax] = gs(g(forward_offset + ax * 2));
        end[ax] = gs(start[ax] + forward[ax] * 256);
    }
    // Private aim traces never write the QuakeC trace result or run weapon touch effects.
    const auto saved_entity = global("TRACE_ENT"), saved_mask = g(20), saved_passed = g(26);
    g(20) = 0;
    g(26) = 512;
    const auto trace_target = [&](const GamePoint& to) {
        auto result = trace(start, to, true, false);
        global("TRACE_ENT") = 0;
        trace_actors(result, start, to);
        return global("TRACE_ENT");
    };
    const auto unit_vector = [&](const GamePoint& input) {
        std::array<GameWord, 3> saved{};
        GamePoint value{};
        for (unsigned ax = 0; ax < 3; ++ax)
        {
            saved[ax] = g(8 + 2 * ax);
            g(8 + 2 * ax) = gw(input[ax]);
        }
        vector_length(true);
        for (unsigned ax = 0; ax < 3; ++ax)
        {
            value[ax] = gs(g(2 + 2 * ax));
            g(8 + 2 * ax) = saved[ax];
        }
        return value;
    };
    const auto direct = trace_target(end);
    GameWord best = 0;
    int best_score = 3810; // ceil(stock sv_aim .93 * 4096)
    if (!direct || field(direct, "TAKEDAMAGE") != 2 * 64)
    {
        const auto candidate = [&](GameWord actor) {
            if (field(actor, "TAKEDAMAGE") != 2 * 64)
                return;
            GamePoint center{}, delta{};
            for (unsigned ax = 0; ax < 3; ++ax)
            {
                const auto extent = gs(field(actor, "MINS", ax) + field(actor, "MAXS", ax));
                center[ax] = gs(field(actor, "ORIGIN", ax) + game_asr(extent, 1));
                delta[ax] = gs(center[ax] - start[ax]);
            }
            const auto direction = unit_vector(delta);
            int score = 0;
            for (unsigned ax = 0; ax < 3; ++ax)
                score += direction[ax] * forward[ax];
            if (score >= best_score && trace_target(center) == actor)
            {
                best_score = score;
                best = actor;
            }
        };
        for (auto actor = constant("QC_GRUNT"); actor < constant("QC_GRUNT_DROP"); actor += 512)
            candidate(gw(actor));
        candidate(gw(constant("QC_EXPLOBOX")));
    }
    auto aim = forward;
    if (best)
    {
        GamePoint delta{};
        GameWord range = 0;
        for (unsigned ax = 0; ax < 3; ++ax)
        {
            delta[ax] = gs(field(best, "ORIGIN", ax) - emitter[ax]);
            range = gw(range + game_q6_mul(gw(delta[ax]), gw(forward[ax])));
        }
        for (unsigned ax = 0; ax < 2; ++ax)
            delta[ax] = gs(game_q6_mul(range, gw(forward[ax])));
        aim = unit_vector(delta);
    }
    last_aim_target = best;
    last_aim = aim;
    global("TRACE_ENT") = saved_entity;
    g(20) = saved_mask;
    g(26) = saved_passed;
    for (unsigned ax = 0; ax < 3; ++ax)
        g(2 + ax * 2) = gw(aim[ax]);
}

GameWord GameplaySession::Impl::vector_yaw(GameWord x, GameWord y)
{
    if (!(x | y))
        return 0;
    auto denominator = abs_word(x), numerator = abs_word(y);
    const bool steep = numerator >= denominator;
    if (steep)
        std::swap(numerator, denominator);
    const auto offset = std::size_t(((game_fraction(numerator, denominator) + 32) >> 5) & 0xfffe);
    auto angle = game_u16(bytes("QuakeBSPGruntAtan.bin"), offset);
    if (steep)
        angle = gw(90 * 64 - angle);
    if (gs(x) < 0)
        angle = gw(180 * 64 - angle);
    if (gs(y) < 0 && angle)
        angle = gw(360 * 64 - angle);
    return angle;
}

void GameplaySession::Impl::grunt_change_yaw(GameWord actor)
{
    auto delta = gs(field(actor, "IDEAL_YAW") - field(actor, "ANGLES", 1));
    if (delta >= 0)
    {
        if (delta > 180 * 64)
            delta = gs(delta - 360 * 64);
    }
    else if (delta < -180 * 64)
        delta = gs(delta + 360 * 64);
    const auto speed = field(actor, "YAW_SPEED");
    if (delta >= 0)
    {
        if (gw(delta) >= speed)
            delta = gs(speed);
    }
    else if (gw(delta) < gw(-speed))
        delta = gs(-speed);
    auto angle = gs(field(actor, "ANGLES", 1) + delta);
    if (angle < 0)
        angle = gs(angle + 360 * 64);
    else if (gw(angle) >= 360 * 64)
        angle = gs(angle - 360 * 64);
    field(actor, "ANGLES", 1) = gw(angle);
}

void GameplaySession::Impl::grunt_tick(unsigned elapsed_units)
{
    if (active_impacts)
        tick_impacts();
    const bool has_actors = constant("QC_GRUNT_COUNT") != 0;
    clock = gw(clock + elapsed_units);
    if (constant("QC_FLUORESCENT_STYLE"))
        fluorescent_phase = gw((fluorescent_phase + elapsed_units) % 160);
    if (clock >= 0x6000)
    {
        clock = gw(clock - 0x4000);
        if (has_actors)
        {
            for (auto actor = constant("QC_GRUNT"); actor < constant("QC_GRUNT_DROP"); actor += 512)
                for (const auto name : {"NEXTTHINK", "ATTACK_FINISHED", "SHOW_HOSTILE", "PAIN_FINISHED"})
                    field(std::size_t(actor), name) = rebase_time(field(std::size_t(actor), name));
            if (const auto box = constant("QC_EXPLOBOX"))
                field(box, "NEXTTHINK") = rebase_time(field(box, "NEXTTHINK"));
            global("SIGHT_ENTITY_TIME") = rebase_time(global("SIGHT_ENTITY_TIME"));
            field(512, "SHOW_HOSTILE") = rebase_time(field(512, "SHOW_HOSTILE"));
        }
        if (constant("QC_POWERUP_COUNT"))
        {
            field(512, "SUPER_DAMAGE_FINISHED") = rebase_time(player("SUPER_DAMAGE_FINISHED"));
            quad_warn_next = rebase_time(quad_warn_next);
            if (constant("QC_POWERUP_COUNT") >= 2)
            {
                field(512, "RADSUIT_FINISHED") = rebase_time(player("RADSUIT_FINISHED"));
                suit_warn_next = rebase_time(suit_warn_next);
                slime_damage_next = rebase_time(slime_damage_next);
            }
            field(512, "SUPER_SOUND") = rebase_time(player("SUPER_SOUND"));
        }
        field(512, "ATTACK_FINISHED") = rebase_time(field(512, "ATTACK_FINISHED"));
        field(512, "NEXTTHINK") = rebase_time(field(512, "NEXTTHINK"));
    }
    global("TIME") = clock;
    if (intermission_phase != 2 && constant("QC_POWERUP_COUNT"))
        powerup_tick();
    if (!has_actors)
        return;
    const auto old_health = gs(player("HEALTH"));
    for (auto cursor = constant("QC_GRUNT"); cursor < constant("QC_GRUNT_DROP"); cursor += 512)
    {
        const auto actor = gw(cursor);
        if (constant("QC_GIB_FIRST_ROW") && (e(actor, gib_records + gib_row) & 0x8000))
        {
            gib_advance(actor, elapsed_units);
            continue;
        }
        if (constant("QC_BACKPACK_COUNT") && e(actor, pack_life))
            backpack_advance(actor, elapsed_units);
        if (assets().constants.contains("QC_DOG_FIRST") && actor >= constant("QC_DOG_FIRST"))
            dog_advance(actor);
        if (clock < field(actor, "NEXTTHINK") || !field(actor, "THINK"))
            continue;
        if (!field(actor, "ENEMY") && gs(field(actor, "MOVETARGET")) >= 0 && gs(field(actor, "HEALTH")) > 0)
        {
            bool distant = false;
            for (unsigned axis = 0; axis < 2; ++axis)
                distant |= gw(player("ORIGIN", axis) - field(actor, "ORIGIN", axis) + 1024 * 8) >= 2048 * 8;
            if (distant)
                continue;
        }
        global("SELF") = actor;
        global("OTHER") = 0;
        budget = 4096;
        invoke(field(actor, "THINK"));
    }
    if (const auto box = constant("QC_EXPLOBOX"); box && e(box, constant("QC_EXPLOSION_LIFE")))
        --e(box, constant("QC_EXPLOSION_LIFE"));
    if (const auto box = constant("QC_EXPLOBOX"); box && field(box, "THINK") && clock >= field(box, "NEXTTHINK"))
    {
        global("SELF") = gw(box);
        global("OTHER") = 0;
        budget = 4096;
        invoke(field(box, "THINK"));
    }
    if (old_health > gs(player("HEALTH")))
    {
        checkpoint("flash.damageBefore");
        damage_flash = 4;
        checkpoint("flash.damageAfter");
    }
}

void GameplaySession::Impl::grunt_builtin(std::int16_t function)
{
    switch (function)
    {
    case -13:
        g(2) = vector_yaw(g(8), g(10));
        return;
    case -17:
        g(2) = gs(player("HEALTH")) > 0 ? 512 : 0;
        return;
    case -38:
        g(2) = gw(g(8) + 63) & 0xffc0;
        return;
    case -40: {
        const auto actor = g(8);
        GamePoint position{};
        for (unsigned axis = 0; axis < 3; ++axis)
            position[axis] = gs(field(actor, "ORIGIN", axis) * 2);
        g(2) = grunt_check_bottom(actor, position) ? 64 : 0;
        return;
    }
    case -49:
        grunt_change_yaw(global("SELF"));
        return;
    case -32:
        g(2) = grunt_move(global("SELF"), g(8), g(14)) ? 64 : 0;
        return;
    case -67:
        grunt_move_to_goal(global("SELF"), g(8));
        return;
    case -4:
        if (constant("QC_GIB_FIRST_ROW") && field(g(8), "MODEL") != constant("QC_BACKPACK_MODEL"))
        {
            for (unsigned axis = 0; axis < 3; ++axis)
            {
                const auto mins = gs(g(14 + 2 * axis)) / 8;
                const auto maxs = gs(g(20 + 2 * axis)) / 8;
                field(g(8), "MINS", axis) = gw(mins);
                field(g(8), "MAXS", axis) = gw(maxs);
                field(g(8), "SIZE", axis) = gw(maxs - mins);
            }
            return;
        }
        if (constant("QC_BACKPACK_COUNT"))
            backpack_spawn();
        return;
    case -48:
        if (constant("QC_IMPACT_ROW") && g(20) == 73 * 64 && gs(g(26)) > 0)
        {
            GamePoint origin{}, delta{};
            for (unsigned axis = 0; axis < 3; ++axis)
            {
                origin[axis] = gs(g(8 + 2 * axis));
                const int direction = gs(g(14 + 2 * axis));
                if (global("SELF") == constant("QC_GRUNT_DROP"))
                    origin[axis] = gs(origin[axis] + (direction < 0 ? -1 : 1) * ((std::abs(direction) + 40) / 80));
                delta[axis] = gs(3 * std::clamp(direction / 4, -128, 127));
            }
            const auto count = g(26) / 64;
            spawn_impact(origin, delta, count <= 8 ? 10 : count <= 18 ? 15 : count <= 40 ? 20 : 25);
            return;
        }
        if (const auto box = constant("QC_EXPLOBOX"); box && global("SELF") == box && g(26) == 255 * 64)
        {
            e(box, constant("QC_EXPLOSION_LIFE")) = gw(2 * constant("QC_EXPLOSION_PHASES"));
            for (unsigned axis = 0; axis < 3; ++axis)
                e(box, constant("QC_EXPLOSION_EMITTER") + 2 * axis) =
                    gw(game_asr(int(gs(g(8 + 2 * axis))) - (axis == 2 ? 176 : 0) + 16, 5));
        }
        return;
    case -14:
        g(2) = gw(constant("QC_GRUNT_DROP"));
        return;
    case -3:
        if (constant("QC_EXPLOBOX") && g(8) == constant("QC_EXPLOBOX"))
            ++revision;
        else if (g(8) != constant("QC_GRUNT_DROP") &&
            !(constant("QC_GIB_FIRST_ROW") && g(8) == global("SELF") &&
              (g(14) == constant("QC_GIB_MODEL_0") || g(14) == constant("QC_GIB_MODEL_1"))))
            throw std::runtime_error("invalid gameplay death-drop edict");
        field(g(8), "MODEL") = g(14);
        return;
    default:
        throw std::runtime_error("unsupported gameplay builtin " + std::to_string(function));
    }
}

void GameplaySession::Impl::backpack_spawn()
{
    const auto actor = global("SELF");
    if (actor < constant("QC_GRUNT") || actor >= constant("QC_DOG_FIRST"))
        return;
    const auto drop = std::size_t(constant("QC_GRUNT_DROP"));
    e(actor, pack_life) = 120 * 64;
    e(actor, pack_shells) = field(drop, "AMMO_SHELLS");
    for (unsigned axis = 0; axis < 3; ++axis)
    {
        e(actor, pack_origin + 2 * axis) = gw(field(actor, "ORIGIN", axis) - (axis == 2 ? 24 * 8 : 0));
        e(actor, pack_velocity + 2 * axis) = gw(game_asr(gs(field(drop, "VELOCITY", axis)), 3));
    }
}

void GameplaySession::Impl::backpack_advance(GameWord actor, unsigned elapsed_units)
{
    auto& life = e(actor, pack_life);
    life = gw(life - std::min<unsigned>(life, elapsed_units));
    if (!life)
        return;
    auto velocity = [&](unsigned axis) -> GameWord& { return e(actor, pack_velocity + 2 * axis); };
    auto origin = [&](unsigned axis) -> GameWord& { return e(actor, pack_origin + 2 * axis); };
    if (velocity(0) || velocity(1) || velocity(2))
    {
        velocity(2) = gw(velocity(2) - 40 * 8);
        GamePoint from{}, to{};
        for (unsigned axis = 0; axis < 3; ++axis)
        {
            from[axis] = gs(2 * (origin(axis) + (axis == 2 ? 24 * 8 : 0)));
            to[axis] = gs(from[axis] + gs(velocity(axis)) / 10);
        }
        const auto sweep = trace(from, to);
        for (unsigned axis = 0; axis < 3; ++axis)
            origin(axis) = gw(game_asr(gs(sweep.result[axis] + 1), 1) - (axis == 2 ? 24 * 8 : 0));
        if (sweep.hit)
        {
            if (sweep.normal[2] >= 11469)
                velocity(0) = velocity(1) = velocity(2) = 0;
            else
            {
                std::int32_t dot = 0;
                for (unsigned axis = 0; axis < 3; ++axis)
                    dot += gs(velocity(axis)) * sweep.normal[axis];
                const auto backoff = game_asr(dot, 14);
                for (unsigned axis = 0; axis < 3; ++axis)
                    velocity(axis) = gw(velocity(axis) - game_asr(backoff * sweep.normal[axis], 14));
            }
        }
    }
    if (gs(player("HEALTH")) <= 0)
        return;
    for (unsigned axis = 0; axis < 3; ++axis)
    {
        const auto delta = gs(player("ORIGIN", axis) - origin(axis));
        if (delta < -(axis == 2 ? 33 : 48) * 8 || delta > (axis == 2 ? 81 : 48) * 8)
            return;
    }
    life = 0;
    notify_pickup(PickupNotice::backpack);
    auto& shells = field(512, "AMMO_SHELLS");
    shells = gw(std::min<int>(100 * 64, shells + e(actor, pack_shells)));
    if (player("WEAPON") == 64 || player("WEAPON") == 128)
        field(512, "CURRENTAMMO") = shells;
    ++sounds;
}

void GameplaySession::Impl::grunt_ride_lift(GameWord next_pose)
{
    if (basic() || next_pose == door_pose)
        return;
    const auto travel = constant("QC_DOOR_TRAVEL"), steps = constant("QC_DOOR_STEPS");
    const auto translation = [&](GameWord pose) { return gs(-std::int64_t(pose) * travel / (steps * 4)); };
    const auto previous = game_asr(translation(door_pose), 1);
    const auto delta = gs(game_asr(translation(next_pose), 1) - previous);
    const auto origin = assets().manifest.at("worldOrigin");
    const auto top =
        gw(previous + std::llround((double(constant("QC_DOOR_MAX_Z")) - origin[2].get<double>() + 22) * 8));
    const auto lower_x = gw(std::llround((double(constant("QC_DOOR_MIN_X")) - origin[0].get<double>()) * 8));
    const auto lower_y = gw(std::llround((double(constant("QC_DOOR_MIN_Y")) - origin[1].get<double>()) * 8));
    for (auto cursor = constant("QC_GRUNT"); cursor < constant("QC_GRUNT_DROP"); cursor += 512)
    {
        const auto actor = gw(cursor);
        if (gw(field(actor, "ORIGIN", 2) - top + 1) >= 3)
            continue;
        if (gw(field(actor, "ORIGIN", 0) - lower_x) >= (constant("QC_DOOR_MAX_X") - constant("QC_DOOR_MIN_X")) * 8)
            continue;
        if (gw(field(actor, "ORIGIN", 1) - lower_y) >= (constant("QC_DOOR_MAX_Y") - constant("QC_DOOR_MIN_Y")) * 8)
            continue;
        for (const auto name : {"ORIGIN", "ABSMIN", "ABSMAX"})
            field(actor, name, 2) = gw(field(actor, name, 2) + delta);
    }
}

bool GameplaySession::Impl::grunt_move(GameWord actor, GameWord angle, GameWord distance, bool turn_only)
{
    if (!(field(actor, "FLAGS") & 512))
        return false;
    // This unsigned classification also accepts yaw-90 and yaw+180 across the sign bit.
    if (angle >= 540 * 64)
        angle = gw(angle + 360 * 64);
    if (angle >= 360 * 64)
        angle = gw(angle - 360 * 64);
    const auto index = angle_index(angle);
    GamePoint base{}, target{};
    for (unsigned axis = 0; axis < 3; ++axis)
        base[axis] = gs(field(actor, "ORIGIN", axis) * 2);
    const auto component = [&](std::int16_t trig) { return game_asr(gs(game_q6_mul(gw(trig), distance) + 2), 2); };
    target = {
        gs(gw(base[0] + component(cosine(index))) & 0xfffe),
        gs(gw(base[1] + component(sine(index))) & 0xfffe),
        base[2]
    };
    auto across = trace(base, target);
    auto drop_from = target;
    if (across.hit)
    {
        auto up_to = base;
        up_to[2] = gs(base[2] + 288);
        const auto up = trace(base, up_to);
        if (up.result[2] == base[2])
        {
            ++grunt_blocked_moves;
            return false;
        }
        auto raised = base;
        raised[2] = up.result[2];
        target[2] = raised[2];
        across = trace(raised, target);
        if (across.hit)
        {
            ++grunt_blocked_moves;
            return false;
        }
        drop_from = target;
    }
    auto drop_to = target;
    drop_to[2] = gs(base[2] - 288);
    const auto down = trace(drop_from, drop_to);
    const auto unsupported = [&] {
        ++grunt_unsupported_moves;
        ++grunt_blocked_moves;
        return false;
    };
    if (!down.hit || down.normal[2] < 11469)
        return unsupported();
    target[2] = down.result[2];
    if (!grunt_clear_of_player(actor, target))
    {
        ++grunt_blocked_moves;
        return false;
    }
    GamePoint q3{};
    for (unsigned axis = 0; axis < 3; ++axis)
        q3[axis] = gs(game_asr(gs(target[axis] + 1), 1));
    if (!grunt_check_bottom(actor, target))
        return unsupported();
    if (constant("QC_GRUNT_COUNT"))
        for (auto cursor = constant("QC_GRUNT"); cursor < constant("QC_GRUNT_DROP"); cursor += 512)
        {
            const auto other = gw(cursor);
            if (other == actor || !field(other, "SOLID"))
                continue;
            bool overlap = true;
            for (unsigned axis = 0; axis < 3; ++axis)
                overlap &= abs_word(gw(field(other, "ORIGIN", axis) - q3[axis])) < (axis == 2 ? 512 : 256);
            if (overlap)
            {
                ++grunt_blocked_moves;
                return false;
            }
        }
    if (turn_only)
        return true;
    ++grunt_moves;
    const auto actor_index = std::size_t((actor - constant("QC_GRUNT")) / 512);
    if (actor_index < gr_actor_moves.size())
        ++gr_actor_moves[actor_index];
    if (gs(target[2] - base[2]) >= 16)
        ++grunt_steps_up;
    grunt_store_origin(actor, q3);
    return true;
}

bool GameplaySession::Impl::grunt_clear_of_player(GameWord actor, const GamePoint& position)
{
    if (!player("SOLID"))
        return true;
    const auto dog = assets().constants.contains("QC_DOG_FIRST") && actor >= constant("QC_DOG_FIRST");
    for (unsigned axis = 0; axis < 2; ++axis)
        if (abs_word(gw(player("ORIGIN", axis) * 2 - position[axis])) >= (dog ? 768 : 512))
            return true;
    const auto delta = gs(player("ORIGIN", 2) * 2 - position[2]);
    return abs_word(gw(delta)) >= (delta < 0 ? 896 : 1024);
}

bool GameplaySession::Impl::grunt_check_bottom(GameWord actor, const GamePoint& position)
{
    GamePoint q3{};
    for (unsigned axis = 0; axis < 3; ++axis)
        q3[axis] = gs(game_asr(gs(position[axis] + 1), 1));
    const auto foot_z = gs(q3[2] - 192);
    const auto dog = assets().constants.contains("QC_DOG_FIRST") && actor >= constant("QC_DOG_FIRST");
    const auto radius = dog ? 256 : 128;
    const std::array<std::array<int, 2>, 5> offsets{{
        {0, 0}, {-radius, -radius}, {-radius, radius}, {radius, -radius}, {radius, radius}}};
    std::int16_t minimum = 0;
    for (std::size_t i = 0; i < offsets.size(); ++i)
    {
        const GamePoint from{gs(q3[0] + offsets[i][0]), gs(q3[1] + offsets[i][1]), foot_z};
        auto to = from;
        to[2] = gs(foot_z - 288);
        const auto support = trace(from, to, true, false);
        if (!support.hit)
            return false;
        if (!i)
            minimum = gs(support.result[2] - 144);
        else if (gs(support.result[2] - minimum) < 0)
            return false;
    }
    return true;
}

void GameplaySession::Impl::grunt_store_origin(GameWord actor, const GamePoint& position)
{
    for (unsigned axis = 0; axis < 3; ++axis)
    {
        field(actor, "ORIGIN", axis) = gw(position[axis]);
        field(actor, "ABSMIN", axis) = gw(position[axis] + field(actor, "MINS", axis) - 8);
        field(actor, "ABSMAX", axis) = gw(position[axis] + field(actor, "MAXS", axis) + 8);
    }
    const auto corner = field(actor, "MOVETARGET");
    if (gs(corner) >= 0 || field(actor, "ENEMY"))
        return;
    for (unsigned axis = 0; axis < 3; ++axis)
    {
        const auto center = patrol_word(corner, 2 * axis);
        if (gs(field(actor, "ABSMIN", axis) - center) > 9 * 8 ||
            gs(center - field(actor, "ABSMAX", axis)) > 9 * 8)
            return;
    }
    const auto next = patrol_word(corner, 6);
    field(actor, "MOVETARGET") = field(actor, "GOALENTITY") = next;
    field(actor, "IDEAL_YAW") = vector_yaw(gw(patrol_word(next, 0) - position[0]),
                                            gw(patrol_word(next, 2) - position[1]));
}

GameWord GameplaySession::Impl::patrol_word(GameWord token, unsigned offset)
{
    return game_u16(bytes("QuakeBSPQuakeCGruntFields.bin"),
                    std::size_t(constant("QC_PATROL_TABLE") + token - constant("QC_PATROL_TOKEN")) + offset);
}

void GameplaySession::Impl::dog_advance(GameWord actor)
{
    if ((field(actor, "FLAGS") & 512) || !field(actor, "TOUCH") ||
        !(field(actor, "VELOCITY", 0) | field(actor, "VELOCITY", 1) | field(actor, "VELOCITY", 2)))
        return;
    global("SELF") = actor;
    field(actor, "VELOCITY", 2) = gw(field(actor, "VELOCITY", 2) - 40 * 8);
    GamePoint from{}, to{};
    for (unsigned axis = 0; axis < 3; ++axis)
    {
        from[axis] = gs(field(actor, "ORIGIN", axis) * 2);
        to[axis] = gs(from[axis] + gs(field(actor, "VELOCITY", axis)) / 10);
    }
    const auto sweep = trace(from, to);
    const bool hit_player = !grunt_clear_of_player(actor, sweep.result);
    const bool landed = !hit_player && sweep.hit && sweep.normal[2] >= 11469;
    if (!hit_player)
    {
        GamePoint position{};
        for (unsigned axis = 0; axis < 3; ++axis)
            position[axis] = gs(game_asr(gs(sweep.result[axis] + 1), 1));
        grunt_store_origin(actor, position);
    }
    if (landed)
        field(actor, "FLAGS") |= 512;
    if (landed || hit_player)
    {
        global("OTHER") = hit_player ? gw(constant("QC_ENTITY_STRIDE")) : 0;
        budget = 4096;
        invoke(field(actor, "TOUCH"));
        field(actor, "VELOCITY", 0) = 0;
        field(actor, "VELOCITY", 1) = 0;
        if (landed)
            field(actor, "VELOCITY", 2) = 0;
    }
}

void GameplaySession::Impl::grunt_move_to_goal(GameWord actor, GameWord distance)
{
    const auto goal = field(actor, "GOALENTITY");
    const bool patrol = gs(goal) < 0 && assets().constants.contains("QC_PATROL_TOKEN");
    if (!goal || (!patrol && goal >= constant("QC_GRUNT_DROP")))
        return;
    const auto delta = [&](unsigned axis) {
        const auto point = patrol ? patrol_word(goal, 2 * axis) : field(goal, "ORIGIN", axis);
        return gs(point - field(actor, "ORIGIN", axis));
    };
    const auto dx = delta(0), dy = delta(1);
    if (!patrol)
    {
        const auto close = gw((distance >> 3) + 272);
        auto dz = delta(2);
        dz = dz < 0 && goal == 512 ? gs(-dz - 192) : gs(abs_word(gw(dz)) - 256);
        if (abs_word(gw(dx)) <= close && abs_word(gw(dy)) <= close && (dz < 0 || gw(dz) <= close))
            return;
    }
    const auto old = angle_index(field(actor, "IDEAL_YAW")) >> 5, reverse = old ^ 4;
    const auto step_direction = [&](GameWord yaw_value) {
        field(actor, "IDEAL_YAW") = yaw_value;
        grunt_change_yaw(actor);
        auto delta = gs(field(actor, "ANGLES", 1) - field(actor, "IDEAL_YAW"));
        if (delta < 0)
            delta = gs(delta + 360 * 64);
        return grunt_move(actor, yaw_value, distance, gw(delta) > 45 * 64 && gw(delta) < 315 * 64);
    };
    if ((random(true) & 3) != 1 && step_direction(field(actor, "IDEAL_YAW")))
        return;
    const auto axis = [](std::int16_t value) -> int { return value > 80 ? 0 : value < -80 ? 4 : -1; };
    auto nav_x = axis(dx), nav_y = axis(dy);
    if (nav_y >= 0)
        nav_y += 2;
    const auto try_octant = [&](int direction) {
        return direction >= 0 && unsigned(direction) != reverse && step_direction(gw(direction * 45 * 64));
    };
    if (nav_x >= 0 && nav_y >= 0)
    {
        int diagonal = nav_x ? (nav_y + 1) & 7 : nav_y - 1;
        if (diagonal == 7 && nav_x)
            diagonal = 5;
        else if (diagonal == 5 && !nav_x)
            diagonal = 7;
        if (try_octant(diagonal))
            return;
    }
    if ((random(true) & 1) || abs_word(gw(dx)) < abs_word(gw(dy)))
        std::swap(nav_x, nav_y);
    if (try_octant(nav_x) || try_octant(nav_y) || try_octant(int(old)))
        return;
    if (random(true) & 1)
    {
        for (int direction = 7; direction >= 0; --direction)
            if (try_octant(direction))
                return;
    }
    else
    {
        for (int direction = 0; direction < 8; ++direction)
            if (try_octant(direction))
                return;
    }
    if (!step_direction(gw(reverse * 45 * 64)))
        field(actor, "IDEAL_YAW") = gw(old * 45 * 64);
}

} // namespace quake_bsp_reference
