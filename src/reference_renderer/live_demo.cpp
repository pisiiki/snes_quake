#include "live_demo.hpp"
#include "world.hpp"
#include "geometry.hpp"
#include "sky.hpp"
#include "instrumentation.hpp"
#include "brushes.hpp"
#include "audio.hpp"
#include "external_models.hpp"
#include "aliases.hpp"
#include "textured_live.hpp"
#include "ordered_replay.hpp"

namespace quake_bsp_reference {

void bind_full_precision_aliases(FullPrecisionReplay& precision, const SourceWorld& world, const AliasAssets& aliases)
{
    precision.packed_alias_ids.resize(precision.rows.size());
    const auto q2 = [](double value, double origin) {
        const double q3 = std::nearbyint(value * 8.0) / 8.0;
        return std::floor((q3 - origin) * 4.0 / kWorldScale + 0.5);
    };
    for (std::size_t pose = 0; pose < precision.rows.size(); ++pose)
    {
        const auto& row = aliases.rows.at(pose);
        const auto& entities = precision.rows[pose].entities;
        const auto& known = aliases.row_entity_ids.at(pose);
        auto& ids = precision.packed_alias_ids[pose];
        ids.assign(row.dynamic_states.size(), -1);
        for (const auto& token : row.tokens)
        {
            if (token.is_static || ids.at(token.index) >= 0)
                continue;
            if (token.index < known.size() && known[token.index] >= 0 && entities.contains(known[token.index]))
            {
                ids[token.index] = known[token.index];
                continue;
            }
            const auto& state = row.dynamic_states.at(token.index);
            const auto& sprite = aliases.sprites.at(alias_sprite_id(state));
            const auto& model = aliases.model_names.at(sprite.model);
            int match = -1;
            int best_rank = 0;
            bool ambiguous = false;
            for (const auto& [id, source] : entities)
            {
                if (source.model != model || q2(source.origin.x, world.origin.x) != state.origin_q2[0] ||
                    q2(source.origin.y, world.origin.y) != state.origin_q2[1] ||
                    q2(source.origin.z, world.origin.z) != state.origin_q2[2])
                    continue;
                const int rank = source.frame == sprite.frame ? 2 : 1;
                if (rank > best_rank)
                {
                    match = id;
                    best_rank = rank;
                    ambiguous = false;
                }
                else if (rank == best_rank)
                {
                    const auto& previous = entities.at(match);
                    ambiguous =
                        ambiguous || previous.origin.x != source.origin.x || previous.origin.y != source.origin.y ||
                        previous.origin.z != source.origin.z || previous.angles != source.angles;
                }
            }
            if (match < 0 || ambiguous)
                fail("cannot bind full precision alias " + model + " at pose " + std::to_string(pose));
            ids[token.index] = match;
        }
    }
}

LiveRenderResult render_full_precision_live_frame(
    const SourceWorld& world,
    const Bvh& bvh,
    const BrushScene& brush_scene,
    const BrushReplay& brush_replay,
    const AliasAssets& aliases,
    const FullPrecisionReplay& precision,
    const SourceCamera& camera,
    std::size_t scene_pose,
    RenderMode mode,
    bool flat,
    bool brushes,
    bool entities,
    bool fly,
    const ExternalBspScene* external_scene,
    const ExternalBspReplay* external_replay,
    const ParticleReplay* particles
)
{
    const auto transform =
        [&](int id, bool is_static = false, bool held_actor = false) -> const SourceEntityTransform& {
        if (held_actor && !is_static)
            if (const auto* source = precision.last_observed(scene_pose, id))
                return *source;
        if (const auto* source = precision.entity(scene_pose, id, is_static, fly))
            return *source;
        fail("full precision replay omits entity " + std::to_string(id) + " at pose " + std::to_string(scene_pose));
    };
    std::vector<BrushEntityState> brush_states;
    if (brushes)
    {
        const auto row = brush_replay.row(scene_pose);
        brush_states.assign(row.begin(), row.end());
        for (auto& brush : brush_states)
        {
            const auto& source = transform(brush.entity);
            if (source.angles != std::array<double, 3>{})
                fail("the source renderer requires translation-only inline brushes");
            brush.origin = source.origin;
        }
    }
    const auto view = source_view_transform(camera);
    const auto server_time =
        brush_replay.first_server_time + static_cast<double>(scene_pose) / brush_replay.sample_rate;
    auto frame = render_source_reference_with_brushes(
        world,
        bvh,
        brush_scene,
        camera,
        brush_states,
        scene_pose,
        server_time,
        flat,
        brushes
    );
    ExternalBspCoverage external_coverage;
    if (external_scene && external_replay)
    {
        const auto row = external_replay->row(scene_pose);
        std::vector<ExternalBspEntityState> states(row.begin(), row.end());
        for (auto& state : states)
        {
            const auto& source = transform(state.entity);
            state.origin = source.origin;
            state.source_angles = source.angles;
        }
        compose_source_external_bsp_models(
            *external_scene,
            states,
            scene_pose,
            server_time,
            flat,
            view,
            frame,
            &external_coverage
        );
    }
    Json surface = {{"schema", "quake-reference-surface-inspection-v1"}, {"available", false}};
    if (mode.textures)
    {
        auto sky = render_quake_sky_presentation(
            mode.lighting == Lighting::None ? frame.texture_indices : frame.lightmap_texture_indices,
            frame.faces,
            frame.entities,
            world,
            view,
            server_time,
            "demo-server-time"
        );
        (mode.lighting == Lighting::None ? frame.texture_indices : frame.lightmap_texture_indices) =
            std::move(sky.indices);
        surface = std::move(sky.inspection);
    }
    if (entities)
    {
        compose_alias_billboards(
            frame,
            world,
            view,
            aliases,
            scene_pose,
            nullptr,
            std::nullopt,
            [&](const AliasToken& token, const AliasState& state) {
                const auto id =
                    token.is_static
                        ? aliases.static_entity_ids.at(token.index)
                        : (fly ? aliases.row_entity_ids.at(scene_pose) : precision.packed_alias_ids.at(scene_pose))
                              .at(token.index);
                const bool source_static = token.is_static || (fly && precision.static_entities.contains(id));
                const auto& source = transform(id, source_static, fly);
                const auto base = alias_sprite_id(state);
                const auto& sprite = aliases.sprites.at(base);
                if (aliases.model_kinds.at(sprite.model) != "mdl")
                    return SourceAliasPlacement{source.origin, base};
                const double yaw = aliases.model_rotates.at(sprite.model) ? server_time * 100.0 : source.angles[1];
                const auto offset = view.origin - source.origin;
                const double angle = std::atan2(offset.y, offset.x) * (180.0 / std::numbers::pi) - yaw;
                const auto direction = static_cast<int>(std::floor(std::remainder(angle, 360.0) / 45.0 + 0.5)) & 7;
                const auto matching = [&](const AliasSprite& other) {
                    return other.model == sprite.model && other.frame == sprite.frame;
                };
                if ((state.sprite & kAliasDirectionalTag) != 0)
                    return SourceAliasPlacement{source.origin, base + static_cast<std::size_t>(direction)};
                auto closest = base;
                auto best_distance = 8;
                for (std::size_t i = 0; i < aliases.sprites.size(); ++i)
                {
                    const auto& candidate = aliases.sprites[i];
                    if (!matching(candidate))
                        continue;
                    const int delta = std::abs(direction - candidate.view);
                    const int distance = std::min(delta, 8 - delta);
                    if (distance < best_distance)
                    {
                        closest = i;
                        best_distance = distance;
                        if (distance == 0)
                            break;
                    }
                }
                return SourceAliasPlacement{source.origin, closest};
            }
        );
    }
    LiveRenderResult result{select_live_indices(frame, mode, false)};
    surface["liquidLighting"] = liquid_lighting_inspection(frame, mode);
    if (particles)
        surface["particles"] = compose_particles(result.indices, frame.depths, view, *particles, scene_pose, mode);
    result.surface_inspection = std::move(surface);
    if (external_replay)
        result.external_bsp_inspection = external_bsp_inspection(
            *external_replay,
            scene_pose,
            external_scene != nullptr,
            external_scene != nullptr,
            external_coverage
        );
    return result;
}

int run_source_realtime_demo(
    const SourceWorld& world,
    const Bvh& bvh,
    const BrushScene& brush_scene,
    const BrushReplay& brush_replay,
    const AliasAssets& alias_assets,
    const fs::path& track_path,
    bool flat,
    RenderMode initial_mode,
    bool initial_legacy_material,
    PlaybackSpeed initial_playback_speed,
    bool brushes_enabled,
    bool entities_enabled,
    const ExternalBspScene* external_scene,
    const ExternalBspReplay* external_replay,
    bool external_bsp_models_enabled,
    const QuakeSoundAssets* sound_assets,
    bool sound_enabled,
    float sound_volume,
    ReferenceInstrumentationConfig instrumentation,
    const ParticleReplay* particles,
    bool particles_enabled,
    const BrushReplay* fly_brush_replay,
    const SourceFlyAliases* fly_aliases,
    const X2WeaponAssets* x2_weapon,
    const FullPrecisionReplay* full_precision
)
{
    const auto canonical_cameras = load_precise_demo_track(track_path);
    if (canonical_cameras.size() != brush_replay.row_count())
    {
        fail("camera and brush replay row counts disagree");
    }
    if (x2_weapon != nullptr && x2_weapon->pose_count() != canonical_cameras.size())
    {
        fail("X2 weapon and camera replay source pose counts disagree");
    }
    const double precise_rate = brush_replay.sample_rate;
    const double duration_seconds = constant_step_duration(canonical_cameras.size(), precise_rate);
    std::optional<SourceCamera> capture_camera;
    bool fly_mode = false;
    std::function<void(bool)> fly_mode_setter;
    if (fly_brush_replay != nullptr && fly_aliases != nullptr)
        fly_mode_setter = [&](bool enabled) { fly_mode = enabled; };
    const auto camera_at_pose = [&](std::size_t pose) { return capture_camera.value_or(canonical_cameras.at(pose)); };
    const auto source_camera_at_pose = [&](std::size_t pose) {
        return capture_camera.value_or(full_precision->rows.at(pose).camera);
    };
    return run_live_demo(
        world,
        canonical_cameras,
        duration_seconds,
        [&](double seconds) { return constant_step_pose_at_time(canonical_cameras.size(), seconds, precise_rate); },
        [precise_rate](std::size_t pose) { return static_cast<double>(pose) / precise_rate; },
        [&](std::size_t pose) { return source_view_transform(camera_at_pose(pose)); },
        [&](std::size_t pose,
            std::size_t scene_pose,
            RenderMode mode,
            bool legacy_material,
            bool brushes,
            bool entities,
            bool external_models,
            bool show_particles,
            bool use_full_precision) {
            const auto& active_brush_replay =
                fly_mode && fly_brush_replay != nullptr ? *fly_brush_replay : brush_replay;
            if (use_full_precision)
                return render_full_precision_live_frame(
                    world,
                    bvh,
                    brush_scene,
                    active_brush_replay,
                    fly_mode ? fly_aliases->assets : alias_assets,
                    *full_precision,
                    source_camera_at_pose(pose),
                    scene_pose,
                    mode,
                    flat,
                    brushes,
                    entities,
                    fly_mode,
                    external_models ? external_scene : nullptr,
                    external_replay,
                    show_particles ? particles : nullptr
                );
            auto frame = render_source_reference_with_brushes(
                world,
                bvh,
                brush_scene,
                camera_at_pose(pose),
                active_brush_replay,
                scene_pose,
                flat,
                brushes
            );
            ExternalBspCoverage external_coverage;
            if (external_replay != nullptr)
            {
                external_coverage = external_bsp_row_coverage(*external_replay, scene_pose);
                if (external_models)
                {
                    if (external_scene == nullptr)
                    {
                        fail("external BSP playback has no loaded model scene");
                    }
                    compose_source_external_bsp_models(
                        *external_scene,
                        external_replay->row(scene_pose),
                        scene_pose,
                        external_bsp_server_time(*external_replay, scene_pose),
                        flat,
                        source_view_transform(camera_at_pose(pose)),
                        frame,
                        &external_coverage
                    );
                }
            }
            Json surface_inspection{
                {"schema", "quake-reference-surface-inspection-v1"},
                {"available", false},
                {"reason", "textures are disabled for this frame"}
            };
            const auto view = source_view_transform(camera_at_pose(pose));
            if (mode.textures && !legacy_material)
            {
                const double surface_time =
                    brush_replay.first_server_time + (static_cast<double>(scene_pose) / brush_replay.sample_rate);
                auto albedo = render_quake_sky_presentation(
                    frame.texture_indices,
                    frame.faces,
                    frame.entities,
                    world,
                    view,
                    surface_time,
                    "demo-server-time"
                );
                auto lightmap = render_quake_sky_presentation(
                    frame.lightmap_texture_indices,
                    frame.faces,
                    frame.entities,
                    world,
                    view,
                    surface_time,
                    "demo-server-time"
                );
                frame.texture_indices = std::move(albedo.indices);
                frame.lightmap_texture_indices = std::move(lightmap.indices);
                surface_inspection = std::move(albedo.inspection);
            }
            if (entities)
            {
                const auto& active_aliases = fly_mode ? fly_aliases->assets : alias_assets;
                compose_alias_billboards(
                    frame,
                    world,
                    view,
                    active_aliases,
                    scene_pose,
                    nullptr,
                    fly_mode ? std::optional<std::uint8_t>(fly_aliases->rotations.at(scene_pose)) : std::nullopt
                );
            }
            LiveRenderResult result{select_live_indices(frame, mode, legacy_material)};
            surface_inspection["liquidLighting"] = liquid_lighting_inspection(frame, mode);
            surface_inspection["brushScene"] = {
                {"policy", fly_mode ? "complete-fly-sign-on-fallback" : "recorded-demo-packet"},
                {"brushes", active_brush_replay.row(scene_pose).size()},
                {"poses", active_brush_replay.row_count()}
            };
            surface_inspection["aliasScene"] =
                fly_mode ? fly_aliases->provenance
                         : Json{{"policy", "recorded-demo-packet"}, {"completeFlyAvailable", fly_aliases != nullptr}};
            const auto& active_aliases = fly_mode ? fly_aliases->assets : alias_assets;
            surface_inspection["aliasScene"]["actors"] = active_aliases.rows.at(scene_pose).dynamic_states.size();
            surface_inspection["aliasScene"]["tokens"] = active_aliases.rows.at(scene_pose).tokens.size();
            surface_inspection["aliasScene"]["enabled"] = entities;
            if (fly_mode)
            {
                std::map<std::uint16_t, std::size_t> visible;
                for (std::size_t pixel = 0; pixel < frame.faces.size(); ++pixel)
                    if (frame.faces[pixel] == kAliasFace)
                        ++visible[frame.entities[pixel]];
                auto& inspected = surface_inspection["aliasScene"]["visibleActors"] = Json::array();
                for (const auto& [index, pixels] : visible)
                {
                    const auto& state = active_aliases.rows.at(scene_pose).dynamic_states.at(index);
                    const int dx = wrap_i16(
                        static_cast<int>(
                            std::lround(state.origin_q2[0] - (view.origin.x - world.origin.x) * 4.0 / kWorldScale)
                        )
                    );
                    const int dy = wrap_i16(
                        static_cast<int>(
                            std::lround(state.origin_q2[1] - (view.origin.y - world.origin.y) * 4.0 / kWorldScale)
                        )
                    );
                    const auto& sprite = active_aliases.sprites.at(
                        alias_resolved_sprite_id(state, dx, dy, fly_aliases->rotations.at(scene_pose))
                    );
                    inspected.push_back(
                        {{"entity", active_aliases.row_entity_ids.at(scene_pose).at(index)},
                         {"model", active_aliases.model_names.at(sprite.model)},
                         {"frame", sprite.frame},
                         {"view", sprite.view},
                         {"pixels", pixels}}
                    );
                }
            }
            if (show_particles && particles != nullptr)
                surface_inspection["particles"] =
                    compose_particles(result.indices, frame.depths, view, *particles, scene_pose, mode);
            result.surface_inspection = std::move(surface_inspection);
            if (external_replay != nullptr)
            {
                result.external_bsp_inspection = external_bsp_inspection(
                    *external_replay,
                    scene_pose,
                    external_models,
                    external_models,
                    external_coverage
                );
            }
            return result;
        },
        LiveDemoConfiguration{
            .playback_contract = "source renderer | offline interpolated fixed-rate cameras | Q3 "
                                 "position + u16 angles | no runtime interpolation",
            .initial_mode = initial_mode,
            .initial_legacy_material = initial_legacy_material,
            .initial_playback_speed = initial_playback_speed,
            .playback_speed_control = true,
            .playback_schedule = PlaybackSchedule::NewestDue,
            .initial_presentation_rate_hz = 3,
            .instrumentation_config = std::move(instrumentation),
            .sound_assets = sound_assets,
            .initial_sound_enabled = sound_enabled,
            .initial_sound_volume = sound_volume,
            .legacy_material_control = false,
            .brush_control = true,
            .entity_control = true,
            .external_bsp_model_control = external_replay != nullptr,
            .particle_control = particles != nullptr,
            .initial_brushes = brushes_enabled,
            .initial_entities = entities_enabled,
            .initial_external_bsp_models = external_bsp_models_enabled,
            .initial_particles = particles_enabled,
            .scene_pose_control = true,
            .capture_camera_setter = [&](std::optional<SourceCamera> camera) { capture_camera = std::move(camera); },
            .capture_camera_getter = camera_at_pose,
            .fly_mode_setter = std::move(fly_mode_setter),
            .x2_weapon = x2_weapon,
            .full_precision_view = full_precision ? std::function<ViewTransform(std::size_t)>([&](std::size_t pose) {
                return source_view_transform(source_camera_at_pose(pose));
            })
                                                  : nullptr
        }
    );
}

int run_packed_realtime_demo(
    const SourceWorld& world,
    const Bvh& bvh,
    const fs::path& track_path,
    const fs::path& timing_path,
    bool flat,
    RenderMode initial_mode,
    bool initial_legacy_material,
    PlaybackSpeed initial_playback_speed,
    ReferenceInstrumentationConfig instrumentation
)
{
    const auto cameras = load_demo_track(track_path);
    const auto timing = load_demo_timing(timing_path, cameras.size());
    const auto loop_ticks = static_cast<std::uint32_t>(timing.back()) + 1U;
    const double duration_seconds = static_cast<double>(loop_ticks) / kNtscFramesPerSecond;
    return run_live_demo(
        world,
        cameras,
        duration_seconds,
        [&](double seconds) {
            const auto tick = static_cast<std::uint16_t>(
                std::min(loop_ticks - 1U, static_cast<std::uint32_t>(seconds * kNtscFramesPerSecond))
            );
            return demo_pose_at_tick(timing, tick);
        },
        [&](std::size_t pose) { return static_cast<double>(timing.at(pose)) / kNtscFramesPerSecond; },
        [&](std::size_t pose) { return packed_view_transform(world, cameras.at(pose)); },
        [&](std::size_t pose, std::size_t, RenderMode mode, bool legacy_material, bool, bool, bool, bool, bool) {
            const auto frame = render_source_reference(
                world,
                bvh,
                cameras.at(pose),
                flat,
                static_cast<double>(timing.at(pose)) / kNtscFramesPerSecond
            );
            LiveRenderResult result{select_live_indices(frame, mode, legacy_material)};
            result.surface_inspection["liquidLighting"] = liquid_lighting_inspection(frame, mode);
            return result;
        },
        LiveDemoConfiguration{
            .playback_contract = "packed SNES parity | 5-byte poses + NTSC due ticks | no "
                                 "interpolation",
            .initial_mode = initial_mode,
            .initial_legacy_material = initial_legacy_material,
            .initial_playback_speed = initial_playback_speed,
            .playback_speed_control = true,
            .playback_schedule = PlaybackSchedule::NewestDue,
            .initial_presentation_rate_hz = 3,
            .instrumentation_config = std::move(instrumentation),
            .sound_assets = nullptr,
            .initial_sound_enabled = false,
            .initial_sound_volume = 0.7F,
            .legacy_material_control = false,
            .brush_control = false,
            .entity_control = false,
            .external_bsp_model_control = false,
            .initial_brushes = false,
            .initial_entities = false,
            .initial_external_bsp_models = false
        }
    );
}

fs::path with_suffix(const fs::path& prefix, std::string_view suffix)
{
    return fs::path(prefix.string() + std::string(suffix));
}

} // namespace quake_bsp_reference
