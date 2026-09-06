#pragma once

#include "world.hpp"
#include "geometry.hpp"
#include "brushes.hpp"

namespace quake_bsp_reference {

inline constexpr std::size_t kExternalBspReplayHeaderBytes = 36;
inline constexpr std::size_t kExternalBspReplayModelBytes = 64;
inline constexpr std::size_t kExternalBspReplaySnapshotBytes = 6;
inline constexpr std::size_t kExternalBspReplayStateBytes = 14;
inline constexpr std::uint16_t kExternalBspReplayVersion = 1;
inline constexpr std::uint16_t kExternalBspModelOwnershipBase = 0x8000;

struct ExternalBspEntityState
{
    std::uint16_t entity{};
    std::uint16_t model_slot{};
    std::uint8_t frame{};
    Vec3 origin;
    std::array<std::int8_t, 3> angles{};
};

struct ExternalBspReplayModel
{
    std::uint16_t model_precache_index{};
    std::string name;
};

struct ExternalBspReplaySnapshot
{
    std::vector<ExternalBspEntityState> entities;
    std::size_t active_models{};
};

struct ExternalBspReplay
{
    std::uint16_t sample_rate{};
    double first_server_time{};
    std::uint64_t camera_track_fnv1a64{};
    std::vector<ExternalBspReplayModel> models;
    std::vector<std::uint16_t> row_snapshots;
    std::vector<ExternalBspReplaySnapshot> snapshots;

    [[nodiscard]] std::size_t row_count() const
    {
        return row_snapshots.size();
    }

    [[nodiscard]] std::span<const ExternalBspEntityState> row(std::size_t index) const
    {
        if (index >= row_snapshots.size())
        {
            fail("external BSP replay row index is out of range");
        }
        return snapshots.at(row_snapshots[index]).entities;
    }
};

struct ExternalBspModel
{
    std::uint16_t model_precache_index{};
    std::string name;
    std::unique_ptr<SourceWorld> world;
    std::unique_ptr<Bvh> bvh;
    std::vector<BrushTextureAnimation> texture_animations;
};

struct ExternalBspScene
{
    std::vector<ExternalBspModel> models;
};

struct ExternalBspEntityCoverage
{
    std::uint16_t entity{};
    std::size_t candidate_pixels{};
    std::size_t visible_pixels{};
    std::uint64_t visible_face_mask{};
};

struct ExternalBspCoverage
{
    std::size_t active_entities{};
    std::size_t active_models{};
    std::size_t candidate_pixels{};
    std::size_t visible_pixels{};
    std::size_t visible_entities{};
    std::size_t visible_models{};
    std::vector<ExternalBspEntityCoverage> entity_records;

    ExternalBspEntityCoverage& entity_coverage(std::uint16_t entity)
    {
        for (auto& record : entity_records)
        {
            if (record.entity == entity)
            {
                return record;
            }
        }
        entity_records.push_back(ExternalBspEntityCoverage{.entity = entity});
        return entity_records.back();
    }

    [[nodiscard]] const ExternalBspEntityCoverage* find_entity_coverage(std::uint16_t entity) const noexcept
    {
        for (const auto& record : entity_records)
        {
            if (record.entity == entity)
            {
                return &record;
            }
        }
        return nullptr;
    }
};

ExternalBspCoverage external_bsp_row_coverage(const ExternalBspReplay& replay, std::size_t source_pose);

ExternalBspReplay load_external_bsp_replay(const fs::path& path);

void require_external_bsp_camera_identity(const ExternalBspReplay& replay, const fs::path& camera_track);

ExternalBspScene build_external_bsp_scene(
    std::span<const std::uint8_t> pak_bytes,
    const std::array<Rgb, kQuakePaletteColors>& palette,
    const QuakeColormap& colormap,
    const ExternalBspReplay& replay
);

struct ExternalBspBasis
{
    Vec3 forward;
    Vec3 left;
    Vec3 up;
};

ExternalBspBasis external_bsp_basis(const std::array<std::int8_t, 3>& angles);

Vec3 external_bsp_world_to_local(const ExternalBspBasis& basis, const Vec3& vector);

Ray external_bsp_local_ray(const ExternalBspBasis& basis, const Vec3& origin, const Ray& world_ray);

double external_bsp_server_time(const ExternalBspReplay& replay, std::size_t sample_index);

ExactTextureSample sample_external_bsp_texture(
    const ExternalBspModel& model,
    std::uint16_t face,
    const Ray& ray,
    std::uint8_t entity_frame,
    double server_time
);

void compose_source_external_bsp_models(
    const ExternalBspScene& scene,
    std::span<const ExternalBspEntityState> entities,
    std::size_t sample_index,
    double server_time,
    bool flat,
    const ViewTransform& view,
    ReferenceFrame& frame,
    ExternalBspCoverage* output_coverage = nullptr
);

Json external_bsp_inspection(
    const ExternalBspReplay& replay,
    std::size_t source_pose,
    bool configured,
    bool effective,
    const ExternalBspCoverage& coverage
);

bool run_external_bsp_replay_self_test();

} // namespace quake_bsp_reference
