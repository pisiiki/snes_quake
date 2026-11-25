#pragma once

#include "world.hpp"

namespace quake_bsp_reference {

inline constexpr int kQuakeTurbulenceCycle = 128;
inline constexpr int kQuakeTurbulenceSpeed = 20;
inline constexpr int kQuakeTurbulenceTextureSize = 64;

struct PackedTextureRaster;

inline thread_local std::optional<std::uint8_t> active_turbulence_phase;
class QuakeTurbulencePhaseScope
{
  public:
    explicit QuakeTurbulencePhaseScope(std::uint8_t phase)
    :
    previous_(active_turbulence_phase)
    {
        active_turbulence_phase = phase & 127U;
    }
    ~QuakeTurbulencePhaseScope()
    {
        active_turbulence_phase = previous_;
    }
    QuakeTurbulencePhaseScope(const QuakeTurbulencePhaseScope&) = delete;
    QuakeTurbulencePhaseScope& operator=(const QuakeTurbulencePhaseScope&) = delete;

  private:
    std::optional<std::uint8_t> previous_;
};
std::uint8_t quake_turbulence_phase(double surface_time);

const std::array<std::uint8_t, kQuakeTurbulenceCycle>& source_quake_turbulence_table();

std::uint8_t sample_source_turbulent_texture(const MipTexture& texture, double s, double t, double surface_time);

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
