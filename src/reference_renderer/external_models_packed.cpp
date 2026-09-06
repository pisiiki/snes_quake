#include "external_models_packed.hpp"
#include "world.hpp"
#include "geometry.hpp"
#include "external_models.hpp"
#include "textured_live.hpp"

namespace quake_bsp_reference {

namespace {
void write_external_bsp_packed_pixel(
    PackedTextureRaster& raster,
    const ExternalBspModel& model,
    const ExternalBspEntityState& entity,
    std::uint16_t model_key,
    std::uint16_t face,
    const Ray& local_ray,
    double server_time,
    std::int16_t depth_q6,
    int x,
    int y
)
{
    const auto pixel = logical_pixel_index(x, y);
    const auto& world = *model.world;
    const auto sample = sample_external_bsp_texture(model, face, local_ray, entity.frame, server_time);
    const auto source_lightmap = sample_bsp_lightmap_level(world, face, sample.s, sample.t);
    const auto lightmap = exact_lightmap_colormap_level(source_lightmap);
    raster.faces[pixel] = face;
    raster.entities[pixel] = entity.entity;
    raster.models[pixel] = model_key;
    raster.depth_q6[pixel] = depth_q6;
    raster.indices[pixel] = sample.index;
    raster.lightmap_levels[pixel] = lightmap;
    raster.lightmapped_indices[pixel] = world.texture_colormap.at(lightmap).at(sample.index);
    raster.untextured_lightmap_indices[pixel] = untextured_lightmap_index(source_lightmap);
    const int s_q4 = wrap_i16(static_cast<int>(std::lround(sample.s * 16.0)));
    const int t_q4 = wrap_i16(static_cast<int>(std::lround(sample.t * 16.0)));
    raster.s_q4[pixel] = static_cast<std::int16_t>(s_q4);
    raster.t_q4[pixel] = static_cast<std::int16_t>(t_q4);
    raster.absolute_s_q4[pixel] = static_cast<std::int16_t>(s_q4);
    raster.absolute_t_q4[pixel] = static_cast<std::int16_t>(t_q4);
}
} // namespace

void compose_packed_external_bsp_models(
    PackedTextureRaster& raster,
    const SourceWorld& packed_world,
    const ExternalBspScene& scene,
    std::span<const ExternalBspEntityState> entities,
    std::size_t sample_index,
    double server_time,
    const Camera& camera,
    ExternalBspCoverage* output_coverage
)
{
    ExternalBspCoverage coverage;
    coverage.active_entities = entities.size();
    std::set<std::uint16_t> active_models;
    const auto view = packed_view_transform(packed_world, camera);
    for (const auto& entity : entities)
    {
        if (entity.model_slot >= scene.models.size())
        {
            fail("external BSP entity at sample " + std::to_string(sample_index) + " references a missing model slot");
        }
        active_models.insert(entity.model_slot);
        auto& entity_coverage = coverage.entity_coverage(entity.entity);
        const auto& model = scene.models[entity.model_slot];
        const auto& world = *model.world;
        const auto basis = external_bsp_basis(entity.angles);
        const Vec3 local_camera = external_bsp_world_to_local(basis, view.origin - entity.origin);
        std::vector<std::uint8_t> visible_faces(world.face_count);
        for (int face = 0; face < world.face_count; ++face)
        {
            const auto& plane = world.visibility_planes.at(face);
            if (dot(local_camera, plane.normal) - plane.distance > kFaceVisibilityEpsilon)
            {
                visible_faces[static_cast<std::size_t>(face)] = 1;
            }
        }
        const auto model_key = static_cast<std::uint16_t>(kExternalBspModelOwnershipBase + entity.model_slot);
        for (int y = 0; y < kLogicalHeight; ++y)
        {
            for (int x = 0; x < kLogicalWidth; ++x)
            {
                const auto ray = external_bsp_local_ray(basis, entity.origin, view_ray(view, x, y));
                const auto hit = model.bvh->nearest(ray, visible_faces);
                if (hit.face == kMissFace)
                {
                    continue;
                }
                ++coverage.candidate_pixels;
                ++entity_coverage.candidate_pixels;
                const auto pixel = logical_pixel_index(x, y);
                const auto scaled_depth = std::lround(hit.depth * 64.0 / kWorldScale);
                if (scaled_depth <= 0 || scaled_depth >= std::numeric_limits<std::int16_t>::max())
                {
                    continue;
                }
                const auto depth_q6 = static_cast<std::int16_t>(scaled_depth);
                if (depth_q6 >= raster.depth_q6[pixel])
                {
                    continue;
                }
                write_external_bsp_packed_pixel(
                    raster,
                    model,
                    entity,
                    model_key,
                    hit.face,
                    ray,
                    server_time,
                    depth_q6,
                    x,
                    y
                );
                ++raster.stats.candidate_writes;
                ++raster.stats.plot_writes;
            }
        }
    }
    coverage.active_models = active_models.size();
    std::set<std::uint16_t> visible_entities;
    std::set<std::uint16_t> visible_models;
    for (std::size_t pixel = 0; pixel < raster.models.size(); ++pixel)
    {
        if (raster.models[pixel] >= kExternalBspModelOwnershipBase && raster.models[pixel] < kMissFace)
        {
            ++coverage.visible_pixels;
            visible_entities.insert(raster.entities[pixel]);
            auto& entity_coverage = coverage.entity_coverage(raster.entities[pixel]);
            ++entity_coverage.visible_pixels;
            if (raster.faces[pixel] >= 64)
            {
                fail("external BSP visible face exceeds uint64 instrumentation");
            }
            entity_coverage.visible_face_mask |= std::uint64_t{1} << raster.faces[pixel];
            visible_models.insert(static_cast<std::uint16_t>(raster.models[pixel] - kExternalBspModelOwnershipBase));
        }
    }
    coverage.visible_entities = visible_entities.size();
    coverage.visible_models = visible_models.size();
    if (output_coverage != nullptr)
    {
        *output_coverage = coverage;
    }
}

} // namespace quake_bsp_reference
