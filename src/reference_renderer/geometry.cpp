#include "geometry.hpp"
#include "world.hpp"

namespace quake_bsp_reference {

PacketSelection parse_packet_selection(std::span<const std::uint8_t> bytes, const SourceWorld& world)
{
    if (bytes.empty() || (bytes.size() & 1U) != 0)
    {
        fail("packet source-face sidecar must contain non-empty u16 records");
    }
    PacketSelection packet;
    packet.selected_faces.resize(static_cast<std::size_t>(world.face_count));
    packet.painter_ranks.resize(static_cast<std::size_t>(world.face_count), -1);
    if (world.drawable_face_mask.size() != static_cast<std::size_t>(world.face_count))
    {
        fail("packet source-face sidecar requires packed drawability records");
    }
    packet.source_faces.reserve(bytes.size() / 2);
    for (std::size_t offset = 0; offset < bytes.size(); offset += 2)
    {
        const auto face = read_u16(bytes, offset);
        if (face >= static_cast<std::uint16_t>(world.face_count))
        {
            fail("packet source-face sidecar escapes the packed world");
        }
        if (packet.selected_faces[face] != 0)
        {
            fail("packet source-face sidecar contains a duplicate face");
        }
        if (world.drawable_face_mask[face] == 0)
        {
            fail("packet source-face sidecar selects a non-drawable face");
        }
        packet.painter_ranks[face] = static_cast<int>(packet.source_faces.size());
        packet.selected_faces[face] = 1;
        packet.source_faces.push_back(face);
    }
    std::ranges::copy_if(world.triangles, std::back_inserter(packet.triangles), [&](const Triangle& triangle) {
        return packet.selected_faces[triangle.face] != 0;
    });
    return packet;
}

PacketSelection load_packet_selection(const fs::path& path, const SourceWorld& world)
{
    const auto bytes = read_file(path);
    return parse_packet_selection(bytes, world);
}

Camera preset_camera(std::string_view name)
{
    if (name == "spawn" || name == "return-spawn")
    {
        return {-46, -80, -7, 24, 0};
    }
    if (name == "near")
    {
        return {-45, -91, -6, 25, 0};
    }
    if (name == "far")
    {
        return {-77, -41, -13, 8, 0};
    }
    if (name == "yaw")
    {
        return {-46, -80, -7, 0, 0};
    }
    if (name == "pitch")
    {
        return {-46, -80, -7, 24, 3};
    }
    fail("unknown camera preset: " + std::string(name));
}

int table_index(int value)
{
    value %= 32;
    return value < 0 ? value + 32 : value;
}

ViewTransform packed_view_transform(const SourceWorld& world, const Camera& camera)
{
    const double yaw_sin = kSinTable[table_index(camera.yaw)] / 64.0;
    const double yaw_cos = kCosTable[table_index(camera.yaw)] / 64.0;
    const double pitch_sin = kSinTable[table_index(camera.pitch)] / 64.0;
    const double pitch_cos = kCosTable[table_index(camera.pitch)] / 64.0;
    return {
        world.origin + Vec3{camera.x * kWorldScale, camera.y * kWorldScale, camera.z * kWorldScale},
        {pitch_cos * yaw_cos, pitch_cos * yaw_sin, pitch_sin},
        {-yaw_sin, yaw_cos, 0.0},
        {-pitch_sin * yaw_cos, -pitch_sin * yaw_sin, pitch_cos},
    };
}

ViewTransform source_view_transform(const SourceCamera& camera)
{
    constexpr double degrees_to_radians = std::numbers::pi / 180.0;
    const double pitch = camera.pitch * degrees_to_radians;
    const double yaw = camera.yaw * degrees_to_radians;
    const double roll = camera.roll * degrees_to_radians;
    const double pitch_sin = std::sin(pitch);
    const double pitch_cos = std::cos(pitch);
    const double yaw_sin = std::sin(yaw);
    const double yaw_cos = std::cos(yaw);
    const double roll_sin = std::sin(roll);
    const double roll_cos = std::cos(roll);
    // This is Quake's AngleVectors basis. Positive pitch looks down and its
    // right vector follows the original right-handed world convention.
    return {
        camera.origin,
        {pitch_cos * yaw_cos, pitch_cos * yaw_sin, -pitch_sin},
        {-roll_sin * pitch_sin * yaw_cos + roll_cos * yaw_sin,
         -roll_sin * pitch_sin * yaw_sin - roll_cos * yaw_cos,
         -roll_sin * pitch_cos},
        {roll_cos * pitch_sin * yaw_cos + roll_sin * yaw_sin,
         roll_cos * pitch_sin * yaw_sin - roll_sin * yaw_cos,
         roll_cos * pitch_cos},
    };
}

Ray view_ray(const ViewTransform& view, int x, int y)
{
    const double right = (static_cast<double>(x) + 0.5 - 64.0) / kFocalLength;
    const double up = (56.0 - (static_cast<double>(y) + 0.5)) / kFocalLength;
    return {view.origin, view.forward + view.screen_right * right + view.up * up};
}

namespace {
} // namespace

bool face_is_visible(const SourceWorld& world, const Camera& camera, const Vec3& source_camera, std::size_t face)
{
    if (!world.packed_visibility_planes.empty())
    {
        if (!world.plane_cull_guard_mask.empty() && world.plane_cull_guard_mask.at(face) != 0)
        {
            return true;
        }
        const auto& plane = world.packed_visibility_planes.at(face);
        const int coordinate_scale = 1 << world.packed_vertex_fraction_bits;
        auto camera_dot = wrap_i16(static_cast<int>(plane.x) * camera.x * coordinate_scale);
        camera_dot = wrap_i16(static_cast<int>(camera_dot) + static_cast<int>(plane.y) * camera.y * coordinate_scale);
        camera_dot = wrap_i16(static_cast<int>(camera_dot) + static_cast<int>(plane.z) * camera.z * coordinate_scale);
        return wrap_i16(static_cast<int>(camera_dot) - plane.distance) < 0;
    }
    const auto& plane = world.visibility_planes.at(face);
    return dot(source_camera, plane.normal) - plane.distance > kFaceVisibilityEpsilon;
}

ReferenceFrame render_reference_with_view(
    const SourceWorld& world,
    const Bvh& bvh,
    const ViewTransform& view,
    const Camera* packed_camera,
    bool flat,
    std::span<const std::uint8_t> allowed_faces,
    std::span<const int> painter_ranks
)
{
    ReferenceFrame frame;
    frame.indices.assign(kLogicalPixels, kUnwrittenIndex);
    frame.faces.resize(kLogicalPixels, kMissFace);
    frame.entities.resize(kLogicalPixels);
    frame.models.resize(kLogicalPixels);
    frame.depths.resize(kLogicalPixels, std::numeric_limits<double>::infinity());
    if (world.visibility_planes.size() != static_cast<std::size_t>(world.face_count) ||
        (!world.packed_visibility_planes.empty() &&
         world.packed_visibility_planes.size() != static_cast<std::size_t>(world.face_count)))
    {
        fail("reference world has an invalid visibility-plane count");
    }
    if ((!allowed_faces.empty() && allowed_faces.size() != static_cast<std::size_t>(world.face_count)) ||
        (!painter_ranks.empty() && painter_ranks.size() != static_cast<std::size_t>(world.face_count)))
    {
        fail("reference ownership filter has an invalid face count");
    }
    if (!world.packed_visibility_planes.empty() && packed_camera == nullptr)
    {
        fail("packed reference world requires a packed camera");
    }
    std::vector<std::uint8_t> visible_faces(static_cast<std::size_t>(world.face_count));
    for (std::size_t index = 0; index < visible_faces.size(); ++index)
    {
        const bool visible =
            packed_camera != nullptr
                ? face_is_visible(world, *packed_camera, view.origin, index)
                : dot(view.origin, world.visibility_planes.at(index).normal) -
                          world.visibility_planes.at(index).distance >
                      kFaceVisibilityEpsilon;
        if ((allowed_faces.empty() || allowed_faces[index] != 0) && visible)
        {
            visible_faces[index] = 1;
            ++frame.visible_faces;
        }
    }
    std::set<std::uint16_t> unique_faces;
    for (int y = 0; y < kLogicalHeight; ++y)
    {
        for (int x = 0; x < kLogicalWidth; ++x)
        {
            const auto ray = view_ray(view, x, y);
            const auto hit =
                painter_ranks.empty()
                    ? bvh.nearest(ray, visible_faces)
                    : bvh.painter(ray, visible_faces, painter_ranks);
            const auto pixel = logical_pixel_index(x, y);
            if (hit.face == kMissFace)
            {
                ++frame.misses;
                continue;
            }
            ++frame.hits;
            frame.faces[pixel] = hit.face;
            frame.depths[pixel] = hit.depth;
            unique_faces.insert(hit.face);
            if (flat)
            {
                frame.indices[pixel] = hit.color.flat;
            }
            else
            {
                frame.indices[pixel] =
                    ((x ^ y) & 1) != 0
                        ? static_cast<std::uint8_t>(hit.color.dither >> 4U)
                        : static_cast<std::uint8_t>(hit.color.dither & 0x0fU);
            }
        }
    }
    frame.unique_faces = static_cast<int>(unique_faces.size());
    return frame;
}

ReferenceFrame render_reference(
    const SourceWorld& world,
    const Bvh& bvh,
    const Camera& camera,
    bool flat,
    std::span<const std::uint8_t> allowed_faces,
    std::span<const int> painter_ranks
)
{
    return render_reference_with_view(
        world,
        bvh,
        packed_view_transform(world, camera),
        &camera,
        flat,
        allowed_faces,
        painter_ranks
    );
}

std::size_t wrapped_texel(double coordinate, std::uint32_t dimension)
{
    if (!std::isfinite(coordinate) || dimension == 0)
    {
        fail("texture coordinate is non-finite or has a zero-sized axis");
    }
    const auto texel = static_cast<std::int64_t>(std::floor(coordinate));
    const auto size = static_cast<std::int64_t>(dimension);
    const auto wrapped = ((texel % size) + size) % size;
    return static_cast<std::size_t>(wrapped);
}

double projection_plane_distance(double ray_depth)
{
    // view_ray() keeps a unit camera-forward component while its off-axis
    // components grow toward the screen edges.  The intersection parameter is
    // therefore camera-forward depth; using the ray-vector length here would
    // introduce artificial radial darkening on a frontoparallel plane.
    return ray_depth / kWorldScale;
}

ExactTextureSample sample_exact_texture(const SourceWorld& world, std::uint16_t face, const Ray& ray)
{
    const auto face_index = static_cast<std::size_t>(face);
    if (face_index >= world.face_texture_infos.size() || face_index >= world.visibility_planes.size())
    {
        fail("texture sample references an invalid source face");
    }
    const int info_index = world.face_texture_infos[face_index];
    if (info_index < 0 || static_cast<std::size_t>(info_index) >= world.texture_infos.size())
    {
        fail("source face references invalid exact texture information");
    }
    const auto& info = world.texture_infos[static_cast<std::size_t>(info_index)];
    if (info.texture_id < 0 || static_cast<std::size_t>(info.texture_id) >= world.textures.size())
    {
        fail("texture information references an invalid miptex");
    }
    const auto& texture = world.textures[static_cast<std::size_t>(info.texture_id)];
    if (!texture.present || texture.level_zero.size() != static_cast<std::size_t>(texture.width) * texture.height)
    {
        fail("texture information references a missing level-zero miptex");
    }
    const auto& plane = world.visibility_planes[face_index];
    const double denominator = dot(plane.normal, ray.direction);
    if (std::abs(denominator) < 1e-12)
    {
        fail("owned texture sample ray is parallel to its source face");
    }
    const double depth = (plane.distance - dot(plane.normal, ray.origin)) / denominator;
    const Vec3 point = ray.origin + ray.direction * depth;
    const double s = dot(info.s_axis, point) + info.s_offset;
    const double t = dot(info.t_axis, point) + info.t_offset;
    const auto u = wrapped_texel(s, texture.width);
    const auto v = wrapped_texel(t, texture.height);
    return {texture.level_zero[v * texture.width + u], projection_plane_distance(depth), s, t};
}

std::uint8_t
sample_bsp_lightmap_level(const FaceLightmap& lightmap, std::span<const std::uint8_t> lighting, double s, double t)
{
    if (lightmap.light_offset == -1)
    {
        return lightmap.missing_level;
    }
    if (lightmap.width <= 0 || lightmap.height <= 0 || lightmap.style_count <= 0 || lightmap.style_count > 4)
    {
        fail("lightmap sample references invalid face metadata");
    }
    const auto sample_count = static_cast<std::size_t>(lightmap.width) * static_cast<std::size_t>(lightmap.height);
    const auto offset = static_cast<std::size_t>(lightmap.light_offset);
    const auto required = sample_count * static_cast<std::size_t>(lightmap.style_count);
    if (offset > lighting.size() || required > lighting.size() - offset)
    {
        fail("lightmap sample escapes the lighting lump");
    }

    const double u = std::clamp(
        (s - static_cast<double>(lightmap.texture_min_s)) / 16.0,
        0.0,
        static_cast<double>(lightmap.width - 1)
    );
    const double v = std::clamp(
        (t - static_cast<double>(lightmap.texture_min_t)) / 16.0,
        0.0,
        static_cast<double>(lightmap.height - 1)
    );
    const int x0 = static_cast<int>(std::floor(u));
    const int y0 = static_cast<int>(std::floor(v));
    const int x1 = std::min(x0 + 1, lightmap.width - 1);
    const int y1 = std::min(y0 + 1, lightmap.height - 1);
    const double fraction_x = u - x0;
    const double fraction_y = v - y0;
    const auto lerp = [](double first, double second, double fraction) { return first + (second - first) * fraction; };

    double accumulated_8_8 = 0.0;
    for (int style = 0; style < lightmap.style_count; ++style)
    {
        const auto plane = offset + static_cast<std::size_t>(style) * sample_count;
        const auto sample_at = [&](int x, int y) {
            return static_cast<double>(lighting[plane + row_major_index(x, y, lightmap.width)]);
        };
        const double upper = lerp(sample_at(x0, y0), sample_at(x1, y0), fraction_x);
        const double lower = lerp(sample_at(x0, y1), sample_at(x1, y1), fraction_x);
        accumulated_8_8 += lerp(upper, lower, fraction_y) * kQuakeNeutralLightStyleScale;
    }

    const int accumulated = static_cast<int>(std::lround(accumulated_8_8));
    const int inverted = std::max(0, 255 * 256 - accumulated);
    const int darkness_8_8 = std::max(1 << kQuakeColormapBits, inverted >> (8 - kQuakeColormapBits));
    return static_cast<std::uint8_t>(std::min(kQuakeColormapLevels - 1, darkness_8_8 >> 8));
}

std::uint8_t sample_bsp_lightmap_level(const SourceWorld& world, std::uint16_t face, double s, double t)
{
    const auto face_index = static_cast<std::size_t>(face);
    if (face_index >= world.face_lightmaps.size())
    {
        fail("lightmap sample references an invalid source face");
    }
    return sample_bsp_lightmap_level(world.face_lightmaps[face_index], world.lighting, s, t);
}

std::uint8_t
sample_packed_bsp_lightmap_level(const SourceWorld& world, std::uint16_t face, std::int16_t s_q4, std::int16_t t_q4)
{
    const auto& lightmap = world.face_lightmaps.at(face);
    if (lightmap.light_offset == -1)
    {
        return lightmap.missing_level;
    }
    if (lightmap.width <= 0 || lightmap.height <= 0 || lightmap.style_count <= 0 || lightmap.style_count > 4)
    {
        fail("packed lightmap sample references invalid face metadata");
    }
    const auto sample_count = static_cast<std::size_t>(lightmap.width) * static_cast<std::size_t>(lightmap.height);
    const auto offset = static_cast<std::size_t>(lightmap.light_offset);
    const auto required = sample_count * static_cast<std::size_t>(lightmap.style_count);
    if (offset > world.lighting.size() || required > world.lighting.size() - offset)
    {
        fail("packed lightmap sample escapes the lighting lump");
    }
    const auto point_level = [&](int x, int y) {
        const auto sample = row_major_index(x, y, lightmap.width);
        if (lightmap.precombined_compact_levels)
        {
            return static_cast<int>(world.lighting[offset + sample]);
        }
        int accumulated = 0;
        for (int style = 0; style < lightmap.style_count; ++style)
        {
            accumulated += world.lighting[offset + static_cast<std::size_t>(style) * sample_count + sample] *
                           kQuakeNeutralLightStyleScale;
        }
        const int inverted = std::max(0, 255 * 256 - accumulated);
        const int darkness_8_8 = std::max(1 << kQuakeColormapBits, inverted >> (8 - kQuakeColormapBits));
        return std::min(kQuakeColormapLevels - 1, darkness_8_8 >> 8);
    };
    const auto coordinate = [](std::int16_t value, int minimum, int extent) {
        const auto bits = std::bit_cast<std::uint16_t>(value);
        const int block = std::bit_cast<std::int8_t>(static_cast<std::uint8_t>(bits >> 8U));
        const int relative = block - minimum / 16;
        if (relative < 0)
        {
            return std::array<int, 2>{0, 0};
        }
        if (relative >= extent - 1)
        {
            return std::array<int, 2>{extent - 1, 0};
        }
        return std::array<int, 2>{relative, static_cast<int>((bits >> 4U) & 15U)};
    };
    const auto x = coordinate(s_q4, lightmap.texture_min_s, lightmap.width);
    const auto y = coordinate(t_q4, lightmap.texture_min_t, lightmap.height);
    const int x1 = x[0] + (x[1] != 0 ? 1 : 0);
    const int y1 = y[0] + (y[1] != 0 ? 1 : 0);
    const auto lerp_q4 = [](int first, int second, int fraction) {
        return (first * (16 - fraction) + second * fraction + 8) >> 4;
    };
    const int upper = lerp_q4(point_level(x[0], y[0]), point_level(x1, y[0]), x[1]);
    const int lower = lerp_q4(point_level(x[0], y1), point_level(x1, y1), x[1]);
    return static_cast<std::uint8_t>(lerp_q4(upper, lower, y[1]));
}

namespace {
std::uint8_t face_distance_bucket(const SourceWorld& world, std::uint16_t face, const Camera& camera)
{
    const auto centroid = world.centroids.at(static_cast<std::size_t>(face));
    std::array<int, 3> axis_distances = {
        std::abs(static_cast<int>(centroid.x) - camera.x),
        std::abs(static_cast<int>(centroid.y) - camera.y),
        std::abs(static_cast<int>(centroid.z) - camera.z),
    };
    const int largest = std::max({axis_distances[0], axis_distances[1], axis_distances[2]});
    const int smallest = std::min({axis_distances[0], axis_distances[1], axis_distances[2]});
    const int middle = axis_distances[0] + axis_distances[1] + axis_distances[2] - largest - smallest;
    // Max + 1/2 middle + 1/4 min is a useful Euclidean-distance surrogate
    // composed only of integer absolute values, comparisons, adds, and shifts.
    const int distance = largest + (middle >> 1) + (smallest >> 2);
    return kDistanceBucketLut.at(std::min(static_cast<std::size_t>(distance), kDistanceBucketLut.size() - 1));
}
} // namespace

std::uint8_t remap_texture_index(
    const SourceWorld& world,
    std::uint8_t texture_index,
    std::uint8_t colormap_level,
    std::uint8_t identity_level
)
{
    return colormap_level == identity_level
               ? texture_index
               : world.texture_colormap.at(colormap_level).at(texture_index);
}

void shade_exact_texture_frame(ReferenceFrame& frame, const SourceWorld& world, const ViewTransform& view)
{
    if (frame.faces.size() != kLogicalPixels)
    {
        fail("exact texture frame has an invalid owner plane");
    }
    frame.texture_indices.assign(frame.faces.size(), kUnwrittenIndex);
    frame.texture_s.resize(frame.faces.size());
    frame.texture_t.resize(frame.faces.size());
    frame.lightmap_texture_indices.assign(frame.faces.size(), kUnwrittenIndex);
    frame.lightmap_texture_levels.resize(frame.faces.size());
    frame.untextured_lightmap_indices.assign(frame.faces.size(), kUntexturedDiagnosticIndex);
    for (int y = 0; y < kLogicalHeight; ++y)
    {
        for (int x = 0; x < kLogicalWidth; ++x)
        {
            const auto pixel = logical_pixel_index(x, y);
            const auto face = frame.faces[pixel];
            if (face != kMissFace)
            {
                const auto sample = sample_exact_texture(world, face, view_ray(view, x, y));
                frame.texture_indices[pixel] = sample.index;
                frame.texture_s[pixel] = sample.s;
                frame.texture_t[pixel] = sample.t;
                const auto lightmap_level = sample_bsp_lightmap_level(world, face, sample.s, sample.t);
                frame.lightmap_texture_levels[pixel] = lightmap_level;
                frame.lightmap_texture_indices[pixel] = remap_texture_index(world, sample.index, lightmap_level, 0);
                frame.untextured_lightmap_indices[pixel] = untextured_lightmap_index(lightmap_level);
            }
        }
    }
}

std::vector<Camera> load_demo_track(const fs::path& path)
{
    constexpr std::size_t record_bytes = 5;
    const auto bytes = read_file(path);
    if (bytes.empty() || bytes.size() % record_bytes != 0)
    {
        fail("demo track must contain non-empty five-byte camera records");
    }
    std::vector<Camera> cameras;
    cameras.reserve(bytes.size() / record_bytes);
    for (std::size_t offset = 0; offset < bytes.size(); offset += record_bytes)
    {
        const auto signed_byte = [&](std::size_t index) {
            return static_cast<int>(std::bit_cast<std::int8_t>(bytes[offset + index]));
        };
        cameras.push_back(
            {signed_byte(0), signed_byte(1), signed_byte(2), static_cast<int>(bytes[offset + 3]), signed_byte(4)}
        );
    }
    return cameras;
}

std::vector<std::uint16_t> load_demo_timing(const fs::path& path, std::size_t expected_samples)
{
    const auto bytes = read_file(path);
    if (bytes.size() != expected_samples * 2U || bytes.empty())
    {
        fail("demo timing must contain one uint16 tick per camera sample");
    }
    std::vector<std::uint16_t> ticks;
    ticks.reserve(expected_samples);
    for (std::size_t offset = 0; offset < bytes.size(); offset += 2U)
    {
        ticks.push_back(
            static_cast<std::uint16_t>(
                static_cast<std::uint16_t>(bytes[offset]) | (static_cast<std::uint16_t>(bytes[offset + 1U]) << 8U)
            )
        );
    }
    if (ticks.front() != 0 || !std::is_sorted(ticks.begin(), ticks.end()))
    {
        fail("demo timing ticks must start at zero and be monotonic");
    }
    return ticks;
}

std::vector<SourceCamera> load_precise_demo_track(const fs::path& path)
{
    constexpr std::size_t record_bytes = 10;
    const auto bytes = read_file(path);
    if (bytes.empty() || bytes.size() % record_bytes != 0)
    {
        fail("precise demo track must contain non-empty ten-byte records");
    }
    std::vector<SourceCamera> cameras;
    cameras.reserve(bytes.size() / record_bytes);
    for (std::size_t offset = 0; offset < bytes.size(); offset += record_bytes)
    {
        const auto yaw = read_u16(bytes, offset + 6);
        const auto pitch = read_i16(bytes, offset + 8);
        cameras.push_back({
            {read_i16(bytes, offset) / 8.0, read_i16(bytes, offset + 2) / 8.0, read_i16(bytes, offset + 4) / 8.0},
            static_cast<double>(pitch) * 360.0 / 65536.0,
            static_cast<double>(yaw) * 360.0 / 65536.0,
            0.0,
        });
    }
    return cameras;
}

std::size_t demo_pose_at_tick(const std::vector<std::uint16_t>& ticks, std::uint16_t tick)
{
    const auto end = std::upper_bound(ticks.begin(), ticks.end(), tick);
    return end == ticks.begin() ? 0U : static_cast<std::size_t>(std::distance(ticks.begin(), end) - 1);
}

double constant_step_duration(std::size_t pose_count, double samples_per_second)
{
    if (pose_count == 0 || !std::isfinite(samples_per_second) || samples_per_second <= 0.0)
    {
        fail("constant-step duration received an invalid rate or track");
    }
    return static_cast<double>(pose_count) / samples_per_second;
}

std::size_t constant_step_pose_at_time(std::size_t pose_count, double seconds, double samples_per_second)
{
    if (pose_count == 0 || !std::isfinite(seconds) || seconds < 0.0 || !std::isfinite(samples_per_second) ||
        samples_per_second <= 0.0)
    {
        fail("constant-step playback received invalid time, rate, or track");
    }
    return std::min(pose_count - 1, static_cast<std::size_t>(seconds * samples_per_second));
}

std::vector<std::size_t> step_demo_pose_indices(std::size_t pose_count, std::size_t sample_rate)
{
    if (pose_count == 0 || sample_rate == 0 || sample_rate % static_cast<std::size_t>(kStepDemoFramesPerSecond) != 0)
    {
        fail("step playback requires a divisible fixed-rate canonical track");
    }
    const auto stride = sample_rate / static_cast<std::size_t>(kStepDemoFramesPerSecond);
    std::vector<std::size_t> indices;
    indices.reserve((pose_count + stride - 1U) / stride);
    for (std::size_t index = 0; index < pose_count; index += stride)
    {
        indices.push_back(index);
    }
    return indices;
}

OrderedDemoAdvance advance_ordered_demo_pose(std::size_t pose_count, std::size_t& pose, std::size_t stride)
{
    if (pose_count == 0 || pose >= pose_count || stride == 0)
    {
        fail("ordered playback received an invalid pose, stride, or track");
    }
    if (stride < pose_count - pose)
    {
        pose += stride;
        return {true, false};
    }
    pose = 0;
    return {true, true};
}

bool consume_ordered_demo_deadline(double frame_seconds, bool frame_presented, double& elapsed_seconds)
{
    if (!std::isfinite(frame_seconds) || frame_seconds <= 0.0 || !std::isfinite(elapsed_seconds) ||
        elapsed_seconds < 0.0)
    {
        fail("ordered playback received an invalid wall-clock deadline");
    }
    if (!frame_presented || elapsed_seconds < frame_seconds)
    {
        return false;
    }
    elapsed_seconds -= frame_seconds;
    return true;
}

namespace {
int material_face_shade(const SourceWorld& world, std::uint16_t face, const Camera& camera)
{
    const auto face_index = static_cast<std::size_t>(face);
    const auto distance_bucket = face_distance_bucket(world, face, camera);
    const auto base_color = world.live_base_colors.at(face_index);
    const int texture_family = base_color >> 4U;
    const int base_light_level = static_cast<int>(base_color & 0x0fU);
    const int light_level = kDistanceShadeLut.at(base_light_level).at(distance_bucket);
    return texture_family * kApparentLightLevels + light_level;
}
} // namespace

int material_palette_index(int texture_family, int light_step)
{
    return 1 + texture_family * kPhysicalColorsPerFamily + light_step;
}

std::uint8_t material_shade_index(int shade, int x, int y, bool flat)
{
    const int texture_family = shade / kApparentLightLevels;
    const int light_level = shade % kApparentLightLevels;
    const int low = material_palette_index(texture_family, light_level / 2);
    const int high = material_palette_index(texture_family, (light_level + 1) / 2);
    return static_cast<std::uint8_t>(flat || ((x ^ y) & 1) != 0 ? high : low);
}

void shade_material_frame(ReferenceFrame& frame, const SourceWorld& world, const Camera& camera, bool flat)
{
    frame.material_indices.resize(frame.faces.size());
    std::vector<int> face_shades(static_cast<std::size_t>(world.face_count), -1);
    for (std::size_t index = 0; index < frame.faces.size(); ++index)
    {
        const auto face = frame.faces[index];
        if (face != kMissFace)
        {
            auto& shade = face_shades.at(static_cast<std::size_t>(face));
            if (shade < 0)
            {
                shade = material_face_shade(world, face, camera);
            }
            const int x = static_cast<int>(index % kLogicalWidth);
            const int y = static_cast<int>(index / kLogicalWidth);
            frame.material_indices[index] = material_shade_index(shade, x, y, flat);
        }
    }
}

ReferenceFrame render_material_reference(
    const SourceWorld& world,
    const Bvh& bvh,
    const Camera& camera,
    bool flat,
    std::span<const std::uint8_t> allowed_faces,
    std::span<const int> painter_ranks
)
{
    auto frame = render_reference(world, bvh, camera, flat, allowed_faces, painter_ranks);
    shade_material_frame(frame, world, camera, flat);
    return frame;
}

ReferenceFrame render_source_reference(const SourceWorld& world, const Bvh& bvh, const Camera& camera, bool flat)
{
    auto frame = render_material_reference(world, bvh, camera, flat);
    shade_exact_texture_frame(frame, world, packed_view_transform(world, camera));
    return frame;
}

namespace {
Camera packed_position_for_material_shading(const SourceWorld& world, const SourceCamera& camera)
{
    return {
        static_cast<int>(std::lround((camera.origin.x - world.origin.x) / kWorldScale)),
        static_cast<int>(std::lround((camera.origin.y - world.origin.y) / kWorldScale)),
        static_cast<int>(std::lround((camera.origin.z - world.origin.z) / kWorldScale)),
        0,
        0,
    };
}
} // namespace

ReferenceFrame render_source_reference(const SourceWorld& world, const Bvh& bvh, const SourceCamera& camera, bool flat)
{
    const auto view = source_view_transform(camera);
    auto frame = render_reference_with_view(world, bvh, view, nullptr, flat, {}, {});
    shade_material_frame(frame, world, packed_position_for_material_shading(world, camera), flat);
    shade_exact_texture_frame(frame, world, view);
    return frame;
}

namespace {
int signed_shift6(int value)
{
    return wrap_i16(value >> 6);
}
} // namespace

ViewVertex transform_packed_vertex(const SourceWorld& world, const PackedVertex& vertex, const Camera& camera)
{
    const int yaw = table_index(camera.yaw);
    const int pitch = table_index(camera.pitch);
    const int coordinate_scale = 1 << world.packed_vertex_fraction_bits;
    const int dx = vertex.x - camera.x * coordinate_scale;
    const int dy = vertex.y - camera.y * coordinate_scale;
    const int dz = vertex.z - camera.z * coordinate_scale;
    const auto to_q6 = [&](int value) {
        return world.packed_vertex_fraction_bits == 0 ? value : value >> world.packed_vertex_fraction_bits;
    };
    const int forward_q6 = to_q6(dx * kCosTable[yaw]) + to_q6(dy * kSinTable[yaw]);
    const int right_q6 = to_q6(dy * kCosTable[yaw]) - to_q6(dx * kSinTable[yaw]);
    const int up_q6 = to_q6(dz * kCosTable[pitch]) - signed_shift6(forward_q6 * kSinTable[pitch]);
    const int depth_q6 = signed_shift6(forward_q6 * kCosTable[pitch]) + to_q6(dz * kSinTable[pitch]);
    return {right_q6, up_q6, depth_q6};
}

ProjectedVertex project_packed_vertex(const SourceWorld& world, const PackedVertex& vertex, const Camera& camera)
{
    const auto view = transform_packed_vertex(world, vertex, camera);
    ProjectedVertex result{view, {}, 0};
    if (view.depth_q6 < 64)
    {
        result.state = 2;
        return result;
    }
    if (view.depth_q6 >= 256 * 64)
    {
        return result;
    }
    const int depth_q4 = std::max(4, (view.depth_q6 + 8) >> 4);
    const int reciprocal_q12 = world.reciprocal_table.at(static_cast<std::size_t>(depth_q4));
    result.screen.x = wrap_i16(64 + ((view.right_q6 * reciprocal_q12) >> 12));
    result.screen.y = wrap_i16(56 - ((view.up_q6 * reciprocal_q12) >> 12));
    result.state = 1;
    return result;
}

void raster_pixel(RasterResult& result, int x, int y, std::uint16_t face, bool uncovered_only)
{
    if (x < 0 || x >= kLogicalWidth || y < 0 || y >= kLogicalHeight)
    {
        return;
    }
    ++result.stats.candidate_writes;
    const auto index = logical_pixel_index(x, y);
    if (uncovered_only && result.frame.faces[index] != kMissFace)
    {
        return;
    }
    ++result.stats.plot_writes;
    result.frame.faces[index] = face;
}

namespace {
void raster_hline(RasterResult& result, int x0, int y, int x1, std::uint16_t face, int overlap, bool uncovered_only)
{
    ++result.stats.span_calls;
    if (y < 0 || y >= kLogicalHeight)
    {
        return;
    }
    if (x1 < x0)
    {
        std::swap(x0, x1);
    }
    x0 -= overlap;
    x1 += overlap;
    if (x1 < 0 || x0 >= kLogicalWidth)
    {
        return;
    }
    x0 = std::max(x0, 0);
    x1 = std::min(x1, kLogicalWidth - 1);
    for (int x = x0; x <= x1; ++x)
    {
        raster_pixel(result, x, y, face, uncovered_only);
    }
}
} // namespace

void raster_span_band(
    RasterResult& result,
    int start_y,
    int end_y,
    int edge0_start,
    int edge0_end,
    int edge1_start,
    int edge1_end,
    std::uint16_t face,
    int overlap,
    bool boundary_jumps
)
{
    const int dy = end_y - start_y;
    if (dy < 0)
    {
        return;
    }
    EdgeWalker edge0(edge0_start, start_y, edge0_end, end_y);
    EdgeWalker edge1(edge1_start, start_y, edge1_end, end_y);
    int y = start_y;
    for (int scan = 0; scan <= dy; ++scan, ++y)
    {
        const int previous0 = edge0.x;
        const int previous1 = edge1.x;
        raster_hline(result, edge0.x, y, edge1.x, face, overlap, false);
        if (scan == dy)
        {
            break;
        }
        edge0.step();
        edge1.step();
        if (boundary_jumps)
        {
            raster_hline(result, previous0, y + 1, edge0.x, face, overlap, false);
            raster_hline(result, previous1, y, edge1.x, face, overlap, false);
        }
    }
}

namespace {
int raster_split_x(const ScreenPoint& top, const ScreenPoint& middle, const ScreenPoint& bottom)
{
    EdgeWalker edge(top.x, top.y, bottom.x, bottom.y);
    const int steps = middle.y - top.y;
    for (int scan = 0; scan < steps; ++scan)
    {
        edge.step();
    }
    return edge.x;
}
} // namespace

namespace {
void raster_triangle(
    RasterResult& result,
    ScreenPoint first,
    ScreenPoint second,
    ScreenPoint third,
    std::uint16_t face,
    int overlap,
    bool boundary_jumps
)
{
    first.y = std::clamp(first.y, -16, 255);
    second.y = std::clamp(second.y, -16, 255);
    third.y = std::clamp(third.y, -16, 255);
    std::array<ScreenPoint, 3> points = {first, second, third};
    std::stable_sort(points.begin(), points.end(), [](const ScreenPoint& left, const ScreenPoint& right) {
        return left.y < right.y;
    });
    const auto& top = points[0];
    const auto& middle = points[1];
    const auto& bottom = points[2];
    if (bottom.y == top.y)
    {
        return;
    }
    ++result.stats.emitted_triangles;
    if (top.y == middle.y)
    {
        raster_span_band(result, top.y, bottom.y, top.x, bottom.x, middle.x, bottom.x, face, overlap, boundary_jumps);
        return;
    }
    if (middle.y == bottom.y)
    {
        raster_span_band(result, top.y, bottom.y, top.x, middle.x, top.x, bottom.x, face, overlap, boundary_jumps);
        return;
    }
    const int split = raster_split_x(top, middle, bottom);
    raster_span_band(result, top.y, middle.y, top.x, middle.x, top.x, split, face, overlap, boundary_jumps);
    raster_span_band(result, middle.y, bottom.y, middle.x, bottom.x, split, bottom.x, face, overlap, boundary_jumps);
}
} // namespace

namespace {
ScreenPoint clip_edge_to_near(const ViewVertex& inside, const ViewVertex& outside)
{
    const int denominator = inside.depth_q6 - outside.depth_q6;
    if (inside.depth_q6 < 64 || outside.depth_q6 >= 64 || denominator <= 0)
    {
        fail("near-edge clip endpoints violate the inside/outside contract");
    }
    const int ratio = std::clamp(((inside.depth_q6 - 64) * 1024) / denominator, 0, 1024);
    const bool inside_base = ratio < 512;
    const int factor = inside_base ? ratio : 1024 - ratio;
    const ViewVertex& base = inside_base ? inside : outside;
    const ViewVertex& other = inside_base ? outside : inside;
    const auto interpolate_q6 = [&](int base_component, int other_component) {
        const int delta = other_component - base_component;
        const int q6 = base_component + ((delta * factor) >> 10);
        return std::clamp(q6, -16384, 16383);
    };
    const int right_q6 = interpolate_q6(base.right_q6, other.right_q6);
    const int up_q6 = interpolate_q6(base.up_q6, other.up_q6);
    return {
        wrap_i16(64 + ((right_q6 * 96) >> 6)),
        wrap_i16(56 - ((up_q6 * 96) >> 6)),
    };
}
} // namespace

namespace {
void raster_projected_triangle(
    RasterResult& result,
    const std::array<ProjectedVertex, 3>& vertices,
    std::uint16_t face,
    int overlap,
    bool boundary_jumps
)
{
    int invalid = 0;
    for (std::size_t index = 0; index < vertices.size(); ++index)
    {
        if (vertices[index].state != 1)
        {
            invalid |= 1 << index;
        }
    }
    if (invalid == 0)
    {
        raster_triangle(
            result,
            vertices[0].screen,
            vertices[1].screen,
            vertices[2].screen,
            face,
            overlap,
            boundary_jumps
        );
        return;
    }
    ++result.stats.near_clipped_triangles;
    if (invalid == 7)
    {
        return;
    }

    int a = 0;
    int b = 1;
    int c = 2;
    bool one_outside = false;
    switch (invalid)
    {
    case 4:
        one_outside = true;
        break;
    case 1:
        a = 1;
        b = 2;
        c = 0;
        one_outside = true;
        break;
    case 2:
        a = 2;
        b = 0;
        c = 1;
        one_outside = true;
        break;
    case 6:
        break;
    case 5:
        a = 1;
        b = 2;
        c = 0;
        break;
    case 3:
        a = 2;
        b = 0;
        c = 1;
        break;
    default:
        return;
    }
    if (one_outside)
    {
        const auto intersection0 = clip_edge_to_near(vertices[b].view, vertices[c].view);
        const auto intersection1 = clip_edge_to_near(vertices[a].view, vertices[c].view);
        raster_triangle(result, vertices[a].screen, vertices[b].screen, intersection0, face, overlap, boundary_jumps);
        raster_triangle(result, vertices[a].screen, intersection0, intersection1, face, overlap, boundary_jumps);
    }
    else
    {
        const auto intersection0 = clip_edge_to_near(vertices[a].view, vertices[b].view);
        const auto intersection1 = clip_edge_to_near(vertices[a].view, vertices[c].view);
        raster_triangle(result, vertices[a].screen, intersection0, intersection1, face, overlap, boundary_jumps);
    }
}
} // namespace

int floor_divide(int numerator, int denominator)
{
    if (denominator <= 0)
    {
        fail("fixed raster division requires a positive denominator");
    }
    int quotient = numerator / denominator;
    if (numerator < 0 && numerator % denominator != 0)
    {
        --quotient;
    }
    return quotient;
}

int ceil_divide(int numerator, int denominator)
{
    return -floor_divide(-numerator, denominator);
}

int frustum_distance(const ViewVertex& point, int plane)
{
    const int axis = plane < 2 ? point.right_q6 : point.up_q6;
    const bool subtract_axis = plane == 1 || plane == 2;
    return (point.depth_q6 >> 1) + (subtract_axis ? -(axis >> 1) : (axis >> 1));
}

namespace {
ViewVertex interpolate_frustum_edge(const ViewVertex& inside, const ViewVertex& outside, int plane)
{
    int inside_distance = frustum_distance(inside, plane);
    int outside_distance = -frustum_distance(outside, plane);
    if (inside_distance < 0 || outside_distance <= 0)
    {
        fail("frustum edge endpoints violate the inside/outside contract");
    }
    while (inside_distance + outside_distance > 32767)
    {
        inside_distance >>= 1;
        outside_distance = std::max(1, outside_distance >> 1);
    }
    const int ratio_q12 = std::clamp((inside_distance << 12) / (inside_distance + outside_distance), 0, 4096);
    const bool inside_base = ratio_q12 < 2048;
    const int factor = inside_base ? ratio_q12 : 4096 - ratio_q12;
    const auto interpolate = [&](int inside_component, int outside_component) {
        const int base = inside_base ? inside_component : outside_component;
        const int other = inside_base ? outside_component : inside_component;
        const int product = (other - base) * factor;
        return wrap_i16(base + product / 4096);
    };
    ViewVertex result{
        interpolate(inside.right_q6, outside.right_q6),
        interpolate(inside.up_q6, outside.up_q6),
        interpolate(inside.depth_q6, outside.depth_q6),
    };
    return result;
}
} // namespace

namespace {
std::vector<ViewVertex> clip_fixed_frustum(std::span<const ViewVertex> polygon)
{
    std::vector<ViewVertex> input(polygon.begin(), polygon.end());
    for (int plane = 0; plane < 4; ++plane)
    {
        if (input.empty())
        {
            break;
        }
        std::vector<ViewVertex> output;
        output.reserve(input.size() + 1);
        auto previous = input.back();
        bool previous_inside = frustum_distance(previous, plane) >= 0;
        for (const auto& current : input)
        {
            const int current_distance = frustum_distance(current, plane);
            const bool current_inside = current_distance >= 0;
            if (current_inside != previous_inside)
            {
                output.push_back(
                    current_inside ? interpolate_frustum_edge(current, previous, plane)
                                   : interpolate_frustum_edge(previous, current, plane)
                );
            }
            if (current_inside)
            {
                output.push_back(current);
            }
            previous = current;
            previous_inside = current_inside;
        }
        input = std::move(output);
    }
    return input;
}
} // namespace

namespace {
void raster_fixed_convex_polygon(RasterResult& result, std::span<const ViewVertex> view_polygon, std::uint16_t face)
{
    const auto clipped = clip_fixed_frustum(view_polygon);
    if (clipped.size() < 3)
    {
        return;
    }
    struct FixedPoint
    {
        int x_q7{};
        int y_q7{};
    };
    std::vector<FixedPoint> polygon;
    polygon.reserve(clipped.size());
    for (const auto& point : clipped)
    {
        const int depth = std::max(1, point.depth_q6);
        const auto projected_delta = [&](int component) {
            const int magnitude = std::min(std::abs(component), depth);
            const int ratio_q11 = (magnitude << 11) / depth;
            const int delta_q7 = ratio_q11 * 6;
            return component < 0 ? -delta_q7 : delta_q7;
        };
        polygon.push_back({8192 + projected_delta(point.right_q6), 7168 - projected_delta(point.up_q6)});
    }

    std::size_t top = 0;
    int minimum_y_q7 = polygon.front().y_q7;
    int maximum_y_q7 = polygon.front().y_q7;
    for (std::size_t index = 1; index < polygon.size(); ++index)
    {
        if (polygon[index].y_q7 < minimum_y_q7)
        {
            minimum_y_q7 = polygon[index].y_q7;
            top = index;
        }
        maximum_y_q7 = std::max(maximum_y_q7, polygon[index].y_q7);
    }
    const int first_y = std::max(0, ceil_divide(minimum_y_q7 - 64, 128));
    const int last_y = std::min(kLogicalHeight - 1, floor_divide(maximum_y_q7 - 65, 128));
    if (first_y > last_y)
    {
        return;
    }

    std::size_t forward = top;
    std::size_t reverse = top;
    const auto intersect_chain = [&](std::size_t& current, int direction, int sample_y_q7) {
        for (std::size_t advances = 0; advances < polygon.size(); ++advances)
        {
            const auto next = static_cast<std::size_t>(
                (static_cast<int>(current) + direction + static_cast<int>(polygon.size())) %
                static_cast<int>(polygon.size())
            );
            if (polygon[next].y_q7 <= sample_y_q7)
            {
                current = next;
                ++result.stats.edge_advances;
                continue;
            }
            const auto& first = polygon[current];
            const auto& second = polygon[next];
            if (first.y_q7 > sample_y_q7)
            {
                fail("fixed convex boundary is not Y-monotonic");
            }
            const int dy = second.y_q7 - first.y_q7;
            const int offset = sample_y_q7 - first.y_q7;
            const int factor_q10 = (offset << 10) / dy;
            ++result.stats.edge_intersections;
            return first.x_q7 + (((second.x_q7 - first.x_q7) * factor_q10) >> 10);
        }
        fail("fixed convex boundary has no active edge");
    };

    for (int y = first_y; y <= last_y; ++y)
    {
        ++result.stats.bounded_rows;
        const int sample_y_q7 = y * 128 + 64;
        const int forward_x_q7 = intersect_chain(forward, 1, sample_y_q7);
        const int reverse_x_q7 = intersect_chain(reverse, -1, sample_y_q7);
        const int minimum_x_q7 = std::min(forward_x_q7, reverse_x_q7);
        const int maximum_x_q7 = std::max(forward_x_q7, reverse_x_q7);
        const int first_x = std::max(0, ceil_divide(minimum_x_q7 - 68, 128));
        const int last_x = std::min(kLogicalWidth - 1, floor_divide(maximum_x_q7 - 60, 128));
        if (first_x <= last_x)
        {
            raster_hline(result, first_x, y, last_x, face, 0, false);
        }
    }
}
} // namespace

void finalize_raster_result(
    RasterResult& result,
    const SourceWorld& world,
    const Camera& camera,
    bool flat,
    int visible_faces
)
{
    result.frame.visible_faces = visible_faces;
    std::set<std::uint16_t> faces;
    for (const auto face : result.frame.faces)
    {
        if (face == kMissFace)
        {
            ++result.frame.misses;
        }
        else
        {
            ++result.frame.hits;
            faces.insert(face);
        }
    }
    result.frame.unique_faces = static_cast<int>(faces.size());
    result.stats.unique_samples = result.frame.hits;
    result.stats.unwritten_samples = result.frame.misses;
    shade_material_frame(result.frame, world, camera, flat);
    result.frame.indices = result.frame.material_indices;
}

RasterResult render_current_pipeline(
    const SourceWorld& world,
    const PacketSelection& packet,
    const Camera& camera,
    bool flat,
    int overlap,
    bool boundary_jumps
)
{
    if (world.packed_vertices.empty() || world.face_vertex_ids.empty() || world.reciprocal_table.size() != 1024)
    {
        fail("current-pipeline render requires complete packed projection data");
    }
    RasterResult result;
    result.frame.faces.resize(kLogicalPixels, kMissFace);
    std::vector<ProjectedVertex> projected;
    projected.reserve(world.packed_vertices.size());
    for (const auto& vertex : world.packed_vertices)
    {
        projected.push_back(project_packed_vertex(world, vertex, camera));
    }
    for (const auto face : packet.source_faces)
    {
        const auto& polygon = world.face_vertex_ids.at(face);
        if (polygon.size() < 3)
        {
            fail("current-pipeline packet contains a non-polygon face");
        }
        ++result.stats.input_faces;
        if (overlap == 0)
        {
            std::vector<ViewVertex> view_polygon;
            view_polygon.reserve(polygon.size());
            for (const auto vertex : polygon)
            {
                view_polygon.push_back(projected.at(vertex).view);
            }
            result.stats.fan_triangles += static_cast<int>(polygon.size()) - 2;
            raster_fixed_convex_polygon(result, view_polygon, face);
            continue;
        }
        for (std::size_t index = 1; index + 1 < polygon.size(); ++index)
        {
            ++result.stats.fan_triangles;
            const std::array<ProjectedVertex, 3> triangle = {
                projected.at(polygon[0]),
                projected.at(polygon[index]),
                projected.at(polygon[index + 1]),
            };
            raster_projected_triangle(result, triangle, face, overlap, boundary_jumps);
        }
    }
    finalize_raster_result(result, world, camera, flat, static_cast<int>(packet.source_faces.size()));
    return result;
}

} // namespace quake_bsp_reference
