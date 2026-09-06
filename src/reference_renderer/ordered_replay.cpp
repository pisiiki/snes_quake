#include "ordered_replay.hpp"
#include "world.hpp"
#include "geometry.hpp"
#include "sky.hpp"
#include "instrumentation.hpp"
#include "brushes.hpp"
#include "audio.hpp"
#include "external_models.hpp"
#include "aliases.hpp"
#include "textured_live.hpp"
#include "live_demo.hpp"
#include "external_models_packed.hpp"
#include "packed_brushes.hpp"
#include "turbulence.hpp"

namespace quake_bsp_reference {

OrderedPackedReplay load_ordered_packed_replay(
    const fs::path& ordered_replay_path,
    const fs::path& camera_track_path,
    const fs::path& data_dir,
    const SourceWorld& world
)
{
    const auto bytes = read_file(ordered_replay_path);
    require_range(bytes, 0, kOrderedReplayHeaderBytes, "QOR1 header");
    if (std::string_view(reinterpret_cast<const char*>(bytes.data()), 4) != "QOR1")
    {
        fail("ordered packed replay does not have QOR1 magic");
    }
    const auto version = read_u16(bytes, 4);
    const auto header_bytes = read_u16(bytes, 6);
    const auto frame_bytes = read_u16(bytes, 8);
    const auto frame_count = read_u16(bytes, 10);
    const auto source_pose_count = read_u16(bytes, 12);
    const auto stride = read_u16(bytes, 14);
    const auto source_rate = read_u16(bytes, 16);
    const auto step_rate = read_u16(bytes, 18);
    const auto track_hash = read_brush_u64(bytes, 20);
    const auto metadata_hash = read_brush_u64(bytes, 28);
    const auto payload_offset = read_u32(bytes, 36);
    if (version != kOrderedReplayVersion || header_bytes != kOrderedReplayHeaderBytes ||
        frame_bytes != kOrderedReplayFrameBytes || frame_count == 0 || source_pose_count == 0 || stride == 0 ||
        source_rate == 0 || step_rate == 0 || source_rate % step_rate != 0 || stride != source_rate / step_rate)
    {
        fail("QOR1 header contract is invalid");
    }
    const auto directory_bytes = checked_stream_bytes(frame_count, kOrderedReplayFrameBytes, "QOR1 frame directory");
    if (payload_offset != kOrderedReplayHeaderBytes + directory_bytes || payload_offset > bytes.size())
    {
        fail("QOR1 payload offset disagrees with its frame directory");
    }
    const auto expected_frames = (static_cast<std::size_t>(source_pose_count) + stride - 1U) / stride;
    if (frame_count != expected_frames)
    {
        fail("QOR1 frame count disagrees with its ordered schedule");
    }
    if (track_hash != brush_fnv1a64(read_file(camera_track_path)))
    {
        fail("QOR1 camera track identity does not match --realtime-demo");
    }
    if (data_dir.empty() || metadata_hash != brush_fnv1a64(read_file(data_dir / "QuakeBSPMetadata.json")))
    {
        fail("QOR1 packed-world metadata identity does not match --data-dir");
    }

    OrderedPackedReplay replay;
    replay.source_pose_count = source_pose_count;
    replay.source_rate = source_rate;
    replay.step_rate = step_rate;
    replay.stride = stride;
    replay.frames.reserve(frame_count);
    std::size_t expected_face_offset = 0;
    for (std::size_t ordinal = 0; ordinal < frame_count; ++ordinal)
    {
        const auto offset = kOrderedReplayHeaderBytes + ordinal * kOrderedReplayFrameBytes;
        const auto source_pose = read_u16(bytes, offset);
        const auto signed_byte = [&](std::size_t byte_offset) {
            return static_cast<int>(std::bit_cast<std::int8_t>(bytes[byte_offset]));
        };
        const Camera camera{
            signed_byte(offset + 2),
            signed_byte(offset + 3),
            signed_byte(offset + 4),
            static_cast<int>(bytes[offset + 5]),
            signed_byte(offset + 6)
        };
        const auto reserved = bytes[offset + 7];
        const auto face_count = read_u16(bytes, offset + 8);
        const auto face_offset = read_u32(bytes, offset + 10);
        if (source_pose != ordinal * stride || source_pose >= source_pose_count || reserved != 0 || face_count == 0 ||
            face_offset != expected_face_offset)
        {
            fail("QOR1 frame directory is not canonical");
        }
        const auto face_bytes = checked_stream_bytes(face_count, 2, "QOR1 packet source faces");
        const auto first = static_cast<std::size_t>(payload_offset) + expected_face_offset;
        require_range(bytes, first, face_bytes, "QOR1 packet source faces");
        replay.frames.push_back(
            {source_pose,
             camera,
             parse_packet_selection(std::span<const std::uint8_t>(bytes).subspan(first, face_bytes), world)}
        );
        expected_face_offset += face_bytes;
    }
    if (static_cast<std::size_t>(payload_offset) + expected_face_offset != bytes.size())
    {
        fail("QOR1 contains trailing or unreferenced packet bytes");
    }
    return replay;
}

std::vector<std::uint8_t> render_ordered_packed_indices(
    const SourceWorld& world,
    const OrderedPackedFrame& ordered_frame,
    const PackedBrushAssets& brush_assets,
    const AliasAssets& alias_assets,
    const fs::path& data_dir,
    RenderMode mode,
    bool brushes_enabled,
    bool entities_enabled,
    AliasCoverage* coverage,
    AliasVisibilityRow* visibility,
    bool authentic_sky,
    double surface_time,
    Json* surface_inspection,
    const ExternalBspScene* external_scene,
    const ExternalBspReplay* external_replay,
    bool external_models_enabled,
    ExternalBspCoverage* external_coverage
)
{
    constexpr auto raster_mode = TextureRasterMode::projective_block8;
    PackedTextureRaster raster;
    if (brushes_enabled)
    {
        const auto visual_state = packed_brush_visual_state_at_pose(brush_assets, ordered_frame.source_pose);
        raster = render_packed_brush_pipeline(
            world,
            ordered_frame.packet,
            ordered_frame.camera,
            visual_state,
            data_dir,
            brush_assets,
            raster_mode,
            surface_time,
            entities_enabled
        );
    }
    else
    {
        raster = render_packed_texture_pipeline(
            world,
            ordered_frame.packet,
            ordered_frame.camera,
            raster_mode,
            surface_time
        );
    }
    if (raster.misses != 0)
    {
        // Alternate configured routes can observe pixels outside every packed
        // opaque face. Preserve miss/depth ownership for aliases, but make
        // every color plane deterministic instead of consuming stale storage.
        for (std::size_t pixel = 0; pixel < raster.faces.size(); ++pixel)
        {
            if (raster.faces[pixel] != kMissFace)
            {
                continue;
            }
            raster.indices[pixel] = 0;
            raster.lightmapped_indices[pixel] = 0;
            raster.untextured_lightmap_indices[pixel] = 0;
        }
    }
    if (external_replay != nullptr)
    {
        if (ordered_frame.source_pose >= external_replay->row_count())
        {
            fail("ordered external BSP source pose is out of range");
        }
        if (external_coverage != nullptr)
        {
            *external_coverage = external_bsp_row_coverage(*external_replay, ordered_frame.source_pose);
        }
        if (external_models_enabled)
        {
            if (external_scene == nullptr)
            {
                fail("external BSP rendering has no loaded model scene");
            }
            compose_packed_external_bsp_models(
                raster,
                world,
                *external_scene,
                external_replay->row(ordered_frame.source_pose),
                ordered_frame.source_pose,
                external_bsp_server_time(*external_replay, ordered_frame.source_pose),
                ordered_frame.camera,
                external_coverage
            );
        }
    }
    else if (external_models_enabled)
    {
        fail("external BSP rendering requires a QER1 replay");
    }
    const auto turbulence_inspection = quake_turbulence_inspection(raster);
    if (surface_inspection != nullptr)
    {
        *surface_inspection = Json{
            {"schema", "quake-reference-surface-inspection-v1"},
            {"available", true},
            {"turbulence", turbulence_inspection}
        };
    }
    const auto& selected = selected_render_indices(raster, mode);
    std::vector<std::uint8_t> opaque(selected.begin(), selected.end());
    if (authentic_sky && mode.textures)
    {
        auto sky = render_quake_sky_presentation(
            opaque,
            raster.faces,
            raster.entities,
            world,
            packed_view_transform(world, ordered_frame.camera),
            surface_time,
            "demo-server-time"
        );
        opaque = std::move(sky.indices);
        if (surface_inspection != nullptr)
        {
            sky.inspection["turbulence"] = turbulence_inspection;
            *surface_inspection = std::move(sky.inspection);
        }
    }
    if (!entities_enabled)
    {
        return opaque;
    }
    return compose_post_opaque_alias_indices(
        opaque,
        raster.depth_q6,
        ordered_frame.camera,
        alias_assets,
        ordered_frame.source_pose,
        mode,
        coverage,
        visibility
    );
}

namespace {
void alias_visibility_store_u16(std::vector<std::uint8_t>& bytes, std::size_t offset, std::uint16_t value)
{
    bytes.at(offset) = static_cast<std::uint8_t>(value & 0xffU);
    bytes.at(offset + 1) = static_cast<std::uint8_t>(value >> 8U);
}
} // namespace

namespace {
void alias_visibility_store_u32(std::vector<std::uint8_t>& bytes, std::size_t offset, std::uint32_t value)
{
    bytes.at(offset) = static_cast<std::uint8_t>(value & 0xffU);
    bytes.at(offset + 1) = static_cast<std::uint8_t>((value >> 8U) & 0xffU);
    bytes.at(offset + 2) = static_cast<std::uint8_t>((value >> 16U) & 0xffU);
    bytes.at(offset + 3) = static_cast<std::uint8_t>(value >> 24U);
}
} // namespace

std::vector<std::uint8_t> encode_ordered_alias_visibility(
    const OrderedPackedReplay& replay,
    const AliasAssets& aliases,
    std::span<const AliasVisibilityRow> rows,
    bool brushes_enabled
)
{
    if (rows.size() != replay.source_pose_count || replay.frames.size() != replay.source_pose_count ||
        replay.stride != 1U)
    {
        fail("alias visibility requires every source replay row");
    }
    std::vector<std::vector<std::uint8_t>> payloads(replay.source_pose_count);
    std::vector<std::uint8_t> record_counts(replay.source_pose_count, 0);
    std::uint16_t maximum_records = 0;
    std::uint16_t maximum_mask_bytes = 0;

    for (const auto& frame : replay.frames)
    {
        const auto& row = rows[frame.source_pose];
        const auto& alias_row = aliases.rows.at(frame.source_pose);
        if (row.tokens.size() != alias_row.tokens.size())
        {
            fail("alias visibility token count disagrees with QBA1");
        }
        auto& payload = payloads.at(frame.source_pose);
        std::size_t records = 0;
        std::size_t mask_bytes = 0;
        for (std::size_t token = 0; token < row.tokens.size(); ++token)
        {
            const auto& candidates = row.tokens[token].candidates;
            const auto visible =
                static_cast<std::size_t>(std::count(candidates.begin(), candidates.end(), std::uint8_t{1}));
            if (visible == candidates.size())
            {
                continue;
            }
            if (token > 0xffU || candidates.empty() || candidates.size() > 0xffffU)
            {
                fail("alias visibility record escapes compact storage");
            }
            ++records;
            payload.push_back(static_cast<std::uint8_t>(token));
            if (visible == 0)
            {
                payload.push_back(kAliasVisibilityHidden);
            }
            else
            {
                payload.push_back(kAliasVisibilityPartial);
            }
            const auto append_u16 = [&](std::uint16_t value) {
                payload.push_back(static_cast<std::uint8_t>(value & 0xffU));
                payload.push_back(static_cast<std::uint8_t>(value >> 8U));
            };
            append_u16(static_cast<std::uint16_t>(candidates.size()));
            if (visible != 0)
            {
                const auto mask_size = (candidates.size() + 7U) / 8U;
                const auto first = payload.size();
                payload.resize(first + mask_size, 0);
                for (std::size_t candidate = 0; candidate < candidates.size(); ++candidate)
                {
                    if (candidates[candidate] != 0)
                    {
                        payload[first + candidate / 8U] |= static_cast<std::uint8_t>(1U << (candidate & 7U));
                    }
                }
                mask_bytes += mask_size;
            }
        }
        if (records > kAliasVisibilityRecordMask || mask_bytes > 0xffffU)
        {
            fail("alias visibility row escapes compact storage");
        }
        record_counts.at(frame.source_pose) = static_cast<std::uint8_t>(records);
        maximum_records = std::max(maximum_records, static_cast<std::uint16_t>(records));
        maximum_mask_bytes = std::max(maximum_mask_bytes, static_cast<std::uint16_t>(mask_bytes));
    }

    const auto byte_vector_less = [](const std::vector<std::uint8_t>& left, const std::vector<std::uint8_t>& right) {
        const auto shared = std::min(left.size(), right.size());
        for (std::size_t index = 0; index < shared; ++index)
        {
            if (left[index] != right[index])
            {
                return left[index] < right[index];
            }
        }
        return left.size() < right.size();
    };
    std::map<std::vector<std::uint8_t>, std::uint16_t, decltype(byte_vector_less)> dictionary_lookup(byte_vector_less);
    std::vector<std::vector<std::uint8_t>> dictionary;
    std::vector<std::uint16_t> row_dictionary(replay.source_pose_count, 0);
    for (std::size_t pose = 0; pose < payloads.size(); ++pose)
    {
        const auto& payload = payloads[pose];
        if (payload.empty())
        {
            continue;
        }
        const auto next_id = static_cast<std::uint16_t>(dictionary.size() + 1U);
        const auto [entry, inserted] = dictionary_lookup.try_emplace(payload, next_id);
        if (inserted)
        {
            if (next_id > kAliasVisibilityDictionaryMaximum)
            {
                fail("alias visibility dictionary escapes its row descriptor");
            }
            dictionary.push_back(payload);
        }
        row_dictionary[pose] = entry->second;
    }

    const auto directory_offset = kAliasVisibilityHeaderBytes;
    const auto directory_bytes = static_cast<std::size_t>(replay.source_pose_count) * kAliasVisibilityRowBytes;
    const auto dictionary_offset = directory_offset + directory_bytes;
    const auto dictionary_bytes = dictionary.size() * 2U;
    const auto payload_offset = dictionary_offset + dictionary_bytes;
    if (payload_offset > kAliasVisibilityHalfbankBytes)
    {
        fail("alias visibility directory exceeds one GSU halfbank");
    }
    std::vector<std::uint8_t> bytes(kAliasVisibilityHalfbankBytes, 0xffU);
    std::fill(bytes.begin(), bytes.begin() + static_cast<std::ptrdiff_t>(payload_offset), 0);
    std::copy_n("QAV2", 4, bytes.begin());
    alias_visibility_store_u16(bytes, 4, kAliasVisibilityVersion);
    alias_visibility_store_u16(bytes, 6, kAliasVisibilityHeaderBytes);
    alias_visibility_store_u16(bytes, 8, replay.source_pose_count);
    alias_visibility_store_u16(bytes, 10, static_cast<std::uint16_t>(replay.frames.size()));
    alias_visibility_store_u16(bytes, 12, replay.stride);
    alias_visibility_store_u16(bytes, 14, replay.source_rate);
    alias_visibility_store_u16(bytes, 16, replay.step_rate);
    alias_visibility_store_u16(bytes, 18, kAliasVisibilityRowBytes);
    alias_visibility_store_u16(bytes, 20, static_cast<std::uint16_t>(brushes_enabled));
    alias_visibility_store_u16(bytes, 22, maximum_records);
    alias_visibility_store_u16(bytes, 24, maximum_mask_bytes);
    alias_visibility_store_u16(bytes, 26, static_cast<std::uint16_t>(dictionary.size()));
    alias_visibility_store_u32(bytes, 28, static_cast<std::uint32_t>(directory_offset));
    alias_visibility_store_u32(bytes, 32, static_cast<std::uint32_t>(payload_offset));

    std::size_t cursor = payload_offset;
    for (std::size_t index = 0; index < dictionary.size(); ++index)
    {
        const auto& payload = dictionary[index];
        if (cursor + payload.size() > bytes.size() || cursor > 0xffffU)
        {
            fail("alias visibility corpus exceeds one GSU halfbank");
        }
        alias_visibility_store_u16(bytes, dictionary_offset + index * 2U, static_cast<std::uint16_t>(cursor));
        std::copy(payload.begin(), payload.end(), bytes.begin() + static_cast<std::ptrdiff_t>(cursor));
        cursor += payload.size();
    }
    for (std::size_t pose = 0; pose < payloads.size(); ++pose)
    {
        const auto dictionary_id = row_dictionary[pose];
        const auto records = record_counts[pose];
        if ((dictionary_id == 0U) != (records == 0U))
        {
            fail("alias visibility row dictionary is inconsistent");
        }
        const auto descriptor = static_cast<std::uint16_t>((dictionary_id << kAliasVisibilityRecordBits) | records);
        alias_visibility_store_u16(bytes, directory_offset + pose * kAliasVisibilityRowBytes, descriptor);
    }
    alias_visibility_store_u32(bytes, 36, static_cast<std::uint32_t>(cursor - payload_offset));
    for (int byte = 0; byte < 8; ++byte)
    {
        bytes[40 + byte] = static_cast<std::uint8_t>(aliases.camera_fingerprint >> (byte * 8U));
        bytes[48 + byte] = static_cast<std::uint8_t>(aliases.package_fingerprint >> (byte * 8U));
    }
    return bytes;
}

std::vector<std::uint8_t> build_ordered_alias_visibility(
    const SourceWorld& world,
    const OrderedPackedReplay& replay,
    const PackedBrushAssets& brush_assets,
    const AliasAssets& aliases,
    const fs::path& data_dir,
    bool brushes_enabled
)
{
    std::vector<AliasVisibilityRow> rows(replay.source_pose_count);
    const RenderMode mode{true, Lighting::LightMap};
    for (const auto& frame : replay.frames)
    {
        static_cast<void>(render_ordered_packed_indices(
            world,
            frame,
            brush_assets,
            aliases,
            data_dir,
            mode,
            brushes_enabled,
            true,
            nullptr,
            &rows.at(frame.source_pose)
        ));
    }
    return encode_ordered_alias_visibility(replay, aliases, rows, brushes_enabled);
}

int run_realtime_demo(
    const SourceWorld& world,
    const Bvh& bvh,
    const BrushScene& brush_scene,
    const BrushReplay& brush_replay,
    const AliasAssets& alias_assets,
    const fs::path& camera_track_path,
    const fs::path& data_dir,
    const fs::path& ordered_replay_path,
    bool flat,
    RenderMode initial_mode,
    bool initial_legacy_material,
    PlaybackSpeed initial_playback_speed,
    bool ordered_2hz,
    bool ordered_fast,
    int presentation_rate_hz,
    ReferenceInstrumentationConfig instrumentation,
    bool brushes_enabled,
    bool entities_enabled,
    const ExternalBspScene* external_scene,
    const ExternalBspReplay* external_replay,
    bool external_bsp_models_enabled,
    const QuakeSoundAssets* sound_assets,
    bool sound_enabled,
    float sound_volume
)
{
    if (!ordered_2hz)
    {
        if (ordered_fast)
        {
            fail("fast ordered playback requires --ordered-2hz");
        }
        return run_source_realtime_demo(
            world,
            bvh,
            brush_scene,
            brush_replay,
            alias_assets,
            camera_track_path,
            flat,
            initial_mode,
            initial_legacy_material,
            initial_playback_speed,
            brushes_enabled,
            entities_enabled,
            external_scene,
            external_replay,
            external_bsp_models_enabled,
            sound_assets,
            sound_enabled,
            sound_volume,
            std::move(instrumentation)
        );
    }
    if (initial_legacy_material)
    {
        fail(
            "--material-view is a source-renderer experiment and cannot use "
            "--ordered-2hz"
        );
    }
    auto quantized_world = build_quantized_world(data_dir, world);
    auto replay = load_ordered_packed_replay(ordered_replay_path, camera_track_path, data_dir, quantized_world);
    if (replay.source_pose_count != brush_replay.row_count() || replay.source_rate != brush_replay.sample_rate ||
        !supported_ordered_replay_step_rate(replay.step_rate))
    {
        fail("QOR1 schedule disagrees with the configured brush replay");
    }
    if (replay.stride != 1 || replay.step_rate != replay.source_rate ||
        replay.frames.size() != replay.source_pose_count)
    {
        fail("live ordered playback requires the complete source-rate QOR1 replay");
    }
    auto brush_assets = load_packed_brush_assets(data_dir);
    const double ordered_source_rate = replay.source_rate;
    const double duration_seconds = constant_step_duration(replay.frames.size(), ordered_source_rate);
    return run_live_demo(
        world,
        replay.frames,
        duration_seconds,
        [&](double seconds) { return constant_step_pose_at_time(replay.frames.size(), seconds, ordered_source_rate); },
        [&](std::size_t pose) { return static_cast<double>(replay.frames.at(pose).source_pose) / replay.source_rate; },
        [&](std::size_t pose) { return packed_view_transform(quantized_world, replay.frames.at(pose).camera); },
        [&](std::size_t pose,
            RenderMode mode,
            bool legacy_material,
            bool brushes,
            bool entities,
            bool external_models) {
            if (legacy_material)
            {
                fail("ordered packed playback cannot select legacy material");
            }
            AliasCoverage coverage;
            const bool inspect_aliases = entities;
            Json surface_inspection{
                {"schema", "quake-reference-surface-inspection-v1"},
                {"available", false},
                {"reason", "textures are disabled for this frame"}
            };
            const double surface_time =
                brush_replay.first_server_time +
                static_cast<double>(replay.frames.at(pose).source_pose) / brush_replay.sample_rate;
            ExternalBspCoverage external_coverage;
            const bool effective_external_models = external_models;
            auto indices = render_ordered_packed_indices(
                quantized_world,
                replay.frames.at(pose),
                brush_assets,
                alias_assets,
                data_dir,
                mode,
                brushes,
                entities,
                inspect_aliases ? &coverage : nullptr,
                nullptr,
                true,
                surface_time,
                &surface_inspection,
                external_scene,
                external_replay,
                effective_external_models,
                &external_coverage
            );
            Json inspection{
                {"schema", "quake-reference-alias-inspection-v1"},
                {"available", false},
                {"sourcePose", replay.frames.at(pose).source_pose},
                {"reason", "billboard entities are disabled for this frame"}
            };
            if (inspect_aliases)
            {
                inspection = packed_alias_inspection(
                    replay.frames.at(pose).camera,
                    alias_assets,
                    replay.frames.at(pose).source_pose,
                    coverage
                );
            }
            LiveRenderResult result{std::move(indices), std::move(inspection), std::move(surface_inspection)};
            if (external_replay != nullptr)
            {
                result.external_bsp_inspection = external_bsp_inspection(
                    *external_replay,
                    replay.frames.at(pose).source_pose,
                    external_models,
                    effective_external_models,
                    external_coverage
                );
            }
            return result;
        },
        LiveDemoConfiguration{
            .playback_contract = "packed SNES parity | exact ordered source rows | no skips",
            .initial_mode = initial_mode,
            .initial_legacy_material = false,
            .initial_playback_speed = PlaybackSpeed::Realtime,
            .playback_speed_control = false,
            .playback_schedule =
                ordered_fast ? PlaybackSchedule::OrderedRenderCompletion : PlaybackSchedule::OrderedTimed,
            .initial_presentation_rate_hz = presentation_rate_hz,
            .ordered_source_rate_hz = replay.source_rate,
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

} // namespace quake_bsp_reference
