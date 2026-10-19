#pragma once

#include "geometry.hpp"
#include "brushes.hpp"
#include "textured_live.hpp"

namespace quake_bsp_reference {

enum class ParticleType { Gravity, Fire, Explode, Explode2 };
struct QuakeParticle
{
    Vec3 origin;
    Vec3 velocity;
    double ramp{};
    int die{};
    std::uint32_t id{};
    std::uint8_t color{};
    ParticleType type{};
};
struct ParticleFrame
{
    std::vector<QuakeParticle> particles;
    std::uint64_t emitted{};
    std::uint64_t dropped{};
    std::string state_hash;
};
struct ParticleReplay
{
    std::vector<ParticleFrame> frames;
    Json coverage;
    std::string replay_hash;
};

ParticleReplay simulate_particle_replay(const Json& document);
ParticleReplay load_particle_replay(
    const fs::path& path,
    std::span<const std::uint8_t> pak,
    const fs::path& camera,
    const BrushReplay& brushes,
    std::string_view map_entry
);
Json compose_particles(
    std::vector<std::uint8_t>& indices,
    std::span<const double> scene_depth,
    const ViewTransform& view,
    const ParticleReplay& replay,
    std::size_t pose,
    RenderMode mode
);
std::vector<double> particle_scene_depth(std::span<const std::int16_t> depth_q6);
bool run_particle_self_test();

} // namespace quake_bsp_reference
