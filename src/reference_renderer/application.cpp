#include "application.hpp"
#include "world.hpp"
#include "geometry.hpp"
#include "sky.hpp"
#include "brushes.hpp"
#include "audio.hpp"
#include "external_models.hpp"
#include "aliases.hpp"
#include "textured_live.hpp"
#include "live_demo.hpp"
#include "packed_brushes.hpp"
#include "ordered_replay.hpp"
#include "artifacts_options.hpp"
#include "tests_reports.hpp"
#include "report.hpp"
#include "turbulence.hpp"

namespace quake_bsp_reference {

class ReferenceRendererApplication
{
  public:
    explicit ReferenceRendererApplication(const Options& options)
    :
    options_(options),
    load_begin_(std::chrono::steady_clock::now()),
    pak_bytes_(read_file(options.pak)),
    bsp_bytes_(extract_pak_entry(pak_bytes_, options.map_entry)),
    quake_palette_(parse_quake_palette(extract_pak_entry(pak_bytes_, "gfx/palette.lmp"))),
    quake_colormap_(parse_quake_colormap(extract_pak_entry(pak_bytes_, "gfx/colormap.lmp"))),
    bsp_(parse_bsp(bsp_bytes_, quake_palette_, quake_colormap_)),
    world_(build_source_world(bsp_)),
    load_end_(std::chrono::steady_clock::now()),
    build_begin_(std::chrono::steady_clock::now()),
    bvh_(world_.triangles),
    build_end_(std::chrono::steady_clock::now())
    {
    }

    int run()
    {
        if (!options_.realtime_demo_track.empty())
        {
            return run_source_replay();
        }
        if (!options_.packed_realtime_demo_track.empty())
        {
            return run_packed_replay();
        }
        return run_static_render();
    }

  private:
    template <typename Value> static Value& required(std::optional<Value>& value)
    {
        if (!value.has_value())
        {
            fail("reference renderer application state is incomplete");
        }
        return *value;
    }

    template <typename Value> static const Value& required(const std::optional<Value>& value)
    {
        if (!value.has_value())
        {
            fail("reference renderer application state is incomplete");
        }
        return *value;
    }

    struct SourceReplayContext
    {
        BrushReplay brush_replay;
        AliasAssets alias_assets;
        BrushScene brush_scene;
        std::optional<ExternalBspReplay> external_bsp_replay;
        std::optional<ExternalBspScene> external_bsp_scene;
        std::optional<QuakeSoundAssets> sound_assets;
        RenderMode initial_mode;
        bool brushes_enabled{};
        bool entities_enabled{};
    };

    SourceReplayContext load_source_replay() const
    {
        auto brush_replay = load_brush_replay(options_.brush_replay);
        require_brush_camera_identity(brush_replay, options_.realtime_demo_track);
        auto alias_assets = load_alias_assets(options_.alias_assets);
        require_alias_camera_identity(alias_assets, options_.realtime_demo_track);
        if (alias_assets.rows.size() != brush_replay.row_count() + kAliasFlyRowCount)
        {
            fail("camera, brush, and alias replay row counts disagree");
        }
        auto brush_scene = build_brush_scene(bsp_, brush_replay);
        std::optional<ExternalBspReplay> external_bsp_replay;
        std::optional<ExternalBspScene> external_bsp_scene;
        if (!options_.external_bsp_replay.empty())
        {
            external_bsp_replay.emplace(load_external_bsp_replay(options_.external_bsp_replay));
            require_external_bsp_camera_identity(*external_bsp_replay, options_.realtime_demo_track);
            if (external_bsp_replay->row_count() != brush_replay.row_count() ||
                external_bsp_replay->sample_rate != brush_replay.sample_rate)
            {
                fail(
                    "camera, brush, alias, and external BSP replay rows "
                    "disagree"
                );
            }
            external_bsp_scene.emplace(
                build_external_bsp_scene(pak_bytes_, quake_palette_, quake_colormap_, *external_bsp_replay)
            );
        }
        std::optional<QuakeSoundAssets> sound_assets;
        if (!options_.sound_replay.empty())
        {
            sound_assets.emplace(load_quake_sound_assets(
                options_.sound_replay,
                pak_bytes_,
                options_.realtime_demo_track,
                brush_replay.row_count(),
                brush_replay.sample_rate
            ));
        }
        return {
            std::move(brush_replay),
            std::move(alias_assets),
            std::move(brush_scene),
            std::move(external_bsp_replay),
            std::move(external_bsp_scene),
            std::move(sound_assets),
            {!options_.no_textures, options_.lighting},
            !options_.no_brushes,
            !options_.no_entities
        };
    }

    int write_ordered_alias_visibility(const SourceReplayContext& replay) const
    {
        const auto& options = options_;
        const auto& world = world_;
        const auto& brush_replay = replay.brush_replay;
        const auto& alias_assets = replay.alias_assets;
        const bool brushes_enabled = replay.brushes_enabled;
        auto quantized = build_quantized_world(options.data_dir, world);
        const auto ordered = load_ordered_packed_replay(
            options.ordered_replay,
            options.realtime_demo_track,
            options.data_dir,
            quantized
        );
        if (ordered.source_pose_count != brush_replay.row_count() || ordered.source_rate != brush_replay.sample_rate)
        {
            fail(
                "ordered visibility schedule disagrees with brush "
                "replay"
            );
        }
        const auto visibility = build_ordered_alias_visibility(
            quantized,
            ordered,
            load_packed_brush_assets(options.data_dir),
            alias_assets,
            options.data_dir,
            brushes_enabled
        );
        write_file(options.ordered_alias_visibility, visibility);
        std::cout << "aliasVisibilityContract=QAV2"
                  << " aliasVisibilityRows=" << ordered.frames.size()
                  << " aliasVisibilityBytes=" << (read_u32(visibility, 32) + read_u32(visibility, 36))
                  << " aliasVisibilityMaxRecords=" << read_u16(visibility, 22) << " aliasVisibilityMaxMaskBytes="
                  << read_u16(visibility, 24) << " brushes=" << (brushes_enabled ? "enabled" : "disabled")
                  << " output=" << options.ordered_alias_visibility << '\n';
        return 0;
    }

    struct DemoPoseState
    {
        std::size_t pose{};
        ReferenceFrame frame;
        AliasCoverage alias_coverage;
        ExternalBspCoverage external_coverage;
        std::optional<PackedTextureRaster> packed_brush_frame;
        std::optional<PackedTextureRaster> packed_disabled_frame;
        std::optional<PackedTextureRaster> qbsf_authority;
        std::optional<ReferenceFrame> packed_source_authority;
    };

    DemoPoseState render_demo_source(const SourceReplayContext& replay) const
    {
        const auto& options = options_;
        const auto cameras = load_precise_demo_track(options.realtime_demo_track);
        DemoPoseState state;
        state.pose = static_cast<std::size_t>(options.demo_pose);
        if (cameras.size() != replay.brush_replay.row_count())
        {
            fail("camera and brush replay row counts disagree");
        }
        if (state.pose >= cameras.size())
        {
            fail("--demo-pose is outside the canonical replay");
        }
        const auto* external_replay = replay.external_bsp_replay ? &*replay.external_bsp_replay : nullptr;
        const auto* external_scene = replay.external_bsp_scene ? &*replay.external_bsp_scene : nullptr;
        state.frame = render_source_reference_with_aliases(
            world_,
            bvh_,
            replay.brush_scene,
            replay.alias_assets,
            cameras[state.pose],
            replay.brush_replay,
            state.pose,
            options.flat,
            replay.brushes_enabled,
            replay.entities_enabled,
            &state.alias_coverage,
            external_scene,
            external_replay,
            options.external_bsp_models,
            &state.external_coverage
        );
        return state;
    }

    void write_demo_sky(const SourceReplayContext& replay, DemoPoseState& state) const
    {
        if (options_.quake_sky_indices.empty())
        {
            return;
        }
        const auto& options = options_;
        const auto& world = world_;
        const auto& brush_replay = replay.brush_replay;
        const auto& alias_assets = replay.alias_assets;
        const auto* external_replay = replay.external_bsp_replay ? &*replay.external_bsp_replay : nullptr;
        const auto* external_scene = replay.external_bsp_scene ? &*replay.external_bsp_scene : nullptr;
        const auto initial_mode = replay.initial_mode;
        const bool brushes_enabled = replay.brushes_enabled;
        const bool entities_enabled = replay.entities_enabled;
        const auto pose = state.pose;
        auto& external_coverage = state.external_coverage;
        auto quantized = build_quantized_world(options.data_dir, world);
        const auto ordered = load_ordered_packed_replay(
            options.ordered_replay,
            options.realtime_demo_track,
            options.data_dir,
            quantized
        );
        const auto selected =
            std::ranges::find_if(ordered.frames, [&](const auto& candidate) { return candidate.source_pose == pose; });
        if (selected == ordered.frames.end())
        {
            fail("--demo-pose is absent from --ordered-replay");
        }
        const double canonical_surface_time =
            brush_replay.first_server_time + (static_cast<double>(selected->source_pose) / brush_replay.sample_rate);
        const double effective_surface_time =
            options.surface_time_override ? options.surface_time : canonical_surface_time;
        Json surface_inspection;
        const auto presented = render_ordered_packed_indices(
            quantized,
            *selected,
            load_packed_brush_assets(options.data_dir),
            alias_assets,
            options.data_dir,
            initial_mode,
            brushes_enabled,
            entities_enabled,
            nullptr,
            nullptr,
            true,
            effective_surface_time,
            &surface_inspection,
            external_scene,
            external_replay,
            options.external_bsp_models,
            &external_coverage
        );
        surface_inspection["timeSource"] = options.surface_time_override ? "command-line-override" : "demo-server-time";
        surface_inspection["canonicalSurfaceTime"] = canonical_surface_time;
        surface_inspection["surfaceTimeOverride"] = options.surface_time_override;
        surface_inspection["sourcePose"] = selected->source_pose;
        surface_inspection["output"] = Json{
            {"indicesPath", options.quake_sky_indices.string()},
            {"indicesBytes", presented.size()},
            {"logicalWidth", kLogicalWidth},
            {"logicalHeight", kLogicalHeight}
        };
        write_quake_sky_artifacts(options.quake_sky_indices, presented, surface_inspection);
    }

    struct DemoPacketSelection
    {
        Camera camera;
        PacketSelection packet;
        std::optional<OrderedPackedFrame> ordered_frame;
    };

    [[nodiscard]] bool demo_packed_requested() const
    {
        return !options_.packed_brush_albedo_indices.empty() || !options_.packed_brush_lightmap_indices.empty() ||
               !options_.packed_brush_render_indices.empty() || !options_.packed_alias_render_indices.empty();
    }

    [[nodiscard]] bool demo_packed_selection_requested() const
    {
        return !options_.packed_brush_render_indices.empty() || !options_.packed_alias_render_indices.empty();
    }

    DemoPacketSelection select_demo_packet(const SourceWorld& quantized, std::size_t pose) const
    {
        DemoPacketSelection selection{options_.camera, {}, std::nullopt};
        if (options_.ordered_replay.empty())
        {
            selection.packet = load_packet_selection(options_.packet_source_faces, quantized);
            return selection;
        }
        const auto ordered = load_ordered_packed_replay(
            options_.ordered_replay,
            options_.realtime_demo_track,
            options_.data_dir,
            quantized
        );
        const auto selected =
            std::ranges::find_if(ordered.frames, [&](const auto& candidate) { return candidate.source_pose == pose; });
        if (selected == ordered.frames.end())
        {
            fail("--demo-pose is absent from --ordered-replay");
        }
        selection.camera = selected->camera;
        selection.packet = selected->packet;
        selection.ordered_frame = *selected;
        return selection;
    }

    void render_demo_packed_frames(
        const SourceReplayContext& replay,
        DemoPoseState& state,
        SourceWorld quantized,
        const DemoPacketSelection& selection
    ) const
    {
        const double server_time =
            replay.brush_replay.first_server_time + (static_cast<double>(state.pose) / replay.brush_replay.sample_rate);
        state.packed_source_authority.emplace(render_packed_camera_source_reference_with_brushes(
            world_,
            bvh_,
            replay.brush_scene,
            selection.camera,
            replay.brush_replay.row(state.pose),
            state.pose,
            server_time,
            options_.flat
        ));
        auto brush_assets = load_packed_brush_assets(options_.data_dir);
        const auto visual_state = packed_brush_visual_state_at_pose(brush_assets, state.pose);
        state.qbsf_authority.emplace(render_direct_qbsf_brush_authority(
            quantized,
            selection.packet,
            selection.camera,
            visual_state,
            options_.data_dir,
            brush_assets
        ));
        state.packed_brush_frame.emplace(render_packed_brush_pipeline(
            std::move(quantized),
            selection.packet,
            selection.camera,
            visual_state,
            options_.data_dir,
            std::move(brush_assets),
            TextureRasterMode::projective_block8,
            server_time
        ));
        if (demo_packed_selection_requested() && !replay.brushes_enabled)
        {
            auto disabled_world = build_quantized_world(options_.data_dir, world_);
            state.packed_disabled_frame.emplace(render_packed_texture_pipeline(
                disabled_world,
                selection.packet,
                selection.camera,
                TextureRasterMode::projective_block8,
                server_time
            ));
        }
    }

    [[nodiscard]] static const PackedTextureRaster&
    selected_demo_packed_frame(const SourceReplayContext& replay, const DemoPoseState& state)
    {
        if (!replay.brushes_enabled)
        {
            return required(state.packed_disabled_frame);
        }
        return required(state.packed_brush_frame);
    }

    void write_demo_packed_planes(const SourceReplayContext& replay, const DemoPoseState& state) const
    {
        if (!options_.packed_brush_albedo_indices.empty())
        {
            write_file(options_.packed_brush_albedo_indices, required(state.packed_brush_frame).indices);
        }
        if (!options_.packed_brush_lightmap_indices.empty())
        {
            write_file(options_.packed_brush_lightmap_indices, required(state.packed_brush_frame).lightmapped_indices);
        }
        if (!options_.packed_brush_render_indices.empty())
        {
            const auto& selected_frame = selected_demo_packed_frame(replay, state);
            write_file(
                options_.packed_brush_render_indices,
                selected_render_indices(selected_frame, replay.initial_mode)
            );
        }
    }

    void write_demo_packed_aliases(
        const SourceReplayContext& replay,
        DemoPoseState& state,
        const DemoPacketSelection& selection
    ) const
    {
        if (options_.packed_alias_render_indices.empty())
        {
            return;
        }
        std::vector<std::uint8_t> composed;
        if (selection.ordered_frame.has_value())
        {
            const auto* external_replay = replay.external_bsp_replay ? &*replay.external_bsp_replay : nullptr;
            const auto* external_scene = replay.external_bsp_scene ? &*replay.external_bsp_scene : nullptr;
            composed = render_ordered_packed_indices(
                build_quantized_world(options_.data_dir, world_),
                *selection.ordered_frame,
                load_packed_brush_assets(options_.data_dir),
                replay.alias_assets,
                options_.data_dir,
                replay.initial_mode,
                replay.brushes_enabled,
                replay.entities_enabled,
                &state.alias_coverage,
                nullptr,
                false,
                0.0,
                nullptr,
                external_scene,
                external_replay,
                options_.external_bsp_models,
                &state.external_coverage
            );
        }
        else
        {
            const auto& selected_frame = selected_demo_packed_frame(replay, state);
            const auto& opaque = selected_render_indices(selected_frame, replay.initial_mode);
            composed =
                replay.entities_enabled
                    ? compose_post_opaque_alias_indices(
                          opaque,
                          selected_frame.depth_q6,
                          selection.camera,
                          replay.alias_assets,
                          state.pose,
                          replay.initial_mode,
                          &state.alias_coverage
                      )
                    : std::vector<std::uint8_t>(opaque.begin(), opaque.end());
        }
        write_file(options_.packed_alias_render_indices, composed);
    }

    void render_demo_packed(const SourceReplayContext& replay, DemoPoseState& state) const
    {
        if (!demo_packed_requested())
        {
            return;
        }
        auto quantized = build_quantized_world(options_.data_dir, world_);
        const auto selection = select_demo_packet(quantized, state.pose);
        render_demo_packed_frames(replay, state, std::move(quantized), selection);
        write_demo_packed_planes(replay, state);
        write_demo_packed_aliases(replay, state, selection);
    }

    void write_demo_outputs(const SourceReplayContext& replay, const DemoPoseState& state) const
    {
        const auto& options = options_;
        const auto& world = world_;
        const auto initial_mode = replay.initial_mode;
        const auto& frame = state.frame;
        const auto& packed_brush_frame = state.packed_brush_frame;
        const auto& packed_disabled_frame = state.packed_disabled_frame;
        const auto& qbsf_authority = state.qbsf_authority;
        const auto& packed_source_authority = state.packed_source_authority;
        if (!options.brush_albedo_indices.empty())
        {
            write_file(options.brush_albedo_indices, frame.texture_indices);
        }
        if (!options.brush_lightmap_indices.empty())
        {
            write_file(options.brush_lightmap_indices, frame.lightmap_texture_indices);
        }
        if (!options.brush_render_indices.empty())
        {
            write_file(options.brush_render_indices, selected_render_indices(frame, initial_mode));
        }
        if (!options.report_only)
        {
            write_reference_outputs(options.output_prefix, frame, world);
            write_brush_ownership_outputs(options.output_prefix, frame);
            if (packed_brush_frame.has_value())
            {
                write_packed_brush_outputs(
                    with_suffix(options.output_prefix, ".packed-brush"),
                    *packed_brush_frame,
                    world
                );
                if (packed_disabled_frame.has_value())
                {
                    write_packed_texture_outputs(
                        with_suffix(options.output_prefix, ".packed-selected-world"),
                        *packed_disabled_frame,
                        world
                    );
                }
                write_packed_brush_outputs(
                    with_suffix(options.output_prefix, ".qbsf-authority"),
                    *qbsf_authority,
                    world
                );
                write_reference_outputs(
                    with_suffix(options.output_prefix, ".packed-source"),
                    *packed_source_authority,
                    world
                );
                write_brush_ownership_outputs(
                    with_suffix(options.output_prefix, ".packed-source"),
                    *packed_source_authority
                );
            }
        }
    }

    void print_demo_header(const SourceReplayContext& replay, const DemoPoseState& state) const
    {
        const auto& alias = state.alias_coverage;
        const auto& external = state.external_coverage;
        std::cout
            << "demo-pose=" << state.pose << " brushes=" << (replay.brushes_enabled ? "enabled" : "disabled")
            << " entities=" << (replay.entities_enabled ? "enabled" : "disabled")
            << " aliasContract=opaque-depth-clipped-v2"
            << " renderMode=" << render_mode_name(replay.initial_mode)
            << " technique=" << render_mode_technique(replay.initial_mode)
            << " renderContract=" << packed_render_contract(replay.initial_mode, replay.brushes_enabled)
            << " hits=" << state.frame.hits << " misses=" << state.frame.misses << " aliasTokens=" << alias.tokens
            << " aliasProjected=" << alias.projected << " aliasClipped=" << alias.clipped
            << " aliasModelMask=" << alias.model_mask << " aliasMinArea=" << alias.minimum_projected_area
            << " aliasMaxArea=" << alias.maximum_projected_area << " aliasPlotPixels=" << alias.packed_plot_pixels
            << " aliasVisiblePixels=" << alias.packed_visible_pixels << " aliasOpaqueOccludedPixels="
            << alias.packed_opaque_occluded_pixels << " idealAliasCandidates=" << alias.ideal_candidate_pixels
            << " idealAliasOpaqueOccluded=" << alias.ideal_opaque_occluded_pixels
            << " externalBspModels=" << (options_.external_bsp_models ? "enabled" : "disabled")
            << " externalBspActiveEntities=" << external.active_entities << " externalBspActiveModels="
            << external.active_models << " externalBspCandidatePixels=" << external.candidate_pixels
            << " externalBspVisiblePixels=" << external.visible_pixels << " externalBspVisibleEntities="
            << external.visible_entities << " externalBspVisibleModels=" << external.visible_models << " aliasRecords=";
        for (std::size_t index = 0; index < alias.records.size(); ++index)
        {
            if (index != 0)
            {
                std::cout << ';';
            }
            const auto& record = alias.records[index];
            std::cout << record.token << ',' << static_cast<int>(record.sprite) << ',' << record.is_static << ','
                      << static_cast<int>(record.state) << ',' << record.first_x << ',' << record.first_y << ','
                      << record.last_x << ',' << record.last_y << ',' << record.plot_pixels << ','
                      << record.visible_pixels << ',' << record.opaque_occluded_pixels;
        }
    }

    struct DemoPackedComparison
    {
        std::size_t owner_mismatches{};
        int first_owner_mismatch{-1};
        std::size_t dynamic_mismatches{};
        int first_dynamic_mismatch{-1};
        std::size_t source_dynamic_mismatches{};
        std::size_t source_boundary_mismatches{};
        std::size_t source_interior_mismatches{};
        int first_source_dynamic_mismatch{-1};
    };

    template <typename Left, typename Right>
    static bool dynamic_owner_equal(const Left& left, const Right& right, std::size_t pixel)
    {
        const bool left_dynamic = left.models[pixel] != 0;
        const bool right_dynamic = right.models[pixel] != 0;
        return left_dynamic == right_dynamic &&
               (!left_dynamic ||
                (left.faces[pixel] == right.faces[pixel] && left.entities[pixel] == right.entities[pixel] &&
                 left.models[pixel] == right.models[pixel]));
    }

    template <typename Frame>
    static bool dynamic_owner_edge(const Frame& frame, std::size_t pixel, std::size_t neighbor)
    {
        return frame.models[pixel] != frame.models[neighbor] ||
               (frame.models[pixel] != 0 &&
                (frame.faces[pixel] != frame.faces[neighbor] || frame.entities[pixel] != frame.entities[neighbor]));
    }

    static bool
    source_dynamic_boundary(const ReferenceFrame& source, const PackedTextureRaster& packed, std::size_t pixel)
    {
        const int origin_x = static_cast<int>(pixel % kLogicalWidth);
        const int origin_y = static_cast<int>(pixel / kLogicalWidth);
        for (int delta_y = -1; delta_y <= 1; ++delta_y)
        {
            for (int delta_x = -1; delta_x <= 1; ++delta_x)
            {
                const int neighbor_x = origin_x + delta_x;
                const int neighbor_y = origin_y + delta_y;
                if ((delta_x == 0 && delta_y == 0) || neighbor_x < 0 || neighbor_x >= kLogicalWidth || neighbor_y < 0 ||
                    neighbor_y >= kLogicalHeight)
                {
                    continue;
                }
                const auto neighbor =
                    (static_cast<std::size_t>(neighbor_y) * kLogicalWidth) + static_cast<std::size_t>(neighbor_x);
                if (dynamic_owner_edge(source, pixel, neighbor) || dynamic_owner_edge(packed, pixel, neighbor))
                {
                    return true;
                }
            }
        }
        return false;
    }

    static DemoPackedComparison compare_demo_packed_frames(
        const PackedTextureRaster& authority,
        const ReferenceFrame& source,
        const PackedTextureRaster& packed
    )
    {
        DemoPackedComparison comparison;
        for (std::size_t pixel = 0; pixel < kLogicalPixels; ++pixel)
        {
            const bool owner_mismatch =
                authority.faces[pixel] != packed.faces[pixel] || authority.entities[pixel] != packed.entities[pixel] ||
                authority.models[pixel] != packed.models[pixel];
            comparison.owner_mismatches += static_cast<std::size_t>(owner_mismatch);
            if (owner_mismatch && comparison.first_owner_mismatch < 0)
            {
                comparison.first_owner_mismatch = static_cast<int>(pixel);
            }
            const bool dynamic_mismatch = !dynamic_owner_equal(authority, packed, pixel);
            comparison.dynamic_mismatches += static_cast<std::size_t>(dynamic_mismatch);
            if (dynamic_mismatch && comparison.first_dynamic_mismatch < 0)
            {
                comparison.first_dynamic_mismatch = static_cast<int>(pixel);
            }
            if (dynamic_owner_equal(source, packed, pixel))
            {
                continue;
            }
            ++comparison.source_dynamic_mismatches;
            if (comparison.first_source_dynamic_mismatch < 0)
            {
                comparison.first_source_dynamic_mismatch = static_cast<int>(pixel);
            }
            const bool boundary = source_dynamic_boundary(source, packed, pixel);
            comparison.source_boundary_mismatches += static_cast<std::size_t>(boundary);
            comparison.source_interior_mismatches += static_cast<std::size_t>(!boundary);
        }
        return comparison;
    }

    static void
    print_demo_packed_records(const PackedBrushGroupBounds& group_bounds, const PackedBrushOrderingAnalysis& ordering)
    {
        std::cout << " packedBrushGroupRecords=";
        for (std::size_t index = 0; index < group_bounds.records.size(); ++index)
        {
            if (index != 0)
            {
                std::cout << ';';
            }
            const auto& record = group_bounds.records[index];
            std::cout << record.leaf << ',' << record.admitted_fragments << ',' << record.projected_vertices << ','
                      << record.scan_rows << ',' << record.spans << ',' << record.max_row_candidates << ','
                      << record.max_pixel_candidates;
        }
        std::cout << " packedBrushOrderingRecords=";
        for (std::size_t index = 0; index < ordering.records.size(); ++index)
        {
            if (index != 0)
            {
                std::cout << ';';
            }
            const auto& record = ordering.records[index];
            std::cout << record.leaf << ',' << record.overlap_pixels << ',' << record.winner_cycle << ','
                      << record.pairwise_cycle << ',' << record.centroid_mismatch_pixels;
        }
    }

    static void print_demo_packed_summary(const DemoPoseState& state)
    {
        const auto& authority = required(state.qbsf_authority);
        const auto& source = required(state.packed_source_authority);
        const auto& packed = required(state.packed_brush_frame);
        const auto group_bounds = packed_brush_group_bounds(packed);
        const auto ordering = packed_brush_ordering_analysis(packed, group_bounds);
        const auto comparison = compare_demo_packed_frames(authority, source, packed);
        std::cout
            << " packedBrushHits=" << packed.hits << " packedBrushMisses=" << packed.misses
            << " packedBrushOwnerMismatches=" << comparison.owner_mismatches << " packedBrushOwnerFirstMismatch="
            << comparison.first_owner_mismatch << " packedBrushDynamicMismatches=" << comparison.dynamic_mismatches
            << " packedBrushDynamicFirstMismatch=" << comparison.first_dynamic_mismatch
            << " sourceBrushDynamicMismatches=" << comparison.source_dynamic_mismatches
            << " sourceBrushDynamicFirstMismatch=" << comparison.first_source_dynamic_mismatch
            << " sourceBrushBoundaryMismatches=" << comparison.source_boundary_mismatches
            << " sourceBrushInteriorMismatches=" << comparison.source_interior_mismatches << " packedBrushGroups="
            << group_bounds.groups << " packedBrushMaxGroupFragments=" << group_bounds.max_admitted_fragments
            << " packedBrushMaxGroupFragmentsLeaf=" << group_bounds.admitted_group
            << " packedBrushMaxGroupVertices=" << group_bounds.max_projected_vertices
            << " packedBrushMaxGroupVerticesLeaf=" << group_bounds.projected_group << " packedBrushMaxGroupRows="
            << group_bounds.max_scan_rows << " packedBrushMaxGroupRowsLeaf=" << group_bounds.scan_rows_group
            << " packedBrushMaxRowCandidates=" << group_bounds.max_row_candidates << " packedBrushMaxRowCandidatesLeaf="
            << group_bounds.row_group << " packedBrushMaxRowCandidatesY=" << group_bounds.row
            << " packedBrushMaxPixelCandidates=" << group_bounds.max_pixel_candidates
            << " packedBrushMaxPixelCandidatesLeaf=" << group_bounds.pixel_group
            << " packedBrushMaxPixelCandidatesPixel=" << group_bounds.pixel << " packedBrushOrderingGroups="
            << ordering.groups << " packedBrushOverlapGroups=" << ordering.overlap_groups
            << " packedBrushWinnerCycleGroups=" << ordering.winner_cycle_groups
            << " packedBrushPairwiseCycleGroups=" << ordering.pairwise_cycle_groups
            << " packedBrushCentroidMismatchGroups=" << ordering.centroid_mismatch_groups
            << " packedBrushCentroidMismatchPixels=" << ordering.centroid_mismatch_pixels;
        print_demo_packed_records(group_bounds, ordering);
    }

    void print_demo_summary(const SourceReplayContext& replay, const DemoPoseState& state) const
    {
        print_demo_header(replay, state);
        if (state.packed_brush_frame.has_value())
        {
            print_demo_packed_summary(state);
        }
        std::cout << '\n';
    }

    int run_demo_pose(const SourceReplayContext& replay) const
    {
        auto state = render_demo_source(replay);
        write_demo_sky(replay, state);
        render_demo_packed(replay, state);
        write_demo_outputs(replay, state);
        print_demo_summary(replay, state);
        return 0;
    }

    int run_live_source_replay(const SourceReplayContext& replay) const
    {
        const auto& options = options_;
        const auto& world = world_;
        const auto& bvh = bvh_;
        const auto& brush_replay = replay.brush_replay;
        const auto& alias_assets = replay.alias_assets;
        const auto& brush_scene = replay.brush_scene;
        const auto* external_replay = replay.external_bsp_replay ? &*replay.external_bsp_replay : nullptr;
        const auto* external_scene = replay.external_bsp_scene ? &*replay.external_bsp_scene : nullptr;
        const auto* sound_assets = replay.sound_assets ? &*replay.sound_assets : nullptr;
        const auto initial_mode = replay.initial_mode;
        const bool brushes_enabled = replay.brushes_enabled;
        const bool entities_enabled = replay.entities_enabled;
        return run_realtime_demo(
            world,
            bvh,
            brush_scene,
            brush_replay,
            alias_assets,
            options.realtime_demo_track,
            options.data_dir,
            options.ordered_replay,
            options.flat,
            initial_mode,
            options.material_view,
            options.playback_speed,
            options.ordered_2hz,
            options.ordered_fast,
            options.ordered_presentation_hz,
            {options.instrumentation_session, options.instrumentation_pipe},
            brushes_enabled,
            entities_enabled,
            external_scene,
            external_replay,
            options.external_bsp_models,
            sound_assets,
            !options.no_sound,
            options.volume
        );
    }

    int run_source_replay()
    {
        const auto replay = load_source_replay();
        if (!options_.ordered_alias_visibility.empty())
        {
            return write_ordered_alias_visibility(replay);
        }
        if (options_.demo_pose >= 0)
        {
            return run_demo_pose(replay);
        }
        return run_live_source_replay(replay);
    }

    int run_packed_replay()
    {
        const auto& options = options_;
        const auto& world = world_;
        const auto& bvh = bvh_;
        return run_packed_realtime_demo(
            world,
            bvh,
            options.packed_realtime_demo_track,
            options.realtime_demo_timing,
            options.flat,
            {!options.no_textures, options.lighting},
            options.material_view,
            options.playback_speed,
            {options.instrumentation_session, options.instrumentation_pipe}
        );
    }

    struct StaticRenderState
    {
        std::optional<SourceWorld> quantized_world;
        std::optional<Bvh> quantized_bvh;
        std::optional<PacketSelection> packet_selection;
        std::optional<Bvh> packet_bvh;
        std::chrono::steady_clock::time_point render_begin;
        ReferenceFrame frame;
        std::chrono::steady_clock::time_point render_end;
        std::optional<ReferenceFrame> quantized_frame;
        std::optional<ReferenceFrame> packet_nearest_frame;
        std::optional<ReferenceFrame> packet_painter_frame;
        std::optional<RasterLayers> raster_layers;
        std::optional<PackedTextureRaster> packed_affine_texture_raster;
        std::optional<PackedTextureRaster> packed_projective_texture_raster;
        std::optional<TextureMappingFidelity> affine_texture_mapping_fidelity;
        std::optional<TextureMappingFidelity> projective_texture_mapping_fidelity;
        std::optional<AliasCoverage> fly_alias_coverage;
        std::size_t fly_alias_row{};
        std::optional<PackedAudit> audit;
        std::optional<Comparison> comparison;
        std::optional<PackedTextureComparison> packed_texture_comparison;
    };

    void prepare_static_render(StaticRenderState& state) const
    {
        const auto& options = options_;
        const auto& world = world_;
        const auto& bvh = bvh_;
        auto& quantized_world = state.quantized_world;
        auto& quantized_bvh = state.quantized_bvh;
        auto& packet_selection = state.packet_selection;
        auto& packet_bvh = state.packet_bvh;
        auto& render_begin = state.render_begin;
        auto& frame = state.frame;
        auto& render_end = state.render_end;
        if (!options.data_dir.empty())
        {
            quantized_world.emplace(build_quantized_world(options.data_dir, world));
            quantized_bvh.emplace(quantized_world->triangles);
            if (!options.packet_source_faces.empty())
            {
                packet_selection.emplace(load_packet_selection(options.packet_source_faces, *quantized_world));
                packet_bvh.emplace(packet_selection->triangles);
            }
        }

        render_begin = std::chrono::steady_clock::now();
        frame = render_source_reference(world, bvh, options.camera, options.flat);
        render_end = std::chrono::steady_clock::now();
        if (!options.report_only)
        {
            write_reference_outputs(options.output_prefix, frame, world);
        }
    }

    [[nodiscard]] RenderMode static_render_mode() const
    {
        return {!options_.no_textures, options_.lighting};
    }

    void render_static_quantized_reference(StaticRenderState& state) const
    {
        if (!state.quantized_world.has_value() || !state.quantized_bvh.has_value())
        {
            return;
        }
        state.quantized_frame.emplace(render_material_reference(
            required(state.quantized_world),
            required(state.quantized_bvh),
            options_.camera,
            options_.flat
        ));
        if (!options_.report_only)
        {
            write_reference_outputs(
                with_suffix(options_.output_prefix, ".quantized"),
                required(state.quantized_frame),
                required(state.quantized_world)
            );
        }
    }

    void write_static_packet_reference_outputs(const StaticRenderState& state) const
    {
        if (options_.report_only)
        {
            return;
        }
        write_reference_outputs(
            with_suffix(options_.output_prefix, ".packet-nearest"),
            required(state.packet_nearest_frame),
            required(state.quantized_world)
        );
        write_reference_outputs(
            with_suffix(options_.output_prefix, ".packet-painter"),
            required(state.packet_painter_frame),
            required(state.quantized_world)
        );
        write_owner_diff(
            with_suffix(options_.output_prefix, ".packet-nearest.owner-diff.bmp"),
            required(state.quantized_frame),
            required(state.packet_nearest_frame),
            required(state.quantized_world).live_material_palette
        );
        write_owner_diff(
            with_suffix(options_.output_prefix, ".packet-painter.owner-diff.bmp"),
            required(state.packet_nearest_frame),
            required(state.packet_painter_frame),
            required(state.quantized_world).live_material_palette
        );
    }

    void render_static_packet_references(StaticRenderState& state) const
    {
        state.packet_nearest_frame.emplace(render_material_reference(
            required(state.quantized_world),
            required(state.packet_bvh),
            options_.camera,
            options_.flat,
            required(state.packet_selection).selected_faces
        ));
        state.packet_painter_frame.emplace(render_material_reference(
            required(state.quantized_world),
            required(state.packet_bvh),
            options_.camera,
            options_.flat,
            required(state.packet_selection).selected_faces,
            required(state.packet_selection).painter_ranks
        ));
        write_static_packet_reference_outputs(state);
        state.raster_layers.emplace(
            RasterLayers{
                render_current_pipeline(
                    required(state.quantized_world),
                    required(state.packet_selection),
                    options_.camera,
                    options_.flat,
                    0,
                    true
                ),
                render_current_pipeline(
                    required(state.quantized_world),
                    required(state.packet_selection),
                    options_.camera,
                    options_.flat,
                    7,
                    true
                ),
                render_convex_counterfactual(
                    required(state.quantized_world),
                    required(state.packet_selection),
                    options_.camera,
                    options_.flat,
                    false
                ),
                render_convex_counterfactual(
                    required(state.quantized_world),
                    required(state.packet_selection),
                    options_.camera,
                    options_.flat,
                    true
                ),
            }
        );
    }

    [[nodiscard]] bool needs_static_affine_raster() const
    {
        return !options_.report_only || !options_.snes_texture_indices.empty();
    }

    [[nodiscard]] bool needs_static_projective_raster() const
    {
        return !options_.report_only || !options_.packed_albedo_indices.empty() ||
               !options_.packed_lightmap_indices.empty() || !options_.packed_lightmap_levels.empty() ||
               !options_.packed_render_indices.empty() || !options_.fly_alias_render_indices.empty();
    }

    void render_static_packed_textures(StaticRenderState& state) const
    {
        const auto render_selected_texture = [&](TextureRasterMode raster_mode) {
            if (!options_.fly_alias_render_indices.empty())
            {
                auto brush_assets = load_packed_brush_assets(options_.data_dir);
                const auto source_pose = static_cast<std::size_t>(options_.fly_source_pose);
                auto visual_state = packed_brush_visual_state_at_pose(brush_assets, source_pose);
                const auto fly = std::ranges::find(brush_assets.sections, "FLYSTATE", &PackedBrushSection::name);
                if (fly == brush_assets.sections.end() || fly->record_bytes != 2 ||
                    visual_state > fly->record_count ||
                    fly->bytes.size() != static_cast<std::size_t>(fly->record_count) * 2)
                {
                    fail("QBSA FLYSTATE cannot complete the requested frozen state");
                }
                visual_state = read_u16(fly->bytes, (visual_state - 1) * 2);
                return render_packed_brush_pipeline(
                    required(state.quantized_world),
                    required(state.packet_selection),
                    options_.camera,
                    visual_state,
                    options_.data_dir,
                    std::move(brush_assets),
                    raster_mode,
                    options_.surface_time,
                    true,
                    source_pose,
                    !options_.no_brushes
                );
            }
            return render_packed_texture_pipeline(
                required(state.quantized_world),
                required(state.packet_selection),
                options_.camera,
                raster_mode,
                options_.surface_time
            );
        };
        if (needs_static_affine_raster())
        {
            state.packed_affine_texture_raster.emplace(render_selected_texture(TextureRasterMode::affine));
            state.affine_texture_mapping_fidelity.emplace(
                compare_texture_mapping_fidelity(world_, state.frame, required(state.packed_affine_texture_raster))
            );
        }
        if (needs_static_projective_raster())
        {
            state.packed_projective_texture_raster.emplace(
                render_selected_texture(TextureRasterMode::projective_block8)
            );
            state.projective_texture_mapping_fidelity.emplace(
                compare_texture_mapping_fidelity(world_, state.frame, required(state.packed_projective_texture_raster))
            );
        }
    }

    [[nodiscard]] static const PackedTextureRaster&
    selected_static_packed_frame(const StaticRenderState& state)
    {
        return required(state.packed_projective_texture_raster);
    }

    void write_static_packed_planes(const StaticRenderState& state, RenderMode mode) const
    {
        if (!options_.packed_albedo_indices.empty())
        {
            write_file(options_.packed_albedo_indices, required(state.packed_projective_texture_raster).indices);
        }
        if (!options_.packed_lightmap_indices.empty())
        {
            write_file(
                options_.packed_lightmap_indices,
                required(state.packed_projective_texture_raster).lightmapped_indices
            );
        }
        if (!options_.packed_lightmap_levels.empty())
        {
            write_file(
                options_.packed_lightmap_levels,
                required(state.packed_projective_texture_raster).lightmap_levels
            );
        }
        if (options_.packed_render_indices.empty())
        {
            return;
        }
        const auto& selected_frame = selected_static_packed_frame(state);
        write_file(options_.packed_render_indices, selected_render_indices(selected_frame, mode));
    }

    void write_static_fly_sky(
        const StaticRenderState& state,
        const PackedTextureRaster& selected_frame,
        std::span<const std::uint8_t> opaque,
        const AliasAssets& alias_assets,
        std::span<const std::uint8_t> composed,
        RenderMode mode
    ) const
    {
        if (options_.quake_sky_indices.empty())
        {
            return;
        }
        auto sky = render_quake_sky_presentation(
            opaque,
            selected_frame.faces,
            selected_frame.entities,
            required(state.quantized_world),
            packed_view_transform(required(state.quantized_world), options_.camera),
            options_.surface_time,
            "command-line-override"
        );
        sky.inspection["turbulence"] = quake_turbulence_inspection(selected_frame);
        const auto presented = options_.no_entities
                                   ? sky.indices
                                   : compose_post_opaque_alias_indices(
                                         sky.indices,
                                         selected_frame.depth_q6,
                                         options_.camera,
                                         alias_assets,
                                         state.fly_alias_row,
                                         mode,
                                         nullptr,
                                         nullptr
                                     );
        sky.inspection["playbackMode"] = "static-fly";
        sky.inspection["surfaceTimeOverride"] = true;
        sky.inspection["camera"] = Json{
            {"x", options_.camera.x},
            {"y", options_.camera.y},
            {"z", options_.camera.z},
            {"yaw", options_.camera.yaw},
            {"pitch", options_.camera.pitch}
        };
        sky.inspection["ownerPlane"] = "post-opaque-world-brush-face-entity";
        sky.inspection["compositionOrder"] = Json::array({"opaque-world-brush", "quake-sky", "post-opaque-aliases"});
        sky.inspection["rawOutput"] = Json{
            {"indicesPath", options_.fly_alias_render_indices.string()},
            {"indicesBytes", composed.size()},
            {"logicalWidth", kLogicalWidth},
            {"logicalHeight", kLogicalHeight}
        };
        sky.inspection["output"] = Json{
            {"indicesPath", options_.quake_sky_indices.string()},
            {"indicesBytes", presented.size()},
            {"logicalWidth", kLogicalWidth},
            {"logicalHeight", kLogicalHeight}
        };
        write_quake_sky_artifacts(options_.quake_sky_indices, presented, sky.inspection);
        std::cout << "fly-sky=PASS contract=winquake-software-sky-v1"
                  << " surfaceTime=" << options_.surface_time << " output=" << options_.quake_sky_indices << '\n';
    }

    void render_static_fly_alias(StaticRenderState& state, RenderMode mode) const
    {
        if (options_.fly_alias_render_indices.empty())
        {
            return;
        }
        const auto& selected_frame = selected_static_packed_frame(state);
        const auto opaque = selected_render_indices(selected_frame, mode);
        auto alias_assets = load_alias_assets(options_.alias_assets);
        alias_assets.rotation_yaw_q8 = static_cast<std::uint8_t>(options_.alias_yaw_q8);
        state.fly_alias_row = alias_fly_row(alias_assets, options_.camera);
        if (options_.no_entities)
        {
            write_file(options_.fly_alias_render_indices, opaque);
            write_static_fly_sky(state, selected_frame, opaque, alias_assets, opaque, mode);
            return;
        }
        state.fly_alias_coverage.emplace();
        const auto composed = compose_post_opaque_alias_indices(
            opaque,
            selected_frame.depth_q6,
            options_.camera,
            alias_assets,
            state.fly_alias_row,
            mode,
            &required(state.fly_alias_coverage),
            nullptr
        );
        write_file(options_.fly_alias_render_indices, composed);
        write_static_fly_sky(state, selected_frame, opaque, alias_assets, composed, mode);
    }

    void write_static_raster_diagnostics(const StaticRenderState& state) const
    {
        if (options_.report_only)
        {
            return;
        }
        const auto write_raster_layer = [&](std::string_view suffix, const RasterResult& layer) {
            write_raster_outputs(with_suffix(options_.output_prefix, suffix), layer, required(state.quantized_world));
        };
        write_raster_layer(".current-pipeline", required(state.raster_layers).current_pipeline);
        write_raster_layer(".legacy-widened-fan", required(state.raster_layers).legacy_widened_fan);
        write_raster_layer(".convex-painter", required(state.raster_layers).convex_painter);
        write_raster_layer(".front-to-back-uncovered", required(state.raster_layers).front_to_back_uncovered);
        write_packed_texture_outputs(
            with_suffix(options_.output_prefix, ".packed-affine"),
            required(state.packed_affine_texture_raster),
            required(state.quantized_world)
        );
        write_packed_texture_outputs(
            with_suffix(options_.output_prefix, ".packed-projective"),
            required(state.packed_projective_texture_raster),
            required(state.quantized_world)
        );
        write_owner_diff(
            with_suffix(options_.output_prefix, ".current-pipeline.owner-diff.bmp"),
            required(state.packet_painter_frame),
            required(state.raster_layers).current_pipeline.frame,
            required(state.quantized_world).live_material_palette
        );
        write_owner_diff(
            with_suffix(options_.output_prefix, ".legacy-widened-fan.owner-diff.bmp"),
            required(state.raster_layers).current_pipeline.frame,
            required(state.raster_layers).legacy_widened_fan.frame,
            required(state.quantized_world).live_material_palette
        );
        write_owner_diff(
            with_suffix(options_.output_prefix, ".convex-painter.owner-diff.bmp"),
            required(state.raster_layers).current_pipeline.frame,
            required(state.raster_layers).convex_painter.frame,
            required(state.quantized_world).live_material_palette
        );
        write_owner_diff(
            with_suffix(options_.output_prefix, ".front-to-back-uncovered.owner-diff.bmp"),
            required(state.raster_layers).convex_painter.frame,
            required(state.raster_layers).front_to_back_uncovered.frame,
            required(state.quantized_world).live_material_palette
        );
    }

    void render_static_layers(StaticRenderState& state) const
    {
        render_static_quantized_reference(state);
        if (!state.packet_selection.has_value() || !state.packet_bvh.has_value())
        {
            return;
        }
        render_static_packet_references(state);
        const auto mode = static_render_mode();
        render_static_packed_textures(state);
        write_static_packed_planes(state, mode);
        render_static_fly_alias(state, mode);
        write_static_raster_diagnostics(state);
    }

    void compare_static_outputs(StaticRenderState& state) const
    {
        const auto& options = options_;
        const auto& world = world_;
        const auto& frame = state.frame;
        const auto& packed_affine_texture_raster = state.packed_affine_texture_raster;
        auto& audit = state.audit;
        auto& comparison = state.comparison;
        auto& packed_texture_comparison = state.packed_texture_comparison;
        if (!options.data_dir.empty())
        {
            audit = audit_packed_colors(options.data_dir, world);
        }
        if (!options.snes_frame.empty())
        {
            const auto snes = load_snes_frame(options.snes_frame, world.live_material_palette);
            if (!options.report_only)
            {
                write_file(with_suffix(options.output_prefix, ".snes.idx"), snes.logical);
            }
            comparison = compare_frames(frame, snes, options.allowed_holes);
            if (!options.report_only)
            {
                write_diff(
                    with_suffix(options.output_prefix, ".material.diff.bmp"),
                    frame,
                    snes,
                    world.live_material_palette
                );
            }
        }
        if (!options.snes_texture_indices.empty())
        {
            if (!packed_affine_texture_raster.has_value())
            {
                fail(
                    "SNES texture comparison requires data-dir and packet "
                    "source faces"
                );
            }
            const auto snes_indices = read_file(options.snes_texture_indices);
            packed_texture_comparison = compare_packed_texture_indices(*packed_affine_texture_raster, snes_indices);
            if (!options.report_only)
            {
                write_file(with_suffix(options.output_prefix, ".snes-texture.idx"), snes_indices);
            }
        }
    }

    [[nodiscard]] bool static_render_passed(const StaticRenderState& state) const
    {
        const auto& world = world_;
        const auto& frame = state.frame;
        const auto& audit = state.audit;
        const auto& comparison = state.comparison;
        const auto& raster_layers = state.raster_layers;
        bool passed = frame.misses == 0;
        if (audit.has_value())
        {
            passed = passed && audit->records == world.face_count && audit->color_mismatches == 0 &&
                     audit->material_records == world.face_count && audit->material_record_mismatches == 0 &&
                     audit->distance_lut_mismatches == 0 && audit->shade_pair_mismatches == 0;
        }
        if (comparison.has_value())
        {
            passed = passed && comparison->passed;
        }
        if (raster_layers.has_value())
        {
            passed = passed && raster_layers->current_pipeline.frame.misses == 0;
        }
        return passed;
    }

    void write_static_report(const StaticRenderState& state, bool passed) const
    {
        const auto& options = options_;
        const auto& world = world_;
        const auto& bvh = bvh_;
        const auto& frame = state.frame;
        const auto& quantized_world = state.quantized_world;
        const auto& quantized_bvh = state.quantized_bvh;
        const auto& quantized_frame = state.quantized_frame;
        const auto& packet_selection = state.packet_selection;
        const auto& packet_bvh = state.packet_bvh;
        const auto& packet_nearest_frame = state.packet_nearest_frame;
        const auto& packet_painter_frame = state.packet_painter_frame;
        const auto& raster_layers = state.raster_layers;
        const auto& packed_affine_texture_raster = state.packed_affine_texture_raster;
        const auto& packed_projective_texture_raster = state.packed_projective_texture_raster;
        const auto& affine_texture_mapping_fidelity = state.affine_texture_mapping_fidelity;
        const auto& projective_texture_mapping_fidelity = state.projective_texture_mapping_fidelity;
        const auto& audit = state.audit;
        const auto& comparison = state.comparison;
        const auto& packed_texture_comparison = state.packed_texture_comparison;
        const auto render_begin = state.render_begin;
        const auto render_end = state.render_end;
        const auto load_begin = load_begin_;
        const auto load_end = load_end_;
        const auto build_begin = build_begin_;
        const auto build_end = build_end_;
        const auto milliseconds = [](auto begin, auto end) {
            return std::chrono::duration<double, std::milli>(end - begin).count();
        };
        write_json_report(
            options.json_path,
            options,
            world,
            bvh,
            frame,
            quantized_world ? &*quantized_world : nullptr,
            quantized_bvh ? &*quantized_bvh : nullptr,
            quantized_frame ? &*quantized_frame : nullptr,
            packet_selection ? &*packet_selection : nullptr,
            packet_bvh ? &*packet_bvh : nullptr,
            packet_nearest_frame ? &*packet_nearest_frame : nullptr,
            packet_painter_frame ? &*packet_painter_frame : nullptr,
            raster_layers ? &*raster_layers : nullptr,
            packed_affine_texture_raster ? &*packed_affine_texture_raster : nullptr,
            packed_projective_texture_raster ? &*packed_projective_texture_raster : nullptr,
            affine_texture_mapping_fidelity ? &*affine_texture_mapping_fidelity : nullptr,
            projective_texture_mapping_fidelity ? &*projective_texture_mapping_fidelity : nullptr,
            audit,
            comparison,
            packed_texture_comparison,
            passed,
            milliseconds(load_begin, load_end),
            milliseconds(build_begin, build_end),
            milliseconds(render_begin, render_end)
        );
    }

    void print_static_summary(const StaticRenderState& state, bool passed) const
    {
        const auto& options = options_;
        const auto& world = world_;
        const auto& bvh = bvh_;
        const auto& frame = state.frame;
        const auto& quantized_world = state.quantized_world;
        const auto& quantized_bvh = state.quantized_bvh;
        const auto& packet_selection = state.packet_selection;
        const auto& quantized_frame = state.quantized_frame;
        const auto& packet_nearest_frame = state.packet_nearest_frame;
        const auto& packet_painter_frame = state.packet_painter_frame;
        const auto& raster_layers = state.raster_layers;
        const auto& packed_affine_texture_raster = state.packed_affine_texture_raster;
        const auto& packed_projective_texture_raster = state.packed_projective_texture_raster;
        const auto& fly_alias_coverage = state.fly_alias_coverage;
        const auto fly_alias_row = state.fly_alias_row;
        const auto& audit = state.audit;
        const auto& comparison = state.comparison;
        const auto& packed_texture_comparison = state.packed_texture_comparison;
        std::cout << "reference=" << (passed ? "PASS" : "FAIL") << " camera=" << options.camera_label
                  << " hits=" << frame.hits << " misses=" << frame.misses << " firstHitFaces=" << frame.unique_faces
                  << " triangles=" << world.triangles.size() << " bvhNodes=" << bvh.node_count() << '\n';
        if (audit.has_value())
        {
            const bool audit_passed =
                audit->color_mismatches == 0 && audit->material_record_mismatches == 0 &&
                audit->distance_lut_mismatches == 0 && audit->shade_pair_mismatches == 0;
            std::cout << "packedColorAudit=" << (audit_passed ? "PASS" : "FAIL")
                      << " drawable=" << audit->drawable_records << " legacyMismatches=" << audit->color_mismatches
                      << " materialMismatches=" << audit->material_record_mismatches
                      << " distanceLutMismatches=" << audit->distance_lut_mismatches
                      << " shadePairMismatches=" << audit->shade_pair_mismatches << '\n';
        }
        if (quantized_frame.has_value())
        {
            std::cout << "quantizedWorld=PASS hits=" << quantized_frame->hits << " misses=" << quantized_frame->misses
                      << " firstHitFaces=" << quantized_frame->unique_faces
                      << " triangles=" << required(quantized_world).triangles.size()
                      << " bvhNodes=" << required(quantized_bvh).node_count() << '\n';
        }
        if (packet_nearest_frame.has_value() && packet_painter_frame.has_value())
        {
            std::cout << "packetNearest=PASS hits=" << packet_nearest_frame->hits
                      << " misses=" << packet_nearest_frame->misses
                      << " selectedFaces=" << required(packet_selection).source_faces.size()
                      << " triangles=" << required(packet_selection).triangles.size() << '\n';
            std::cout << "packetPainter=PASS hits=" << packet_painter_frame->hits
                      << " misses=" << packet_painter_frame->misses
                      << " firstHitFaces=" << packet_painter_frame->unique_faces << '\n';
        }
        if (raster_layers.has_value())
        {
            const auto print_raster = [](std::string_view name, const RasterResult& raster) {
                std::cout << name << "=PASS hits=" << raster.frame.hits << " misses=" << raster.frame.misses
                          << " writes=" << raster.stats.plot_writes
                          << " candidateWrites=" << raster.stats.candidate_writes << '\n';
            };
            print_raster("currentPipeline", raster_layers->current_pipeline);
            print_raster("legacyWidenedFan", raster_layers->legacy_widened_fan);
            print_raster("convexPainter", raster_layers->convex_painter);
            print_raster("frontToBackUncovered", raster_layers->front_to_back_uncovered);
        }
        if (packed_affine_texture_raster.has_value())
        {
            std::cout << "packedAffineTexture=PASS hits=" << packed_affine_texture_raster->hits
                      << " misses=" << packed_affine_texture_raster->misses
                      << " writes=" << packed_affine_texture_raster->stats.plot_writes
                      << " candidateWrites=" << packed_affine_texture_raster->stats.candidate_writes << '\n';
        }
        if (packed_projective_texture_raster.has_value())
        {
            std::cout << "packedProjectiveTexture=PASS hits=" << packed_projective_texture_raster->hits
                      << " misses=" << packed_projective_texture_raster->misses
                      << " writes=" << packed_projective_texture_raster->stats.plot_writes
                      << " candidateWrites=" << packed_projective_texture_raster->stats.candidate_writes << '\n';
        }
        if (fly_alias_coverage.has_value())
        {
            const auto& coverage = *fly_alias_coverage;
            const auto& selected_frame = *packed_projective_texture_raster;
            std::cout
                << "fly-alias=PASS"
                << " aliasContract=current-camera-opaque-depth-clipped-v1"
                << " flyAliasRow=" << fly_alias_row << " packedBrushMisses=" << selected_frame.misses << " aliasTokens="
                << coverage.tokens << " aliasProjected=" << coverage.projected << " aliasClipped=" << coverage.clipped
                << " aliasModelMask=" << coverage.model_mask << " aliasMinArea=" << coverage.minimum_projected_area
                << " aliasMaxArea=" << coverage.maximum_projected_area << " aliasPlotPixels="
                << coverage.packed_plot_pixels << " aliasVisiblePixels=" << coverage.packed_visible_pixels
                << " aliasOpaqueOccludedPixels=" << coverage.packed_opaque_occluded_pixels
                << " idealAliasCandidates=" << coverage.ideal_candidate_pixels
                << " idealAliasOpaqueOccluded=" << coverage.ideal_opaque_occluded_pixels << " aliasRecords=";
            for (std::size_t index = 0; index < coverage.records.size(); ++index)
            {
                if (index != 0)
                {
                    std::cout << ';';
                }
                const auto& record = coverage.records[index];
                std::cout << record.token << ',' << static_cast<int>(record.sprite) << ',' << record.is_static << ','
                          << static_cast<int>(record.state) << ',' << record.first_x << ',' << record.first_y << ','
                          << record.last_x << ',' << record.last_y << ',' << record.plot_pixels << ','
                          << record.visible_pixels << ',' << record.opaque_occluded_pixels;
            }
            std::cout << '\n';
        }
        if (comparison.has_value())
        {
            std::cout << "comparison=" << (comparison->passed ? "PASS" : "FAIL")
                      << " exact=" << comparison->exact_pixels << " holes=" << comparison->snes_hole_pixels
                      << " falseGeometry=" << comparison->snes_false_geometry_pixels << " paletteMismatch="
                      << comparison->palette_mismatch_pixels << " bad2x2=" << comparison->bad_2x2 << '\n';
        }
        if (packed_texture_comparison.has_value())
        {
            std::cout << "packedAffineTextureComparison exact=" << packed_texture_comparison->exact_pixels
                      << " different=" << packed_texture_comparison->different_pixels
                      << " firstMismatch=" << packed_texture_comparison->first_mismatch << '\n';
        }
        std::cout << "outputPrefix=" << options.output_prefix.string() << '\n';
    }

    int run_static_render()
    {
        StaticRenderState state;
        prepare_static_render(state);
        render_static_layers(state);
        compare_static_outputs(state);
        const bool passed = static_render_passed(state);
        write_static_report(state, passed);
        print_static_summary(state, passed);
        return passed ? 0 : 2;
    }

    const Options& options_;
    std::chrono::steady_clock::time_point load_begin_;
    std::vector<std::uint8_t> pak_bytes_;
    std::vector<std::uint8_t> bsp_bytes_;
    std::array<Rgb, kQuakePaletteColors> quake_palette_;
    QuakeColormap quake_colormap_;
    BspData bsp_;
    SourceWorld world_;
    std::chrono::steady_clock::time_point load_end_;
    std::chrono::steady_clock::time_point build_begin_;
    Bvh bvh_;
    std::chrono::steady_clock::time_point build_end_;
};

int run_application(int argc, char** argv)
{
    const auto options = parse_options(argc, argv);
    if (options.self_test)
    {
        const bool passed = run_self_test();
        std::cout << "self-test=" << (passed ? "PASS" : "FAIL") << '\n';
        return passed ? 0 : 2;
    }
    return ReferenceRendererApplication(options).run();
}

} // namespace quake_bsp_reference
