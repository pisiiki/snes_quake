#include "turbulence.hpp"
#include "textured_live.hpp"

namespace quake_bsp_reference {

std::uint8_t quake_turbulence_phase(double surface_time)
{
    if (!std::isfinite(surface_time) || surface_time < 0.0)
    {
        fail("Quake turbulence time must be finite and nonnegative");
    }
    return static_cast<std::uint8_t>(
        static_cast<std::uint64_t>(surface_time * kQuakeTurbulenceSpeed) & (kQuakeTurbulenceCycle - 1)
    );
}

std::pair<int, int> quake_turbulent_texel_coordinates(
    int s_q4,
    int t_q4,
    std::uint8_t phase,
    const std::array<std::uint8_t, kQuakeTurbulenceCycle>& table
)
{
    const int s_displacement = table[static_cast<std::size_t>(((t_q4 >> 4) + phase) & 127)];
    const int t_displacement = table[static_cast<std::size_t>(((s_q4 >> 4) + phase) & 127)];
    return {((s_q4 + s_displacement) >> 4) & 63, ((t_q4 + t_displacement) >> 4) & 63};
}

std::uint8_t sample_quake_turbulent_texture(
    const MipTexture& texture,
    int s_q4,
    int t_q4,
    std::uint8_t phase,
    const std::array<std::uint8_t, kQuakeTurbulenceCycle>& table
)
{
    if (!texture.turbulent || texture.width != kQuakeTurbulenceTextureSize ||
        texture.height != kQuakeTurbulenceTextureSize ||
        texture.level_zero.size() !=
            static_cast<std::size_t>(kQuakeTurbulenceTextureSize) *
                static_cast<std::size_t>(kQuakeTurbulenceTextureSize))
    {
        fail("Quake turbulent sampler requires a flagged 64x64 level zero");
    }
    const auto [s, t] = quake_turbulent_texel_coordinates(s_q4, t_q4, phase, table);
    return texture.level_zero.at(row_major_index(s, t, kQuakeTurbulenceTextureSize));
}

Json quake_turbulence_inspection(const PackedTextureRaster& raster)
{
    std::uint64_t hash = 14695981039346656037ULL;
    std::set<std::uint16_t> faces;
    std::size_t pixels = 0;
    for (std::size_t pixel = 0; pixel < raster.turbulent_pixels.size(); ++pixel)
    {
        if (raster.turbulent_pixels[pixel] == 0)
        {
            continue;
        }
        ++pixels;
        faces.insert(raster.faces[pixel]);
        hash = (hash ^ raster.indices[pixel]) * 1099511628211ULL;
    }
    std::ostringstream encoded_hash;
    encoded_hash << std::hex << std::setfill('0') << std::setw(16) << hash;
    return Json{
        {"schema", "quake-reference-turbulence-inspection-v1"},
        {"available", true},
        {"phase", raster.turbulence_phase},
        {"pixelCount", pixels},
        {"faces", faces},
        {"indexFnv1a64", encoded_hash.str()},
        {"palettePolicy", "fullbright-level-zero"}
    };
}

} // namespace quake_bsp_reference
