#include "gameplay_models.hpp"
#include "particles.hpp"

namespace quake_bsp_reference {
namespace {
struct ModelFrame
{
    std::vector<Vec3> vertices;
};
struct ModelTriangle
{
    std::array<std::uint32_t, 3> vertices;
    bool front{};
};
struct ModelTexcoord
{
    int seam{}, s{}, t{};
};
struct GameplayMdl
{
    int width{}, height{};
    std::vector<std::uint8_t> skin;
    std::vector<ModelTexcoord> texcoords;
    std::vector<ModelTriangle> triangles;
    std::vector<ModelFrame> frames;
};

GameplayMdl parse_model(std::span<const std::uint8_t> data)
{
    require_range(data, 0, 84, "gameplay MDL header");
    if (read_u32(data, 0) != 0x4f504449 || read_u32(data, 4) != 6)
        fail("gameplay requires Quake MDL version6");
    const Vec3 scale{read_f32(data, 8), read_f32(data, 12), read_f32(data, 16)};
    const Vec3 origin{read_f32(data, 20), read_f32(data, 24), read_f32(data, 28)};
    const auto count = [&](std::size_t position, int maximum) {
        const int value = read_i32(data, position);
        if (value <= 0 || value > maximum)
            fail("invalid gameplay MDL count");
        return value;
    };
    const int skins = count(48, 256), vertices = count(60, 4096), triangles = count(64, 8192), frames = count(68, 4096);
    GameplayMdl model;
    model.width = count(52, 4096);
    model.height = count(56, 4096);
    const auto skin_bytes = static_cast<std::size_t>(model.width) * model.height;
    std::size_t offset = 84;
    for (int index = 0; index < skins; ++index)
    {
        require_range(data, offset, 4, "gameplay MDL skin type");
        const int type = read_i32(data, offset);
        offset += 4;
        int images = 1;
        if (type == 1)
        {
            require_range(data, offset, 4, "gameplay MDL skin group");
            images = read_i32(data, offset);
            offset += 4;
            if (images <= 0 || images > 256)
                fail("invalid MDL skin group");
            require_range(data, offset, static_cast<std::size_t>(images) * 4, "MDL skin intervals");
            offset += static_cast<std::size_t>(images) * 4;
        }
        else if (type != 0)
            fail("invalid MDL skin type");
        require_range(data, offset, skin_bytes * images, "gameplay MDL skin pixels");
        if (index == 0)
            model.skin.assign(data.begin() + offset, data.begin() + offset + skin_bytes);
        offset += skin_bytes * images;
    }
    require_range(data, offset, static_cast<std::size_t>(vertices) * 12, "gameplay MDL texcoords");
    for (int vertex = 0; vertex < vertices; ++vertex, offset += 12)
        model.texcoords.push_back({read_i32(data, offset), read_i32(data, offset + 4), read_i32(data, offset + 8)});
    require_range(data, offset, static_cast<std::size_t>(triangles) * 16, "gameplay MDL triangles");
    for (int triangle = 0; triangle < triangles; ++triangle, offset += 16)
    {
        ModelTriangle item{
            {read_u32(data, offset + 4), read_u32(data, offset + 8), read_u32(data, offset + 12)},
            read_i32(data, offset) != 0
        };
        for (const auto vertex : item.vertices)
            if (vertex >= static_cast<std::uint32_t>(vertices))
                fail("MDL triangle vertex is out of range");
        model.triangles.push_back(item);
    }
    const auto frame_at = [&] {
        require_range(data, offset, 24 + static_cast<std::size_t>(vertices) * 4, "gameplay MDL frame");
        offset += 24;
        ModelFrame result;
        for (int vertex = 0; vertex < vertices; ++vertex, offset += 4)
            result.vertices.push_back(
                {origin.x + scale.x * data[offset],
                 origin.y + scale.y * data[offset + 1],
                 origin.z + scale.z * data[offset + 2]}
            );
        return result;
    };
    for (int frame = 0; frame < frames; ++frame)
    {
        require_range(data, offset, 4, "gameplay MDL frame type");
        const auto type = read_i32(data, offset);
        offset += 4;
        if (type == 0)
            model.frames.push_back(frame_at());
        else if (type == 1)
        {
            require_range(data, offset, 12, "gameplay MDL frame group");
            const int count_frames = read_i32(data, offset);
            offset += 12;
            if (count_frames <= 0 || count_frames > 4096)
                fail("invalid MDL frame group");
            require_range(data, offset, static_cast<std::size_t>(count_frames) * 4, "MDL frame intervals");
            offset += static_cast<std::size_t>(count_frames) * 4;
            for (int member = 0; member < count_frames; ++member)
            {
                auto decoded = frame_at();
                if (member == 0)
                    model.frames.push_back(std::move(decoded));
            }
        }
        else
            fail("invalid MDL frame type");
    }
    return model;
}

bool intersect(const Ray& ray, const std::array<Vec3, 3>& vertices, double& depth, double& u, double& v)
{
    const auto edge1 = vertices[1] - vertices[0], edge2 = vertices[2] - vertices[0];
    const auto p = cross(ray.direction, edge2);
    const double determinant = dot(edge1, p);
    if (std::abs(determinant) < 1e-10)
        return false;
    const auto t = ray.origin - vertices[0];
    u = dot(t, p) / determinant;
    if (u < 0.0 || u > 1.0)
        return false;
    const auto q = cross(t, edge1);
    v = dot(ray.direction, q) / determinant;
    if (v < 0.0 || u + v > 1.0)
        return false;
    depth = dot(edge2, q) / determinant;
    return depth > 1e-7;
}
void compose_cloud(ReferenceFrame& frame, const ViewTransform& view, const ParticleReplay& cloud)
{
    auto colors = frame.texture_indices;
    compose_particles(colors, frame.depths, view, cloud, 0, RenderMode{.textures = true});
    for (std::size_t i = 0; i < colors.size(); ++i)
        if (colors[i] != frame.texture_indices[i])
        {
            frame.texture_indices[i] = frame.lightmap_texture_indices[i] = colors[i];
            frame.untextured_lightmap_indices[i] = kUntexturedBrightIndex;
            if (!frame.turbulent_pixels.empty())
                frame.turbulent_pixels[i] = 0;
        }
}

void compose_impact(ReferenceFrame& frame, const ViewTransform& view, Vec3 origin, unsigned pose)
{
    constexpr std::array<unsigned, 6> counts{10, 20, 8, 18, 40, 80};
    const auto style = pose / 5, age = pose % 5;
    std::uint32_t seed = 1;
    auto random = [&] {
        seed = 214013u * seed + 2531011u;
        return (seed >> 16) & 32767u;
    };
    ParticleReplay cloud;
    auto& particles = cloud.frames.emplace_back().particles;
    const auto fall = 40.0 * (2 * age) * (int(2 * age) - 1) / 800;
    for (unsigned i = 0; i < counts.at(style); ++i)
    {
        const auto life = random() % 5;
        const auto color = std::uint8_t((style < 2 ? 0 : 72) + (random() & 7u));
        const Vec3 offset{double(int(random() & 15u) - 8), double(int(random() & 15u) - 8),
                          double(int(random() & 15u) - 8) - fall};
        if (age <= life)
        {
            auto& particle = particles.emplace_back();
            particle.origin = origin + offset;
            particle.color = color;
        }
    }
    compose_cloud(frame, view, cloud);
}

// Original R_TeleportSplash for the source-geometry reference. The cartridge
// uses seven view-facing raster frames synthesized from the same particle cloud.
void compose_teleport(ReferenceFrame& frame, const ViewTransform& view, Vec3 origin, unsigned age)
{
    std::uint32_t seed = 1;
    auto random = [&] {
        seed = 214013u * seed + 2531011u;
        return (seed >> 16) & 32767u;
    };
    ParticleReplay cloud;
    auto& particles = cloud.frames.emplace_back().particles;
    const double time = age / 20.0;
    for (int x = -16; x < 16; x += 4)
        for (int y = -16; y < 16; y += 4)
            for (int z = -24; z < 32; z += 4)
            {
                const double life = 0.2 + (random() & 7u) * 0.02;
                const auto color = std::uint8_t(7 + (random() & 7u));
                Vec3 offset{x + int(random() & 3u) * 1.0, y + int(random() & 3u) * 1.0, z + int(random() & 3u) * 1.0};
                const double speed = 50 + (random() & 63u);
                if (time > life)
                    continue;
                const double scale = time * speed / std::max(1.0, std::hypot(x, y, z));
                offset = offset + Vec3{y * scale, x * scale, z * scale - 40.0 * age * (int(age) - 1) / 800.0};
                auto& particle = particles.emplace_back();
                particle.origin = origin + offset;
                particle.color = color;
            }
    compose_cloud(frame, view, cloud);
}
} // namespace

class GameplayModels::Impl
{
  public:
    explicit Impl(std::span<const std::uint8_t> pak)
    :
    pak_(pak)
    {
    }

    void compose(ReferenceFrame& frame, const SourceWorld& world, const GameplayRenderSnapshot& snapshot)
    {
        const auto view = source_view_transform(snapshot.source_camera);
        for (const auto& actor : snapshot.actors)
        {
            if (!actor.visible)
                continue;
            if (actor.model == "effects/combat-impact.spr")
            {
                const Vec3 origin = world.origin + Vec3{
                    actor.origin_q3[0] / 8.0, actor.origin_q3[1] / 8.0, actor.origin_q3[2] / 8.0};
                compose_impact(frame, view, origin, actor.mdl_frame);
                continue;
            }
            if (actor.model == "effects/te_teleport.spr")
            {
                const Vec3 origin = world.origin + Vec3{
                    actor.origin_q3[0] / 8.0, actor.origin_q3[1] / 8.0, actor.origin_q3[2] / 8.0};
                if (actor.mdl_frame % 3 == 0)
                    compose_teleport(frame, view, origin, actor.mdl_frame / 3);
                continue;
            }
            auto found = models_.find(actor.model);
            if (found == models_.end())
                found = models_.emplace(actor.model, parse_model(extract_pak_entry(pak_, actor.model))).first;
            const auto& model = found->second;
            if (actor.mdl_frame >= model.frames.size())
                fail("gameplay MDL frame is out of range");
            const Vec3 origin =
                world.origin +
                Vec3{
                    actor.render_origin_q2[0] * (kWorldScale / 4.0),
                    actor.render_origin_q2[1] * (kWorldScale / 4.0),
                    actor.render_origin_q2[2] * (kWorldScale / 4.0)
                };
            const double yaw = actor.yaw * (2.0 * std::numbers::pi / 256.0), cosine = std::cos(yaw),
                         sine = std::sin(yaw);
            std::vector<Vec3> transformed;
            for (const auto& vertex : model.frames[actor.mdl_frame].vertices)
                transformed.push_back(
                    origin + Vec3{cosine * vertex.x - sine * vertex.y, sine * vertex.x + cosine * vertex.y, vertex.z}
                );
            for (const auto& triangle : model.triangles)
            {
                const std::array vertices{
                    transformed[triangle.vertices[0]],
                    transformed[triangle.vertices[1]],
                    transformed[triangle.vertices[2]]
                };
                int first_x = kLogicalWidth - 1, last_x = 0, first_y = kLogicalHeight - 1, last_y = 0;
                bool crosses_near = false;
                int in_front = 0;
                for (const auto& vertex : vertices)
                {
                    const auto delta = vertex - view.origin;
                    const double depth = dot(delta, view.forward);
                    if (depth <= 1.0)
                    {
                        crosses_near = true;
                        continue;
                    }
                    ++in_front;
                    const auto x = static_cast<int>(
                        std::floor(render_center_x() + render_focal_length() * dot(delta, view.screen_right) / depth)
                    );
                    const auto y = static_cast<int>(
                        std::floor(render_center_y() - render_focal_length() * dot(delta, view.up) / depth)
                    );
                    first_x = std::min(first_x, x - 1);
                    last_x = std::max(last_x, x + 1);
                    first_y = std::min(first_y, y - 1);
                    last_y = std::max(last_y, y + 1);
                }
                if (in_front == 0)
                    continue;
                if (crosses_near)
                {
                    first_x = first_y = 0;
                    last_x = kLogicalWidth - 1;
                    last_y = kLogicalHeight - 1;
                }
                first_x = std::max(0, first_x);
                first_y = std::max(0, first_y);
                last_x = std::min(kLogicalWidth - 1, last_x);
                last_y = std::min(kLogicalHeight - 1, last_y);
                for (int y = first_y; y <= last_y; ++y)
                    for (int x = first_x; x <= last_x; ++x)
                    {
                        double depth = 0, u = 0, v = 0;
                        if (!intersect(view_ray(view, x, y), vertices, depth, u, v))
                            continue;
                        const auto pixel = static_cast<std::size_t>(y) * kLogicalWidth + x;
                        if (depth >= frame.depths[pixel] - kHitTieEpsilon)
                            continue;
                        std::array<double, 3> s{}, t{};
                        for (std::size_t corner = 0; corner < 3; ++corner)
                        {
                            const auto& uv = model.texcoords[triangle.vertices[corner]];
                            s[corner] = uv.s + (!triangle.front && uv.seam ? model.width / 2 : 0);
                            t[corner] = uv.t;
                        }
                        const int sx = std::clamp(
                            static_cast<int>(std::floor(s[0] * (1 - u - v) + s[1] * u + s[2] * v)),
                            0,
                            model.width - 1
                        );
                        const int sy = std::clamp(
                            static_cast<int>(std::floor(t[0] * (1 - u - v) + t[1] * u + t[2] * v)),
                            0,
                            model.height - 1
                        );
                        const auto texel = model.skin[static_cast<std::size_t>(sy) * model.width + sx];
                        frame.depths[pixel] = depth;
                        frame.entities[pixel] = actor.entity;
                        frame.texture_indices[pixel] = texel;
                        frame.lightmap_texture_indices[pixel] = texel;
                        frame.untextured_lightmap_indices[pixel] = kUntexturedBrightIndex;
                        if (!frame.turbulent_pixels.empty())
                            frame.turbulent_pixels[pixel] = 0;
                    }
            }
        }
    }

  private:
    std::span<const std::uint8_t> pak_;
    std::map<std::string, GameplayMdl> models_;
};

GameplayModels::GameplayModels(std::span<const std::uint8_t> pak)
:
impl_(std::make_unique<Impl>(pak))
{
}
GameplayModels::~GameplayModels() = default;
void GameplayModels::compose(ReferenceFrame& frame, const SourceWorld& world, const GameplayRenderSnapshot& snapshot)
{
    impl_->compose(frame, world, snapshot);
}

} // namespace quake_bsp_reference
