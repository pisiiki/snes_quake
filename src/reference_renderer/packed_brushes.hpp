#pragma once

#include "world.hpp"
#include "geometry.hpp"
#include "textured_live.hpp"

namespace quake_bsp_reference {

inline constexpr std::size_t kBrushRomBankBytes = 0x8000;

struct PackedBrushSection
{
    std::string name;
    std::vector<std::uint8_t> bytes;
    std::uint8_t bank{};
    std::uint16_t address{};
    std::uint8_t record_bytes{};
    std::uint16_t record_count{};
};

struct PackedBrushVariant
{
    std::uint8_t inline_model{};
    std::int16_t origin_x_q3{};
    std::int16_t origin_y_q3{};
    std::int16_t origin_z_q3{};
    std::uint16_t first_bucket{};
    std::uint16_t bucket_count{};
    std::array<std::int16_t, 3> bounds_center_q2{};
    std::array<std::uint16_t, 3> bounds_extent_q2{};
};

struct PackedBrushBucket
{
    std::uint16_t leaf{};
    std::uint16_t first_fragment{};
    std::uint8_t fragment_count{};
    bool solid{};
    std::uint16_t parent_node{};
};

struct PackedBrushFragment
{
    std::uint16_t packed_face{};
    std::uint32_t first_vertex{};
    std::uint8_t vertex_count{};
};

struct PackedBrushFace
{
    std::uint16_t source_face{};
    std::uint16_t texinfo{};
    std::uint16_t packed_face{};
    std::uint16_t base_texture{};
    std::int8_t s_axis{};
    std::int8_t t_axis{};
    std::int16_t s_offset{};
    std::int16_t t_offset{};
    std::uint8_t inline_model{};
    std::uint8_t local_face{};
    std::uint8_t side{};
};

struct PackedBrushEntity
{
    std::uint16_t entity{};
    std::uint8_t inline_model{};
    std::uint8_t variant_count{};
    std::uint16_t first_variant{};
};

struct PackedBrushStaticVariant
{
    std::uint16_t entity{};
    std::uint16_t geometry_variant{};
};

struct PackedBrushExternalStaticVariant
{
    std::uint16_t entity{};
    std::uint16_t geometry_variant{};
    std::uint8_t slot{};
};

struct PackedBrushActiveGeometry
{
    std::uint8_t slot{};
    std::uint16_t geometry{};
};

struct PackedBrushLink
{
    std::uint16_t fragment{};
    std::uint16_t prior_head{};
    std::uint8_t slot{};
};

struct PackedBrushDirectFragment
{
    std::uint16_t geometry{};
    std::uint16_t fragment{};
    std::uint8_t slot{};
};

enum class PackedBrushTokenKind {
    world,
    leaf_marker,
    brush,
};

struct PackedBrushToken
{
    PackedBrushTokenKind kind{};
    std::uint16_t value{};
};

struct PackedBrushVisualState
{
    std::vector<std::pair<std::uint8_t, std::uint8_t>> transforms;
    std::vector<std::array<std::uint8_t, 3>> textures;
};

struct PackedBrushAssets
{
    std::uint16_t leaf_count{};
    std::size_t external_entity_slot_first{};
    std::size_t external_active_row_bytes{};
    std::vector<PackedBrushSection> sections;
    std::vector<PackedBrushVariant> variants;
    std::vector<PackedBrushBucket> buckets;
    std::vector<PackedBrushFragment> fragments;
    std::vector<PackedBrushFace> faces;
    std::vector<PackedPlane> face_planes;
    std::vector<PackedVertex> vertices;
    std::vector<PackedBrushEntity> entities;
    std::vector<PackedBrushStaticVariant> static_variants;
    std::vector<PackedBrushExternalStaticVariant> external_static_variants;
    std::vector<PackedBrushLink> links;
    std::vector<PackedBrushToken> tokens;
    std::vector<std::uint16_t> active_geometry_by_slot;
};

PackedBrushAssets load_packed_brush_assets(const fs::path& data_dir);

std::uint16_t packed_brush_visual_state_at_pose(const PackedBrushAssets& assets, std::size_t pose);

struct PackedBrushGroupRecord
{
    std::uint16_t leaf{};
    int admitted_fragments{};
    int projected_vertices{};
    int scan_rows{};
    int spans{};
    int max_row_candidates{};
    int max_pixel_candidates{};
};

struct PackedBrushGroupBounds
{
    int groups{};
    int max_admitted_fragments{};
    std::uint16_t admitted_group{0xffff};
    int max_projected_vertices{};
    std::uint16_t projected_group{0xffff};
    int max_scan_rows{};
    std::uint16_t scan_rows_group{0xffff};
    int max_row_candidates{};
    std::uint16_t row_group{0xffff};
    int row{-1};
    int max_pixel_candidates{};
    std::uint16_t pixel_group{0xffff};
    int pixel{-1};
    std::vector<PackedBrushGroupRecord> records;
};

PackedBrushGroupBounds packed_brush_group_bounds(const PackedTextureRaster& raster);

struct PackedBrushOrderingRecord
{
    std::uint16_t leaf{};
    int overlap_pixels{};
    bool winner_cycle{};
    bool pairwise_cycle{};
    int centroid_mismatch_pixels{};
};

struct PackedBrushOrderingAnalysis
{
    int groups{};
    int overlap_groups{};
    int winner_cycle_groups{};
    int pairwise_cycle_groups{};
    int centroid_mismatch_groups{};
    int centroid_mismatch_pixels{};
    std::vector<PackedBrushOrderingRecord> records;
};

PackedBrushOrderingAnalysis
packed_brush_ordering_analysis(const PackedTextureRaster& raster, const PackedBrushGroupBounds& bounds);

PackedTextureRaster render_packed_brush_pipeline(
    SourceWorld world,
    const PacketSelection& packet,
    const Camera& camera,
    std::uint16_t visual_state,
    const fs::path& data_dir,
    PackedBrushAssets assets,
    TextureRasterMode mode = TextureRasterMode::projective_block8,
    double surface_time = 0.0,
    bool external_bsp_enabled = true,
    std::optional<std::size_t> fly_source_pose = std::nullopt,
    bool fly_static_brushes = true
);

PackedTextureRaster render_direct_qbsf_brush_authority(
    SourceWorld world,
    const PacketSelection& packet,
    const Camera& camera,
    std::uint16_t visual_state,
    const fs::path& data_dir,
    const PackedBrushAssets& assets
);

} // namespace quake_bsp_reference
