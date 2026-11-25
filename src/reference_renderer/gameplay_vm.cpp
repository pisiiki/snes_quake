#include "gameplay_internal.hpp"

namespace quake_bsp_reference {

static GameWord armor_saving(GameWord type, GameWord damage_q6)
{
    const float factor = type == 38 ? 0.6f : (type ? 0.3f : 0.0f);
    return gw(static_cast<int>(std::ceil(factor * (damage_q6 / 64.0f))) * 64);
}

void GameplaySession::Impl::invoke(GameWord function)
{
    const auto& functions = bytes("QuakeBSPQuakeCFunctions.bin");
    const auto& code = bytes("QuakeBSPQuakeCCode.bin");
    const auto fp = std::size_t(function) * 16;
    if (fp + 16 > functions.size())
        throw std::runtime_error("gameplay function out of bounds");
    const auto entry = game_u16(functions, fp);
    if (entry == 0x8000)
        throw std::runtime_error("unsupported gameplay function " + std::to_string(function));
    if (gs(entry) < 0)
    {
        builtin(gs(entry));
        return;
    }
    const auto local = game_u16(functions, fp + 2), count = game_u16(functions, fp + 4);
    const auto depth_limit = constant("QC_EXPLOBOX") ? 20 : 12;
    if (depth >= depth_limit || saved_local_bytes + count > 256)
        throw std::runtime_error("gameplay VM stack exhausted at function " + std::to_string(function) +
            ", depth " + std::to_string(depth + 1) + ", local bytes " + std::to_string(saved_local_bytes + count));
    std::vector<GameWord> saved;
    for (unsigned i = 0; i < count; i += 2)
        saved.push_back(g(local + i));
    ++depth;
    saved_local_bytes += count;
    auto destination = local;
    for (unsigned parameter = 0; parameter < functions[fp + 6]; ++parameter)
        for (unsigned byte = 0; byte < functions[fp + 8 + parameter]; byte += 2)
        {
            g(destination) = g(8 + parameter * 6 + byte);
            destination = gw(destination + 2);
        }
    std::size_t pc = entry;
    bool finished = false;
    while (!finished)
    {
        if (--budget <= 0 || pc + 8 > code.size())
            throw std::runtime_error("gameplay VM instruction budget/range exhausted");
        const auto encoded = game_u16(code, pc), a = game_u16(code, pc + 2), b = game_u16(code, pc + 4),
                   c = game_u16(code, pc + 6);
        if (encoded & 1 || encoded >= 140)
            throw std::runtime_error("uncovered gameplay opcode at " + std::to_string(pc));
        pc += 8;
        ++statements;
        const auto op = encoded / 2;
        auto boolean = [&](bool value) { g(c) = value ? 64 : 0; };
        auto vector_binary = [&](bool subtract) {
            for (unsigned i = 0; i < 6; i += 2)
                g(c + i) = gw(subtract ? int(g(a + i)) - g(b + i) : int(g(a + i)) + g(b + i));
        };
        switch (op)
        {
        case 69:
            gib_capture(b != 0);
            [[fallthrough]];
        case 0:
        case 43:
            for (unsigned i = 0; i < 6; i += 2)
                g(2 + i) = g(a + i);
            finished = true;
            break;
        case 1:
            g(c) = game_q6_mul(g(a), g(b));
            break;
        case 2: {
            GameWord sum = 0;
            for (unsigned i = 0; i < 6; i += 2)
                sum = gw(sum + game_q6_mul(g(a + i), g(b + i)));
            g(c) = sum;
            break;
        }
        case 3:
        case 4: {
            const auto vector = op == 3 ? b : a, scalar = op == 3 ? a : b;
            for (unsigned i = 0; i < 6; i += 2)
                g(c + i) = game_q6_mul(g(vector + i), g(scalar));
            break;
        }
        case 5: {
            const auto dividend = std::int64_t(gs(g(a))), divisor = std::int64_t(gs(g(b)));
            if (!divisor)
                throw std::runtime_error("gameplay division by zero");
            const auto magnitude = ((std::abs(dividend) << 6) + std::abs(divisor) / 2) / std::abs(divisor);
            g(c) = gw((dividend < 0) != (divisor < 0) ? -magnitude : magnitude);
            break;
        }
        case 6:
            g(c) = gw(g(a) + g(b));
            break;
        case 7:
            vector_binary(false);
            break;
        case 8:
            g(c) = gw(g(a) - g(b));
            break;
        case 9:
            vector_binary(true);
            break;
        case 10:
        case 12:
        case 13:
        case 14:
            boolean(g(a) == g(b));
            break;
        case 11:
            boolean(g(a) == g(b) && g(a + 2) == g(b + 2) && g(a + 4) == g(b + 4));
            break;
        case 15:
        case 17:
        case 18:
        case 19:
            boolean(g(a) != g(b));
            break;
        case 20:
            boolean(gs(g(a)) <= gs(g(b)));
            break;
        case 21:
            boolean(gs(g(a)) >= gs(g(b)));
            break;
        case 22:
            boolean(gs(g(a)) < gs(g(b)));
            break;
        case 23:
            boolean(gs(g(a)) > gs(g(b)));
            break;
        case 24:
        case 26:
        case 27:
        case 28:
        case 29:
            g(c) = e(g(a), g(b));
            break;
        case 25:
            for (unsigned i = 0; i < 6; i += 2)
                g(c + i) = e(g(a), g(b) + i);
            break;
        case 30:
            g(c) = gw(g(a) + g(b));
            break;
        case 31:
        case 33:
        case 34:
        case 35:
        case 36:
            g(b) = g(a);
            break;
        case 32:
            for (unsigned i = 0; i < 6; i += 2)
                g(b + i) = g(a + i);
            break;
        case 37:
        case 39:
        case 40:
        case 41:
        case 42:
            e(0, g(b)) = g(a);
            break;
        case 38:
            for (unsigned i = 0; i < 6; i += 2)
                e(0, g(b) + i) = g(a + i);
            break;
        case 44:
        case 46:
        case 47:
        case 48:
            boolean(g(a) == 0);
            break;
        case 49:
            if (g(a))
                pc = b;
            break;
        case 50:
            if (!g(a))
                pc = b;
            break;
        case 51:
        case 52:
        case 53:
        case 54:
        case 55:
        case 56:
        case 57:
        case 58:
        case 59:
            invoke(g(a));
            break;
        case 60: {
            const auto actor = global("SELF");
            field(actor, "FRAME") = g(a);
            field(actor, "NEXTTHINK") = gw(global("TIME") + 6);
            field(actor, "THINK") = g(b);
            break;
        }
        case 61:
            pc = a;
            break;
        case 62:
            boolean(g(a) && g(b));
            break;
        case 63:
            boolean(g(a) || g(b));
            break;
        case 64:
            g(c) = gw((g(a) & g(b)) & 0xffc0);
            break;
        case 65:
            g(c) = gw((g(a) | g(b)) & 0xffc0);
            break;
        case 66:
            g(c) = g(a) & g(b);
            break;
        case 67:
            g(c) = g(a) | g(b);
            break;
        case 68: { // T_Damage immediately rounds saved armor up to whole points.
            g(c) = armor_saving(g(a), g(b));
            break;
        }
        default:
            throw std::runtime_error("unsupported gameplay opcode " + std::to_string(op));
        }
    }
    for (unsigned i = 0; i < saved.size(); ++i)
        g(local + i * 2) = saved[i];
    --depth;
    saved_local_bytes -= count;
}

void GameplaySession::Impl::event(GameWord actor, GameWord other, GameWord function, int statement_budget)
{
    global("SELF") = actor;
    global("OTHER") = other;
    field(actor, "LTIME") = 0;
    global("TIME") = clock;
    budget = statement_budget;
    ++callbacks;
    invoke(function);
}

GameWord GameplaySession::Impl::random(bool navigation)
{
    auto& rng = navigation ? nav_rng : shot_rng;
    if (!rng)
    {
        const auto seed = gameplay_rng_tick() | 1;
        checkpoint(navigation ? "rng.navSeed" : "rng.shotSeed");
        rng = gw(seed);
    }
    const auto bit = rng & 1;
    rng = gw((rng >> 1) ^ (bit ? 0xb400 : 0));
    return navigation ? gw(rng >> 8) : gw((rng >> 8) & 63);
}

void GameplaySession::Impl::play_vm_sound(GameWord sound)
{
    if (!collect_sound || !sound)
        return;
    constexpr std::pair<std::string_view, std::string_view> cues[] = {
        {"QC_SHOTGUN_SOUND", "weapons/guncock.wav"},
        {"QC_SSG_SOUND", "weapons/shotgn2.wav"},
        {"QC_SHELL_SOUND", "weapons/lock4.wav"},
        {"QC_AXE_HIT_SOUND", "player/axhit2.wav"},
        {"QC_EXPLOBOX_SOUND", "weapons/r_exp3.wav"},
        {"QC_LIFT_MOVE_SOUND", "doors/hydro1.wav"},
        {"QC_LIFT_STOP_SOUND", "doors/hydro2.wav"},
        {"QC_LIFT_BUTTON_SOUND", "buttons/switch21.wav"},
        {"QC_QUAD_SOUND", "items/damage3.wav"},
        {"QC_GIB_SOUND", "player/udeath.wav"},
        {"QC_GRUNT_SOUND_0", "soldier/sight1.wav"},
        {"QC_GRUNT_SOUND_1", "soldier/sattck1.wav"},
        {"QC_GRUNT_SOUND_2", "soldier/pain1.wav"},
        {"QC_GRUNT_SOUND_3", "soldier/pain2.wav"},
        {"QC_GRUNT_SOUND_4", "soldier/death1.wav"},
        {"QC_GRUNT_SOUND_5", "soldier/idle.wav"},
        {"QC_DOG_SOUND_0", "dog/dsight.wav"},
        {"QC_DOG_SOUND_1", "dog/dattack1.wav"},
        {"QC_DOG_SOUND_2", "dog/dpain1.wav"},
        {"QC_DOG_SOUND_3", "dog/ddeath.wav"},
        {"QC_DOG_SOUND_4", "dog/idle.wav"},
    };
    for (const auto& [key, name] : cues)
    {
        if (sound != constant(key))
            continue;
        const auto actor = g(8);
        const auto raw_channel = std::clamp<int>(gs(g(14)) / 64, 0, 7);
        const auto volume = std::clamp<int>(gs(g(26)) * 255 / 64, 0, 255);
        play_sound(name, actor, static_cast<std::uint8_t>(raw_channel), static_cast<std::uint8_t>(volume),
                   static_cast<std::uint8_t>(std::clamp<int>(gs(g(32)), 0, 255)));
        return;
    }
}

void GameplaySession::Impl::builtin(std::int16_t function)
{
    switch (function)
    {
    case -1:
        make_vectors();
        return;
    case -2: {
        const auto actor = g(8);
        for (unsigned i = 0; i < 3; ++i)
            field(actor, "ORIGIN", i) = g(14 + i * 2);
        e(actor, 400) = 0;
        return;
    }
    case -15: {
        const auto box = g(8);
        if (!constant("QC_EXPLOBOX") || box != constant("QC_EXPLOBOX"))
            throw std::runtime_error("unexpected removed gameplay edict");
        for (const auto name : {"MODEL", "SOLID", "THINK", "NEXTTHINK"})
            field(box, name) = 0;
        ++revision;
        return;
    }
    case -22: {
        const auto radius = gs(g(14)) / 8;  // Q6 radius in Q3 world coordinates.
        GameWord chain = 0;
        for (int i = 0; i < constant("QC_RADIUS_COUNT"); ++i)
        {
            const auto actor = gw(constant("QC_RADIUS_EDICT_" + std::to_string(i)));
            if (!field(actor, "SOLID"))
                continue;
            std::int64_t squared = 0;
            for (unsigned axis = 0; axis < 3; ++axis)
            {
                const auto center = gs(field(actor, "ORIGIN", axis)) +
                    (gs(field(actor, "MINS", axis)) + gs(field(actor, "MAXS", axis))) / 2;
                const auto delta = center - gs(g(8 + axis * 2));
                squared += std::int64_t(delta) * delta;
            }
            if (squared <= std::int64_t(radius) * radius)
            {
                field(actor, "CHAIN") = chain;
                chain = actor;
            }
        }
        g(2) = chain;
        return;
    }
    case -7:
        g(2) = random();
        return;
    case -8: {
        ++sounds;
        const auto sound = g(20);
        play_vm_sound(sound);
        if (sound == constant("QC_SHOTGUN_SOUND") || (constant("QC_SSG_SOUND") && sound == constant("QC_SSG_SOUND")))
        {
            ++shots;
            checkpoint("flash.muzzleBefore");
            flash = 3;
            checkpoint("flash.muzzleAfter");
        }
        else if (sound != constant("QC_SHELL_SOUND") && sound == constant("QC_GRUNT_SOUND_1"))
        {
            ++grunt_shots;
            const auto slot = std::size_t(gw(g(8) - constant("QC_GRUNT")) >> 9);
            ++gr_actor_shots.at(slot);
        }
        return;
    }
    case -9:
        vector_length(true);
        return;
    case -12: {
        const auto self = global("SELF");
        if (self >= constant("QC_GRUNT") && self < constant("QC_GRUNT_DROP"))
        {
            g(2) = vector_length(false);
            return;
        }
        if (constant("QC_EXPLOBOX") && self == constant("QC_EXPLOBOX"))
        {
            std::int64_t squared = 0;
            for (unsigned axis = 0; axis < 3; ++axis)
            {
                const auto component = gs(g(8 + axis * 2)) * 8;
                squared += std::int64_t(component) * component;
            }
            g(2) = static_cast<GameWord>(std::sqrt(static_cast<double>(squared)));
            return;
        }
        const auto active_axes = unsigned(g(8) != 0) + unsigned(g(10) != 0) + unsigned(g(12) != 0);
        if (active_axes > 1)
            throw std::runtime_error("unsupported non-axial pusher length");
        const auto component = g(8) ? g(8) : g(10) ? g(10) : g(12);
        g(2) = gw(std::abs(int(gs(component))));
        return;
    }
    case -16:
        trace_shot();
        return;
    case -18: {
        GameWord actor = g(8);
        const auto offset = g(14), name = g(20);
        g(2) = 0;
        while (std::size_t(actor) + 512 < edicts.size() * 2)
        {
            actor = gw(actor + 512);
            if (e(actor, offset) && e(actor, offset) == name)
            {
                g(2) = actor;
                break;
            }
        }
        return;
    }
    case -21:
    case -24:
        return;
    case -44:
        if (constant("QC_STOCK_AIM"))
        {
            player_aim();
            return;
        }
        for (unsigned i = 0; i < 6; i += 2)
            g(2 + i) = g(std::size_t(constant("QC_GLOBAL_FORWARD")) + i);
        return;
    case -52:
        if (constant("QC_IMPACT_ROW"))
        {
            if (g(14) == 23 * 64)
                impact_message = 1;
            else if (impact_message == 1 && (g(14) == 0 || g(14) == 2 * 64))
            {
                impact_message = 2;
                impact_style = g(14) ? 5 : 0;
            }
            else
                impact_message = 0;
        }
        ++effect_word;
        return;
    case -56:
        if (impact_message >= 2)
        {
            impact_origin[(impact_message - 2) / 2] = gs(g(14));
            impact_message += 2;
            if (impact_message == 8)
            {
                spawn_impact(impact_origin, {}, impact_style);
                impact_message = 0;
            }
        }
        ++effect_word;
        if (effect_word == 5 && global("SELF") == 512 && !axe_selected)
            ++impact_events;
        return;
    default:
        grunt_builtin(function);
        return;
    }
}

void GameplaySession::Impl::make_vectors()
{
    const auto self = global("SELF");
    if (self >= constant("QC_GRUNT") && self < constant("QC_GRUNT_DROP"))
    {
        shot_yaw = gw(g(10) / 90);
        shot_pitch = g(8) ? gw(-int(g(8) / 90)) & 255 : 0;
    }
    const auto sy = gw(sine(shot_yaw)), cy = gw(cosine(shot_yaw)), sp = gw(sine(shot_pitch)),
               cp = gw(cosine(shot_pitch));
    global("RIGHT") = sy;
    g(std::size_t(constant("QC_GLOBAL_RIGHT")) + 2) = gw(-cy);
    g(std::size_t(constant("QC_GLOBAL_RIGHT")) + 4) = 0;
    global("FORWARD") = game_q6_mul(cy, cp);
    g(std::size_t(constant("QC_GLOBAL_FORWARD")) + 2) = game_q6_mul(sy, cp);
    g(std::size_t(constant("QC_GLOBAL_FORWARD")) + 4) = sp;
    global("UP") = game_q6_mul(cy, gw(-sp));
    g(std::size_t(constant("QC_GLOBAL_UP")) + 2) = game_q6_mul(sy, gw(-sp));
    g(std::size_t(constant("QC_GLOBAL_UP")) + 4) = cp;
}

void GameplaySession::Impl::shot_tick()
{
    const auto limit = constant("BSP_WEAPON_LIVE_TICKS", 36);
    if (shot_clock < limit)
        shot_clock = gw(std::min<std::int64_t>(limit, shot_clock + (queued_input ? input_vblanks : 1)));
    const auto menu_value = gameplay_menu();
    checkpoint("shot.menu");
    const auto blocked = menu_value || gameplay_release();
    checkpoint("shot.menuGate");
    if (blocked)
        return;
    if ((constant("QC_NAIL_COUNT") || constant("QC_CAMPAIGN_ITEMS")))
        nail_tick();
    const auto fire_buttons = gameplay_buttons();
    checkpoint("shot.buttons");
    const bool cycle = queued_input ? input_clock.active.cycle_weapon : cycle_weapon;
    if (constant("QC_AXE_FUNCTION") && cycle)
    {
        if ((constant("QC_NAIL_COUNT") || constant("QC_CAMPAIGN_ITEMS")))
        {
            nail_frame = 0;
            unsigned next = 0;
            const auto current = axe_selected ? 0 : player("WEAPON") / 64;
            if (current < 1 && player("AMMO_SHELLS"))
                next = 1;
            else if (current < 2 && (player("ITEMS") & 2) && player("AMMO_SHELLS"))
                next = 2;
            else if (current < 4 && (player("ITEMS") & 4) && player("AMMO_NAILS"))
                next = 4;
            axe_selected = next == 0;
            if (next)
                field(512, "WEAPON") = gw(next * 64);
            field(512, "CURRENTAMMO") = next == 4 ? player("AMMO_NAILS") : next ? player("AMMO_SHELLS") : 0;
        }
        else
            axe_selected ^= 1;
        axe_pending = 0;
        shot_clock = gw(limit);
        shot_view = shots;
    }
    if (gs(player("HEALTH")) <= 0)
    {
        axe_pending = nail_frame = 0;
        return;
    }
    if (axe_selected)
    {
        if (axe_pending && shot_clock >= 12)
        {
            axe_pending = 0;
            global("TIME") = clock;
            global("SELF") = 512;
            global("OTHER") = 0;
            // The cartridge samples this aim inside AxeService. The shotgun
            // firing fences belong exclusively to ShotgunFireBegin.
            shot_yaw = yaw & 255;
            shot_pitch = pitch & 255;
            budget = 4096;
            invoke(gw(constant("QC_AXE_FUNCTION")));
        }
        else if ((fire_buttons & 0x20) && clock >= player("ATTACK_FINISHED"))
        {
            field(512, "ATTACK_FINISHED") = gw(clock + 32);
            powerup_attack();
            ++axe_swings;
            axe_pending = 1;
            shot_clock = 0;
        }
        return;
    }
    if ((constant("QC_NAIL_COUNT") || constant("QC_CAMPAIGN_ITEMS")) && player("WEAPON") == 4 * 64)
    {
        nail_attack((fire_buttons & 0x20) != 0);
        return;
    }
    if (!(fire_buttons & 0x20) || clock < player("ATTACK_FINISHED"))
        return;
    if (!player("AMMO_SHELLS"))
    {
        if (constant("QC_SSG_SOUND") && player("WEAPON") == 2 * 64)
        {
            if ((player("ITEMS") & 4) && player("AMMO_NAILS"))
            {
                field(512, "WEAPON") = 4 * 64;
                field(512, "CURRENTAMMO") = player("AMMO_NAILS");
            }
            else
            {
                axe_selected = 1;
                field(512, "CURRENTAMMO") = 0;
            }
        }
        return;
    }
    global("TIME") = clock;
    global("SELF") = 512;
    global("OTHER") = 0;
    field(512, "BUTTON0") = 64;
    shot_yaw = yaw & 255;
    checkpoint("shot.yaw");
    shot_pitch = pitch & 255;
    checkpoint("shot.aim");
    budget = 4096;
    invoke(gw(constant("QC_WEAPON_FRAME")));
    shot_clock = 0;
}

void GameplaySession::Impl::nail_attack(bool fire)
{
    if (nail_frame)
    {
        if (--nail_next_frame)
            return;
    }
    else if (clock < player("ATTACK_FINISHED"))
        return;
    if (!fire)
    {
        nail_frame = 0;
        return;
    }
    if (!player("AMMO_NAILS"))
    {
        nail_frame = 0;
        if (player("AMMO_SHELLS"))
            field(512, "WEAPON") = (player("ITEMS") & 2) && player("AMMO_SHELLS") >= 2 * 64 ? 2 * 64 : 64;
        else
            axe_selected = 1;
        field(512, "CURRENTAMMO") = player("AMMO_SHELLS");
        return;
    }
    const auto slot = std::find_if(nails.begin(), nails.end(), [](const auto& n) { return !n.life; });
    if (slot == nails.end())
        return;
    global("SELF") = 512;
    shot_yaw = yaw & 255;
    shot_pitch = pitch & 255;
    make_vectors();
    if (constant("QC_STOCK_AIM"))
        player_aim();
    const auto direction = constant("QC_STOCK_AIM") ? 2 : constant("QC_GLOBAL_FORWARD");
    nail_frame = (nail_frame & 7) + 1;
    slot->yaw = shot_yaw;
    slot->life = 120;
    for (unsigned axis = 0; axis < 3; ++axis)
    {
        const auto right = gs(g(std::size_t(constant("QC_GLOBAL_RIGHT")) + 2 * axis));
        const auto forward = gs(g(direction + 2 * axis));
        const auto offset = axis == 2 ? 16 * 8 : game_asr(nail_frame & 1 ? right : -right, 1);
        slot->origin[axis] = gs(field(512, "ORIGIN", axis) + offset);
        slot->delta[axis] = gs(forward * 25);
        slot->remainder[axis] = 0;
    }
    ++nail_shots;
    nail_next_frame = 2;
    field(512, "ATTACK_FINISHED") = gw(clock + 13);
    field(512, "AMMO_NAILS") -= 64;
    field(512, "CURRENTAMMO") = player("AMMO_NAILS");
    powerup_attack();
    ++sounds;
    play_sound("weapons/rocket1i.wav", 512, 1);
}

void GameplaySession::Impl::spawn_impact(GamePoint origin, GamePoint delta, unsigned first_frame)
{
    auto& impact = combat_impacts[impact_next];
    impact_next = (impact_next + 1) % combat_impacts.size();
    if (!impact.life)
        ++active_impacts;
    impact = {origin, delta, {}, 9, first_frame};
}

void GameplaySession::Impl::spike_wall_impact()
{
    if (!constant("QC_IMPACT_ROW"))
        return;
    GamePoint origin{};
    for (unsigned axis = 0; axis < 3; ++axis)
        origin[axis] = gs(g(constant("QC_GLOBAL_TRACE_ENDPOS") + 2 * axis));
    spawn_impact(origin, {}, 0);
}

void GameplaySession::Impl::tick_impacts()
{
    for (auto& burst : combat_impacts)
    {
        if (!burst.life)
            continue;
        if (--burst.life == 0)
        {
            --active_impacts;
            continue;
        }
        for (unsigned axis = 0; axis < 3; ++axis)
        {
            const int step = burst.delta[axis] + burst.remainder[axis];
            burst.origin[axis] = gs(burst.origin[axis] + game_asr(step, 3));
            burst.remainder[axis] = gs(step & 7);
        }
    }
}

void GameplaySession::Impl::nail_tick()
{
    for (auto& nail : nails)
    {
        if (!nail.life)
            continue;
        for (unsigned axis = 0; axis < 3; ++axis)
        {
            g(8 + 2 * axis) = gw(nail.origin[axis]);
            const auto step = nail.delta[axis] + nail.remainder[axis];
            nail.remainder[axis] = gs(step & 3);
            nail.origin[axis] = gs(nail.origin[axis] + game_asr(step, 2));
            g(14 + 2 * axis) = gw(nail.origin[axis]);
        }
        g(20) = 0;
        g(26) = 512;
        const auto projectile = gw(constant("QC_GRUNT_DROP"));
        global("SELF") = projectile;
        trace_shot();
        if (global("TRACE_FRACTION") == 64)
        {
            --nail.life;
            continue;
        }
        nail.life = 0;
        const auto target = global("TRACE_ENT");
        if (!target || !field(target, "TAKEDAMAGE"))
        {
            ++nail_world_hits;
            spike_wall_impact();
            const auto random_byte = [this]() {
                nail_effect_rng = gw((nail_effect_rng >> 1) ^ ((nail_effect_rng & 1) ? 0xb400 : 0));
                return nail_effect_rng >> 8;
            };
            unsigned cue = 2;  // tink1, then ric1/ric2/ric3 in stock TE_SPIKE order
            if (!(random_byte() % 5))
            {
                const auto ricochet = random_byte() & 3;
                cue = ricochet == 1 ? 3 : ricochet == 2 ? 4 : 5;
            }
            nail_impact_sound = gw(cue);
            ++sounds;
            constexpr std::array impact_cues{
                "weapons/tink1.wav", "weapons/ric1.wav", "weapons/ric2.wav", "weapons/ric3.wav"
            };
            play_sound(impact_cues[cue - 2], 0xf200, 0);
            continue;
        }
        ++nail_actor_hits;
        if (constant("QC_NAIL_BLOOD"))
        {
            for (unsigned axis = 0; axis < 3; ++axis)
            {
                field(projectile, "ORIGIN", axis) = g(constant("QC_GLOBAL_TRACE_ENDPOS") + 2 * axis);
                field(projectile, "VELOCITY", axis) = gw(nail.delta[axis]);
            }
            g(8) = 9 * 64;
            budget = 4096;
            invoke(gw(constant("QC_NAIL_BLOOD")));
        }
        global("SELF") = projectile;
        global("TIME") = clock;
        g(8) = target;
        g(14) = projectile;
        g(20) = field(projectile, "OWNER") = 512;
        g(26) = 9 * 64;
        for (unsigned axis = 0; axis < 3; ++axis)
            field(projectile, "ORIGIN", axis) = g(std::size_t(constant("QC_GLOBAL_TRACE_ENDPOS")) + 2 * axis);
        budget = 4096;
        invoke(gw(constant("QC_NAIL_DAMAGE_FUNCTION")));
    }
}

void GameplaySession::Impl::notify_pickup(PickupNotice message)
{
    if (!constant("QC_PICKUP_NOTICES"))
        return;
    const auto add_row = [&](GameWord id) {
        const auto slot = pickup_notice_next / 2;
        checkpoint("pickup.rowBefore");
        pickup_notice_life[slot] = 180;
        checkpoint("pickup.rowAfter");
        pickup_notice_rows[slot] = id;
        pickup_notice_next = gw((pickup_notice_next + 2) & 6);
    };
    add_row(static_cast<GameWord>(message));
    if (message == PickupNotice::super_shotgun)
        add_row(static_cast<GameWord>(message) + 1);
    pickup_bonus_ticks = 30;
    checkpoint("pickup.bonusAfter");
    ++pickup_notice_revision;
}

void GameplaySession::Impl::shell_touch()
{
    const auto menu_value = gameplay_menu();
    checkpoint("shell.menu");
    const auto blocked = menu_value || gameplay_release();
    checkpoint("shell.gate");
    if (blocked)
        return;
    const auto origin = assets().manifest.at("worldOrigin");
    for (unsigned i = 0; i < unsigned(constant("QC_SHELL_COUNT")); ++i)
    {
        if (!(shell_mask & (1u << i)))
            continue;
        bool inside = true;
        for (unsigned axis = 0; axis < 3; ++axis)
        {
            const auto name = "QC_SHELL_" + std::to_string(i) + "_" + std::string(1, "XYZ"[axis]);
            const auto lower = constant(name + "_MIN"), upper = constant(name + "_MAX");
            const auto rebased = gs(std::llround(double(lower) - origin.at(axis).get<double>() * 16));
            inside &= gw(walk.from[axis] - rebased) < gw(upper - lower + 1);
        }
        if (inside)
        {
            const auto actor = gw((4 + i) * 512);
            event(actor, 512, field(actor, "TOUCH"));
            if (!field(actor, "SOLID"))
            {
                shell_mask = gw(shell_mask & ~(1u << i));
                notify_pickup(PickupNotice::shells);
            }
        }
    }
    if (constant("QC_ARMOR_COUNT"))
    {
        armor_angle_step = (armor_angle_step + 1) % 72;
        if (armor_mask)
            armor_touch();
    }
    if (nail_mask)
        nail_touch();
    if (super_shotgun_visible)
        super_shotgun_touch();
    if (health_mask)
        health_touch();
    if (powerup_mask)
        powerup_touch();
}

void GameplaySession::Impl::powerup_touch()
{
    if (gs(player("HEALTH")) <= 0)
        return;
    const auto& origin = assets().manifest.at("worldOrigin");
    const auto& boxes = metadata().at("stockPowerups");
    for (std::size_t index = 0; index < boxes.size(); ++index)
    {
        const auto mask = 1u << index;
        const auto& box = boxes.at(index);
        bool touching = (powerup_mask & mask) != 0;
        for (unsigned axis = 0; touching && axis < 3; ++axis)
        {
            const int lo = box.at("triggerEyeMinQ4").at(axis), hi = box.at("triggerEyeMaxQ4").at(axis);
            const auto local = gs(std::llround(lo - origin.at(axis).get<double>() * 16));
            touching = gw(walk.from[axis] - local) <= hi - lo;
        }
        if (!touching)
            continue;
        powerup_mask &= ~mask;
        items_high |= gw(box.at("bit").get<unsigned>() >> 16);
        const bool suit = box.at("kind") == "suit";
        notify_pickup(suit ? PickupNotice::biosuit : PickupNotice::quad);
        field(512, suit ? "RADSUIT_FINISHED" : "SUPER_DAMAGE_FINISHED") = gw(clock + box.at("duration").get<int>() * 64);
        (suit ? suit_warn_next : quad_warn_next) = 0;
        (suit ? suit_warning_pulses : quad_warning_pulses) = 0;
        ++sounds;
        if (collect_sound)
            play_sound(box.value("sound", suit ? "items/suit.wav" : "items/damage.wav"));
        ++revision;
    }
}

void GameplaySession::Impl::powerup_attack()
{
    if (!constant("QC_POWERUP_COUNT") || player("SUPER_DAMAGE_FINISHED") <= clock || clock <= player("SUPER_SOUND"))
        return;
    field(512, "SUPER_SOUND") = gw(clock + 64);
    ++sounds;
    play_sound("items/damage3.wav", 512, 0);
}

void GameplaySession::Impl::powerup_tick()
{
    auto update = [&](const char* deadline, GameWord& next_warning, GameWord& pulses, std::int64_t item_bit) {
        auto& finish = field(512, deadline);
        if (!finish)
            return;
        if (clock > finish)
        {
            finish = next_warning = 0;
            items_high &= ~gw(item_bit);
        }
        else if (finish - clock < 3 * 64 && clock > next_warning)
        {
            if (!next_warning)
                ++sounds;
            ++pulses;
            next_warning = gw(clock + 64);
        }
    };
    update("SUPER_DAMAGE_FINISHED", quad_warn_next, quad_warning_pulses, constant("QC_POWERUP_0_ITEM_HIGH"));
    if (constant("QC_POWERUP_COUNT") >= 2)
    {
        update("RADSUIT_FINISHED", suit_warn_next, suit_warning_pulses, constant("QC_POWERUP_1_ITEM_HIGH"));
        if (gs(player("HEALTH")) > 0)
            liquid_effects();
    }
}

void GameplaySession::Impl::nail_touch()
{
    if (gs(player("HEALTH")) <= 0)
        return;
    const auto& stock = metadata().at("stockNailgun");
    const auto& boxes = stock.at("boxes");
    const auto& origin = assets().manifest.at("worldOrigin");
    for (unsigned i = 0; i <= boxes.size(); ++i)
    {
        const auto bit = 1u << (i ? i - 1 : static_cast<unsigned>(boxes.size()));
        if (!(nail_mask & bit) || (i && player("AMMO_NAILS") >= 200 * 64))
            continue;
        const auto& box = i ? boxes.at(i - 1) : stock.at("gun");
        bool touches = true;
        for (unsigned axis = 0; axis < 3; ++axis)
        {
            const int lo = box.at("triggerEyeMinQ4").at(axis);
            const int hi = box.at("triggerEyeMaxQ4").at(axis);
            const auto local = gs(std::llround(lo - origin.at(axis).get<double>() * 16));
            touches &= gw(walk.from[axis] - local) <= hi - lo;
        }
        if (!touches)
            continue;
        if (!i)
        {
            field(512, "ITEMS") |= 4;
            field(512, "WEAPON") = 4 * 64;
            axe_selected = axe_pending = nail_frame = 0;
        }
        field(512, "AMMO_NAILS") = gw(std::min(200 * 64, player("AMMO_NAILS") + box.at("amount").get<int>() * 64));
        if (!axe_selected && player("WEAPON") == 4 * 64)
            field(512, "CURRENTAMMO") = player("AMMO_NAILS");
        nail_mask = gw(nail_mask & ~bit);
        notify_pickup(i ? PickupNotice::nails : PickupNotice::nailgun);
        ++sounds;
        play_sound(i ? "weapons/lock4.wav" : "weapons/pkup.wav");
        ++revision;
    }
}

void GameplaySession::Impl::super_shotgun_touch()
{
    if (gs(player("HEALTH")) <= 0)
        return;
    const auto& item = metadata().at("stockSuperShotgun").at("pickup");
    const auto& origin = assets().manifest.at("worldOrigin");
    for (unsigned axis = 0; axis < 3; ++axis)
    {
        const int lo = item.at("triggerEyeMinQ4").at(axis);
        const int hi = item.at("triggerEyeMaxQ4").at(axis);
        const auto local = gs(std::llround(lo - origin.at(axis).get<double>() * 16));
        if (gw(walk.from[axis] - local) > hi - lo)
            return;
    }
    field(512, "AMMO_SHELLS") = gw(std::min(100 * 64, player("AMMO_SHELLS") + item.at("amount").get<int>() * 64));
    field(512, "CURRENTAMMO") = player("AMMO_SHELLS");
    field(512, "ITEMS") = gw((player("ITEMS") & ~0xe00) | 0x102);
    field(512, "WEAPON") = 2 * 64;
    axe_selected = axe_pending = nail_frame = 0;
    shot_clock = gw(constant("BSP_WEAPON_LIVE_TICKS", 36));
    shot_view = shots;
    super_shotgun_visible = 0;
    notify_pickup(PickupNotice::super_shotgun);
    ++sounds;
    play_sound("weapons/pkup.wav");
    ++revision;
}

void GameplaySession::Impl::armor_touch()
{
    if (gs(player("HEALTH")) <= 0)
        return;
    const auto& boxes = metadata().at("stockArmor");
    const auto& origin = assets().manifest.at("worldOrigin");
    for (std::size_t i = 0; i < boxes.size(); ++i)
    {
        const auto& box = boxes.at(i);
        if (!(armor_mask & (1u << i)))
            continue;
        bool inside = true;
        for (unsigned axis = 0; axis < 3; ++axis)
        {
            const int lo = box.at("triggerEyeMinQ4").at(axis);
            const int hi = box.at("triggerEyeMaxQ4").at(axis);
            const auto local = gs(std::llround(lo - origin.at(axis).get<double>() * 16));
            inside &= gw(walk.from[axis] - local) <= hi - lo;
        }
        const int value = box.at("value"), tenths = box.at("tenths");
        const int old_tenths = player("ARMORTYPE") == 38 ? 6 : 3;
        if (!inside || old_tenths * player("ARMORVALUE") >= tenths * value * 64)
            continue;
        field(512, "ARMORTYPE") = gw((tenths * 64 + 5) / 10);
        field(512, "ARMORVALUE") = gw(value * 64);
        field(512, "ITEMS") = gw((player("ITEMS") & 0x1fff) | box.at("bit").get<int>());
        armor_mask = gw(armor_mask & ~(1u << i));
        notify_pickup(PickupNotice::armor);
        ++sounds;
        play_sound(box.at("sound").get_ref<const std::string&>());
        ++revision;
    }
}

int GameplaySession::Impl::environmental_damage(int points)
{
    if ((!constant("QC_ARMOR_COUNT") && !constant("QC_CAMPAIGN_ITEMS")) || !player("ARMORTYPE"))
        return points * 64;
    auto& armor = field(512, "ARMORVALUE");
    const int saved = std::min<int>(armor, armor_saving(player("ARMORTYPE"), gw(points * 64)));
    armor = gw(armor - saved);
    if (!armor)
    {
        field(512, "ARMORTYPE") = 0;
        field(512, "ITEMS") &= 0x1fff;
    }
    return points * 64 - saved;
}

void GameplaySession::Impl::health_touch()
{
    const int maximum = gs(player("MAX_HEALTH"));
    int health = gs(player("HEALTH"));
    if (health <= 0 || health >= 250 * 64)
        return;
    const auto& origin = assets().manifest.at("worldOrigin");
    const auto& boxes = assets().manifest.at("metadata").at("gameplay").at("stockHealth").at("boxes");
    for (std::size_t i = 0; i < boxes.size(); ++i)
    {
        if (!(health_mask & (1u << i)))
            continue;
        const auto& box = boxes.at(i);
        const bool mega = box.at("size") == "Mega";
        if (!mega && health >= maximum)
            continue;
        bool inside = true;
        for (std::size_t axis = 0; axis < 3; ++axis)
        {
            const int lower = box.at("triggerEyeMinQ4").at(axis).get<int>();
            const int upper = box.at("triggerEyeMaxQ4").at(axis).get<int>();
            const auto local_lower = gs(std::llround(lower - origin.at(axis).get<double>() * 16));
            inside &= gw(walk.from[axis] - local_lower) < gw(upper - lower + 1);
        }
        if (!inside)
            continue;
        health = std::min(health + box.at("amount").get<int>() * 64, mega ? 250 * 64 : maximum);
        field(512, "HEALTH") = gw(health);
        health_mask = gw(health_mask & ~(1u << i));
        if (mega)
        {
            const auto number = i - static_cast<std::size_t>(constant("QC_REGULAR_HEALTH_COUNT"));
            mega_timers.at(number) = gw(5 * (queued_input ? simulation_hz : 64) + 1);
            items_high |= 1;
            health_sound = 3;
        }
        else
            health_sound = box.at("sound") == "items/health1.wav" ? 2 : 1;
        notify_pickup(mega ? PickupNotice::megahealth : box.at("amount") == 15 ? PickupNotice::health15 : PickupNotice::health25);
        ++sounds;
        play_sound(box.at("sound").get_ref<const std::string&>());
        ++revision;
    }
}

void GameplaySession::Impl::mega_rot()
{
    for (auto& remaining : mega_timers)
    {
        if (!remaining || --remaining)
            continue;
        auto& health = field(512, "HEALTH");
        if (gs(health) > gs(player("MAX_HEALTH")))
        {
            health = gw(health - 64);
            remaining = queued_input ? simulation_hz : 64;
        }
        else
            items_high &= ~1u;
    }
}

void GameplaySession::Impl::trace_shot()
{
    effect_word = 0;
    const auto self = global("SELF");
    if (self == 512 && !axe_selected)
        ++pellets;
    GamePoint start{}, end{};
    for (unsigned i = 0; i < 3; ++i)
    {
        start[i] = gs(g(8 + i * 2));
        end[i] = gs(g(14 + i * 2));
    }
    auto result = trace(start, end, true, false);
    if (self == 512 && constant("QC_E1M3_SHOT_TERMINAL") == result.terminal)
        e1m3_stair_button_hit = true;
    global("TRACE_ENT") = 0;
    if (result.terminal == 0xfffd)
        global("TRACE_ENT") = gw(constant("QC_DOOR"));
    else if (result.terminal == 0xfffc)
        global("TRACE_ENT") = gw(constant("QC_BUTTON"));
    const auto brush_terminal = result.terminal;
    trace_actors(result, start, end);
    const bool player_trace = self == 512 || (self == constant("QC_GRUNT_DROP") && g(26) == 512);
    if (constant("QC_SECRET_DOOR_COUNT") && player_trace && !g(20) && !global("TRACE_ENT"))
    {
        secret_door_shot(brush_terminal);
        if (constant("QC_ORD_DOOR_COUNT") && brush_terminal == gw(-72) && !ordinary_shot_cooldown)
        {
            ordinary_shot_cooldown = 13;
            ordinary_door_use(0);
        }
    }
    if (self == 512 && hub_clue_edict && global("TRACE_ENT") == hub_clue_edict)
        hub_shoot_clue();
    if (result.fraction < 4096 && self == 512)
    {
        if (axe_selected)
        {
            const auto target = global("TRACE_ENT");
            if (target && field(target, "TAKEDAMAGE"))
                ++axe_hits;
        }
        else
            ++hits;
    }
    global("TRACE_FRACTION") = result.fraction >= 4096 ? 64 : std::min<GameWord>(63, result.fraction >> 6);
    for (unsigned i = 0; i < 3; ++i)
    {
        g(std::size_t(constant("QC_GLOBAL_TRACE_ENDPOS")) + i * 2) = gw(result.result[i]);
        g(std::size_t(constant("QC_GLOBAL_TRACE_NORMAL")) + i * 2) = gw(game_asr(result.normal[i], 8));
    }
}

void GameplaySession::Impl::trace_actors(GameplayTrace& result, const GamePoint& from, const GamePoint& to)
{
    const bool has_actors = constant("QC_GRUNT_COUNT") != 0;
    if (g(20) || (!has_actors && !hub_clue_edict))
        return;
    std::vector<GameWord> actors{gw(has_actors ? 512 : hub_clue_edict)};
    for (auto a = constant("QC_GRUNT"); a < constant("QC_GRUNT_DROP"); a += 512)
        actors.push_back(gw(a));
    if (const auto box = constant("QC_EXPLOBOX"))
        actors.push_back(gw(box));
    for (const auto actor : actors)
    {
        if (actor == g(26) || !field(actor, "SOLID"))
            continue;
        GameWord enter = 0, exit = result.fraction;
        GamePoint normal{};
        bool accepted = true;
        for (unsigned axis = 0; axis < 3; ++axis)
        {
            auto low = gw(field(actor, "ORIGIN", axis) + field(actor, "MINS", axis)) ^ 0x8000;
            auto high = gw(field(actor, "ORIGIN", axis) + field(actor, "MAXS", axis)) ^ 0x8000;
            auto a = gw(from[axis]) ^ 0x8000, b = gw(to[axis]) ^ 0x8000;
            std::int16_t n = -16384;
            if (b < a)
            {
                auto old = low;
                low = high ^ 0xffff;
                high = old ^ 0xffff;
                a ^= 0xffff;
                b ^= 0xffff;
                n = 16384;
            }
            if (a > high || b < low)
            {
                accepted = false;
                break;
            }
            if (a < low)
            {
                const auto t = game_fraction(low - a, b - a);
                if (t >= enter)
                {
                    enter = t;
                    normal = {};
                    normal[axis] = n;
                }
            }
            if (b > high)
                exit = std::min(exit, game_fraction(high - a, b - a));
            if (enter > exit)
            {
                accepted = false;
                break;
            }
        }
        if (accepted && enter < result.fraction)
        {
            result.fraction = enter;
            result.hit = true;
            result.normal = normal;
            for (unsigned i = 0; i < 3; ++i)
                result.result[i] = gs(from[i] + game_asr(std::int64_t(gs(to[i] - from[i])) * enter, 12));
            global("TRACE_ENT") = actor;
        }
    }
}

} // namespace quake_bsp_reference
