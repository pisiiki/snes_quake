#include "particles.hpp"
#include <bit>

namespace quake_bsp_reference {
namespace {
constexpr std::array<std::uint8_t, 6> fire_ramp{109, 107, 6, 5, 4, 3};
constexpr std::array<std::uint8_t, 8> explode_ramp{111, 109, 107, 105, 103, 101, 99, 97};
constexpr std::array<std::uint8_t, 8> explode2_ramp{111, 110, 109, 108, 107, 106, 104, 102};
constexpr double step = 1.0 / 30.0;

std::string hash_bytes(std::span<const std::uint8_t> bytes)
{
    std::ostringstream stream;
    stream << std::hex << std::setfill('0') << std::setw(16) << brush_fnv1a64(bytes);
    return stream.str();
}

std::string state_hash(const ParticleFrame& frame)
{
    std::vector<std::uint8_t> bytes;
    const auto append = [&](std::uint64_t value) {
        for (unsigned shift = 0; shift < 64; shift += 8)
            bytes.push_back(static_cast<std::uint8_t>(value >> shift));
    };
    append(frame.emitted);
    append(frame.dropped);
    for (const auto& p : frame.particles)
    {
        append(p.id);
        append(static_cast<std::uint64_t>(p.type));
        append(p.color);
        append(static_cast<std::uint64_t>(p.die));
        append(std::bit_cast<std::uint64_t>(p.ramp));
        for (int axis = 0; axis < 3; ++axis)
        {
            append(std::bit_cast<std::uint64_t>(p.origin[axis]));
            append(std::bit_cast<std::uint64_t>(p.velocity[axis]));
        }
    }
    return hash_bytes(bytes);
}

Vec3 vector_value(const Json& value)
{
    if (!value.is_array() || value.size() != 3)
        fail("QPR1 vector must have three components");
    Vec3 result{value.at(0).get<double>(), value.at(1).get<double>(), value.at(2).get<double>()};
    for (int axis = 0; axis < 3; ++axis)
        if (!std::isfinite(result[axis]) || std::abs(result[axis]) > 16384.0)
            fail("QPR1 coordinate is non-finite or out of range");
    return result;
}

class Simulator
{
  public:
    explicit Simulator(const Json& document)
    :
    random_(document.at("seed").get<std::uint32_t>()),
    capacity_(document.at("capacity").get<std::size_t>())
    {
        if (random_ == 0 || capacity_ == 0 || capacity_ > 2048)
            fail("QPR1 invalid seed or capacity");
    }
    ParticleFrame frame;

    void emit(const Json& event, int row)
    {
        const auto kind = event.at("kind").get<std::string>();
        auto origin = vector_value(event.at("origin"));
        Vec3 direction{};
        int count = 0;
        int color = 0;
        Vec3 advance{};
        const bool burst = kind == "burst";
        const bool explosion = kind == "explosion";
        const bool blood = kind == "gib" || kind == "zomgib";
        if (burst || explosion)
        {
            count = event.at("count").get<int>();
            color = event.at("color").get<int>();
            direction = vector_value(event.at("direction"));
            if (count < 0 || count > 1024 || color < 0 || color > 255)
                fail("QPR1 invalid burst count or color");
            for (int axis = 0; axis < 3; ++axis)
                if (direction[axis] < -8 || direction[axis] > 7.9375)
                    fail("QPR1 direction outside signed wire range");
        }
        else
        {
            if (!blood && kind != "grenade" && kind != "rocket")
                fail("QPR1 unknown emitter");
            const auto delta = vector_value(event.at("end")) - origin;
            for (int axis = 0; axis < 3; ++axis)
                if (std::abs(delta[axis]) > 100)
                    fail("QPR1 trail crossed a discontinuity");
            const auto length = std::sqrt(length_squared(delta));
            if (length == 0)
                return;
            advance = delta * (1.0 / length);
            count = static_cast<int>(std::ceil(length / (kind == "zomgib" ? 6.0 : 3.0)));
        }
        for (int index = 0; index < count; ++index)
        {
            QuakeParticle p;
            p.id = static_cast<std::uint32_t>(++frame.emitted);
            p.origin = origin;
            p.type = ParticleType::Gravity;
            if (burst)
            {
                p.die = row + static_cast<int>(random() % 5U) * 3;
                p.color = static_cast<std::uint8_t>((color & ~7) + static_cast<int>(random() & 7U));
                p.origin = p.origin + jitter(16, 8);
                p.velocity = direction * 15.0;
            }
            else if (explosion)
            {
                p.die = row + 150;
                p.ramp = static_cast<double>(random() & 3U);
                p.color = explode_ramp[0];
                p.type = (index & 1) != 0 ? ParticleType::Explode : ParticleType::Explode2;
                p.origin = p.origin + jitter(32, 16);
                p.velocity = jitter(512, 256);
            }
            else if (blood)
            {
                p.die = row + 60;
                p.color = static_cast<std::uint8_t>(67U + (random() & 3U));
                p.origin = p.origin + jitter(6, 3);
            }
            else
            {
                p.die = row + 60;
                p.type = ParticleType::Fire;
                p.ramp = static_cast<double>((random() & 3U) + (kind == "grenade" ? 2U : 0U));
                p.color = fire_ramp.at(static_cast<std::size_t>(p.ramp));
                p.origin = p.origin + jitter(6, 3);
            }
            // Advance the PRNG even on exhaustion, so later events retain their identity.
            if (frame.particles.size() < capacity_)
                frame.particles.push_back(p);
            else
                ++frame.dropped;
            origin = origin + advance;
        }
    }

    void update(int row)
    {
        for (auto& p : frame.particles)
        {
            p.origin = p.origin + p.velocity * step;
            if (p.type == ParticleType::Fire)
            {
                p.ramp += 5.0 * step;
                if (p.ramp >= 6.0)
                    p.die = row;
                else
                    p.color = fire_ramp.at(static_cast<std::size_t>(p.ramp));
                p.velocity.z += 40.0 * step;
            }
            else
            {
                if (p.type == ParticleType::Explode || p.type == ParticleType::Explode2)
                {
                    const bool first = p.type == ParticleType::Explode;
                    p.ramp += (first ? 10.0 : 15.0) * step;
                    if (p.ramp >= 8.0)
                        p.die = row;
                    else
                        p.color = (first ? explode_ramp : explode2_ramp).at(static_cast<std::size_t>(p.ramp));
                    p.velocity = p.velocity * (first ? 1.0 + 4.0 * step : 1.0 - step);
                }
                p.velocity.z -= 40.0 * step;
            }
        }
        std::erase_if(frame.particles, [row](const auto& p) { return p.die < row + 1; });
    }

  private:
    std::uint32_t random_;
    std::size_t capacity_;
    std::uint32_t random()
    {
        random_ ^= random_ << 13U;
        random_ ^= random_ >> 17U;
        random_ ^= random_ << 5U;
        return random_;
    }
    Vec3 jitter(std::uint32_t range, int bias)
    {
        const auto value = [&]() { return static_cast<double>(static_cast<int>(random() % range) - bias); };
        return {value(), value(), value()};
    }
};
} // namespace

ParticleReplay simulate_particle_replay(const Json& document)
{
    if (document.at("schema") != "quake-particle-replay-v1" || document.at("version") != 1 || document.at("rate") != 30)
        fail("unsupported QPR1 schema, version or clock");
    const auto rows = document.at("rows").get<int>();
    const auto& events = document.at("events");
    if (rows <= 0 || rows > 100000 || !events.is_array() || events.size() > 1000000)
        fail("QPR1 invalid row/event count");
    int previous = -100000;
    for (const auto& event : events)
    {
        const int row = event.at("row").get<int>();
        if (row < previous || row >= rows)
            fail("QPR1 events not ordered within camera rows");
        previous = row;
    }
    Simulator simulator(document);
    ParticleReplay result;
    result.coverage = document.value("coverage", Json::object());
    result.coverage["unsupported"] = document.value("unsupported", Json::object());
    result.coverage["trail_resets"] = document.value("trail_resets", Json::object());
    std::size_t cursor = 0;
    std::size_t stored = 0;
    const int first = events.empty() ? 0 : std::min(0, events.front().at("row").get<int>());
    for (int row = first; row < rows; ++row)
    {
        while (cursor < events.size() && events.at(cursor).at("row").get<int>() == row)
            simulator.emit(events.at(cursor++), row);
        if (row >= 0)
        {
            stored += simulator.frame.particles.size();
            if (stored > 8000000)
                fail("QPR1 snapshot storage budget exceeded");
            simulator.frame.state_hash = state_hash(simulator.frame);
            result.frames.push_back(simulator.frame);
        }
        simulator.update(row);
    }
    return result;
}

ParticleReplay load_particle_replay(
    const fs::path& path,
    std::span<const std::uint8_t> pak,
    const fs::path& camera,
    const BrushReplay& brushes,
    std::string_view map_entry
)
{
    const auto bytes = read_file(path);
    if (bytes.size() > 32U * 1024U * 1024U)
        fail("QPR1 file exceeds 32 MiB");
    const auto document = Json::parse(bytes.begin(), bytes.end());
    if (document.at("camera_fnv1a64") != hash_bytes(read_file(camera)) || document.at("rows") != brushes.row_count() ||
        document.at("rate") != brushes.sample_rate ||
        std::abs(document.at("first_server_time").get<double>() - brushes.first_server_time) > 0.000001 ||
        document.at("source").at("map_entry").get<std::string>() != map_entry)
        fail("QPR1 camera/map/clock binding mismatch");
    const auto& source = document.at("source");
    const auto demo =
        source.value("demo_source", "pak") == "file"
            ? read_file(fs::path(source.at("demo_locator").get<std::string>()))
            : extract_pak_entry(pak, source.at("demo_entry").get<std::string>());
    if (source.at("demo_fnv1a64") != hash_bytes(demo))
        fail("QPR1 demo binding mismatch");
    for (const auto& model : source.at("models"))
        if (model.at("fnv1a64") != hash_bytes(extract_pak_entry(pak, model.at("entry").get<std::string>())))
            fail("QPR1 model binding mismatch");
    auto result = simulate_particle_replay(document);
    result.replay_hash = hash_bytes(bytes);
    return result;
}

std::vector<double> particle_scene_depth(std::span<const std::int16_t> depth_q6)
{
    std::vector<double> result;
    result.reserve(depth_q6.size());
    for (const auto depth : depth_q6)
        result.push_back(
            depth == std::numeric_limits<std::int16_t>::max()
                ? std::numeric_limits<double>::infinity()
                : depth * (kWorldScale / 64.0)
        );
    return result;
}

Json compose_particles(
    std::vector<std::uint8_t>& indices,
    std::span<const double> scene_depth,
    const ViewTransform& view,
    const ParticleReplay& replay,
    std::size_t pose,
    RenderMode mode
)
{
    if (indices.size() != kLogicalPixels || scene_depth.size() != kLogicalPixels)
        fail("particles require complete scene color and depth planes");
    const auto& frame = replay.frames.at(pose);
    std::vector<double> depth(scene_depth.begin(), scene_depth.end());
    std::size_t projected = 0, occluded = 0, drawn = 0, clipped = 0;
    std::map<int, std::size_t> colors;
    for (const auto& p : frame.particles)
    {
        const auto delta = p.origin - view.origin;
        const double z = dot(delta, view.forward);
        if (!std::isfinite(z) || z < 8.0)
        {
            ++clipped;
            continue;
        }
        const double u = render_center_x() + dot(delta, view.screen_right) * render_focal_length() / z;
        const double v = render_center_y() - dot(delta, view.up) * render_focal_length() / z;
        const int maximum = std::max(1, static_cast<int>(render_width() / 80.0 + 0.5));
        const int size = std::clamp(static_cast<int>(32768.0 / z) >> 8, 1, maximum);
        if (!std::isfinite(u) || !std::isfinite(v) || u < -size || v < -size || u >= render_width() ||
            v >= render_height())
        {
            ++clipped;
            continue;
        }
        const int left = static_cast<int>(std::floor(u + 0.5));
        const int top = static_cast<int>(std::floor(v + 0.5));
        for (int y = std::max(0, top); y < std::min(render_height(), top + size); ++y)
            for (int x = std::max(0, left); x < std::min(render_width(), left + size); ++x)
            {
                ++projected;
                const auto pixel = logical_pixel_index(x, y);
                // Opaque geometry and actors own ties. Earlier particle IDs own particle ties.
                if (z >= depth[pixel])
                {
                    ++occluded;
                    continue;
                }
                depth[pixel] = z;
                indices[pixel] = mode.textures ? p.color : kUntexturedBrightIndex;
                ++drawn;
                ++colors[p.color];
            }
    }
    Json color_counts = Json::object();
    for (const auto& [color, count] : colors)
        color_counts[std::to_string(color)] = count;
    return Json{
        {"schema", "quake-particle-inspection-v1"},
        {"sourcePose", pose},
        {"active", frame.particles.size()},
        {"emitted", frame.emitted},
        {"dropped", frame.dropped},
        {"projected", projected},
        {"occluded", occluded},
        {"drawn", drawn},
        {"clipped", clipped},
        {"stateHash", frame.state_hash},
        {"indexHash", hash_bytes(indices)},
        {"replayHash", replay.replay_hash},
        {"drawnColors", color_counts},
        {"coverage", replay.coverage},
        {"logicalWidth", render_width()},
        {"logicalHeight", render_height()},
        {"clock", "fixed-30Hz-source-row"}
    };
}
} // namespace quake_bsp_reference
