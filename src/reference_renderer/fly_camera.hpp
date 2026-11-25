#pragma once

#include "geometry.hpp"

namespace quake_bsp_reference {

struct FlyCameraInput
{
    double forward{};
    double right{};
    double vertical{};
    double mouse_x{};
    double mouse_y{};
    bool fast{};
};

inline Vec3 fly_unit(const Vec3& vector)
{
    const double length = std::sqrt(length_squared(vector));
    return length > 1e-12 ? vector * (1.0 / length) : Vec3{};
}

inline Vec3 fly_rotate(const Vec3& vector, const Vec3& axis, double radians)
{
    const double cosine = std::cos(radians);
    return vector * cosine + cross(axis, vector) * std::sin(radians) + axis * (dot(axis, vector) * (1.0 - cosine));
}

// This is an unrestricted source-world inspection camera. Preserve a supplied
// native capture basis, including its handedness and quantization, until input
// actually changes it; replacing it with Quake's Euler basis mirrors the view.
inline bool advance_fly_camera(SourceCamera& camera, const FlyCameraInput& input, double seconds)
{
    auto view = source_view_transform(camera);
    bool changed = false;
    if (input.mouse_x != 0.0 || input.mouse_y != 0.0)
    {
        constexpr double sensitivity = 0.15 * std::numbers::pi / 180.0;
        constexpr double pitch_limit = 89.0 * std::numbers::pi / 180.0;
        const double handedness = dot(cross(view.forward, view.screen_right), view.up) < 0.0 ? -1.0 : 1.0;
        std::array basis{view.forward, view.screen_right, view.up};
        for (auto& axis : basis)
            axis = fly_rotate(axis, {0.0, 0.0, 1.0}, handedness * input.mouse_x * sensitivity);
        const auto forward = fly_unit(basis[0]);
        const double elevation = std::asin(std::clamp(forward.z, -1.0, 1.0));
        const double delta = std::clamp(elevation - input.mouse_y * sensitivity, -pitch_limit, pitch_limit) - elevation;
        auto horizontal_right = cross(Vec3{0.0, 0.0, 1.0}, forward);
        if (length_squared(horizontal_right) < 1e-12)
            horizontal_right = Vec3{basis[1].x, basis[1].y, 0.0} * handedness;
        const auto pitch_axis = fly_unit(horizontal_right) * handedness;
        for (auto& axis : basis)
            axis = fly_rotate(axis, pitch_axis, -handedness * delta);
        camera.capture_basis = basis;
        view = source_view_transform(camera);
        changed = true;
    }
    const auto motion =
        fly_unit(view.forward) * input.forward + fly_unit(view.screen_right) * input.right +
        Vec3{0.0, 0.0, input.vertical};
    // Cap resume/focus gaps and normalize diagonals. Render cost must not turn
    // one event-loop stall into a large camera teleport.
    const double distance = std::clamp(seconds, 0.0, 0.1) * (input.fast ? 640.0 : 160.0);
    if (length_squared(motion) > 1e-12 && distance > 0.0)
    {
        camera.origin = camera.origin + fly_unit(motion) * distance;
        changed = true;
    }
    return changed;
}

} // namespace quake_bsp_reference
