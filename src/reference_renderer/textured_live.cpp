#include "textured_live.hpp"
#include "world.hpp"
#include "geometry.hpp"
#include "turbulence.hpp"

namespace quake_bsp_reference {

namespace {
int signed_multiply_shift_trunc(int value, int factor, int shift)
{
    return (value * factor) / (1 << shift);
}
} // namespace

namespace {
std::int16_t linear_interpolate_i16(std::int16_t first, std::int16_t second, int numerator, int denominator)
{
    if (denominator <= 0 || numerator < 0 || numerator > denominator)
    {
        fail("linear interpolation received an invalid segment");
    }
    const int delta = wrap_i16(static_cast<int>(second) - first);
    return wrap_i16(first + static_cast<int>(static_cast<std::int64_t>(delta) * numerator / denominator));
}
} // namespace

namespace {
int ratio_q12(int numerator, int denominator)
{
    if (denominator <= 0 || numerator < 0 || numerator > denominator)
    {
        fail("Q12 ratio received an invalid segment");
    }
    return static_cast<int>(static_cast<std::int64_t>(numerator) * 4096 / denominator);
}
} // namespace

namespace {
int perspective_factor_q12(int first_depth, int second_depth, int screen_factor_q12)
{
    if (first_depth <= 0 || second_depth <= 0 || screen_factor_q12 < 0 || screen_factor_q12 > 4096)
    {
        fail("perspective factor received an invalid segment");
    }
    const int numerator = signed_multiply_shift_trunc(first_depth, screen_factor_q12, 12);
    const int depth_delta = second_depth - first_depth;
    const int denominator = second_depth - signed_multiply_shift_trunc(depth_delta, screen_factor_q12, 12);
    if (denominator <= 0 || numerator < 0 || numerator > denominator)
    {
        fail("perspective factor escaped its positive depth segment");
    }
    return ratio_q12(numerator, denominator);
}
} // namespace

std::int16_t perspective_interpolate_i16(
    std::int16_t first,
    std::int16_t second,
    int first_depth,
    int second_depth,
    int numerator,
    int denominator
)
{
    const int factor = perspective_factor_q12(first_depth, second_depth, ratio_q12(numerator, denominator));
    return linear_interpolate_i16(first, second, factor, 4096);
}

namespace {
std::int16_t perspective_interpolate_depth(int first_depth, int second_depth, int numerator, int denominator)
{
    const int factor = perspective_factor_q12(first_depth, second_depth, ratio_q12(numerator, denominator));
    return linear_interpolate_i16(
        static_cast<std::int16_t>(first_depth),
        static_cast<std::int16_t>(second_depth),
        factor,
        4096
    );
}
} // namespace

namespace {
TexturedViewVertex
interpolate_textured_frustum_edge(const TexturedViewVertex& inside, const TexturedViewVertex& outside, int plane)
{
    int inside_distance = frustum_distance(inside.view, plane);
    int outside_distance = -frustum_distance(outside.view, plane);
    if (inside_distance < 0 || outside_distance <= 0)
    {
        fail("textured frustum endpoints violate the inside/outside contract");
    }
    while (inside_distance + outside_distance > 32767)
    {
        inside_distance >>= 1;
        outside_distance = std::max(1, outside_distance >> 1);
    }
    const int ratio_q12 = std::clamp((inside_distance << 12) / (inside_distance + outside_distance), 0, 4096);
    const bool inside_base = ratio_q12 < 2048;
    const int factor = inside_base ? ratio_q12 : 4096 - ratio_q12;
    const auto interpolate = [&](int inside_value, int outside_value) {
        const int base = inside_base ? inside_value : outside_value;
        const int other = inside_base ? outside_value : inside_value;
        const int delta = wrap_i16(other - base);
        return wrap_i16(base + signed_multiply_shift_trunc(delta, factor, 12));
    };
    return {
        {interpolate(inside.view.right_q6, outside.view.right_q6),
         interpolate(inside.view.up_q6, outside.view.up_q6),
         interpolate(inside.view.depth_q6, outside.view.depth_q6)},
        interpolate(inside.s_q4, outside.s_q4),
        interpolate(inside.t_q4, outside.t_q4),
    };
}
} // namespace

namespace {
std::vector<TexturedViewVertex> clip_textured_frustum(std::span<const TexturedViewVertex> polygon)
{
    std::vector<TexturedViewVertex> input(polygon.begin(), polygon.end());
    for (int plane = 0; plane < 4; ++plane)
    {
        if (input.empty())
        {
            break;
        }
        std::vector<TexturedViewVertex> output;
        output.reserve(input.size() + 1);
        auto previous = input.back();
        bool previous_inside = frustum_distance(previous.view, plane) >= 0;
        for (const auto& current : input)
        {
            const bool current_inside = frustum_distance(current.view, plane) >= 0;
            if (current_inside != previous_inside)
            {
                output.push_back(
                    current_inside ? interpolate_textured_frustum_edge(current, previous, plane)
                                   : interpolate_textured_frustum_edge(previous, current, plane)
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
int normalize_texture_q4(int value, int dimension)
{
    const int period = dimension * 16;
    if (period <= 0 || period > 32767)
    {
        fail("packed texture has an unsupported Q4 wrap period");
    }
    value = wrap_i16(value);
    while (value < 0)
    {
        value = wrap_i16(value + period);
    }
    while (value >= period)
    {
        value = wrap_i16(value - period);
    }
    return value;
}
} // namespace

namespace {
std::uint8_t sample_packed_texture(const MipTexture& texture, int s_q4, int t_q4)
{
    const auto s = static_cast<std::size_t>(s_q4 >> 4);
    const auto t = static_cast<std::size_t>(t_q4 >> 4);
    if (s >= texture.width || t >= texture.height)
    {
        fail("normalized packed texture coordinate escaped its miptex");
    }
    return texture.level_zero.at(t * texture.width + s);
}
} // namespace

namespace {
bool packed_texture_candidate_wins(PackedTextureRaster& result, std::size_t pixel, std::int16_t depth_q6)
{
    if (!result.current_depth_arbitration)
    {
        if (result.arbitration_groups.size() == kLogicalPixels)
        {
            result.arbitration_groups[pixel] = 0xffff;
        }
        return true;
    }
    result.candidate_samples.push_back(
        {result.current_arbitration_group, result.current_candidate_serial, static_cast<std::uint16_t>(pixel), depth_q6}
    );
    if (result.arbitration_groups.size() != kLogicalPixels || result.arbitration_depth_q6.size() != kLogicalPixels)
    {
        fail("packed same-key arbitration planes are missing");
    }
    if (result.arbitration_groups[pixel] != result.current_arbitration_group)
    {
        result.arbitration_groups[pixel] = result.current_arbitration_group;
        result.arbitration_depth_q6[pixel] = depth_q6;
        return true;
    }
    const auto current_depth = result.arbitration_depth_q6[pixel];
    bool wins = depth_q6 < current_depth;
    if (depth_q6 == current_depth)
    {
        wins = result.models[pixel] == 0 || result.current_entity < result.entities[pixel] ||
               (result.current_entity == result.entities[pixel] &&
                (result.current_model < result.models[pixel] ||
                 (result.current_model == result.models[pixel] && result.current_source_face < result.faces[pixel])));
    }
    if (wins)
    {
        result.arbitration_depth_q6[pixel] = depth_q6;
    }
    return wins;
}
} // namespace

void draw_packed_texture_span_affine(
    PackedTextureRaster& result,
    const SourceWorld& world,
    const MipTexture& texture,
    std::uint16_t face,
    int y,
    int first_x,
    int last_x,
    int left_x_q7,
    int right_x_q7,
    std::int16_t left_s_q4,
    std::int16_t left_t_q4,
    std::int16_t right_s_q4,
    std::int16_t right_t_q4,
    std::int16_t left_depth_q6,
    std::int16_t right_depth_q6
)
{
    ++result.stats.span_calls;
    result.spans.push_back(
        {face,
         result.current_depth_arbitration ? result.current_arbitration_group : std::uint16_t{0xffff},
         result.current_candidate_serial,
         y,
         first_x,
         last_x,
         left_s_q4,
         left_t_q4,
         right_s_q4,
         right_t_q4,
         left_x_q7,
         right_x_q7,
         left_depth_q6,
         right_depth_q6}
    );
    const int denominator = std::max(1, last_x - first_x);
    const int screen_denominator_q7 = right_x_q7 - left_x_q7;
    const auto sample_depth = [&](int x) {
        if (screen_denominator_q7 == 0)
        {
            return left_depth_q6;
        }
        const int sample_x_q7 = x * 128 + 64;
        const int screen_numerator_q7 = std::clamp(sample_x_q7 - left_x_q7, 0, screen_denominator_q7);
        return perspective_interpolate_depth(left_depth_q6, right_depth_q6, screen_numerator_q7, screen_denominator_q7);
    };
    const auto divide_delta = [&](std::int16_t left, std::int16_t right) {
        const auto delta = wrap_i16(static_cast<int>(right) - left);
        const int sign = delta < 0 ? -1 : 1;
        const auto unsigned_delta = static_cast<std::uint16_t>(delta);
        const auto magnitude = sign < 0 ? static_cast<std::uint16_t>(0U - unsigned_delta) : unsigned_delta;
        return std::array<int, 3>{
            sign,
            static_cast<int>(magnitude / denominator),
            static_cast<int>(magnitude % denominator)
        };
    };
    const auto s_division = divide_delta(left_s_q4, right_s_q4);
    const auto t_division = divide_delta(left_t_q4, right_t_q4);
    int s = normalize_texture_q4(left_s_q4, static_cast<int>(texture.width));
    int t = normalize_texture_q4(left_t_q4, static_cast<int>(texture.height));
    int absolute_s = left_s_q4;
    int absolute_t = left_t_q4;
    int s_error = 0;
    int t_error = 0;
    for (int x = first_x; x <= last_x; ++x)
    {
        ++result.stats.candidate_writes;
        ++result.stats.plot_writes;
        const auto pixel = logical_pixel_index(x, y);
        result.faces[pixel] = result.current_source_face == kMissFace ? face : result.current_source_face;
        result.entities[pixel] = result.current_entity;
        result.models[pixel] = result.current_model;
        result.s_q4[pixel] = static_cast<std::int16_t>(s);
        result.t_q4[pixel] = static_cast<std::int16_t>(t);
        result.absolute_s_q4[pixel] = static_cast<std::int16_t>(absolute_s);
        result.absolute_t_q4[pixel] = static_cast<std::int16_t>(absolute_t);
        result.depth_q6[pixel] = sample_depth(x);
        const auto texel =
            texture.turbulent
                ? sample_quake_turbulent_texture(
                      texture,
                      absolute_s,
                      absolute_t,
                      result.turbulence_phase,
                      world.turbulence_table
                  )
                : sample_packed_texture(texture, s, t);
        result.indices[pixel] = texel;
        const auto source_lightmap_level = sample_packed_bsp_lightmap_level(
            world,
            face,
            static_cast<std::int16_t>(absolute_s),
            static_cast<std::int16_t>(absolute_t)
        );
        const auto lightmap_level = exact_lightmap_colormap_level(source_lightmap_level);
        result.lightmap_levels[pixel] = lightmap_level;
        result.lightmapped_indices[pixel] = texture.turbulent ? texel : world.texture_colormap[lightmap_level][texel];
        result.turbulent_pixels[pixel] = static_cast<std::uint8_t>(texture.turbulent);
        result.untextured_lightmap_indices[pixel] = untextured_lightmap_index(source_lightmap_level);
        if (x == last_x)
        {
            break;
        }
        s = wrap_i16(s + s_division[0] * s_division[1]);
        absolute_s = wrap_i16(absolute_s + s_division[0] * s_division[1]);
        s_error += s_division[2];
        if (s_error >= denominator)
        {
            s_error -= denominator;
            s = wrap_i16(s + s_division[0]);
            absolute_s = wrap_i16(absolute_s + s_division[0]);
        }
        s = normalize_texture_q4(s, static_cast<int>(texture.width));

        t = wrap_i16(t + t_division[0] * t_division[1]);
        absolute_t = wrap_i16(absolute_t + t_division[0] * t_division[1]);
        t_error += t_division[2];
        if (t_error >= denominator)
        {
            t_error -= denominator;
            t = wrap_i16(t + t_division[0]);
            absolute_t = wrap_i16(absolute_t + t_division[0]);
        }
        t = normalize_texture_q4(t, static_cast<int>(texture.height));
    }
}

void draw_packed_texture_span_projective(
    PackedTextureRaster& result,
    const SourceWorld& world,
    const MipTexture& texture,
    std::uint16_t face,
    int y,
    int first_x,
    int last_x,
    int left_x_q7,
    int right_x_q7,
    std::int16_t left_s_q4,
    std::int16_t left_t_q4,
    std::int16_t right_s_q4,
    std::int16_t right_t_q4,
    std::int16_t left_depth_q6,
    std::int16_t right_depth_q6
)
{
    ++result.stats.span_calls;
    result.spans.push_back(
        {face,
         result.current_depth_arbitration ? result.current_arbitration_group : std::uint16_t{0xffff},
         result.current_candidate_serial,
         y,
         first_x,
         last_x,
         left_s_q4,
         left_t_q4,
         right_s_q4,
         right_t_q4,
         left_x_q7,
         right_x_q7,
         left_depth_q6,
         right_depth_q6}
    );
    const int screen_denominator_q7 = right_x_q7 - left_x_q7;
    if (screen_denominator_q7 < 0)
    {
        fail("projective span edges are not ordered");
    }
    const auto sample_attribute = [&](std::int16_t left, std::int16_t right, int x) {
        if (screen_denominator_q7 == 0)
        {
            return left;
        }
        const int sample_x_q7 = x * 128 + 64;
        const int screen_numerator_q7 = std::clamp(sample_x_q7 - left_x_q7, 0, screen_denominator_q7);
        return perspective_interpolate_i16(
            left,
            right,
            left_depth_q6,
            right_depth_q6,
            screen_numerator_q7,
            screen_denominator_q7
        );
    };
    for (int x = first_x; x <= last_x; ++x)
    {
        const int span_numerator = x - first_x;
        constexpr int perspective_block_pixels = 8;
        const int block_first_offset = (span_numerator / perspective_block_pixels) * perspective_block_pixels;
        const int block_last_offset = std::min(last_x - first_x, block_first_offset + perspective_block_pixels);
        const int block_first_x = first_x + block_first_offset;
        const int block_last_x = first_x + block_last_offset;
        const auto block_first_s = sample_attribute(left_s_q4, right_s_q4, block_first_x);
        const auto block_last_s = sample_attribute(left_s_q4, right_s_q4, block_last_x);
        const auto block_first_t = sample_attribute(left_t_q4, right_t_q4, block_first_x);
        const auto block_last_t = sample_attribute(left_t_q4, right_t_q4, block_last_x);
        const auto absolute_s_sample = linear_interpolate_i16(
            block_first_s,
            block_last_s,
            span_numerator - block_first_offset,
            std::max(1, block_last_offset - block_first_offset)
        );
        const auto absolute_t_sample = linear_interpolate_i16(
            block_first_t,
            block_last_t,
            span_numerator - block_first_offset,
            std::max(1, block_last_offset - block_first_offset)
        );
        const int s = normalize_texture_q4(absolute_s_sample, static_cast<int>(texture.width));
        const int t = normalize_texture_q4(absolute_t_sample, static_cast<int>(texture.height));
        const auto pixel = logical_pixel_index(x, y);
        ++result.stats.candidate_writes;
        const auto depth_sample = sample_attribute(left_depth_q6, right_depth_q6, x);
        if (!packed_texture_candidate_wins(result, pixel, depth_sample))
        {
            continue;
        }
        ++result.stats.plot_writes;
        result.faces[pixel] = result.current_source_face == kMissFace ? face : result.current_source_face;
        result.entities[pixel] = result.current_entity;
        result.models[pixel] = result.current_model;
        result.s_q4[pixel] = static_cast<std::int16_t>(s);
        result.t_q4[pixel] = static_cast<std::int16_t>(t);
        result.absolute_s_q4[pixel] = absolute_s_sample;
        result.absolute_t_q4[pixel] = absolute_t_sample;
        result.depth_q6[pixel] = depth_sample;
        const auto texel =
            texture.turbulent
                ? sample_quake_turbulent_texture(
                      texture,
                      absolute_s_sample,
                      absolute_t_sample,
                      result.turbulence_phase,
                      world.turbulence_table
                  )
                : sample_packed_texture(texture, s, t);
        result.indices[pixel] = texel;
        const auto source_lightmap_level =
            sample_packed_bsp_lightmap_level(world, face, absolute_s_sample, absolute_t_sample);
        const auto lightmap_level = exact_lightmap_colormap_level(source_lightmap_level);
        result.lightmap_levels[pixel] = lightmap_level;
        result.lightmapped_indices[pixel] = texture.turbulent ? texel : world.texture_colormap[lightmap_level][texel];
        result.turbulent_pixels[pixel] = static_cast<std::uint8_t>(texture.turbulent);
        result.untextured_lightmap_indices[pixel] = untextured_lightmap_index(source_lightmap_level);
        if (x == last_x)
        {
            break;
        }
    }
}

void raster_packed_texture_polygon(
    PackedTextureRaster& result,
    const SourceWorld& world,
    std::span<const TexturedViewVertex> view_polygon,
    const MipTexture& texture,
    std::uint16_t face,
    TextureRasterMode mode
)
{
    const auto clipped = clip_textured_frustum(view_polygon);
    if (clipped.size() < 3)
    {
        return;
    }
    std::vector<TexturedFixedPoint> polygon;
    polygon.reserve(clipped.size());
    for (const auto& point : clipped)
    {
        const int depth = std::max(1, point.view.depth_q6);
        const auto projected_delta = [&](int component) {
            const int magnitude = std::min(std::abs(component), depth);
            const int ratio_q11 = (magnitude << 11) / depth;
            const int delta_q7 = ratio_q11 * 6;
            return component < 0 ? -delta_q7 : delta_q7;
        };
        polygon.push_back(
            {8192 + projected_delta(point.view.right_q6),
             7168 - projected_delta(point.view.up_q6),
             point.s_q4,
             point.t_q4,
             static_cast<std::int16_t>(point.view.depth_q6)}
        );
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
    if (result.current_depth_arbitration)
    {
        const auto depth_sum =
            std::accumulate(clipped.begin(), clipped.end(), 0, [](int sum, const TexturedViewVertex& vertex) {
                return sum + vertex.view.depth_q6;
            });
        result.projected_fragments.push_back(
            {result.current_arbitration_group,
             result.current_candidate_serial,
             static_cast<std::uint8_t>(clipped.size()),
             static_cast<std::int16_t>(depth_sum / static_cast<int>(clipped.size())),
             result.current_entity,
             result.current_model,
             result.current_source_face}
        );
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
                fail("textured convex boundary is not Y-monotonic");
            }
            const int factor_q10 = ((sample_y_q7 - first.y_q7) << 10) / (second.y_q7 - first.y_q7);
            const auto interpolate_affine = [&](std::int16_t first_value, std::int16_t second_value) {
                const int delta = wrap_i16(static_cast<int>(second_value) - first_value);
                return wrap_i16(first_value + signed_multiply_shift_trunc(delta, factor_q10, 10));
            };
            ++result.stats.edge_intersections;
            return TexturedFixedPoint{
                wrap_i16(first.x_q7 + (((second.x_q7 - first.x_q7) * factor_q10) >> 10)),
                sample_y_q7,
                mode == TextureRasterMode::projective_block8
                    ? perspective_interpolate_i16(
                          first.s_q4,
                          second.s_q4,
                          first.depth_q6,
                          second.depth_q6,
                          factor_q10,
                          1024
                      )
                    : interpolate_affine(first.s_q4, second.s_q4),
                mode == TextureRasterMode::projective_block8
                    ? perspective_interpolate_i16(
                          first.t_q4,
                          second.t_q4,
                          first.depth_q6,
                          second.depth_q6,
                          factor_q10,
                          1024
                      )
                    : interpolate_affine(first.t_q4, second.t_q4),
                mode == TextureRasterMode::projective_block8
                    ? perspective_interpolate_depth(first.depth_q6, second.depth_q6, factor_q10, 1024)
                    : interpolate_affine(first.depth_q6, second.depth_q6),
            };
        }
        fail("textured convex boundary has no active edge");
    };

    for (int y = first_y; y <= last_y; ++y)
    {
        ++result.stats.bounded_rows;
        const int sample_y_q7 = y * 128 + 64;
        auto left = intersect_chain(forward, 1, sample_y_q7);
        auto right = intersect_chain(reverse, -1, sample_y_q7);
        if (right.x_q7 < left.x_q7)
        {
            std::swap(left, right);
        }
        const int first_x = std::max(0, ceil_divide(left.x_q7 - 68, 128));
        const int last_x = std::min(kLogicalWidth - 1, floor_divide(right.x_q7 - 60, 128));
        if (first_x <= last_x)
        {
            if (mode == TextureRasterMode::affine)
            {
                draw_packed_texture_span_affine(
                    result,
                    world,
                    texture,
                    face,
                    y,
                    first_x,
                    last_x,
                    left.x_q7,
                    right.x_q7,
                    left.s_q4,
                    left.t_q4,
                    right.s_q4,
                    right.t_q4,
                    left.depth_q6,
                    right.depth_q6
                );
                continue;
            }
            draw_packed_texture_span_projective(
                result,
                world,
                texture,
                face,
                y,
                first_x,
                last_x,
                left.x_q7,
                right.x_q7,
                left.s_q4,
                left.t_q4,
                right.s_q4,
                right.t_q4,
                left.depth_q6,
                right.depth_q6
            );
        }
    }
}

PackedTextureRaster render_packed_texture_pipeline(
    const SourceWorld& world,
    const PacketSelection& packet,
    const Camera& camera,
    TextureRasterMode mode,
    double surface_time
)
{
    if (world.face_vertex_ids.size() != static_cast<std::size_t>(world.face_count) ||
        world.face_texture_coordinates.size() != static_cast<std::size_t>(world.face_count) ||
        world.face_texture_ids.size() != static_cast<std::size_t>(world.face_count) || world.packed_textures.empty())
    {
        fail("packed texture render requires complete generated texture data");
    }
    PackedTextureRaster result;
    result.indices.assign(kLogicalPixels, kUnwrittenIndex);
    result.lightmapped_indices.assign(kLogicalPixels, kUnwrittenIndex);
    result.lightmap_levels.resize(kLogicalPixels);
    result.untextured_lightmap_indices.assign(kLogicalPixels, kUntexturedDiagnosticIndex);
    result.faces.resize(kLogicalPixels, kMissFace);
    result.entities.resize(kLogicalPixels);
    result.models.resize(kLogicalPixels);
    result.s_q4.resize(kLogicalPixels);
    result.t_q4.resize(kLogicalPixels);
    result.absolute_s_q4.resize(kLogicalPixels);
    result.absolute_t_q4.resize(kLogicalPixels);
    result.depth_q6.assign(kLogicalPixels, std::numeric_limits<std::int16_t>::max());
    result.turbulent_pixels.resize(kLogicalPixels);
    result.turbulence_phase = quake_turbulence_phase(surface_time);
    for (const auto face : packet.source_faces)
    {
        const auto& vertex_ids = world.face_vertex_ids.at(face);
        const auto& coordinates = world.face_texture_coordinates.at(face);
        if (vertex_ids.size() < 3 || vertex_ids.size() != coordinates.size())
        {
            fail("packed texture packet contains an invalid polygon");
        }
        const auto texture_id = world.face_texture_ids.at(face);
        if (texture_id == 0xff)
        {
            continue;
        }
        if (texture_id >= world.packed_textures.size())
        {
            fail("packed face texture ID escapes its directory");
        }
        std::vector<TexturedViewVertex> polygon;
        polygon.reserve(vertex_ids.size());
        for (std::size_t index = 0; index < vertex_ids.size(); ++index)
        {
            polygon.push_back(
                {transform_packed_vertex(world, world.packed_vertices.at(vertex_ids[index]), camera),
                 coordinates[index].s_q4,
                 coordinates[index].t_q4}
            );
        }
        ++result.stats.input_faces;
        raster_packed_texture_polygon(result, world, polygon, world.packed_textures[texture_id], face, mode);
    }
    std::set<std::uint16_t> unique_faces;
    for (const auto face : result.faces)
    {
        if (face == kMissFace)
        {
            ++result.misses;
        }
        else
        {
            ++result.hits;
            unique_faces.insert(face);
        }
    }
    result.unique_faces = static_cast<int>(unique_faces.size());
    result.stats.unique_samples = result.hits;
    result.stats.unwritten_samples = result.misses;
    return result;
}

namespace {
std::vector<ViewPoint> clip_convex_frustum(std::span<const ViewPoint> polygon)
{
    std::vector<ViewPoint> input(polygon.begin(), polygon.end());
    const std::array<std::array<double, 3>, 4> plane_coefficients = {
        std::array{1.0, 0.0, 1.0},
        std::array{-1.0, 0.0, 1.0},
        std::array{0.0, -1.0, 1.0},
        std::array{0.0, 1.0, 1.0},
    };
    for (const auto& coefficients : plane_coefficients)
    {
        const auto distance = [&](const ViewPoint& point) {
            return coefficients[0] * point.right + coefficients[1] * point.up + coefficients[2] * point.depth;
        };
        if (input.empty())
        {
            break;
        }
        std::vector<ViewPoint> output;
        output.reserve(input.size() + 1);
        auto previous = input.back();
        double previous_distance = distance(previous);
        bool previous_inside = previous_distance >= 0.0;
        for (const auto& current : input)
        {
            const double current_distance = distance(current);
            const bool current_inside = current_distance >= 0.0;
            if (current_inside != previous_inside)
            {
                const double ratio = previous_distance / (previous_distance - current_distance);
                output.push_back({
                    previous.right + (current.right - previous.right) * ratio,
                    previous.up + (current.up - previous.up) * ratio,
                    previous.depth + (current.depth - previous.depth) * ratio,
                });
            }
            if (current_inside)
            {
                output.push_back(current);
            }
            previous = current;
            previous_distance = current_distance;
            previous_inside = current_inside;
        }
        input = std::move(output);
    }
    return input;
}
} // namespace

namespace {
void raster_convex_polygon(
    RasterResult& result,
    std::span<const ViewPoint> view_polygon,
    std::uint16_t face,
    bool uncovered_only
)
{
    const auto clipped = clip_convex_frustum(view_polygon);
    if (clipped.size() < 3)
    {
        return;
    }
    struct Point
    {
        double x{};
        double y{};
    };
    std::vector<Point> polygon;
    polygon.reserve(clipped.size());
    for (const auto& vertex : clipped)
    {
        polygon.push_back({64.0 + vertex.right * 96.0 / vertex.depth, 56.0 - vertex.up * 96.0 / vertex.depth});
    }
    const auto [minimum_y, maximum_y] = std::ranges::minmax_element(polygon, {}, &Point::y);
    constexpr double kBoundaryEpsilon = 1e-9;
    const int first_y = std::max(0, static_cast<int>(std::ceil(minimum_y->y - 0.5 - kBoundaryEpsilon)));
    const int last_y =
        std::min(kLogicalHeight - 1, static_cast<int>(std::floor(maximum_y->y - 0.5 + kBoundaryEpsilon)));
    for (int y = first_y; y <= last_y; ++y)
    {
        const double sample_y = static_cast<double>(y) + 0.5;
        std::vector<double> intersections;
        intersections.reserve(polygon.size());
        for (std::size_t index = 0; index < polygon.size(); ++index)
        {
            const auto& first = polygon[index];
            const auto& second = polygon[(index + 1) % polygon.size()];
            if ((first.y <= sample_y && second.y > sample_y) || (second.y <= sample_y && first.y > sample_y))
            {
                const double ratio = (sample_y - first.y) / (second.y - first.y);
                intersections.push_back(first.x + (second.x - first.x) * ratio);
            }
        }
        if (intersections.size() < 2)
        {
            continue;
        }
        const auto [minimum_x, maximum_x] = std::ranges::minmax(intersections);
        int first_x = static_cast<int>(std::ceil(minimum_x - 0.5 - kBoundaryEpsilon));
        int last_x = static_cast<int>(std::floor(maximum_x - 0.5 + kBoundaryEpsilon));
        first_x = std::max(first_x, 0);
        last_x = std::min(last_x, kLogicalWidth - 1);
        if (first_x > last_x)
        {
            continue;
        }
        ++result.stats.span_calls;
        for (int x = first_x; x <= last_x; ++x)
        {
            raster_pixel(result, x, y, face, uncovered_only);
        }
    }
}
} // namespace

RasterResult render_convex_counterfactual(
    const SourceWorld& world,
    const PacketSelection& packet,
    const Camera& camera,
    bool flat,
    bool front_to_back
)
{
    RasterResult result;
    result.frame.faces.resize(kLogicalPixels, kMissFace);
    const auto render_face = [&](std::uint16_t face) {
        const auto& vertex_ids = world.face_vertex_ids.at(face);
        if (vertex_ids.size() < 3)
        {
            fail("convex counterfactual packet contains a non-polygon face");
        }
        ++result.stats.input_faces;
        result.stats.fan_triangles += static_cast<int>(vertex_ids.size()) - 2;
        std::vector<ViewPoint> polygon;
        polygon.reserve(vertex_ids.size());
        for (const auto vertex_id : vertex_ids)
        {
            const auto view = transform_packed_vertex(world, world.packed_vertices.at(vertex_id), camera);
            polygon.push_back(
                {static_cast<double>(view.right_q6) / 64.0,
                 static_cast<double>(view.up_q6) / 64.0,
                 static_cast<double>(view.depth_q6) / 64.0}
            );
        }
        raster_convex_polygon(result, polygon, face, front_to_back);
    };
    if (front_to_back)
    {
        for (auto face = packet.source_faces.rbegin(); face != packet.source_faces.rend(); ++face)
        {
            render_face(*face);
        }
    }
    else
    {
        for (const auto face : packet.source_faces)
        {
            render_face(face);
        }
    }
    finalize_raster_result(result, world, camera, flat, static_cast<int>(packet.source_faces.size()));
    return result;
}

const std::vector<std::uint8_t>& selected_render_indices(const ReferenceFrame& frame, RenderMode mode)
{
    if (mode.textures)
    {
        return mode.lighting == Lighting::None ? frame.texture_indices : frame.lightmap_texture_indices;
    }
    if (mode.lighting == Lighting::LightMap)
    {
        return frame.untextured_lightmap_indices;
    }
    fail("reference renderer supports only techniques 2, 4, and 7");
}

const std::vector<std::uint8_t>& selected_render_indices(const PackedTextureRaster& frame, RenderMode mode)
{
    if (mode.textures)
    {
        return mode.lighting == Lighting::None ? frame.indices : frame.lightmapped_indices;
    }
    if (mode.lighting == Lighting::LightMap)
    {
        return frame.untextured_lightmap_indices;
    }
    fail("reference renderer supports only techniques 2, 4, and 7");
}

std::string render_mode_name(RenderMode mode)
{
    const auto lighting = kLightingLabels.at(static_cast<std::size_t>(mode.lighting));
    return std::string(mode.textures ? "textures+" : "untextured+") + lighting;
}

int render_mode_technique(RenderMode mode)
{
    if (mode.textures && mode.lighting == Lighting::None)
    {
        return 2;
    }
    if (mode.lighting == Lighting::LightMap)
    {
        return mode.textures ? 4 : 7;
    }
    fail("reference renderer supports only techniques 2, 4, and 7");
}

bool is_supported_render_mode(RenderMode mode)
{
    return (mode.textures && mode.lighting == Lighting::None) || mode.lighting == Lighting::LightMap;
}

std::string packed_render_contract(RenderMode mode, bool brushes)
{
    switch (render_mode_technique(mode))
    {
    case 2:
        return brushes ? "packed-gsu-q4-projective-block8-enabled-brush-"
                         "albedo-v1"
                       : "packed-gsu-q4-projective-block8-albedo-v1";
    case 4:
        return brushes ? "packed-gsu-q4-projective-block8-enabled-brush-"
                         "lightmap-v1"
                       : "packed-gsu-q4-projective-block8-lightmap-v1";
    case 7:
        return brushes ? "packed-gsu-q4-projective-block8-enabled-brush-"
                         "untextured-lightmap-v1"
                       : "packed-gsu-q4-projective-block8-untextured-"
                         "lightmap-v1";
    default:
        fail("reference renderer supports only techniques 2, 4, and 7");
    }
}

std::vector<std::uint8_t> select_live_indices(const ReferenceFrame& frame, RenderMode mode, bool legacy_material)
{
    const auto& selected = legacy_material ? frame.material_indices : selected_render_indices(frame, mode);
    return {selected.begin(), selected.end()};
}

void update_live_pixels(LiveWindowState& state, std::span<const std::uint8_t> indices, const SourceWorld& world)
{
    state.pixels.resize(indices.size());
    for (std::size_t index = 0; index < indices.size(); ++index)
    {
        const auto color = state.legacy_material ? world.live_material_palette.at(indices[index])
                           : state.mode.textures  ? world.texture_palette.at(indices[index])
                                                 : world.untextured_palette.at(indices[index]);
        state.pixels[index] =
            (static_cast<std::uint32_t>(color.r) << 16U) | (static_cast<std::uint32_t>(color.g) << 8U) |
            static_cast<std::uint32_t>(color.b);
    }
}

void update_live_pixels(LiveWindowState& state, const ReferenceFrame& frame, const SourceWorld& world)
{
    const auto& indices = state.legacy_material ? frame.material_indices : selected_render_indices(frame, state.mode);
    update_live_pixels(state, indices, world);
}

} // namespace quake_bsp_reference
