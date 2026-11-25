#include "gameplay_internal.hpp"

namespace quake_bsp_reference {
namespace {
constexpr int kHubTeleportCooldown = 45;

int hub_integer(const Json& value, int low, int high)
{
    if (!value.is_number_integer() ||
        (value.is_number_unsigned() && value.get<std::uint64_t>() > static_cast<std::uint64_t>(high)))
        throw std::runtime_error("hub metadata requires bounded native integers");
    const auto number = value.get<std::int64_t>();
    if (number < low || number > high)
        throw std::runtime_error("hub metadata integer escapes its native range");
    return static_cast<int>(number);
}

GamePoint hub_point(const Json& value)
{
    if (!value.is_array() || value.size() != 3)
        throw std::runtime_error("hub metadata requires three native coordinates");
    GamePoint point{};
    for (unsigned axis = 0; axis < point.size(); ++axis)
        point[axis] = static_cast<std::int16_t>(hub_integer(value.at(axis), -32768, 32767));
    return point;
}

bool contains(const GameplayHubTrigger& trigger, const GamePoint& point)
{
    for (unsigned axis = 0; axis < point.size(); ++axis)
        if (point[axis] < trigger.lower[axis] || point[axis] > trigger.upper[axis])
            return false;
    return true;
}
} // namespace

void GameplaySession::Impl::hub_init()
{
    const auto& gameplay = metadata();
    if (gameplay.contains("stockLiquids"))
    {
        const auto& liquid = gameplay.at("stockLiquids");
        liquid_nodes = liquid.at("nodes").get<std::vector<std::array<int, 6>>>();
        liquid_root = liquid.at("root");
        liquid_ceiling = liquid.at("ceilingQ4");
    }
    const bool start = assets().map == "start";
    std::string_view destination;
    if (start)
        destination = "e1m1";
    else if (assets().map == "e1m1" && !basic())
        destination = "e1m2";
    else if (assets().map == "e1m2" && basic())
        destination = "e1m3";
    else if (assets().map == "e1m3" && basic())
        destination = "e1m4";
    if (!start && (!gameplay.contains("hub") || gameplay.at("hub").is_null()))
        return;
    const auto& hub = gameplay.at("hub");
    if (!hub.is_object() ||
        (start && (!basic() || hub.value("schema", "") != "quake-start-hub-v1")) ||
        (!start && (destination.empty() || hub.value("schema", "") != "quake-episode-exit-v1")))
        throw std::runtime_error("map has incompatible authored trigger metadata");
    std::set<unsigned> entities;
    const auto parse = [&](const Json& rows, std::vector<GameplayHubTrigger>& output, std::size_t maximum) {
        if (!rows.is_array() || rows.empty() || rows.size() > maximum)
            throw std::runtime_error("hub trigger roster is empty or exceeds its bound");
        for (const auto& row : rows)
        {
            const auto entity = unsigned(hub_integer(row.at("entityNumber"), 1, 65535));
            if (!entities.insert(entity).second)
                throw std::runtime_error("hub trigger roster repeats an entity");
            GameplayHubTrigger trigger;
            trigger.lower = hub_point(row.at("triggerEyeMinQ4"));
            trigger.upper = hub_point(row.at("triggerEyeMaxQ4"));
            for (unsigned axis = 0; axis < trigger.lower.size(); ++axis)
                if (trigger.lower[axis] > trigger.upper[axis] ||
                    int(trigger.upper[axis]) - trigger.lower[axis] >= 65535)
                    throw std::runtime_error("hub trigger has invalid ordered native bounds");
            output.push_back(std::move(trigger));
        }
    };
    if (start)
    {
        parse(hub.at("skills"), hub_skills, 4);
        parse(hub.at("teleports"), hub_teleporters, 16);
        if (hub.contains("teleportArrivalDelayQ6"))
            hub_arrival_cooldown_tick = gw(kHubTeleportCooldown -
                hub_integer(hub.at("teleportArrivalDelayQ6"), 1, kHubTeleportCooldown - 1));
        // Retained v1 START manifests predate the warning descriptors.
        if (hub.contains("registeredWarning"))
        {
            const auto& warning = hub.at("registeredWarning");
            parse(warning.at("triggers"), hub_warning_triggers, 3);
            if (hub_warning_triggers.size() != 3)
                throw std::runtime_error("START must have three registered warning triggers");
            hub_warning_duration = gw(hub_integer(warning.at("durationQ6"), 128, 128));
            const auto message = warning.at("message").get<std::string>();
            if (message.empty())
                throw std::runtime_error("START warning text is empty");
            hub_messages.assign(hub_warning_triggers.size(), message);
        }
        const auto parse_prompts = [&](const Json& prompts, std::size_t count) {
            if (hub_messages.size() < 3 || !prompts.is_array() || prompts.size() != count)
                throw std::runtime_error("START has an incomplete prompt roster");
            const auto first = hub_warning_triggers.size();
            parse(prompts, hub_warning_triggers, count);
            for (std::size_t i = 0; i < count; ++i)
            {
                const auto& range = prompts.at(i).at("yawRange");
                if (!range.is_array() || range.size() != 2)
                    throw std::runtime_error("START prompt requires two facing limits");
                auto& trigger = hub_warning_triggers[first + i];
                trigger.yaw_start = gw(hub_integer(range.at(0), 0, 255));
                const auto end = hub_integer(range.at(1), 0, 255);
                trigger.yaw_span = gw(((end - trigger.yaw_start) & 255) + 1);
                auto message = prompts.at(i).at("message").get<std::string>();
                if (message.empty())
                    throw std::runtime_error("START prompt text is empty");
                hub_messages.push_back(std::move(message));
            }
        };
        if (hub.contains("skillHints"))
            parse_prompts(hub.at("skillHints"), 4);
        if (hub.contains("episodePrompts"))
            parse_prompts(hub.at("episodePrompts"), 2);
        if (hub.contains("poolSwimZonesQ4"))
        {
            const auto& zones = hub.at("poolSwimZonesQ4");
            if (!zones.is_array() || zones.size() != 4)
                throw std::runtime_error("START requires four swim zones");
            for (const auto& row : zones)
            {
                GameplaySwimZone zone{};
                if (!row.is_array() || row.size() != zone.size())
                    throw std::runtime_error("START swim zone requires seven intervals");
                for (std::size_t i = 0; i < zone.size(); ++i)
                {
                    const auto& bounds = row.at(i);
                    if (!bounds.is_array() || bounds.size() != 2)
                        throw std::runtime_error("START swim interval requires two bounds");
                    const auto lower = hub_integer(bounds.at(0), -32768, 32766);
                    zone[i] = {lower, hub_integer(bounds.at(1), lower + 1, 32767)};
                }
                hub_swim_zones.push_back(zone);
            }
        }
        hub_warning_cooldowns.resize(hub_warning_triggers.size());
        if (hub.contains("shootableClue"))
        {
            const auto& clue = hub.at("shootableClue");
            const auto actor = hub_integer(clue.at("edictOffset"), 1, 65535);
            if (actor != constant("QC_GRUNT"))
                throw std::runtime_error("START clue must use the spare actor slot");
            hub_clue_edict = gw(actor);
            hub_clue_rearm = gw(hub_integer(clue.at("rearmQ6"), 192, 192));
            auto message = clue.at("message").get<std::string>();
            if (hub_messages.empty() || message.empty() || field(hub_clue_edict, "SOLID") != 128)
                throw std::runtime_error("START clue requires a solid actor and centerprint text");
            hub_messages.push_back(std::move(message));
        }
    }
    else
    {
        if (hub.at("skills") != Json::array())
            throw std::runtime_error("unexpected episode skill trigger");
        if (hub.at("teleports") != Json::array())
        {
            if (assets().map != "e1m1")
                throw std::runtime_error("unexpected episode teleport");
            parse(hub.at("teleports"), hub_teleporters, 1);
            hub_arrival_cooldown_tick = gw(kHubTeleportCooldown -
                hub_integer(hub.at("teleportArrivalDelayQ6"), 1, kHubTeleportCooldown - 1));
        }
    }
    if (hub.contains("hints"))
    {
        const auto& hints = hub.at("hints");
        const auto& triggers = hints.at("triggers");
        const auto& removers = hints.at("removers");
        if (assets().map != "e1m1" || triggers.size() != 3 || removers.size() != 2)
            throw std::runtime_error("invalid E1M1 hint roster");
        parse(triggers, hub_warning_triggers, 3);
        parse(removers, hub_hint_removers, 2);
        hub_warning_duration = gw(hub_integer(hints.at("durationQ6"), 1, 32767));
        hub_warning_repeat = gw(hub_integer(hints.at("cooldownQ6"), 1, 32767));
        hub_warning_cooldowns.resize(triggers.size());
        for (std::size_t i = 0; i < triggers.size(); ++i)
        {
            const auto& row = triggers.at(i);
            const auto& range = row.at("yawRange");
            auto& trigger = hub_warning_triggers[i];
            trigger.value = gw(hub_integer(row.at("spawnflags"), 0, 4095));
            trigger.yaw_start = gw(hub_integer(range.at(0), 0, 255));
            trigger.yaw_span = gw(((hub_integer(range.at(1), 0, 255) - trigger.yaw_start) & 255) + 1);
            hub_messages.push_back(row.at("message").get<std::string>());
        }
        for (std::size_t i = 0; i < removers.size(); ++i)
        {
            const auto target = removers.at(i).at("killtarget");
            const auto found = std::find_if(triggers.begin(), triggers.end(),
                [&](const auto& row) { return row.at("targetname") == target; });
            if (found == triggers.end())
                throw std::runtime_error("hint remover has no matching trigger");
            hub_hint_removers[i].value = gw(std::distance(triggers.begin(), found));
        }
    }
    else
        hub_warning_repeat = hub_warning_duration;
    if (hub.contains("secrets"))
    {
        const auto& descriptor = hub.at("secrets");
        if (assets().map != "e1m1" || descriptor.at("triggers").size() != 6 ||
            descriptor.at("sound") != "misc/secret.wav" || hub_messages.empty())
            throw std::runtime_error("invalid E1M1 secret roster");
        parse(descriptor.at("triggers"), secrets, 6);
        hub_messages.push_back(descriptor.at("message").get<std::string>());
        secret_gate = gw(hub_messages.size());
        if (hub.contains("secretDoorHint"))
            hub_messages.push_back(hub.at("secretDoorHint").get<std::string>());
        if (hub.contains("ordinaryDoorHint"))
            hub_messages.push_back(hub.at("ordinaryDoorHint").get<std::string>());
    }
    parse(hub.at("exits"), hub_exits, start ? 4 : 1);
    std::set<unsigned> skills;
    for (std::size_t i = 0; i < hub_skills.size(); ++i)
    {
        const auto skill = unsigned(hub_integer(hub.at("skills").at(i).at("skill"), 0, 3));
        if (!skills.insert(skill).second)
            throw std::runtime_error("hub skill roster repeats a difficulty");
        hub_skills[i].value = gw(skill);
    }
    if (start && skills.size() != 4)
        throw std::runtime_error("start map requires all four difficulty choices");
    for (std::size_t i = 0; i < hub_teleporters.size(); ++i)
    {
        const auto& row = hub.at("teleports").at(i);
        hub_teleporters[i].destination = hub_point(row.at("destinationEyeQ4"));
        hub_teleporters[i].value = gw(hub_integer(row.at("destinationYaw"), 0, 255));
    }
    for (std::size_t i = 0; i < hub_exits.size(); ++i)
    {
        const auto& name = hub.at("exits").at(i).at("destination");
        if (!name.is_string())
            throw std::runtime_error("hub exit requires a destination map");
        hub_exits[i].target = name.get<std::string>();
        const auto& target = hub_exits[i].target;
        if (target != destination)
            throw std::runtime_error("authored exit has an unsupported destination");
        if (std::ranges::none_of(maps, [&](const auto& entry) { return entry.map == target; }))
        {
            if (start)
                throw std::runtime_error("hub exit destination assets are unavailable");
            // The reference also supports isolated episode maps for inspection.
            hub_exits.clear();
            return;
        }
    }
}

bool GameplaySession::Impl::hub_can_swim(const GamePoint& point) const
{
    const auto [x, y, z] = point;
    const std::array<int, 7> axes{x, y, z, x + y, x - y, 2 * x + y, 2 * x - y};
    return std::ranges::any_of(hub_swim_zones, [&](const auto& zone) {
        for (std::size_t i = 0; i < axes.size(); ++i)
            if (axes[i] < zone[i][0] || axes[i] >= zone[i][1])
                return false;
        return true;
    });
}

void GameplaySession::Impl::teleport_death_touch()
{
    const auto center = hub_teleporters.at(0).destination;
    for (auto actor = gw(constant("QC_GRUNT")); actor < constant("QC_GRUNT_DROP"); actor += 512)
    {
        if (gs(field(actor, "HEALTH")) <= 0 || !field(actor, "TAKEDAMAGE"))
            continue;
        bool touching = true;
        for (unsigned axis = 0; axis < 3; ++axis)
        {
            const int delta = gs(field(actor, "ORIGIN", axis)) - center[axis] / 2;
            const int min = axis == 2 ? -27*8 : -19*8, max = axis == 2 ? 35*8 : 19*8;
            touching &= delta + gs(field(actor, "MINS", axis)) <= max && delta + gs(field(actor, "MAXS", axis)) >= min;
        }
        if (touching)
        {
            field(actor, "HEALTH") = gw(-99 * 64);
            g(8) = global("OTHER") = actor;
            g(14) = global("SELF") = gw(constant("QC_GRUNT_DROP"));
            global("TIME") = clock;
            budget = 4096;
            invoke(gw(constant("QC_TELEFRAG_KILLED")));
        }
    }
}

bool GameplaySession::Impl::intermission_service()
{
    if (!constant("QC_INTERMISSION_COUNT"))
        return false;
    if (gameplay_menu() || gameplay_release())
        return intermission_phase != 0;
    if (intermission_phase != 2)
    {
        if (++intermission_subseconds == simulation_hz)
        {
            intermission_subseconds = 0;
            ++intermission_seconds;
        }
        if (!intermission_phase)
            return false;
        if (--intermission_wait)
            return true;
        // FindIntermission advances while random()*4 is strictly greater than one.
        intermission_camera = gw(std::max(0, int(random()) - 1) / 16);
        const auto& table = metadata().at("hub").at("intermission");
        const auto& spot = table.at("cameras").at(intermission_camera);
        walk.pending_xyz = hub_point(spot.at("eyeQ4"));
        for (unsigned axis = 0; axis < 3; ++axis)
        {
            field(512, "ORIGIN", axis) = gw(game_asr(walk.pending_xyz[axis], 1));
            field(512, "VIEW_OFS", axis) = 0;
            field(512, "VELOCITY", axis) = 0;
        }
        for (const auto name : {"SOLID", "TAKEDAMAGE", "MOVETYPE"})
            field(512, name) = 0;
        pending_yaw = spot.at("yaw").get<GameWord>();
        pending_yaw_valid = walk.pending = true;
        intermission_phase = 2;
        intermission_wait = 120;
        intermission_kills = global("KILLED_MONSTERS") / 64;
        intermission_monsters = table.at("monsters").at(skill_active).get<GameWord>();
        walk.velocity_xy = {};
        walk.velocity_z = 0;
        publish_walk();
        // The cartridge reads its clock after the one-time MSU panel load.
        const auto armed_video = video;
        checkpoint("intermission.arm");
        intermission_video = armed_video;
        return true;
    }
    if (intermission_wait)
    {
        const auto sampled_video = video;
        checkpoint("intermission.clock");
        const auto elapsed = gw(sampled_video - intermission_video);
        intermission_wait = elapsed < 120 ? gw(120 - elapsed) : 0;
        if (intermission_wait)
        {
            qc_step();
            return true;
        }
    }
    if (gameplay_buttons() & 0x30)
    {
        pending_map = hub_exits.at(0).target;
        campaign_exit = assets().map == "e1m1" && pending_map == "e1m2";
        switch_pending = true;
    }
    else
        qc_step();
    return true;
}

void GameplaySession::Impl::hub_tick()
{
    if (hub_skills.empty() && ((hub_exits.empty() && hub_warning_triggers.empty()) || gs(player("HEALTH")) <= 0))
        return;
    if (hub_teleport_cooldown)
    {
        --hub_teleport_cooldown;
        if (constant("QC_TELEFRAG_KILLED") && hub_teleport_cooldown > hub_arrival_cooldown_tick)
            teleport_death_touch();
        if (hub_arrival_cooldown_tick && hub_teleport_cooldown == hub_arrival_cooldown_tick)
        {
            if (hub_skills.empty())
            {
                g(2) = random();
                g(2) = random();
                ++sounds;
            }
            ++sounds;
        }
    }
    if (!hub_warning_triggers.empty())
    {
        if (hub_warning_ticks && !--hub_warning_ticks)
            hub_warning_gate = 0;
        for (auto& remaining : hub_warning_cooldowns)
            if (remaining && remaining != 0xffff)
                --remaining;
    }
    if (hub_clue_cooldown)
        --hub_clue_cooldown;
    if (gameplay_menu() || gameplay_release() || pending_yaw_valid || switch_pending)
        return;
    const auto point = walk.pending ? walk.pending_xyz : camera;
    for (const auto& trigger : hub_skills)
        if (contains(trigger, point))
        {
            skill_selected = trigger.value;
            break;
        }
    for (std::size_t i = 0; i < secrets.size(); ++i)
    {
        const auto bit = static_cast<GameWord>(1u << i);
        if (!(secret_mask & bit) && contains(secrets[i], point))
        {
            secret_mask |= bit;
            ++found_secrets;
            hub_warning_ticks = hub_warning_duration;
            hub_warning_gate = secret_gate;
            ++hub_warning_events;
            ++sounds;
        }
    }
    for (std::size_t i = 0; i < hub_warning_triggers.size(); ++i)
    {
        const auto& trigger = hub_warning_triggers[i];
        const unsigned skill_flag = 256u << std::min(skill_active, 2u);
        if (!(trigger.value & skill_flag) && !hub_warning_cooldowns[i]
            && ((yaw - trigger.yaw_start) & 255) < trigger.yaw_span && contains(trigger, point))
        {
            hub_warning_cooldowns[i] = hub_warning_repeat;
            hub_warning_ticks = hub_warning_duration;
            hub_warning_gate = gw(i + 1);
            ++hub_warning_events;
            ++sounds;
            break;
        }
    }
    if (skill_active < 2)
        for (const auto& remover : hub_hint_removers)
            if (contains(remover, point))
                hub_warning_cooldowns[remover.value] = 0xffff;
    if (!hub_teleport_cooldown)
        for (const auto& trigger : hub_teleporters)
            if (contains(trigger, point))
            {
                // The NMI publishes this whole pose; no old-heading movement
                // may overwrite it while foreground catch-up is still pending.
                teleport_departure_eye = point;
                walk.pending = false;
                walk.pending_xyz = trigger.destination;
                pending_yaw = trigger.value;
                // Stock teleport_touch launches the player along t6's due-east mangle.
                walk.velocity_xy = {static_cast<std::int16_t>(hub_skills.empty() ? 300 * 16 / 20 : 0), 0};
                walk.velocity_z = 0;
                walk.grounded = 0;
                walk.support_valid = false;
                walk.button_contact = 0;
                walk.failed_step_plane = 0xffff;
                walk.failed_step_tick = 0;
                hub_teleport_cooldown = kHubTeleportCooldown;
                if (constant("QC_TELEFRAG_KILLED"))
                    teleport_death_touch();
                ++hub_teleports;
                pending_yaw_valid = true;
                walk.pending = true;
                return;
            }
    for (const auto& trigger : hub_exits)
        if (contains(trigger, point))
        {
            if (constant("QC_INTERMISSION_COUNT"))
            {
                if (!intermission_phase)
                {
                    intermission_phase = 1;
                    intermission_wait = 2;
                }
                return;
            }
            pending_map = trigger.target;
            switch_pending = true;
            return;
        }
}

void GameplaySession::Impl::hub_shoot_clue()
{
    if (hub_clue_cooldown)
        return;
    hub_clue_cooldown = hub_clue_rearm;
    hub_warning_ticks = hub_warning_duration;
    hub_warning_gate = gw(hub_messages.size());
    ++hub_warning_events;
    ++sounds;
}

std::string_view GameplaySession::Impl::hub_centerprint() const
{
    if (hub_warning_ticks && !menu_open)
        return hub_messages.at(hub_warning_gate - 1);
    return {};
}

} // namespace quake_bsp_reference
