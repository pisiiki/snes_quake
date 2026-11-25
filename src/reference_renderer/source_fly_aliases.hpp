#pragma once

#include "aliases.hpp"

namespace quake_bsp_reference {

struct SourceFlyAliases
{
    AliasAssets assets;
    std::vector<std::uint8_t> rotations;
    Json provenance;
};

SourceFlyAliases load_source_fly_aliases(
    const fs::path& path,
    std::span<const std::uint8_t> pak,
    const fs::path& camera,
    const BrushReplay& brushes,
    const AliasAssets& original,
    std::string_view map_entry
);

} // namespace quake_bsp_reference
