#include "particles.hpp"

namespace quake_bsp_reference {
namespace {
Json fixture()
{
    return Json{
        {"schema", "quake-particle-replay-v1"},
        {"version", 1},
        {"rate", 30},
        {"rows", 80},
        {"seed", 123},
        {"capacity", 2048},
        {"events",
         Json::array(
             {Json{
                  {"row", 0},
                  {"kind", "burst"},
                  {"count", 100},
                  {"color", 73},
                  {"origin", {64, 0, 0}},
                  {"direction", {0, 0, 1}}
              },
              Json{{"row", 1}, {"kind", "grenade"}, {"origin", {64, 0, 0}}, {"end", {73, 0, 0}}}}
         )}
    };
}
} // namespace

bool run_particle_self_test()
{
    const auto source = fixture();
    const auto replay = simulate_particle_replay(source);
    const auto repeated = simulate_particle_replay(source);
    bool okay = replay.frames.at(0).particles.size() == 100 && replay.frames.at(79).particles.empty();
    for (std::size_t row = 0; row < replay.frames.size(); ++row)
        okay = okay && replay.frames.at(row).state_hash == repeated.frames.at(row).state_hash;
    // Random access, pause, loops and presentation schedules are pure reads of immutable source rows.
    for (const auto row : {30U, 0U, 30U, 1U, 79U, 0U})
        okay = okay && replay.frames.at(row).state_hash == repeated.frames.at(row).state_hash;
    const auto& p0 = *std::ranges::find_if(replay.frames.at(0).particles, [](const auto& p) { return p.die > 0; });
    const auto found =
        std::ranges::find_if(replay.frames.at(1).particles, [&](const auto& p) { return p.id == p0.id; });
    if (p0.die > 0)
        okay = okay && found != replay.frames.at(1).particles.end() &&
               std::abs(found->velocity.z - (p0.velocity.z - 40.0 / 30.0)) < 1e-10;
    auto limited = source;
    limited["capacity"] = 1;
    const auto exhausted = simulate_particle_replay(limited);
    okay = okay && exhausted.frames.front().particles.size() == 1 && exhausted.frames.front().dropped == 99;
    const auto fire =
        std::ranges::find_if(replay.frames.at(2).particles, [](const auto& p) { return p.type == ParticleType::Fire; });
    okay = okay && fire != replay.frames.at(2).particles.end() && fire->ramp > 2 && fire->velocity.z > 0;
    for (const auto& birth : replay.frames.front().particles)
    {
        const auto& alive = replay.frames.at(static_cast<std::size_t>(birth.die)).particles;
        const auto& expired = replay.frames.at(static_cast<std::size_t>(birth.die + 1)).particles;
        okay = okay && std::ranges::any_of(alive, [&](const auto& p) { return p.id == birth.id; }) &&
               std::ranges::none_of(expired, [&](const auto& p) { return p.id == birth.id; });
    }
    auto preroll = source;
    preroll["events"] = Json::array({source["events"][0]});
    preroll["events"][0]["row"] = -30;
    okay = okay && simulate_particle_replay(preroll).frames.front().particles.empty();
    auto bad = source;
    bad["events"][1]["end"] = {165, 0, 0};
    bool rejected = false;
    try
    {
        static_cast<void>(simulate_particle_replay(bad));
    }
    catch (const std::exception&)
    {
        rejected = true;
    }
    okay = okay && rejected;

    ParticleReplay scene;
    ParticleFrame frame;
    frame.particles.push_back(QuakeParticle{{64, 0, 0}, {}, 0, 60, 1, 73, ParticleType::Gravity});
    frame.state_hash = "fixture";
    scene.frames.push_back(frame);
    const ViewTransform view{{}, {1, 0, 0}, {0, 1, 0}, {0, 0, 1}};
    for (const auto scale : {RenderScale::X2, RenderScale::X3})
    {
        const RenderViewportScope scope(scale);
        const auto pixel = logical_pixel_index(render_center_x(), render_center_y());
        std::vector<std::uint8_t> indices(kLogicalPixels, 12);
        std::vector<double> depths(kLogicalPixels, 64); // opaque actor pixels, including equal-depth ties
        const auto hidden = compose_particles(indices, depths, view, scene, 0, {true, Lighting::LightMap});
        okay = okay && hidden.at("drawn") == 0 && indices.at(pixel) == 12;
        depths.at(pixel) = std::numeric_limits<double>::infinity(); // transparent actor hole
        const auto hole = compose_particles(indices, depths, view, scene, 0, {true, Lighting::LightMap});
        okay = okay && hole.at("drawn") == 1 && indices.at(pixel) == 73;
        std::ranges::fill(depths, std::numeric_limits<double>::infinity());
        const auto visible = compose_particles(indices, depths, view, scene, 0, {true, Lighting::LightMap});
        okay = okay && visible.at("drawn") == (scale == RenderScale::X2 ? 4 : 1);
        const auto unlit = compose_particles(indices, depths, view, scene, 0, {false, Lighting::LightMap});
        okay = okay && unlit.at("drawn") != 0 && indices.at(pixel) == kUntexturedBrightIndex;
        auto clipped = scene;
        clipped.frames[0].particles[0].origin = {7, 0, 0};
        const auto near_clip = compose_particles(indices, depths, view, clipped, 0, {true, Lighting::LightMap});
        okay = okay && near_clip.at("clipped") == 1 && near_clip.at("drawn") == 0;
    }
    return okay;
}
} // namespace quake_bsp_reference
