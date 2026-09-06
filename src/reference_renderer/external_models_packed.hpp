#pragma once

#include "world.hpp"
#include "geometry.hpp"
#include "external_models.hpp"
#include "textured_live.hpp"

namespace quake_bsp_reference {

void compose_packed_external_bsp_models(
    PackedTextureRaster& raster,
    const SourceWorld& packed_world,
    const ExternalBspScene& scene,
    std::span<const ExternalBspEntityState> entities,
    std::size_t sample_index,
    double server_time,
    const Camera& camera,
    ExternalBspCoverage* output_coverage = nullptr
);

} // namespace quake_bsp_reference
