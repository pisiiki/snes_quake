#pragma once

#include "gameplay.hpp"

namespace quake_bsp_reference {

// Original PAK MDL geometry for basic live gameplay. Packed sprite parity
// remains available when the manifest supplies a referenceData directory.
class GameplayModels
{
  public:
    explicit GameplayModels(std::span<const std::uint8_t> pak);
    ~GameplayModels();
    void compose(ReferenceFrame& frame, const SourceWorld& world, const GameplayRenderSnapshot& snapshot);

  private:
    class Impl;
    std::unique_ptr<Impl> impl_;
};

} // namespace quake_bsp_reference
