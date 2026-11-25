#include "gameplay_internal.hpp"

namespace quake_bsp_reference {

void GameplaySession::Impl::sync_player()
{
    if (gs(player("HEALTH")) <= 0)
        return;
    for (unsigned axis = 0; axis < 3; ++axis)
    {
        const auto position = gs(game_asr(walk.from[axis], 1));
        const auto delta = gs(position - gs(field(512, "ORIGIN", axis)));
        field(512, "ORIGIN", axis) = gw(position);
        const int max_delta = queued_input ? 384 : 128;
        field(512, "VELOCITY", axis) =
            delta >= -max_delta && delta <= max_delta ? gw(delta * int(queued_input ? simulation_hz : 60)) : 0;
    }
    field(512, "ABSMIN", 2) = gw(field(512, "ORIGIN", 2) - 200);
}

void GameplaySession::Impl::pusher(GameWord actor, unsigned axis, bool door)
{
    auto& deadline = field(actor, "NEXTTHINK");
    if (gs(deadline) <= 0)
        return;
    --deadline;
    const auto velocity = gs(field(actor, "VELOCITY", axis));
    if (velocity)
    {
        const auto total = gs(e(actor, 400) + velocity);
        const auto fraction = gw(total) & 63;
        auto candidate = gs(field(actor, "ORIGIN", axis) + game_asr(total, 6));
        if (!deadline)
            candidate = gs(field(actor, "FINALDEST", axis));
        const auto steps = constant(door ? "QC_DOOR_STEPS" : "QC_BUTTON_STEPS");
        const auto travel = constant(door ? "QC_DOOR_TRAVEL" : "QC_BUTTON_TRAVEL");
        const auto interval = travel / steps;
        const auto pose =
            gw(candidate < 0 ? std::min<std::int64_t>(steps, (-std::int64_t(candidate) + interval / 2) / interval) : 0);
        if (door && velocity >= 0 && pose != door_pose)
        {
            const auto origin = assets().manifest.at("worldOrigin");
            const auto eye = walk.pending ? walk.pending_xyz : camera;
            bool blocked = true;
            for (unsigned a = 0; a < 3; ++a)
            {
                const auto low = constant("QC_DOOR_MIN_" + std::string(1, "XYZ"[a]));
                const auto high = constant("QC_DOOR_MAX_" + std::string(1, "XYZ"[a]));
                auto coordinate = std::int64_t(eye[a]);
                if (a == 2)
                    coordinate += std::int64_t(pose) * travel / (steps * 4);
                const auto lower = std::llround((double(low) + (a == 2 ? 22 : 0) - origin[a].get<double>()) * 16);
                blocked &= gw(coordinate - lower) < gw((high - low) * 16);
            }
            if (blocked && constant("QC_E1M1_PLATFORM_FIRST"))
            {
                const auto top = std::llround((constant("QC_DOOR_MAX_Z") + 22 - origin[2].get<double>()) * 16);
                const auto old_top = top - door_pose * travel / (steps * 4);
                const auto new_top = top - pose * travel / (steps * 4);
                if (eye[2] >= old_top)
                {
                    auto target = eye;
                    target[2] = gs(eye[2] + new_top - old_top);
                    const auto sweep = trace(eye, target);
                    if (sweep.result[2] >= new_top)
                    {
                        walk.from = walk.pending_xyz = sweep.result;
                        walk.pending = true;
                        walk.support_valid = false;
                        blocked = false;
                    }
                }
            }
            if (blocked)
            {
                ++deadline;
                ++door_blocks;
                event(actor, 512, field(actor, "BLOCKED"));
                return;
            }
        }
        if (door)
        {
            grunt_ride_lift(pose);
            door_pose = pose;
        }
        else
            button_pose = pose;
        field(actor, "ORIGIN", axis) = gw(candidate);
        e(actor, 400) = gw(fraction);
    }
    if (!deadline)
        event(actor, 0, field(actor, "THINK"));
}

void GameplaySession::Impl::qc_step()
{
    ++qc_ticks;
    checkpoint("qc.begin");
    unsigned elapsed_units = 1;
    if (queued_input)
    {
        constexpr unsigned quakec_units_per_second = 64;
        const auto units = unsigned(phase) + quakec_units_per_second;
        elapsed_units = units / simulation_hz;
        phase = gw(units % simulation_hz);
    }
    for (unsigned i = 0; i < elapsed_units; ++i)
    {
        if (!basic())
        {
            if (contact)
            {
                contact = 0;
                const auto button = gw(constant("QC_BUTTON"));
                if (field(button, "STATE") == 64)
                {
                    ++activations;
                    event(button, 512, field(button, "TOUCH"));
                }
            }
            pusher(gw(constant("QC_BUTTON")), unsigned(constant("QC_BUTTON_MOVE")) / 2, false);
            pusher(gw(constant("QC_DOOR")), unsigned(constant("QC_DOOR_MOVE")) / 2, true);
            brush_row = gw(door_pose * 3 + button_pose);
            entrance_tick();
            exit_tick();
            if (constant("QC_SECRET_DOOR_COUNT"))
                secret_doors_tick();
            if (constant("QC_ORD_DOOR_COUNT"))
                ordinary_doors_tick();
        }
        else if (constant("QC_E1M2_GROUP_COUNT"))
            e1m2_machinery_tick();
        if (intermission_phase != 2)
            hub_tick();
    }
    const auto menu_value = gameplay_menu();
    checkpoint("qc.menu");
    const auto blocked = menu_value || gameplay_release();
    checkpoint("qc.gruntGate");
    if (!blocked)
    {
        if (intermission_phase != 2 && constant("QC_MEGA_COUNT"))
            mega_rot();
        grunt_tick(elapsed_units);
    }
}

bool GameplaySession::Impl::service_tick()
{
    if (switch_pending)
    {
        const auto next = pending_map.empty() ? maps.at((map_index + 1) % maps.size()).map : pending_map;
        const auto selected = skill_selected;
        static constexpr std::array<std::string_view, 9> fields{
            "ITEMS", "HEALTH", "ARMORVALUE", "AMMO_SHELLS", "AMMO_NAILS", "AMMO_ROCKETS",
            "AMMO_CELLS", "WEAPON", "ARMORTYPE"
        };
        const bool carry = campaign_exit;
        std::array<GameWord, fields.size()> parms{4097, 100*64, 0, 25*64, 0, 0, 0, 64, 0};
        GameWord retained_items_high = 0, retained_axe = 0;
        if (carry && gs(player("HEALTH")) > 0)
        {
            for (std::size_t i = 0; i < fields.size(); ++i)
                parms[i] = player(fields[i]);
            parms[1] = std::clamp<GameWord>(parms[1], 50*64, 100*64);
            parms[3] = std::max<GameWord>(parms[3], 25*64);
            retained_items_high = items_high & 0xff81;
            retained_axe = axe_selected;
        }
        reset(next, selected);
        if (carry && constant("QC_CAMPAIGN_ITEMS"))
        {
            for (std::size_t i = 0; i < fields.size(); ++i)
                field(512, fields[i]) = parms[i];
            items_high = retained_items_high;
            axe_selected = retained_axe;
            field(512, "CURRENTAMMO") = axe_selected ? 0 : player(parms[7] == 4*64 ? "AMMO_NAILS" : "AMMO_SHELLS");
        }
        return false;
    }
    if (restart_pending)
    {
        const auto name = assets().map;
        const auto saved_video = video, saved_divider = divider, saved_previous = previous_buttons,
                   saved_buttons = buttons, saved_revision = revision;
        const auto saved_gate = release_gate;
        const auto saved_scale = scale;
        const auto saved_entities = entities_enabled, saved_brushes = brushes_enabled;
        const auto saved_technique = technique;
        const auto saved_dx = mouse_dx, saved_dy = mouse_dy;
        const auto saved_sky = sky_phase_q24;
        const auto saved_turb = turbulence_phase_q24, saved_alias = alias_phase_q32;
        const auto saved_last = last;
        const auto saved_services = services;
        auto saved_input_clock = std::move(input_clock);
        reset(name, skill_selected);
        video = saved_video;
        last = queued_input ? saved_last : video;
        if (queued_input)
        {
            services = saved_services;
            input_clock = std::move(saved_input_clock);
        }
        divider = saved_divider;
        previous_buttons = saved_previous;
        buttons = saved_buttons;
        revision = saved_revision;
        release_gate = saved_gate;
        scale = saved_scale;
        entities_enabled = saved_entities;
        brushes_enabled = saved_brushes;
        mouse_dx = saved_dx;
        mouse_dy = saved_dy;
        technique = saved_technique;
        sky_phase_q24 = saved_sky;
        turbulence_phase_q24 = saved_turb;
        alias_phase_q32 = saved_alias;
        if (!queued_input)
            return false;
    }
    if (fault || (queued_input ? input_clock.tick : video) == last)
        return false;
    ++last;
    ++services;
    try
    {
        checkpoint("service.begin");
        if (queued_input)
        {
            consume_input();
            if (intermission_service())
            {
                checkpoint("service.end");
                return true;
            }
            if (!gameplay_menu() && !gameplay_release() && request_respawn())
            {
                checkpoint("service.end");
                return true;
            }
        }
        walk_tick();
        const auto sync_menu = gameplay_menu();
        checkpoint("sync.menu");
        const auto sync_blocked = sync_menu || gameplay_release();
        checkpoint("sync.gate");
        if (!sync_blocked)
            sync_player();
        shell_touch();
        shot_tick();
        finish_landing();
        qc_step();
        if (queued_input)
            publish_walk();
        else
        {
            phase = gw(phase + 4);
            if (phase >= 60)
            {
                phase = gw(phase - 60);
                checkpoint("service.extra");
                qc_step();
            }
        }
        checkpoint("service.end");
    }
    catch (const std::exception&)
    {
        fault = 1;
        throw;
    }
    return true;
}

} // namespace quake_bsp_reference
