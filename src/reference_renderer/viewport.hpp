#pragma once

#include "world.hpp"

namespace quake_bsp_reference {

enum class RenderScale { X2, X3, X3Warp };
inline constexpr std::array kRenderScaleLabels{"X2", "X3", "X3 WARP"};
inline constexpr int kX3CenterX = 43;
inline constexpr std::string_view kX3ProjectionContract = "snes-x3-center43-v1";

// Keep the established 128-byte row stride for parity planes. X3 traces and
// rasterizes only the active 85x74 area; it is never resized from an X2 render.
inline thread_local RenderScale active_render_scale = RenderScale::X2;
// Static diagnostics may reproduce a native source focal. Presentation and
// training retain the default 64-pixel X3 target projection.
inline thread_local int active_source_focal = 64;
inline int render_width()
{
    return active_render_scale == RenderScale::X2 ? 128 : 85;
}
inline int render_height()
{
    return active_render_scale == RenderScale::X2 ? 112 : 74;
}
inline int render_center_x()
{
    // Match BSP_VIEW_CENTER_X, including the odd-width viewport's rounding.
    return active_render_scale == RenderScale::X2 ? 64 : kX3CenterX;
}
inline int render_center_y()
{
    return active_render_scale == RenderScale::X2 ? 56 : 37;
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

class RenderViewportScope
{
  public:
    explicit RenderViewportScope(RenderScale scale, int source_focal = 64)
    :
    previous_(active_render_scale),
    previous_focal_(active_source_focal)
    {
        if (source_focal < 33 || source_focal > 64 || (scale == RenderScale::X2 && source_focal != 64))
            fail("diagnostic source focal requires X3 and a value in [33,64]");
        active_render_scale = scale;
        active_source_focal = source_focal;
    }
    ~RenderViewportScope()
    {
        active_render_scale = previous_;
        active_source_focal = previous_focal_;
    }
    RenderViewportScope(const RenderViewportScope&) = delete;
    RenderViewportScope& operator=(const RenderViewportScope&) = delete;

  private:
    RenderScale previous_;
    int previous_focal_;
};

inline RenderScale parse_render_scale(std::string_view value)
{
    if (value == "x2")
        return RenderScale::X2;
    if (value == "x3")
        return RenderScale::X3;
    if (value == "x3-warp" || value == "x3 warp")
        return RenderScale::X3Warp;
    fail("render scale must be x2, x3 or x3-warp");
}

inline std::string render_scale_name(RenderScale scale)
{
    return scale == RenderScale::X2 ? "x2" : scale == RenderScale::X3 ? "x3" : "x3-warp";
}

} // namespace quake_bsp_reference
