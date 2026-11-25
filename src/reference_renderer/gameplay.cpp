#include "gameplay_internal.hpp"

namespace quake_bsp_reference {
namespace {
std::vector<GameWord> words(const std::vector<std::uint8_t>& data)
{
    if (data.size() & 1)
        throw std::runtime_error("partial gameplay word array");
    std::vector<GameWord> result;
    for (std::size_t i = 0; i < data.size(); i += 2)
        result.push_back(game_u16(data, i));
    return result;
}
} // namespace

GameplayAssets load_gameplay_assets(const fs::path& path)
{
    GameplayAssets assets;
    const auto resolved = fs::absolute(path).lexically_normal();
    std::ifstream stream(resolved);
    if (!stream)
        throw std::runtime_error("cannot open gameplay manifest");
    stream >> assets.manifest;
    auto& document = assets.manifest;
    if (document.at("schema") != "quake-gameplay-assets-v1")
        throw std::runtime_error("unsupported gameplay asset schema");
    assets.map = document.at("map").get<std::string>();
    if (assets.map != "start" && assets.map != "e1m1" && assets.map != "e1m3" &&
        assets.map != "e1m2" && assets.map != "e1m4")
        throw std::runtime_error("unsupported playable map");
    for (const auto& [key, value] : document.at("constants").items())
        assets.constants.emplace(key, value.get<std::int64_t>());
    if (document.at("worldOrigin").size() != 3 || document.at("spawnEyeQ4").size() != 3)
        throw std::runtime_error("gameplay camera dimensions invalid");
    for (const auto& row : document.at("payloads"))
    {
        const auto name = row.at("file").get<std::string>();
        const fs::path relative(name);
        if (relative.is_absolute() || relative.has_parent_path() || name.empty())
            throw std::runtime_error("invalid gameplay payload path");
        const auto expected = row.at("bytes").get<std::size_t>();
        if (expected > 1024 * 1024)
            throw std::runtime_error("gameplay payload exceeds bound");
        const auto checksum = row.at("sha256").get<std::string>();
        if (checksum.size() != 64)
            throw std::runtime_error("missing gameplay payload checksum binding");
        std::ifstream input(resolved.parent_path() / relative, std::ios::binary);
        if (!input)
            throw std::runtime_error("missing gameplay payload: " + name);
        input.seekg(0, std::ios::end);
        if (input.tellg() != std::streamoff(expected))
            throw std::runtime_error("gameplay payload length differs: " + name);
        input.seekg(0);
        std::vector<std::uint8_t> data(expected);
        input.read(reinterpret_cast<char*>(data.data()), static_cast<std::streamsize>(expected));
        if (!input && expected)
            throw std::runtime_error("cannot read gameplay payload: " + name);
        if (!assets.payloads.emplace(name, std::move(data)).second)
            throw std::runtime_error("duplicate gameplay payload");
    }
    document["manifestPath"] = resolved.string();
    document["assetDirectory"] = resolved.parent_path().string();
    for (const auto* name : {"cameraSinQ6", "cameraMoveSinQ4"})
        if (document.at("tables").at(name).size() < 256)
            throw std::runtime_error("truncated gameplay angle table");
    if (document.at("tables").at("weaponLiveFrames").empty())
        throw std::runtime_error("empty live weapon schedule");
    return assets;
}

GameplayInput gameplay_input_from_json(const Json& value)
{
    if (!value.is_object())
        throw std::runtime_error("gameplay input must be an object");
    const std::set<std::string> known{"joypad", "mouseDx", "mouseDy", "mouseButtons", "mouseConnected", "cycleWeapon"};
    for (const auto& [key, _] : value.items())
        if (!known.contains(key))
            throw std::runtime_error("unknown gameplay input field: " + key);
    auto bounded = [&](const char* name, int low, int high) {
        if (!value.contains(name))
            return 0;
        const auto& field = value.at(name);
        if (!field.is_number_integer())
            throw std::runtime_error("gameplay input requires an integer");
        if (field.is_number_unsigned())
        {
            const auto v = field.get<std::uint64_t>();
            if (v > static_cast<std::uint64_t>(high))
                throw std::runtime_error("gameplay input out of range");
            return static_cast<int>(v);
        }
        const auto v = field.get<std::int64_t>();
        if (v < low || v > high)
            throw std::runtime_error("gameplay input out of range");
        return static_cast<int>(v);
    };
    GameplayInput result;
    result.joypad = gw(bounded("joypad", 0, 65535));
    result.mouse_dx = gs(bounded("mouseDx", -127, 127));
    result.mouse_dy = gs(bounded("mouseDy", -127, 127));
    result.mouse_buttons = static_cast<std::uint8_t>(bounded("mouseButtons", 0, 255));
    if (value.contains("mouseConnected") && !value.at("mouseConnected").is_boolean())
        throw std::runtime_error("gameplay mouseConnected requires a boolean");
    result.mouse_connected = value.value("mouseConnected", false);
    if (value.contains("cycleWeapon") && !value.at("cycleWeapon").is_boolean())
        throw std::runtime_error("gameplay cycleWeapon requires a boolean");
    result.cycle_weapon = value.value("cycleWeapon", false);
    return result;
}

GameplaySession::GameplaySession(std::vector<GameplayAssets> maps, std::string map) :
impl_(std::make_unique<Impl>())
{
    if (maps.empty())
        throw std::runtime_error("no gameplay asset maps");
    impl_->maps = std::move(maps);
    impl_->reset(map, 1);
}
GameplaySession::~GameplaySession() = default;
GameplaySession::GameplaySession(GameplaySession&&) noexcept = default;
GameplaySession& GameplaySession::operator=(GameplaySession&& other) noexcept
{
    if (this != &other)
    {
        continuation_.reset();
        impl_ = std::move(other.impl_);
        continuation_ = std::move(other.continuation_);
    }
    return *this;
}
void GameplaySession::reset(std::string_view map, std::uint8_t skill)
{
    if (continuation_ && continuation_->phase() != "done")
        throw std::runtime_error("cannot reset a suspended gameplay service");
    continuation_.reset();
    impl_->reset(map, skill);
}
void GameplaySession::set_initial_pose(std::array<std::int16_t, 3> eye_q4, std::uint8_t yaw,
                                       std::int16_t pitch, std::optional<std::int16_t> health_q6,
                                       std::optional<std::array<unsigned, 2>> armor, bool quad, std::optional<unsigned> shells)
{
    if (impl_->video || impl_->services || impl_->qc_ticks || impl_->initial_pose_set)
        throw std::runtime_error("gameplay initial pose requires an unused reset state");
    if (pitch < -64 || pitch > 64)
        throw std::runtime_error("gameplay initial pitch is outside native bounds");
    impl_->camera = eye_q4;
    impl_->yaw = yaw;
    impl_->pitch = gw(pitch);
    if (shells)
    {
        if (*shells > 100)
            throw std::runtime_error("initial shell count exceeds stock capacity");
        impl_->field(512, "AMMO_SHELLS") = gw(*shells * 64);
        impl_->field(512, "CURRENTAMMO") = gw(*shells * 64);
    }
    if (health_q6)
        impl_->field(512, "HEALTH") = gw(*health_q6);
    if (armor)
    {
        const auto [kind, points] = *armor;
        if (!impl_->constant("QC_ARMOR_COUNT") || kind > 1 || points == 0 ||
            points > impl_->constant(kind ? "QC_ARMOR_1_VALUE" : "QC_ARMOR_0_VALUE"))
            throw std::runtime_error("initial armor exceeds the stock type or capacity");
        impl_->field(512, "ARMORVALUE") = gw(points * 64);
        impl_->field(512, "ARMORTYPE") = gw(kind ? 38 : 19);
        auto& items = impl_->field(512, "ITEMS");
        items = gw((items & 0x1fff) | impl_->constant(kind ? "QC_ARMOR_1_BIT" : "QC_ARMOR_0_BIT"));
    }
    if (quad)
    {
        if (!impl_->constant("QC_POWERUP_COUNT"))
            throw std::runtime_error("initial Quad requires a map with the stock pickup");
        impl_->powerup_mask &= ~1u;
        impl_->items_high |= gw(impl_->constant("QC_POWERUP_0_ITEM_HIGH"));
        impl_->field(512, "SUPER_DAMAGE_FINISHED") =
            gw(impl_->clock + impl_->constant("QC_POWERUP_0_SECONDS") * 64);
    }
    impl_->walk = GameplayWalk{};
    impl_->initial_pose_set = true;
}
void GameplaySession::video_tick(const GameplayInput& input)
{
    impl_->video_tick(input);
}
void GameplaySession::use_queued_input(bool enabled)
{
    if (impl_->video || impl_->services)
        throw std::runtime_error("input scheduling requires a fresh gameplay session");
    impl_->queued_input = enabled;
}
bool GameplaySession::always_run() const
{
    return impl_->always_run;
}
void GameplaySession::set_always_run(bool enabled)
{
    impl_->always_run = enabled;
}
void GameplaySession::set_skill(std::uint8_t skill)
{
    const auto selected = skill & 3U;
    impl_->global("SKILL") = gw(selected * 64);
    impl_->skill_selected = impl_->skill_active = selected;
}
void GameplaySession::set_render_technique(unsigned technique)
{
    if (technique != 2 && technique != 3 && technique != 4 && technique != 7)
        throw std::runtime_error("unsupported gameplay render technique");
    impl_->technique = technique;
}
void GameplaySession::set_initial_render_scale(unsigned scale)
{
    if ((scale != 2 && scale != 3) || impl_->video || impl_->services)
        throw std::runtime_error("initial render scale requires a fresh session and scale 2 or 3");
    impl_->scale = scale;
    impl_->menu_scale = scale == 3 ? 1 : 0;
}
bool GameplaySession::service_tick()
{
    if (!continuation_)
        return impl_->service_tick();
    if (continuation_->phase() == "done")
    {
        continuation_.reset();
        return impl_->service_tick();
    }
    while (continuation_->phase() != "done")
        continuation_->resume();
    const auto result = continuation_->result();
    continuation_.reset();
    return result;
}
void GameplaySession::step(const GameplayInput& input, unsigned ticks)
{
    if (ticks > 1'000'000)
        throw std::runtime_error("gameplay tick request exceeds bound");
    for (unsigned i = 0; i < ticks; ++i)
    {
        video_tick(input);
        service_tick();
    }
}
Json GameplaySession::state() const
{
    return impl_->state();
}
std::string_view GameplaySession::centerprint() const
{
    return impl_->hub_centerprint();
}
GameplayRenderSnapshot GameplaySession::render_snapshot(bool consume_weapon)
{
    return impl_->snapshot(consume_weapon);
}
void GameplaySession::set_live_sound(bool enabled)
{
    impl_->collect_sound = enabled;
    impl_->pending_sounds.clear();
    ++impl_->sound_generation;
}

std::uint64_t GameplaySession::sound_generation() const
{
    return impl_->sound_generation;
}

std::vector<GameplaySound> GameplaySession::take_sounds()
{
    return std::exchange(impl_->pending_sounds, {});
}

void GameplaySession::Impl::play_sound(std::string_view name, GameWord entity, std::uint8_t channel,
                                        std::uint8_t volume, std::uint8_t attenuation,
                                        std::optional<Vec3> position)
{
    if (!collect_sound || name.empty() || name == "misc/null.wav")
        return;
    if (!position && entity != 512)
    {
        const auto& world = assets().manifest.at("worldOrigin");
        if (std::size_t(entity) + 512 <= edicts.size() * sizeof(GameWord))
        {
            position = Vec3{
                world.at(0).get<double>() + gs(field(entity, "ORIGIN", 0)) / 8.0,
                world.at(1).get<double>() + gs(field(entity, "ORIGIN", 1)) / 8.0,
                world.at(2).get<double>() + gs(field(entity, "ORIGIN", 2)) / 8.0
            };
        }
        else
            position = Vec3{
                world.at(0).get<double>() + camera[0] / 16.0,
                world.at(1).get<double>() + camera[1] / 16.0,
                world.at(2).get<double>() + camera[2] / 16.0
            };
    }
    pending_sounds.push_back({std::string(name), entity, channel, volume, attenuation, position.value_or(Vec3{})});
}

std::array<std::uint16_t, 2> GameplaySession::entrance_render_rows(std::array<std::uint16_t, 2> poses) const
{
    return impl_->entrance_render_rows(poses);
}

void GameplaySession::Impl::reset(std::string_view map, unsigned skill)
{
    const auto found = std::find_if(maps.begin(), maps.end(), [&](const auto& a) { return a.map == map; });
    if (found == maps.end())
        throw std::runtime_error("requested map assets are unavailable");
    const auto index = std::size_t(found - maps.begin());
    const auto use_queue = queued_input;
    const auto live_sound = collect_sound;
    const auto next_sound_generation = sound_generation + 1;
    const auto run_enabled = always_run;
    const auto render_technique = technique;
    auto retained = std::move(maps);
    // A queued respawn can reset the map inside the current service continuation.
    auto observer = std::move(checkpoint_hook);
    *this = Impl{};
    checkpoint_hook = std::move(observer);
    queued_input = use_queue;
    collect_sound = live_sound;
    sound_generation = next_sound_generation;
    always_run = run_enabled;
    technique = render_technique;
    maps = std::move(retained);
    map_index = index;
    if (constant("QC_E1M3_GOLD_KEY") || constant("QC_E1M1_PLATFORM_FIRST"))
    {
        const auto& movers = metadata().at("stockExitMachinery").at("movers");
        for (std::size_t i = 0; i < movers.size(); ++i)
        {
            const auto& mover = movers.at(i);
            exit_offsets_q4.at(i) = mover.at("positionsQ4").front().get<int>();
            if (mover.contains("secondTrajectoryQ4"))
                exit_offsets_q4.at(movers.size() + i) = mover.at("secondTrajectoryQ4").front().get<int>();
        }
    }
    if (constant("QC_ORD_DOOR_COUNT"))
    {
        const auto& doors = metadata().at("stockExitMachinery").at("ordinaryDoors");
        for (std::size_t i = 0; i < doors.size(); ++i)
            ordinary_offset.at(i) = doors[i].at("startQ4").get<int>();
    }
    skill_selected = skill_active = skill & 3;
    globals = words(bytes("QuakeBSPQuakeCGlobals.bin"));
    edicts.assign(std::size_t(constant("QC_EDICT_BYTES")) / 2, 0);
    const auto& initial = bytes("QuakeBSPQuakeCEdicts.bin");
    const auto prefix = constant("QC_HUB_CLUE_EDICT", 0)
        ? edicts.size() * 2 : std::size_t(constant("QC_GRUNT"));
    if (prefix > initial.size() || prefix > edicts.size() * 2)
        throw std::runtime_error("truncated gameplay initial edicts");
    for (std::size_t i = 0; i < prefix; i += 2)
        e(0, i) = game_u16(initial, i);
    global("SKILL") = gw(skill_active * 64);
    gr_actor_moves.assign(std::size_t(constant("QC_GRUNT_COUNT")), 0);
    gr_actor_shots.assign(gr_actor_moves.size(), 0);
    if (constant("QC_GRUNT_COUNT"))
    {
        const auto& fields = bytes("QuakeBSPQuakeCGruntFields.bin");
        std::size_t cursor = prefix;
        const std::array<unsigned, 4> exclusions{0x100, 0x200, 0x400, 0x400};
        for (auto actor = constant("QC_GRUNT"); actor < constant("QC_GRUNT_DROP"); actor += 512)
        {
            const auto flags = game_u16(initial, cursor);
            cursor += 2;
            for (std::size_t i = 0; i < std::size_t(constant("QC_GRUNT_INIT_WORDS")); ++i)
            {
                const auto value = game_u16(initial, cursor);
                cursor += 2;
                if (!(flags & exclusions[skill_active]))
                    e(std::size_t(actor), game_u16(fields, i * 2)) = value;
            }
        }
        const auto source = std::size_t(constant("QC_ENTRANCE_INIT_OFFSET"));
        const auto target = std::size_t(constant("QC_ENTRANCE_INIT_TARGET"));
        const auto count = std::size_t(constant("QC_ENTRANCE_INIT_BYTES"));
        if (((source | target | count) & 1) || source + count > initial.size() || target + count > edicts.size() * 2)
            throw std::runtime_error("truncated entrance initial edicts");
        for (std::size_t i = 0; i < count; i += 2)
            e(0, target + i) = game_u16(initial, source + i);
    }
    shell_mask = gw((std::uint32_t{1} << unsigned(constant("QC_SHELL_COUNT"))) - 1);
    const auto health_count = constant("QC_HEALTH_COUNT");
    if (health_count < 0 || health_count > 16 ||
        (health_count && assets().manifest.at("metadata").at("gameplay").at("stockHealth").at("boxes").size() !=
            static_cast<std::size_t>(health_count)))
        throw std::runtime_error("gameplay health pickup count differs from its manifest");
    health_mask = gw((std::uint32_t{1} << unsigned(health_count)) - 1);
    health_sound = 0;
    pickup_notice_rows = {};
    pickup_notice_life = {};
    pickup_notice_next = pickup_notice_revision = pickup_bonus_ticks = 0;
    mega_timers = {};
    items_high = 0;
    powerup_mask = gw((1u << constant("QC_POWERUP_COUNT")) - 1);
    quad_warn_next = quad_warning_pulses = suit_warn_next = suit_warning_pulses = 0;
    armor_angle_step = 0;
    armor_mask = gw((1u << constant("QC_ARMOR_COUNT")) - 1);
    nails = {};
    combat_impacts = {};
    last_aim = {};
    last_aim_target = 0;
    impact_next = impact_message = impact_style = active_impacts = 0;
    super_shotgun_visible = constant("QC_SSG_ROW") != 0;
    nail_effect_rng = 0x4a3d;
    nail_impact_sound = 0;
    nail_frame = nail_next_frame = nail_shots = nail_actor_hits = nail_world_hits = 0;
    nail_mask = constant("QC_NAIL_COUNT") ? gw((2u << constant("QC_NAIL_COUNT")) - 1) : 0;
    if (health_count)
        field(512, "MAX_HEALTH") = 100 * 64;
    clock = gw(constant("QC_GRUNT_START_TIME", 128));
    fluorescent_phase = clock % 160;
    yaw = gw(assets().manifest.at("spawnYaw").get<int>());
    for (unsigned i = 0; i < 3; ++i)
        camera[i] = gs(assets().manifest.at("spawnEyeQ4").at(i).get<int>());
    hub_init();
}

void GameplaySession::Impl::queue_restart()
{
    restart_pending = true;
    if (queued_input)
        return;
    yaw = gw(assets().manifest.at("spawnYaw").get<int>());
    pitch = 0;
    for (unsigned i = 0; i < 3; ++i)
        camera[i] = gs(assets().manifest.at("spawnEyeQ4").at(i).get<int>());
}

void GameplaySession::Impl::menu(const GameplayInput&, GameWord triggered)
{
    enum : unsigned {
        level_row, render_row, brushes_row, entities_row, scale_row, skill_row, always_run_row, restart_row, menu_rows
    };
    auto close = [&] {
        menu_open = false;
        release_gate = true;
        scale = menu_scale == 0 ? 2 : 3;
        technique = draft_technique;
        entities_enabled = draft_entities;
        brushes_enabled = draft_brushes;
    };
    if (!menu_open)
    {
        if (triggered & 0x1000)
        {
            menu_open = true;
            menu_selection = 0;
            mouse_dx = mouse_dy = 0;
            draft_map = map_index;
            menu_scale = scale == 2 ? 0 : 1;
            draft_technique = technique;
            draft_entities = entities_enabled;
            draft_brushes = brushes_enabled;
        }
        return;
    }
    if (triggered & (0x8000 | 0x1000))
    {
        close();
        return;
    }
    if (triggered & 0x800)
    {
        menu_selection = (menu_selection + menu_rows - 1) % menu_rows;
        return;
    }
    if (triggered & 0x400)
    {
        menu_selection = (menu_selection + 1) % menu_rows;
        return;
    }
    const bool left = (triggered & 0x200) != 0, right = (triggered & 0x100) != 0, activate = (triggered & 0x80) != 0;
    if (!left && !right && !activate)
        return;
    switch (menu_selection)
    {
    case level_row:
        if (left || right)
            draft_map = (draft_map + (left ? maps.size() - 1 : 1)) % maps.size();
        else if (draft_map != map_index)
        {
            pending_map = maps.at(draft_map).map;
            campaign_exit = false;
            switch_pending = true;
            close();
        }
        break;
    case render_row:
    {
        constexpr std::array<unsigned, 4> render_order{4, 3, 2, 7};
        const auto current = std::ranges::find(render_order, draft_technique);
        const auto index = current == render_order.end() ? 0 : current - render_order.begin();
        draft_technique = render_order[(index + (left ? 3 : 1)) % render_order.size()];
        break;
    }
    case brushes_row:
        draft_brushes = !draft_brushes && constant("BSP_BRUSH_DYNAMIC_REPLAY_SUPPORTED", 1) != 0;
        break;
    case entities_row:
        draft_entities = !draft_entities && constant("BSP_RENDER_ENTITIES_SUPPORTED", 1) != 0;
        break;
    case scale_row:
        menu_scale ^= 1;
        break;
    case skill_row:
        skill_selected = (skill_selected + (left ? 3 : 1)) & 3;
        break;
    case always_run_row:
        always_run = !always_run;
        break;
    case restart_row:
        if (activate && !left && !right)
        {
            close();
            queue_restart();
        }
        break;
    }
}

void GameplaySession::Impl::publish_walk()
{
    if (!walk.pending)
        return;
    camera = walk.pending_xyz;
    if (pending_yaw_valid)
    {
        yaw = pending_yaw;
        pitch = intermission_phase == 2 ? gw(constant("QC_INTERMISSION_0_PITCH")) : 0;
        pending_yaw_valid = false;
    }
    walk.pending = false;
    ++revision;
}

std::size_t GameplaySession::Impl::input_record_cells(const GameplayControls& sample) const
{
    return constant("QC_INPUT_REPLAY_CELL_BYTES") && (sample.yaw_delta || sample.pitch_delta) ? 2 : 1;
}

void GameplaySession::Impl::latch_input(GameplayControls sample)
{
    if (input_clock.sample_pending)
        sample = input_clock.pending;
    else
    {
        sample.walk_speed = !always_run;
        input_clock.yaw_delta += sample.yaw_delta;
        input_clock.pitch_delta += sample.pitch_delta;
        if (!sample.menu && !sample.release)
        {
            input_clock.actions |= sample.buttons & 0x30;
            input_clock.cycle_weapon ^= sample.cycle_weapon;
        }
        else
            input_clock.cycle_weapon = false;
        if (++input_clock.divider < input_vblanks)
            return;
        if (!sample.menu && !sample.release)
        {
            sample.buttons |= input_clock.actions;
            sample.cycle_weapon = input_clock.cycle_weapon;
            sample.yaw_delta = input_clock.yaw_delta;
            sample.pitch_delta = input_clock.pitch_delta;
        }
    }
    if (sample.cycle_weapon || sample != input_clock.previous)
    {
        // Leave one cell empty to distinguish a full native ring from an empty one.
        const auto cell_bytes = constant("QC_INPUT_REPLAY_CELL_BYTES");
        const bool large_fifo = constant("QC_KNIGHT_ROSTER") && constant("QC_E1M2_GROUP_COUNT");
        const std::size_t capacity = cell_bytes ? 2048U / cell_bytes - 1 : (large_fifo ? 1023 : 255);
        const auto cells = input_record_cells(sample);
        if (input_clock.used_queue_cells + cells > capacity)
        {
            input_clock.sample_pending = true;
            input_clock.pending = sample;
            ++input_clock.waits;
            return;
        }
        input_clock.queue.emplace_back(gw(input_clock.tick + 1), sample);
        input_clock.used_queue_cells += cells;
        input_clock.previous = sample;
        input_clock.previous.cycle_weapon = false;
    }
    ++input_clock.tick;
    input_clock.sample_pending = false;
    input_clock.divider = input_clock.actions = 0;
    input_clock.cycle_weapon = false;
    input_clock.yaw_delta = input_clock.pitch_delta = 0;
}

void GameplaySession::Impl::consume_input()
{
    input_clock.active.cycle_weapon = false;
    if (!input_clock.queue.empty() && input_clock.queue.front().first == last)
    {
        input_clock.active = input_clock.queue.front().second;
        input_clock.used_queue_cells -= input_record_cells(input_clock.active);
        input_clock.queue.pop_front();
    }
    if (input_clock.respawn_release)
    {
        if (input_clock.active.buttons)
            return;
        input_clock.respawn_release = false;
    }
    if (intermission_phase == 2)
        return;
    if (input_clock.active.yaw_delta)
    {
        yaw = gw(yaw + input_clock.active.yaw_delta) & 255;
        ++revision;
    }
    const auto next_pitch = gw(std::clamp(int(gs(pitch)) + input_clock.active.pitch_delta, -64, 64));
    if (pitch != next_pitch)
    {
        pitch = next_pitch;
        ++revision;
    }
}

bool GameplaySession::Impl::request_respawn()
{
    if (gs(player("HEALTH")) > 0)
        return false;
    if (!(gameplay_buttons() & 0x20))
    {
        respawn_armed = true;
        return false;
    }
    if (!respawn_armed)
        return false;
    if (queued_input)
        input_clock.respawn_release = true;
    else
        release_gate = true;
    flash = damage_flash = 0;
    queue_restart();
    return true;
}

void GameplaySession::Impl::video_tick(const GameplayInput& input)
{
    ++video;
    if (pickup_bonus_ticks)
        --pickup_bonus_ticks;
    for (std::size_t i = 0; i < pickup_notice_life.size(); ++i)
        if (pickup_notice_life[i] && --pickup_notice_life[i] == 0)
        {
            pickup_notice_rows[i] = 0;
            ++pickup_notice_revision;
        }
    cycle_weapon = false;
    const auto triggered = gw(input.joypad & ~previous_buttons);
    previous_buttons = input.joypad;
    if (!menu_open)
    {
        sky_phase_q24 =
            (sky_phase_q24 + std::uint64_t(constant("BSP_SKY_FLY_CLOCK_PHASE_STEP_Q16", 8723)) * 256 +
             std::uint64_t(constant("BSP_SKY_FLY_CLOCK_FRACTION_STEP_Q8", 196))) &
            ((std::uint64_t{1} << 36) - 1);
        turbulence_phase_q24 = static_cast<std::uint32_t>(
            (turbulence_phase_q24 + std::uint64_t(constant("BSP_TURBULENCE_FLY_CLOCK_PHASE_STEP_Q16", 21809)) * 256 +
             std::uint64_t(constant("BSP_TURBULENCE_FLY_CLOCK_FRACTION_STEP_Q8", 106))) &
            0x7fffffff
        );
        alias_phase_q32 += static_cast<std::uint32_t>(constant("BSP_ALIAS_ROTATION_STEP_Q32", 0x012ee897));
    }
    if (restart_pending && !queued_input)
        return;
    menu(input, triggered);
    if (menu_open)
    {
        flash = damage_flash = 0;
        if (queued_input)
            latch_input({.menu = true});
        return;
    }
    if (damage_flash)
        --damage_flash;
    else if (flash)
        --flash;
    if (restart_pending && !queued_input)
        return;
    if (!queued_input)
        publish_walk();
    ++divider;
    buttons = input.joypad;
    int mx = 0, my = 0;
    const bool fine_look = !queued_input && scale == 3;
    const bool look_tick = fine_look || (divider & 1) == 0;
    const int cap = fine_look ? 4 : 8;
    if (input.mouse_connected)
    {
        mouse_dx = gs(std::clamp(int(mouse_dx) + input.mouse_dx, -15, 15));
        mouse_dy = gs(std::clamp(int(mouse_dy) + input.mouse_dy, -15, 15));
        if (input.mouse_buttons & 0x40)
            buttons |= 0x20;
        if (input.mouse_buttons & 0x80)
            buttons |= 0x8000;
        if (look_tick)
        {
            mx = std::clamp(int(mouse_dx), -cap, cap);
            my = -std::clamp(int(mouse_dy), -cap, cap);
            mouse_dx = gs(mouse_dx - mx);
            mouse_dy = gs(mouse_dy + my);
        }
    }
    else
        mouse_dx = mouse_dy = 0;
    if (release_gate)
    {
        if (!buttons)
            release_gate = false;
        if (queued_input)
            latch_input({.buttons = buttons, .release = release_gate});
        return;
    }
    if (!queued_input && request_respawn())
        return;
    if (triggered & 0x2000)
        technique = technique == 2 ? 4 : technique == 4 ? 7 : 2;
    int yaw_step = 0, pitch_step = 0;
    if (look_tick)
    {
        yaw_step = mx;
        if (buttons & 0x200)
            yaw_step -= cap;
        else if (buttons & 0x100)
            yaw_step += cap;
        pitch_step = my;
        if (buttons & 0x800)
            pitch_step += cap;
        else if (buttons & 0x400)
            pitch_step -= cap;
    }
    if (queued_input)
        latch_input({.buttons = buttons, .yaw_delta = -yaw_step, .pitch_delta = pitch_step,
                     .cycle_weapon = input.cycle_weapon});
    else
    {
        cycle_weapon = input.cycle_weapon;
        if (yaw_step)
        {
            yaw = gw(yaw - yaw_step) & 255;
            ++revision;
        }
        const auto next = std::clamp(int(gs(pitch)) + pitch_step, -64, 64);
        if (gs(pitch) != next)
        {
            pitch = gw(next);
            ++revision;
        }
    }
}

Json GameplaySession::Impl::state() const
{
    Json result{
        {"map", assets().map},
        {"videoTick", video},
        {"lastTick", last},
        {"services", services},
        {"phase", phase},
        {"cameraQ4", camera},
        {"pendingQ4", walk.pending_xyz},
        {"pending", walk.pending},
        {"pendingYaw", pending_yaw},
        {"pendingYawValid", pending_yaw_valid},
        {"pendingMap", pending_map},
        {"skillSelected", skill_selected},
        {"skillActive", skill_active},
        {"hubTeleports", hub_teleports},
        {"hubTeleportCooldown", hub_teleport_cooldown},
        {"yaw", yaw},
        {"pitch", gs(pitch)},
        {"controlDivider", divider},
        {"menuOpen", menu_open},
        {"releaseGate", release_gate},
        {"renderScale", scale},
        {"flyPlaybackMode", scale == 2 ? 2 : 6},
        {"surfaceClock",
         {{"skyPhaseQ24", sky_phase_q24},
          {"turbulencePhaseQ24", turbulence_phase_q24},
          {"aliasPhaseQ32", alias_phase_q32}}},
        {"walk",
         {{"ticks", walk.ticks},
          {"grounded", walk.grounded},
          {"velocityZ", walk.velocity_z},
          {"velocityXY", walk.velocity_xy},
          {"impacts", walk.impacts},
          {"slides", walk.slides},
          {"stairs", walk.stairs},
          {"traceFault", walk.trace_fault},
          {"startsolid", walk.startsolid},
          {"jumpHeld", walk.jump_held}}},
        {"shotgun",
         {{"shots", shots},
          {"pellets", pellets},
          {"hits", hits},
          {"impactEvents", impact_events},
          {"clock", shot_clock},
          {"rng", shot_rng},
          {"navRng", nav_rng},
          {"flash", flash}}},
        {"quakec",
         {{"ticks", qc_ticks},
          {"clock", clock},
          {"brushRow", brush_row},
          {"doorPose", door_pose},
          {"buttonPose", button_pose},
          {"entrancePose", entrance_pose},
          {"shellMask", shell_mask},
          {"fault", fault},
          {"faultOpcode", fault_opcode},
          {"callbacks", callbacks},
          {"statements", statements},
          {"sounds", sounds},
          {"activations", activations},
          {"doorBlocks", door_blocks}}},
        {"player",
         {{"health", player("HEALTH")},
          {"ammoShells", player("AMMO_SHELLS")},
          {"currentAmmo", player("CURRENTAMMO")},
          {"items", player("ITEMS")},
          {"attackFinished", player("ATTACK_FINISHED")}}},
        {"grunts", Json::array()}
    };
    if (constant("QC_BACKPACK_COUNT"))
    {
        auto& packs = result["quakec"]["backpacks"] = Json::array();
        for (int i = 0; i < constant("QC_BACKPACK_COUNT"); ++i)
        {
            const auto actor = gw(constant("QC_GRUNT") + 512 * i);
            if (!e(actor, pack_life) || (e(actor, pack_life) & 0x8000))
                continue;
            GamePoint origin{}, velocity{};
            for (unsigned axis = 0; axis < 3; ++axis)
            {
                origin[axis] = gs(e(actor, pack_origin + axis * 2));
                velocity[axis] = gs(e(actor, pack_velocity + axis * 2));
            }
            packs.push_back({{"soldierSlot", actor / 512}, {"originQ3", origin},
                {"velocityQ3", velocity}, {"shellsQ6", e(actor, pack_shells)}, {"lifeQ6", e(actor, pack_life)}});
        }
    }
    if (constant("QC_PICKUP_NOTICES"))
        result["quakec"]["pickupNotify"] = {
            {"rows", pickup_notice_rows}, {"life", pickup_notice_life}, {"next", pickup_notice_next},
            {"revision", pickup_notice_revision}, {"bonusTicks", pickup_bonus_ticks}};
    if (const auto box = constant("QC_EXPLOBOX"))
    {
        for (const auto& [key, name] : {std::pair{"health", "HEALTH"}, {"solid", "SOLID"},
                 {"takedamage", "TAKEDAMAGE"}, {"model", "MODEL"}, {"frame", "FRAME"},
                 {"think", "THINK"}, {"nextthink", "NEXTTHINK"}})
            result["quakec"]["explobox"][key] = e(box, constant("QC_FIELD_" + std::string(name)));
        if (constant("QC_EXPLOSION_LIFE"))
        {
            auto& effect = result["quakec"]["explobox"];
            effect["particleLife"] = e(box, constant("QC_EXPLOSION_LIFE"));
            for (unsigned axis = 0; axis < 3; ++axis)
                effect["particleOrigin"].push_back(gs(e(box, constant("QC_EXPLOSION_EMITTER") + 2 * axis)));
        }
    }
    if (constant("QC_GIB_FIRST_ROW"))
    {
        auto& gibs = result["quakec"]["gibs"] = Json::array();
        for (int actor = int(constant("QC_GRUNT")); actor < constant("QC_GRUNT_DROP"); actor += 512)
        {
            if (!(e(actor, gib_records + gib_row) & 0x8000))
                continue;
            for (unsigned piece = 0; piece < 4; ++piece)
            {
                const unsigned record = gib_records + piece * gib_size;
                if (!e(actor, record))
                    continue;
                auto vector = [&](unsigned start) {
                    return GamePoint{gs(e(actor, record + start)), gs(e(actor, record + start + 2)),
                                     gs(e(actor, record + start + 4))};
                };
                gibs.push_back({{"slot", actor / 512}, {"piece", piece}, {"lifeQ6", e(actor, record)},
                    {"spriteRow", e(actor, record + gib_row) & 255}, {"originQ3", vector(gib_origin)},
                    {"velocityQ3", vector(gib_velocity)}, {"anglesQ6", vector(gib_angles)}, {"spinQ3", vector(gib_spin)}});
            }
        }
    }
    if (constant("QC_ARMOR_COUNT"))
    {
        result["quakec"]["armorMask"] = armor_mask;
    }
    if (constant("QC_ARMOR_COUNT") || constant("QC_CAMPAIGN_ITEMS"))
    {
        result["player"]["armorValue"] = player("ARMORVALUE");
        result["player"]["armorType"] = player("ARMORTYPE");
    }
    if (constant("QC_IMPACT_ROW"))
    {
        result["shotgun"]["aimTarget"] = last_aim_target;
        result["shotgun"]["aimQ6"] = last_aim;
        auto& bursts = result["shotgun"]["bursts"] = Json::array();
        for (std::size_t i = 0; i < combat_impacts.size(); ++i)
        {
            const auto& burst = combat_impacts[i];
            if (burst.life)
                bursts.push_back({{"slot", i}, {"life", burst.life}, {"style", burst.first_frame / 5},
                                  {"originQ3", burst.origin}, {"delta", burst.delta}});
        }
    }
    if (constant("QC_CAMPAIGN_ITEMS"))
    {
        result["player"]["ammoNails"] = player("AMMO_NAILS");
        result["player"]["weapon"] = player("WEAPON");
        result["player"]["itemsHigh"] = items_high;
    }
    if (constant("QC_FIELD_AMMO_ROCKETS") && (constant("QC_ARMOR_COUNT") || constant("QC_CAMPAIGN_ITEMS")))
    {
        result["player"]["ammoRockets"] = player("AMMO_ROCKETS");
        result["player"]["ammoCells"] = player("AMMO_CELLS");
    }
    if (constant("QC_NAIL_COUNT") || constant("QC_CAMPAIGN_ITEMS"))
    {
        if (constant("QC_NAIL_COUNT"))
            result["quakec"]["nailMask"] = nail_mask;
        if (constant("QC_SSG_ROW"))
            result["quakec"]["superShotgunVisible"] = super_shotgun_visible;
        result["player"]["ammoNails"] = player("AMMO_NAILS");
        result["player"]["weapon"] = player("WEAPON");
        result["nailgun"] = {{"frame", nail_frame}, {"shots", nail_shots}, {"actorHits", nail_actor_hits},
                             {"worldHits", nail_world_hits}, {"impactSound", nail_impact_sound}, {"projectiles", Json::array()}};
        for (const auto& nail : nails)
            if (nail.life)
                result["nailgun"]["projectiles"].push_back({{"originQ3", nail.origin}, {"life", nail.life}, {"yaw", nail.yaw}});
    }
    if (constant("QC_POWERUP_COUNT"))
    {
        result["quakec"]["powerupMask"] = powerup_mask;
        result["quakec"]["quadWarningPulses"] = quad_warning_pulses;
        result["quakec"]["quadWarnNext"] = quad_warn_next;
        result["quakec"]["quadSoundNext"] = player("SUPER_SOUND");
        result["player"]["quadFinished"] = player("SUPER_DAMAGE_FINISHED");
        if (constant("QC_POWERUP_COUNT") >= 2)
        {
            result["player"]["suitFinished"] = player("RADSUIT_FINISHED");
            result["walk"]["waterLevel"] = water_level;
            result["walk"]["waterType"] = liquid_type;
            result["walk"]["airTicks"] = air_ticks;
            result["walk"]["drownDamage"] = drown_damage;
            result["walk"]["slimeDamageNext"] = slime_damage_next;
            result["quakec"]["suitWarnNext"] = suit_warn_next;
            result["quakec"]["suitWarningPulses"] = suit_warning_pulses;
        }
    }
    if (constant("QC_HEALTH_COUNT"))
    {
        result["quakec"]["healthMask"] = health_mask;
        result["quakec"]["healthSound"] = health_sound;
        if (constant("QC_MEGA_COUNT"))
        {
            result["quakec"]["megaTimers"] = mega_timers;
            result["player"]["itemsHigh"] = items_high;
        }
    }
    if (constant("QC_EXIT_MOVER_COUNT"))
    {
        result["quakec"]["exitPoseWord"] = exit_pose_word();
        result["quakec"]["exitTargets"] = exit_targets;
        if (constant("QC_SECRET_DOOR_COUNT"))
        {
            auto& qc = result["quakec"];
            qc["secretDoorPhases"] = secret_door_phase;
            qc["secretDoorTravelQ5"] = secret_door_travel;
            qc["secretDoorPoses"] = secret_door_pose;
            if (constant("QC_ORD_DOOR_COUNT"))
            {
                qc["ordinaryDoorPhases"] = ordinary_phase;
                qc["ordinaryDoorAges"] = ordinary_age;
                qc["ordinaryDoorPoses"] = ordinary_pose;
                qc["ordinaryDoorOffsetsQ4"] = ordinary_offset;
                qc["ordinaryLights"] = ordinary_lights;
                if (constant("QC_T3_LIGHT_STYLE"))
                    qc["t3TriggerState"] = t3_trigger_state;
            }
            qc["secretDoorOffsetsQ4"] = secret_door_xy;
        }
        if (const auto first = constant("QC_E1M1_PLATFORM_FIRST"))
        {
            result["quakec"]["platformPhases"] = platform_phase;
            result["quakec"]["platformAges"] = platform_age;
            result["quakec"]["platformWaits"] = platform_wait;
            result["quakec"]["platformOffsetsQ4"] = std::vector<int>(exit_offsets_q4.begin() + first,
                exit_offsets_q4.begin() + first + platform_phase.size());
        }
        if (constant("QC_E1M2_GROUP_COUNT"))
            result["quakec"][constant("QC_E1M3_GOLD_KEY") ? "goldKey" : "silverKey"] = e1m2_key;
        if (constant("QC_E1M3_GOLD_KEY"))
        {
            auto& qc = result["quakec"];
            qc["moverOffsetsQ4"] = std::vector<int>(exit_offsets_q4.begin(),
                exit_offsets_q4.begin() + 2 * constant("QC_EXIT_MOVER_COUNT"));
            qc["platformAge"] = key_platform_age;
            qc["platformPhase"] = key_platform_phase;
            qc["platformWait"] = key_platform_wait;
            qc["stairButtonHit"] = e1m3_stair_button_hit;
        }
    }
    if (!hub_warning_triggers.empty())
    {
        result["hubWarningQ6"] = hub_warning_ticks;
        result["hubWarningGate"] = hub_warning_gate;
        result["hubWarningEvents"] = hub_warning_events;
        result["centerprint"] = hub_centerprint();
    }
    if (constant("QC_INTERMISSION_COUNT"))
        result["intermission"] = {{"phase", intermission_phase}, {"wait", intermission_wait},
            {"subseconds", intermission_subseconds}, {"seconds", intermission_seconds}, {"camera", intermission_camera},
            {"kills", intermission_kills}, {"monsters", intermission_monsters}};
    if (!secrets.empty())
    {
        result["foundSecrets"] = found_secrets;
        result["totalSecrets"] = secrets.size();
    }
    if (hub_clue_edict)
        result["hubClueCooldownQ6"] = hub_clue_cooldown;
    for (auto actor = constant("QC_GRUNT"); actor < constant("QC_GRUNT_DROP"); actor += 512)
    {
        auto read = [&](std::string_view name, unsigned axis = 0) {
            return edicts.at(
                (std::size_t(actor) + std::size_t(constant("QC_FIELD_" + std::string(name))) + axis * 2) / 2
            );
        };
        Json row{
            {"slot", actor / 512},
            {"originQ3", {gs(read("ORIGIN", 0)), gs(read("ORIGIN", 1)), gs(read("ORIGIN", 2))}},
            {"angles", {read("ANGLES", 0), read("ANGLES", 1), read("ANGLES", 2)}}
        };
        for (auto [key, name] :
             {std::pair{"health", "HEALTH"},
              {"model", "MODEL"},
              {"solid", "SOLID"},
              {"frame", "FRAME"},
              {"nextthink", "NEXTTHINK"},
              {"think", "THINK"},
              {"enemy", "ENEMY"},
              {"attackFinished", "ATTACK_FINISHED"},
              {"flags", "FLAGS"}})
            row[key] = read(name);
        result["grunts"].push_back(std::move(row));
    }
    if (constant("QC_AXE_FUNCTION"))
        result["axe"] = {{"selected", axe_selected}, {"pending", axe_pending},
                         {"swings", axe_swings}, {"hits", axe_hits}};
    if (queued_input)
    {
        result["inputTick"] = input_clock.tick;
        result["inputWaits"] = input_clock.waits;
    }
    return result;
}

Camera gameplay_render_camera(const std::array<std::int16_t, 3>& eye_q4, int yaw, int pitch, int position_units)
{
    auto coarse = [&](unsigned axis) {
        return game_asr(eye_q4[axis], 8);
    };
    Camera camera{coarse(0), coarse(1), coarse(2), yaw, pitch};
    if (position_units != 4 && position_units != 8 && position_units != 16)
        fail("unsupported playable camera position grid");
    const auto mask = 4 - position_units / 4;
    for (unsigned axis = 0; axis < 3; ++axis)
        camera.residual_q2[axis] = (gw(eye_q4[axis]) >> 6) & mask;
    return camera;
}

GameplayRenderSnapshot GameplaySession::Impl::snapshot(bool consume_weapon)
{
    GameplayRenderSnapshot result;
    result.map = assets().map;
    static constexpr std::array<std::string_view, 13> notify_rows = {
        "", "You got the shells", "You got the nails", "You got the nailgun", "You got armor",
        "You receive 15 health", "You receive 25 health", "You receive 100 health", "You got the Quad Damage",
        "You got the Biosuit", "You get 5 shells", "You got the Double-barrelled", "Shotgun"
    };
    if (!menu_open)
    {
        if (!liquid_nodes.empty())
            result.eye_contents = liquid_contents(camera, 0);
        result.pickup_bonus_ticks = pickup_bonus_ticks;
        result.damage_tint = damage_flash != 0;
        result.muzzle_tint = flash != 0;
        std::size_t line = 0;
        for (std::size_t i = 0; i < pickup_notice_rows.size(); ++i)
        {
            const auto id = pickup_notice_rows.at((pickup_notice_next / 2 + i) % pickup_notice_rows.size());
            if (id)
                result.pickup_lines.at(line++) = notify_rows.at(id);
        }
    }
    result.quad_tint = (items_high & constant("QC_POWERUP_0_ITEM_HIGH")) != 0;
    result.suit_tint = (items_high & constant("QC_POWERUP_1_ITEM_HIGH")) != 0;
    result.video_tick = video;
    result.eye_q4 = camera;
    result.camera_position_units =
        assets().manifest.value("billboards", Json::object()).value("cameraPositionUnits", 16);
    result.native_camera = gameplay_render_camera(camera, yaw, pitch & 255, result.camera_position_units);
    const auto position_q2 = result.native_camera.position_q2();
    const auto origin = assets().manifest.at("worldOrigin");
    result.source_camera.origin = {
        origin[0].get<double>() + position_q2[0] * 4,
        origin[1].get<double>() + position_q2[1] * 4,
        origin[2].get<double>() + position_q2[2] * 4
    };
    result.source_camera.yaw = yaw * 360. / 256;
    result.source_camera.pitch = -gs(pitch) * 360. / 256;
    // Retain native Q6 quantization with Quake's screen-right convention.
    // The legacy packed projection uses the opposite right vector.
    const double sy = sine(result.native_camera.yaw) / 64.0;
    const double cy = cosine(result.native_camera.yaw) / 64.0;
    const double sp = sine(result.native_camera.pitch) / 64.0;
    const double cp = cosine(result.native_camera.pitch) / 64.0;
    result.source_camera.capture_basis =
        std::array{Vec3{cp * cy, cp * sy, sp}, Vec3{sy, -cy, 0}, Vec3{-sp * cy, -sp * sy, cp}};
    result.shell_mask = shell_mask;
    if (const auto box = constant("QC_EXPLOBOX"))
        result.explobox_solid = e(box, constant("QC_FIELD_SOLID")) != 0;
    result.health_mask = health_mask;
    result.nail_mask = nail_mask;
    result.technique = technique;
    result.render_scale = scale;
    result.brushes_enabled = brushes_enabled;
    result.entities_enabled = entities_enabled;
    result.brush_row = brush_row;
    result.switched_lights = static_cast<std::uint8_t>(ordinary_lights | (t3_trigger_state & 16U));
    if (constant("QC_FLUORESCENT_STYLE"))
    {
        constexpr std::string_view pattern = "mmamammmmammamamaaamammma";
        if (pattern[fluorescent_phase * 10 / 64] == 'a')
            result.switched_lights |= 32;
    }
    result.surface_time = double(sky_phase_q24) / (8. * 16777216.);
    result.sky_phase_q24 = sky_phase_q24;
    result.turbulence_phase_q24 = turbulence_phase_q24;
    result.alias_phase_q32 = alias_phase_q32;
    const auto& meta = metadata();
    if (constant("QC_ENTRANCE_COUNT"))
        result.entrance_rows = entrance_render_rows(entrance_pose);
    if (constant("QC_EXIT_MOVER_COUNT"))
    {
        result.exit_pose_word = exit_pose_word();
        const auto& movers = meta.at("stockExitMachinery").at("movers");
        if (movers.size() > result.exit_rows.size() || movers.size() > exit_poses.size())
            throw std::runtime_error("gameplay exit mover roster exceeds its snapshot");
        for (std::size_t i = 0; i < movers.size(); ++i)
        {
            const auto& mover = movers.at(i);
            result.exit_rows[i] = mover.at(mover.contains("visualRows") ? "visualRows" : "poseRows")
                                      .at(exit_poses[i]).get<GameWord>();
        }
        if (constant("QC_SECRET_DOOR_COUNT"))
        {
            const auto& doors = meta.at("stockExitMachinery").at("secretDoors");
            for (std::size_t i = 0; i < doors.size(); ++i)
                result.exit_rows.at(movers.size() + i) = doors.at(i).at("visualRows").at(secret_door_pose.at(i)).get<GameWord>();
            if (constant("QC_ORD_DOOR_COUNT"))
            {
                const auto& ordinary = meta.at("stockExitMachinery").at("ordinaryDoors");
                for (std::size_t i = 0; i < ordinary.size(); ++i)
                    result.exit_rows.at(movers.size() + doors.size() + i) =
                        ordinary.at(i).at("visualRows").at(ordinary_pose.at(i)).get<GameWord>();
            }
        }
    }
    const auto& roster = meta.at("stockGrunts");
    for (std::size_t i = 0; i < roster.size(); ++i)
    {
        const auto actor = gw(constant("QC_GRUNT") + std::int64_t(i) * 512);
        GameplayActorPose pose;
        pose.slot = actor / 512;
        pose.entity =
            static_cast<std::uint16_t>(roster[i].value("renderEntity", roster[i].at("entityNumber").get<int>()));
        pose.model = roster[i].at("model").get<std::string>();
        pose.visible = field(actor, "MODEL") != 0;
        pose.mdl_frame = field(actor, "FRAME") >> 6;
        if (constant("QC_GIB_FIRST_ROW") && (e(actor, gib_records + gib_row) & 0x8000))
        {
            pose.sprite_row = unsigned(e(actor, gib_records + gib_row) & 0xff);
            pose.model = i < std::size_t(constant("QC_BACKPACK_COUNT")) ? "progs/h_guard.mdl" : "progs/h_dog.mdl";
            pose.mdl_frame = 0;
        }
        pose.yaw = static_cast<std::uint8_t>(field(actor, "ANGLES", 1) / 90);
        for (unsigned axis = 0; axis < 3; ++axis)
        {
            pose.origin_q3[axis] = gs(field(actor, "ORIGIN", axis));
            pose.render_origin_q2[axis] = gs(game_asr(int(pose.origin_q3[axis]) - (axis == 2 ? 176 : 0) + 16, 5));
        }
        result.actors.push_back(std::move(pose));
    }
    auto add_rotating_items = [&](const char* name, GameWord mask) {
        unsigned bit = 0;
        for (const auto& item : meta.at(name))
        {
            GameplayActorPose pose;
            pose.entity = item.at("entityNumber");
            pose.model = item.at("model");
            pose.mdl_frame = item.at("frame");
            pose.sprite_row = item.at("spriteRow").get<unsigned>();
            pose.yaw = static_cast<std::uint8_t>(armor_angle_step * 256 / 72);
            pose.visible = (mask & (1u << bit++)) != 0;
            pose.origin_q3 = item.at("originQ3").get<GamePoint>();
            pose.render_origin_q2 = item.at("renderOriginQ2").get<GamePoint>();
            result.actors.push_back(std::move(pose));
        }
    };
    if (constant("QC_ARMOR_COUNT"))
        add_rotating_items("stockArmor", armor_mask);
    if (constant("QC_POWERUP_COUNT"))
        add_rotating_items("stockPowerups", powerup_mask);
    auto add_weapon_pickup = [&](const Json& item, bool visible) {
        GameplayActorPose pose;
        pose.entity = item.at("entityNumber").get<std::uint16_t>();
        pose.model = item.at("model").get<std::string>();
        pose.sprite_row = item.at("spriteRow").get<unsigned>();
        pose.yaw = static_cast<std::uint8_t>(armor_angle_step * 256 / 72);
        pose.visible = visible;
        pose.origin_q3 = item.at("originQ3").get<decltype(pose.origin_q3)>();
        pose.render_origin_q2 = item.at("renderOriginQ2").get<decltype(pose.render_origin_q2)>();
        result.actors.push_back(std::move(pose));
    };
    if (constant("QC_NAIL_COUNT"))
        add_weapon_pickup(meta.at("stockNailgun").at("gun"), nail_mask & (1u << constant("QC_NAIL_COUNT")));
    if (constant("QC_SSG_ROW"))
        add_weapon_pickup(meta.at("stockSuperShotgun").at("pickup"), super_shotgun_visible);
    for (int index = 0; index < constant("QC_BACKPACK_COUNT"); ++index)
    {
        const auto actor = gw(constant("QC_GRUNT") + index * 512);
        if (!e(actor, pack_life) || (e(actor, pack_life) & 0x8000))
            continue;
        GameplayActorPose pose;
        pose.entity = std::uint16_t(0x4000 + index);
        pose.slot = actor / 512;
        pose.model = "progs/backpack.mdl";
        pose.visible = true;
        pose.sprite_row = static_cast<unsigned>(constant("QC_BACKPACK_ROW"));
        pose.yaw = static_cast<std::uint8_t>(constant("QC_ARMOR_COUNT") ? armor_angle_step * 256 / 72 : alias_phase_q32 >> 24);
        for (unsigned axis = 0; axis < 3; ++axis)
        {
            pose.origin_q3[axis] = gs(e(actor, pack_origin + 2 * axis));
            pose.render_origin_q2[axis] = gs(game_asr(int(pose.origin_q3[axis]) - (axis == 2 ? 176 : 0) + 16, 5));
        }
        result.actors.push_back(std::move(pose));
    }
    if (meta.contains("staticAmbientMdls"))
        for (const auto& actor : meta.at("staticAmbientMdls"))
        {
            GameplayActorPose pose;
            pose.entity = actor.at("entityNumber").get<std::uint16_t>();
            pose.model = actor.at("model").get<std::string>();
            pose.mdl_frame = actor.at("frame").get<std::uint16_t>();
            pose.yaw = actor.at("yaw").get<std::uint8_t>();
            pose.visible = !constant("QC_E1M2_GROUP_COUNT") || e1m2_key == 0;
            for (unsigned axis = 0; axis < 3; ++axis)
            {
                pose.origin_q3[axis] = actor.at("originQ3").at(axis).get<std::int16_t>();
                pose.render_origin_q2[axis] = actor.at("renderOriginQ2").at(axis).get<std::int16_t>();
            }
            result.actors.push_back(std::move(pose));
        }
    if (constant("QC_NAIL_COUNT") || constant("QC_CAMPAIGN_ITEMS"))
        for (std::size_t i = 0; i < nails.size(); ++i)
        {
            const auto& nail = nails[i];
            if (!nail.life)
                continue;
            GameplayActorPose pose;
            pose.entity = gw(0x6000 + i);
            pose.model = "progs/spike.mdl";
            pose.visible = true;
            pose.sprite_row = static_cast<unsigned>(constant("QC_SPIKE_ROW"));
            pose.yaw = static_cast<std::uint8_t>(nail.yaw);
            pose.origin_q3 = nail.origin;
            for (unsigned axis = 0; axis < 3; ++axis)
                pose.render_origin_q2[axis] = gs(game_asr(int(nail.origin[axis]) - (axis == 2 ? 176 : 0) + 16, 5));
            result.actors.push_back(std::move(pose));
        }

    if (const auto box = constant("QC_EXPLOBOX"); box && e(box, constant("QC_FIELD_MODEL")) == constant("QC_EXPLOSION_MODEL"))
    {
        GameplayActorPose pose;
        pose.entity = meta.at("stockExplobox").at("entityNumber").get<std::uint16_t>();
        pose.slot = static_cast<std::uint16_t>(box / 512);
        pose.model = meta.at("stockExplobox").at("explosionModel").get<std::string>();
        pose.mdl_frame = e(box, constant("QC_FIELD_FRAME")) / 64;
        pose.sprite_row = static_cast<unsigned>(constant("QC_EXPLOSION_ROW")) + pose.mdl_frame;
        pose.visible = true;
        for (unsigned axis = 0; axis < 3; ++axis)
        {
            pose.origin_q3[axis] = gs(e(box, constant("QC_FIELD_ORIGIN") + 2 * axis));
            pose.render_origin_q2[axis] = gs(game_asr(int(pose.origin_q3[axis]) - (axis == 2 ? 176 : 0) + 16, 5));
        }
        result.actors.push_back(std::move(pose));
    }
    // Mover, backpack and projectile rows share the native live pose allocation.
    const auto transient_capacity = [&] {
        return roster.size() + meta.at("stockArmor").size() + meta.at("stockPowerups").size() +
               std::size_t(constant("QC_BACKPACK_COUNT")) + (constant("QC_NAIL_COUNT") ? 1 + nails.size() : 0) +
               (constant("QC_SSG_ROW") ? 1 : 0) + (constant("QC_EXPLOBOX") ? 1 : 0);
    };
    if (constant("QC_GIB_FIRST_ROW"))
    {
        const auto max_poses = transient_capacity();
        if (const auto box = constant("QC_EXPLOBOX"); box && e(box, constant("QC_EXPLOSION_LIFE")))
        {
            const auto cloud_frame = constant("QC_EXPLOSION_PHASES") - (e(box, constant("QC_EXPLOSION_LIFE")) + 1) / 2;
            const auto& effect = meta.at("stockExplobox");
            const auto rows = effect.at("particleRows").at(cloud_frame).get<std::array<unsigned, 2>>();
            const auto first = effect.at("particleRows").front().front().get<unsigned>();
            for (auto row = rows[0]; row < rows[1] && result.actors.size() < max_poses; ++row)
            {
                GameplayActorPose pose;
                pose.entity = gw(0x7000 + row);
                pose.model = effect.at("particleModel").get<std::string>();
                pose.sprite_row = row;
                pose.mdl_frame = gw(row - first);
                pose.visible = true;
                for (unsigned axis = 0; axis < 3; ++axis)
                {
                    pose.render_origin_q2[axis] = gs(e(box, constant("QC_EXPLOSION_EMITTER") + 2 * axis));
                    pose.origin_q3[axis] = gs(pose.render_origin_q2[axis] * 32 + (axis == 2 ? 176 : 0));
                }
                result.actors.push_back(std::move(pose));
            }
        }
        for (std::size_t i = 0; i < roster.size(); ++i)
        {
            const auto actor = gw(constant("QC_GRUNT") + i * 512);
            for (unsigned piece = 1; piece <= 3; ++piece)
            {
                const unsigned record = gib_records + gib_size * piece;
                if (!e(actor, record) || result.actors.size() >= max_poses)
                    continue;
                GameplayActorPose pose;
                pose.entity = std::uint16_t(0x5000 + i * 3 + piece - 1);
                pose.slot = actor / 512;
                pose.sprite_row = e(actor, record + gib_row);
                pose.model = "progs/gib" + std::to_string(*pose.sprite_row - constant("QC_GIB_FIRST_ROW") - 1) + ".mdl";
                pose.visible = true;
                pose.yaw = std::uint8_t(e(actor, record + gib_angles + 2) / 90);
                for (unsigned axis = 0; axis < 3; ++axis)
                {
                    pose.origin_q3[axis] = gs(e(actor, record + gib_origin + 2 * axis));
                    pose.render_origin_q2[axis] = gs(game_asr(int(pose.origin_q3[axis]) - (axis == 2 ? 176 : 0) + 16, 5));
                }
                result.actors.push_back(std::move(pose));
            }
        }
    }
    if (constant("QC_TELEPORT_FOG_ROW") && !hub_teleporters.empty() && hub_teleport_cooldown >= 24)
    {
        const auto max_poses = transient_capacity();
        const auto frame = unsigned(((45 - hub_teleport_cooldown) * 20 + 16) / 64);
        for (unsigned part = 0; part < 6 && result.actors.size() < max_poses; ++part)
        {
            GameplayActorPose pose;
            const bool end = part >= 3;
            pose.entity = std::uint16_t(0x5800 + part);
            pose.model = "effects/te_teleport.spr";
            pose.mdl_frame = static_cast<std::uint16_t>(3 * frame + part % 3);
            pose.sprite_row = unsigned(constant("QC_TELEPORT_FOG_ROW")) + pose.mdl_frame;
            pose.visible = true;
            const auto eye = end ? hub_teleporters.front().destination : teleport_departure_eye;
            for (unsigned axis = 0; axis < 3; ++axis)
            {
                const int q4 = eye[axis] + ((end && axis == 0) ? 32 * 16 : 0) - (axis == 2 ? 22 * 16 : 0);
                pose.origin_q3[axis] = gs(game_asr(q4, 1));
                pose.render_origin_q2[axis] = gs(game_asr(q4 + 32, 6));
            }
            result.actors.push_back(std::move(pose));
        }
    }
    if (active_impacts)
    {
        const auto capacity = transient_capacity();
        for (std::size_t i = 0; i < combat_impacts.size() && result.actors.size() < capacity; ++i)
        {
            const auto& burst = combat_impacts[i];
            if (!burst.life)
                continue;
            GameplayActorPose pose;
            pose.entity = std::uint16_t(0x5900 + i);
            pose.model = "effects/combat-impact.spr";
            pose.mdl_frame = std::uint16_t(burst.first_frame + (9 - burst.life) / 2);
            pose.sprite_row = unsigned(constant("QC_IMPACT_ROW")) + pose.mdl_frame;
            pose.visible = true;
            pose.origin_q3 = burst.origin;
            for (unsigned axis = 0; axis < 3; ++axis)
                pose.render_origin_q2[axis] = gs(game_asr(burst.origin[axis] - (axis == 2 ? 176 : 0) + 16, 5));
            result.actors.push_back(std::move(pose));
        }
    }
    auto add_brush = [&](const Json& row) {
        BrushEntityState brush;
        brush.entity = static_cast<std::uint16_t>(row.value("entity", row.value("entity_number", 0)));
        brush.model_index = static_cast<std::uint16_t>(row.value("modelIndex", row.value("model_index", 0)));
        brush.inline_model = static_cast<std::uint16_t>(row.value("inlineModel", row.value("inline_model", 0)));
        brush.frame = static_cast<std::uint8_t>(row.value("frame", 0));
        const auto position = row.at("origin");
        brush.origin = {position[0].get<double>(), position[1].get<double>(), position[2].get<double>()};
        if (row.contains("angles"))
            for (unsigned i = 0; i < 3; ++i)
                brush.angles[i] = static_cast<std::int8_t>(row.at("angles")[i].get<int>());
        auto found = std::find_if(result.brushes.begin(), result.brushes.end(), [&](const auto& old) {
            return old.entity == brush.entity;
        });
        if (found != result.brushes.end())
            *found = brush;
        else
            result.brushes.push_back(brush);
    };
    if (assets().manifest.contains("authoredBrushes"))
        for (const auto& row : assets().manifest.at("authoredBrushes"))
            add_brush(row);
    if (assets().manifest.contains("brushRows"))
    {
        const auto& rows = assets().manifest.at("brushRows");
        if (brush_row >= rows.size())
            throw std::runtime_error("gameplay brush row out of range");
        const auto& row = rows.at(brush_row);
        for (const auto& brush : row.is_array() ? row : row.at("brushes"))
            add_brush(brush);
        const auto add_variant = [&](unsigned entity, GameWord pose_row) {
            const auto& selected = rows.at(pose_row);
            for (const auto& brush : selected.is_array() ? selected : selected.at("brushes"))
                if (brush.value("entity", brush.value("entity_number", 0U)) == entity)
                    add_brush(brush);
        };
        if (constant("QC_ENTRANCE_COUNT"))
            for (unsigned leaf = 0; leaf < entrance_pose.size(); ++leaf)
            {
                const auto entity = meta.at("stockEntranceDoors").at(leaf).at("renderEntity").get<unsigned>();
                add_variant(entity, result.entrance_rows[leaf]);
            }
        if (constant("QC_EXIT_MOVER_COUNT"))
        {
            const auto& movers = meta.at("stockExitMachinery").at("movers");
            for (std::size_t i = 0; i < movers.size(); ++i)
                add_variant(movers.at(i).at("renderEntity").get<unsigned>(), result.exit_rows[i]);
            if (constant("QC_SECRET_DOOR_COUNT"))
            {
                const auto& doors = meta.at("stockExitMachinery").at("secretDoors");
                for (std::size_t i = 0; i < doors.size(); ++i)
                    add_variant(doors.at(i).at("renderEntity").get<unsigned>(), result.exit_rows.at(movers.size() + i));
                if (constant("QC_ORD_DOOR_COUNT"))
                {
                    const auto& ordinary = meta.at("stockExitMachinery").at("ordinaryDoors");
                    for (std::size_t i = 0; i < ordinary.size(); ++i)
                        add_variant(ordinary.at(i).at("renderEntity").get<unsigned>(),
                                    result.exit_rows.at(movers.size() + doors.size() + i));
                }
            }
        }
    }
    if (intermission_phase == 2)
    {
        result.intermission_stats = {intermission_seconds, found_secrets, gw(secrets.size()),
                                     intermission_kills, intermission_monsters};
        result.weapon_frame = 0;
        return result;
    }
    if (axe_selected)
    {
        const auto& frames = assets().manifest.at("tables").at("weaponAxeFrames");
        result.weapon_frame = frames.at(std::min<std::size_t>(shot_clock, frames.size() - 1)).get<std::uint16_t>();
        return result;
    }
    if ((constant("QC_NAIL_COUNT") || constant("QC_CAMPAIGN_ITEMS")) && player("WEAPON") == 4 * 64)
    {
        result.weapon_frame = gw(constant("BSP_WEAPON_NAIL_IDLE") + nail_frame);
        return result;
    }
    result.weapon_frame = 1;
    if (shots && shots != shot_view)
    {
        if (consume_weapon)
            shot_view = shots;
        result.weapon_frame = 2;
    }
    else if (shots)
    {
        const auto& frames = assets().manifest.at("tables").at("weaponLiveFrames");
        result.weapon_frame = frames.at(std::min<std::size_t>(shot_clock, frames.size() - 1)).get<std::uint16_t>();
    }
    if (constant("QC_SSG_SOUND") && player("WEAPON") == 2 * 64)
        result.weapon_frame += gw(constant("BSP_WEAPON_SSG_IDLE") - 1);
    return result;
}

} // namespace quake_bsp_reference
