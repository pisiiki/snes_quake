#pragma once

#include "gameplay.hpp"

namespace quake_bsp_reference {

using GameplayCapture = std::function<Json(const GameplayRenderSnapshot&, std::size_t, std::string_view)>;

Json gameplay_snapshot_json(const GameplayRenderSnapshot& snapshot);
// No SDL or wall clock: every script operation is an explicit native tick,
// foreground service, level reset, or render-snapshot boundary.
Json run_gameplay_script(GameplaySession& session, const Json& script, const GameplayCapture& capture = {});

} // namespace quake_bsp_reference
