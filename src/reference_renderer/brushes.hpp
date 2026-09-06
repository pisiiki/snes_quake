#pragma once

#include "world.hpp"
#include "geometry.hpp"

namespace quake_bsp_reference {

inline constexpr std::size_t kBrushReplayHeaderBytes = 32;
inline constexpr std::size_t kBrushReplaySnapshotBytes = 6;
inline constexpr std::size_t kBrushReplayStateBytes = 16;
inline constexpr std::uint16_t kBrushReplayVersion = 2;
inline constexpr std::uint16_t kBrushReplaySelfTestSampleRate = 20;

struct BrushEntityState
{
    std::uint16_t entity{};
    std::uint16_t model_index{};
    std::uint16_t inline_model{};
    std::uint8_t frame{};
    Vec3 origin;
    std::array<std::int8_t, 3> angles{};
};

struct BrushReplaySnapshot
{
    std::vector<BrushEntityState> entities;
};

struct BrushReplay
{
    std::uint16_t sample_rate{};
    double first_server_time{};
    std::uint64_t camera_track_fnv1a64{};
    std::vector<std::uint16_t> row_snapshots;
    std::vector<BrushReplaySnapshot> snapshots;

    [[nodiscard]] std::size_t row_count() const
    {
        return row_snapshots.size();
    }

    [[nodiscard]] std::span<const BrushEntityState> row(std::size_t index) const
    {
        if (index >= row_snapshots.size())
        {
            fail("brush replay row index is out of range");
        }
        return snapshots.at(row_snapshots[index]).entities;
    }
};

std::uint64_t read_brush_u64(std::span<const std::uint8_t> bytes, std::size_t offset);

std::uint64_t brush_fnv1a64(std::span<const std::uint8_t> bytes);

std::size_t checked_stream_bytes(std::uint32_t count, std::size_t stride, std::string_view label);

BrushReplay load_brush_replay(const fs::path& path);

void require_brush_camera_identity(const BrushReplay& replay, const fs::path& camera_track);

struct BrushTextureAnimation
{
    std::array<int, 10> regular{};
    std::array<int, 10> alternate{};
    int regular_count{};
    int alternate_count{};
    bool animated{};
    bool base_is_alternate{};
};

std::vector<BrushTextureAnimation> build_brush_texture_animations(std::span<const MipTexture> textures);

int resolve_brush_texture(
    std::span<const BrushTextureAnimation> animations,
    int texture_id,
    std::uint8_t entity_frame,
    double server_time
);

struct BrushFace
{
    std::uint16_t source_face{};
    Plane plane;
    int texture_info{};
    FaceLightmap lightmap;
    FaceColor color;
    std::uint8_t live_base_color{};
    Vec3 centroid;
};

struct BrushModelGeometry
{
    std::uint16_t model{};
    Vec3 mins;
    Vec3 maxs;
    Vec3 origin;
    int first_face{};
    std::vector<BrushFace> faces;
    std::vector<Triangle> triangles;
    std::optional<Bvh> bvh;
};

struct BrushScene
{
    std::vector<std::optional<BrushModelGeometry>> models;
    std::vector<BrushTextureAnimation> texture_animations;
};

BrushScene build_brush_scene(const BspData& bsp, const BrushReplay& replay);

ExactTextureSample sample_brush_texture(
    const SourceWorld& world,
    const BrushScene& scene,
    const BrushModelGeometry& model,
    std::uint16_t local_face,
    const Ray& ray,
    std::uint8_t entity_frame,
    double server_time
);

ReferenceFrame render_packed_camera_source_reference_with_brushes(
    const SourceWorld& world,
    const Bvh& world_bvh,
    const BrushScene& scene,
    const Camera& camera,
    std::span<const BrushEntityState> entities,
    std::size_t sample_index,
    double server_time,
    bool flat
);

ReferenceFrame render_source_reference_with_brushes(
    const SourceWorld& world,
    const Bvh& world_bvh,
    const BrushScene& scene,
    const SourceCamera& camera,
    const BrushReplay& replay,
    std::size_t sample_index,
    bool flat,
    bool enabled
);

bool run_brush_reference_self_test();

} // namespace quake_bsp_reference
