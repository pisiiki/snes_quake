#pragma once

#include "x2_weapon.hpp"

namespace quake_bsp_reference {

inline std::vector<std::uint8_t> gameplay_x3_visible(
    std::span<std::uint8_t> plane, const X2WeaponAssets& weapon,
    std::uint16_t weapon_word, int first_software_pose, int source_height,
    std::span<const std::uint16_t, 256> colors)
{
    const int height = source_height == 67 ? 200 : 224;
    const int pose = weapon_word & 255;
    const int bob = static_cast<std::int8_t>(weapon_word >> 8);
    if ((source_height != 67 && source_height != 74) || plane.size() != kLogicalPixels)
        fail("invalid visible X3 source extent");
    std::vector<std::uint8_t> overlay(kLogicalPixels);
    weapon.for_each_opaque(pose, bob, [&](std::size_t pos, std::uint8_t color) {
        overlay.at(pos) = color;
    });
    if (pose >= first_software_pose)
        for (int cy = 0; cy < source_height; ++cy)
            for (int cx = 0; cx < 85; ++cx)
                if (const auto ink = overlay[(3 * cy / 2) * kLogicalWidth + 127 - 3 * cx / 2])
                    plane[cy * kLogicalWidth + 84 - cx] = ink;
    std::vector<std::uint8_t> output(256 * height * 2);
    for (int y = 0; y < height; ++y)
    {
        for (int x = 0; x < 256; ++x)
        {
            const int cell = x / 3;
            std::uint8_t color = x < 255 && y / 3 < source_height
                ? plane[(y / 3) * kLogicalWidth + 84 - cell] : 0;
            if (pose && pose < first_software_pose)
            {
                // Hardware OBJ pixels keep their physical 2x scale.
                if (const auto ink = overlay[(y / 2) * kLogicalWidth + 127 - x / 2])
                    color = ink;
            }
            const auto word = colors[color];
            const auto offset = 2 * (256 * y + x);
            output[offset] = static_cast<std::uint8_t>(word);
            output[offset + 1] = static_cast<std::uint8_t>(word >> 8);
        }
    }
    return output;
}

} // namespace quake_bsp_reference
