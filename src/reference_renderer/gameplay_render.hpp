#pragma once

#include "gameplay.hpp"

namespace quake_bsp_reference {

struct GameplayFrame
{
    std::vector<std::uint8_t> world;
    std::vector<std::uint8_t> composite;
    std::vector<std::uint8_t> visible_x3_bgr555;
    std::vector<std::uint32_t> pixels;
    // Four 256-pixel console rows, eight scanlines per row, MSB first.
    std::vector<std::uint8_t> pickup_text_mask;
    Json inspection;
};

// Internal native-composition boundary, exposed for the Q6 depth regression.
std::vector<std::int16_t> gameplay_packed_opaque_depth(std::span<const double> source, const ViewTransform& view);

class GameplayRenderer
{
  public:
    GameplayRenderer(const fs::path& pak, const std::vector<GameplayAssets>& maps);
    ~GameplayRenderer();
    GameplayRenderer(const GameplayRenderer&) = delete;
    GameplayRenderer& operator=(const GameplayRenderer&) = delete;
    GameplayFrame render(const GameplayRenderSnapshot& snapshot);

  private:
    class Impl;
    std::unique_ptr<Impl> impl_;
};

} // namespace quake_bsp_reference
