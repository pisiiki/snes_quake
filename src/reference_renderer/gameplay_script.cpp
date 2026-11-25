#include "gameplay_script.hpp"

namespace quake_bsp_reference {
namespace {
struct GameplayPaletteSample
{
    std::uint16_t bonus;
    int eye;
    bool damage, muzzle, quad, suit;

    explicit GameplayPaletteSample(const GameplayRenderSnapshot& state)
        : bonus(state.pickup_bonus_ticks), eye(state.eye_contents), damage(state.damage_tint),
          muzzle(state.muzzle_tint), quad(state.quad_tint), suit(state.suit_tint) {}

    void apply(GameplayRenderSnapshot& state) const
    {
        state.pickup_bonus_ticks = bonus;
        state.eye_contents = eye;
        state.damage_tint = damage;
        state.muzzle_tint = muzzle;
        state.quad_tint = quad;
        state.suit_tint = suit;
    }
};

void require_fields(const Json& object, std::initializer_list<std::string_view> allowed, std::string_view context)
{
    if (!object.is_object())
        fail(std::string(context) + " must be an object");
    for (const auto& item : object.items())
        if (std::ranges::find(allowed, item.key()) == allowed.end())
            fail(std::string(context) + " contains unknown field " + item.key());
}

struct RenderCameraOverride
{
    std::array<std::int16_t, 3> eye_q4{};
    std::uint8_t yaw{};
    std::int16_t pitch{};
};

RenderCameraOverride parse_render_camera(const Json& value)
{
    require_fields(value, {"eyeQ4", "yaw", "pitch"}, "snapshot renderCamera");
    const auto integer = [](const Json& item, int low, int high) {
        if (!item.is_number_integer() ||
            (item.is_number_unsigned() && item.get<std::uint64_t>() > static_cast<std::uint64_t>(high)))
            fail("snapshot renderCamera requires bounded native integers");
        const auto number = item.get<std::int64_t>();
        if (number < low || number > high)
            fail("snapshot renderCamera coordinate exceeds its native range");
        return static_cast<int>(number);
    };
    const auto& eye = value.at("eyeQ4");
    if (!eye.is_array() || eye.size() != 3)
        fail("snapshot renderCamera eyeQ4 requires three signed native coordinates");
    RenderCameraOverride result;
    for (std::size_t axis = 0; axis < 3; ++axis)
        result.eye_q4[axis] = static_cast<std::int16_t>(integer(eye.at(axis), -32768, 32767));
    result.yaw = static_cast<std::uint8_t>(integer(value.at("yaw"), 0, 255));
    result.pitch = static_cast<std::int16_t>(integer(value.at("pitch"), -64, 64));
    return result;
}

GameplayRenderSnapshot render_camera_snapshot(GameplayRenderSnapshot snapshot, const RenderCameraOverride& camera)
{
    const auto old_position = snapshot.native_camera.position_q2();
    const auto world_origin = snapshot.source_camera.origin -
        Vec3{double(old_position[0]), double(old_position[1]), double(old_position[2])} * (kWorldScale / 4);
    snapshot.eye_q4 = camera.eye_q4;
    snapshot.native_camera = gameplay_render_camera(
        camera.eye_q4, camera.yaw, camera.pitch & 255, snapshot.camera_position_units);
    const auto position = snapshot.native_camera.position_q2();
    snapshot.source_camera.origin = world_origin +
        Vec3{double(position[0]), double(position[1]), double(position[2])} * (kWorldScale / 4);
    snapshot.source_camera.yaw = camera.yaw * 360.0 / 256.0;
    snapshot.source_camera.pitch = -camera.pitch * 360.0 / 256.0;
    const auto yaw = snapshot.native_camera.yaw & 255, pitch = snapshot.native_camera.pitch & 255;
    const double sy = kSinTable[yaw] / 64.0, cy = kCosTable[yaw] / 64.0;
    const double sp = kSinTable[pitch] / 64.0, cp = kCosTable[pitch] / 64.0;
    snapshot.source_camera.capture_basis =
        std::array{Vec3{cp * cy, cp * sy, sp}, Vec3{sy, -cy, 0}, Vec3{-sp * cy, -sp * sy, cp}};
    return snapshot;
}

std::array<std::uint16_t, 2> parse_render_entrance_poses(const Json& value)
{
    if (!value.is_array() || value.size() != 2)
        fail("snapshot renderEntrancePoses requires exactly two integer poses");
    std::array<std::uint16_t, 2> result{};
    for (std::size_t leaf = 0; leaf < result.size(); ++leaf)
    {
        const auto& item = value.at(leaf);
        if (!item.is_number_integer() || (item.is_number_unsigned() && item.get<std::uint64_t>() > 16))
            fail("snapshot renderEntrancePoses requires integer poses in0..16");
        const auto pose = item.get<std::int64_t>();
        if (pose < 0 || pose > 16)
            fail("snapshot renderEntrancePoses requires integer poses in0..16");
        result[leaf] = static_cast<std::uint16_t>(pose);
    }
    return result;
}

unsigned tick_count(const Json& step, unsigned fallback)
{
    if (!step.contains("ticks"))
        return fallback;
    if (!step["ticks"].is_number_integer())
        fail("gameplay ticks must be an integer");
    const auto value = step["ticks"].get<std::int64_t>();
    if (value < 0 || value > 1000000)
        fail("gameplay ticks must be in0..1000000");
    return static_cast<unsigned>(value);
}
} // namespace

Json gameplay_snapshot_json(const GameplayRenderSnapshot& snapshot)
{
    Json basis = nullptr;
    if (snapshot.source_camera.capture_basis)
    {
        basis = Json::array();
        for (const auto& axis : *snapshot.source_camera.capture_basis)
            basis.push_back({axis.x, axis.y, axis.z});
    }
    Json actors = Json::array();
    for (const auto& actor : snapshot.actors)
        actors.push_back(
            {{"slot", actor.slot},
             {"entity", actor.entity},
             {"model", actor.model},
             {"visible", actor.visible},
             {"mdlFrame", actor.mdl_frame},
             {"yaw", actor.yaw},
             {"originQ3", actor.origin_q3},
             {"renderOriginQ2", actor.render_origin_q2}}
        );
    Json brushes = Json::array();
    for (const auto& brush : snapshot.brushes)
        brushes.push_back(
            {{"entity", brush.entity},
             {"modelIndex", brush.model_index},
             {"inlineModel", brush.inline_model},
             {"frame", brush.frame},
             {"origin", Json::array({brush.origin.x, brush.origin.y, brush.origin.z})},
             {"angles", brush.angles}}
        );
    Json result = {
        {"map", snapshot.map},
        {"videoTick", snapshot.video_tick},
        {"nativeCamera",
         Json::array(
             {snapshot.native_camera.x,
              snapshot.native_camera.y,
              snapshot.native_camera.z,
              snapshot.native_camera.yaw,
              snapshot.native_camera.pitch}
         )},
        {"eyeQ4", snapshot.eye_q4},
        {"nativeCameraQ2", snapshot.native_camera.position_q2()},
        {"sourceCamera",
         {{"origin",
           {snapshot.source_camera.origin.x, snapshot.source_camera.origin.y, snapshot.source_camera.origin.z}},
          {"captureBasis", std::move(basis)}}},
        {"brushRow", snapshot.brush_row},
        {"entranceRows", snapshot.entrance_rows},
        {"shellMask", snapshot.shell_mask},
        {"healthMask", snapshot.health_mask},
        {"weaponFrame", snapshot.weapon_frame},
        {"technique", snapshot.technique},
        {"renderScale", snapshot.render_scale},
        {"brushesEnabled", snapshot.brushes_enabled},
        {"entitiesEnabled", snapshot.entities_enabled},
        {"surfaceTime", snapshot.surface_time},
        {"brushes", std::move(brushes)},
        {"skyPhaseQ24", snapshot.sky_phase_q24},
        {"turbulencePhaseQ24", snapshot.turbulence_phase_q24},
        {"aliasPhaseQ32", snapshot.alias_phase_q32},
        {"actors", std::move(actors)}
    };
    if (snapshot.switched_lights)
        result["switchedLights"] = snapshot.switched_lights;
    if (snapshot.intermission_stats)
        result["intermissionStats"] = *snapshot.intermission_stats;
    return result;
}

Json run_gameplay_script(GameplaySession& session, const Json& script, const GameplayCapture& capture)
{
    require_fields(script, {"schema", "initialMap", "steps", "queuedInput", "initialRenderTechnique", "initialRenderScale", "pickupStorePhases",
                            "intermissionClockPhases"}, "gameplay script");
    const bool observe_pickup_stores = script.value("pickupStorePhases", false);
    const bool observe_intermission_clock = script.value("intermissionClockPhases", false);
    if (script.value("schema", "") != "quake-gameplay-script-v1")
        fail("unsupported gameplay script schema");
    if (script.contains("initialMap"))
        session.reset(script.at("initialMap").get<std::string>());
    if (script.contains("queuedInput"))
        session.use_queued_input(script.at("queuedInput").get<bool>());
    if (script.contains("initialRenderScale"))
    {
        const auto& scale = script.at("initialRenderScale");
        if (!scale.is_number_integer() || (scale != 2 && scale != 3))
            fail("initialRenderScale must be 2 or 3");
        session.set_initial_render_scale(scale.get<unsigned>());
    }
    if (script.contains("initialRenderTechnique"))
    {
        const auto& technique = script.at("initialRenderTechnique");
        if (!technique.is_number_integer())
            fail("initialRenderTechnique must be an integer");
        session.set_render_technique(technique.get<unsigned>());
    }
    if (!script.contains("steps") || !script.at("steps").is_array())
        fail("gameplay script requires a steps array");
    Json rows = Json::array();
    std::vector<std::string> labels;
    std::optional<std::pair<std::string, GameplayRenderSnapshot>> frozen_world;
    std::map<std::string, GameplayRenderSnapshot> awaiting_display;
    std::map<std::string, GameplayPaletteSample> palette_samples;
    std::optional<std::uint16_t> pickup_peak;
    Json previous_video_clocks, video_clocks;
    std::string clock_map;
    for (const auto& step : script.at("steps"))
    {
        require_fields(
            step,
            {"label",
             "op",
             "ticks",
             "input",
             "map",
             "skill",
             "capture",
             "eyeQ4",
             "yaw",
             "pitch",
             "healthQ6",
             "initialArmor",
             "initialQuad",
             "initialShells",
             "phase",
             "renderCamera",
             "renderEntrancePoses",
             "renderEntities",
             "observeWorld",
             "worldSnapshot",
             "deferDisplay",
             "presentFrame",
             "observePickupPeak",
             "recordPaletteSample",
             "publishedPaletteSource",
             "previousVideoSurfaceClocks"},
            "gameplay step"
        );
        const auto index = rows.size();
        const auto op = step.value("op", "step");
        const auto label = step.value("label", "step-" + std::to_string(index));
        const bool capture_requested = step.value("capture", op == "snapshot");
        const bool observe_world = step.value("observeWorld", false);
        const auto world_snapshot = step.value("worldSnapshot", "");
        const bool defer_display = step.value("deferDisplay", false);
        const auto present_frame = step.value("presentFrame", "");
        const bool observe_peak = step.value("observePickupPeak", false);
        const bool record_palette = step.value("recordPaletteSample", false);
        if ((observe_peak && (op != "snapshot" || capture_requested)) ||
            (record_palette && op != "video" && !observe_peak) ||
            (step.contains("publishedPaletteSource") && present_frame.empty()))
            fail("invalid gameplay palette observation or presentation");
        if ((defer_display && world_snapshot.empty()) ||
            (step.contains("presentFrame") && (op != "video" || !capture_requested || present_frame.empty())))
            fail("deferred presentation requires a composed frame and its VBlank");
        const auto previous_clocks = step.value("previousVideoSurfaceClocks", std::vector<std::string>{});
        if (step.contains("previousVideoSurfaceClocks") &&
            (!observe_world || previous_video_clocks.is_null() || previous_clocks.empty()))
            fail("previous video surface clocks require a frozen world and an earlier replayed VBlank");
        if (label.empty() || label.size() > 160 || std::ranges::find(labels, label) != labels.end())
            fail("gameplay step labels must be nonempty and unique (maximum160bytes)");
        labels.push_back(label);
        const auto ticks =
            tick_count(step, op == "reset" || op == "snapshot" || op == "fixture" || op == "servicePhase" ? 0U : 1U);
        const auto input_json = step.value("input", Json::object());
        const auto input = gameplay_input_from_json(input_json);
        std::optional<RenderCameraOverride> render_camera;
        if (step.contains("renderCamera"))
        {
            if (op != "snapshot")
                fail("renderCamera is allowed only on a snapshot operation");
            render_camera = parse_render_camera(step.at("renderCamera"));
        }
        std::optional<std::array<std::uint16_t, 2>> render_entrance_rows;
        if (step.contains("renderEntrancePoses"))
        {
            if (op != "snapshot")
                fail("renderEntrancePoses is allowed only on a snapshot operation");
            const auto poses = parse_render_entrance_poses(step.at("renderEntrancePoses"));
            render_entrance_rows = session.entrance_render_rows(poses);
        }
        std::optional<bool> render_entities;
        if (step.contains("renderEntities"))
        {
            if (op != "snapshot" || !step.at("renderEntities").is_boolean())
                fail("renderEntities requires a boolean on a snapshot operation");
            render_entities = step.at("renderEntities").get<bool>();
        }
        if (step.contains("observeWorld") || step.contains("worldSnapshot"))
        {
            if (op != "snapshot" || render_camera || render_entrance_rows || render_entities)
                fail("two-phase frame snapshots require independent gameplay state");
            if (observe_world && (capture_requested || step.contains("worldSnapshot")))
                fail("a frozen world observation cannot compose or capture");
            if (step.contains("worldSnapshot") && (world_snapshot.empty() || !capture_requested))
                fail("worldSnapshot requires a named observation and capture");
        }
        unsigned services = 0;
        std::string observed_phase;
        if (op != "fixture" && (step.contains("eyeQ4") || step.contains("yaw") || step.contains("pitch") ||
                                step.contains("healthQ6") || step.contains("initialArmor") || step.contains("initialQuad") ||
                                step.contains("initialShells")))
            fail("gameplay initial fields require the fixture operation");
        if (op != "servicePhase" && step.contains("phase"))
            fail("gameplay phase requires the servicePhase operation");
        if (op == "servicePhase")
        {
            if (ticks != 0 || !input_json.empty() || step.contains("map") || step.contains("skill"))
                fail("gameplay servicePhase cannot advance video ticks, reset, or apply input");
            const auto expected_phase = step.at("phase").get<std::string>();
            if (expected_phase.empty() || expected_phase.size() > 160)
                fail("gameplay servicePhase requires a bounded phase name");
            observed_phase = expected_phase == "service.begin" ? session.begin_service() : session.resume_service();
            // Legacy captures omit the within-service reads and stores.
            while ((!observe_pickup_stores && observed_phase.starts_with("pickup.")) ||
                   (!observe_intermission_clock && observed_phase.starts_with("intermission.")))
                observed_phase = session.resume_service();
            if (observed_phase != expected_phase)
                fail("gameplay service phase diverged at " + label + ": expected " + expected_phase + ", observed " +
                     observed_phase);
            if (observed_phase == "service.begin")
                pickup_peak.reset();
            else if (observed_phase == "pickup.bonusAfter")
                pickup_peak = session.render_snapshot(false).pickup_bonus_ticks;
            services = observed_phase == "service.end" ? 1U : 0U;
        }
        else if (op == "fixture")
        {
            if (ticks != 0 || !input_json.empty() || step.contains("map") || step.contains("skill"))
                fail("gameplay fixture can only set the initial pose after reset");
            const auto integer = [](const Json& value, int low, int high) {
                if (!value.is_number_integer())
                    fail("gameplay fixture coordinates must be integers");
                if (value.is_number_unsigned() && value.get<std::uint64_t>() > static_cast<std::uint64_t>(high))
                    fail("gameplay fixture coordinate outside its native range");
                const auto number = value.get<std::int64_t>();
                if (number < low || number > high)
                    fail("gameplay fixture coordinate outside its native range");
                return static_cast<int>(number);
            };
            const auto& eye = step.at("eyeQ4");
            if (!eye.is_array() || eye.size() != 3)
                fail("gameplay fixture eyeQ4 requires three signed native coordinates");
            std::array<std::int16_t, 3> pose{};
            for (std::size_t axis = 0; axis < pose.size(); ++axis)
                pose[axis] = static_cast<std::int16_t>(integer(eye.at(axis), -32768, 32767));
            std::optional<std::int16_t> health;
            if (step.contains("healthQ6"))
                health = static_cast<std::int16_t>(integer(step.at("healthQ6"), -32768, 32767));
            std::optional<std::array<unsigned, 2>> armor;
            if (step.contains("initialArmor"))
            {
                const auto& data = step.at("initialArmor");
                if (!data.is_array() || data.size() != 2)
                    fail("initialArmor requires the stock type index and whole armor points");
                armor = {static_cast<unsigned>(integer(data.at(0), 0, 1)),
                         static_cast<unsigned>(integer(data.at(1), 1, 150))};
            }
            std::optional<unsigned> shells;
            if (step.contains("initialShells"))
                shells = static_cast<unsigned>(integer(step.at("initialShells"), 0, 100));
            session.set_initial_pose(
                pose,
                static_cast<std::uint8_t>(integer(step.at("yaw"), 0, 255)),
                static_cast<std::int16_t>(integer(step.at("pitch"), -64, 64)),
                health, armor, step.value("initialQuad", false), shells
            );
        }
        else if (op == "reset")
        {
            if (ticks != 0 || !input_json.empty())
                fail("gameplay reset cannot advance ticks or apply input");
            if (step.contains("skill") && !step.at("skill").is_number_integer())
                fail("gameplay skill must be an integer");
            const auto skill = step.contains("skill") ? step.at("skill").get<std::int64_t>() : 1;
            if (skill < 0 || skill > 3)
                fail("gameplay skill must be in0..3");
            session.reset(step.at("map").get<std::string>(), static_cast<std::uint8_t>(skill));
            frozen_world.reset();
            awaiting_display.clear();
            pickup_peak.reset();
        }
        else if (op == "snapshot")
        {
            if (ticks != 0 || !input_json.empty())
                fail("gameplay snapshot cannot advance ticks or apply input");
        }
        else if (op == "step" || op == "video" || op == "service")
        {
            if (op == "service" && !input_json.empty())
                fail("gameplay service uses the already latched input");
            for (unsigned tick = 0; tick < ticks; ++tick)
            {
                if (op != "service")
                    session.video_tick(input);
                if (op != "video")
                    services += session.service_tick() ? 1U : 0U;
            }
        }
        else
            fail("unknown gameplay operation " + op);
        Json result{{"label", label}, {"op", op}, {"ticks", ticks}, {"input", input_json}, {"services", services}};
        if (op == "snapshot" || capture_requested || record_palette)
        {
            const auto physics_before =
                render_camera || render_entrance_rows || render_entities
                    ? std::optional<Json>{session.state()}
                    : std::nullopt;
            auto snapshot = session.render_snapshot(!observe_world && !observe_peak && present_frame.empty() &&
                                                    !(op == "video" && record_palette));
            if (observe_peak)
            {
                if (!pickup_peak)
                    fail("palette peak has no independent gameplay pickup");
                snapshot.pickup_bonus_ticks = *pickup_peak;
                pickup_peak.reset();
            }
            if (record_palette)
                palette_samples.emplace(label, GameplayPaletteSample(snapshot));
            for (const auto& clock : previous_clocks)
            {
                if (clock == "sky")
                {
                    snapshot.sky_phase_q24 = previous_video_clocks.at("skyPhaseQ24").get<std::uint64_t>();
                    snapshot.surface_time = double(snapshot.sky_phase_q24) / (8. * 16777216.);
                }
                else if (clock == "turbulence")
                    snapshot.turbulence_phase_q24 = previous_video_clocks.at("turbulencePhaseQ24").get<std::uint32_t>();
                else
                    fail("unknown previous video surface clock " + clock);
            }
            if (render_camera)
            {
                const auto original = gameplay_snapshot_json(snapshot);
                snapshot = render_camera_snapshot(std::move(snapshot), *render_camera);
                result["renderCameraOverride"] = {
                    {"schema", "quake-gameplay-render-camera-override-v1"},
                    {"request", step.at("renderCamera")},
                    {"originalEyeQ4", original.at("eyeQ4")},
                    {"originalNativeCamera", original.at("nativeCamera")},
                    {"physicsStateUnchanged", true}
                };
            }
            if (render_entrance_rows)
            {
                const auto original = snapshot.entrance_rows;
                snapshot.entrance_rows = *render_entrance_rows;
                result["renderEntranceOverride"] = {
                    {"schema", "quake-gameplay-render-entrance-override-v1"},
                    {"request", step.at("renderEntrancePoses")},
                    {"originalEntranceRows", original},
                    {"selectedEntranceRows", snapshot.entrance_rows},
                    {"renderOnly", true},
                    {"physicsStateUnchanged", true}
                };
            }
            if (render_entities)
            {
                const auto original = snapshot.entities_enabled;
                snapshot.entities_enabled = *render_entities;
                result["renderEntitiesOverride"] = {
                    {"schema", "quake-gameplay-render-entities-override-v1"},
                    {"request", *render_entities},
                    {"originalEntitiesEnabled", original},
                    {"renderOnly", true},
                    {"physicsStateUnchanged", true}
                };
            }
            result["renderSnapshot"] = gameplay_snapshot_json(snapshot);
            if (observe_world)
                frozen_world.emplace(label, std::move(snapshot));
            else if (!world_snapshot.empty())
            {
                if (!frozen_world || frozen_world->first != world_snapshot || frozen_world->second.map != snapshot.map)
                    fail("worldSnapshot does not name the pending frozen world");
                auto composed = std::move(frozen_world->second);
                frozen_world.reset();
                composed.weapon_frame = snapshot.weapon_frame;
                // IntermissionStage draws on the completed world after gameplay may have advanced.
                composed.intermission_stats = snapshot.intermission_stats;
                composed.pickup_bonus_ticks = snapshot.pickup_bonus_ticks;
                composed.eye_contents = snapshot.eye_contents;
                composed.damage_tint = snapshot.damage_tint;
                composed.muzzle_tint = snapshot.muzzle_tint;
                composed.pickup_lines = snapshot.pickup_lines;
                composed.quad_tint = snapshot.quad_tint;
                composed.suit_tint = snapshot.suit_tint;
                result["composedFrom"] = world_snapshot;
                if (defer_display)
                    awaiting_display.emplace(label, std::move(composed));
                else if (capture)
                    result["capture"] = capture(composed, index, label);
            }
            else if (!present_frame.empty())
            {
                auto frame = awaiting_display.extract(present_frame);
                if (frame.empty() || frame.mapped().map != snapshot.map)
                    fail("presentFrame does not name a completed frame on this map");
                auto& displayed = frame.mapped();
                displayed.pickup_bonus_ticks = snapshot.pickup_bonus_ticks;
                displayed.eye_contents = snapshot.eye_contents;
                displayed.damage_tint = snapshot.damage_tint;
                displayed.muzzle_tint = snapshot.muzzle_tint;
                displayed.quad_tint = snapshot.quad_tint;
                displayed.suit_tint = snapshot.suit_tint;
                if (step.contains("publishedPaletteSource"))
                {
                    const auto source = step.at("publishedPaletteSource").get<std::string>();
                    if (source.empty())
                    {
                        // The ordinary ROM palette still follows live damage, muzzle and held-artifact tints.
                        displayed.pickup_bonus_ticks = 0;
                        displayed.eye_contents = -1;
                    }
                    else
                    {
                        const auto sample = palette_samples.find(source);
                        if (sample == palette_samples.end())
                            fail("published gameplay palette has no earlier independent source");
                        sample->second.apply(displayed);
                    }
                    result["publishedPaletteSource"] = source;
                }
                result["presentedFrom"] = present_frame;
                if (capture)
                    result["capture"] = capture(displayed, index, label);
            }
            else if (capture && capture_requested)
                result["capture"] = capture(snapshot, index, label);
            if (physics_before && session.state() != *physics_before)
                fail("render-only override changed gameplay state during snapshot capture");
        }
        result["state"] = session.state();
        const auto& map = result["state"].at("map").get_ref<const std::string&>();
        if (map != clock_map)
        {
            awaiting_display.clear();
            clock_map = map;
            if (frozen_world && frozen_world->second.map != map)
                frozen_world.reset();
            video_clocks = result["state"].at("surfaceClock");
            previous_video_clocks = video_clocks;
        }
        else if (op == "video")
        {
            previous_video_clocks = std::move(video_clocks);
            video_clocks = result["state"].at("surfaceClock");
        }
        if (!observed_phase.empty())
            result["servicePhase"] = observed_phase;
        rows.push_back(std::move(result));
        // The full-state boundary was captured above. Release only its final
        // return, so a following begin cannot inherit an abandoned worker.
        if (observed_phase == "service.end" && session.resume_service() != "done")
            fail("gameplay service.end did not return directly to done");
    }
    return {
        {"schema", "quake-gameplay-script-report-v1"},
        {"passed", true},
        {"states", std::move(rows)},
        {"finalState", session.state()}
    };
}

} // namespace quake_bsp_reference
