#include "presentation_warp.hpp"

namespace quake_bsp_reference {
namespace {
int stable_round(double value)
{
    return static_cast<int>(std::nearbyint(std::nearbyint(value * 1e9) / 1e9));
}

HdmaBand band_registers(const ProjectiveWarp& warp, double screen_y)
{
    HdmaBand result{{0, 0, 0, 0, 96, 96, 96, 96}, false};
    if (!warp.valid)
        return result;
    const auto& h = warp.inverse;
    const double px = 128.0 / 3.0, py = (screen_y + 0.5) / 3.0;
    const double z = h[6] * px + h[7] * py + h[8];
    if (z <= 1e-9)
        return result;
    bool neutral = true;
    for (int i = 0; i < 9; ++i)
        neutral = neutral && std::abs(h[static_cast<std::size_t>(i)] - (i % 4 == 0 ? 1.0 : 0.0)) <= 1e-10;
    if (neutral)
        return {{-85, 0, 0, 85, 85, 0, 85, 0}, true};
    std::array<int, 4> slopes{};
    std::array<double, 2> origin{};
    for (int row = 0; row < 2; ++row)
    {
        const auto i = static_cast<std::size_t>(row * 3);
        const double center = (h[i] * px + h[i + 1] * py + h[i + 2]) / z;
        for (int axis = 0; axis < 2; ++axis)
        {
            const double slope = (h[i + axis] - center * h[6 + axis]) / z * (256.0 / 3.0);
            if (!std::isfinite(slope) || std::abs(slope) > 32769.0)
                return result;
            slopes[static_cast<std::size_t>(row * 2 + axis)] = stable_round(slope) * (axis == 0 ? -1 : 1);
        }
        const int a = slopes[static_cast<std::size_t>(row * 2)], b = slopes[static_cast<std::size_t>(row * 2 + 1)];
        if (a < -32768 || a > 32767 || b < -32768 || b > 32767)
            return result;
        origin[static_cast<std::size_t>(row)] = center * 256 - a * 127.5 - b * (screen_y + 1);
    }
    double best = std::numeric_limits<double>::infinity();
    std::array<int, 8> registers{};
    for (int dx = -3; dx <= 3; ++dx)
        for (int dy = -3; dy <= 3; ++dy)
        {
            std::array<int, 2> centers{};
            double error = 0;
            for (int row = 0; row < 2; ++row)
            {
                const auto i = static_cast<std::size_t>(row);
                const int term = (slopes[i * 2] * dx & ~63) + (slopes[i * 2 + 1] * dy & ~63);
                const double center = (origin[i] - term) / 256;
                if (!std::isfinite(center) || std::abs(center) > 1000000)
                    return result;
                centers[i] = stable_round(center);
                const double residual = centers[i] * 256.0 + term - origin[i];
                error += residual * residual;
            }
            error = std::nearbyint(error * 1e7);
            if (error < best)
            {
                best = error;
                registers = {
                    slopes[0],
                    slopes[1],
                    slopes[2],
                    slopes[3],
                    centers[0],
                    centers[1],
                    centers[0] + dx,
                    centers[1] + dy
                };
            }
        }
    if (std::any_of(registers.begin() + 4, registers.end(), [](int v) { return v < -4096 || v > 4095; }))
        return result;
    return {registers, true};
}
} // namespace

HdmaWarp hdma_camera_warp(const ViewTransform& current, const ViewTransform& rendered, const WarpSettings& settings)
{
    HdmaWarp result;
    for (int band = 0; band < settings.bands; ++band)
    {
        const int first = band * 224 / settings.bands, end = (band + 1) * 224 / settings.bands;
        const double y = (first + end - 1) / 2.0;
        double depth = settings.depth;
        const auto& profile = settings.inverse_depth_profile;
        if (!profile.empty())
        {
            const double position = y / 223.0 * static_cast<double>(profile.size() - 1);
            const auto left = static_cast<std::size_t>(std::floor(position));
            const auto right = std::min(left + 1, profile.size() - 1);
            const double q = profile[left] + (profile[right] - profile[left]) * (position - static_cast<double>(left));
            depth = q == 0 ? 0 : 65536.0 / q;
        }
        result.push_back(band_registers(projective_camera_warp(current, rendered, depth), y));
    }
    return result;
}

std::vector<std::uint32_t> present_hdma_x3(std::span<const std::uint32_t> pixels, const HdmaWarp& bands)
{
    if (pixels.size() != 85U * 74U || bands.empty())
        fail("HDMA presentation requires X3 pixels and a register table");
    std::vector<std::uint32_t> output(256U * 224U, 0U);
    const auto clip = [](int value) { return value & 0x2000 ? value | ~0x3ff : value & 0x3ff; };
    for (std::size_t band = 0; band < bands.size(); ++band)
    {
        const auto& r = bands[band].registers;
        const int dx = clip(r[6] - r[4]), dy = clip(r[7] - r[5]);
        const int first = static_cast<int>(band * 224 / bands.size()),
                  end = static_cast<int>((band + 1) * 224 / bands.size());
        for (int y = first; y < end; ++y)
            for (int x = 0; x < 256; ++x)
            {
                const int sx =
                    ((r[0] * dx & ~63) + (r[1] * dy & ~63) + (r[1] * (y + 1) & ~63) + r[4] * 256 + r[0] * (255 - x)) >>
                    8;
                const int sy =
                    ((r[2] * dx & ~63) + (r[3] * dy & ~63) + (r[3] * (y + 1) & ~63) + r[5] * 256 + r[2] * (255 - x)) >>
                    8;
                if (sx >= 0 && sx < 85 && sy >= 0 && sy < 74)
                    output[row_major_index(x, y, 256)] = pixels[row_major_index(sx, sy, 85)];
            }
    }
    return output;
}

Json hdma_warp_json(const HdmaWarp& bands)
{
    Json registers = Json::array(), valid = Json::array();
    for (const auto& band : bands)
    {
        registers.push_back(band.registers);
        valid.push_back(band.valid);
    }
    return {
        {"bands", bands.size()},
        {"registers", registers},
        {"valid", valid},
        {"channels", 4},
        {"registerBytesPerUpdate", 16},
        {"requiresActiveOnlyTilemap", true},
        {"measuredSnesCost", false}
    };
}

void run_hdma_warp_tests()
{
    const ViewTransform camera{{0, 0, 0}, {1, 0, 0}, {0, 1, 0}, {0, 0, 1}};
    std::vector<std::uint32_t> pixels(85U * 74U);
    std::iota(pixels.begin(), pixels.end(), 1U);
    for (const int count : {1, 8, 16, 32, 224})
    {
        const auto settings = parse_warp_settings("hdma", 192, count, {128, 256, 512});
        if (present_hdma_x3(pixels, hdma_camera_warp(camera, camera, settings)) != present_x3(pixels, {}))
            fail("neutral HDMA must preserve exact X3 pixels");
    }
}
} // namespace quake_bsp_reference
