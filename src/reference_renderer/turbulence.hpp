#pragma once

#include "world.hpp"

namespace quake_bsp_reference {

inline constexpr int kQuakeTurbulenceCycle = 128;
inline constexpr int kQuakeTurbulenceSpeed = 20;
inline constexpr int kQuakeTurbulenceTextureSize = 64;

struct PackedTextureRaster;

std::uint8_t quake_turbulence_phase(double surface_time);

std::pair<int, int> quake_turbulent_texel_coordinates(
    int s_q4,
    int t_q4,
    std::uint8_t phase,
    const std::array<std::uint8_t, kQuakeTurbulenceCycle>& table
);

std::uint8_t sample_quake_turbulent_texture(
    const MipTexture& texture,
    int s_q4,
    int t_q4,
    std::uint8_t phase,
    const std::array<std::uint8_t, kQuakeTurbulenceCycle>& table
);

Json quake_turbulence_inspection(const PackedTextureRaster& raster);

} // namespace quake_bsp_reference
