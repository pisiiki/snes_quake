#include "presentation.hpp"

namespace quake_bsp_reference {
namespace {
int angle16(double radians)
{
    return static_cast<int>(std::lround(radians * (65536.0 / (2.0 * std::numbers::pi)))) & 65535;
}
int yaw16(const ViewTransform& camera)
{
    return angle16(std::atan2(camera.forward.y, camera.forward.x));
}
int pitch16(const ViewTransform& camera)
{
    return angle16(std::atan2(camera.forward.z, std::hypot(camera.forward.x, camera.forward.y)));
}
} // namespace

std::vector<std::uint8_t> compact_viewport(std::span<const std::uint8_t> indices, RenderScale scale)
{
    if (indices.size() != kLogicalPixels)
        fail("invalid reference backing plane");
    const RenderViewportScope viewport(scale);
    std::vector<std::uint8_t> result;
    result.reserve(static_cast<std::size_t>(render_width() * render_height()));
    for (int y = 0; y < render_height(); ++y)
    {
        const auto row = indices.subspan(logical_pixel_index(0, y), static_cast<std::size_t>(render_width()));
        result.insert(result.end(), row.begin(), row.end());
    }
    return result;
}

std::vector<std::uint32_t> present_x3(std::span<const std::uint32_t> pixels)
{
    if (pixels.size() != 85U * 74U)
        fail("X3 presentation requires an 85x74 rendered image");
    std::vector<std::uint32_t> output(256U * 224U, 0U);
    for (int y = 0; y < 222; ++y)
        for (int x = 0; x < 255; ++x)
            output[row_major_index(x, y, 256)] = pixels[row_major_index(x / 3, y / 3, 85)];
    return output;
}

Json view_camera_json(const ViewTransform& camera)
{
    return Json{
        {"position", {camera.origin.x, camera.origin.y, camera.origin.z}},
        {"yawU16", yaw16(camera)},
        {"pitchU16", pitch16(camera)},
        {"forward", {camera.forward.x, camera.forward.y, camera.forward.z}},
        {"up", {camera.up.x, camera.up.y, camera.up.z}},
        {"screenRight", {camera.screen_right.x, camera.screen_right.y, camera.screen_right.z}}
    };
}

void run_presentation_tests()
{
    std::vector<std::uint32_t> pixels(85U * 74U);
    std::iota(pixels.begin(), pixels.end(), 1U);
    const auto output = present_x3(pixels);
    for (int y = 0; y < 224; ++y)
        for (int x = 0; x < 256; ++x)
        {
            const auto expected = x < 255 && y < 222 ? pixels[row_major_index(x / 3, y / 3, 85)] : 0U;
            if (output[row_major_index(x, y, 256)] != expected)
                fail("X3 mosaic geometry");
        }
}
} // namespace quake_bsp_reference
