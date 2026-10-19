#include "turbulence.hpp"
#include "textured_live.hpp"

namespace quake_bsp_reference {

const std::array<std::uint8_t, kQuakeTurbulenceCycle>& source_quake_turbulence_table()
{
    // Frozen with quake_bsp_turbulence.py: never depend on platform libm rounding.
    static constexpr auto table = [] {
        constexpr std::array<int, 33> quarter{
            0,  6,  13,  19,  25,  31,  37,  43,  49,  55,  60,  66,  71,  76,  81,  86, 91,
            95, 99, 103, 106, 110, 113, 116, 118, 121, 122, 124, 126, 127, 127, 128, 128
        };
        std::array<std::uint8_t, kQuakeTurbulenceCycle> result{};
        for (int i = 0; i < kQuakeTurbulenceCycle; ++i)
        {
            const int sine =
                i <= 32   ? quarter[i]
                : i <= 64 ? quarter[64 - i]
                : i <= 96 ? -quarter[i - 64]
                          : -quarter[128 - i];
            result[i] = static_cast<std::uint8_t>(std::clamp(128 + sine, 0, 255));
        }
        return result;
    }();
    return table;
}

std::uint8_t sample_source_turbulent_texture(const MipTexture& texture, double s, double t, double surface_time)
{
    const auto q4 = [](double coordinate) {
        if (!std::isfinite(coordinate))
        {
            fail("source turbulent UV must be finite");
        }
        // Keep the sine's 128-texel period, not just the texture's 64 texels.
        // Reduce before conversion so negative and very large UVs cannot overflow.
        return static_cast<int>(std::floor(std::fmod(coordinate, 128.0) * 16.0));
    };
    return sample_quake_turbulent_texture(
        texture,
        q4(s),
        q4(t),
        quake_turbulence_phase(surface_time),
        source_quake_turbulence_table()
    );
}

std::uint8_t quake_turbulence_phase(double surface_time)
{
    if (!std::isfinite(surface_time) || surface_time < 0.0)
    {
        fail("Quake turbulence time must be finite and nonnegative");
    }
    const double phase = surface_time * kQuakeTurbulenceSpeed;
    if (!std::isfinite(phase))
        fail("Quake turbulence phase exceeds finite time storage");
    return static_cast<std::uint8_t>(std::fmod(phase, kQuakeTurbulenceCycle));
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
