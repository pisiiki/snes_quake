#pragma once

#include "geometry.hpp"
#include "brushes.hpp"
#include <optional>

namespace quake_bsp_reference {

// Immutable inputs produced from the original PAK. Never populate these from
// evolving emulator RAM or captured gameplay results.
struct GameplayAssets
{
    std::string map;
    Json manifest;
    std::map<std::string, std::int64_t> constants;
    std::map<std::string, std::vector<std::uint8_t>> payloads;
};

GameplayAssets load_gameplay_assets(const fs::path& manifest_path);
bool run_gameplay_self_test();
Camera gameplay_render_camera(const std::array<std::int16_t, 3>& eye_q4, int yaw, int pitch, int position_units);

struct GameplayInput
{
    std::uint16_t joypad{}; // Native JOY_* held mask; edges derived internally.
    std::int16_t mouse_dx{};
    std::int16_t mouse_dy{};
    std::uint8_t mouse_buttons{}; // SNES bits: $40 fire, $80 backward.
    bool mouse_connected{};
    bool cycle_weapon{}; // One relative switch in the two-weapon roster.

    bool operator==(const GameplayInput&) const = default;
};

// JSON input fields: joypad (u16), mouseDx/mouseDy (signed count),
// mouseButtons (u8), mouseConnected (bool), cycleWeapon (bool).
GameplayInput gameplay_input_from_json(const Json& value);
bool run_gameplay_self_test();

struct GameplayActorPose
{
    std::uint16_t slot{};
    std::uint16_t entity{};
    std::string model;
    bool visible{};
    std::uint16_t mdl_frame{};
    std::optional<unsigned> sprite_row;
    std::uint8_t yaw{};
    std::array<std::int16_t, 3> origin_q3{};        // body coordinates, hull-origin rebased
    std::array<std::int16_t, 3> render_origin_q2{}; // exact staged native pose
};

struct GameplayRenderSnapshot
{
    std::string map;
    std::uint16_t video_tick{};
    Camera native_camera;
    SourceCamera source_camera; // Reconstructed from native quantized camera.
    int camera_position_units{16};
    std::array<std::int16_t, 3> eye_q4{};
    std::vector<BrushEntityState> brushes;
    std::vector<GameplayActorPose> actors;
    std::uint16_t shell_mask{};
    std::uint16_t health_mask{}, nail_mask{};
    bool explobox_solid{};
    std::uint16_t brush_row{};
    std::array<std::uint16_t, 2> entrance_rows{}; // Independently frozen entrance-leaf poses.
    std::array<std::uint16_t, 32> exit_rows{};
    std::uint8_t switched_lights{};
    std::optional<std::array<std::uint16_t, 5>> intermission_stats;
    std::uint32_t exit_pose_word{};
    std::uint16_t weapon_frame{};                 // Production live descriptor ID (idle=1).
    bool quad_tint{}, suit_tint{};
    std::uint16_t pickup_bonus_ticks{};
    int eye_contents{-1};
    bool damage_tint{}, muzzle_tint{};
    std::array<std::string_view, 4> pickup_lines{};
    unsigned technique{4};
    unsigned render_scale{2}; // Active raster dimensions; parity planes retain stride 128.
    bool brushes_enabled{true}, entities_enabled{true};
    double surface_time{};
    std::uint64_t sky_phase_q24{};
    std::uint32_t turbulence_phase_q24{};
    std::uint32_t alias_phase_q32{};
};

struct GameplaySound
{
    std::string name;
    std::uint16_t entity;
    std::uint8_t channel, volume, attenuation;
    Vec3 origin;
};

class GameplaySession
{
  public:
    explicit GameplaySession(std::vector<GameplayAssets> maps, std::string initial_map = "start");
    void use_queued_input(bool enabled);
    bool always_run() const;
    void set_always_run(bool enabled);
    void set_live_sound(bool enabled);
    std::uint64_t sound_generation() const;
    std::vector<GameplaySound> take_sounds();
    void set_skill(std::uint8_t skill);
    void set_render_technique(unsigned technique);
    void set_initial_render_scale(unsigned scale);
    ~GameplaySession();
    GameplaySession(GameplaySession&&) noexcept;
    GameplaySession& operator=(GameplaySession&&) noexcept;
    GameplaySession(const GameplaySession&) = delete;
    GameplaySession& operator=(const GameplaySession&) = delete;

    void reset(std::string_view map, std::uint8_t skill = 1);
    // One immutable qualification fixture, immediately after reset only.
    void set_initial_pose(std::array<std::int16_t, 3> eye_q4, std::uint8_t yaw, std::int16_t pitch,
                          std::optional<std::int16_t> health_q6 = std::nullopt,
                          std::optional<std::array<unsigned, 2>> armor = std::nullopt, bool quad = false,
                          std::optional<unsigned> shells = std::nullopt);
    // Native NMI: publish completed walk, latch controls/menu/mouse/look.
    void video_tick(const GameplayInput& input);
    // Consume at most one outstanding video tick. Uses current latched input,
    // matching foreground catch-up; returns false when already caught up.
    bool service_tick();
    // Qualification-only continuation. Each call pauses at a semantic hook;
    // video_tick/state are safe while suspended. Normal service_tick stays
    // synchronous, and drains a continuation if one is already active.
    std::string begin_service();
    std::string resume_service();
    std::string service_phase() const;
    // Convenience for ordinary independent operation: one NMI and one service
    // per tick. The split API above permits native scheduling qualification.
    void step(const GameplayInput& input, unsigned ticks = 1);
    Json state() const;
    std::string_view centerprint() const;
    // Snapshot freezes mutable state; taking it consumes the new-shot view
    // override exactly once, independently from simulation tick frequency.
    GameplayRenderSnapshot render_snapshot(bool consume_weapon = true);
    // Immutable pose-to-asset lookup for render-only qualification fixtures.
    std::array<std::uint16_t, 2> entrance_render_rows(std::array<std::uint16_t, 2> poses) const;

  private:
    friend bool run_gameplay_self_test();
    class Impl;
    std::unique_ptr<Impl> impl_;
    class Continuation;
    std::unique_ptr<Continuation> continuation_;
};

} // namespace quake_bsp_reference
