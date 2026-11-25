#include "gameplay_internal.hpp"
#include "gameplay_render.hpp"
#include "gameplay_script.hpp"
#include "gameplay_tape.hpp"
#include "aliases.hpp"

namespace quake_bsp_reference {

bool run_gameplay_self_test()
{
    auto put16 = [](std::vector<std::uint8_t>& data, std::size_t at, GameWord value) {
        data.at(at) = static_cast<std::uint8_t>(value);
        data.at(at + 1) = static_cast<std::uint8_t>(value >> 8);
    };
    auto require = [](bool valid, const char* what) {
        if (!valid)
            throw std::runtime_error(std::string("gameplay self-test: ") + what);
    };
    GameplayAssets assets;
    assets.map = "e1m3";
    assets.constants = {
        {"QC_BASIC_GAMEPLAY", 1},
        {"QC_EDICT_BYTES", 1536},
        {"QC_GRUNT", 1024},
        {"QC_GRUNT_DROP", 1024},
        {"QC_GRUNT_START_TIME", 128},
        {"QC_FIELD_HEALTH", 0},
        {"QC_FIELD_ORIGIN", 8},
        {"QC_FIELD_ABSMIN", 14},
        {"QC_FIELD_VELOCITY", 20},
        {"QC_FIELD_AMMO_SHELLS", 2},
        {"QC_FIELD_CURRENTAMMO", 4},
        {"QC_FIELD_ITEMS", 6},
        {"QC_FIELD_ATTACK_FINISHED", 26},
        {"QC_GLOBAL_SKILL", 0},
        {"QC_GLOBAL_TIME", 2},
        {"WALK_HULL_ROOT", 0},
        {"WALK_HULL_PLANES", 6},
        {"WALK_HULL_STACK_ENTRIES", 2},
        {"SHOT_HULL_ROOT", 0},
        {"SHOT_HULL_PLANES", 6},
        {"SHOT_HULL_STACK_ENTRIES", 2},
        {"WALK_DOOR_PLANE", 8192},
        {"WALK_BUTTON_PLANE", 8192}
    };
    assets.manifest = {
        {"map", "e1m3"},
        {"worldOrigin", {0, 0, 0}},
        {"spawnEyeQ4", {0, 0, 2}},
        {"spawnYaw", 0},
        {"metadata", {{"gameplay", {{"stockGrunts", Json::array()}}}}},
        {"tables", {{"cameraSinQ6", Json::array()}, {"cameraMoveSinQ4", Json::array()}, {"weaponLiveFrames", {1}}}}
    };
    for (unsigned i = 0; i < 320; ++i)
    {
        const auto sin = std::round(std::sin(double(i) * 2 * std::numbers::pi / 256) * 64);
        assets.manifest["tables"]["cameraSinQ6"].push_back(int(sin));
        assets.manifest["tables"]["cameraMoveSinQ4"].push_back(int(std::nearbyint(sin / 2)));
    }
    assets.payloads["QuakeBSPQuakeCGlobals.bin"] = std::vector<std::uint8_t>(8);
    auto& initial = assets.payloads["QuakeBSPQuakeCEdicts.bin"];
    initial.resize(1536);
    put16(initial, 512, 6400);
    auto& hull = assets.payloads["QuakeBSPWalkHull.bin"];
    hull.resize(16);
    put16(hull, 0, 0xa000);
    put16(hull, 2, 0xffff);
    put16(hull, 4, 0xfffe);
    auto& point_hull = assets.payloads["QuakeBSPShotHull.bin"];
    point_hull = hull;
    put16(point_hull, 10, gw(-24 * 8));
    put16(point_hull, 12, 0xffff);
    {
        auto source = assets, destination = assets;
        source.map = "e1m1";
        destination.map = "e1m2";
        destination.constants["QC_CAMPAIGN_ITEMS"] = 1;
        for (auto* map : {&source, &destination})
        {
            for (const auto& [field, offset] : std::array<std::pair<const char*, int>, 5>{{
                    {"AMMO_NAILS", 40}, {"AMMO_ROCKETS", 42}, {"AMMO_CELLS", 44},
                    {"ARMORVALUE", 46}, {"ARMORTYPE", 48}}})
                map->constants["QC_FIELD_" + std::string(field)] = offset;
            map->constants["QC_FIELD_WEAPON"] = 50;
        }
        GameplaySession campaign({source, destination}, "e1m1");
        auto& host = *campaign.impl_;
        for (const auto health : {0, 1, 49, 50, 99, 100, 125})
        for (const auto shells : {0, 24, 25, 57})
        for (const auto selection : {0, 1, 2, 4})
        {
            campaign.reset("e1m1", 0);
            host.field(512, "HEALTH") = gw(health*64);
            host.field(512, "ITEMS") = 0x5107;
            host.items_high = 0x7f;
            host.field(512, "ARMORTYPE") = 38;
            host.field(512, "ARMORVALUE") = 126*64;
            host.field(512, "AMMO_SHELLS") = gw(shells*64);
            host.field(512, "AMMO_NAILS") = 31*64;
            host.field(512, "AMMO_ROCKETS") = 9*64;
            host.field(512, "AMMO_CELLS") = 12*64;
            host.field(512, "WEAPON") = gw((selection ? selection : 1)*64);
            host.axe_selected = selection == 0;
            host.campaign_exit = host.switch_pending = true;
            host.pending_map = "e1m2";
            campaign.service_tick();
            const int ammo = !health ? 25 : selection == 4 ? 31 : selection ? std::max(25, shells) : 0;
            require(host.assets().map == "e1m2" && !host.skill_active &&
                    host.player("HEALTH") == (health ? std::clamp(health, 50, 100) : 100)*64 &&
                    host.player("ITEMS") == (health ? 0x5107 : 4097) && host.items_high == (health ? 1 : 0) &&
                    host.player("ARMORVALUE") == (health ? 126*64 : 0) && host.player("ARMORTYPE") == (health ? 38 : 0) &&
                    host.player("AMMO_SHELLS") == (health ? std::max(25, shells) : 25)*64 &&
                    host.player("AMMO_NAILS") == (health ? 31*64 : 0) && host.player("AMMO_CELLS") == (health ? 12*64 : 0) &&
                    host.player("AMMO_ROCKETS") == (health ? 9*64 : 0) && host.player("CURRENTAMMO") == ammo*64 &&
                    host.player("WEAPON") == (health && selection ? selection : 1)*64 &&
                    host.axe_selected == (!selection && health ? 1 : 0), "stock campaign changelevel parameters");
        }
        host.switch_pending = true;
        host.pending_map = "e1m2";
        campaign.service_tick();
        require(host.player("ARMORVALUE") == 0 && host.items_high == 0 &&
                host.player("AMMO_NAILS") == 0, "manual map requests reset the campaign loadout");
    }
    {
        GameplaySession movement({assets}, "e1m3");
        auto& host = *movement.impl_;
        host.walk.from = {0, 0, 2};
        host.walk.grounded = 1;
        for (const auto speed : {128, 230, 256})
            require(host.walk_run({256, 0, 0}) == GamePoint{gs(speed), 0, 0}, "ground acceleration");
        for (const auto speed : {205, 164, 131, 105, 84, 67, 51, 35, 19, 3, 0})
            require(host.walk_run({}) == GamePoint{gs(speed), 0, 0}, "ground friction and stop speed");
        host.walk.velocity_xy = {128, 0};
        auto& floor = host.maps[0].payloads["QuakeBSPShotHull.bin"];
        put16(floor, 4, 0xffff);
        require(host.walk_run({}) == GamePoint{77, 0, 0}, "double friction at a ledge");
        host.walk.grounded = 0;
        host.walk.velocity_xy = {256, 0};
        require(host.walk_run({}) == GamePoint{256, 0, 0}, "air retains momentum without input");
        require(host.walk_run({0, 256, 0}) == GamePoint{256, 24, 0}, "air accelerates sideways");
        require(host.walk_run({0, 256, 0}) == GamePoint{256, 24, 0}, "air caps only the projected speed");
    }
    {
        GameplaySession movement({assets}, "e1m3");
        auto& host = *movement.impl_;
        host.walk.from = {0, 0, 2};
        host.walk.grounded = 1;
        for (const auto speed : {80, 144, 160})
            require(host.walk_run({256, 0, 0}, 160) == GamePoint{gs(speed), 0, 0}, "walk acceleration");

        movement.use_queued_input(true);
        require(movement.always_run(), "always run defaults on");
        for (int tick = 0; tick < 3; ++tick)
            movement.video_tick({.joypad = 0x40});
        movement.video_tick({.joypad = 0x1000});
        movement.video_tick({.joypad = 0x800});
        movement.video_tick({});
        movement.video_tick({.joypad = 0x800});
        movement.video_tick({.joypad = 0x80});
        require(!movement.always_run(), "always run menu wraps up from Level and toggles off");
        movement.video_tick({.joypad = 0x1000});
        movement.video_tick({});
        movement.video_tick({.joypad = 0x40});
        movement.video_tick({.joypad = 0x40});
        require(host.input_clock.queue.size() == 4 && !host.input_clock.queue.front().second.walk_speed &&
                    host.input_clock.queue.back().second.walk_speed,
                "always run setting is retained by queued input");
        movement.reset("e1m3");
        require(!movement.always_run(), "always run survives a level reset");
    }
    {
        GameplaySession live({assets}, "e1m3");
        auto& host = *live.impl_;
        host.camera = {60, 40, 2};
        host.yaw = 48;
        host.field(512, "HEALTH") = 72 * 64;
        auto expected_state = live.state();
        const auto edicts = host.edicts;
        for (const std::uint8_t skill : std::array<std::uint8_t, 4>{3, 0, 2, 1})
        {
            live.set_skill(skill);
            expected_state["skillActive"] = skill;
            expected_state["skillSelected"] = skill;
            require(live.state() == expected_state && host.edicts == edicts && host.global("SKILL") == skill * 64,
                    "changing difficulty updates the live skill without resetting gameplay");
        }
    }
    for (const bool mouse : {false, true})
    {
        auto respawn_assets = assets;
        put16(respawn_assets.payloads["QuakeBSPQuakeCEdicts.bin"], 514, 25 * 64);
        GameplaySession respawn({respawn_assets}, "e1m3");
        auto& host = *respawn.impl_;
        GameplayInput fire;
        fire.joypad = mouse ? 0 : 0x20;
        fire.mouse_connected = mouse;
        fire.mouse_buttons = mouse ? 0x40 : 0;

        respawn.video_tick(fire);
        require(!host.restart_pending && !host.respawn_armed, "fire while alive never requests respawn");
        host.field(512, "HEALTH") = mouse ? gw(-1) : 0;
        host.field(512, "AMMO_SHELLS") = 0;
        host.skill_selected = 2;
        host.camera = {60, 40, 2};
        host.yaw = 48;
        host.damage_flash = 4;
        respawn.video_tick(fire);
        require(!host.restart_pending && !host.respawn_armed, "fire held through death cannot respawn");
        respawn.video_tick({});
        require(host.respawn_armed && !host.restart_pending, "a released fire sample arms respawn");
        respawn.video_tick(fire);
        require(host.restart_pending && host.release_gate && !host.damage_flash &&
                    host.camera == GamePoint{0, 0, 2} && host.yaw == 0,
                "new fire queues a reset to the same spawn and clears the damage flash");
        require(!respawn.service_tick() && host.assets().map == "e1m3" && host.skill_active == 2 &&
                    host.player("HEALTH") == 100 * 64 && host.player("AMMO_SHELLS") == 25 * 64 &&
                    host.release_gate && !host.respawn_armed,
                "normal restart restores the selected skill and the initial player state");
        respawn.video_tick(fire);
        require(host.release_gate && !host.restart_pending, "respawn fire stays gated until release");
        respawn.video_tick({});
        require(!host.release_gate, "input resumes after the respawn trigger is released");
    }
    {
        GameplaySession respawn({assets}, "e1m3");
        respawn.use_queued_input(true);
        auto& host = *respawn.impl_;
        host.field(512, "HEALTH") = 0;
        for (const auto input : {GameplayInput{}, GameplayInput{0x20}, GameplayInput{0x40}, GameplayInput{}})
            for (unsigned i = 0; i < 3; ++i)
                respawn.video_tick(input);
        require(!host.restart_pending, "latched fire cannot restart before its logical step");
        require(respawn.service_tick() && host.respawn_armed && !host.restart_pending,
                "consumed neutral input arms respawn");
        require(respawn.service_tick() && host.restart_pending && host.last == 2,
                "consumed fire requests respawn at its own step");
        auto phase = respawn.begin_service();
        require(phase == "service.begin", "respawn service publishes its first checkpoint after map reset");
        while (phase != "service.end" && phase != "done")
            phase = respawn.resume_service();
        require(phase == "service.end" && respawn.resume_service() == "done" &&
                    host.last == 3 && host.player("HEALTH") == 6400 &&
                    host.camera == GamePoint{0, 0, 2} && host.input_clock.respawn_release,
                "restart preserves the input clock and gates the next held input");
        require(respawn.service_tick() && host.last == 4 && !host.input_clock.respawn_release &&
                    !respawn.service_tick(),
                "queued release is consumed once after respawn");
    }
    GameplaySession session({assets}, "e1m3");
    auto& engine = *session.impl_;
    const auto floor = engine.trace({0, 0, 32}, {0, 0, -32});
    require(
        floor.hit && floor.fraction == 2048 && floor.result == GamePoint{0, 0, 2} &&
            floor.normal == GamePoint{0, 0, 16384},
        "axial floor skin/fraction"
    );
    auto& test_hull = engine.maps[0].payloads["QuakeBSPWalkHull.bin"];
    put16(test_hull, 0, 0);
    put16(test_hull, 6, 11585);
    put16(test_hull, 8, 11585);
    const auto oblique = engine.trace({16, 16, 0}, {-16, -16, 0});
    require(
        oblique.hit && oblique.fraction == 2048 && oblique.result == GamePoint{2, 2, 0} &&
            oblique.normal == GamePoint{11585, 11585, 0},
        "oblique plane skin"
    );
    put16(test_hull, 0, 0xc000);
    put16(test_hull, 6, 9459);
    put16(test_hull, 8, 9459);
    put16(test_hull, 14, 9459);
    engine.maps[0].constants["WALK_HULL_THIRD_COEFFICIENTS"] = 14;
    const auto three_axis = engine.trace({16, 16, 16}, {-16, -16, -16});
    require(
        three_axis.hit && three_axis.result == GamePoint{2, 2, 2} && three_axis.normal == GamePoint{9459, 9459, 9459},
        "three-axis plane"
    );
    require(
        game_q6_mul(gw(-1), 32) == gw(-1) && game_q6_mul(1, 32) == 1 && game_asr(-1, 4) == -1 && gs(32768) == -32768,
        "rounding and wrap domains"
    );
    require(game_q6_mul(32768, 1) == 512, "native signed wide multiply absolute-value edge");
    engine.globals.resize(32);
    engine.maps[0].payloads["QuakeBSPQuakeCFunctions.bin"].resize(16);
    auto& code = engine.maps[0].payloads["QuakeBSPQuakeCCode.bin"];
    code.resize(16);
    put16(code, 0, 2);
    put16(code, 2, 8);
    put16(code, 4, 10);
    put16(code, 6, 12);
    put16(code, 8, 86);
    put16(code, 10, 12);
    engine.g(8) = gw(-1);
    engine.g(10) = 32;
    engine.budget = 16;
    engine.invoke(0);
    require(engine.g(2) == gw(-1) && engine.statements == 2, "packed Q6 multiply and return VM instructions");
    {
        auto length_assets = assets;
        length_assets.constants["QC_GRUNT_DROP"] = 1536;
        GameplaySession lengths({length_assets}, "e1m3");
        auto& pusher = *lengths.impl_;
        pusher.globals.resize(32);
        pusher.global("SELF") = 512;
        const auto edicts_before = pusher.edicts;
        pusher.g(8) = pusher.g(10) = pusher.g(12) = 0;
        pusher.builtin(-12);
        require(pusher.g(2) == 0, "zero pusher vector has zero length");
        for (unsigned axis = 0; axis < 3; ++axis)
            for (const auto value : {-32768, -6144, -6016, -1, 1, 6016, 6144, 32767})
            {
                pusher.g(8) = pusher.g(10) = pusher.g(12) = 0;
                pusher.g(8 + axis * 2) = gw(value);
                pusher.g(4) = 0x1234;
                pusher.g(6) = 0x5678;
                const auto inputs = std::array{pusher.g(8), pusher.g(10), pusher.g(12)};
                pusher.builtin(-12);
                require(pusher.g(2) == gw(std::abs(value)), "signed axial X/Y/Z pusher length");
                require(
                    std::array{pusher.g(8), pusher.g(10), pusher.g(12)} == inputs && pusher.g(4) == 0x1234 &&
                        pusher.g(6) == 0x5678 && pusher.edicts == edicts_before,
                    "pusher length preserves its input vector, other returns and every edict"
                );
            }
        for (const auto& vector :
             std::array{std::array{64, -64, 0}, std::array{-64, 0, 64}, std::array{0, 64, -64}, std::array{64, 64, 64}})
        {
            for (unsigned axis = 0; axis < 3; ++axis)
                pusher.g(8 + axis * 2) = gw(vector[axis]);
            pusher.g(2) = 0x4321;
            const auto globals_before = pusher.globals;
            bool rejected = false;
            try
            {
                pusher.builtin(-12);
            }
            catch (const std::runtime_error&)
            {
                rejected = true;
            }
            require(
                rejected && pusher.globals == globals_before && pusher.edicts == edicts_before,
                "diagonal pusher length still rejects without state mutation"
            );
        }
        pusher.global("SELF") = gw(length_assets.constants.at("QC_GRUNT"));
        pusher.g(8) = 192;
        pusher.g(10) = 256;
        pusher.g(12) = 0;
        pusher.builtin(-12);
        require(pusher.g(2) == 320, "grunt diagonal vector length retains the full vector math path");
    }
    engine.maps[0] = assets;
    {
        session.reset("e1m3");
        bool rejected_peak = false;
        try
        {
            (void)run_gameplay_script(session, {
                {"schema", "quake-gameplay-script-v1"},
                {"steps", Json::array({Json{{"op", "snapshot"}, {"label", "spurious-peak"}, {"capture", false},
                                             {"observePickupPeak", true}}})}
            });
        }
        catch (const std::exception& error)
        {
            rejected_peak = std::string_view(error.what()).find("no independent gameplay pickup") != std::string_view::npos;
        }
        require(rejected_peak, "a palette producer observation must follow a C++ gameplay pickup");
        const auto report = run_gameplay_script(session, {
            {"schema", "quake-gameplay-script-v1"}, {"initialRenderScale", 3}, {"initialRenderTechnique", 4},
            {"steps", Json::array({Json{{"op", "snapshot"}, {"label", "cold-x3"}, {"capture", false}}})}
        });
        const auto& snapshot = report.at("states").at(0).at("renderSnapshot");
        require(snapshot.at("renderScale") == 3 && snapshot.at("technique") == 4,
                "cold native X3 Full selection reaches the independently replayed snapshot");
    }
    session.reset("e1m3");
    engine.contact = 7;
    engine.walk_tick();
    require(engine.contact == 7, "walk preserves pending QuakeC contact");
    session.reset("e1m3");
    session.step(GameplayInput{0x40});
    auto state = session.state();
    require(
        state["cameraQ4"][0] == 0 && state["pendingQ4"][0] == 32 && state["pending"] == true,
        "walk delayed publication"
    );
    session.video_tick(GameplayInput{});
    state = session.state();
    require(state["cameraQ4"][0] == 32 && !state["pending"].get<bool>(), "NMI publication");
    session.service_tick();
    session.video_tick(GameplayInput{0x10});
    session.service_tick();
    state = session.state();
    require(state["walk"]["velocityZ"] == 1095 && state["walk"]["grounded"] == 0, "jump impulse then gravity");
    require(!session.service_tick(), "one service per outstanding tick");
    session.reset("e1m3");
    engine.menu({}, 0x1000);
    engine.menu_selection = 4;
    engine.menu({}, 0x100);
    require(engine.scale == 2 && engine.menu_scale == 1, "scale draft waits for close");
    require(
        session.render_snapshot().render_scale == 2 &&
            gameplay_snapshot_json(session.render_snapshot()).at("renderScale") == 2,
        "uncommitted X3 menu draft leaves the independent render snapshot at X2"
    );
    engine.menu({}, 0x8000);
    require(engine.scale == 3, "X3 committed on menu close");
    const auto x3_snapshot = session.render_snapshot();
    require(
        x3_snapshot.render_scale == 3 && gameplay_snapshot_json(x3_snapshot).at("renderScale") == 3,
        "committed X3 reaches the immutable snapshot and capture JSON"
    );
    engine.menu({}, 0x1000);
    engine.menu_selection = 4;
    engine.menu({}, 0x100);
    engine.menu({}, 0x8000);
    require(engine.scale == 2, "Scale selection wraps to X2");
    engine.menu({}, 0x1000);
    engine.menu_selection = 3;
    engine.menu({}, 0x100);
    require(engine.entities_enabled && !engine.draft_entities, "entities draft waits for close");
    engine.menu({}, 0x8000);
    require(!engine.entities_enabled, "entities commit on close");
    session.reset("e1m3");
    const auto fixture_before = session.state();
    session.set_initial_pose({12, -34, 56}, 123, -12);
    const auto fixture_after = session.state();
    require(
        fixture_after["cameraQ4"] == Json::array({12, -34, 56}) && fixture_after["yaw"] == 123 &&
            fixture_after["pitch"] == -12,
        "initial qualification pose applies native coordinates"
    );
    require(
        fixture_after["player"] == fixture_before["player"] && fixture_after["quakec"] == fixture_before["quakec"] &&
            fixture_after["shotgun"] == fixture_before["shotgun"],
        "initial pose preserves independent game state"
    );
    bool repeat_rejected = false;
    try
    {
        session.set_initial_pose({0, 0, 0}, 0, 0);
    }
    catch (const std::runtime_error&)
    {
        repeat_rejected = true;
    }
    require(repeat_rejected, "initial pose is one-use until reset");
    session.reset("e1m3");
    session.video_tick({});
    bool late_rejected = false;
    try
    {
        session.set_initial_pose({0, 0, 0}, 0, 0);
    }
    catch (const std::runtime_error&)
    {
        late_rejected = true;
    }
    require(late_rejected, "initial pose rejects after an NMI");
    const auto parsed = gameplay_input_from_json(
        {{"joypad", 65535}, {"mouseDx", -127}, {"mouseDy", 127}, {"mouseButtons", 255}, {"mouseConnected", true}}
    );
    require(
        parsed.joypad == 65535 && parsed.mouse_dx == -127 && parsed.mouse_dy == 127 && parsed.mouse_buttons == 255 &&
            parsed.mouse_connected,
        "strict input accepts native integer endpoints"
    );
    const std::vector<Json> invalid_inputs{
        Json{{"joypad", true}},
        Json{{"joypad", 1.5}},
        Json{{"mouseDx", false}},
        Json{{"mouseDy", -0.5}},
        Json{{"mouseButtons", 4.0}},
        Json{{"mouseDx", "1"}},
        Json{{"mouseDx", std::numeric_limits<std::uint64_t>::max()}},
        Json{{"mouseConnected", 1}},
        Json{{"mouseConnected", "true"}},
        Json{{"mouseDz", 0}},
        Json{{"joypad", -1}},
        Json{{"mouseDy", 128}},
        Json{{"mouseButtons", 256}}
    };
    for (const auto& invalid : invalid_inputs)
    {
        bool rejected = false;
        try
        {
            (void)gameplay_input_from_json(invalid);
        }
        catch (const std::exception&)
        {
            rejected = true;
        }
        require(rejected, "strict input rejects coercion, out-of-range, and unknown fields");
    }
    // Gameplay retains Q6 quantization, with the original Quake handedness.
    engine.maps[0] = assets;
    engine.maps[0].manifest["worldOrigin"] = {17, -31, 43};
    session.reset("e1m3");
    SourceWorld basis_world;
    basis_world.origin = {17, -31, 43};
    const auto same_vector = [](const Vec3& a, const Vec3& b) { return length_squared(a - b) < 1e-24; };
    for (unsigned native_yaw = 0; native_yaw < 256; ++native_yaw)
        for (const int native_pitch : {-64, -31, 0, 17, 64})
        {
            engine.camera = {1234, -2345, 3456};
            engine.yaw = gw(native_yaw);
            engine.pitch = gw(native_pitch);
            const auto snapshot = session.render_snapshot();
            require(snapshot.source_camera.capture_basis.has_value(), "native camera basis is retained");
            auto expected = packed_view_transform(basis_world, snapshot.native_camera);
            expected.screen_right = expected.screen_right * -1.0;
            const auto actual = source_view_transform(snapshot.source_camera);
            require(
                same_vector(actual.origin, expected.origin) && same_vector(actual.forward, expected.forward) &&
                    same_vector(actual.screen_right, expected.screen_right) && same_vector(actual.up, expected.up),
                "gameplay preserves native quantization with Quake screen-right"
            );
            auto quake_camera = snapshot.source_camera;
            quake_camera.capture_basis.reset();
            const auto quake = source_view_transform(quake_camera);
            require(
                dot(actual.screen_right, quake.screen_right) > 0.98,
                "gameplay screen-right agrees with original Quake AngleVectors"
            );
        }
    // The asymmetric source scene detects a mirror in actual frame ownership and texels.
    engine.maps[0] = assets;
    session.reset("e1m3");
    engine.camera = {0, 0, 0};
    SourceWorld capture_world;
    capture_world.face_count = 1;
    capture_world.colors = {{2, 0x32}};
    capture_world.visibility_planes = {{{-1, 0, 0}, -16}};
    capture_world.face_texture_infos = {0};
    capture_world.face_lightmaps.resize(1);
    capture_world.live_base_colors = {0};
    capture_world.centroids = {{1, 0, 0}};
    capture_world.texture_infos = {{{0, 1, 0}, 0, {0, 0, 1}, 0, 0}};
    capture_world.textures = {{"wall", 64, 64, std::vector<std::uint8_t>(4096), true}};
    for (std::size_t pixel = 0; pixel < 4096; ++pixel)
        capture_world.textures[0].level_zero[pixel] = static_cast<std::uint8_t>(1 + pixel % 251);
    for (auto& row : capture_world.texture_colormap)
        for (std::size_t index = 0; index < row.size(); ++index)
            row[index] = static_cast<std::uint8_t>(index);
    const auto triangle = [](Vec3 a, Vec3 b, Vec3 c) {
        Triangle result;
        result.first = a;
        result.second = b;
        result.third = c;
        result.centroid = (a + b + c) * (1.0 / 3.0);
        result.bounds.include(a);
        result.bounds.include(b);
        result.bounds.include(c);
        result.color = {2, 0x32};
        return result;
    };
    capture_world.triangles = {
        triangle({16, -24, -12}, {16, -4, -12}, {16, -4, 12}),
        triangle({16, -24, -12}, {16, -4, 12}, {16, -24, 12})
    };
    const Bvh capture_bvh(capture_world.triangles);
    const auto capture = session.render_snapshot();
    const auto source_frame = render_source_reference(capture_world, capture_bvh, capture.source_camera, false);
    auto quake_camera = capture.source_camera;
    quake_camera.capture_basis.reset();
    const auto quake_frame = render_source_reference(capture_world, capture_bvh, quake_camera, false);
    require(
        quake_frame.hits > 0 && source_frame.faces == quake_frame.faces && source_frame.depths == quake_frame.depths &&
            source_frame.texture_indices == quake_frame.texture_indices &&
            source_frame.lightmap_texture_indices == quake_frame.lightmap_texture_indices,
        "gameplay matches original Quake ownership/depth/texels in an asymmetric scene"
    );
    unsigned left_hits = 0, right_hits = 0;
    for (int y = 0; y < kLogicalHeight; ++y)
        for (int x = 0; x < kLogicalWidth; ++x)
            if (source_frame.faces[logical_pixel_index(x, y)] != kMissFace)
                (x < kLogicalWidth / 2 ? left_hits : right_hits)++;
    require(
        left_hits == 0 && right_hits > 0,
        "the negative-Y wall appears on screen-right when looking along positive X"
    );
    GameplaySession atomic({assets}, "e1m3"), resumed({assets}, "e1m3");
    atomic.step(GameplayInput{0x40});
    resumed.video_tick(GameplayInput{0x40});
    require(resumed.begin_service() == "service.begin", "continuation starts before walk");
    require(
        resumed.service_tick() && resumed.state() == atomic.state(),
        "drained continuation equals synchronous service"
    );
    resumed.reset("e1m3");
    resumed.video_tick(GameplayInput{0x40});
    resumed.begin_service();
    while (resumed.resume_service() != "done")
    {
    }
    require(!resumed.service_tick(), "completed continuation does not count a service twice");
    resumed.step(GameplayInput{0x40});
    atomic.step(GameplayInput{0x40});
    require(resumed.state() == atomic.state(), "ordinary stepping consumes the next video tick");
    {
        GameplaySession immediate({assets}, "e1m3"), delayed({assets}, "e1m3");
        immediate.use_queued_input(true);
        delayed.use_queued_input(true);
        constexpr std::array<GameplayInput, 6> tape{{{0x40}, {0x40}, {0x200}, {0x200}, {0x40}, {}}};
        for (const auto& input : tape)
            for (unsigned i = 0; i < 3; ++i)
                delayed.video_tick(input);
        for (const auto& input : tape)
        {
            immediate.step(input, 3);
            require(delayed.service_tick(), "every admitted controller sample runs once");
            for (const auto* field : {"lastTick", "cameraQ4", "pendingQ4", "yaw", "pitch", "walk", "quakec"})
                require(immediate.state().at(field) == delayed.state().at(field), "queued simulation ignores video lag");
        }
        require(!delayed.service_tick() && immediate.state() == delayed.state(), "queued input drains in order");
    }
    {
        for (const bool knight_map : {false, true})
        {
            GameplaySession queued({assets}, "e1m3");
            auto& host = *queued.impl_;
            if (knight_map)
            {
                host.maps.front().constants["QC_KNIGHT_ROSTER"] = 1;
                host.maps.front().constants["QC_E1M2_GROUP_COUNT"] = 6;
            }
            const unsigned capacity = knight_map ? 1023 : 255;
            for (unsigned sample = 0; sample <= capacity; ++sample)
                for (unsigned tick = 0; tick < host.input_vblanks; ++tick)
                    host.latch_input({.buttons = sample % 2 ? GameWord{0x40} : GameWord{0x80}});
            require(host.input_clock.tick == capacity && host.input_clock.waits == 1 &&
                        host.input_clock.queue.size() == capacity,
                    "reference replay matches the cartridge input capacity");
        }
    }
    {
        GameplaySession queued({assets}, "e1m3");
        auto& host = *queued.impl_;
        host.maps.front().constants["QC_INPUT_REPLAY_CELL_BYTES"] = 4;
        for (unsigned tick = 0; tick < 510U * host.input_vblanks; ++tick)
            host.latch_input({.buttons = tick / host.input_vblanks % 2 ? GameWord{0x40} : GameWord{0x80}});
        for (unsigned tick = 0; tick < host.input_vblanks; ++tick)
            host.latch_input({.yaw_delta = 12, .pitch_delta = -8});
        require(host.input_clock.tick == 510 && host.input_clock.waits == 1 && host.input_clock.used_queue_cells == 510,
                "a look record cannot consume the compact ring's reserved last cell");
        host.last = 1;
        host.consume_input();
        host.latch_input({});
        require(host.input_clock.tick == 511 && host.input_clock.used_queue_cells == 511 &&
                    host.input_clock.queue.back().second.yaw_delta == 36 &&
                    host.input_clock.queue.back().second.pitch_delta == -24,
                "one consumed button record admits both cells of the original pending look");
    }
    {
        GameplayTape recording;
        recording.map = "e1m3";
        recording.skill = 2;
        recording.always_run = false;
        const std::array<GameplayInput, 6> inputs{{
            {0x40}, {0x40}, {0x40, 9, -6, 0x40, true, true}, {0x40, 0, 0, 0x40, true}, {}, {}
        }};
        GameplaySession live({assets}, recording.map), replay({assets}, recording.map);
        live.reset(recording.map, recording.skill);
        live.set_always_run(recording.always_run);
        live.use_queued_input(true);
        for (const auto& input : inputs)
        {
            live.step(input);
            recording.append(input);
        }
        const auto tape = parse_gameplay_tape(gameplay_tape_json(recording));
        require(tape.ticks == inputs.size() && tape.holds.size() == 4 && tape.holds[1].input == inputs[2],
                "recorded holds retain mouse and weapon input while compressing identical ticks");
        replay.reset(tape.map, tape.skill);
        replay.set_always_run(tape.always_run);
        replay.use_queued_input(true);
        for (const auto& hold : tape.holds)
            replay.step(hold.input, hold.ticks);
        require(live.state() == replay.state(), "a serialized tape reproduces live gameplay state");
        const auto legacy = parse_gameplay_tape(Json::parse(R"([{"clock":"video","ticks":3,"buttons":["Y","R"]}])"), "e1m3");
        require(legacy.skill == 1 && legacy.always_run && legacy.ticks == 3 && legacy.holds[0].input.joypad == 0x4010,
                "legacy benchmark tapes keep their start settings and controller mapping");
    }
    resumed.reset("e1m3");
    resumed.video_tick(GameplayInput{0x40});
    resumed.begin_service();
    auto advance_to = [&](std::string_view phase) {
        for (unsigned count = 0; count < 64; ++count)
        {
            if (resumed.service_phase() == phase)
                return;
            require(resumed.resume_service() != "done", "continuation reaches requested phase");
        }
        require(false, "continuation phase limit");
    };
    advance_to("walk.input");
    resumed.video_tick(GameplayInput{0x8000});
    advance_to("walk.publish");
    require(
        !resumed.state()["pending"].get<bool>() && resumed.state()["cameraQ4"][0] == 0,
        "in-flight walk cannot publish during hull arithmetic"
    );
    advance_to("walk.clear");
    resumed.video_tick({});
    require(
        !resumed.state()["pending"].get<bool>() && resumed.state()["cameraQ4"][0] == 0,
        "NMI cannot publish an incomplete pending copy"
    );
    advance_to("walk.readyBefore");
    resumed.video_tick({});
    require(
        !resumed.state()["pending"].get<bool>() && resumed.state()["cameraQ4"][0] == 0,
        "NMI cannot publish before the ready store"
    );
    advance_to("walk.end");
    require(resumed.state()["pendingQ4"][0] == 32, "walk retains the pre-NMI input latch");
    resumed.video_tick({});
    require(
        resumed.state()["cameraQ4"][0] == 32 && !resumed.state()["pending"].get<bool>(),
        "NMI publishes only the completed walk pose"
    );
    require(resumed.service_tick(), "normal service API drains suspended work");
    {
        const RenderViewportScope viewport(RenderScale::X2);
        SourceWorld depth_world;
        const Camera camera{0, 0, 0, 16, 0};
        auto view = packed_view_transform(depth_world, camera);
        view.screen_right = view.screen_right * -1.0; // Physical Quake handedness.
        require(kSinTable[16] == 24 && kCosTable[16] == 59, "nonunit native Q6 fixture basis");
        // A wall perpendicular to forward at ray t=100 has native Z
        // round(100*(59*59+24*24)/1024)=396, not round(t*4)=400.
        std::vector<double> ray_depth(kLogicalPixels, 100.0);
        ray_depth.back() = std::numeric_limits<double>::infinity();
        ray_depth.front() = 0;
        const auto native_depth = gameplay_packed_opaque_depth(ray_depth, view);
        require(
            native_depth.at(logical_pixel_index(64, 56)) == 396 && native_depth.front() == 0 &&
                native_depth.back() == std::numeric_limits<std::int16_t>::max(),
            "ray t converts to native forward depth and preserves sentinels"
        );
        AliasAssets aliases;
        AliasSprite sprite;
        sprite.width = sprite.height = 1;
        sprite.pixels = {7};
        aliases.sprites.push_back(sprite);
        AliasRow row;
        row.dynamic_states.push_back({0, {22, 12, 0}, 0, 0});
        row.tokens.push_back({false, 0, 0, 0});
        aliases.rows.push_back(row);
        const auto projected = ordered_packed_alias_views(camera, aliases, 0);
        require(
            projected.size() == 1 && projected[0].depth_q6 == 397,
            "fixture actor lies behind the nonunit-basis wall"
        );
        const std::vector<std::uint8_t> opaque(kLogicalPixels, 3);
        AliasCoverage coverage;
        const auto composed =
            compose_post_opaque_alias_indices(opaque, native_depth, camera, aliases, 0, RenderMode{}, &coverage);
        require(
            coverage.packed_plot_pixels > 0 && coverage.packed_visible_pixels == 0 && composed == opaque,
            "native billboard cannot leak through a nearer nonunit-Q6 wall"
        );
    }
    {
        auto camera_assets = assets;
        camera_assets.manifest["worldOrigin"] = {17, -31, 43};
        GameplaySession inspection({camera_assets}, "e1m3");
        inspection.video_tick(GameplayInput{0x40});
        inspection.service_tick();
        const auto physics_before = inspection.state();
        require(physics_before["pending"] == true, "render override fixture retains an unpublished walk pose");
        const auto snapshot_before = gameplay_snapshot_json(inspection.render_snapshot());
        const Json requested{{"eyeQ4", {-1, -257, 32767}}, {"yaw", 16}, {"pitch", -17}};
        const Json script{
            {"schema", "quake-gameplay-script-v1"},
            {"steps", Json::array({Json{{"op", "snapshot"}, {"label", "render-view"}, {"renderCamera", requested}}})}
        };
        Json captured;
        unsigned captures = 0;
        const auto report = run_gameplay_script(
            inspection,
            script,
            [&](const GameplayRenderSnapshot& snapshot, std::size_t index, std::string_view label) {
                require(index == 0 && label == "render-view", "render override capture identity");
                captured = gameplay_snapshot_json(snapshot);
                ++captures;
                return Json{{"rendered", true}};
            }
        );
        require(
            captures == 1 && inspection.state() == physics_before,
            "render camera preserves full gameplay state, RNG, clocks and pending pose"
        );
        require(
            captured["eyeQ4"] == requested["eyeQ4"] &&
                captured["nativeCamera"] == Json::array({-1, -2, 127, 16, 239}) &&
                captured["sourceCamera"]["origin"] == Json::array({1.0, -63.0, 2075.0}),
            "render camera retains signed-byte quantization and map origin"
        );
        require(
            captured["sourceCamera"]["captureBasis"][1] == Json::array({24.0 / 64.0, -59.0 / 64.0, 0.0}),
            "render camera keeps Quake screen-right with native Q6 coefficients"
        );
        auto original_non_camera = snapshot_before, rendered_non_camera = captured;
        for (const auto* field : {"eyeQ4", "nativeCamera", "nativeCameraQ2", "sourceCamera"})
        {
            original_non_camera.erase(field);
            rendered_non_camera.erase(field);
        }
        require(original_non_camera == rendered_non_camera, "render override changes only snapshot camera fields");
        const auto& override_info = report.at("states").at(0).at("renderCameraOverride");
        require(
            override_info.at("request") == requested && override_info.at("physicsStateUnchanged") == true &&
                override_info.at("originalNativeCamera") == snapshot_before.at("nativeCamera"),
            "render override is explicit and retains its original physics camera"
        );
        require(
            gameplay_snapshot_json(inspection.render_snapshot()) == snapshot_before,
            "render camera override is one snapshot and cannot persist into the session"
        );
        const std::vector<Json> invalid_cameras{
            Json(nullptr),
            Json::array(),
            Json{{"eyeQ4", {0, 0}}, {"yaw", 0}, {"pitch", 0}},
            Json{{"eyeQ4", {false, 0, 0}}, {"yaw", 0}, {"pitch", 0}},
            Json{{"eyeQ4", {0.5, 0, 0}}, {"yaw", 0}, {"pitch", 0}},
            Json{{"eyeQ4", {-32769, 0, 0}}, {"yaw", 0}, {"pitch", 0}},
            Json{{"eyeQ4", {32768, 0, 0}}, {"yaw", 0}, {"pitch", 0}},
            Json{{"eyeQ4", {0, 0, 0}}, {"yaw", true}, {"pitch", 0}},
            Json{{"eyeQ4", {0, 0, 0}}, {"yaw", 0.0}, {"pitch", 0}},
            Json{{"eyeQ4", {0, 0, 0}}, {"yaw", -1}, {"pitch", 0}},
            Json{{"eyeQ4", {0, 0, 0}}, {"yaw", 256}, {"pitch", 0}},
            Json{{"eyeQ4", {0, 0, 0}}, {"yaw", std::numeric_limits<std::uint64_t>::max()}, {"pitch", 0}},
            Json{{"eyeQ4", {0, 0, 0}}, {"yaw", 0}, {"pitch", -65}},
            Json{{"eyeQ4", {0, 0, 0}}, {"yaw", 0}, {"pitch", 65}},
            Json{{"eyeQ4", {0, 0, 0}}, {"yaw", 0}, {"pitch", "0"}},
            Json{{"eyeQ4", {0, 0, 0}}, {"pitch", 0}},
            Json{{"eyeQ4", {0, 0, 0}}, {"yaw", 0}, {"pitch", 0}, {"frame", 17}}
        };
        const auto reject = [&](const Json& step) {
            bool rejected = false;
            try
            {
                (void)run_gameplay_script(
                    inspection,
                    Json{{"schema", "quake-gameplay-script-v1"}, {"steps", Json::array({step})}}
                );
            }
            catch (const std::exception&)
            {
                rejected = true;
            }
            require(
                rejected && inspection.state() == physics_before,
                "invalid render camera rejects before any gameplay mutation"
            );
        };
        for (const auto& invalid : invalid_cameras)
            reject(Json{{"op", "snapshot"}, {"renderCamera", invalid}});
        for (const auto* op : {"video", "step", "service", "servicePhase", "reset", "fixture"})
            reject(Json{{"op", op}, {"renderCamera", requested}});
        for (const auto pitch : {-64, 64})
        {
            const auto endpoints = run_gameplay_script(
                inspection,
                Json{
                    {"schema", "quake-gameplay-script-v1"},
                    {"steps",
                     Json::array({Json{
                         {"op", "snapshot"},
                         {"renderCamera", {{"eyeQ4", {-32768, 32767, 0}}, {"yaw", 255}, {"pitch", pitch}}}
                     }})}
                }
            );
            require(
                endpoints.at("states").at(0).at("renderSnapshot").at("nativeCamera") ==
                        Json::array({-128, 127, 0, 255, pitch & 255}) &&
                    inspection.state() == physics_before,
                "render camera accepts native integer endpoints without gameplay changes"
            );
        }
    }

    {
        GameplaySession inspection({assets}, "e1m3");
        inspection.impl_->shots = 1;
        const Json steps = Json::array({
            Json{{"op", "snapshot"}, {"label", "frozen"}, {"observeWorld", true}, {"capture", false}},
            Json{{"op", "video"}, {"label", "later"}},
            Json{{"op", "snapshot"}, {"label", "composite"}, {"worldSnapshot", "frozen"}, {"capture", true}},
            Json{{"op", "snapshot"}, {"label", "settled"}, {"capture", false}}
        });
        const auto report = run_gameplay_script(
            inspection,
            Json{{"schema", "quake-gameplay-script-v1"}, {"steps", steps}},
            [&require](const GameplayRenderSnapshot& snapshot, std::size_t, std::string_view label) {
                require(label == "composite", "only the selected two-phase frame is rendered");
                return gameplay_snapshot_json(snapshot);
            }
        );
        const auto& rows = report.at("states");
        const auto& composite = rows.at(2);
        require(
            composite.at("composedFrom") == "frozen" &&
                composite.at("capture").at("videoTick") == rows.at(0).at("renderSnapshot").at("videoTick") &&
                composite.at("capture").at("videoTick") != composite.at("renderSnapshot").at("videoTick"),
            "two-phase replay composites the earlier frozen world"
        );
        require(
            composite.at("capture").at("weaponFrame") == 2 &&
                composite.at("renderSnapshot").at("weaponFrame") == 2 &&
                rows.at(3).at("renderSnapshot").at("weaponFrame") == 1,
            "world observation preserves the first late muzzle frame"
        );
    }

    {
        GameplaySession inspection({assets}, "e1m3");
        inspection.video_tick(GameplayInput{0x40});
        inspection.service_tick();
        auto& test_impl = *inspection.impl_;
        auto& render_assets = test_impl.maps[0];
        Json pose_rows = Json::array({0});
        for (unsigned row = 51; row <= 66; ++row)
            pose_rows.push_back(row);
        render_assets.manifest["metadata"]["gameplay"]["stockEntranceDoors"] = Json::array(
            {Json{{"renderEntity", 15}, {"poseRows", pose_rows}}, Json{{"renderEntity", 16}, {"poseRows", pose_rows}}}
        );
        render_assets.manifest["brushRows"] = Json::array();
        for (unsigned row = 0; row < 67; ++row)
            render_assets.manifest["brushRows"].push_back(Json::array());
        render_assets.constants["QC_ENTRANCE_COUNT"] = 2;
        test_impl.entrance_pose = {4, 3};
        const auto physics_before = inspection.state();
        const auto edicts_before = test_impl.edicts, globals_before = test_impl.globals;
        const auto original_snapshot = gameplay_snapshot_json(inspection.render_snapshot());
        require(physics_before.at("pending") == true, "entrance override retains an unpublished walk pose");
        require(
            original_snapshot.at("entranceRows") == Json::array({54, 53}),
            "live entrance snapshot uses current poses"
        );
        const auto override_script = [](const Json& poses) {
            return Json{
                {"schema", "quake-gameplay-script-v1"},
                {"steps",
                 Json::array({Json{{"op", "snapshot"}, {"renderEntrancePoses", poses}, {"renderEntities", false}}})}
            };
        };
        for (const auto& requested :
             {Json::array({0, 0}), Json::array({8, 9}), Json::array({16, 16}), Json::array({0, 16})})
        {
            Json captured;
            unsigned captures = 0;
            const auto report = run_gameplay_script(
                inspection,
                override_script(requested),
                [&](const GameplayRenderSnapshot& snapshot, std::size_t, std::string_view) {
                    captured = gameplay_snapshot_json(snapshot);
                    ++captures;
                    return Json{{"rendered", true}};
                }
            );
            const Json expected = Json::array(
                {pose_rows.at(requested.at(0).get<unsigned>()), pose_rows.at(requested.at(1).get<unsigned>())}
            );
            require(
                captures == 1 && captured.at("entranceRows") == expected,
                "entrance render-only override independently maps both authored pose rows"
            );
            auto restored = captured;
            restored["entranceRows"] = original_snapshot.at("entranceRows");
            require(captured.at("entitiesEnabled") == false, "render-only entity toggle suppresses billboards");
            restored["entitiesEnabled"] = original_snapshot.at("entitiesEnabled");
            require(restored == original_snapshot, "entrance/entity overrides change only copied render fields");
            const auto& entities_proof = report.at("states").at(0).at("renderEntitiesOverride");
            require(
                entities_proof.at("request") == false && entities_proof.at("originalEntitiesEnabled") == true &&
                    entities_proof.at("renderOnly") == true && entities_proof.at("physicsStateUnchanged") == true,
                "render-only entity toggle explicitly reports its original default"
            );
            const auto& proof = report.at("states").at(0).at("renderEntranceOverride");
            require(
                proof.at("request") == requested && proof.at("selectedEntranceRows") == expected &&
                    proof.at("originalEntranceRows") == original_snapshot.at("entranceRows") &&
                    proof.at("renderOnly") == true && proof.at("physicsStateUnchanged") == true,
                "entrance render-only override reports its request and original live rows"
            );
            require(
                inspection.state() == physics_before && test_impl.edicts == edicts_before &&
                    test_impl.globals == globals_before &&
                    gameplay_snapshot_json(inspection.render_snapshot()) == original_snapshot,
                "entrance override preserves all edicts/globals, RNG, clocks, pending walk and later snapshots"
            );
        }
        const auto reject = [&](const Json& step) {
            bool rejected = false;
            try
            {
                (void)run_gameplay_script(
                    inspection,
                    Json{{"schema", "quake-gameplay-script-v1"}, {"steps", Json::array({step})}}
                );
            }
            catch (const std::exception&)
            {
                rejected = true;
            }
            require(
                rejected && inspection.state() == physics_before && test_impl.edicts == edicts_before &&
                    test_impl.globals == globals_before,
                "invalid entrance render override rejects before simulation mutation"
            );
        };
        for (const auto& invalid : std::vector<Json>{
                 nullptr,
                 Json::object(),
                 Json::array(),
                 Json::array({0}),
                 Json::array({0, 0, 0}),
                 Json::array({false, 0}),
                 Json::array({0.0, 0}),
                 Json::array({"0", 0}),
                 Json::array({-1, 0}),
                 Json::array({0, 17}),
                 Json::array({std::numeric_limits<std::uint64_t>::max(), 0}),
                 Json{{"poses", {0, 0}}, {"unknown", true}}
             })
            reject(Json{{"op", "snapshot"}, {"renderEntrancePoses", invalid}});
        for (const auto* op : {"video", "step", "service", "servicePhase", "reset", "fixture"})
            reject(Json{{"op", op}, {"renderEntrancePoses", {0, 16}}});
        reject(Json{{"op", "snapshot"}, {"renderEntrancePoses", {0, 16}}, {"unknown", true}});
        reject(Json{{"op", "snapshot"}, {"renderEntrancePoses", {0, 16}}, {"ticks", 1}});
        reject(Json{{"op", "snapshot"}, {"renderEntrancePoses", {0, 16}}, {"input", {{"joypad", 64}}}});
        for (const auto& invalid : std::vector<Json>{nullptr, 0, 1, "false", Json::array(), Json::object()})
            reject(Json{{"op", "snapshot"}, {"renderEntities", invalid}});
        for (const auto* op : {"video", "step", "service", "servicePhase", "reset", "fixture"})
            reject(Json{{"op", op}, {"renderEntities", false}});
        const auto entity_only = run_gameplay_script(
            inspection,
            Json{
                {"schema", "quake-gameplay-script-v1"},
                {"steps",
                 Json::array(
                     {Json{{"op", "snapshot"}, {"renderEntities", false}},
                      Json{{"op", "snapshot"}, {"renderEntities", true}}}
                 )}
            }
        );
        require(
            entity_only.at("states").at(0).at("renderSnapshot").at("entitiesEnabled") == false &&
                entity_only.at("states").at(1).at("renderSnapshot").at("entitiesEnabled") == true &&
                inspection.state() == physics_before && test_impl.edicts == edicts_before &&
                test_impl.globals == globals_before,
            "entity-only render controls preserve all live state and accept both boolean values"
        );
        auto& leaves = render_assets.manifest["metadata"]["gameplay"]["stockEntranceDoors"];
        const auto correct_leaves = leaves;
        leaves = Json::array();
        reject(Json{{"op", "snapshot"}, {"renderEntrancePoses", {0, 16}}});
        leaves = correct_leaves;
        leaves[1]["poseRows"][16] = 65536;
        reject(Json{{"op", "snapshot"}, {"renderEntrancePoses", {0, 16}}});
        leaves = correct_leaves;
        leaves[0]["poseRows"][0] = false;
        reject(Json{{"op", "snapshot"}, {"renderEntrancePoses", {0, 16}}});
    }

    {
        auto hub_assets = assets;
        hub_assets.map = "start";
        hub_assets.manifest["map"] = "start";
        auto destination = assets;
        destination.map = "e1m1";
        destination.manifest["map"] = "e1m1";
        auto bounds = [](unsigned entity, int x) {
            return Json{
                {"entityNumber", entity},
                {"triggerEyeMinQ4", {x - 16, -16, -16}},
                {"triggerEyeMaxQ4", {x + 16, 16, 16}}
            };
        };
        Json hub{
            {"schema", "quake-start-hub-v1"},
            {"skills", Json::array()},
            {"teleports", Json::array()},
            {"exits", Json::array()}
        };
        for (unsigned skill = 0; skill < 4; ++skill)
        {
            auto trigger = bounds(skill + 1, 1000 + int(skill) * 1000);
            trigger["skill"] = skill;
            hub["skills"].push_back(std::move(trigger));
        }
        auto teleport = bounds(10, 5000);
        teleport["destinationEyeQ4"] = {7000, -3000, 80};
        teleport["destinationYaw"] = 90;
        hub["teleports"].push_back(std::move(teleport));
        auto exit = bounds(20, 8000);
        exit["destination"] = "e1m1";
        hub["exits"].push_back(std::move(exit));
        hub["registeredWarning"] = {
            {"message", "For registered users only!\nPlay episode 1"},
            {"durationQ6", 128},
            {"triggers", {bounds(21, 9000), bounds(22, 10000), bounds(23, 11000)}}
        };
        hub_assets.manifest["metadata"]["gameplay"]["hub"] = hub;
        GameplaySession hub_session({destination, assets, hub_assets});
        auto& host = *hub_session.impl_;
        require(hub_session.state()["map"] == "start", "start is the default playable map");
        host.camera = {9000, 0, 0};
        host.hub_tick();
        require(host.hub_warning_gate == 1 && host.hub_warning_events == 1 && host.sounds == 1 &&
                hub_session.centerprint() == "For registered users only!\nPlay episode 1" && !host.switch_pending,
                "shareware warning displays without entering an unavailable map");
        for (unsigned i = 0; i < 127; ++i)
            host.hub_tick();
        require(host.hub_warning_ticks == 1 && host.hub_warning_events == 1, "warning cannot repeat early");
        host.hub_tick();
        require(host.hub_warning_ticks == 128 && host.hub_warning_events == 2, "warning repeats at two seconds");
        host.camera = {10000, 0, 0};
        host.hub_tick();
        require(host.hub_warning_gate == 2 && host.hub_warning_events == 3, "warning cooldowns are independent");
        host.camera = {0, 0, 0};
        for (unsigned i = 0; i < 128; ++i)
            host.hub_tick();
        require(!host.hub_warning_gate && hub_session.centerprint().empty(), "warning expires after leaving");
        for (unsigned skill = 0; skill < 4; ++skill)
        {
            host.camera = {static_cast<std::int16_t>(1000 + int(skill) * 1000 - 16), -16, -16};
            host.hub_tick();
            require(
                host.skill_selected == skill && host.skill_active == 1 && host.global("SKILL") == 64,
                "inclusive skill trigger chooses next level without changing active difficulty"
            );
        }
        host.camera = {0, 0, 2};
        host.walk.pending = true;
        host.walk.pending_xyz = {2000, 0, 2};
        host.hub_tick();
        require(host.skill_selected == 1, "hub skill checks the completed pending movement");
        host.menu_open = true;
        host.hub_teleport_cooldown = 2;
        host.walk.pending_xyz = {4000, 0, 2};
        host.hub_tick();
        require(
            host.skill_selected == 1 && host.hub_teleport_cooldown == 1,
            "menu blocks hub actions while the fixed QC cooldown still advances"
        );
        host.menu_open = false;
        host.release_gate = true;
        host.hub_tick();
        require(host.skill_selected == 1 && host.hub_teleport_cooldown == 0, "release gate blocks hub actions");
        host.release_gate = false;
        host.camera = {0, 0, 2};
        host.yaw = 12;
        host.pitch = 13;
        host.walk.pending_xyz = {5000, 0, 2};
        host.walk.velocity_z = 123;
        host.walk.grounded = 1;
        host.walk.support_valid = true;
        host.walk.button_contact = 1;
        host.hub_tick();
        require(
            host.camera == GamePoint{0, 0, 2} && host.yaw == 12 && host.pitch == 13 && host.walk.pending &&
                host.walk.pending_xyz == GamePoint{7000, -3000, 80} && host.pending_yaw == 90 &&
                host.pending_yaw_valid && host.hub_teleports == 1 && host.hub_teleport_cooldown == 45,
            "foreground teleport queues position and yaw without early publication"
        );
        require(
            host.walk.velocity_z == 0 && host.walk.grounded == 0 && !host.walk.support_valid &&
                host.walk.button_contact == 0 && host.walk.failed_step_plane == 0xffff,
            "teleport clears gravity and stale support/contact state"
        );
        const auto queued = host.walk.pending_xyz;
        const auto walk_ticks_before = host.walk.ticks;
        host.buttons = 0x40;
        host.walk_tick();
        host.hub_tick();
        require(
            host.walk.pending_xyz == queued && host.walk.ticks == walk_ticks_before && host.pending_yaw_valid &&
                host.hub_teleports == 1 && host.hub_teleport_cooldown == 44,
            "foreground catch-up cannot move a queued teleport with the old heading"
        );
        hub_session.video_tick({});
        require(
            host.camera == queued && host.yaw == 90 && host.pitch == 0 && !host.walk.pending && !host.pending_yaw_valid,
            "NMI atomically publishes teleport position/yaw/pitch"
        );
        for (unsigned tick = 0; tick < 44; ++tick)
        {
            host.camera = {0, 0, 2};
            host.hub_tick();
        }
        require(host.hub_teleport_cooldown == 0, "teleport rearms after forty-five QC ticks");
        host.camera = {5000, 0, 2};
        host.hub_tick();
        require(
            host.hub_teleports == 2 && host.hub_teleport_cooldown == 45,
            "a later authored teleport can trigger after cooldown"
        );
        hub_session.video_tick({});
        host.camera = {8000, 0, 2};
        host.skill_selected = 3;
        host.hub_tick();
        require(
            host.assets().map == "start" && host.pending_map == "e1m1" && host.switch_pending,
            "episode portal queues a cold level load instead of resetting in its callback"
        );
        require(
            !hub_session.service_tick() && hub_session.state()["map"] == "e1m1" && host.skill_selected == 3 &&
                host.skill_active == 3 && host.global("SKILL") == 192 && host.pending_map.empty() &&
                host.hub_teleports == 0,
            "episode load applies selected difficulty and clears old map state"
        );
        for (const auto* expected : {"e1m3", "start", "e1m1"})
        {
            host.skill_selected = 2;
            host.menu({}, 0x1000);
            host.menu({}, 0x100);
            require(host.menu_open && !host.switch_pending, "level direction changes only the draft");
            host.menu({}, 0x80);
            hub_session.service_tick();
            require(
                hub_session.state()["map"] == expected && host.skill_active == 2,
                "level menu reaches all three loaded maps and carries chosen difficulty"
            );
        }
        for (const auto* expected : {"start", "e1m3", "e1m1"})
        {
            host.menu({}, 0x1000);
            host.menu({}, 0x200);
            host.menu({}, 0x80);
            hub_session.service_tick();
            require(
                hub_session.state()["map"] == expected && host.skill_active == 2,
                "left cycles all three maps in the native menu order and retains difficulty"
            );
        }
        auto second_level = assets;
        second_level.map = "e1m2";
        second_level.manifest["map"] = "e1m2";
        GameplaySession four_maps({destination, assets, hub_assets, second_level});
        auto& four_map_host = *four_maps.impl_;
        four_map_host.skill_selected = 2;
        const auto check_level = [&](GameWord direction, const char* expected) {
            four_map_host.menu({}, 0x1000);
            four_map_host.menu({}, direction);
            four_map_host.menu({}, 0x80);
            four_maps.service_tick();
            require(four_maps.state()["map"] == expected && four_map_host.skill_active == 2,
                    "four-map level menu preserves native order and selected difficulty");
        };
        for (const auto* expected : {"e1m2", "e1m1", "e1m3", "start"})
            check_level(0x100, expected);
        for (const auto* expected : {"e1m3", "e1m1", "e1m2", "start"})
            check_level(0x200, expected);

        const auto reject_hub = [&](Json invalid, bool include_destination = true) {
            auto bad = hub_assets;
            bad.manifest["metadata"]["gameplay"]["hub"] = std::move(invalid);
            bool rejected = false;
            try
            {
                std::vector<GameplayAssets> inputs{bad};
                if (include_destination)
                    inputs.push_back(destination);
                GameplaySession invalid_session(std::move(inputs));
            }
            catch (const std::exception&)
            {
                rejected = true;
            }
            require(rejected, "malformed hub metadata rejects before gameplay");
        };
        auto invalid = hub;
        invalid["skills"][0]["skill"] = true;
        reject_hub(invalid);
        invalid = hub;
        invalid["skills"][0]["skill"] = 4;
        reject_hub(invalid);
        invalid = hub;
        invalid["skills"][0]["triggerEyeMinQ4"][0] = 32768;
        reject_hub(invalid);
        invalid = hub;
        invalid["skills"][0]["triggerEyeMaxQ4"][0] = -32768;
        reject_hub(invalid);
        invalid = hub;
        invalid["teleports"][0]["entityNumber"] = 1;
        reject_hub(invalid);
        invalid = hub;
        invalid["teleports"][0]["destinationYaw"] = 256;
        reject_hub(invalid);
        invalid = hub;
        invalid["exits"][0]["destination"] = "missing";
        reject_hub(invalid);
        invalid = hub;
        invalid["schema"] = "unknown";
        reject_hub(invalid);
        reject_hub(hub, false);
    }

    return true;
}

} // namespace quake_bsp_reference
