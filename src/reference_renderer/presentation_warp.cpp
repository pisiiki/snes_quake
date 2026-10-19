#include "presentation_warp.hpp"

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
int cyclic_delta(int current, int rendered)
{
    return ((current - rendered + 32768) & 65535) - 32768;
}
int sine_q5(int angle)
{
    return static_cast<int>(
        std::nearbyint(std::nearbyint(64.0 * std::sin((angle & 255) * (2.0 * std::numbers::pi / 256.0))) / 2.0)
    );
}
} // namespace

WarpSettings parse_warp_settings(std::string_view model, double depth, int bands, std::vector<int> profile)
{
    if (model != "projective" && model != "mode7" && model != "hdma")
        fail("warp model must be projective, mode7 or hdma");
    if (!std::isfinite(depth) || depth < 0.0 || depth > 8192.0 || (depth > 0.0 && depth < 1.0))
        fail("warp depth must be zero (rotation only) or 1..8192 Quake units");
    if (bands != 1 && bands != 8 && bands != 16 && bands != 32 && bands != 224)
        fail("HDMA bands must be 1, 8, 16, 32 or 224");
    if (!profile.empty() && profile.size() != 3 && profile.size() != 5)
        fail("HDMA profile requires three or five inverse-depth Q16 values");
    if (!std::all_of(profile.begin(), profile.end(), [](int q) { return q == 0; }) &&
        !std::all_of(profile.begin(), profile.end(), [](int q) { return q >= 8 && q <= 4096; }))
        fail("HDMA profile values must all be zero or all be Q16 8..4096");
    return {model == "projective", depth, model == "hdma", bands, std::move(profile)};
}

std::string_view warp_model_name(const WarpSettings& settings)
{
    return settings.hdma ? "hdma" : settings.projective ? "projective" : "mode7";
}

ProjectiveWarp projective_camera_warp(const ViewTransform& current, const ViewTransform& rendered, double depth)
{
    parse_warp_settings("projective", depth);
    ProjectiveWarp warp;
    // Invert the actual render basis, including the packed camera's Q6 scaling.
    // Transposing it would assume orthonormal vectors and break neutral parity.
    const auto right = cross(rendered.up, rendered.forward);
    const double determinant = dot(rendered.screen_right, right);
    if (!std::isfinite(determinant) || std::abs(determinant) < 1e-12)
    {
        warp.valid = false;
        return warp;
    }
    const std::array dual{
        right * (1.0 / determinant),
        cross(rendered.forward, rendered.screen_right) * (1.0 / determinant),
        cross(rendered.screen_right, rendered.up) * (1.0 / determinant)
    };
    const auto delta = current.origin - rendered.origin;
    const double inverse_depth = depth == 0.0 ? 0.0 : 1.0 / depth;
    const double dx = dot(dual[0], delta) * inverse_depth;
    const double dy = dot(dual[1], delta) * inverse_depth;
    const double remaining = 1.0 - dot(dual[2], delta) * inverse_depth;
    if (!std::isfinite(remaining) || remaining <= 1e-9)
    {
        warp.valid = false;
        return warp;
    }
    // K^-1 [x,y,1], with the same pixel centers/intrinsics as view_ray().
    const std::array rays{
        current.screen_right * (1.0 / 64.0),
        current.up * (-1.0 / 64.0),
        current.forward - current.screen_right * (kX3CenterX / 64.0) + current.up * (37.0 / 64.0)
    };
    for (std::size_t column = 0; column < 3; ++column)
    {
        const double z = dot(dual[2], rays[column]);
        warp.inverse[column] = 64.0 * (remaining * dot(dual[0], rays[column]) + dx * z) + kX3CenterX * z;
        warp.inverse[3 + column] = -64.0 * (remaining * dot(dual[1], rays[column]) + dy * z) + 37.0 * z;
        warp.inverse[6 + column] = z;
    }
    warp.valid = std::all_of(warp.inverse.begin(), warp.inverse.end(), [](double v) { return std::isfinite(v); });
    return warp;
}

std::vector<std::uint32_t> present_projective_x3(std::span<const std::uint32_t> pixels, const ProjectiveWarp& warp)
{
    if (pixels.size() != 85U * 74U)
        fail("X3 presentation requires an 85x74 rendered image");
    std::vector<std::uint32_t> output(256U * 224U, 0U);
    if (!warp.valid)
        return output;
    const auto& h = warp.inverse;
    for (int y = 0; y < 224; ++y)
        for (int x = 0; x < 256; ++x)
        {
            const double px = (x + 0.5) / 3.0, py = (y + 0.5) / 3.0;
            const double z = h[6] * px + h[7] * py + h[8];
            if (z <= 1e-9)
                continue;
            // Snap numerical noise at integral texel boundaries consistently with the evaluator.
            const double sx = std::floor((h[0] * px + h[1] * py + h[2]) / z + 1e-9);
            const double sy = std::floor((h[3] * px + h[4] * py + h[5]) / z + 1e-9);
            if (sx >= 0.0 && sx < 85.0 && sy >= 0.0 && sy < 74.0)
                output[row_major_index(x, y, 256)] =
                    pixels[row_major_index(static_cast<int>(sx), static_cast<int>(sy), 85)];
        }
    return output;
}

PresentationWarp camera_warp(const ViewTransform& current, const ViewTransform& rendered)
{
    const auto delta = current.origin - rendered.origin;
    const auto bounded = [](double value) { return std::clamp(static_cast<int>(std::floor(value)), -255, 255); };
    const int dx = bounded(delta.x), dy = bounded(delta.y), dz = bounded(delta.z);
    const int yaw = yaw16(rendered), pitch = pitch16(rendered);
    const int sy = sine_q5(yaw >> 8), cy = sine_q5((yaw >> 8) + 64);
    const int sp = sine_q5(pitch >> 8), cp = sine_q5((pitch >> 8) + 64);
    const int handedness =
        dot(rendered.screen_right, Vec3{-static_cast<double>(sy), static_cast<double>(cy), 0.0}) < 0.0 ? -1 : 1;
    const int right = (dy * cy - dx * sy) >> 5;
    const int horizontal = std::clamp((dx * cy + dy * sy) >> 5, -255, 255);
    const int up = (dz * cp - horizontal * sp) >> 5;
    const int forward = (horizontal * cp + dz * sp) >> 6;
    const int look_x = cyclic_delta(yaw16(current), yaw) >> 6;
    const int look_y = cyclic_delta(pitch16(current), pitch) >> 6;
    return {
        std::clamp(handedness * (right + look_x), -80, 80),
        std::clamp(-up - look_y, -80, 80),
        std::clamp(-forward, -16, 16)
    };
}

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

std::vector<std::uint32_t> present_x3(std::span<const std::uint32_t> pixels, PresentationWarp warp)
{
    if (pixels.size() != 85U * 74U)
        fail("X3 presentation requires an 85x74 rendered image");
    if (std::abs(warp.x) > 80 || std::abs(warp.y) > 80 || std::abs(warp.zoom) > 16)
        fail("unbounded image warp");
    std::vector<std::uint32_t> output(256U * 224U, 0U);
    const int scale = 85 + warp.zoom;
    const int cx = 85 + (warp.zoom >> 1), cy = -((warp.zoom * 7) >> 4);
    // Match the SNES Mode 7 shared-latch, 8.8 matrix and truncation contract.
    for (int y = 0; y < 224; ++y)
    {
        const int sy = (((scale * (y + 1)) & ~63) + ((scale * warp.y) & ~63) + cy * 256) >> 8;
        if (sy < 0 || sy >= 74)
            continue;
        for (int x = 0; x < 256; ++x)
        {
            const int sx = (((scale * warp.x) & ~63) - scale * (255 - x) + cx * 256) >> 8;
            if (sx >= 0 && sx < 85)
                output[row_major_index(x, y, 256)] = pixels[row_major_index(sx, sy, 85)];
        }
    }
    return output;
}

Json warp_camera_json(const ViewTransform& camera)
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

void run_presentation_warp_tests()
{
    run_hdma_warp_tests();
    const ViewTransform reference{{0, 0, 0}, {1, 0, 0}, {0, 1, 0}, {0, 0, 1}};
    auto view = reference;
    view.origin = {2, 3, 4};
    const auto warp = camera_warp(view, reference);
    if (warp.x != 3 || warp.y != -4 || warp.zoom != -1)
        fail("camera warp translation contract");
    view.origin = {10000, 10000, 10000};
    const auto bounded = camera_warp(view, reference);
    if (bounded.x != 80 || bounded.y != -80 || bounded.zoom != -16)
        fail("camera warp limits");
    std::vector<std::uint32_t> pixels(85U * 74U);
    std::iota(pixels.begin(), pixels.end(), 1U);
    const auto output = present_x3(pixels, {});
    const auto projective = present_projective_x3(pixels, projective_camera_warp(reference, reference, 192.0));
    if (output != projective)
        fail("neutral projective X3 geometry");
    const auto rolled = source_view_transform({{0, 0, 0}, 0, 0, 20});
    const auto source = source_view_transform({{0, 0, 0}, 0, 0, 0});
    const auto rotation = projective_camera_warp(rolled, source, 0.0);
    if (!rotation.valid || std::abs(rotation.inverse[1]) < 0.3 || present_projective_x3(pixels, rotation) == projective)
        fail("projective roll must rotate the image");
    view = reference;
    view.origin = {193, 0, 0};
    if (projective_camera_warp(view, reference, 192.0).valid)
        fail("camera beyond the reprojection plane must be rejected");
    for (int y = 0; y < 224; ++y)
        for (int x = 0; x < 256; ++x)
        {
            const auto expected = x < 255 && y < 222 ? pixels[row_major_index(x / 3, y / 3, 85)] : 0U;
            if (output[row_major_index(x, y, 256)] != expected)
                fail("neutral X3 geometry");
        }
}
} // namespace quake_bsp_reference
