#include "brushes.hpp"
#include "world.hpp"
#include "geometry.hpp"

namespace quake_bsp_reference {

std::uint64_t read_brush_u64(std::span<const std::uint8_t> bytes, std::size_t offset)
{
    require_range(bytes, offset, 8, "QBR2 uint64");
    std::uint64_t value{};
    for (int byte = 0; byte < 8; ++byte)
    {
        value |= static_cast<std::uint64_t>(bytes[offset + static_cast<std::size_t>(byte)]) << (byte * 8);
    }
    return value;
}

std::uint64_t brush_fnv1a64(std::span<const std::uint8_t> bytes)
{
    std::uint64_t value = 0xCBF29CE484222325ULL;
    for (const auto byte : bytes)
    {
        value = (value ^ byte) * 0x100000001B3ULL;
    }
    return value;
}

std::size_t checked_stream_bytes(std::uint32_t count, std::size_t stride, std::string_view label)
{
    if (count > std::numeric_limits<std::size_t>::max() / stride)
    {
        fail(std::string(label) + " byte count overflows size_t");
    }
    return static_cast<std::size_t>(count) * stride;
}

namespace {
BrushReplay parse_brush_replay(std::span<const std::uint8_t> bytes)
{
    require_range(bytes, 0, kBrushReplayHeaderBytes, "QBR2 header");
    if (std::string_view(reinterpret_cast<const char*>(bytes.data()), 4) != "QBR2")
    {
        fail("brush replay does not have QBR2 magic");
    }
    const auto version = read_u16(bytes, 4);
    const auto sample_rate = read_u16(bytes, 6);
    const double first_server_time = read_f32(bytes, 8);
    const auto camera_track_fnv1a64 = read_brush_u64(bytes, 12);
    const auto row_count = read_u32(bytes, 20);
    const auto snapshot_count = read_u32(bytes, 24);
    const auto state_count = read_u32(bytes, 28);
    if (version != kBrushReplayVersion)
    {
        fail("unsupported QBR2 version " + std::to_string(version));
    }
    if (sample_rate == 0 || sample_rate % 2 != 0 || sample_rate % 10 != 0)
    {
        fail("QBR2 sample rate must be divisible by 2 Hz and 10 Hz clocks");
    }
    if (!std::isfinite(first_server_time) || first_server_time < 0.0)
    {
        fail("QBR2 first server time must be finite and nonnegative");
    }
    if (row_count == 0 || snapshot_count == 0)
    {
        fail("QBR2 must contain at least one row and snapshot");
    }
    if (snapshot_count > std::numeric_limits<std::uint16_t>::max() + 1ULL)
    {
        fail("QBR2 snapshot count exceeds its uint16 row identity");
    }

    const auto row_bytes = checked_stream_bytes(row_count, 2, "QBR2 rows");
    const auto directory_bytes = checked_stream_bytes(snapshot_count, kBrushReplaySnapshotBytes, "QBR2 snapshots");
    const auto state_bytes = checked_stream_bytes(state_count, kBrushReplayStateBytes, "QBR2 states");
    std::size_t expected = kBrushReplayHeaderBytes;
    for (const auto part : {row_bytes, directory_bytes, state_bytes})
    {
        if (part > std::numeric_limits<std::size_t>::max() - expected)
        {
            fail("QBR2 total byte count overflows size_t");
        }
        expected += part;
    }
    if (bytes.size() != expected)
    {
        fail("QBR2 has " + std::to_string(bytes.size()) + " bytes; expected exactly " + std::to_string(expected));
    }

    BrushReplay replay;
    replay.sample_rate = sample_rate;
    replay.first_server_time = first_server_time;
    replay.camera_track_fnv1a64 = camera_track_fnv1a64;
    replay.row_snapshots.reserve(row_count);
    std::size_t cursor = kBrushReplayHeaderBytes;
    for (std::uint32_t row = 0; row < row_count; ++row)
    {
        const auto snapshot = read_u16(bytes, cursor);
        cursor += 2;
        if (snapshot >= snapshot_count)
        {
            fail("QBR2 row " + std::to_string(row) + " references a missing snapshot");
        }
        replay.row_snapshots.push_back(snapshot);
    }

    struct SnapshotRange
    {
        std::uint32_t offset{};
        std::uint16_t count{};
    };
    std::vector<SnapshotRange> ranges;
    ranges.reserve(snapshot_count);
    for (std::uint32_t snapshot = 0; snapshot < snapshot_count; ++snapshot)
    {
        const auto offset = read_u32(bytes, cursor);
        const auto count = read_u16(bytes, cursor + 4);
        cursor += kBrushReplaySnapshotBytes;
        if (offset > state_count || count > state_count - offset)
        {
            fail("QBR2 snapshot " + std::to_string(snapshot) + " escapes the state array");
        }
        ranges.push_back({offset, count});
    }

    std::vector<BrushEntityState> states;
    states.reserve(state_count);
    for (std::uint32_t state_index = 0; state_index < state_count; ++state_index)
    {
        BrushEntityState state;
        state.entity = read_u16(bytes, cursor);
        state.model_index = read_u16(bytes, cursor + 2);
        state.inline_model = read_u16(bytes, cursor + 4);
        state.frame = bytes[cursor + 6];
        state.origin = {
            read_i16(bytes, cursor + 7) / 8.0,
            read_i16(bytes, cursor + 9) / 8.0,
            read_i16(bytes, cursor + 11) / 8.0,
        };
        state.angles = {
            decode_i8(bytes[cursor + 13]),
            decode_i8(bytes[cursor + 14]),
            decode_i8(bytes[cursor + 15]),
        };
        cursor += kBrushReplayStateBytes;
        if (state.entity == 0 || state.model_index == 0 || state.inline_model == 0)
        {
            fail("QBR2 state " + std::to_string(state_index) + " has a zero entity or model identity");
        }
        states.push_back(state);
    }

    replay.snapshots.reserve(snapshot_count);
    for (std::size_t snapshot_index = 0; snapshot_index < ranges.size(); ++snapshot_index)
    {
        const auto range = ranges[snapshot_index];
        BrushReplaySnapshot snapshot;
        snapshot.entities.assign(
            states.begin() + static_cast<std::ptrdiff_t>(range.offset),
            states.begin() + static_cast<std::ptrdiff_t>(range.offset) + static_cast<std::ptrdiff_t>(range.count)
        );
        for (std::size_t index = 0; index < snapshot.entities.size(); ++index)
        {
            if (index != 0 && snapshot.entities[index - 1].entity >= snapshot.entities[index].entity)
            {
                fail(
                    "QBR2 snapshot " + std::to_string(snapshot_index) +
                    " does not have strictly increasing entity identities"
                );
            }
        }
        replay.snapshots.push_back(std::move(snapshot));
    }

    for (std::size_t row = 0; row < replay.row_count(); ++row)
    {
        for (const auto& state : replay.row(row))
        {
            if (state.angles != std::array<std::int8_t, 3>{})
            {
                fail(
                    "nonzero brush angle at sample " + std::to_string(row) + ", entity " +
                    std::to_string(state.entity) + ", inline model *" + std::to_string(state.inline_model)
                );
            }
        }
    }
    return replay;
}
} // namespace

BrushReplay load_brush_replay(const fs::path& path)
{
    return parse_brush_replay(read_file(path));
}

void require_brush_camera_identity(const BrushReplay& replay, const fs::path& camera_track)
{
    const auto actual = brush_fnv1a64(read_file(camera_track));
    if (actual != replay.camera_track_fnv1a64)
    {
        std::ostringstream message;
        message << "camera track does not match QBR2: expected FNV-1a64 " << std::hex << replay.camera_track_fnv1a64
                << ", got " << actual;
        fail(message.str());
    }
}

std::vector<BrushTextureAnimation> build_brush_texture_animations(std::span<const MipTexture> textures)
{
    std::vector<BrushTextureAnimation> result(textures.size());
    for (auto& animation : result)
    {
        animation.regular.fill(-1);
        animation.alternate.fill(-1);
    }
    for (std::size_t texture_id = 0; texture_id < textures.size(); ++texture_id)
    {
        const auto& base = textures[texture_id];
        if (!base.present || base.name.size() < 2 || base.name[0] != '+')
        {
            continue;
        }
        auto& animation = result[texture_id];
        animation.animated = true;
        const char base_frame = base.name[1];
        animation.base_is_alternate =
            (base_frame >= 'A' && base_frame <= 'J') || (base_frame >= 'a' && base_frame <= 'j');
        const std::string_view suffix(base.name.data() + 2, base.name.size() - 2);
        for (std::size_t candidate_id = 0; candidate_id < textures.size(); ++candidate_id)
        {
            const auto& candidate = textures[candidate_id];
            if (!candidate.present || candidate.name.size() < 2 || candidate.name[0] != '+' ||
                std::string_view(candidate.name.data() + 2, candidate.name.size() - 2) != suffix)
            {
                continue;
            }
            char frame = candidate.name[1];
            if (frame >= 'a' && frame <= 'j')
            {
                frame = static_cast<char>(frame - ('a' - 'A'));
            }
            if (frame >= '0' && frame <= '9')
            {
                const int index = frame - '0';
                animation.regular[static_cast<std::size_t>(index)] = static_cast<int>(candidate_id);
                animation.regular_count = std::max(animation.regular_count, index + 1);
            }
            else if (frame >= 'A' && frame <= 'J')
            {
                const int index = frame - 'A';
                animation.alternate[static_cast<std::size_t>(index)] = static_cast<int>(candidate_id);
                animation.alternate_count = std::max(animation.alternate_count, index + 1);
            }
            else
            {
                fail("bad animated texture name " + candidate.name);
            }
        }
        for (int frame = 0; frame < animation.regular_count; ++frame)
        {
            if (animation.regular[static_cast<std::size_t>(frame)] < 0)
            {
                fail("missing regular frame " + std::to_string(frame) + " of animated texture " + base.name);
            }
        }
        for (int frame = 0; frame < animation.alternate_count; ++frame)
        {
            if (animation.alternate[static_cast<std::size_t>(frame)] < 0)
            {
                fail("missing alternate frame " + std::to_string(frame) + " of animated texture " + base.name);
            }
        }
    }
    return result;
}

int resolve_brush_texture(
    std::span<const BrushTextureAnimation> animations,
    int texture_id,
    std::uint8_t entity_frame,
    double server_time
)
{
    if (texture_id < 0 || static_cast<std::size_t>(texture_id) >= animations.size())
    {
        fail("brush face references an invalid texture animation");
    }
    const auto& animation = animations[static_cast<std::size_t>(texture_id)];
    if (!animation.animated)
    {
        return texture_id;
    }

    bool alternate = animation.base_is_alternate;
    if (entity_frame != 0)
    {
        if (alternate && animation.regular_count != 0)
        {
            alternate = false;
        }
        else if (!alternate && animation.alternate_count != 0)
        {
            alternate = true;
        }
    }
    const auto& frames = alternate ? animation.alternate : animation.regular;
    const int count = alternate ? animation.alternate_count : animation.regular_count;
    if (count == 0)
    {
        return texture_id;
    }
    if (!std::isfinite(server_time) || server_time < 0.0)
    {
        fail("brush texture animation received an invalid server time");
    }
    constexpr std::size_t animation_cycle_tenths = 2;
    const auto tenths = static_cast<std::size_t>(server_time * 10.0);
    const auto relative = tenths % (static_cast<std::size_t>(count) * animation_cycle_tenths);
    const auto frame = relative / animation_cycle_tenths;
    return frames.at(frame);
}

namespace {
void append_brush_triangles(
    BrushModelGeometry& model,
    std::span<const Vec3> polygon,
    std::uint16_t local_face,
    FaceColor color
)
{
    std::vector<Vec3> cleaned;
    cleaned.reserve(polygon.size());
    for (const auto& vertex : polygon)
    {
        if (cleaned.empty() || !exactly_equal(cleaned.back(), vertex))
        {
            cleaned.push_back(vertex);
        }
    }
    if (cleaned.size() > 1 && exactly_equal(cleaned.front(), cleaned.back()))
    {
        cleaned.pop_back();
    }
    if (cleaned.size() < 3)
    {
        return;
    }
    for (std::size_t index = 1; index + 1 < cleaned.size(); ++index)
    {
        const auto edge_a = cleaned[index] - cleaned[0];
        const auto edge_b = cleaned[index + 1] - cleaned[0];
        if (length_squared(cross(edge_a, edge_b)) <= 1e-18)
        {
            continue;
        }
        Triangle triangle;
        triangle.first = cleaned[0];
        triangle.second = cleaned[index];
        triangle.third = cleaned[index + 1];
        triangle.centroid = (triangle.first + triangle.second + triangle.third) * (1.0 / 3.0);
        triangle.bounds.include(triangle.first);
        triangle.bounds.include(triangle.second);
        triangle.bounds.include(triangle.third);
        triangle.face = local_face;
        triangle.color = color;
        model.triangles.push_back(triangle);
    }
}
} // namespace

BrushScene build_brush_scene(const BspData& bsp, const BrushReplay& replay)
{
    if (bsp.faces.size() >= kMissFace)
    {
        fail("source BSP has too many faces for brush ownership");
    }
    BrushScene scene;
    scene.models.resize(bsp.models.size());
    scene.texture_animations = build_brush_texture_animations(bsp.textures);
    std::vector<std::uint8_t> referenced_models(bsp.models.size());
    for (const auto& snapshot : replay.snapshots)
    {
        for (const auto& state : snapshot.entities)
        {
            if (state.inline_model >= bsp.models.size())
            {
                fail(
                    "brush entity " + std::to_string(state.entity) + " references missing inline model *" +
                    std::to_string(state.inline_model)
                );
            }
            referenced_models[state.inline_model] = 1;
        }
    }

    for (std::size_t model_id = 1; model_id < referenced_models.size(); ++model_id)
    {
        if (referenced_models[model_id] == 0)
        {
            continue;
        }
        const auto& source_model = bsp.models[model_id];
        if (source_model.first_face < 0 || source_model.face_count <= 0 ||
            static_cast<std::size_t>(source_model.first_face) > bsp.faces.size() ||
            static_cast<std::size_t>(source_model.face_count) >
                bsp.faces.size() - static_cast<std::size_t>(source_model.first_face) ||
            source_model.face_count >= kMissFace)
        {
            fail("inline model *" + std::to_string(model_id) + " has an invalid face range");
        }
        scene.models[model_id].emplace();
        auto& model = *scene.models[model_id];
        model.model = static_cast<std::uint16_t>(model_id);
        model.mins = source_model.mins;
        model.maxs = source_model.maxs;
        model.origin = source_model.origin;
        model.first_face = source_model.first_face;
        model.faces.resize(static_cast<std::size_t>(source_model.face_count));

        for (int local_face = 0; local_face < source_model.face_count; ++local_face)
        {
            const int source_face_id = source_model.first_face + local_face;
            const auto& source_face = bsp.faces[static_cast<std::size_t>(source_face_id)];
            if (source_face.plane < 0 || static_cast<std::size_t>(source_face.plane) >= bsp.planes.size() ||
                source_face.texture_info < 0 ||
                static_cast<std::size_t>(source_face.texture_info) >= bsp.texture_infos.size())
            {
                fail("inline model face references an invalid plane or texinfo");
            }
            const auto& texture_info = bsp.texture_infos[static_cast<std::size_t>(source_face.texture_info)];
            if (texture_info.texture_id < 0 ||
                static_cast<std::size_t>(texture_info.texture_id) >= bsp.textures.size() ||
                static_cast<std::size_t>(texture_info.texture_id) >= bsp.texture_families.size() ||
                !bsp.textures[static_cast<std::size_t>(texture_info.texture_id)].present)
            {
                fail("inline model face references a missing texture");
            }
            auto polygon = polygon_for_face(bsp, source_face);
            if (polygon.empty())
            {
                continue;
            }
            Vec3 centroid{};
            for (const auto& vertex : polygon)
            {
                centroid = centroid + vertex;
            }
            centroid = centroid * (1.0 / static_cast<double>(polygon.size()));
            auto normal = bsp.planes[static_cast<std::size_t>(source_face.plane)].normal;
            double distance = bsp.planes[static_cast<std::size_t>(source_face.plane)].distance;
            if (source_face.side != 0)
            {
                normal = normal * -1.0;
                distance = -distance;
            }
            // Dynamic models may be plane-thin (for example, a button face),
            // so their local bounds are not a valid normalization volume.
            // Keep positional shading in the same world-space bounds used by
            // the static BSP instead.
            const double intensity = face_intensity(normal, centroid, bsp.models.front().mins, bsp.models.front().maxs);
            const auto color = shade_face(intensity);
            auto& face = model.faces[static_cast<std::size_t>(local_face)];
            face.source_face = static_cast<std::uint16_t>(source_face_id);
            face.plane = {normal, distance};
            face.texture_info = source_face.texture_info;
            face.lightmap = make_face_lightmap(
                source_face,
                polygon,
                texture_info,
                bsp.textures[static_cast<std::size_t>(texture_info.texture_id)].name,
                bsp.lighting.size()
            );
            face.color = color;
            face.live_base_color = static_cast<std::uint8_t>(
                (bsp.texture_families[static_cast<std::size_t>(texture_info.texture_id)] << 4U) |
                orientation_light_level(normal)
            );
            face.centroid = centroid;
            append_brush_triangles(model, polygon, static_cast<std::uint16_t>(local_face), color);
        }
        if (model.triangles.empty())
        {
            fail("inline model *" + std::to_string(model_id) + " produced no reference triangles");
        }
        model.bvh.emplace(std::span<const Triangle>(model.triangles));
    }
    return scene;
}

namespace {
void require_translation_only(std::span<const BrushEntityState> entities, std::size_t sample_index)
{
    for (const auto& state : entities)
    {
        if (state.angles != std::array<std::int8_t, 3>{})
        {
            fail(
                "nonzero brush angle at sample " + std::to_string(sample_index) + ", entity " +
                std::to_string(state.entity) + ", inline model *" + std::to_string(state.inline_model)
            );
        }
    }
}
} // namespace

ExactTextureSample sample_brush_texture(
    const SourceWorld& world,
    const BrushScene& scene,
    const BrushModelGeometry& model,
    std::uint16_t local_face,
    const Ray& ray,
    std::uint8_t entity_frame,
    double server_time
)
{
    const auto& face = model.faces.at(local_face);
    const int info_index = face.texture_info;
    if (info_index < 0 || static_cast<std::size_t>(info_index) >= world.texture_infos.size())
    {
        fail("brush face references invalid texture information");
    }
    const auto& info = world.texture_infos[static_cast<std::size_t>(info_index)];
    const int texture_id = resolve_brush_texture(scene.texture_animations, info.texture_id, entity_frame, server_time);
    if (texture_id < 0 || static_cast<std::size_t>(texture_id) >= world.textures.size())
    {
        fail("brush texture animation resolved outside the miptex array");
    }
    const auto& texture = world.textures[static_cast<std::size_t>(texture_id)];
    if (!texture.present || texture.level_zero.size() != static_cast<std::size_t>(texture.width) * texture.height)
    {
        fail("brush face references a missing level-zero miptex");
    }
    const double denominator = dot(face.plane.normal, ray.direction);
    if (std::abs(denominator) < 1e-12)
    {
        fail("owned brush texture ray is parallel to its face");
    }
    const double depth = (face.plane.distance - dot(face.plane.normal, ray.origin)) / denominator;
    const Vec3 point = ray.origin + ray.direction * depth;
    const double s = dot(info.s_axis, point) + info.s_offset;
    const double t = dot(info.t_axis, point) + info.t_offset;
    const auto u = wrapped_texel(s, texture.width);
    const auto v = wrapped_texel(t, texture.height);
    return {texture.level_zero[v * texture.width + u], projection_plane_distance(depth), s, t};
}

namespace {
std::uint8_t brush_distance_bucket(
    const SourceWorld& world,
    const BrushFace& face,
    const BrushEntityState& entity,
    const Vec3& camera_origin
)
{
    const Vec3 centroid = face.centroid + entity.origin;
    std::array<int, 3> axis_distances{};
    for (int axis = 0; axis < 3; ++axis)
    {
        const auto packed_centroid = std::lround((centroid[axis] - world.origin[axis]) / kWorldScale);
        const auto packed_camera = std::lround((camera_origin[axis] - world.origin[axis]) / kWorldScale);
        axis_distances[static_cast<std::size_t>(axis)] = static_cast<int>(std::abs(packed_centroid - packed_camera));
    }
    const int largest = std::max({axis_distances[0], axis_distances[1], axis_distances[2]});
    const int smallest = std::min({axis_distances[0], axis_distances[1], axis_distances[2]});
    const int middle = axis_distances[0] + axis_distances[1] + axis_distances[2] - largest - smallest;
    const int distance = largest + (middle >> 1) + (smallest >> 2);
    return kDistanceBucketLut.at(std::min(static_cast<std::size_t>(distance), kDistanceBucketLut.size() - 1));
}
} // namespace

namespace {
bool brush_hit_wins(
    const ReferenceFrame& frame,
    std::size_t pixel,
    double depth,
    const BrushEntityState& entity,
    std::uint16_t source_face
)
{
    if (frame.faces[pixel] == kMissFace || depth < frame.depths[pixel] - kHitTieEpsilon)
    {
        return true;
    }
    if (std::abs(depth - frame.depths[pixel]) > kHitTieEpsilon)
    {
        return false;
    }
    if (frame.models[pixel] == 0)
    {
        return true;
    }
    if (entity.entity != frame.entities[pixel])
    {
        return entity.entity < frame.entities[pixel];
    }
    if (entity.inline_model != frame.models[pixel])
    {
        return entity.inline_model < frame.models[pixel];
    }
    return source_face < frame.faces[pixel];
}
} // namespace

namespace {
void write_brush_pixel(
    ReferenceFrame& frame,
    const SourceWorld& world,
    const BrushScene& scene,
    const BrushModelGeometry& model,
    const BrushEntityState& entity,
    std::uint16_t local_face,
    const Ray& local_ray,
    double depth,
    double server_time,
    int x,
    int y,
    bool flat
)
{
    const auto pixel = logical_pixel_index(x, y);
    const auto& face = model.faces.at(local_face);
    const auto sample = sample_brush_texture(world, scene, model, local_face, local_ray, entity.frame, server_time);
    frame.faces[pixel] = face.source_face;
    frame.entities[pixel] = entity.entity;
    frame.models[pixel] = entity.inline_model;
    frame.depths[pixel] = depth;
    frame.indices[pixel] =
        flat || ((x ^ y) & 1) != 0
            ? static_cast<std::uint8_t>(face.color.dither >> 4U)
            : static_cast<std::uint8_t>(face.color.dither & 0x0fU);
    if (flat)
    {
        frame.indices[pixel] = face.color.flat;
    }

    const auto distance_bucket = brush_distance_bucket(world, face, entity, local_ray.origin + entity.origin);
    const int texture_family = face.live_base_color >> 4U;
    const int base_light_level = static_cast<int>(face.live_base_color & 0x0fU);
    const int light_level = kDistanceShadeLut.at(base_light_level).at(distance_bucket);
    frame.material_indices[pixel] =
        material_shade_index(texture_family * kApparentLightLevels + light_level, x, y, flat);
    frame.texture_indices[pixel] = sample.index;
    frame.texture_s[pixel] = sample.s;
    frame.texture_t[pixel] = sample.t;
    const auto lightmap_level = sample_bsp_lightmap_level(face.lightmap, world.lighting, sample.s, sample.t);
    frame.lightmap_texture_levels[pixel] = lightmap_level;
    frame.lightmap_texture_indices[pixel] = remap_texture_index(world, sample.index, lightmap_level, 0);
    frame.untextured_lightmap_indices[pixel] = untextured_lightmap_index(lightmap_level);
}
} // namespace

namespace {
void compose_source_brushes(
    const SourceWorld& world,
    const BrushScene& scene,
    std::span<const BrushEntityState> entities,
    std::size_t sample_index,
    double server_time,
    bool flat,
    const ViewTransform& view,
    ReferenceFrame& frame
)
{
    if (frame.depths.size() != kLogicalPixels || frame.entities.size() != kLogicalPixels ||
        frame.models.size() != kLogicalPixels)
    {
        fail("world reference frame is missing brush composition planes");
    }
    for (const auto& entity : entities)
    {
        if (entity.inline_model >= scene.models.size() || !scene.models[entity.inline_model].has_value())
        {
            fail(
                "sample " + std::to_string(sample_index) + ", entity " + std::to_string(entity.entity) +
                " references an unbuilt inline model *" + std::to_string(entity.inline_model)
            );
        }
        const auto& model = *scene.models[entity.inline_model];
        if (!model.bvh.has_value())
        {
            fail("inline brush model is missing its ray index");
        }
        const auto& bvh = model.bvh.value();
        const Vec3 local_camera = view.origin - entity.origin;
        std::vector<std::uint8_t> visible_faces(model.faces.size());
        for (std::size_t face = 0; face < model.faces.size(); ++face)
        {
            const auto& plane = model.faces[face].plane;
            if (dot(local_camera, plane.normal) - plane.distance > kFaceVisibilityEpsilon)
            {
                visible_faces[face] = 1;
                ++frame.visible_faces;
            }
        }
        for (int y = 0; y < kLogicalHeight; ++y)
        {
            for (int x = 0; x < kLogicalWidth; ++x)
            {
                auto local_ray = view_ray(view, x, y);
                local_ray.origin = local_ray.origin - entity.origin;
                const auto hit = bvh.nearest(local_ray, visible_faces);
                if (hit.face == kMissFace)
                {
                    continue;
                }
                const auto pixel = logical_pixel_index(x, y);
                const auto source_face = model.faces.at(hit.face).source_face;
                if (brush_hit_wins(frame, pixel, hit.depth, entity, source_face))
                {
                    write_brush_pixel(
                        frame,
                        world,
                        scene,
                        model,
                        entity,
                        hit.face,
                        local_ray,
                        hit.depth,
                        server_time,
                        x,
                        y,
                        flat
                    );
                }
            }
        }
    }

    frame.hits = 0;
    frame.misses = 0;
    std::set<std::uint16_t> unique_faces;
    for (const auto face : frame.faces)
    {
        if (face == kMissFace)
        {
            ++frame.misses;
        }
        else
        {
            ++frame.hits;
            unique_faces.insert(face);
        }
    }
    frame.unique_faces = static_cast<int>(unique_faces.size());
}
} // namespace

namespace {
ReferenceFrame render_source_reference_with_brushes(
    const SourceWorld& world,
    const Bvh& world_bvh,
    const BrushScene& scene,
    const SourceCamera& camera,
    std::span<const BrushEntityState> entities,
    std::size_t sample_index,
    double server_time,
    bool flat,
    bool enabled
)
{
    if (!enabled)
    {
        return render_source_reference(world, world_bvh, camera, flat);
    }
    require_translation_only(entities, sample_index);
    const auto view = source_view_transform(camera);
    auto frame = render_source_reference(world, world_bvh, camera, flat);
    compose_source_brushes(world, scene, entities, sample_index, server_time, flat, view, frame);
    return frame;
}
} // namespace

ReferenceFrame render_packed_camera_source_reference_with_brushes(
    const SourceWorld& world,
    const Bvh& world_bvh,
    const BrushScene& scene,
    const Camera& camera,
    std::span<const BrushEntityState> entities,
    std::size_t sample_index,
    double server_time,
    bool flat
)
{
    require_translation_only(entities, sample_index);
    const auto view = packed_view_transform(world, camera);
    auto frame = render_reference_with_view(world, world_bvh, view, nullptr, flat, {}, {});
    shade_material_frame(frame, world, camera, flat);
    shade_exact_texture_frame(frame, world, view);
    compose_source_brushes(world, scene, entities, sample_index, server_time, flat, view, frame);
    return frame;
}

ReferenceFrame render_source_reference_with_brushes(
    const SourceWorld& world,
    const Bvh& world_bvh,
    const BrushScene& scene,
    const SourceCamera& camera,
    const BrushReplay& replay,
    std::size_t sample_index,
    bool flat,
    bool enabled
)
{
    if (sample_index >= replay.row_count())
    {
        fail("brush render sample index is out of range");
    }
    const double server_time = replay.first_server_time + static_cast<double>(sample_index) / replay.sample_rate;
    return render_source_reference_with_brushes(
        world,
        world_bvh,
        scene,
        camera,
        replay.row(sample_index),
        sample_index,
        server_time,
        flat,
        enabled
    );
}

namespace {
Triangle make_brush_test_triangle(double x, std::uint16_t face, FaceColor color)
{
    Triangle triangle;
    triangle.first = {x, -32.0, -32.0};
    triangle.second = {x, 32.0, -32.0};
    triangle.third = {x, 0.0, 32.0};
    triangle.centroid = (triangle.first + triangle.second + triangle.third) * (1.0 / 3.0);
    triangle.bounds.include(triangle.first);
    triangle.bounds.include(triangle.second);
    triangle.bounds.include(triangle.third);
    triangle.face = face;
    triangle.color = color;
    return triangle;
}
} // namespace

bool run_brush_reference_self_test()
{
    std::vector<std::uint8_t> encoded;
    const auto append_u16 = [&](std::uint16_t value) {
        encoded.push_back(static_cast<std::uint8_t>(value));
        encoded.push_back(static_cast<std::uint8_t>(value >> 8U));
    };
    const auto append_u32 = [&](std::uint32_t value) {
        for (int byte = 0; byte < 4; ++byte)
        {
            encoded.push_back(static_cast<std::uint8_t>(value >> (byte * 8)));
        }
    };
    const auto append_u64 = [&](std::uint64_t value) {
        for (int byte = 0; byte < 8; ++byte)
        {
            encoded.push_back(static_cast<std::uint8_t>(value >> (byte * 8)));
        }
    };
    encoded.insert(encoded.end(), {'Q', 'B', 'R', '2'});
    append_u16(kBrushReplayVersion);
    append_u16(kBrushReplaySelfTestSampleRate);
    append_u32(std::bit_cast<std::uint32_t>(1.5753059387207031F));
    append_u64(0x123456789ABCDEF0ULL);
    append_u32(2);
    append_u32(1);
    append_u32(1);
    append_u16(0);
    append_u16(0);
    append_u32(0);
    append_u16(1);
    append_u16(42);
    append_u16(3);
    append_u16(1);
    encoded.push_back(1);
    append_u16(std::bit_cast<std::uint16_t>(std::int16_t{8}));
    append_u16(std::bit_cast<std::uint16_t>(std::int16_t{-16}));
    append_u16(std::bit_cast<std::uint16_t>(std::int16_t{24}));
    encoded.insert(encoded.end(), {0, 0, 0});
    const auto replay = parse_brush_replay(encoded);
    if (replay.sample_rate != kBrushReplaySelfTestSampleRate || replay.row_count() != 2 ||
        replay.first_server_time != static_cast<double>(1.5753059387207031F) ||
        replay.camera_track_fnv1a64 != 0x123456789ABCDEF0ULL || replay.row(1).size() != 1 ||
        replay.row(1)[0].entity != 42 || replay.row(1)[0].frame != 1 ||
        !exactly_equal(replay.row(1)[0].origin, {1.0, -2.0, 3.0}))
    {
        return false;
    }

    std::vector<MipTexture> animated = {
        {"+0test", 1, 1, {10}, true},
        {"+1test", 1, 1, {11}, true},
        {"+2test", 1, 1, {12}, true},
        {"+3test", 1, 1, {13}, true},
        {"+Atest", 1, 1, {14}, true},
        {"+Btest", 1, 1, {15}, true},
        {"plain", 1, 1, {7}, true},
    };
    const auto animations = build_brush_texture_animations(animated);
    if (resolve_brush_texture(animations, 0, 0, 0.0) != 0 || resolve_brush_texture(animations, 0, 0, 0.2) != 1 ||
        resolve_brush_texture(animations, 0, 0, 1.5753059387207031) != 3 ||
        resolve_brush_texture(animations, 0, 0, 1.5753059387207031 + 1.0 / kBrushReplaySelfTestSampleRate) != 0 ||
        resolve_brush_texture(animations, 0, 1, 0.0) != 4 || resolve_brush_texture(animations, 4, 1, 0.0) != 0 ||
        resolve_brush_texture(animations, 6, 1, 100.0) != 6)
    {
        return false;
    }

    SourceWorld world;
    world.origin = {};
    world.face_count = 1;
    world.colors = {{2, 0x32}};
    world.visibility_planes = {{{-1.0, 0.0, 0.0}, -10.0}};
    world.face_texture_infos = {0};
    world.face_lightmaps.resize(1);
    world.live_base_colors = {0};
    world.centroids = {{1, 0, 0}};
    world.textures = {{"plain", 1, 1, {7}, true}};
    world.texture_infos = {
        {{0.0, 1.0, 0.0}, 0.0, {0.0, 0.0, 1.0}, 0.0, 0},
    };
    for (auto& level : world.texture_colormap)
    {
        for (std::size_t index = 0; index < level.size(); ++index)
        {
            level[index] = static_cast<std::uint8_t>(index);
        }
    }
    world.triangles.push_back(make_brush_test_triangle(10.0, 0, world.colors[0]));
    const Bvh world_bvh(world.triangles);

    BrushScene scene;
    scene.models.resize(2);
    scene.texture_animations = build_brush_texture_animations(world.textures);
    scene.models[1].emplace();
    auto& model = *scene.models[1];
    model.model = 1;
    model.first_face = 1;
    model.faces.resize(1);
    model.faces[0].source_face = 1;
    model.faces[0].plane = {{-1.0, 0.0, 0.0}, -5.0};
    model.faces[0].texture_info = 0;
    model.faces[0].color = {3, 0x43};
    model.faces[0].centroid = {5.0, 0.0, 0.0};
    model.triangles.push_back(make_brush_test_triangle(5.0, 0, model.faces[0].color));
    model.bvh.emplace(std::span<const Triangle>(model.triangles));

    const SourceCamera camera{{0.0, 0.0, 0.0}, 0.0, 0.0, 0.0};
    BrushEntityState entity{42, 3, 1, 0, {}, {}};
    const std::array<BrushEntityState, 1> entities{entity};
    const auto disabled =
        render_source_reference_with_brushes(world, world_bvh, scene, camera, entities, 0, 0.0, false, false);
    const auto baseline = render_source_reference(world, world_bvh, camera, false);
    if (disabled.faces != baseline.faces || disabled.texture_indices != baseline.texture_indices ||
        disabled.lightmap_texture_indices != baseline.lightmap_texture_indices)
    {
        return false;
    }

    const auto enabled =
        render_source_reference_with_brushes(world, world_bvh, scene, camera, entities, 0, 0.0, false, true);
    const auto center = logical_pixel_index(64, 56);
    if (enabled.faces[center] != 1 || enabled.entities[center] != 42 || enabled.models[center] != 1 ||
        enabled.texture_indices[center] != 7 || enabled.lightmap_texture_indices[center] != 7 ||
        std::abs(enabled.depths[center] - 5.0) > 1e-9)
    {
        return false;
    }

    entity.origin = {10.0, 0.0, 0.0};
    const std::array<BrushEntityState, 1> behind{entity};
    const auto occluded =
        render_source_reference_with_brushes(world, world_bvh, scene, camera, behind, 0, 0.0, false, true);
    if (occluded.models[center] != 0 || occluded.faces[center] != 0)
    {
        return false;
    }

    entity.origin = {};
    entity.angles[0] = 1;
    try
    {
        const std::array<BrushEntityState, 1> angled{entity};
        static_cast<void>(
            render_source_reference_with_brushes(world, world_bvh, scene, camera, angled, 7, 0.0, false, true)
        );
        return false;
    }
    catch (const std::runtime_error& error)
    {
        const std::string message = error.what();
        if (message.find("sample 7") == std::string::npos || message.find("entity 42") == std::string::npos ||
            message.find("*1") == std::string::npos)
        {
            return false;
        }
    }
    return true;
}

} // namespace quake_bsp_reference
