#include "report.hpp"
#include "world.hpp"
#include "geometry.hpp"
#include "textured_live.hpp"
#include "live_demo.hpp"
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
)
{
    if (path.empty())
    {
        return;
    }
    if (!path.parent_path().empty())
    {
        fs::create_directories(path.parent_path());
    }
    const Vec3 source_camera =
        world.origin +
        Vec3{options.camera.x * kWorldScale, options.camera.y * kWorldScale, options.camera.z * kWorldScale};
    Json material_palette = Json::array();
    for (const auto& color : world.live_material_palette)
    {
        material_palette.push_back(Json::array({color.r, color.g, color.b}));
    }
    Json texture_palette_bgr555 = Json::array();
    for (const auto& color : world.source_palette)
    {
        texture_palette_bgr555.push_back(snes_color_word(color));
    }
    Json untextured_palette_bgr555 = Json::array();
    for (const auto& color : world.untextured_palette)
    {
        untextured_palette_bgr555.push_back(snes_color_word(color));
    }
    Json lightmap_mapping = Json::array();
    for (int level = 0; level < kQuakeColormapLevels; ++level)
    {
        lightmap_mapping.push_back(
            {{"lightmapLevel", level}, {"paletteIndex", untextured_lightmap_index(static_cast<std::uint8_t>(level))}}
        );
    }

    Json report{
        {"schema", 1},
        {"passed", passed},
        {"renderer", "source-bsp-bvh-raycast-v2"},
        {"groundTruthScope",
         "original BSP29 world geometry; independent BVH, ray/triangle "
         "intersection, lighting, and pixel ownership; no packed PVS, packet, "
         "packed face-plane, or SuperFX raster input"},
        {"pak", options.pak.generic_string()},
        {"mapEntry", options.map_entry},
        {"camera",
         {{"label", options.camera_label},
          {"packed", Json::array({options.camera.x, options.camera.y, options.camera.z})},
          {"yaw", options.camera.yaw},
          {"pitch", options.camera.pitch},
          {"source", Json::array({source_camera.x, source_camera.y, source_camera.z})}}},
        {"logicalResolution", Json::array({kLogicalWidth, kLogicalHeight})},
        {"artifactMode", options.report_only ? "report-only" : "full"},
        {"colorMode", options.flat ? "flat" : "checker-dither"},
        {"renderMatrix",
         {{"contract", "quake-techniques-2-4-7-v1"},
          {"selected", render_mode_name({!options.no_textures, options.lighting})},
          {"technique", render_mode_technique({!options.no_textures, options.lighting})},
          {"packedContract",
           packed_render_contract({!options.no_textures, options.lighting}, false)},
          {"textures", !options.no_textures},
          {"lighting", kLightingLabels.at(static_cast<std::size_t>(options.lighting))},
          {"untexturedGradient",
           {{"contract", "neutral-bgr555-ramp64-v1"},
            {"paletteEntries", kUntexturedPalette.size()},
            {"geometryIndexRange", Json::array({0, 63})},
            {"distinctGeometryBgr555Colors", kUntexturedRampColors},
            {"diagnosticBackgroundMenuIndex", kUntexturedDiagnosticIndex},
            {"reservedBlackIndexRange", Json::array({64, 238})},
            {"quakeTexturePaletteTailRange", Json::array({kUntexturedQuakeTailFirstIndex, 255})},
            {"quakeTexturePaletteTailPurpose", "retained for SNES OBJ palette 7 runtime menu"},
            {"paletteBgr555", untextured_palette_bgr555},
            {"lightmapMapping", lightmap_mapping},
            {"lightmapIndices", with_suffix(options.output_prefix, ".untextured-lightmap.idx").generic_string()}}}}},
        {"surfaceVisibility",
         {{"contract", "Quake dface.side camera half-space"},
          {"faceVisibilityEpsilon", kFaceVisibilityEpsilon},
          {"equalDepthTieEpsilon", kHitTieEpsilon},
          {"equalDepthTieBreak", "lowest source-face ID"}}},
        {"materialShading",
         {{"textureFamilyCount", kTextureFamilyCount},
          {"physicalColorsPerFamily", kPhysicalColorsPerFamily},
          {"apparentLightLevelsPerFamily", kApparentLightLevels},
          {"familyHues",
           Json::array({world.texture_family_hues[0], world.texture_family_hues[1], world.texture_family_hues[2]})},
          {"paletteRgb", material_palette},
          {"diagnosticIndex", 0}}},
        {"geometry",
         {{"worldFaces", world.face_count},
          {"cameraVisibleFaces", frame.visible_faces},
          {"triangles", world.triangles.size()},
          {"bvhNodes", bvh.node_count()}}},
        {"reference",
         {{"hitPixels", frame.hits},
          {"missPixels", frame.misses},
          {"uniqueFirstHitFaces", frame.unique_faces},
          {"indices", with_suffix(options.output_prefix, ".idx").generic_string()},
          {"faces", with_suffix(options.output_prefix, ".faces").generic_string()},
          {"image", with_suffix(options.output_prefix, ".bmp").generic_string()},
          {"nativeImage", with_suffix(options.output_prefix, ".native.bmp").generic_string()}}},
        {"materialReference",
         {{"contract", "material-distance-v1"},
          {"diagnosticPixels", std::ranges::count(frame.material_indices, std::uint8_t{0})},
          {"indices", with_suffix(options.output_prefix, ".material.idx").generic_string()},
          {"image", with_suffix(options.output_prefix, ".material.bmp").generic_string()},
          {"nativeImage", with_suffix(options.output_prefix, ".material.native.bmp").generic_string()}}},
        {"exactTextureReference",
         {{"contract", "exact-miptex-source-ray-v1"},
          {"ownership", "independent source-BSP pixel-center ray"},
          {"sample", "floor nearest, per-axis modulo original dimensions"},
          {"mipLevel", 0},
          {"lightmaps", false},
          {"shading", false},
          {"textureCount",
           std::ranges::count_if(world.textures, [](const MipTexture& texture) { return texture.present; })},
          {"paletteEntries", world.source_palette.size()},
          {"paletteConversion", "independent round(R,G,B * 31 / 255) to BGR555"},
          {"paletteBgr555", texture_palette_bgr555},
          {"sourceIndexZeroPixels", std::ranges::count(frame.texture_indices, std::uint8_t{0})},
          {"indices", with_suffix(options.output_prefix, ".texture.idx").generic_string()},
          {"image", with_suffix(options.output_prefix, ".texture.bmp").generic_string()},
          {"nativeImage", with_suffix(options.output_prefix, ".texture.native.bmp").generic_string()}}},
        {"bspLightmappedTextureReference",
         {{"contract", "exact-miptex-bsp29-static-lightmap-v1"},
          {"lightingLumpBytes", world.lighting.size()},
          {"lightmappedFaces",
           std::ranges::count_if(
               world.face_lightmaps,
               [](const FaceLightmap& lightmap) { return lightmap.light_offset >= 0; }
           )},
          {"unlightmappedFaces",
           std::ranges::count_if(
               world.face_lightmaps,
               [](const FaceLightmap& lightmap) { return lightmap.light_offset < 0; }
           )},
          {"sampleGrid", "16 source units, bilinear per covered pixel"},
          {"lightStyles", "all baked planes at static neutral 'm' intensity"},
          {"neutralStyleScale8_8", kQuakeNeutralLightStyleScale},
          {"dynamicLights", false},
          {"animatedOrSwitchedStyleTiming", false},
          {"colormapLevelRange", Json::array({0, kQuakeColormapLevels - 1})},
          {"palette", "unchanged 256-entry SNES BGR555 palette"},
          {"fullbrightIndices", "224..255 remain unshaded"},
          {"levelPlane", with_suffix(options.output_prefix, ".texture-lightmap.levels").generic_string()},
          {"indices", with_suffix(options.output_prefix, ".texture-lightmap.idx").generic_string()},
          {"image", with_suffix(options.output_prefix, ".texture-lightmap.bmp").generic_string()},
          {"nativeImage", with_suffix(options.output_prefix, ".texture-lightmap.native.bmp").generic_string()}}},
    };
    if (quantized_world != nullptr && quantized_bvh != nullptr && quantized_frame != nullptr)
    {
        report["quantizedWorld"] = {
            {"contract", "packed-world-bvh-raycast-v1"},
            {"scope",
             "all count-nonzero packed world faces; source-space camera rays; "
             "no PVS, packet admission/order, projected vertices, or spans"},
            {"visibility", "packed Q6 signed-16 camera half-space; negative side visible"},
            {"geometry",
             {{"worldFaces", quantized_world->face_count},
              {"drawableFaces", quantized_world->drawable_faces},
              {"triangles", quantized_world->triangles.size()},
              {"bvhNodes", quantized_bvh->node_count()}}},
            {"reference",
             {{"hitPixels", quantized_frame->hits},
              {"missPixels", quantized_frame->misses},
              {"uniqueFirstHitFaces", quantized_frame->unique_faces},
              {"visibleFaces", quantized_frame->visible_faces},
              {"indices", with_suffix(options.output_prefix, ".quantized.idx").generic_string()},
              {"faces", with_suffix(options.output_prefix, ".quantized.faces").generic_string()},
              {"image", with_suffix(options.output_prefix, ".quantized.bmp").generic_string()},
              {"nativeImage", with_suffix(options.output_prefix, ".quantized.native.bmp").generic_string()}}},
            {"materialReference",
             {{"contract", "material-distance-v1"},
              {"diagnosticPixels", std::ranges::count(quantized_frame->material_indices, std::uint8_t{0})},
              {"indices", with_suffix(options.output_prefix, ".quantized.material.idx").generic_string()},
              {"image", with_suffix(options.output_prefix, ".quantized.material.bmp").generic_string()},
              {"nativeImage", with_suffix(options.output_prefix, ".quantized.material.native.bmp").generic_string()}}},
        };
    }
    else
    {
        report["quantizedWorld"] = nullptr;
    }
    if (quantized_world != nullptr && quantized_bvh != nullptr && packet_selection != nullptr &&
        packet_bvh != nullptr && packet_nearest_frame != nullptr && packet_painter_frame != nullptr)
    {
        const auto packet_layer =
            [&](std::string_view contract,
                std::string_view scope,
                std::string_view suffix,
                std::string_view preceding,
                const ReferenceFrame& packet_frame) {
                const auto artifact_suffix = std::string(suffix);
                return Json{
                    {"contract", contract},
                    {"scope", scope},
                    {"visibility",
                     "packed Q6 signed-16 camera half-space; negative side "
                     "visible"},
                    {"packetSourceFaces", options.packet_source_faces.generic_string()},
                    {"geometry",
                     {{"worldFaces", quantized_world->face_count},
                      {"selectedFaces", packet_selection->source_faces.size()},
                      {"triangles", packet_selection->triangles.size()},
                      {"bvhNodes", packet_bvh->node_count()}}},
                    {"reference",
                     {{"hitPixels", packet_frame.hits},
                      {"missPixels", packet_frame.misses},
                      {"uniqueFirstHitFaces", packet_frame.unique_faces},
                      {"visibleFaces", packet_frame.visible_faces},
                      {"indices", with_suffix(options.output_prefix, artifact_suffix + ".idx").generic_string()},
                      {"faces", with_suffix(options.output_prefix, artifact_suffix + ".faces").generic_string()},
                      {"image", with_suffix(options.output_prefix, artifact_suffix + ".bmp").generic_string()},
                      {"nativeImage",
                       with_suffix(options.output_prefix, artifact_suffix + ".native.bmp").generic_string()}}},
                    {"materialReference",
                     {{"contract", "material-distance-v1"},
                      {"diagnosticPixels", std::ranges::count(packet_frame.material_indices, std::uint8_t{0})},
                      {"indices",
                       with_suffix(options.output_prefix, artifact_suffix + ".material.idx").generic_string()},
                      {"image", with_suffix(options.output_prefix, artifact_suffix + ".material.bmp").generic_string()},
                      {"nativeImage",
                       with_suffix(options.output_prefix, artifact_suffix + ".material.native.bmp").generic_string()}}},
                    {"ownerDiffFromPreceding",
                     {{"precedingLayer", preceding},
                      {"image",
                       with_suffix(options.output_prefix, artifact_suffix + ".owner-diff.bmp").generic_string()}}},
                };
            };
        report["packetNearest"] = packet_layer(
            "packed-packet-bvh-nearest-v1",
            "exact oracle-selected packed faces; source-space camera rays; "
            "nearest hit; no projected vertices, clipping, fan spans, or "
            "framebuffer state",
            ".packet-nearest",
            "quantizedWorld",
            *packet_nearest_frame
        );
        report["packetPainter"] = packet_layer(
            "packed-packet-ideal-painter-v1",
            "exact oracle-selected packed faces; source-space camera rays; "
            "last intersected face in far-to-near packet order wins; no "
            "projected vertices, clipping, fan spans, or framebuffer state",
            ".packet-painter",
            "packetNearest",
            *packet_painter_frame
        );
    }
    else
    {
        report["packetNearest"] = nullptr;
        report["packetPainter"] = nullptr;
    }
    if (raster_layers != nullptr)
    {
        const auto raster_layer =
            [&](std::string_view contract,
                std::string_view scope,
                std::string_view order,
                std::string_view suffix,
                const RasterResult& result,
                int working_ram_bytes) {
                const auto artifact_suffix = std::string(suffix);
                const double overdraw =
                    result.stats.unique_samples == 0
                        ? 0.0
                        : static_cast<double>(result.stats.candidate_writes) / result.stats.unique_samples;
                return Json{
                    {"contract", contract},
                    {"scope", scope},
                    {"faceOrder", order},
                    {"workingRamBytes", working_ram_bytes},
                    {"raster",
                     {{"inputFaces", result.stats.input_faces},
                      {"fanTriangles", result.stats.fan_triangles},
                      {"emittedTriangles", result.stats.emitted_triangles},
                      {"nearClippedTriangles", result.stats.near_clipped_triangles},
                      {"boundedRows", result.stats.bounded_rows},
                      {"edgeIntersections", result.stats.edge_intersections},
                      {"edgeAdvances", result.stats.edge_advances},
                      {"spanCalls", result.stats.span_calls},
                      {"candidateWrites", result.stats.candidate_writes},
                      {"plotWrites", result.stats.plot_writes},
                      {"uniqueCoveredSamples", result.stats.unique_samples},
                      {"unwrittenSamples", result.stats.unwritten_samples},
                      {"candidateOverdraw", overdraw}}},
                    {"reference",
                     {{"hitPixels", result.frame.hits},
                      {"missPixels", result.frame.misses},
                      {"uniqueOwnerFaces", result.frame.unique_faces},
                      {"indices", with_suffix(options.output_prefix, artifact_suffix + ".idx").generic_string()},
                      {"faces", with_suffix(options.output_prefix, artifact_suffix + ".faces").generic_string()},
                      {"image", with_suffix(options.output_prefix, artifact_suffix + ".bmp").generic_string()},
                      {"nativeImage",
                       with_suffix(options.output_prefix, artifact_suffix + ".native.bmp").generic_string()}}},
                };
            };
        report["currentPipeline"] = raster_layer(
            "packed-packet-current-gsu-raster-v6",
            "exact Q2 packet face polygons; signed Q6 view transform; fixed "
            "four-plane frustum clip; Q7 projection; bounded whole-convex "
            "two-chain pixel-center spans and exact unpadded horizontal "
            "endpoints",
            "far-to-near painter",
            ".current-pipeline",
            raster_layers->current_pipeline,
            0
        );
        report["legacyWidenedFan"] = raster_layer(
            "packed-packet-legacy-widened-fan-v1",
            "superseded fan/stepped-edge path with seven-sample padding on "
            "both horizontal endpoints and boundary jumps retained",
            "far-to-near painter",
            ".legacy-widened-fan",
            raster_layers->legacy_widened_fan,
            0
        );
        report["convexPainter"] = raster_layer(
            "packed-packet-convex-pixel-center-v1",
            "near-clipped convex face polygons rasterized directly at logical "
            "pixel centers without fan diagonals or conservative widening",
            "far-to-near painter",
            ".convex-painter",
            raster_layers->convex_painter,
            0
        );
        report["frontToBackUncovered"] = raster_layer(
            "packed-packet-front-to-back-uncovered-v1",
            "the same convex pixel-center spans committed only where a bounded "
            "per-row coverage bit remains unset",
            "near-to-far packet reversal",
            ".front-to-back-uncovered",
            raster_layers->front_to_back_uncovered,
            1792
        );
    }
    else
    {
        report["currentPipeline"] = nullptr;
        report["legacyWidenedFan"] = nullptr;
        report["convexPainter"] = nullptr;
        report["frontToBackUncovered"] = nullptr;
    }
    const auto texture_fidelity_json = [&](const TextureMappingFidelity* fidelity, std::string_view contract) -> Json {
        if (fidelity == nullptr)
        {
            return nullptr;
        }
        const auto ratio = [&](int count) { return static_cast<double>(count) / fidelity->comparable_pixels; };
        Json first_beyond_two_texels = nullptr;
        if (fidelity->first_beyond_two_texels >= 0)
        {
            const int pixel = fidelity->first_beyond_two_texels;
            first_beyond_two_texels = {
                {"pixel", pixel},
                {"x", pixel % kLogicalWidth},
                {"y", pixel / kLogicalWidth},
                {"face", fidelity->first_face},
                {"sourceSQ4", fidelity->first_source_s_q4},
                {"sourceTQ4", fidelity->first_source_t_q4},
                {"packedSQ4", fidelity->first_packed_s_q4},
                {"packedTQ4", fidelity->first_packed_t_q4},
                {"sErrorQ4", fidelity->first_s_error_q4},
                {"tErrorQ4", fidelity->first_t_error_q4},
                {"sourceIndex", fidelity->first_source_index},
                {"packedIndex", fidelity->first_packed_index},
            };
        }
        Json first_beyond_four_texels = nullptr;
        if (fidelity->first_beyond_four_texels >= 0)
        {
            const int pixel = fidelity->first_beyond_four_texels;
            first_beyond_four_texels = {
                {"pixel", pixel},
                {"x", pixel % kLogicalWidth},
                {"y", pixel / kLogicalWidth},
            };
        }
        return {
            {"contract", contract},
            {"ownerMatchPixels", fidelity->owner_match_pixels},
            {"ownerMismatchPixels", fidelity->owner_mismatch_pixels},
            {"comparablePixels", fidelity->comparable_pixels},
            {"exactTexelPixels", fidelity->exact_texel_pixels},
            {"exactTexelRatio", ratio(fidelity->exact_texel_pixels)},
            {"withinOneTexelPixels", fidelity->within_one_texel_pixels},
            {"withinOneTexelRatio", ratio(fidelity->within_one_texel_pixels)},
            {"withinTwoTexelsPixels", fidelity->within_two_texel_pixels},
            {"withinTwoTexelsRatio", ratio(fidelity->within_two_texel_pixels)},
            {"withinFourTexelsPixels", fidelity->within_four_texel_pixels},
            {"withinFourTexelsRatio", ratio(fidelity->within_four_texel_pixels)},
            {"meanSErrorQ4", static_cast<double>(fidelity->total_s_error_q4) / fidelity->comparable_pixels},
            {"meanTErrorQ4", static_cast<double>(fidelity->total_t_error_q4) / fidelity->comparable_pixels},
            {"maxSErrorQ4", fidelity->max_s_error_q4},
            {"maxTErrorQ4", fidelity->max_t_error_q4},
            {"firstBeyondTwoTexels", first_beyond_two_texels},
            {"firstBeyondFourTexels", first_beyond_four_texels},
        };
    };
    const auto packed_texture_layer =
        [&](const PackedTextureRaster* raster,
            std::string_view contract,
            std::string_view scope,
            std::string_view suffix,
            std::string_view edge_interpolation,
            std::string_view span_interpolation,
            const TextureMappingFidelity* fidelity,
            std::string_view fidelity_contract) -> Json {
        if (raster == nullptr)
        {
            return nullptr;
        }
        const std::string artifact_suffix(suffix);
        const double overdraw =
            raster->stats.unique_samples == 0
                ? 0.0
                : static_cast<double>(raster->stats.candidate_writes) / raster->stats.unique_samples;
        Json layer = {
            {"contract", contract},
            {"scope", scope},
            {"faceOrder", "far-to-near painter"},
            {"textureCoordinates",
             {{"format", "signed Q4 at vertices; wrapped nonnegative Q4 per pixel"},
              {"clipInterpolation", "signed multiply, shift toward zero"},
              {"edgeInterpolation", edge_interpolation},
              {"spanInterpolation", span_interpolation}}},
            {"raster",
             {{"inputFaces", raster->stats.input_faces},
              {"boundedRows", raster->stats.bounded_rows},
              {"edgeIntersections", raster->stats.edge_intersections},
              {"edgeAdvances", raster->stats.edge_advances},
              {"spanCalls", raster->stats.span_calls},
              {"candidateWrites", raster->stats.candidate_writes},
              {"plotWrites", raster->stats.plot_writes},
              {"candidateOverdraw", overdraw}}},
            {"reference",
             {{"hitPixels", raster->hits},
              {"missPixels", raster->misses},
              {"uniqueOwnerFaces", raster->unique_faces},
              {"indices", with_suffix(options.output_prefix, artifact_suffix + ".idx").generic_string()},
              {"faces", with_suffix(options.output_prefix, artifact_suffix + ".faces").generic_string()},
              {"sQ4", with_suffix(options.output_prefix, artifact_suffix + ".s-q4").generic_string()},
              {"tQ4", with_suffix(options.output_prefix, artifact_suffix + ".t-q4").generic_string()},
              {"spans", with_suffix(options.output_prefix, artifact_suffix + ".spans.json").generic_string()},
              {"lightmappedIndices",
               with_suffix(options.output_prefix, artifact_suffix + ".lightmapped.idx").generic_string()},
              {"lightmapLevels",
               with_suffix(options.output_prefix, artifact_suffix + ".lightmapped.levels").generic_string()},
              {"image", with_suffix(options.output_prefix, artifact_suffix + ".bmp").generic_string()},
              {"nativeImage", with_suffix(options.output_prefix, artifact_suffix + ".native.bmp").generic_string()}}},
            {"sourceMappingFidelity", texture_fidelity_json(fidelity, fidelity_contract)},
        };
        return layer;
    };
    report["packedAffineTexture"] = packed_texture_layer(
        packed_affine_texture_raster,
        "packed-gsu-signed-q4-affine-v1",
        "diagnostic mapping comparison: generated Q2 packet polygons, "
        "signed-Q4 edge coordinates, fixed clip and affine edge/span interpolation",
        ".packed-affine",
        "Q10 affine, shift toward zero",
        "signed quotient/remainder DDA",
        affine_texture_mapping_fidelity,
        "source-bsp-ray-vs-packed-affine-q4-v1"
    );
    report["packedProjectiveTexture"] = packed_texture_layer(
        packed_projective_texture_raster,
        "packed-gsu-q4-projective-block8-lightmap-v1",
        "techniques 2/4/7: generated Q2 packet polygons, pixel-center "
        "endpoints, Q12 perspective edges and eight-pixel perspective span "
        "blocks",
        ".packed-projective",
        "Q12 projective fixed-point interpolation",
        "exact projective block endpoints plus signed quotient/remainder DDA",
        projective_texture_mapping_fidelity,
        "source-bsp-ray-vs-packed-projective-block8-q4-v1"
    );
    if (packed_projective_texture_raster != nullptr)
    {
        report["packedProjectiveTexture"]["reference"]["albedoContract"] = "packed-gsu-q4-projective-block8-albedo-v1";
        report["packedProjectiveTexture"]["reference"]["depthContract"] = "packed-gsu-q4-projective-block8-depth-v1";
        report["packedProjectiveTexture"]["reference"]["lightmapContract"] =
            "packed-gsu-q4-projective-block8-lightmap-v1";
    }
    if (packed_projective_texture_raster != nullptr && !options.packed_albedo_indices.empty())
    {
        report["packedProjectiveTexture"]["reference"]["requestedAlbedoIndices"] =
            options.packed_albedo_indices.generic_string();
    }
    if (packed_projective_texture_raster != nullptr && !options.packed_lightmap_indices.empty())
    {
        report["packedProjectiveTexture"]["reference"]["requestedLightmappedIndices"] =
            options.packed_lightmap_indices.generic_string();
    }
    if (audit.has_value())
    {
        report["packedColorAudit"] = {
            {"records", audit->records},
            {"drawableRecords", audit->drawable_records},
            {"colorMismatches", audit->color_mismatches},
            {"materialRecords", audit->material_records},
            {"materialRecordMismatches", audit->material_record_mismatches},
            {"distanceLutMismatches", audit->distance_lut_mismatches},
            {"shadePairMismatches", audit->shade_pair_mismatches},
        };
    }
    else
    {
        report["packedColorAudit"] = nullptr;
    }
    if (comparison.has_value())
    {
        report["comparison"] = {
            {"passed", comparison->passed},
            {"referenceLayer", "material-distance-v1"},
            {"input", options.snes_frame.generic_string()},
            {"inputFormat", comparison->input_format},
            {"normalizedInput", with_suffix(options.output_prefix, ".snes.idx").generic_string()},
            {"bad2x2Blocks", comparison->bad_2x2},
            {"exactPixels", comparison->exact_pixels},
            {"snesHolePixels", comparison->snes_hole_pixels},
            {"snesFalseGeometryPixels", comparison->snes_false_geometry_pixels},
            {"paletteMismatchPixels", comparison->palette_mismatch_pixels},
            {"geometryPaletteMatchPixels", comparison->geometry_palette_match_pixels},
            {"diffImage", with_suffix(options.output_prefix, ".material.diff.bmp").generic_string()},
        };
    }
    else
    {
        report["comparison"] = nullptr;
    }
    if (packed_texture_comparison.has_value())
    {
        report["packedAffineTextureComparison"] = {
            {"input", options.snes_texture_indices.generic_string()},
            {"inputFormat", "raw 128x112 palette indices"},
            {"referenceLayer", "packed-gsu-signed-q4-affine-v1"},
            {"exactPixels", packed_texture_comparison->exact_pixels},
            {"differentPixels", packed_texture_comparison->different_pixels},
            {"firstMismatch", packed_texture_comparison->first_mismatch},
            {"expectedIndex", packed_texture_comparison->expected_index},
            {"actualIndex", packed_texture_comparison->actual_index},
        };
    }
    else
    {
        report["packedAffineTextureComparison"] = nullptr;
    }
    report["timingMs"] = {
        {"loadSource", load_ms},
        {"buildBvh", build_ms},
        {"render", render_ms},
    };

    std::ofstream out(path);
    if (!out)
    {
        fail("cannot create " + path.string());
    }
    out << report.dump(2) << '\n';
    if (!out)
    {
        fail("cannot write " + path.string());
    }
}

} // namespace quake_bsp_reference
