#include "sky_tests.hpp"
#include "world.hpp"
#include "geometry.hpp"
#include "sky.hpp"

namespace quake_bsp_reference {

namespace {
MipTexture make_quake_sky_self_test_texture(std::uint8_t background)
{
    MipTexture texture{
        "sky_self_test",
        kQuakeSkySourceWidth,
        kQuakeSkySourceHeight,
        std::vector<std::uint8_t>(
            static_cast<std::size_t>(kQuakeSkySourceWidth) * static_cast<std::size_t>(kQuakeSkySourceHeight)
        ),
        true
    };
    for (int y = 0; y < kQuakeSkySize; ++y)
    {
        for (int x = 0; x < kQuakeSkySize; ++x)
        {
            texture.level_zero[row_major_index(kQuakeSkySize + x, y, kQuakeSkySourceWidth)] = background;
        }
    }
    return texture;
}
} // namespace

namespace {
bool run_quake_sky_mask_self_test()
{
    auto texture = make_quake_sky_self_test_texture(37);
    constexpr int y = 7;
    constexpr int transparent_x = 11;
    constexpr int foreground_x = 12;
    texture.level_zero[row_major_index(foreground_x, y, kQuakeSkySourceWidth)] = 91;

    const auto tile = make_quake_sky_tile(texture, quake_sky_clock(0.0));
    const auto row = row_major_index(0, y, kQuakeSkyRowBytes);
    return tile.indices[row + transparent_x] == 37 && tile.indices[row + foreground_x] == 91 &&
           tile.indices[row + kQuakeSkySize + transparent_x] == 37 &&
           tile.indices[row + kQuakeSkySize + foreground_x] == 37;
}
} // namespace

namespace {
bool run_quake_sky_motion_self_test()
{
    auto background = make_quake_sky_self_test_texture(0);
    auto foreground = make_quake_sky_self_test_texture(200);
    for (int y = 0; y < kQuakeSkySize; ++y)
    {
        for (int x = 0; x < kQuakeSkySize; ++x)
        {
            const auto left = row_major_index(x, y, kQuakeSkySourceWidth);
            const auto right = left + kQuakeSkySize;
            background.level_zero[left] = 0;
            background.level_zero[right] = static_cast<std::uint8_t>(129 + x % 100);
            foreground.level_zero[left] = static_cast<std::uint8_t>(1 + x % 127);
        }
    }

    const auto clock0 = quake_sky_clock(0.0);
    const auto clock1 = quake_sky_clock(1.0);
    const auto background0 = make_quake_sky_tile(background, clock0);
    const auto background1 = make_quake_sky_tile(background, clock1);
    const auto foreground0 = make_quake_sky_tile(foreground, clock0);
    const auto foreground1 = make_quake_sky_tile(foreground, clock1);
    const auto phase0 = static_cast<std::int32_t>(clock0.projected_phase * 65536.0F);
    const auto phase1 = static_cast<std::int32_t>(clock1.projected_phase * 65536.0F);

    return clock1.projected_phase == 8.0F && clock1.composite_shift == 8 &&
           quake_sky_sample(background0, phase0, phase0) == 129 &&
           quake_sky_sample(background1, phase1, phase1) == 137 && quake_sky_sample(foreground0, phase0, phase0) == 1 &&
           quake_sky_sample(foreground1, phase1, phase1) == 17;
}
} // namespace

namespace {
bool run_quake_sky_clock_self_test()
{
    const auto zero = quake_sky_clock(0.0);
    const auto wrapped_zero = quake_sky_clock(512.0);
    const auto first = quake_sky_clock(1.25);
    const auto repeated = quake_sky_clock(513.25);
    constexpr double actual_origin = 1.3801482915878296;
    const auto actual_first = quake_sky_clock(actual_origin);
    const auto actual_repeated = quake_sky_clock(actual_origin + kQuakeSkyRepeatSeconds);
    const auto last_eighth = quake_sky_clock(511.875);
    const auto texture = make_quake_sky_self_test_texture(73);

    return wrapped_zero.wrapped_time == zero.wrapped_time && wrapped_zero.projected_phase == zero.projected_phase &&
           wrapped_zero.composite_shift == zero.composite_shift && first.wrapped_time == repeated.wrapped_time &&
           first.projected_phase == repeated.projected_phase && first.composite_shift == repeated.composite_shift &&
           actual_first.wrapped_time == actual_repeated.wrapped_time &&
           actual_first.projected_phase == actual_repeated.projected_phase &&
           actual_first.composite_shift == actual_repeated.composite_shift && last_eighth.projected_phase == 4095.0F &&
           last_eighth.composite_shift == 127 &&
           make_quake_sky_tile(texture, zero).indices == make_quake_sky_tile(texture, wrapped_zero).indices;
}
} // namespace

namespace {
bool run_quake_sky_projection_self_test()
{
    const auto clock = quake_sky_clock(0.0);
    const ViewTransform centered{{}, {1, 0, 0}, {0, 1, 0}, {0, 0, 1}};
    const auto center = quake_sky_uv_to_st(centered, kLogicalWidth / 2, kLogicalHeight / 2, clock);
    if (center[0] != kQuakeSkyProjectionScale * 65536 || center[1] != 0)
    {
        return false;
    }

    const ViewTransform negative_x{{}, {-1, 0, 1}, {0, 1, 0}, {0, 0, 1}};
    const auto projected_negative = quake_sky_uv_to_st(negative_x, kLogicalWidth / 2, kLogicalHeight / 2, clock);
    float expected_x = -4096.0F;
    const float expected_z = 4096.0F * 3.0F;
    const float expected_magnitude = std::sqrt(expected_x * expected_x + expected_z * expected_z);
    const float expected_inverse_magnitude = 1.0F / expected_magnitude;
    expected_x *= expected_inverse_magnitude;
    const float expected_fixed = (static_cast<float>(kQuakeSkyProjectionScale) * expected_x) * 65536.0F;
    const auto expected_negative = static_cast<std::int32_t>(expected_fixed);
    if (projected_negative[0] != expected_negative ||
        expected_negative != static_cast<std::int32_t>(std::ceil(expected_fixed)) || projected_negative[1] != 0)
    {
        return false;
    }

    const ViewTransform negative_y{{}, {0, -1, 0}, {1, 0, 0}, {0, 0, 1}};
    const auto wrapped = quake_sky_uv_to_st(negative_y, kLogicalWidth / 2, kLogicalHeight / 2, clock);
    QuakeSkyTile tile;
    for (int y = 0; y < kQuakeSkySize; ++y)
    {
        for (int x = 0; x < kQuakeSkySize; ++x)
        {
            tile.indices[row_major_index(x, y, kQuakeSkyRowBytes)] = static_cast<std::uint8_t>(y + 1);
        }
    }
    return wrapped[0] == 0 && wrapped[1] == -kQuakeSkyProjectionScale * 65536 &&
           quake_sky_sample(tile, wrapped[0], wrapped[1]) == 7;
}
} // namespace

namespace {
bool run_quake_sky_span_partition_self_test()
{
    QuakeSkyTile tile;
    for (int y = 0; y < kQuakeSkySize; ++y)
    {
        for (int x = 0; x < kQuakeSkySize; ++x)
        {
            tile.indices[row_major_index(x, y, kQuakeSkyRowBytes)] =
                static_cast<std::uint8_t>((y * 17 + x * 3) % 251 + 1);
        }
    }
    const ViewTransform view{{}, {1, 0, 0}, {0, 1, 0}, {0, 0, 1}};
    const auto clock = quake_sky_clock(0.0);
    std::vector<std::uint8_t> indices(kLogicalPixels);
    constexpr int y = kLogicalHeight / 2;
    draw_quake_sky_span(indices, tile, view, clock, y, 0, 32);

    const auto start = quake_sky_uv_to_st(view, 0, y, clock);
    const auto boundary = quake_sky_uv_to_st(view, 32, y, clock);
    const auto direct31 = quake_sky_uv_to_st(view, 31, y, clock);
    const auto s_step = quake_sky_arithmetic_shift5(boundary[0] - start[0]);
    const auto t_step = quake_sky_arithmetic_shift5(boundary[1] - start[1]);
    const auto interpolated31 = quake_sky_sample(tile, start[0] + 31 * s_step, start[1] + 31 * t_step);
    const auto projected31 = quake_sky_sample(tile, direct31[0], direct31[1]);
    const auto exact32 = quake_sky_sample(tile, boundary[0], boundary[1]);
    const auto pixel = [](int x) { return logical_pixel_index(x, y); };

    return interpolated31 != projected31 && indices[pixel(31)] == interpolated31 && indices[pixel(32)] == exact32 &&
           indices[pixel(33)] == 0;
}
} // namespace

namespace {
SourceWorld make_quake_sky_presentation_self_test_world()
{
    SourceWorld world;
    world.face_count = 1;
    world.face_sky_mask = {1};
    world.face_texture_infos = {0};
    world.texture_infos = {TextureInfo{{}, 0, {}, 0, 0}};
    auto texture = make_quake_sky_self_test_texture(77);
    for (int y = 0; y < kQuakeSkySize; ++y)
    {
        for (int x = 0; x < kQuakeSkySize; ++x)
        {
            texture.level_zero[row_major_index(x, y, kQuakeSkySourceWidth)] = 91;
        }
    }
    world.textures = {std::move(texture)};
    return world;
}
} // namespace

namespace {
bool run_quake_sky_presentation_self_test()
{
    const auto world = make_quake_sky_presentation_self_test_world();
    std::vector<std::uint8_t> base_a(kLogicalPixels, 17);
    std::vector<std::uint8_t> base_b(kLogicalPixels, 203);
    std::vector<std::uint8_t> base_c(kLogicalPixels, 44);
    std::vector<std::uint16_t> faces(kLogicalPixels, kMissFace);
    std::vector<std::uint16_t> entities(kLogicalPixels);
    constexpr int y = 4;
    const ViewTransform view{{}, {1, 0, 0}, {0, 1, 0}, {0, 0, 1}};
    const auto empty = render_quake_sky_presentation(base_a, faces, entities, world, view, 0.0, "self-test-empty");
    if (empty.indices != base_a || empty.inspection.at("skyPixels").get<int>() != 0 ||
        empty.inspection.at("skySpans").get<int>() != 0)
    {
        return false;
    }
    for (int x = 8; x <= 10; ++x)
    {
        faces[logical_pixel_index(x, y)] = 0;
    }
    const auto rendered_a = render_quake_sky_presentation(base_a, faces, entities, world, view, 0.0, "self-test-a");
    const auto rendered_b = render_quake_sky_presentation(base_b, faces, entities, world, view, 0.0, "self-test-b");
    const auto rendered_c = render_quake_sky_presentation(base_c, faces, entities, world, view, 0.0, "self-test-c");
    const auto pixel = [](int x, int row) { return logical_pixel_index(x, row); };
    for (std::size_t index = 0; index < kLogicalPixels; ++index)
    {
        const bool sky_pixel = index >= pixel(8, y) && index <= pixel(10, y);
        if ((sky_pixel && (rendered_a.indices[index] != 91 || rendered_a.indices[index] != rendered_b.indices[index] ||
                           rendered_a.indices[index] != rendered_c.indices[index])) ||
            (!sky_pixel && (rendered_a.indices[index] != base_a[index] || rendered_b.indices[index] != base_b[index] ||
                            rendered_c.indices[index] != base_c[index])))
        {
            return false;
        }
    }
    return rendered_a.indices[pixel(7, y)] == 17 && rendered_b.indices[pixel(7, y)] == 203 &&
           rendered_c.indices[pixel(7, y)] == 44 && rendered_a.inspection.at("skyPixels").get<int>() == 3 &&
           rendered_a.inspection.at("skySpans").get<int>() == 1 &&
           std::ranges::all_of(base_a, [](std::uint8_t value) { return value == 17; }) &&
           std::ranges::all_of(base_b, [](std::uint8_t value) { return value == 203; }) &&
           std::ranges::all_of(base_c, [](std::uint8_t value) { return value == 44; });
}
} // namespace

namespace {
bool run_quake_sky_malformed_miptex_self_test()
{
    const auto rejected = [](const MipTexture& texture) {
        try
        {
            require_quake_sky_texture(texture);
        }
        catch (const std::runtime_error&)
        {
            return true;
        }
        return false;
    };
    auto missing = make_quake_sky_self_test_texture(1);
    missing.present = false;
    auto narrow = make_quake_sky_self_test_texture(1);
    narrow.width = kQuakeSkySourceWidth - 1;
    auto short_texture = make_quake_sky_self_test_texture(1);
    short_texture.level_zero.pop_back();
    if (!rejected(missing) || !rejected(narrow) || !rejected(short_texture))
    {
        return false;
    }

    auto world = make_quake_sky_presentation_self_test_world();
    world.textures.front().height = kQuakeSkySourceHeight - 1;
    std::vector<std::uint8_t> base(kLogicalPixels);
    std::vector<std::uint16_t> faces(kLogicalPixels, kMissFace);
    std::vector<std::uint16_t> entities(kLogicalPixels);
    faces.front() = 0;
    const ViewTransform view{{}, {1, 0, 0}, {0, 1, 0}, {0, 0, 1}};
    try
    {
        static_cast<void>(render_quake_sky_presentation(base, faces, entities, world, view, 0.0, "self-test"));
    }
    catch (const std::runtime_error&)
    {
        return true;
    }
    return false;
}
} // namespace

bool run_quake_sky_self_test()
{
    return run_quake_sky_mask_self_test() && run_quake_sky_motion_self_test() && run_quake_sky_clock_self_test() &&
           run_quake_sky_projection_self_test() && run_quake_sky_span_partition_self_test() &&
           run_quake_sky_presentation_self_test() && run_quake_sky_malformed_miptex_self_test();
}

} // namespace quake_bsp_reference
