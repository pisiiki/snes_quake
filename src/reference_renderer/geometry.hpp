#pragma once

#include "world.hpp"

namespace quake_bsp_reference {

struct PacketSelection
{
    std::vector<std::uint16_t> source_faces;
    std::vector<std::uint8_t> selected_faces;
    std::vector<int> painter_ranks;
    std::vector<Triangle> triangles;
};

PacketSelection parse_packet_selection(std::span<const std::uint8_t> bytes, const SourceWorld& world);

PacketSelection load_packet_selection(const fs::path& path, const SourceWorld& world);

struct BvhNode
{
    Aabb bounds;
    std::uint32_t first{};
    std::uint32_t count{};
    std::uint32_t left{};
    std::uint32_t right{};
};

struct Ray
{
    Vec3 origin;
    Vec3 direction;
};

struct Hit
{
    double depth{std::numeric_limits<double>::infinity()};
    std::uint16_t face{kMissFace};
    FaceColor color{};
};

class Bvh
{
  public:
    explicit Bvh(std::span<const Triangle> triangles)
    :
    triangles_(triangles)
    {
        order_.resize(triangles.size());
        std::iota(order_.begin(), order_.end(), std::uint32_t{0});
        nodes_.reserve(triangles.size() * 2);
        build(0, static_cast<std::uint32_t>(order_.size()));
    }

    [[nodiscard]] std::size_t node_count() const
    {
        return nodes_.size();
    }

    [[nodiscard]] Hit nearest(const Ray& ray, std::span<const std::uint8_t> visible_faces) const
    {
        Hit best;
        std::vector<std::uint32_t> stack;
        stack.reserve(64);
        stack.push_back(0);
        while (!stack.empty())
        {
            const auto node_index = stack.back();
            stack.pop_back();
            const auto& node = nodes_[node_index];
            if (!intersects(node.bounds, ray, best.depth + kHitTieEpsilon))
            {
                continue;
            }
            if (node.count != 0)
            {
                for (std::uint32_t index = 0; index < node.count; ++index)
                {
                    const auto& triangle = triangles_[order_[node.first + index]];
                    if (triangle.face >= visible_faces.size() || visible_faces[triangle.face] == 0)
                    {
                        continue;
                    }
                    const auto depth = intersect_triangle(triangle, ray);
                    if (!depth.has_value())
                    {
                        continue;
                    }
                    if (*depth < best.depth - kHitTieEpsilon ||
                        (std::abs(*depth - best.depth) <= kHitTieEpsilon && triangle.face < best.face))
                    {
                        best.depth = *depth;
                        best.face = triangle.face;
                        best.color = triangle.color;
                    }
                }
            }
            else
            {
                stack.push_back(node.right);
                stack.push_back(node.left);
            }
        }
        return best;
    }

    [[nodiscard]] Hit
    painter(const Ray& ray, std::span<const std::uint8_t> visible_faces, std::span<const int> painter_ranks) const
    {
        Hit best;
        int best_rank = -1;
        std::vector<std::uint32_t> stack;
        stack.reserve(64);
        stack.push_back(0);
        while (!stack.empty())
        {
            const auto node_index = stack.back();
            stack.pop_back();
            const auto& node = nodes_[node_index];
            if (!intersects(node.bounds, ray, std::numeric_limits<double>::infinity()))
            {
                continue;
            }
            if (node.count != 0)
            {
                for (std::uint32_t index = 0; index < node.count; ++index)
                {
                    const auto& triangle = triangles_[order_[node.first + index]];
                    if (triangle.face >= visible_faces.size() || triangle.face >= painter_ranks.size() ||
                        visible_faces[triangle.face] == 0 || painter_ranks[triangle.face] < 0)
                    {
                        continue;
                    }
                    const auto depth = intersect_triangle(triangle, ray);
                    const int rank = painter_ranks[triangle.face];
                    if (depth.has_value() && rank > best_rank)
                    {
                        best_rank = rank;
                        best.depth = *depth;
                        best.face = triangle.face;
                        best.color = triangle.color;
                    }
                }
            }
            else
            {
                stack.push_back(node.right);
                stack.push_back(node.left);
            }
        }
        return best;
    }

  private:
    std::span<const Triangle> triangles_;
    std::vector<std::uint32_t> order_;
    std::vector<BvhNode> nodes_;

    std::uint32_t build(std::uint32_t begin, std::uint32_t end)
    {
        const auto node_index = static_cast<std::uint32_t>(nodes_.size());
        nodes_.push_back({});
        Aabb bounds;
        Aabb centroid_bounds;
        for (auto index = begin; index < end; ++index)
        {
            const auto& triangle = triangles_[order_[index]];
            bounds.include(triangle.bounds);
            centroid_bounds.include(triangle.centroid);
        }
        nodes_[node_index].bounds = bounds;
        const auto count = end - begin;
        if (count <= 8)
        {
            nodes_[node_index].first = begin;
            nodes_[node_index].count = count;
            return node_index;
        }
        const Vec3 extent = centroid_bounds.maximum - centroid_bounds.minimum;
        int axis = 0;
        if (extent.y > extent.x)
        {
            axis = 1;
        }
        if (extent.z > extent[axis])
        {
            axis = 2;
        }
        if (extent[axis] <= 1e-12)
        {
            nodes_[node_index].first = begin;
            nodes_[node_index].count = count;
            return node_index;
        }
        const auto middle = begin + count / 2;
        std::nth_element(
            order_.begin() + begin,
            order_.begin() + middle,
            order_.begin() + end,
            [&](std::uint32_t left, std::uint32_t right) {
                const auto& a = triangles_[left];
                const auto& b = triangles_[right];
                if (a.centroid[axis] != b.centroid[axis])
                {
                    return a.centroid[axis] < b.centroid[axis];
                }
                if (a.face != b.face)
                {
                    return a.face < b.face;
                }
                return left < right;
            }
        );
        const auto left = build(begin, middle);
        const auto right = build(middle, end);
        nodes_[node_index].left = left;
        nodes_[node_index].right = right;
        return node_index;
    }

    static bool intersects(const Aabb& bounds, const Ray& ray, double maximum_depth)
    {
        double minimum_depth = 0.0;
        for (int axis = 0; axis < 3; ++axis)
        {
            const double direction = ray.direction[axis];
            if (std::abs(direction) <= 1e-15)
            {
                if (ray.origin[axis] < bounds.minimum[axis] || ray.origin[axis] > bounds.maximum[axis])
                {
                    return false;
                }
                continue;
            }
            const double inverse = 1.0 / direction;
            double first = (bounds.minimum[axis] - ray.origin[axis]) * inverse;
            double second = (bounds.maximum[axis] - ray.origin[axis]) * inverse;
            if (first > second)
            {
                std::swap(first, second);
            }
            minimum_depth = std::max(minimum_depth, first);
            maximum_depth = std::min(maximum_depth, second);
            if (maximum_depth < minimum_depth)
            {
                return false;
            }
        }
        return maximum_depth > 1e-9;
    }

    static std::optional<double> intersect_triangle(const Triangle& triangle, const Ray& ray)
    {
        constexpr double epsilon = 1e-9;
        const auto edge1 = triangle.second - triangle.first;
        const auto edge2 = triangle.third - triangle.first;
        const auto p = cross(ray.direction, edge2);
        const double determinant = dot(edge1, p);
        if (std::abs(determinant) <= epsilon)
        {
            return std::nullopt;
        }
        const double inverse = 1.0 / determinant;
        const auto delta = ray.origin - triangle.first;
        const double u = dot(delta, p) * inverse;
        if (u < -epsilon || u > 1.0 + epsilon)
        {
            return std::nullopt;
        }
        const auto q = cross(delta, edge1);
        const double v = dot(ray.direction, q) * inverse;
        if (v < -epsilon || u + v > 1.0 + epsilon)
        {
            return std::nullopt;
        }
        const double depth = dot(edge2, q) * inverse;
        if (depth <= epsilon)
        {
            return std::nullopt;
        }
        return depth;
    }
};

struct Camera
{
    int x{};
    int y{};
    int z{};
    int yaw{};
    int pitch{};
};

struct SourceCamera
{
    Vec3 origin;
    double pitch{};
    double yaw{};
    double roll{};
};

struct ViewTransform
{
    Vec3 origin;
    Vec3 forward;
    Vec3 screen_right;
    Vec3 up;
};

Camera preset_camera(std::string_view name);

int table_index(int value);

ViewTransform packed_view_transform(const SourceWorld& world, const Camera& camera);

ViewTransform source_view_transform(const SourceCamera& camera);

Ray view_ray(const ViewTransform& view, int x, int y);

struct ReferenceFrame
{
    std::vector<std::uint8_t> indices;
    std::vector<std::uint8_t> material_indices;
    std::vector<std::uint8_t> texture_indices;
    std::vector<double> texture_s;
    std::vector<double> texture_t;
    std::vector<std::uint8_t> lightmap_texture_indices;
    std::vector<std::uint8_t> lightmap_texture_levels;
    std::vector<std::uint8_t> untextured_lightmap_indices;
    std::vector<std::uint16_t> faces;
    std::vector<std::uint16_t> entities;
    std::vector<std::uint16_t> models;
    std::vector<double> depths;
    int hits{};
    int misses{};
    int unique_faces{};
    int visible_faces{};
};

bool face_is_visible(const SourceWorld& world, const Camera& camera, const Vec3& source_camera, std::size_t face);

ReferenceFrame render_reference_with_view(
    const SourceWorld& world,
    const Bvh& bvh,
    const ViewTransform& view,
    const Camera* packed_camera,
    bool flat,
    std::span<const std::uint8_t> allowed_faces,
    std::span<const int> painter_ranks
);

ReferenceFrame render_reference(
    const SourceWorld& world,
    const Bvh& bvh,
    const Camera& camera,
    bool flat,
    std::span<const std::uint8_t> allowed_faces = {},
    std::span<const int> painter_ranks = {}
);

std::size_t wrapped_texel(double coordinate, std::uint32_t dimension);

struct ExactTextureSample
{
    std::uint8_t index{};
    double distance{};
    double s{};
    double t{};
};

double projection_plane_distance(double ray_depth);

ExactTextureSample sample_exact_texture(const SourceWorld& world, std::uint16_t face, const Ray& ray);

std::uint8_t
sample_bsp_lightmap_level(const FaceLightmap& lightmap, std::span<const std::uint8_t> lighting, double s, double t);

std::uint8_t sample_bsp_lightmap_level(const SourceWorld& world, std::uint16_t face, double s, double t);

std::uint8_t
sample_packed_bsp_lightmap_level(const SourceWorld& world, std::uint16_t face, std::int16_t s_q4, std::int16_t t_q4);

std::uint8_t remap_texture_index(
    const SourceWorld& world,
    std::uint8_t texture_index,
    std::uint8_t colormap_level,
    std::uint8_t identity_level
);

void shade_exact_texture_frame(ReferenceFrame& frame, const SourceWorld& world, const ViewTransform& view);

std::vector<Camera> load_demo_track(const fs::path& path);

std::vector<std::uint16_t> load_demo_timing(const fs::path& path, std::size_t expected_samples);

std::vector<SourceCamera> load_precise_demo_track(const fs::path& path);

std::size_t demo_pose_at_tick(const std::vector<std::uint16_t>& ticks, std::uint16_t tick);

inline constexpr int kPlaybackControlsHeight = 152;
inline constexpr int kMinimumLiveClientWidth = 768;
inline constexpr double kNtscFramesPerSecond = 60.0988138974405;
inline constexpr double kStepDemoFramesPerSecond = 2.0;

enum class PlaybackSpeed {
    Realtime,
    Half,
    Quarter,
};

enum class PlaybackSchedule {
    NewestDue,
    OrderedTimed,
    OrderedRenderCompletion,
};

inline constexpr std::array<const char*, 3> kPlaybackSpeedLabels{
    "Realtime",
    "1/2 Realtime",
    "1/4 Realtime",
};

inline constexpr std::array<const char*, 2> kOrderedPaceLabels{
    "Timed",
    "Fast",
};

inline constexpr std::array<const char*, 2> kOrderedRateLabels{
    "2 Hz",
    "20 Hz",
};

constexpr double playback_speed_scale(PlaybackSpeed speed)
{
    switch (speed)
    {
    case PlaybackSpeed::Realtime:
        return 1.0;
    case PlaybackSpeed::Half:
        return 0.5;
    case PlaybackSpeed::Quarter:
        return 0.25;
    }
    return 1.0;
}

constexpr double playback_source_delta(double wall_seconds, PlaybackSpeed speed)
{
    return wall_seconds * playback_speed_scale(speed);
}

double constant_step_duration(std::size_t pose_count, double samples_per_second);

std::size_t constant_step_pose_at_time(std::size_t pose_count, double seconds, double samples_per_second);

std::vector<std::size_t> step_demo_pose_indices(std::size_t pose_count, std::size_t sample_rate);

struct OrderedDemoAdvance
{
    bool advanced{};
    bool wrapped{};
};

OrderedDemoAdvance advance_ordered_demo_pose(std::size_t pose_count, std::size_t& pose, std::size_t stride = 1);

bool consume_ordered_demo_deadline(double frame_seconds, bool frame_presented, double& elapsed_seconds);

enum class Lighting {
    None,
    LightMap,
};

inline constexpr std::array<const char*, 2> kLightingLabels{
    "None",
    "LightMap",
};

struct RenderMode
{
    bool textures{true};
    Lighting lighting{Lighting::LightMap};

    auto operator<=>(const RenderMode&) const = default;
};

bool is_supported_render_mode(RenderMode mode);

int render_mode_technique(RenderMode mode);

struct LiveWindowState
{
    std::vector<std::uint32_t> pixels;
    bool paused{};
    bool brushes_enabled{};
    bool entities_enabled{};
    bool external_bsp_models{};
    bool sound_enabled{};
    float sound_volume{0.7F};
    bool legacy_material{};
    PlaybackSpeed playback_speed{PlaybackSpeed::Realtime};
    RenderMode mode{};
};

int material_palette_index(int texture_family, int light_step);

std::uint8_t material_shade_index(int shade, int x, int y, bool flat);

void shade_material_frame(ReferenceFrame& frame, const SourceWorld& world, const Camera& camera, bool flat);

ReferenceFrame render_material_reference(
    const SourceWorld& world,
    const Bvh& bvh,
    const Camera& camera,
    bool flat,
    std::span<const std::uint8_t> allowed_faces = {},
    std::span<const int> painter_ranks = {}
);

ReferenceFrame render_source_reference(const SourceWorld& world, const Bvh& bvh, const Camera& camera, bool flat);

ReferenceFrame render_source_reference(const SourceWorld& world, const Bvh& bvh, const SourceCamera& camera, bool flat);

struct ViewVertex
{
    int right_q6{};
    int up_q6{};
    int depth_q6{};
};

struct ScreenPoint
{
    int x{};
    int y{};
};

struct ProjectedVertex
{
    ViewVertex view;
    ScreenPoint screen;
    int state{}; // 0=far, 1=projectable, 2=behind the near plane.
};

struct RasterStats
{
    std::uint64_t candidate_writes{};
    std::uint64_t plot_writes{};
    std::uint64_t span_calls{};
    std::uint64_t bounded_rows{};
    std::uint64_t edge_intersections{};
    std::uint64_t edge_advances{};
    int input_faces{};
    int fan_triangles{};
    int emitted_triangles{};
    int near_clipped_triangles{};
    int unique_samples{};
    int unwritten_samples{};
};

struct RasterResult
{
    ReferenceFrame frame;
    RasterStats stats;
};

struct RasterLayers
{
    RasterResult current_pipeline;
    RasterResult legacy_widened_fan;
    RasterResult convex_painter;
    RasterResult front_to_back_uncovered;
};

ViewVertex transform_packed_vertex(const SourceWorld& world, const PackedVertex& vertex, const Camera& camera);

ProjectedVertex project_packed_vertex(const SourceWorld& world, const PackedVertex& vertex, const Camera& camera);

struct EdgeWalker
{
    int x{};
    int dx{};
    int dy{};
    int error{};
    int step_x{1};

    EdgeWalker(int x0, int y0, int x1, int y1)
    :
    x(x0),
    dx(x1 - x0),
    dy(y1 - y0)
    {
        if (dx < 0)
        {
            dx = -dx;
            step_x = -1;
        }
    }

    void step()
    {
        error += dx;
        while (error - dy >= 0)
        {
            x = wrap_i16(x + step_x);
            error -= dy;
        }
    }
};

void raster_pixel(RasterResult& result, int x, int y, std::uint16_t face, bool uncovered_only);

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
);

int floor_divide(int numerator, int denominator);

int ceil_divide(int numerator, int denominator);

int frustum_distance(const ViewVertex& point, int plane);

void finalize_raster_result(
    RasterResult& result,
    const SourceWorld& world,
    const Camera& camera,
    bool flat,
    int visible_faces
);

RasterResult render_current_pipeline(
    const SourceWorld& world,
    const PacketSelection& packet,
    const Camera& camera,
    bool flat,
    int overlap,
    bool boundary_jumps
);

} // namespace quake_bsp_reference
