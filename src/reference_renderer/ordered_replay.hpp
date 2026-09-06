#pragma once

#include "world.hpp"
#include "geometry.hpp"
#include "instrumentation.hpp"
#include "brushes.hpp"
#include "audio.hpp"
#include "external_models.hpp"
#include "aliases.hpp"
#include "packed_brushes.hpp"

namespace quake_bsp_reference {

inline constexpr std::size_t kOrderedReplayHeaderBytes = 40;
inline constexpr std::size_t kOrderedReplayFrameBytes = 14;
inline constexpr std::uint16_t kOrderedReplayVersion = 1;

struct OrderedPackedFrame
{
    std::uint16_t source_pose{};
    Camera camera;
    PacketSelection packet;
};

struct OrderedPackedReplay
{
    std::uint16_t source_pose_count{};
    std::uint16_t source_rate{};
    std::uint16_t step_rate{};
    std::uint16_t stride{};
    std::vector<OrderedPackedFrame> frames;
};

constexpr bool supported_ordered_replay_step_rate(std::uint16_t rate)
{
    return rate == 2U || rate == 20U;
}

OrderedPackedReplay load_ordered_packed_replay(
    const fs::path& ordered_replay_path,
    const fs::path& camera_track_path,
    const fs::path& data_dir,
    const SourceWorld& world
);

std::vector<std::uint8_t> render_ordered_packed_indices(
    const SourceWorld& world,
    const OrderedPackedFrame& ordered_frame,
    const PackedBrushAssets& brush_assets,
    const AliasAssets& alias_assets,
    const fs::path& data_dir,
    RenderMode mode,
    bool brushes_enabled,
    bool entities_enabled,
    AliasCoverage* coverage = nullptr,
    AliasVisibilityRow* visibility = nullptr,
    bool authentic_sky = false,
    double surface_time = 0.0,
    Json* surface_inspection = nullptr,
    const ExternalBspScene* external_scene = nullptr,
    const ExternalBspReplay* external_replay = nullptr,
    bool external_models_enabled = false,
    ExternalBspCoverage* external_coverage = nullptr
);

inline constexpr std::size_t kAliasVisibilityHeaderBytes = 56;
inline constexpr std::size_t kAliasVisibilityRowBytes = 2;
inline constexpr std::size_t kAliasVisibilityHalfbankBytes = 0x8000;
inline constexpr std::uint16_t kAliasVisibilityVersion = 2;
inline constexpr unsigned kAliasVisibilityRecordBits = 4;
inline constexpr std::uint16_t kAliasVisibilityRecordMask = (1U << kAliasVisibilityRecordBits) - 1U;
inline constexpr std::uint16_t kAliasVisibilityDictionaryMaximum = (1U << (16U - kAliasVisibilityRecordBits)) - 1U;
inline constexpr std::uint8_t kAliasVisibilityPartial = 1;
inline constexpr std::uint8_t kAliasVisibilityHidden = 2;

std::vector<std::uint8_t> encode_ordered_alias_visibility(
    const OrderedPackedReplay& replay,
    const AliasAssets& aliases,
    std::span<const AliasVisibilityRow> rows,
    bool brushes_enabled
);

std::vector<std::uint8_t> build_ordered_alias_visibility(
    const SourceWorld& world,
    const OrderedPackedReplay& replay,
    const PackedBrushAssets& brush_assets,
    const AliasAssets& aliases,
    const fs::path& data_dir,
    bool brushes_enabled
);

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
);

} // namespace quake_bsp_reference
