#include "tests_reports.hpp"
#include "world.hpp"
#include "geometry.hpp"
#include "brushes.hpp"
#include "audio.hpp"
#include "external_models.hpp"
#include "aliases.hpp"
#include "textured_live.hpp"
#include "packed_brushes.hpp"
#include "ordered_replay.hpp"
#include "artifacts_options.hpp"
#include "alias_tests.hpp"
#include "sky_tests.hpp"

namespace quake_bsp_reference {

namespace {
bool run_surface_visibility_self_test()
{
    SourceWorld world;
    world.origin = {0, 0, 0};
    world.bounds_min = {-64, -64, -64};
    world.bounds_max = {64, 64, 64};
    world.face_count = 2;
    world.visibility_planes = {
        Plane{{-1, 0, 0}, -10},
        Plane{{1, 0, 0}, 10},
    };
    constexpr std::array<FaceColor, 2> colors = {FaceColor{3, 0x43}, FaceColor{6, 0x76}};
    const std::array<Vec3, 4> vertices = {Vec3{10, -64, -64}, Vec3{10, 64, -64}, Vec3{10, 64, 64}, Vec3{10, -64, 64}};
    for (std::uint16_t face = 0; face < 2; ++face)
    {
        for (const auto indices : {std::array<int, 3>{0, 1, 2}, std::array<int, 3>{0, 2, 3}})
        {
            world.triangles.push_back(
                make_test_triangle(vertices[indices[0]], vertices[indices[1]], vertices[indices[2]], face, colors[face])
            );
        }
    }
    const Bvh bvh(world.triangles);
    const auto front = render_reference(world, bvh, {0, 0, 0, 0, 0}, false);
    const auto back = render_reference(world, bvh, {2, 0, 0, 16, 0}, false);
    if (front.hits != kLogicalPixels || front.misses != 0 || front.unique_faces != 1 || front.visible_faces != 1 ||
        back.hits != kLogicalPixels || back.misses != 0 || back.unique_faces != 1 || back.visible_faces != 1 ||
        std::ranges::any_of(front.faces, [](std::uint16_t face) { return face != 0; }) ||
        std::ranges::any_of(back.faces, [](std::uint16_t face) { return face != 1; }))
    {
        return false;
    }
    for (int y = 0; y < kLogicalHeight; ++y)
    {
        for (int x = 0; x < kLogicalWidth; ++x)
        {
            const auto pixel = logical_pixel_index(x, y);
            const auto front_expected = static_cast<std::uint8_t>(((x ^ y) & 1) ? 4 : 3);
            const auto back_expected = static_cast<std::uint8_t>(((x ^ y) & 1) ? 7 : 6);
            if (front.indices[pixel] != front_expected || back.indices[pixel] != back_expected)
            {
                return false;
            }
        }
    }
    auto comparison_frame = front;
    comparison_frame.material_indices = front.indices;
    SnesFrame exact{front.indices, "self-test", 0};
    const auto exact_comparison = compare_frames(comparison_frame, exact, 0);
    if (!exact_comparison.passed || exact_comparison.exact_pixels != kLogicalPixels)
    {
        return false;
    }
    exact.logical[0] = 0;
    const auto hole_comparison = compare_frames(comparison_frame, exact, 0);
    if (hole_comparison.passed || hole_comparison.snes_hole_pixels != 1)
    {
        return false;
    }
    exact.logical[0] = front.indices[0] == 1 ? 2 : 1;
    const auto palette_comparison = compare_frames(comparison_frame, exact, 0);
    if (!palette_comparison.passed || palette_comparison.palette_mismatch_pixels != 1)
    {
        return false;
    }
    return true;
}
} // namespace

namespace {
bool run_bvh_tie_self_test()
{
    std::vector<Triangle> triangles;
    const FaceColor color{3, 0x43};
    for (std::uint16_t index = 0; index < 7; ++index)
    {
        const double x = 1.0 + index;
        triangles.push_back(
            make_test_triangle({x, 2, 2}, {x, 3, 2}, {x, 2, 3}, static_cast<std::uint16_t>(index + 2), color)
        );
    }
    triangles.push_back(make_test_triangle({10, -2, -2}, {10, 2, -2}, {10, 0, 2}, 1, color));
    const double tied_x = 10.0 + kHitTieEpsilon * 0.5;
    triangles.push_back(make_test_triangle({tied_x, -2, -2}, {tied_x, 2, -2}, {tied_x, 0, 2}, 0, color));
    for (std::uint16_t index = 0; index < 7; ++index)
    {
        const double x = 20.0 + index;
        triangles.push_back(
            make_test_triangle({x, 2, 2}, {x, 3, 2}, {x, 2, 3}, static_cast<std::uint16_t>(index + 9), color)
        );
    }
    const Bvh bvh(triangles);
    const std::vector<std::uint8_t> visible_faces(16, 1);
    const auto hit = bvh.nearest({{0, 0, 0}, {1, 0, 0}}, visible_faces);
    return hit.face == 0 && hit.depth > 10.0 && hit.depth - 10.0 < kHitTieEpsilon;
}
} // namespace

namespace {
bool run_painter_rank_self_test()
{
    const FaceColor near_color{3, 0x43};
    const FaceColor far_color{6, 0x76};
    const std::vector<Triangle> triangles = {
        make_test_triangle({5, -2, -2}, {5, 2, -2}, {5, 0, 2}, 0, near_color),
        make_test_triangle({10, -2, -2}, {10, 2, -2}, {10, 0, 2}, 1, far_color),
    };
    const Bvh bvh(triangles);
    const std::array<std::uint8_t, 2> visible = {1, 1};
    const std::array<int, 2> painter_ranks = {0, 1};
    const Ray ray{{0, 0, 0}, {1, 0, 0}};
    const auto nearest = bvh.nearest(ray, visible);
    const auto painter = bvh.painter(ray, visible, painter_ranks);
    return nearest.face == 0 && nearest.depth == 5.0 && painter.face == 1 && painter.depth == 10.0;
}
} // namespace

namespace {
bool run_packet_selection_self_test()
{
    SourceWorld world;
    world.face_count = 3;
    world.drawable_face_mask = {1, 1, 0};
    const FaceColor color{3, 0x43};
    world.triangles = {
        make_test_triangle({5, -2, -2}, {5, 2, -2}, {5, 0, 2}, 0, color),
        make_test_triangle({10, -2, -2}, {10, 2, -2}, {10, 0, 2}, 1, color),
    };
    const std::array<std::uint8_t, 4> valid = {1, 0, 0, 0};
    const auto packet = parse_packet_selection(valid, world);
    if (packet.source_faces != std::vector<std::uint16_t>{1, 0} || packet.painter_ranks != std::vector<int>{1, 0, -1} ||
        packet.triangles.size() != 2)
    {
        return false;
    }
    const auto rejected = [&](std::span<const std::uint8_t> bytes) {
        try
        {
            static_cast<void>(parse_packet_selection(bytes, world));
            return false;
        }
        catch (const std::runtime_error&)
        {
            return true;
        }
    };
    const std::array<std::uint8_t, 0> empty{};
    const std::array<std::uint8_t, 1> odd = {0};
    const std::array<std::uint8_t, 4> duplicate = {0, 0, 0, 0};
    const std::array<std::uint8_t, 2> escaped = {3, 0};
    const std::array<std::uint8_t, 2> nondrawable = {2, 0};
    return rejected(empty) && rejected(odd) && rejected(duplicate) && rejected(escaped) && rejected(nondrawable);
}
} // namespace

namespace {
bool run_material_layer_self_test()
{
    SourceWorld world;
    world.face_count = 1;
    world.live_base_colors = {
        static_cast<std::uint8_t>((1 << 4U) | 8),
    };
    world.centroids = {{21, 0, 0}};
    world.live_material_palette[0] = {255, 0, 255};
    for (std::size_t index = 1; index < world.live_material_palette.size(); ++index)
    {
        world.live_material_palette[index] = {
            static_cast<std::uint8_t>(index),
            static_cast<std::uint8_t>(index * 2),
            static_cast<std::uint8_t>(index * 3),
        };
    }

    ReferenceFrame checker;
    checker.faces = {0, 0, 0, 0, kMissFace};
    shade_material_frame(checker, world, {0, 0, 0, 0, 0}, false);
    if (checker.material_indices != std::vector<std::uint8_t>{9, 10, 9, 10, 0})
    {
        return false;
    }
    LiveWindowState state;
    state.legacy_material = true;
    update_live_pixels(state, checker, world);
    if (state.pixels != std::vector<std::uint32_t>{0x09121b, 0x0a141e, 0x09121b, 0x0a141e, 0xff00ff})
    {
        return false;
    }
    auto flat = checker;
    shade_material_frame(flat, world, {0, 0, 0, 0, 0}, true);
    if (flat.material_indices != std::vector<std::uint8_t>{10, 10, 10, 10, 0})
    {
        return false;
    }

    world.centroids[0] = {127, 0, 0};
    auto distant = checker;
    shade_material_frame(distant, world, {0, 0, 0, 0, 0}, false);
    return distant.material_indices == std::vector<std::uint8_t>{7, 7, 7, 7, 0};
}
} // namespace

namespace {
bool run_render_mode_self_test()
{
    SourceWorld world;
    for (std::size_t index = 0; index < world.texture_palette.size(); ++index)
    {
        world.texture_palette[index] = {
            static_cast<std::uint8_t>(index),
            static_cast<std::uint8_t>(index),
            static_cast<std::uint8_t>(index),
        };
    }
    world.untextured_palette = make_untextured_palette(world.texture_palette);
    ReferenceFrame frame;
    frame.faces = {0, 0, kMissFace};
    frame.texture_indices = {1, 2, 0};
    frame.lightmap_texture_indices = {5, 6, 0};
    frame.untextured_lightmap_indices = {10, 11, 0};
    if (selected_render_indices(frame, {true, Lighting::None}) != frame.texture_indices ||
        selected_render_indices(frame, {true, Lighting::LightMap}) != frame.lightmap_texture_indices ||
        selected_render_indices(frame, {false, Lighting::LightMap}) != frame.untextured_lightmap_indices)
    {
        return false;
    }
    LiveWindowState state;
    state.mode = {false, Lighting::LightMap};
    update_live_pixels(state, frame, world);
    const auto packed_rgb = [](Rgb color) {
        return (static_cast<std::uint32_t>(color.r) << 16U) | (static_cast<std::uint32_t>(color.g) << 8U) |
               static_cast<std::uint32_t>(color.b);
    };
    if (state.pixels !=
        std::vector<std::uint32_t>{
            packed_rgb(world.untextured_palette[10]),
            packed_rgb(world.untextured_palette[11]),
            packed_rgb(world.untextured_palette[0])
        })
    {
        return false;
    }

    PackedTextureRaster packed;
    packed.indices = frame.texture_indices;
    packed.lightmapped_indices = frame.lightmap_texture_indices;
    packed.untextured_lightmap_indices = frame.untextured_lightmap_indices;
    if (selected_render_indices(packed, {true, Lighting::None}) != packed.indices ||
        selected_render_indices(packed, {true, Lighting::LightMap}) != packed.lightmapped_indices ||
        selected_render_indices(packed, {false, Lighting::LightMap}) != packed.untextured_lightmap_indices)
    {
        return false;
    }
    std::set<std::uint16_t> ramp_colors;
    int previous_red = -1;
    int previous_green = -1;
    int previous_blue = -1;
    for (int index = 0; index < kUntexturedRampColors; ++index)
    {
        const auto color = world.untextured_palette[static_cast<std::size_t>(index)];
        const int red = (color.r * 31 + 127) / 255;
        const int green = (color.g * 31 + 127) / 255;
        const int blue = (color.b * 31 + 127) / 255;
        if (red < previous_red || green < previous_green || blue < previous_blue ||
            std::max({red, green, blue}) - std::min({red, green, blue}) > 1)
        {
            return false;
        }
        previous_red = red;
        previous_green = green;
        previous_blue = blue;
        ramp_colors.insert(snes_color_word(color));
    }
    return ramp_colors.size() == kUntexturedRampColors && world.untextured_palette[64] == Rgb{} &&
           world.untextured_palette[238] == Rgb{} && world.untextured_palette[240] == world.texture_palette[240] &&
           world.untextured_palette[255] == world.texture_palette[255] &&
           world.untextured_palette[kUntexturedDiagnosticIndex] == Rgb{255, 0, 255} &&
           untextured_lightmap_index(0) == 63 &&
           untextured_lightmap_index(63) == 0 && render_mode_name({true, Lighting::None}) == "textures+None" &&
           render_mode_name({false, Lighting::LightMap}) == "untextured+LightMap" &&
           render_mode_technique({true, Lighting::None}) == 2 &&
           render_mode_technique({true, Lighting::LightMap}) == 4 &&
           render_mode_technique({false, Lighting::LightMap}) == 7 &&
           is_supported_render_mode({true, Lighting::None}) &&
           is_supported_render_mode({true, Lighting::LightMap}) &&
           is_supported_render_mode({false, Lighting::LightMap}) &&
           !is_supported_render_mode({false, Lighting::None}) &&
           packed_render_contract({true, Lighting::None}, false) ==
               "packed-gsu-q4-projective-block8-albedo-v1" &&
           packed_render_contract({true, Lighting::LightMap}, false) ==
               "packed-gsu-q4-projective-block8-lightmap-v1" &&
           packed_render_contract({false, Lighting::LightMap}, true) ==
               "packed-gsu-q4-projective-block8-enabled-brush-"
               "untextured-lightmap-v1";
}
} // namespace

namespace {
bool run_exact_texture_self_test()
{
    SourceWorld world;
    world.face_count = 1;
    world.visibility_planes = {Plane{{1, 0, 0}, 10}};
    world.face_texture_infos = {0};
    world.texture_infos = {
        TextureInfo{{0, 1, 0}, 0, {0, 0, 1}, 0, 0},
    };
    world.textures = {
        MipTexture{"test", 2, 2, {10, 11, 12, 13}, true},
    };
    const auto negative = sample_exact_texture(world, 0, Ray{{0, -0.25, -1.25}, {1, 0, 0}});
    const auto positive = sample_exact_texture(world, 0, Ray{{0, 2.25, 3.75}, {1, 0, 0}});
    const auto center = sample_exact_texture(world, 0, Ray{{0, 0, 0}, {1, 0, 0}});
    const auto edge = sample_exact_texture(world, 0, Ray{{0, 0, 0}, {1, 0.75, 0}});
    const auto corner = sample_exact_texture(world, 0, Ray{{0, 0, 0}, {1, 0.75, 0.5}});

    BrushScene scene;
    scene.texture_animations.resize(1);
    BrushModelGeometry brush_model;
    BrushFace brush_face;
    brush_face.plane = world.visibility_planes[0];
    brush_face.texture_info = 0;
    brush_model.faces = {brush_face};
    const auto brush_center = sample_brush_texture(world, scene, brush_model, 0, Ray{{0, 0, 0}, {1, 0, 0}}, 0, 0.0);
    const auto brush_edge = sample_brush_texture(world, scene, brush_model, 0, Ray{{0, 0, 0}, {1, 0.75, 0}}, 0, 0.0);
    const auto brush_corner =
        sample_brush_texture(world, scene, brush_model, 0, Ray{{0, 0, 0}, {1, 0.75, 0.5}}, 0, 0.0);
    return negative.index == 11 && positive.index == 12 && std::abs(negative.distance - 0.625) < 1e-12 &&
           std::abs(positive.distance - 0.625) < 1e-12 && std::abs(center.distance - edge.distance) < 1e-12 &&
           std::abs(center.distance - corner.distance) < 1e-12 && std::abs(center.distance - 0.625) < 1e-12 &&
           std::abs(brush_center.distance - brush_edge.distance) < 1e-12 &&
           std::abs(brush_center.distance - brush_corner.distance) < 1e-12 &&
           std::abs(brush_center.distance - 0.625) < 1e-12 && snes_color_word({255, 0, 255}) == 0x7c1f;
}
} // namespace

namespace {
bool run_bsp_lightmap_self_test()
{
    SourceWorld world;
    FaceLightmap lit;
    lit.width = 2;
    lit.height = 2;
    lit.light_offset = 0;
    lit.styles = {0, 255, 255, 255};
    lit.style_count = 1;
    FaceLightmap unlit;
    auto special = unlit;
    special.missing_level = 0;
    auto multiple_styles = lit;
    multiple_styles.light_offset = 4;
    multiple_styles.styles = {32, 0, 255, 255};
    multiple_styles.style_count = 2;
    world.face_lightmaps = {lit, unlit, multiple_styles, special};
    world.lighting = {255, 0, 0, 255, 64, 64, 64, 64, 64, 64, 64, 64};
    for (std::size_t level = 0; level < world.texture_colormap.size(); ++level)
    {
        for (std::size_t index = 0; index < kQuakePaletteColors; ++index)
        {
            world.texture_colormap[level][index] = static_cast<std::uint8_t>(index);
        }
    }
    world.texture_colormap[30][17] = 42;
    world.texture_colormap[63][17] = 0;
    auto escaped = world;
    escaped.face_lightmaps[0].light_offset = 9;
    bool rejected_escape = false;
    try
    {
        static_cast<void>(sample_bsp_lightmap_level(escaped, 0, 0, 0));
    }
    catch (const std::runtime_error&)
    {
        rejected_escape = true;
    }
    return sample_bsp_lightmap_level(world, 0, 0, 0) == 0 && sample_bsp_lightmap_level(world, 0, 16, 0) == 63 &&
           sample_bsp_lightmap_level(world, 0, 8, 8) == 30 && sample_bsp_lightmap_level(world, 1, 8, 8) == 63 &&
           sample_bsp_lightmap_level(world, 2, 5, 11) == 30 && sample_bsp_lightmap_level(world, 3, 8, 8) == 0 &&
           remap_texture_index(world, 17, sample_bsp_lightmap_level(world, 1, 8, 8), 0) == 0 &&
           remap_texture_index(world, 17, sample_bsp_lightmap_level(world, 3, 8, 8), 0) == 17 &&
           remap_texture_index(world, 17, 30, 0) == 42 && remap_texture_index(world, 17, 0, 0) == 17 &&
           untextured_lightmap_index(0) == 63 && untextured_lightmap_index(30) == 33 &&
           untextured_lightmap_index(sample_bsp_lightmap_level(world, 1, 8, 8)) == 0 && rejected_escape;
}
} // namespace

namespace {
bool run_packed_brush_compact_lightmap_self_test()
{
    SourceWorld world;
    FaceLightmap lightmap;
    lightmap.width = 2;
    lightmap.height = 2;
    lightmap.light_offset = 0;
    lightmap.styles = {0, 255, 255, 255};
    lightmap.style_count = 1;
    lightmap.precombined_compact_levels = true;
    world.face_lightmaps = {lightmap};
    world.lighting = {56, 54, 56, 54};

    return exact_lightmap_colormap_is_identity() && sample_packed_bsp_lightmap_level(world, 0, 0, 0) == 56 &&
           sample_packed_bsp_lightmap_level(world, 0, 48, 240) == 56 &&
           sample_packed_bsp_lightmap_level(world, 0, 256, 0) == 54;
}
} // namespace

namespace {
bool run_packed_brush_ordering_self_test()
{
    PackedTextureRaster raster;
    raster.projected_fragments = {
        {7, 1, 4, 50, 10, 2, 100},
        {7, 2, 4, 60, 11, 2, 101},
    };
    raster.candidate_samples = {
        {7, 1, 0, 40},
        {7, 2, 0, 50},
        {7, 1, 1, 60},
        {7, 2, 1, 50},
    };
    PackedBrushGroupBounds bounds;
    bounds.records.push_back({7, 2, 8, 1, 2, 2, 2});

    const auto analysis = packed_brush_ordering_analysis(raster, bounds);
    return analysis.groups == 1 && analysis.overlap_groups == 1 && analysis.winner_cycle_groups == 1 &&
           analysis.pairwise_cycle_groups == 1 && analysis.centroid_mismatch_groups == 1 &&
           analysis.centroid_mismatch_pixels == 1;
}
} // namespace

namespace {
bool run_packed_texture_span_self_test()
{
    SourceWorld world;
    for (auto& row : world.texture_colormap)
    {
        for (std::size_t index = 0; index < kQuakePaletteColors; ++index)
        {
            row[index] = static_cast<std::uint8_t>(index);
        }
    }
    world.face_lightmaps.resize(10);
    world.face_lightmaps[9].width = 1;
    world.face_lightmaps[9].height = 1;
    world.face_lightmaps[9].light_offset = 0;
    world.face_lightmaps[9].styles = {0, 255, 255, 255};
    world.face_lightmaps[9].style_count = 1;
    world.face_lightmaps[9].precombined_compact_levels = true;
    world.lighting = {1};
    const auto make_raster = [] {
        PackedTextureRaster result;
        result.indices.resize(kLogicalPixels);
        result.lightmapped_indices.resize(kLogicalPixels);
        result.lightmap_levels.resize(kLogicalPixels);
        result.untextured_lightmap_indices.assign(kLogicalPixels, kUntexturedDiagnosticIndex);
        result.faces.resize(kLogicalPixels, kMissFace);
        result.entities.resize(kLogicalPixels);
        result.models.resize(kLogicalPixels);
        result.s_q4.resize(kLogicalPixels);
        result.t_q4.resize(kLogicalPixels);
        result.absolute_s_q4.resize(kLogicalPixels);
        result.absolute_t_q4.resize(kLogicalPixels);
        result.depth_q6.resize(kLogicalPixels);
        result.arbitration_groups.resize(kLogicalPixels, 0xffff);
        result.arbitration_depth_q6.resize(kLogicalPixels);
        result.turbulent_pixels.resize(kLogicalPixels);
        return result;
    };
    auto raster = make_raster();
    const MipTexture texture{"packed", 4, 2, {0, 1, 2, 3, 4, 5, 6, 7}, true};
    draw_packed_texture_span_projective(raster, world, texture, 9, 5, 10, 14, 1344, 1856, 0, 0, 64, 0, 64, 64);
    const auto pixel = [](int x, int y) { return logical_pixel_index(x, y); };
    const bool simple_span_passed =
        raster.indices[pixel(10, 5)] == 0 && raster.indices[pixel(11, 5)] == 1 && raster.indices[pixel(12, 5)] == 2 &&
        raster.indices[pixel(13, 5)] == 3 && raster.indices[pixel(14, 5)] == 0 &&
        raster.lightmap_levels[pixel(10, 5)] == 1 &&
        raster.untextured_lightmap_indices[pixel(10, 5)] == 62 && raster.faces[pixel(12, 5)] == 9 &&
        raster.s_q4[pixel(13, 5)] == 48 && raster.stats.span_calls == 1 && raster.spans.size() == 1 &&
        raster.spans.front().face == 9 && raster.spans.front().first_x == 10 && raster.spans.front().right_s_q4 == 64;
    if (!simple_span_passed)
    {
        return false;
    }

    MipTexture split_texture{"split", 32, 1, std::vector<std::uint8_t>(32), true};
    for (std::size_t index = 0; index < split_texture.level_zero.size(); ++index)
    {
        split_texture.level_zero[index] = static_cast<std::uint8_t>(index);
    }
    auto affine = make_raster();
    auto projective = make_raster();
    draw_packed_texture_span_affine(affine, world, split_texture, 9, 6, 0, 16, 64, 2112, 0, 0, 256, 0, 64, 128);
    draw_packed_texture_span_projective(
        projective,
        world,
        split_texture,
        9,
        6,
        0,
        16,
        64,
        2112,
        0,
        0,
        256,
        0,
        64,
        128
    );
    auto degenerate = make_raster();
    draw_packed_texture_span_projective(
        degenerate,
        world,
        split_texture,
        9,
        7,
        3,
        3,
        448,
        448,
        16,
        0,
        128,
        0,
        64,
        128
    );
    return affine.absolute_s_q4[pixel(8, 6)] == 128 && projective.absolute_s_q4[pixel(8, 6)] == 85 &&
           affine.indices[pixel(8, 6)] == 8 && projective.indices[pixel(8, 6)] == 5 &&
           projective.depth_q6[pixel(8, 6)] > 64 && projective.depth_q6[pixel(8, 6)] < 128 &&
           degenerate.absolute_s_q4[pixel(3, 7)] == 16 && degenerate.depth_q6[pixel(3, 7)] == 64;
}
} // namespace

namespace {
bool run_texture_mapping_fidelity_self_test()
{
    SourceWorld world;
    world.textures.push_back({"fidelity", 8, 4, std::vector<std::uint8_t>(32), true});
    world.texture_infos.resize(1);
    world.face_texture_infos.resize(10);

    ReferenceFrame source;
    source.faces.resize(kLogicalPixels, kMissFace);
    source.texture_indices.resize(kLogicalPixels);
    source.texture_s.resize(kLogicalPixels);
    source.texture_t.resize(kLogicalPixels);
    PackedTextureRaster packed;
    packed.faces.resize(kLogicalPixels, kMissFace);
    packed.indices.resize(kLogicalPixels);
    packed.absolute_s_q4.resize(kLogicalPixels);
    packed.absolute_t_q4.resize(kLogicalPixels);
    const auto pixel = [](int x) { return logical_pixel_index(x, 5); };
    for (int x = 10; x <= 12; ++x)
    {
        source.faces[pixel(x)] = 9;
        packed.faces[pixel(x)] = 9;
    }
    source.texture_s[pixel(10)] = 0.0;
    source.texture_s[pixel(11)] = 1.0;
    source.texture_s[pixel(12)] = 2.0;
    packed.absolute_s_q4[pixel(10)] = 0;
    packed.absolute_s_q4[pixel(11)] = 31;
    packed.absolute_s_q4[pixel(12)] = 65;
    source.texture_indices[pixel(10)] = 1;
    source.texture_indices[pixel(11)] = 2;
    source.texture_indices[pixel(12)] = 3;
    packed.indices[pixel(10)] = 1;
    packed.indices[pixel(11)] = 2;
    packed.indices[pixel(12)] = 4;
    source.faces[pixel(13)] = 9;

    const auto fidelity = compare_texture_mapping_fidelity(world, source, packed);
    return fidelity.owner_match_pixels == kLogicalPixels - 1 && fidelity.owner_mismatch_pixels == 1 &&
           fidelity.comparable_pixels == 3 && fidelity.exact_texel_pixels == 2 &&
           fidelity.within_one_texel_pixels == 2 && fidelity.within_two_texel_pixels == 2 &&
           fidelity.within_four_texel_pixels == 3 && fidelity.max_s_error_q4 == 33 && fidelity.max_t_error_q4 == 0 &&
           fidelity.first_beyond_two_texels == static_cast<int>(pixel(12)) && fidelity.first_beyond_four_texels == -1 &&
           fidelity.first_face == 9 && fidelity.first_source_s_q4 == 32 && fidelity.first_packed_s_q4 == 65 &&
           fidelity.first_source_index == 3 && fidelity.first_packed_index == 4;
}
} // namespace

namespace {
bool run_quantized_world_self_test()
{
    SourceWorld world;
    world.face_count = 1;
    world.visibility_planes.resize(1);
    world.packed_visibility_planes = {{64, 0, 0, 0}};
    if (!face_is_visible(world, {-1, 0, 0, 0, 0}, {}, 0) || face_is_visible(world, {1, 0, 0, 0, 0}, {}, 0))
    {
        return false;
    }
    world.plane_cull_guard_mask = {1};
    if (!face_is_visible(world, {1, 0, 0, 0, 0}, {}, 0))
    {
        return false;
    }
    world.plane_cull_guard_mask.clear();
    // The runtime subtracts in signed 16 bits. This case is negative only
    // after the positive mathematical result wraps through 0xffff.
    world.packed_visibility_planes = {{64, 64, 64, -32768}};
    if (!face_is_visible(world, {127, 127, 127, 0, 0}, {}, 0))
    {
        return false;
    }

    const FaceColor color{3, 0x43};
    const std::array<Vec3, 4> collapsed = {Vec3{0, 0, 0}, Vec3{0, 0, 0}, Vec3{1, 0, 0}, Vec3{0, 0, 0}};
    append_face_triangles(world, collapsed, 0, color);
    if (!world.triangles.empty())
    {
        return false;
    }
    const std::array<Vec3, 4> drawable = {Vec3{0, 0, 0}, Vec3{1, 0, 0}, Vec3{1, 1, 0}, Vec3{0, 1, 0}};
    append_face_triangles(world, drawable, 0, color);
    return world.triangles.size() == 2;
}
} // namespace

namespace {
bool run_current_pipeline_self_test()
{
    SourceWorld world;
    world.face_count = 1;
    world.live_material_palette = kPalette;
    world.live_base_colors = {0};
    world.centroids = {{8, 0, 0}};
    world.packed_vertices = {
        {8, -2, -2},
        {8, 2, -2},
        {8, 0, 2},
    };
    world.face_vertex_ids = {{0, 1, 2}};
    world.reciprocal_table.resize(1024);
    for (std::size_t depth_q4 = 4; depth_q4 < world.reciprocal_table.size(); ++depth_q4)
    {
        world.reciprocal_table[depth_q4] =
            static_cast<std::uint16_t>(std::lround(24576.0 / static_cast<double>(depth_q4)));
    }
    PacketSelection packet;
    packet.source_faces = {0};
    const Camera camera{};
    const auto center = project_packed_vertex(world, {8, 0, 0}, camera);
    const auto raster = render_current_pipeline(world, packet, camera, false, 0, false);
    const auto center_pixel = logical_pixel_index(64, 56);
    return center.state == 1 && center.screen.x == 64 && center.screen.y == 56 &&
           raster.frame.faces[center_pixel] == 0 && raster.stats.fan_triangles == 1 && raster.stats.plot_writes > 0;
}
} // namespace

namespace {
bool run_span_endpoint_self_test()
{
    RasterResult raster;
    raster.frame.faces.resize(kLogicalPixels, kMissFace);
    raster_span_band(raster, 10, 12, 20, 20, 40, 48, 7, 0, true);
    const auto owner = [&](int x, int y) { return raster.frame.faces[logical_pixel_index(x, y)]; };
    return owner(20, 10) == 7 && owner(40, 10) == 7 && owner(48, 12) == 7 && owner(49, 12) == kMissFace &&
           raster.stats.span_calls == 7;
}
} // namespace

namespace {
bool run_demo_timing_self_test()
{
    const std::vector<std::uint16_t> ticks{0, 3, 3, 5};
    return demo_pose_at_tick(ticks, 0) == 0 && demo_pose_at_tick(ticks, 2) == 0 && demo_pose_at_tick(ticks, 3) == 2 &&
           demo_pose_at_tick(ticks, 5) == 3;
}
} // namespace

namespace {
bool run_precise_demo_self_test()
{
    const auto view = source_view_transform({{1.0, 2.0, 3.0}, 0.0, 0.0, 0.0});
    const auto close = [](double left, double right) { return std::abs(left - right) < 1e-12; };
    const auto half_advanced = 10.0 + playback_source_delta(1.0, PlaybackSpeed::Half);
    const auto step_indices = step_demo_pose_indices(2086, 20);
    std::size_t ordered_pose = 0;
    const auto ordered_first = advance_ordered_demo_pose(step_indices.size(), ordered_pose);
    const auto ordered_second = advance_ordered_demo_pose(step_indices.size(), ordered_pose);
    ordered_pose = step_indices.size() - 1U;
    const auto ordered_wrap = advance_ordered_demo_pose(step_indices.size(), ordered_pose);
    advance_ordered_demo_pose(1484, ordered_pose, 10);
    const bool stride_advanced = ordered_pose == 10;
    ordered_pose = 1480;
    const auto stride_wrap = advance_ordered_demo_pose(1484, ordered_pose, 10);
    double early_deadline = 0.499;
    const bool early_advance = consume_ordered_demo_deadline(0.5, true, early_deadline);
    double exact_deadline = 0.5;
    const bool exact_advance = consume_ordered_demo_deadline(0.5, true, exact_deadline);
    double unpresented_deadline = 0.75;
    const bool unpresented_advance = consume_ordered_demo_deadline(0.5, false, unpresented_deadline);
    return constant_step_pose_at_time(4, 0.0, 30.0) == 0 && constant_step_pose_at_time(4, 0.032, 30.0) == 0 &&
           constant_step_pose_at_time(4, 0.034, 30.0) == 1 && constant_step_pose_at_time(4, 0.067, 30.0) == 2 &&
           constant_step_pose_at_time(4, 10.0, 30.0) == 3 && constant_step_pose_at_time(4, 0.499, 2.0) == 0 &&
           constant_step_pose_at_time(4, 0.5, 2.0) == 1 && close(constant_step_duration(2226, 30.0), 74.2) &&
           close(playback_speed_scale(PlaybackSpeed::Realtime), 1.0) &&
           close(playback_speed_scale(PlaybackSpeed::Half), 0.5) &&
           close(playback_speed_scale(PlaybackSpeed::Quarter), 0.25) &&
           close(10.0 + playback_source_delta(1.0, PlaybackSpeed::Realtime), 11.0) && close(half_advanced, 10.5) &&
           close(half_advanced + playback_source_delta(1.0, PlaybackSpeed::Quarter), 10.75) &&
           close(constant_step_duration(2226, 30.0) / playback_speed_scale(PlaybackSpeed::Half), 148.4) &&
           close(constant_step_duration(2226, 30.0) / playback_speed_scale(PlaybackSpeed::Quarter), 296.8) &&
           close(constant_step_duration(step_indices.size(), 2.0), 104.5) && step_indices.size() == 209 &&
           step_indices[1] == 10 && step_indices.back() == 2080 && ordered_first.advanced && !ordered_first.wrapped &&
           ordered_second.advanced && !ordered_second.wrapped && ordered_wrap.advanced && ordered_wrap.wrapped &&
           ordered_pose == 0 && stride_advanced && stride_wrap.advanced && stride_wrap.wrapped && ordered_pose == 0 &&
           !early_advance && close(early_deadline, 0.499) && exact_advance && close(exact_deadline, 0.0) &&
           !unpresented_advance && close(unpresented_deadline, 0.75) && close(view.origin.x, 1.0) &&
           close(view.origin.y, 2.0) && close(view.origin.z, 3.0) && close(view.forward.x, 1.0) &&
           close(view.forward.y, 0.0) && close(view.forward.z, 0.0) && close(view.screen_right.x, 0.0) &&
           close(view.screen_right.y, -1.0) && close(view.screen_right.z, 0.0) && close(view.up.x, 0.0) &&
           close(view.up.y, 0.0) && close(view.up.z, 1.0);
}
} // namespace

namespace {
bool run_packed_alias_occlusion_self_test()
{
    AliasAssets assets;
    assets.sprites = {
        {16, 16, -8, 8, std::vector<std::uint8_t>(std::size_t{16} * 16U, 4)},
        {16, 16, -8, 8, std::vector<std::uint8_t>(std::size_t{16} * 16U, 5)},
    };
    AliasRow row;
    row.dynamic_states = {
        {0, {16, 0, 0}},
        {1, {8, 0, 0}},
    };
    row.tokens = {{false, 0}, {false, 1}};
    assets.rows.push_back(std::move(row));
    std::vector<std::uint8_t> opaque(kLogicalPixels, 3);
    std::vector<std::int16_t> depth(kLogicalPixels, std::numeric_limits<std::int16_t>::max());
    const auto occluded = logical_pixel_index(64, 56);
    const auto visible = occluded + 1;
    depth[occluded] = 128;
    depth[visible] = 129;
    AliasCoverage coverage;
    AliasVisibilityRow visibility_row;
    const auto composed = compose_post_opaque_alias_indices(
        opaque,
        depth,
        Camera{},
        assets,
        0,
        RenderMode{true, Lighting::LightMap},
        &coverage,
        &visibility_row
    );
    return composed[occluded] == opaque[occluded] && composed[visible] == 5 && coverage.packed_plot_pixels > 0 &&
           coverage.packed_visible_pixels > 0 && coverage.packed_opaque_occluded_pixels > 0 &&
           visibility_row.tokens.size() == 2 &&
           std::ranges::any_of(visibility_row.tokens[0].candidates, [](std::uint8_t value) { return value == 0; }) &&
           std::ranges::any_of(visibility_row.tokens[0].candidates, [](std::uint8_t value) { return value == 1; }) &&
           coverage.packed_visible_pixels + coverage.packed_opaque_occluded_pixels == coverage.packed_plot_pixels;
}
} // namespace

namespace {
bool run_alias_inspection_self_test()
{
    AliasAssets assets;
    assets.sprites = {
        {8, 8, -4, 4, std::vector<std::uint8_t>(std::size_t{8} * 8U, 4)},
        {8, 8, -4, 4, std::vector<std::uint8_t>(std::size_t{8} * 8U, 5)},
    };
    AliasRow row;
    row.dynamic_states = {{0, {8, 0, 0}}, {1, {16, 0, 0}}};
    row.tokens = {{false, 0, 7, 9}, {false, 1, 11, 13}};
    assets.rows.push_back(std::move(row));
    std::vector<std::uint8_t> opaque(kLogicalPixels, 3);
    std::vector<std::int16_t> depth(kLogicalPixels, std::numeric_limits<std::int16_t>::max());
    AliasCoverage coverage;
    const auto composed = compose_post_opaque_alias_indices(
        opaque,
        depth,
        Camera{},
        assets,
        0,
        RenderMode{true, Lighting::LightMap},
        &coverage
    );
    const auto inspection = packed_alias_inspection(Camera{}, assets, 0, coverage);
    return inspection.at("available").get<bool>() && composed.at(56 * kLogicalWidth + 64) == 4 &&
           inspection.at("aliases").size() == 2 &&
           inspection.at("orderingContract") == "global-depth-q6-far-to-near-stable-token-ties" &&
           inspection.at("aliases").at(0).at("paintOrdinal") == 0 &&
           inspection.at("aliases").at(0).at("tokenOrdinal") == 1 &&
           inspection.at("aliases").at(0).at("group").at("leaf") == 11 &&
           inspection.at("aliases").at(1).at("paintOrdinal") == 1 &&
           inspection.at("aliases").at(1).at("tokenOrdinal") == 0 &&
           inspection.at("aliases").at(1).at("group").at("parent") == 9 &&
           inspection.at("aliases").at(0).at("pixels").at("overwrittenByAlias") == 144 &&
           inspection.at("aliases").at(0).at("pixels").at("finalOwned") == 0 &&
           inspection.at("aliases").at(1).at("pixels").at("overwroteAlias") == 144 &&
           inspection.at("aliases").at(1).at("pixels").at("finalOwned") == 576 &&
           inspection.at("summary").at("aliasOverwritePairs") == 1 &&
           inspection.at("summary").at("fartherOverNearerPixels") == 0 &&
           inspection.at("overwrites").at(0).at("earlierToken") == 1 &&
           inspection.at("overwrites").at(0).at("laterToken") == 0 &&
           inspection.at("overwrites").at(0).at("pixels") == 144 &&
           inspection.at("overwrites").at(0).at("fartherOverNearer") == false;
}
} // namespace

namespace {
bool run_alias_order_self_test()
{
    AliasAssets assets;
    AliasRow row;
    row.dynamic_states = {{0, {8, 0, 0}}, {0, {16, 0, 0}}, {0, {16, 0, 0}}};
    row.tokens = {{false, 0, 7, 9}, {false, 1, 11, 13}, {false, 2, 5, 3}};
    assets.rows.push_back(std::move(row));
    const auto views = ordered_packed_alias_views(Camera{}, assets, 0);
    return views.size() == 3 && views[0].token == 1 && views[1].token == 2 && views[2].token == 0 &&
           views[0].depth_q6 == views[1].depth_q6 && views[1].depth_q6 > views[2].depth_q6;
}
} // namespace

namespace {
bool run_alias_visibility_encoding_self_test()
{
    OrderedPackedReplay replay;
    replay.source_pose_count = 11;
    replay.source_rate = 20;
    replay.step_rate = 20;
    replay.stride = 1;
    for (std::uint16_t pose = 0; pose < replay.source_pose_count; ++pose)
    {
        replay.frames.push_back({pose, {}, {}});
    }
    AliasAssets aliases;
    aliases.camera_fingerprint = 0x1122334455667788ULL;
    aliases.package_fingerprint = 0x8877665544332211ULL;
    aliases.rows.resize(replay.source_pose_count);
    aliases.rows[0].tokens = {{false, 0}, {false, 1}};
    aliases.rows[10].tokens = {{false, 0}};
    std::vector<AliasVisibilityRow> rows(replay.source_pose_count);
    rows[0].tokens = {{{1, 1}}, {{1, 0, 1}}};
    rows[10].tokens = {{{0, 0}}};
    const auto encoded = encode_ordered_alias_visibility(replay, aliases, rows, true);
    const auto directory = read_u32(encoded, 28);
    const auto dictionary = directory + replay.source_pose_count * 2U;
    const auto first = read_u16(encoded, dictionary);
    const auto last = read_u16(encoded, dictionary + 2U);
    return encoded.size() == kAliasVisibilityHalfbankBytes &&
           std::equal(encoded.begin(), encoded.begin() + 4, "QAV2") &&
           read_u16(encoded, 4) == kAliasVisibilityVersion && read_u16(encoded, 8) == 11 &&
           read_u16(encoded, 10) == 11 && read_u16(encoded, 12) == 1 && read_u16(encoded, 16) == 20 &&
           read_u16(encoded, 20) == 1 && read_u16(encoded, 26) == 2 && read_u16(encoded, directory) == 0x11 &&
           read_u16(encoded, directory + 2U) == 0 && read_u16(encoded, directory + 10U * 2U) == 0x21 &&
           encoded[first] == 1 && encoded[first + 1] == kAliasVisibilityPartial && read_u16(encoded, first + 2) == 3 &&
           encoded[first + 4] == 5 && encoded[last] == 0 && encoded[last + 1] == kAliasVisibilityHidden &&
           read_u16(encoded, last + 2) == 2 && alias_read_u64(encoded, 40) == aliases.camera_fingerprint &&
           alias_read_u64(encoded, 48) == aliases.package_fingerprint;
}
} // namespace

bool run_self_test()
{
    const bool ordered_rates =
        supported_ordered_replay_step_rate(2) && supported_ordered_replay_step_rate(20) &&
        !supported_ordered_replay_step_rate(1) && !supported_ordered_replay_step_rate(10) &&
        std::abs(constant_step_duration(209, 2.0) - 104.5) < 1e-9 &&
        std::abs(constant_step_duration(2086, 20.0) - 104.3) < 1e-9 &&
        constant_step_pose_at_time(2086, 104.25, 20.0) == 2085;
    return run_brush_reference_self_test() && run_quake_audio_self_test() && run_external_bsp_replay_self_test() &&
           run_surface_visibility_self_test() && run_bvh_tie_self_test() && run_painter_rank_self_test() &&
           run_packet_selection_self_test() && run_material_layer_self_test() && run_render_mode_self_test() &&
           run_exact_texture_self_test() && run_bsp_lightmap_self_test() &&
           run_packed_brush_compact_lightmap_self_test() &&
           run_packed_brush_ordering_self_test() && run_packed_texture_span_self_test() &&
           run_texture_mapping_fidelity_self_test() && run_quantized_world_self_test() &&
           run_current_pipeline_self_test() &&
           run_span_endpoint_self_test() && run_demo_timing_self_test() && run_precise_demo_self_test() &&
           run_packed_alias_occlusion_self_test() && run_packed_alias_projection_self_test() &&
           run_alias_order_self_test() && run_alias_inspection_self_test() && run_quake_sky_self_test() &&
           run_alias_visibility_encoding_self_test() && ordered_rates;
}

} // namespace quake_bsp_reference
