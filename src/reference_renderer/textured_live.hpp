#pragma once

#include "world.hpp"
#include "geometry.hpp"

namespace quake_bsp_reference {

struct TexturedViewVertex
{
    ViewVertex view;
    std::int16_t s_q4{};
    std::int16_t t_q4{};
};

struct TexturedFixedPoint
{
    int x_q7{};
    int y_q7{};
    std::int16_t s_q4{};
    std::int16_t t_q4{};
    std::int16_t depth_q6{};
};

struct PackedTextureSpan
{
    std::uint16_t face{};
    std::uint16_t arbitration_group{0xffff};
    std::uint32_t candidate_serial{};
    int y{};
    int first_x{};
    int last_x{};
    std::int16_t left_s_q4{};
    std::int16_t left_t_q4{};
    std::int16_t right_s_q4{};
    std::int16_t right_t_q4{};
    int left_x_q7{};
    int right_x_q7{};
    std::int16_t left_depth_q6{};
    std::int16_t right_depth_q6{};
};

struct PackedBrushProjectedFragment
{
    std::uint16_t arbitration_group{};
    std::uint32_t candidate_serial{};
    std::uint8_t projected_vertices{};
    std::int16_t centroid_depth_q6{};
    std::uint16_t entity{};
    std::uint16_t model{};
    std::uint16_t source_face{};
};

struct PackedBrushCandidateSample
{
    std::uint16_t arbitration_group{};
    std::uint32_t candidate_serial{};
    std::uint16_t pixel{};
    std::int16_t depth_q6{};
};

struct PackedTextureRaster
{
    std::vector<std::uint8_t> indices;
    std::vector<std::uint8_t> lightmapped_indices;
    std::vector<std::uint8_t> lightmap_levels;
    std::vector<std::uint8_t> untextured_lightmap_indices;
    std::vector<std::uint16_t> faces;
    std::vector<std::uint16_t> entities;
    std::vector<std::uint16_t> models;
    std::vector<std::int16_t> s_q4;
    std::vector<std::int16_t> t_q4;
    std::vector<std::int16_t> absolute_s_q4;
    std::vector<std::int16_t> absolute_t_q4;
    std::vector<std::int16_t> depth_q6;
    std::vector<std::uint16_t> arbitration_groups;
    std::vector<std::int16_t> arbitration_depth_q6;
    std::vector<std::uint8_t> turbulent_pixels;
    std::vector<PackedTextureSpan> spans;
    std::vector<PackedBrushProjectedFragment> projected_fragments;
    std::vector<PackedBrushCandidateSample> candidate_samples;
    RasterStats stats;
    int hits{};
    int misses{};
    int unique_faces{};
    std::uint16_t current_source_face{kMissFace};
    std::uint16_t current_entity{};
    std::uint16_t current_model{};
    std::uint16_t current_arbitration_group{};
    std::uint32_t current_candidate_serial{};
    bool current_depth_arbitration{};
    std::uint8_t turbulence_phase{};
};

enum class TextureRasterMode {
    affine,
    projective_block8,
};

std::int16_t perspective_interpolate_i16(
    std::int16_t first,
    std::int16_t second,
    int first_depth,
    int second_depth,
    int numerator,
    int denominator
);

void draw_packed_texture_span_affine(
    PackedTextureRaster& result,
    const SourceWorld& world,
    const MipTexture& texture,
    std::uint16_t face,
    int y,
    int first_x,
    int last_x,
    int left_x_q7,
    int right_x_q7,
    std::int16_t left_s_q4,
    std::int16_t left_t_q4,
    std::int16_t right_s_q4,
    std::int16_t right_t_q4,
    std::int16_t left_depth_q6,
    std::int16_t right_depth_q6
);

void draw_packed_texture_span_projective(
    PackedTextureRaster& result,
    const SourceWorld& world,
    const MipTexture& texture,
    std::uint16_t face,
    int y,
    int first_x,
    int last_x,
    int left_x_q7,
    int right_x_q7,
    std::int16_t left_s_q4,
    std::int16_t left_t_q4,
    std::int16_t right_s_q4,
    std::int16_t right_t_q4,
    std::int16_t left_depth_q6,
    std::int16_t right_depth_q6
);

void raster_packed_texture_polygon(
    PackedTextureRaster& result,
    const SourceWorld& world,
    std::span<const TexturedViewVertex> view_polygon,
    const MipTexture& texture,
    std::uint16_t face,
    TextureRasterMode mode
);

PackedTextureRaster render_packed_texture_pipeline(
    const SourceWorld& world,
    const PacketSelection& packet,
    const Camera& camera,
    TextureRasterMode mode,
    double surface_time = 0.0
);

struct ViewPoint
{
    double right{};
    double up{};
    double depth{};
};

RasterResult render_convex_counterfactual(
    const SourceWorld& world,
    const PacketSelection& packet,
    const Camera& camera,
    bool flat,
    bool front_to_back
);

const std::vector<std::uint8_t>& selected_render_indices(const ReferenceFrame& frame, RenderMode mode);

const std::vector<std::uint8_t>& selected_render_indices(const PackedTextureRaster& frame, RenderMode mode);

std::string render_mode_name(RenderMode mode);

std::string packed_render_contract(RenderMode mode, bool brushes);

std::vector<std::uint8_t> select_live_indices(const ReferenceFrame& frame, RenderMode mode, bool legacy_material);

struct LiveRenderResult
{
    std::vector<std::uint8_t> indices;
    Json alias_inspection{
        {"schema", "quake-reference-alias-inspection-v1"},
        {"available", false},
        {"reason", "this playback path has no packed alias diagnostics"}
    };
    Json surface_inspection{
        {"schema", "quake-reference-surface-inspection-v1"},
        {"available", false},
        {"reason", "this playback path has no dynamic surface diagnostics"}
    };
    Json external_bsp_inspection{
        {"schema", "quake-reference-external-bsp-inspection-v2"},
        {"available", false},
        {"reason", "this playback path has no external BSP replay"}
    };
};

void update_live_pixels(LiveWindowState& state, std::span<const std::uint8_t> indices, const SourceWorld& world);

void update_live_pixels(LiveWindowState& state, const ReferenceFrame& frame, const SourceWorld& world);

} // namespace quake_bsp_reference
