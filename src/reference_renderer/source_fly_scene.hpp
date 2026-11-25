#pragma once

#include "brushes.hpp"
#include "packed_brushes.hpp"

namespace quake_bsp_reference {

// Complete only interactive Fly; ordinary source replay remains the recorded set.
BrushReplay complete_source_fly_brush_replay(
    const BrushReplay& replay,
    const PackedBrushAssets& assets,
    std::span<const std::uint8_t> compact_replay
);

bool run_source_fly_scene_self_test();

} // namespace quake_bsp_reference
