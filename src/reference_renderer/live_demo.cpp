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
    ReferenceInstrumentationConfig instrumentation
)
{
    const auto canonical_cameras = load_precise_demo_track(track_path);
    if (canonical_cameras.size() != brush_replay.row_count())
    {
        fail("camera and brush replay row counts disagree");
    }
    const double precise_rate = brush_replay.sample_rate;
    const double duration_seconds = constant_step_duration(canonical_cameras.size(), precise_rate);
    return run_live_demo(
        world,
        canonical_cameras,
        duration_seconds,
        [&](double seconds) { return constant_step_pose_at_time(canonical_cameras.size(), seconds, precise_rate); },
        [precise_rate](std::size_t pose) { return static_cast<double>(pose) / precise_rate; },
        [&](std::size_t pose) { return source_view_transform(canonical_cameras.at(pose)); },
        [&](std::size_t pose,
            RenderMode mode,
            bool legacy_material,
            bool brushes,
            bool entities,
            bool external_models) {
            auto frame = render_source_reference_with_brushes(
                world,
                bvh,
                brush_scene,
                canonical_cameras.at(pose),
                brush_replay,
                pose,
                flat,
                brushes
            );
            ExternalBspCoverage external_coverage;
            if (external_replay != nullptr)
            {
                external_coverage = external_bsp_row_coverage(*external_replay, pose);
                if (external_models)
                {
                    if (external_scene == nullptr)
                    {
                        fail("external BSP playback has no loaded model scene");
                    }
                    compose_source_external_bsp_models(
                        *external_scene,
                        external_replay->row(pose),
                        pose,
                        external_bsp_server_time(*external_replay, pose),
                        flat,
                        source_view_transform(canonical_cameras.at(pose)),
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
            const auto view = source_view_transform(canonical_cameras.at(pose));
            if (mode.textures && !legacy_material)
            {
                const double surface_time =
                    brush_replay.first_server_time + (static_cast<double>(pose) / brush_replay.sample_rate);
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
                compose_alias_billboards(frame, world, view, alias_assets, pose);
            }
            LiveRenderResult result{select_live_indices(frame, mode, legacy_material)};
            result.surface_inspection = std::move(surface_inspection);
            if (external_replay != nullptr)
            {
                result.external_bsp_inspection = external_bsp_inspection(
                    *external_replay,
                    pose,
                    external_models,
                    external_models,
                    external_coverage
                );
            }
            return result;
        },
        LiveDemoConfiguration{
            .playback_contract = "source renderer | configured fixed-rate point samples | Q3 "
                                 "position + u16 angles | no interpolation",
            .initial_mode = initial_mode,
            .initial_legacy_material = initial_legacy_material,
            .initial_playback_speed = initial_playback_speed,
            .playback_speed_control = true,
            .playback_schedule = PlaybackSchedule::NewestDue,
            .initial_presentation_rate_hz = 2,
            .instrumentation_config = std::move(instrumentation),
            .sound_assets = sound_assets,
            .initial_sound_enabled = sound_enabled,
            .initial_sound_volume = sound_volume,
            .legacy_material_control = false,
            .brush_control = true,
            .entity_control = true,
            .external_bsp_model_control = external_replay != nullptr,
            .initial_brushes = brushes_enabled,
            .initial_entities = entities_enabled,
            .initial_external_bsp_models = external_bsp_models_enabled
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
        [&](std::size_t pose, RenderMode mode, bool legacy_material, bool, bool, bool) {
            const auto frame = render_source_reference(world, bvh, cameras.at(pose), flat);
            return LiveRenderResult{select_live_indices(frame, mode, legacy_material)};
        },
        LiveDemoConfiguration{
            .playback_contract = "packed SNES parity | 5-byte poses + NTSC due ticks | no "
                                 "interpolation",
            .initial_mode = initial_mode,
            .initial_legacy_material = initial_legacy_material,
            .initial_playback_speed = initial_playback_speed,
            .playback_speed_control = true,
            .playback_schedule = PlaybackSchedule::NewestDue,
            .initial_presentation_rate_hz = 2,
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
