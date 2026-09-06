#pragma once

#include "world.hpp"
#include "geometry.hpp"

namespace quake_bsp_reference {

inline constexpr int kQuakeSkySize = 128;
inline constexpr int kQuakeSkySourceWidth = 256;
inline constexpr int kQuakeSkySourceHeight = 128;
inline constexpr int kQuakeSkyRowBytes = 256;
inline constexpr int kQuakeSkySpanMaximum = 32;
inline constexpr int kQuakeSkySpeed = 8;
inline constexpr int kQuakeSkySecondarySpeed = 2;
inline constexpr int kQuakeSkyProjectionScale = 6 * (kQuakeSkySize / 2 - 1);
inline constexpr float kQuakeSkyRepeatSeconds = 512.0F;
inline constexpr std::uint32_t kQuakeSkyFixedMask = 0x007F0000U;

struct QuakeSkyClock
{
    double surface_time{};
    float wrapped_time{};
    float projected_phase{};
    int composite_shift{};
};

struct QuakeSkyTile
{
    std::array<std::uint8_t, static_cast<std::size_t>(kQuakeSkyRowBytes) * kQuakeSkySourceHeight> indices{};
};

struct QuakeSkyPresentation
{
    std::vector<std::uint8_t> indices;
    Json inspection;
};

QuakeSkyClock quake_sky_clock(double surface_time);

void require_quake_sky_texture(const MipTexture& texture);

QuakeSkyTile make_quake_sky_tile(const MipTexture& texture, const QuakeSkyClock& clock);

std::array<std::int32_t, 2> quake_sky_uv_to_st(const ViewTransform& view, int u, int v, const QuakeSkyClock& clock);

int quake_sky_arithmetic_shift5(std::int32_t value);

std::uint8_t quake_sky_sample(const QuakeSkyTile& tile, std::int32_t s, std::int32_t t);

void draw_quake_sky_span(
    std::vector<std::uint8_t>& indices,
    const QuakeSkyTile& tile,
    const ViewTransform& view,
    const QuakeSkyClock& clock,
    int y,
    int first_x,
    int last_x
);

QuakeSkyPresentation render_quake_sky_presentation(
    std::span<const std::uint8_t> base_indices,
    std::span<const std::uint16_t> faces,
    std::span<const std::uint16_t> entities,
    const SourceWorld& world,
    const ViewTransform& view,
    double surface_time,
    std::string_view time_source
);

} // namespace quake_bsp_reference
