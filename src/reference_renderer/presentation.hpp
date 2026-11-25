#pragma once

#include "geometry.hpp"

namespace quake_bsp_reference {

std::vector<std::uint8_t> compact_viewport(std::span<const std::uint8_t> indices, RenderScale scale);
std::vector<std::uint32_t> present_x3(std::span<const std::uint32_t> pixels);
Json view_camera_json(const ViewTransform& camera);
void run_presentation_tests();

} // namespace quake_bsp_reference
