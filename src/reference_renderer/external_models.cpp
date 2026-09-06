#include "external_models.hpp"
#include "world.hpp"
#include "geometry.hpp"
#include "brushes.hpp"

namespace quake_bsp_reference {

ExternalBspCoverage external_bsp_row_coverage(const ExternalBspReplay& replay, std::size_t source_pose)
{
    if (source_pose >= replay.row_snapshots.size())
    {
        fail("external BSP replay row index is out of range");
    }
    const auto& snapshot = replay.snapshots.at(replay.row_snapshots[source_pose]);
    ExternalBspCoverage coverage;
    coverage.active_entities = snapshot.entities.size();
    coverage.active_models = snapshot.active_models;
    return coverage;
}

namespace {
bool valid_external_bsp_name(std::string_view name)
{
    return !name.empty() && name.front() != '*' && name.ends_with(".bsp") &&
           std::all_of(name.begin(), name.end(), [](unsigned char byte) {
               return byte >= 0x20U && byte < 0x7fU && byte != '\\';
           });
}
} // namespace

namespace {
ExternalBspReplay parse_external_bsp_replay(std::span<const std::uint8_t> bytes)
{
    require_range(bytes, 0, kExternalBspReplayHeaderBytes, "QER1 header");
    if (std::string_view(reinterpret_cast<const char*>(bytes.data()), 4) != "QER1")
    {
        fail("external BSP replay does not have QER1 magic");
    }
    const auto version = read_u16(bytes, 4);
    const auto sample_rate = read_u16(bytes, 6);
    const double first_server_time = read_f32(bytes, 8);
    const auto camera_hash = read_brush_u64(bytes, 12);
    const auto row_count = read_u32(bytes, 20);
    const auto snapshot_count = read_u32(bytes, 24);
    const auto state_count = read_u32(bytes, 28);
    const auto model_count = read_u16(bytes, 32);
    const auto model_bytes = read_u16(bytes, 34);
    if (version != kExternalBspReplayVersion || sample_rate == 0 || !std::isfinite(first_server_time) ||
        first_server_time < 0.0 || row_count == 0 || snapshot_count == 0 ||
        model_count > kExternalBspModelOwnershipBase - 1U || model_bytes != kExternalBspReplayModelBytes ||
        snapshot_count > std::numeric_limits<std::uint16_t>::max() + 1ULL)
    {
        fail("QER1 header contract is invalid");
    }
    const auto model_total = checked_stream_bytes(model_count, kExternalBspReplayModelBytes, "QER1 models");
    const auto row_total = checked_stream_bytes(row_count, 2, "QER1 rows");
    const auto snapshot_total = checked_stream_bytes(snapshot_count, kExternalBspReplaySnapshotBytes, "QER1 snapshots");
    const auto state_total = checked_stream_bytes(state_count, kExternalBspReplayStateBytes, "QER1 states");
    std::size_t expected = kExternalBspReplayHeaderBytes;
    for (const auto part : {model_total, row_total, snapshot_total, state_total})
    {
        if (part > std::numeric_limits<std::size_t>::max() - expected)
        {
            fail("QER1 total byte count overflows size_t");
        }
        expected += part;
    }
    if (bytes.size() != expected)
    {
        fail("QER1 has " + std::to_string(bytes.size()) + " bytes; expected exactly " + std::to_string(expected));
    }

    ExternalBspReplay replay;
    replay.sample_rate = sample_rate;
    replay.first_server_time = first_server_time;
    replay.camera_track_fnv1a64 = camera_hash;
    std::size_t cursor = kExternalBspReplayHeaderBytes;
    replay.models.reserve(model_count);
    std::uint16_t previous_precache{};
    for (std::uint16_t slot = 0; slot < model_count; ++slot)
    {
        const auto precache = read_u16(bytes, cursor);
        const auto name_bytes = bytes[cursor + 2];
        if (precache == 0 || precache <= previous_precache || name_bytes == 0 || name_bytes > 61)
        {
            fail("QER1 model directory is not canonical");
        }
        const std::string name(reinterpret_cast<const char*>(bytes.data() + cursor + 3), name_bytes);
        if (!valid_external_bsp_name(name))
        {
            fail("QER1 model is not a canonical external BSP: " + name);
        }
        for (std::size_t padding = name_bytes; padding < 61; ++padding)
        {
            if (bytes[cursor + 3 + padding] != 0)
            {
                fail("QER1 model name has nonzero padding");
            }
        }
        replay.models.push_back({precache, name});
        previous_precache = precache;
        cursor += kExternalBspReplayModelBytes;
    }
    replay.row_snapshots.reserve(row_count);
    for (std::uint32_t row = 0; row < row_count; ++row)
    {
        const auto snapshot = read_u16(bytes, cursor);
        cursor += 2;
        if (snapshot >= snapshot_count)
        {
            fail("QER1 row references a missing snapshot");
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
        cursor += kExternalBspReplaySnapshotBytes;
        if (offset > state_count || count > state_count - offset)
        {
            fail("QER1 snapshot escapes the state array");
        }
        ranges.push_back({offset, count});
    }
    std::vector<ExternalBspEntityState> states;
    states.reserve(state_count);
    for (std::uint32_t state_index = 0; state_index < state_count; ++state_index)
    {
        ExternalBspEntityState state;
        state.entity = read_u16(bytes, cursor);
        state.model_slot = read_u16(bytes, cursor + 2);
        state.frame = bytes[cursor + 4];
        state.origin =
            {read_i16(bytes, cursor + 5) / 8.0, read_i16(bytes, cursor + 7) / 8.0, read_i16(bytes, cursor + 9) / 8.0};
        state.angles = {decode_i8(bytes[cursor + 11]), decode_i8(bytes[cursor + 12]), decode_i8(bytes[cursor + 13])};
        cursor += kExternalBspReplayStateBytes;
        if (state.entity == 0 || state.model_slot >= model_count)
        {
            fail("QER1 state has an invalid entity or model slot");
        }
        states.push_back(state);
    }
    replay.snapshots.reserve(snapshot_count);
    for (std::size_t snapshot = 0; snapshot < ranges.size(); ++snapshot)
    {
        const auto range = ranges[snapshot];
        ExternalBspReplaySnapshot decoded;
        decoded.entities.assign(
            states.begin() + static_cast<std::ptrdiff_t>(range.offset),
            states.begin() + static_cast<std::ptrdiff_t>(range.offset) + static_cast<std::ptrdiff_t>(range.count)
        );
        for (std::size_t index = 0; index < decoded.entities.size(); ++index)
        {
            if (index != 0 && decoded.entities[index - 1].entity >= decoded.entities[index].entity)
            {
                fail("QER1 snapshot entity order is not canonical");
            }
        }
        std::set<std::uint16_t> active_models;
        for (const auto& entity : decoded.entities)
        {
            active_models.insert(entity.model_slot);
        }
        decoded.active_models = active_models.size();
        replay.snapshots.push_back(std::move(decoded));
    }
    return replay;
}
} // namespace

ExternalBspReplay load_external_bsp_replay(const fs::path& path)
{
    return parse_external_bsp_replay(read_file(path));
}

void require_external_bsp_camera_identity(const ExternalBspReplay& replay, const fs::path& camera_track)
{
    const auto actual = brush_fnv1a64(read_file(camera_track));
    if (actual != replay.camera_track_fnv1a64)
    {
        fail("camera track does not match QER1 external BSP replay");
    }
}

ExternalBspScene build_external_bsp_scene(
    std::span<const std::uint8_t> pak_bytes,
    const std::array<Rgb, kQuakePaletteColors>& palette,
    const QuakeColormap& colormap,
    const ExternalBspReplay& replay
)
{
    ExternalBspScene scene;
    scene.models.reserve(replay.models.size());
    for (const auto& record : replay.models)
    {
        const auto bsp = parse_bsp(extract_pak_entry(pak_bytes, record.name), palette, colormap);
        auto world = std::make_unique<SourceWorld>(build_source_world(bsp));
        auto bvh = std::make_unique<Bvh>(std::span<const Triangle>(world->triangles));
        auto texture_animations = build_brush_texture_animations(world->textures);
        scene.models.push_back(
            {record.model_precache_index, record.name, std::move(world), std::move(bvh), std::move(texture_animations)}
        );
    }
    return scene;
}

namespace {
double external_bsp_angle_radians(std::int8_t angle)
{
    const auto protocol_angle = static_cast<std::uint8_t>(angle);
    return static_cast<double>(protocol_angle) * (2.0 * std::numbers::pi / 256.0);
}
} // namespace

ExternalBspBasis external_bsp_basis(const std::array<std::int8_t, 3>& angles)
{
    const double pitch = external_bsp_angle_radians(angles[0]);
    const double yaw = external_bsp_angle_radians(angles[1]);
    const double roll = external_bsp_angle_radians(angles[2]);
    const double sp = std::sin(pitch);
    const double cp = std::cos(pitch);
    const double sy = std::sin(yaw);
    const double cy = std::cos(yaw);
    const double sr = std::sin(roll);
    const double cr = std::cos(roll);
    const Vec3 forward{cp * cy, cp * sy, -sp};
    const Vec3 right{-sr * sp * cy + cr * sy, -sr * sp * sy - cr * cy, -sr * cp};
    const Vec3 up{cr * sp * cy + sr * sy, cr * sp * sy - sr * cy, cr * cp};
    return {forward, {-right.x, -right.y, -right.z}, up};
}

Vec3 external_bsp_world_to_local(const ExternalBspBasis& basis, const Vec3& vector)
{
    return {dot(vector, basis.forward), dot(vector, basis.left), dot(vector, basis.up)};
}

Ray external_bsp_local_ray(const ExternalBspBasis& basis, const Vec3& origin, const Ray& world_ray)
{
    return {
        external_bsp_world_to_local(basis, world_ray.origin - origin),
        external_bsp_world_to_local(basis, world_ray.direction)
    };
}

double external_bsp_server_time(const ExternalBspReplay& replay, std::size_t sample_index)
{
    if (sample_index >= replay.row_count())
    {
        fail("external BSP source pose is out of range");
    }
    return replay.first_server_time + static_cast<double>(sample_index) / replay.sample_rate;
}

ExactTextureSample sample_external_bsp_texture(
    const ExternalBspModel& model,
    std::uint16_t face,
    const Ray& ray,
    std::uint8_t entity_frame,
    double server_time
)
{
    const auto& world = *model.world;
    const auto face_index = static_cast<std::size_t>(face);
    if (face_index >= world.face_texture_infos.size() || face_index >= world.visibility_planes.size())
    {
        fail("external BSP texture sample references an invalid face");
    }
    const int info_index = world.face_texture_infos[face_index];
    if (info_index < 0 || static_cast<std::size_t>(info_index) >= world.texture_infos.size())
    {
        fail("external BSP face references invalid texture information");
    }
    const auto& info = world.texture_infos[static_cast<std::size_t>(info_index)];
    const int texture_id = resolve_brush_texture(model.texture_animations, info.texture_id, entity_frame, server_time);
    if (texture_id < 0 || static_cast<std::size_t>(texture_id) >= world.textures.size())
    {
        fail("external BSP texture animation escaped its miptex array");
    }
    const auto& texture = world.textures[static_cast<std::size_t>(texture_id)];
    if (!texture.present || texture.level_zero.size() != static_cast<std::size_t>(texture.width) * texture.height)
    {
        fail("external BSP face references a missing level-zero miptex");
    }
    const auto& plane = world.visibility_planes[face_index];
    const double denominator = dot(plane.normal, ray.direction);
    if (std::abs(denominator) < 1e-12)
    {
        fail("owned external BSP texture ray is parallel to its face");
    }
    const double depth = (plane.distance - dot(plane.normal, ray.origin)) / denominator;
    const Vec3 point = ray.origin + ray.direction * depth;
    const double s = dot(info.s_axis, point) + info.s_offset;
    const double t = dot(info.t_axis, point) + info.t_offset;
    const auto u = wrapped_texel(s, texture.width);
    const auto v = wrapped_texel(t, texture.height);
    return {texture.level_zero[v * texture.width + u], projection_plane_distance(depth), s, t};
}

namespace {
bool external_bsp_hit_wins(
    const ReferenceFrame& frame,
    std::size_t pixel,
    double depth,
    const ExternalBspEntityState& entity,
    std::uint16_t model_key,
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
    if (frame.models[pixel] < kExternalBspModelOwnershipBase)
    {
        return false;
    }
    if (entity.entity < frame.entities[pixel])
    {
        return true;
    }
    return entity.entity == frame.entities[pixel] &&
           (model_key < frame.models[pixel] || (model_key == frame.models[pixel] && source_face < frame.faces[pixel]));
}
} // namespace

namespace {
void write_external_bsp_source_pixel(
    ReferenceFrame& frame,
    const ExternalBspModel& model,
    const ExternalBspEntityState& entity,
    std::uint16_t model_key,
    std::uint16_t face,
    const Ray& local_ray,
    double depth,
    int x,
    int y,
    double server_time,
    bool flat
)
{
    const auto pixel = logical_pixel_index(x, y);
    const auto& world = *model.world;
    const auto sample = sample_external_bsp_texture(model, face, local_ray, entity.frame, server_time);
    const auto& color = world.colors.at(face);
    frame.faces[pixel] = face;
    frame.entities[pixel] = entity.entity;
    frame.models[pixel] = model_key;
    frame.depths[pixel] = depth;
    frame.indices[pixel] =
        flat ? color.flat : static_cast<std::uint8_t>(((x ^ y) & 1) != 0 ? color.dither >> 4U : color.dither & 0x0fU);
    const auto distance = static_cast<std::size_t>(
        std::clamp(static_cast<int>(sample.distance), 0, static_cast<int>(kDistanceBucketLut.size()) - 1)
    );
    const int texture_family = world.live_base_colors.at(face) >> 4U;
    const int base_light = static_cast<int>(world.live_base_colors.at(face) & 0x0fU);
    const auto bucket = kDistanceBucketLut.at(std::min(distance, kDistanceBucketLut.size() - 1));
    frame.material_indices[pixel] = material_shade_index(
        texture_family * kApparentLightLevels + kDistanceShadeLut.at(base_light).at(bucket),
        x,
        y,
        flat
    );
    frame.texture_indices[pixel] = sample.index;
    frame.texture_s[pixel] = sample.s;
    frame.texture_t[pixel] = sample.t;
    const auto lightmap_level = sample_bsp_lightmap_level(world, face, sample.s, sample.t);
    frame.lightmap_texture_levels[pixel] = lightmap_level;
    frame.lightmap_texture_indices[pixel] = remap_texture_index(world, sample.index, lightmap_level, 0);
    frame.untextured_lightmap_indices[pixel] = untextured_lightmap_index(lightmap_level);
}
} // namespace

void compose_source_external_bsp_models(
    const ExternalBspScene& scene,
    std::span<const ExternalBspEntityState> entities,
    std::size_t sample_index,
    double server_time,
    bool flat,
    const ViewTransform& view,
    ReferenceFrame& frame,
    ExternalBspCoverage* output_coverage
)
{
    ExternalBspCoverage coverage;
    coverage.active_entities = entities.size();
    std::set<std::uint16_t> active_models;
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
                if (external_bsp_hit_wins(frame, pixel, hit.depth, entity, model_key, hit.face))
                {
                    write_external_bsp_source_pixel(
                        frame,
                        model,
                        entity,
                        model_key,
                        hit.face,
                        ray,
                        hit.depth,
                        x,
                        y,
                        server_time,
                        flat
                    );
                }
            }
        }
    }
    coverage.active_models = active_models.size();
    std::set<std::uint16_t> visible_entities;
    std::set<std::uint16_t> visible_models;
    for (std::size_t pixel = 0; pixel < frame.models.size(); ++pixel)
    {
        if (frame.models[pixel] >= kExternalBspModelOwnershipBase && frame.models[pixel] < kMissFace)
        {
            ++coverage.visible_pixels;
            visible_entities.insert(frame.entities[pixel]);
            auto& entity_coverage = coverage.entity_coverage(frame.entities[pixel]);
            ++entity_coverage.visible_pixels;
            if (frame.faces[pixel] >= 64)
            {
                fail("external BSP visible face exceeds uint64 instrumentation");
            }
            entity_coverage.visible_face_mask |= std::uint64_t{1} << frame.faces[pixel];
            visible_models.insert(static_cast<std::uint16_t>(frame.models[pixel] - kExternalBspModelOwnershipBase));
        }
    }
    coverage.visible_entities = visible_entities.size();
    coverage.visible_models = visible_models.size();
    if (output_coverage != nullptr)
    {
        *output_coverage = coverage;
    }
}

Json external_bsp_inspection(
    const ExternalBspReplay& replay,
    std::size_t source_pose,
    bool configured,
    bool effective,
    const ExternalBspCoverage& coverage
)
{
    Json entities = Json::array();
    for (const auto& entity : replay.row(source_pose))
    {
        const auto* entity_coverage = coverage.find_entity_coverage(entity.entity);
        entities.push_back(
            Json{
                {"entity", entity.entity},
                {"modelSlot", entity.model_slot},
                {"frame", entity.frame},
                {"candidatePixels", entity_coverage == nullptr ? 0U : entity_coverage->candidate_pixels},
                {"visiblePixels", entity_coverage == nullptr ? 0U : entity_coverage->visible_pixels},
                {"visibleFaceMask", entity_coverage == nullptr ? 0U : entity_coverage->visible_face_mask}
            }
        );
    }
    return Json{
        {"schema", "quake-reference-external-bsp-inspection-v2"},
        {"available", true},
        {"configured", configured},
        {"effective", effective},
        {"sourcePose", source_pose},
        {"loadedModels", replay.models.size()},
        {"activeEntities", coverage.active_entities},
        {"activeModels", coverage.active_models},
        {"candidatePixels", coverage.candidate_pixels},
        {"visiblePixels", coverage.visible_pixels},
        {"visibleEntities", coverage.visible_entities},
        {"visibleModels", coverage.visible_models},
        {"entities", std::move(entities)}
    };
}

bool run_external_bsp_replay_self_test()
{
    std::vector<std::uint8_t> bytes(kExternalBspReplayHeaderBytes, 0);
    bytes[0] = 'Q';
    bytes[1] = 'E';
    bytes[2] = 'R';
    bytes[3] = '1';
    const auto append_u16_at = [&](std::size_t offset, std::uint16_t value) {
        bytes[offset] = static_cast<std::uint8_t>(value);
        bytes[offset + 1] = static_cast<std::uint8_t>(value >> 8U);
    };
    const auto append_u32_at = [&](std::size_t offset, std::uint32_t value) {
        for (int byte = 0; byte < 4; ++byte)
        {
            bytes[offset + byte] = static_cast<std::uint8_t>(value >> (byte * 8));
        }
    };
    append_u16_at(4, kExternalBspReplayVersion);
    append_u16_at(6, 20);
    append_u32_at(8, std::bit_cast<std::uint32_t>(1.25F));
    append_u32_at(20, 1);
    append_u32_at(24, 1);
    append_u32_at(28, 1);
    append_u16_at(32, 1);
    append_u16_at(34, kExternalBspReplayModelBytes);
    bytes.resize(bytes.size() + kExternalBspReplayModelBytes, 0);
    const auto model = kExternalBspReplayHeaderBytes;
    bytes[model] = 7;
    constexpr std::string_view name = "maps/b_shell0.bsp";
    bytes[model + 2] = static_cast<std::uint8_t>(name.size());
    std::copy(name.begin(), name.end(), bytes.begin() + model + 3);
    bytes.insert(bytes.end(), {0, 0});
    bytes.insert(bytes.end(), {0, 0, 0, 0, 1, 0});
    bytes.insert(bytes.end(), {42, 0, 0, 0, 3, 8, 0, 240, 255, 24, 0, 8, 64, 128});
    const auto replay = parse_external_bsp_replay(bytes);
    const auto yaw_basis = external_bsp_basis({0, 64, 0});
    const auto yaw_forward = external_bsp_world_to_local(yaw_basis, {0.0, 2.0, 0.0});
    const auto yaw_left = external_bsp_world_to_local(yaw_basis, {-3.0, 0.0, 0.0});
    return replay.sample_rate == 20 && replay.row_count() == 1 && replay.models.size() == 1 &&
           replay.models[0].name == name && replay.row(0).size() == 1 && replay.row(0)[0].entity == 42 &&
           replay.row(0)[0].frame == 3 && replay.row(0)[0].angles == std::array<std::int8_t, 3>{8, 64, -128} &&
           exactly_equal(replay.row(0)[0].origin, {1.0, -2.0, 3.0}) &&
           length_squared(yaw_forward - Vec3{2.0, 0.0, 0.0}) < 1e-24 &&
           length_squared(yaw_left - Vec3{0.0, 3.0, 0.0}) < 1e-24;
}

} // namespace quake_bsp_reference
