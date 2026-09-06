#pragma once

#include "world.hpp"
#include "geometry.hpp"
#include "textured_live.hpp"

namespace quake_bsp_reference {

void write_quake_sky_artifacts(
    const fs::path& indices_path,
    std::span<const std::uint8_t> indices,
    const Json& inspection
);

void write_reference_outputs(const fs::path& prefix, const ReferenceFrame& frame, const SourceWorld& world);

void write_brush_ownership_outputs(const fs::path& prefix, const ReferenceFrame& frame);

void write_raster_outputs(const fs::path& prefix, const RasterResult& result, const SourceWorld& world);

void write_packed_texture_outputs(const fs::path& prefix, const PackedTextureRaster& result, const SourceWorld& world);

void write_packed_brush_outputs(const fs::path& prefix, const PackedTextureRaster& result, const SourceWorld& world);

void write_owner_diff(
    const fs::path& path,
    const ReferenceFrame& before,
    const ReferenceFrame& after,
    std::span<const Rgb> palette
);

struct PackedAudit
{
    int records{};
    int drawable_records{};
    int color_mismatches{};
    int material_records{};
    int material_record_mismatches{};
    int distance_lut_mismatches{};
    int shade_pair_mismatches{};
};

PackedAudit audit_packed_colors(const fs::path& data_dir, const SourceWorld& world);

struct SnesFrame
{
    std::vector<std::uint8_t> logical;
    std::string format;
    int bad_2x2{};
};

SnesFrame load_snes_frame(const fs::path& path, std::span<const Rgb> palette);

struct Comparison
{
    std::string input_format;
    int bad_2x2{};
    int exact_pixels{};
    int snes_hole_pixels{};
    int snes_false_geometry_pixels{};
    int palette_mismatch_pixels{};
    int geometry_palette_match_pixels{};
    bool passed{};
};

struct PackedTextureComparison
{
    int exact_pixels{};
    int different_pixels{};
    int first_mismatch{-1};
    int expected_index{-1};
    int actual_index{-1};
};

struct TextureMappingFidelity
{
    int owner_match_pixels{};
    int owner_mismatch_pixels{};
    int comparable_pixels{};
    int exact_texel_pixels{};
    int within_one_texel_pixels{};
    int within_two_texel_pixels{};
    int within_four_texel_pixels{};
    std::int64_t total_s_error_q4{};
    std::int64_t total_t_error_q4{};
    int max_s_error_q4{};
    int max_t_error_q4{};
    int first_beyond_two_texels{-1};
    int first_beyond_four_texels{-1};
    std::uint16_t first_face{kMissFace};
    std::int64_t first_source_s_q4{};
    std::int64_t first_source_t_q4{};
    int first_packed_s_q4{};
    int first_packed_t_q4{};
    int first_s_error_q4{};
    int first_t_error_q4{};
    int first_source_index{-1};
    int first_packed_index{-1};
};

TextureMappingFidelity compare_texture_mapping_fidelity(
    const SourceWorld& world,
    const ReferenceFrame& source,
    const PackedTextureRaster& packed
);

PackedTextureComparison
compare_packed_texture_indices(const PackedTextureRaster& expected, std::span<const std::uint8_t> actual);

Comparison compare_frames(const ReferenceFrame& reference, const SnesFrame& snes, int allowed_holes);

void write_diff(
    const fs::path& path,
    const ReferenceFrame& reference,
    const SnesFrame& snes,
    std::span<const Rgb> palette
);

struct Options
{
    fs::path pak;
    std::string map_entry{"maps/e1m3.bsp"};
    fs::path data_dir;
    fs::path packet_source_faces;
    fs::path output_prefix;
    fs::path json_path;
    fs::path snes_frame;
    fs::path snes_texture_indices;
    fs::path packed_albedo_indices;
    fs::path packed_lightmap_indices;
    fs::path packed_lightmap_levels;
    fs::path packed_render_indices;
    fs::path brush_albedo_indices;
    fs::path brush_lightmap_indices;
    fs::path brush_render_indices;
    fs::path packed_brush_albedo_indices;
    fs::path packed_brush_lightmap_indices;
    fs::path packed_brush_render_indices;
    fs::path packed_alias_render_indices;
    fs::path quake_sky_indices;
    fs::path fly_alias_render_indices;
    fs::path realtime_demo_track;
    fs::path brush_replay;
    fs::path external_bsp_replay;
    fs::path sound_replay;
    fs::path alias_assets;
    fs::path ordered_replay;
    fs::path ordered_alias_visibility;
    fs::path packed_realtime_demo_track;
    fs::path realtime_demo_timing;
    std::string instrumentation_session;
    std::string instrumentation_pipe;
    Camera camera{-46, -80, -7, 24, 0};
    std::string camera_label{"spawn"};
    int allowed_holes{};
    int demo_pose{-1};
    int fly_source_pose{};
    int alias_yaw_q8{};
    double surface_time{};
    bool surface_time_override{};
    bool flat{};
    bool no_textures{};
    bool material_view{};
    PlaybackSpeed playback_speed{PlaybackSpeed::Realtime};
    Lighting lighting{Lighting::LightMap};
    bool ordered_2hz{};
    bool ordered_fast{};
    int ordered_presentation_hz{2};
    bool no_brushes{};
    bool no_entities{};
    bool external_bsp_models{};
    bool no_sound{};
    float volume{0.7F};
    bool self_test{};
    bool report_only{};
};

struct RawOptionValues
{
    std::string preset;
    std::string lighting{"lightmap"};
    std::string playback_speed{"realtime"};
    std::vector<int> camera;
    CLI::Option* surface_time_option{};
};

struct OptionFacts
{
    bool precise_demo{};
    bool brush_demo{};
    bool packed_demo{};
    bool static_fly{};
    bool ordered_sky{};
    bool fly_sky{};
    bool packed_brush_indices{};
    bool brush_indices{};
    bool raw_indices{};
};

Options parse_options(int argc, char** argv);

Triangle
make_test_triangle(const Vec3& first, const Vec3& second, const Vec3& third, std::uint16_t face, FaceColor color);

} // namespace quake_bsp_reference
