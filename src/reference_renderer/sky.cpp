#include "sky.hpp"
#include "world.hpp"
#include "geometry.hpp"

namespace quake_bsp_reference {

// Independently authored implementation of the released WinQuake software-sky
// behavior. Behavioral references: id Software Quake commit
// bf4ac424ce754894ac8f1dae6a3981954bc9852d, WinQuake/r_sky.c,
// WinQuake/d_sky.c, WinQuake/d_edge.c, and WinQuake/d_local.h.

static_assert(kQuakeSkyProjectionScale == 378);
constexpr int kDerivedQuakeSkyRepeatSeconds = kQuakeSkySize * (kQuakeSkySpeed / 2) * (kQuakeSkySecondarySpeed / 2);
static_assert(kQuakeSkyRepeatSeconds == static_cast<float>(kDerivedQuakeSkyRepeatSeconds));

QuakeSkyClock quake_sky_clock(double surface_time)
{
    if (!std::isfinite(surface_time) || surface_time < 0.0 ||
        surface_time > static_cast<double>(std::numeric_limits<int>::max()))
    {
        fail("Quake sky surface time must be finite, nonnegative, and bounded");
    }
    // Quake keeps cl.time as a double, performs the periodic reduction in
    // double precision, and stores only the reduced skytime as a float.
    const auto cycles = static_cast<int>(surface_time / static_cast<double>(kQuakeSkyRepeatSeconds));
    const float wrapped =
        static_cast<float>(surface_time - static_cast<double>(cycles) * static_cast<double>(kQuakeSkyRepeatSeconds));
    const float phase = wrapped * static_cast<float>(kQuakeSkySpeed);
    return {surface_time, wrapped, phase, static_cast<int>(phase) & (kQuakeSkySize - 1)};
}

void require_quake_sky_texture(const MipTexture& texture)
{
    const auto expected =
        static_cast<std::size_t>(kQuakeSkySourceWidth) * static_cast<std::size_t>(kQuakeSkySourceHeight);
    if (!texture.present || texture.width != kQuakeSkySourceWidth || texture.height != kQuakeSkySourceHeight ||
        texture.level_zero.size() != expected)
    {
        fail("Quake sky miptex must contain one 256x128 level-zero image");
    }
}

namespace {
const MipTexture* quake_sky_texture_for_face(const SourceWorld& world, std::uint16_t face)
{
    if (world.face_sky_mask.size() != static_cast<std::size_t>(world.face_count))
    {
        fail("Quake sky presentation requires a complete face classification");
    }
    if (face >= world.face_sky_mask.size() || world.face_sky_mask[face] == 0)
    {
        return nullptr;
    }
    if (!world.packed_textures.empty())
    {
        if (world.face_texture_ids.size() != world.face_sky_mask.size())
        {
            fail("packed Quake sky presentation requires face texture IDs");
        }
        const auto texture_id = world.face_texture_ids[face];
        if (texture_id == 0xff || texture_id >= world.packed_textures.size())
        {
            fail("packed Quake sky face has no embedded texture");
        }
        const auto& texture = world.packed_textures[texture_id];
        require_quake_sky_texture(texture);
        return &texture;
    }
    if (face >= world.face_texture_infos.size())
    {
        fail("source Quake sky face has no texture information");
    }
    const auto texture_info = world.face_texture_infos[face];
    if (texture_info < 0 || static_cast<std::size_t>(texture_info) >= world.texture_infos.size())
    {
        fail("source Quake sky face has invalid texture information");
    }
    const auto texture_id = world.texture_infos[static_cast<std::size_t>(texture_info)].texture_id;
    if (texture_id < 0 || static_cast<std::size_t>(texture_id) >= world.textures.size())
    {
        fail("source Quake sky face has an invalid miptex ID");
    }
    const auto& texture = world.textures[static_cast<std::size_t>(texture_id)];
    if (!is_quake_sky_texture_name(texture.name))
    {
        fail("source Quake sky classification disagrees with its miptex name");
    }
    require_quake_sky_texture(texture);
    return &texture;
}
} // namespace

QuakeSkyTile make_quake_sky_tile(const MipTexture& texture, const QuakeSkyClock& clock)
{
    require_quake_sky_texture(texture);
    QuakeSkyTile tile;
    for (int y = 0; y < kQuakeSkySize; ++y)
    {
        const int foreground_y = (y + clock.composite_shift) & (kQuakeSkySize - 1);
        for (int x = 0; x < kQuakeSkySize; ++x)
        {
            const int foreground_x = (x + clock.composite_shift) & (kQuakeSkySize - 1);
            const auto foreground =
                texture.level_zero[row_major_index(foreground_x, foreground_y, kQuakeSkySourceWidth)];
            const auto background = texture.level_zero[row_major_index(kQuakeSkySize + x, y, kQuakeSkySourceWidth)];
            const auto row = row_major_index(0, y, kQuakeSkyRowBytes);
            tile.indices[row + static_cast<std::size_t>(x)] = foreground != 0 ? foreground : background;
            tile.indices[row + kQuakeSkySize + static_cast<std::size_t>(x)] = background;
        }
    }
    return tile;
}

std::array<std::int32_t, 2> quake_sky_uv_to_st(const ViewTransform& view, int u, int v, const QuakeSkyClock& clock)
{
    constexpr float screen_extent =
        static_cast<float>(kLogicalWidth >= kLogicalHeight ? kLogicalWidth : kLogicalHeight);
    const float wu = 8192.0F * static_cast<float>(u - (kLogicalWidth >> 1)) / screen_extent;
    const float wv = 8192.0F * static_cast<float>((kLogicalHeight >> 1) - v) / screen_extent;
    float end_x = 4096.0F * static_cast<float>(view.forward.x) + wu * static_cast<float>(view.screen_right.x) +
                  wv * static_cast<float>(view.up.x);
    float end_y = 4096.0F * static_cast<float>(view.forward.y) + wu * static_cast<float>(view.screen_right.y) +
                  wv * static_cast<float>(view.up.y);
    float end_z = 4096.0F * static_cast<float>(view.forward.z) + wu * static_cast<float>(view.screen_right.z) +
                  wv * static_cast<float>(view.up.z);
    end_z *= 3.0F;
    const float magnitude = std::sqrt(end_x * end_x + end_y * end_y + end_z * end_z);
    if (!std::isfinite(magnitude) || magnitude <= 0.0F)
    {
        fail("Quake sky view direction cannot be normalized");
    }
    const float inverse_magnitude = 1.0F / magnitude;
    end_x *= inverse_magnitude;
    end_y *= inverse_magnitude;
    const float s = (clock.projected_phase + static_cast<float>(kQuakeSkyProjectionScale) * end_x) * 65536.0F;
    const float t = (clock.projected_phase + static_cast<float>(kQuakeSkyProjectionScale) * end_y) * 65536.0F;
    if (!std::isfinite(s) || !std::isfinite(t) || s < static_cast<float>(std::numeric_limits<std::int32_t>::min()) ||
        s > static_cast<float>(std::numeric_limits<std::int32_t>::max()) ||
        t < static_cast<float>(std::numeric_limits<std::int32_t>::min()) ||
        t > static_cast<float>(std::numeric_limits<std::int32_t>::max()))
    {
        fail("Quake sky fixed-point projection overflowed");
    }
    return {static_cast<std::int32_t>(s), static_cast<std::int32_t>(t)};
}

int quake_sky_arithmetic_shift5(std::int32_t value)
{
    if (value >= 0)
    {
        return value / kQuakeSkySpanMaximum;
    }
    const auto magnitude = -static_cast<std::int64_t>(value);
    return -static_cast<int>((magnitude + kQuakeSkySpanMaximum - 1) / kQuakeSkySpanMaximum);
}

std::uint8_t quake_sky_sample(const QuakeSkyTile& tile, std::int32_t s, std::int32_t t)
{
    const auto s_bits = std::bit_cast<std::uint32_t>(s);
    const auto t_bits = std::bit_cast<std::uint32_t>(t);
    const auto offset = ((t_bits & kQuakeSkyFixedMask) >> 8U) + ((s_bits & kQuakeSkyFixedMask) >> 16U);
    return tile.indices.at(offset);
}

void draw_quake_sky_span(
    std::vector<std::uint8_t>& indices,
    const QuakeSkyTile& tile,
    const ViewTransform& view,
    const QuakeSkyClock& clock,
    int y,
    int first_x,
    int last_x
)
{
    if (indices.size() != kLogicalPixels || y < 0 || y >= kLogicalHeight || first_x < 0 || last_x >= kLogicalWidth ||
        first_x > last_x)
    {
        fail("Quake sky span escapes the logical framebuffer");
    }
    int u = first_x;
    int output_x = first_x;
    int remaining = last_x - first_x + 1;
    auto current = quake_sky_uv_to_st(view, u, y, clock);
    while (remaining > 0)
    {
        const int count = std::min(kQuakeSkySpanMaximum, remaining);
        remaining -= count;
        auto next = current;
        int s_step = 0;
        int t_step = 0;
        if (remaining > 0)
        {
            u += count;
            next = quake_sky_uv_to_st(view, u, y, clock);
            s_step = quake_sky_arithmetic_shift5(next[0] - current[0]);
            t_step = quake_sky_arithmetic_shift5(next[1] - current[1]);
        }
        else if (count > 1)
        {
            u += count - 1;
            next = quake_sky_uv_to_st(view, u, y, clock);
            s_step = (next[0] - current[0]) / (count - 1);
            t_step = (next[1] - current[1]) / (count - 1);
        }
        auto s = current[0];
        auto t = current[1];
        for (int pixel = 0; pixel < count; ++pixel)
        {
            indices[logical_pixel_index(output_x + pixel, y)] = quake_sky_sample(tile, s, t);
            s += s_step;
            t += t_step;
        }
        output_x += count;
        current = next;
    }
}

QuakeSkyPresentation render_quake_sky_presentation(
    std::span<const std::uint8_t> base_indices,
    std::span<const std::uint16_t> faces,
    std::span<const std::uint16_t> entities,
    const SourceWorld& world,
    const ViewTransform& view,
    double surface_time,
    std::string_view time_source
)
{
    if (base_indices.size() != kLogicalPixels || faces.size() != kLogicalPixels || entities.size() != kLogicalPixels)
    {
        fail("Quake sky presentation requires complete color/owner planes");
    }
    const auto clock = quake_sky_clock(surface_time);
    QuakeSkyPresentation result;
    result.indices.assign(base_indices.begin(), base_indices.end());
    std::map<const MipTexture*, QuakeSkyTile> tiles;
    std::set<std::uint16_t> sky_faces;
    Json sky_runs = Json::array();
    int sky_pixels = 0;
    int changed_sky_pixels = 0;
    int sky_spans = 0;
    for (int y = 0; y < kLogicalHeight; ++y)
    {
        int x = 0;
        while (x < kLogicalWidth)
        {
            const auto pixel = logical_pixel_index(x, y);
            const auto face = faces[pixel];
            const auto* texture = entities[pixel] == 0 ? quake_sky_texture_for_face(world, face) : nullptr;
            if (texture == nullptr)
            {
                ++x;
                continue;
            }
            const int first_x = x;
            while (++x < kLogicalWidth)
            {
                const auto next = logical_pixel_index(x, y);
                if (entities[next] != 0 || faces[next] != face)
                {
                    break;
                }
            }
            auto [position, inserted] = tiles.try_emplace(texture);
            if (inserted)
            {
                position->second = make_quake_sky_tile(*texture, clock);
            }
            draw_quake_sky_span(result.indices, position->second, view, clock, y, first_x, x - 1);
            for (int changed_x = first_x; changed_x < x; ++changed_x)
            {
                const auto changed_pixel = logical_pixel_index(changed_x, y);
                changed_sky_pixels += result.indices[changed_pixel] != base_indices[changed_pixel];
            }
            sky_runs.push_back(Json{{"face", face}, {"y", y}, {"firstX", first_x}, {"lastX", x - 1}});
            sky_faces.insert(face);
            sky_pixels += x - first_x;
            ++sky_spans;
        }
    }
    Json face_records = Json::array();
    for (const auto face : sky_faces)
    {
        face_records.push_back(face);
    }
    result.inspection = Json{
        {"schema", "quake-reference-surface-inspection-v1"},
        {"available", true},
        {"contract", "winquake-software-sky-v1"},
        {"sourceCommit", "bf4ac424ce754894ac8f1dae6a3981954bc9852d"},
        {"timeSource", time_source},
        {"surfaceTime", surface_time},
        {"wrappedTime", clock.wrapped_time},
        {"projectedPhase", clock.projected_phase},
        {"compositeShift", clock.composite_shift},
        {"backgroundTexelsPerSecond", kQuakeSkySpeed},
        {"foregroundTexelsPerSecond", kQuakeSkySpeed * 2},
        {"repeatSeconds", kQuakeSkyRepeatSeconds},
        {"skyPixels", sky_pixels},
        {"changedSkyPixels", changed_sky_pixels},
        {"skySpans", sky_spans},
        {"skyFaces", std::move(face_records)},
        {"skyRuns", std::move(sky_runs)}
    };
    return result;
}

} // namespace quake_bsp_reference
