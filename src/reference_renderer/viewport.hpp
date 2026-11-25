#pragma once

#include "world.hpp"

namespace quake_bsp_reference {

enum class RenderScale { X2, X3 };
enum class ViewportLayout { Full, Playable };
inline constexpr std::array kRenderScaleLabels{"X2", "X3"};
inline constexpr int kX3CenterX = 43;
inline constexpr int kPlayableWorldHeight = 200;
inline constexpr std::string_view kX3ProjectionContract = "snes-x3-center43-v1";

// Parity planes have a 128-byte row stride. Each scale projects and rasterizes
// directly into the active rows of its viewport.
inline thread_local RenderScale active_render_scale = RenderScale::X2;
inline thread_local ViewportLayout active_viewport_layout = ViewportLayout::Full;
// Static diagnostics can select a focal length. Plain X3 uses 64 pixels.
inline thread_local int active_source_focal = 64;
inline int render_width()
{
    return active_render_scale == RenderScale::X2 ? 128 : 85;
}
inline int render_height()
{
    if (active_viewport_layout == ViewportLayout::Playable)
        return active_render_scale == RenderScale::X2 ? kPlayableWorldHeight / 2 : (kPlayableWorldHeight + 2) / 3;
    return active_render_scale == RenderScale::X2 ? 112 : 74;
}
inline int render_center_x()
{
    // Match BSP_VIEW_CENTER_X, including the odd-width viewport's rounding.
    return active_render_scale == RenderScale::X2 ? 64 : kX3CenterX;
}
inline int render_center_y()
{
    return render_height() / 2;
}
inline int render_focal_length()
{
    return active_render_scale == RenderScale::X2 ? 96 : active_source_focal;
}
inline int render_project_q7(int ratio_q11)
{
    // The native focal patch floors the signed product before multiplying by
    // four. Applying the sign afterward changes negative endpoints at f!=64.
    return active_render_scale == RenderScale::X2 ? ratio_q11 * 6 : ((ratio_q11 * active_source_focal) >> 6) * 4;
}
inline bool render_wide_frustum()
{
    return active_render_scale != RenderScale::X2 && active_source_focal < kX3CenterX;
}

inline int render_project_world_q7(int component, int depth)
{
    // Keep X2's already-computed Q12 bit: dropping it can flatten a shared
    // boundary onto a half-open row sample and leave an uncovered pixel.
    const int limit = render_wide_frustum() ? 2 : 1;
    const int bits = active_render_scale == RenderScale::X2 ? 12 : 11;
    // FX3 saturates before division, including a rounded zero-depth endpoint.
    const int quotient = depth == 0 ? limit << bits : (std::min(std::abs(component), depth * limit) << bits) / depth;
    const int signed_quotient = component < 0 ? -quotient : quotient;
    return active_render_scale == RenderScale::X2 ? signed_quotient * 3 : render_project_q7(signed_quotient);
}

class RenderViewportScope
{
  public:
    explicit RenderViewportScope(RenderScale scale, int source_focal = 64, ViewportLayout layout = ViewportLayout::Full)
    :
    previous_(active_render_scale),
    previous_focal_(active_source_focal),
    previous_layout_(active_viewport_layout)
    {
        if (source_focal < 33 || source_focal > 64 || (scale == RenderScale::X2 && source_focal != 64))
            fail("diagnostic source focal requires X3 and a value in [33,64]");
        active_render_scale = scale;
        active_source_focal = source_focal;
        active_viewport_layout = layout;
    }
    ~RenderViewportScope()
    {
        active_render_scale = previous_;
        active_source_focal = previous_focal_;
        active_viewport_layout = previous_layout_;
    }
    RenderViewportScope(const RenderViewportScope&) = delete;
    RenderViewportScope& operator=(const RenderViewportScope&) = delete;

  private:
    RenderScale previous_;
    int previous_focal_;
    ViewportLayout previous_layout_;
};

inline RenderScale parse_render_scale(std::string_view value)
{
    if (value == "x2")
        return RenderScale::X2;
    if (value == "x3")
        return RenderScale::X3;
    fail("render scale must be x2 or x3");
}

inline std::string render_scale_name(RenderScale scale)
{
    return scale == RenderScale::X2 ? "x2" : "x3";
}

} // namespace quake_bsp_reference
