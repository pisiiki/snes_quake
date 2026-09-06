#include "alias_tests.hpp"
#include "world.hpp"
#include "geometry.hpp"
#include "aliases.hpp"

namespace quake_bsp_reference {

bool run_packed_alias_projection_self_test()
{
    const auto off_left = project_packed_alias_axis(-1514, -1446, 74, 8192, false, kLogicalWidth);
    const auto off_right = project_packed_alias_axis(1446, 1514, 74, 8192, false, kLogicalWidth);
    const auto clipped_left = project_packed_alias_axis(-192, -124, 256, 8192, false, kLogicalWidth);
    const auto clipped_right = project_packed_alias_axis(124, 192, 256, 8192, false, kLogicalWidth);
    const auto vertical = project_packed_alias_axis(96, -108, 256, 7168, true, kLogicalHeight);

    AliasAssets assets;
    AliasSprite left_sprite{17, 51, 0, 0, std::vector<std::uint8_t>(std::size_t{17} * 51U)};
    AliasSprite right_sprite{17, 51, -1, 0, std::vector<std::uint8_t>(std::size_t{17} * 51U)};
    for (std::size_t y = 0; y < 51; ++y)
    {
        for (std::size_t x = 0; x < 17; ++x)
        {
            left_sprite.pixels[y * 17 + x] = static_cast<std::uint8_t>(x);
            right_sprite.pixels[y * 17 + x] = static_cast<std::uint8_t>(x);
        }
    }
    assets.sprites = {std::move(left_sprite), std::move(right_sprite)};
    AliasRow row;
    // With the identity camera these become depth=256, up=96, and the
    // horizontal component pairs exercised above.
    row.dynamic_states = {{0, {16, -12, 6}}, {1, {16, 8, 6}}};
    row.tokens = {{false, 0}, {false, 1}};
    assets.rows.push_back(std::move(row));

    std::uint8_t left_first_texel = 0xffU;
    std::uint8_t right_last_texel = 0xffU;
    for_each_packed_alias_pixel(
        Camera{},
        assets,
        0,
        [&](std::size_t pixel, int, std::uint8_t texel, std::size_t token) {
            if (pixel == logical_pixel_index(0, 20) && token == 0)
            {
                left_first_texel = texel;
            }
            if (pixel == logical_pixel_index(127, 20) && token == 1)
            {
                right_last_texel = texel;
            }
        }
    );

    const bool octants =
        alias_directional_view(64, 0) == 0 && alias_directional_view(64, 64) == 1 &&
        alias_directional_view(0, 64) == 2 && alias_directional_view(-64, 64) == 3 &&
        alias_directional_view(-64, 0) == 4 && alias_directional_view(-64, -64) == 5 &&
        alias_directional_view(0, -64) == 6 && alias_directional_view(64, -64) == 7;
    const bool nearest_boundary = alias_directional_view(64, 26) == 0 && alias_directional_view(64, 27) == 1;
    const AliasState directional{
        static_cast<std::uint16_t>(kAliasDirectionalTag | 8U),
        {0, 0, 0},
        0,
        64,
    };
    const bool resolved =
        alias_resolved_sprite_id(directional, -64, 0) == 8 && alias_resolved_sprite_id(directional, 0, -64) == 10;
    auto pickup = directional;
    pickup.yaw_sin_q6 = -128;
    bool rotation = true;
    for (int phase = 0; phase < 8; ++phase)
    {
        const auto yaw = static_cast<std::uint8_t>(phase * 32);
        rotation &= alias_resolved_sprite_id(pickup, -64, 0, yaw) == 8U + ((8 - phase) & 7);
        rotation &= alias_resolved_sprite_id(directional, -64, 0, yaw) == 8;
    }

    return !off_left.visible && off_left.last_pixel < 0 && !off_right.visible &&
           off_right.first_pixel >= kLogicalWidth && off_left.span_q7 == off_right.span_q7 && clipped_left.visible &&
           clipped_left.clipped && clipped_left.first_pixel < 0 && clipped_right.visible && clipped_right.clipped &&
           clipped_right.last_pixel >= kLogicalWidth && vertical.visible && !vertical.clipped &&
           clipped_left.span_q7 == clipped_right.span_q7 && clipped_left.span_q7 * 51 == vertical.span_q7 * 17 &&
           left_first_texel == 5 && right_last_texel == 11 && octants && nearest_boundary && resolved && rotation;
}

} // namespace quake_bsp_reference
