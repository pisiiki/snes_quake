#pragma once

#include "world.hpp"
#include "geometry.hpp"
#include "textured_live.hpp"
#include "artifacts_options.hpp"

namespace quake_bsp_reference {

void write_json_report(
    const fs::path& path,
    const Options& options,
    const SourceWorld& world,
    const Bvh& bvh,
    const ReferenceFrame& frame,
    const SourceWorld* quantized_world,
    const Bvh* quantized_bvh,
    const ReferenceFrame* quantized_frame,
    const PacketSelection* packet_selection,
    const Bvh* packet_bvh,
    const ReferenceFrame* packet_nearest_frame,
    const ReferenceFrame* packet_painter_frame,
    const RasterLayers* raster_layers,
    const PackedTextureRaster* packed_affine_texture_raster,
    const PackedTextureRaster* packed_projective_texture_raster,
    const TextureMappingFidelity* affine_texture_mapping_fidelity,
    const TextureMappingFidelity* projective_texture_mapping_fidelity,
    const std::optional<PackedAudit>& audit,
    const std::optional<Comparison>& comparison,
    const std::optional<PackedTextureComparison>& packed_texture_comparison,
    bool passed,
    double load_ms,
    double build_ms,
    double render_ms
);

} // namespace quake_bsp_reference
