#pragma once
#include "gameplay.hpp"
#include <deque>
#include <condition_variable>
#include <mutex>
#include <thread>

namespace quake_bsp_reference {

using GameWord = std::uint16_t;
using GamePoint = std::array<std::int16_t, 3>;
inline GameWord gw(std::int64_t v)
{
    return static_cast<GameWord>(v);
}
inline std::int16_t gs(std::int64_t v)
{
    return std::bit_cast<std::int16_t>(gw(v));
}
inline std::int32_t game_asr(std::int64_t v, unsigned shift)
{
    const auto denominator = std::int64_t{1} << shift;
    return static_cast<std::int32_t>(v >= 0 ? v / denominator : -((-v + denominator - 1) / denominator));
}
inline GameWord game_u16(std::span<const std::uint8_t> b, std::size_t p)
{
    if (p + 2 > b.size())
        throw std::runtime_error("gameplay binary word outside input");
    return static_cast<GameWord>(b[p] | (b[p + 1] << 8));
}
inline std::int16_t game_s16(std::span<const std::uint8_t> b, std::size_t p)
{
    return gs(game_u16(b, p));
}
inline std::int32_t game_s32(std::span<const std::uint8_t> b, std::size_t p)
{
    return std::bit_cast<std::int32_t>(std::uint32_t(game_u16(b, p)) | (std::uint32_t(game_u16(b, p + 2)) << 16));
}
inline GameWord game_fraction(std::uint32_t numerator, std::uint32_t denominator)
{
    if (numerator >= denominator)
        return 4096;
    return gw((std::uint64_t(numerator) << 12) / denominator);
}
inline GameWord game_q6_mul(GameWord a, GameWord b)
{
    // QCMulRound takes 16-bit magnitudes, then calls the signed wide
    // multiplier. Preserve its $8000 absolute-value case and low-word wrap.
    const auto product = std::int64_t(gs(std::abs(int(gs(a))))) * gs(std::abs(int(gs(b))));
    const auto rounded = static_cast<std::uint32_t>(product) + 32U;
    const auto magnitude = gw(rounded >> 6U);
    return (a ^ b) & 0x8000 ? gw(-int(magnitude)) : magnitude;
}

struct GameplayTrace
{
    GamePoint result{};
    GamePoint normal{};
    GameWord fraction{4096};
    GameWord plane{0xffff};
    GameWord terminal{0xffff};
    bool hit{};
    bool start_solid{};
};

enum class LandingCue { none, normal, hard, water };

struct GameplayWalk
{
    GamePoint from{}, pending_xyz{}, support_xyz{};
    std::array<std::int16_t, 2> velocity_xy{};
    std::int16_t velocity_z{};
    int water_jump_ticks{};
    std::array<std::int16_t, 2> water_jump_move{};
    LandingCue landing{};
    GameWord ticks{}, grounded{}, impacts{}, slides{}, stairs{}, trace_fault{}, startsolid{}, jump_held{};
    GameWord failed_step_plane{}, failed_step_tick{}, support_pose{}, button_contact{};
    bool pending{}, support_valid{}, jump_consumed{};
};

struct GameplayHubTrigger
{
    GamePoint lower{}, upper{}, destination{};
    GameWord value{};
    GameWord yaw_start{}, yaw_span{256};
    std::string target;
};
using GameplaySwimZone = std::array<std::array<int, 2>, 7>;

struct GameplayControls
{
    GameWord buttons{};
    int yaw_delta{}, pitch_delta{};
    bool menu{}, release{};
    bool cycle_weapon{};
    bool walk_speed{};
    bool operator==(const GameplayControls&) const = default;
};

struct GameplayInputClock
{
    bool sample_pending{}, respawn_release{};
    GameWord tick{}, waits{}, divider{}, actions{};
    int yaw_delta{}, pitch_delta{};
    bool cycle_weapon{};
    std::size_t used_queue_cells{};
    GameplayControls active, previous, pending;
    std::deque<std::pair<GameWord, GameplayControls>> queue;
};

class GameplaySession::Impl
{
  public:
    std::vector<GameplayAssets> maps;
    std::size_t map_index{};
    std::vector<GameWord> globals, edicts;
    GameplayWalk walk;
    GamePoint camera{};
    GameWord video{}, last{}, qc_ticks{}, phase{}, clock{}, yaw{}, pitch{}, divider{}, revision{};
    static constexpr unsigned simulation_hz = 20;
    static constexpr unsigned input_vblanks = 60 / simulation_hz;
    bool queued_input{};
    bool collect_sound{};
    std::uint64_t sound_generation{};
    std::vector<GameplaySound> pending_sounds;
    void play_sound(std::string_view name, GameWord entity = 512, std::uint8_t channel = 3,
                    std::uint8_t volume = 255, std::uint8_t attenuation = 64,
                    std::optional<Vec3> position = std::nullopt);
    void play_vm_sound(GameWord sound);
    GameplayInputClock input_clock;
    std::uint64_t services{};
    std::uint64_t sky_phase_q24{};
    std::uint32_t turbulence_phase_q24{}, alias_phase_q32{};
    GameWord buttons{}, previous_buttons{}, contact{}, door_pose{}, button_pose{}, brush_row{}, shell_mask{};
    enum class PickupNotice : GameWord {
        shells = 1, nails, nailgun, armor, health15, health25, megahealth, quad, biosuit, backpack, super_shotgun
    };
    std::array<GameWord, 4> pickup_notice_rows{}, pickup_notice_life{};
    GameWord pickup_notice_next{}, pickup_notice_revision{}, pickup_bonus_ticks{};
    void notify_pickup(PickupNotice message);
    GameWord health_mask{}, health_sound{}, armor_mask{}, armor_angle_step{}, nail_mask{}, super_shotgun_visible{};
    std::array<GameWord, 2> mega_timers{};
    GameWord items_high{}, powerup_mask{}, quad_warn_next{}, quad_warning_pulses{}, suit_warn_next{}, suit_warning_pulses{};
    std::array<GameWord, 2> entrance_pose{};
    std::array<GameWord, 8> exit_ages{};
    std::array<GameWord, 2> platform_phase{}, platform_age{}, platform_wait{};
    std::array<GameWord, 7> secret_door_phase{}, secret_door_wait{}, secret_door_travel{}, secret_door_pose{};
    std::array<int, 14> secret_door_xy{};
    GameWord secret_door_hint_wait{};
    std::array<GameWord, 8> ordinary_phase{}, ordinary_age{}, ordinary_wait{}, ordinary_pose{};
    std::array<int, 8> ordinary_offset{};
    GameWord ordinary_lights{}, ordinary_shot_cooldown{}, ordinary_hint_wait{};
    GameWord t3_trigger_state{};
    GameWord fluorescent_phase{};
    std::array<GameWord, 32> exit_poses{};
    std::array<int, 64> exit_offsets_q4{};
    unsigned key_platform_phase{}, key_platform_age{}, key_platform_wait{};
    bool e1m3_stair_button_hit{};
    std::array<GameWord, 16> e1m2_group_age{}, e1m2_group_wait{};
    unsigned e1m2_key{};
    GameWord exit_targets{}, exit_wait{};
    bool exit_started{};
    GameWord shots{}, pellets{}, hits{}, impact_events{}, shot_clock{}, shot_rng{}, nav_rng{}, shot_view{};
    GameWord shot_yaw{}, shot_pitch{}, effect_word{}, flash{}, damage_flash{};
    struct NailProjectile
    {
        GamePoint origin{}, delta{}, remainder{};
        GameWord life{}, yaw{};
    };
    std::array<NailProjectile, 60> nails{};
    struct CombatImpact
    {
        GamePoint origin{}, delta{}, remainder{};
        unsigned life{}, first_frame{};
    };
    std::array<CombatImpact, 20> combat_impacts{};
    GamePoint impact_origin{}, last_aim{};
    GameWord last_aim_target{};
    unsigned impact_next{}, impact_message{}, impact_style{}, active_impacts{};
    void spawn_impact(GamePoint origin, GamePoint delta, unsigned first_frame);
    void spike_wall_impact();
    void tick_impacts();
    GameWord nail_effect_rng{}, nail_impact_sound{};
    GameWord nail_frame{}, nail_next_frame{}, nail_shots{}, nail_world_hits{}, nail_actor_hits{};
    GameWord axe_selected{}, axe_pending{}, axe_swings{}, axe_hits{};
    bool cycle_weapon{};
    GameWord callbacks{}, statements{}, sounds{}, activations{}, door_blocks{}, fault{}, fault_opcode{};
    GameWord grunt_blocked_moves{}, grunt_unsupported_moves{};
    GameWord grunt_moves{}, grunt_steps_up{}, grunt_shots{};
    std::vector<GameWord> gr_actor_moves, gr_actor_shots;
    std::int16_t mouse_dx{}, mouse_dy{};
    bool menu_open{}, release_gate{}, restart_pending{}, switch_pending{}, campaign_exit{};
    bool respawn_armed{};
    bool initial_pose_set{}, pending_yaw_valid{};
    GameWord pending_yaw{}, hub_teleports{}, hub_teleport_cooldown{};
    GamePoint teleport_departure_eye{};
    GameWord hub_arrival_cooldown_tick{};
    std::string pending_map;
    std::vector<GameplayHubTrigger> hub_skills, hub_teleporters, hub_exits;
    std::vector<GameplayHubTrigger> hub_warning_triggers;
    std::vector<GameplayHubTrigger> hub_hint_removers;
    std::vector<GameplayHubTrigger> secrets;
    GameWord found_secrets{}, secret_mask{}, secret_gate{};
    std::vector<GameWord> hub_warning_cooldowns;
    std::vector<GameplaySwimZone> hub_swim_zones;
    std::vector<std::array<int, 6>> liquid_nodes;
    int liquid_root{}, liquid_ceiling{}, water_level{}, liquid_type{-1};
    GameWord slime_damage_next{};
    bool in_water{};
    GameWord swim_sound_cooldown{};
    int air_ticks{}, drown_cooldown{}, drown_damage{};
    GameWord hub_warning_duration{}, hub_warning_repeat{}, hub_warning_ticks{}, hub_warning_gate{}, hub_warning_events{};
    GameWord hub_clue_edict{}, hub_clue_rearm{}, hub_clue_cooldown{};
    std::vector<std::string> hub_messages;
    unsigned menu_selection{}, skill_selected{1}, skill_active{1}, scale{2};
    std::size_t draft_map{};
    bool entities_enabled{true}, brushes_enabled{true};
    bool always_run{true};
    unsigned menu_scale{}, technique{4}, draft_technique{4};
    bool draft_entities{true}, draft_brushes{true};
    int budget{}, depth{}, saved_local_bytes{};
    std::function<void(std::string_view)> checkpoint_hook;
    bool gameplay_menu() const { return queued_input ? input_clock.active.menu : menu_open; }
    bool gameplay_release() const
    {
        return queued_input ? input_clock.active.release || input_clock.respawn_release : release_gate;
    }
    GameWord gameplay_buttons() const { return queued_input ? input_clock.active.buttons : buttons; }
    GameWord gameplay_rng_tick() const { return queued_input ? last : video; }
    std::size_t input_record_cells(const GameplayControls& sample) const;
    void latch_input(GameplayControls sample);
    void consume_input();
    void publish_walk();
    bool request_respawn();
    void checkpoint(std::string_view checkpoint_name)
    {
        if (checkpoint_hook)
            checkpoint_hook(checkpoint_name);
    }

    const GameplayAssets& assets() const
    {
        return maps.at(map_index);
    }
    std::int64_t constant(std::string_view name, std::int64_t fallback = 0) const
    {
        auto i = assets().constants.find(std::string(name));
        return i == assets().constants.end() ? fallback : i->second;
    }
    const std::vector<std::uint8_t>& bytes(std::string_view name) const
    {
        auto i = assets().payloads.find(std::string(name));
        if (i == assets().payloads.end())
            throw std::runtime_error("missing gameplay payload: " + std::string(name));
        return i->second;
    }
    GameWord& g(std::size_t offset)
    {
        if (offset & 1 || offset / 2 >= globals.size())
            throw std::runtime_error("gameplay global offset out of bounds");
        return globals[offset / 2];
    }
    GameWord& global(std::string_view name)
    {
        return g(static_cast<std::size_t>(constant("QC_GLOBAL_" + std::string(name))));
    }
    std::size_t edict_index(std::size_t actor, std::size_t field) const
    {
        const auto p = actor + field;
        if (p & 1 || p / 2 >= edicts.size())
            throw std::runtime_error("gameplay edict offset out of bounds");
        return p / 2;
    }
    GameWord& e(std::size_t actor, std::size_t field)
    {
        return edicts[edict_index(actor, field)];
    }
    GameWord e(std::size_t actor, std::size_t field) const
    {
        return edicts[edict_index(actor, field)];
    }
    GameWord& field(std::size_t actor, std::string_view name, unsigned axis = 0)
    {
        return e(actor, static_cast<std::size_t>(constant("QC_FIELD_" + std::string(name))) + axis * 2);
    }
    GameWord player(std::string_view name, unsigned axis = 0) const
    {
        const auto p = 512 + std::size_t(constant("QC_FIELD_" + std::string(name))) + axis * 2;
        return edicts.at(p / 2);
    }
    bool basic() const
    {
        return constant("QC_BASIC_GAMEPLAY") != 0;
    }
    std::int16_t sine(unsigned angle) const
    {
        return static_cast<std::int16_t>(assets().manifest.at("tables").at("cameraSinQ6").at(angle & 255).get<int>());
    }
    std::int16_t cosine(unsigned angle) const
    {
        return sine(angle + 64);
    }
    std::int16_t move_sine(unsigned angle) const
    {
        return static_cast<std::int16_t>(
            assets().manifest.at("tables").at("cameraMoveSinQ4").at(angle & 255).get<int>()
        );
    }
    std::int16_t move_cosine(unsigned angle) const
    {
        return move_sine(angle + 64);
    }
    const Json& metadata() const
    {
        return assets().manifest.at("metadata").at("gameplay");
    }
    void reset(std::string_view map, unsigned skill);
    void video_tick(const GameplayInput& input);
    bool service_tick();
    void queue_restart();
    void menu(const GameplayInput& input, GameWord triggered);
    void sync_player();
    void walk_tick();
    bool water_jump(int facing_yaw, int facing_pitch, int vblanks);
    void walk_breath_tick(bool submerged, int vblanks);
    void walk_vertical(int displacement, int previous_velocity);
    void walk_gravity(int previous_velocity);
    void queue_landing(int previous_velocity);
    bool landing_in_water() const;
    void finish_landing();
    GamePoint swim_move(int forward, int side, int yaw_angle, int pitch_angle, bool slow);
    GamePoint walk_run(GamePoint wish, int target_speed = 256);
    GamePoint walk_horizontal(GamePoint wish, bool& can_step, GameWord& step_plane);
    void shell_touch();
    void health_touch();
    void mega_rot();
    void armor_touch();
    void nail_touch();
    void super_shotgun_touch();
    void nail_tick();
    void nail_attack(bool fire);
    int environmental_damage(int points);
    void shot_tick();
    void qc_step();
    void invoke(GameWord function);
    void event(GameWord actor, GameWord other, GameWord function, int statement_budget = 512);
    void builtin(std::int16_t function);
    void pusher(GameWord actor, unsigned axis, bool door);
    void entrance_tick();
    void exit_tick();
    void secret_doors_tick();
    void ordinary_doors_tick();
    void ordinary_door_use(std::size_t index);
    void secret_door_start(std::size_t index);
    void secret_door_shot(GameWord terminal);
    void platforms_tick(const GamePoint& point, const Json& movers);
    bool vertical_pusher_blocked(const GamePoint& eye, const Json& mover, std::size_t index,
                                int& offset, int next);
    void e1m2_machinery_tick();
    void e1m3_mover_tick(std::size_t index, const Json& mover, int age);
    std::uint32_t exit_pose_word() const;
    void hub_init();
    bool hub_can_swim(const GamePoint& point) const;
    int liquid_contents(const GamePoint& eye, int height) const;
    void liquid_effects();
    void hub_tick();
    bool intermission_service();
    GameWord intermission_phase{}, intermission_wait{}, intermission_video{}, intermission_subseconds{}, intermission_seconds{};
    GameWord intermission_camera{}, intermission_kills{}, intermission_monsters{};
    void teleport_death_touch();
    void hub_shoot_clue();
    std::string_view hub_centerprint() const;
    void entrance_pusher(unsigned leaf);
    GameWord entrance_quantized_pose(unsigned leaf, GameWord origin) const;
    GameWord support_pose_key() const;
    std::array<GameWord, 2> entrance_render_rows(std::array<GameWord, 2> poses) const;
    bool entrance_contains_player(unsigned leaf, GameWord candidate_pose, const GamePoint& point);
    void grunt_tick(unsigned elapsed_units = 1);
    void grunt_builtin(std::int16_t function);
    void dog_advance(GameWord actor);
    bool grunt_clear_of_player(GameWord actor, const GamePoint& position);
    bool grunt_check_bottom(GameWord actor, const GamePoint& position);
    void grunt_store_origin(GameWord actor, const GamePoint& position);
    GameWord patrol_word(GameWord token, unsigned offset);
    GameWord random(bool navigation = false);
    void make_vectors();
    void trace_shot();
    void trace_actors(GameplayTrace& trace, const GamePoint& start, const GamePoint& end);
    void player_aim();
    GameplayTrace trace(const GamePoint& from, const GamePoint& to, bool point = false, bool skin = true);
    bool point_solid(const GamePoint& point);
    std::int64_t plane_distance(GameWord ref, const GamePoint& point, bool shot);
    GamePoint plane_normal(GameWord ref, bool shot);
    bool grunt_move(GameWord actor, GameWord angle, GameWord distance, bool turn_only = false);
    void grunt_move_to_goal(GameWord actor, GameWord distance);
    void grunt_change_yaw(GameWord actor);
    static constexpr unsigned pack_life = 402, pack_shells = 404, pack_origin = 406, pack_velocity = 412;
    void powerup_touch();
    void powerup_tick();
    void powerup_attack();
    static constexpr unsigned gib_records = 400, gib_size = 28;
    static constexpr unsigned gib_row = 2, gib_origin = 4, gib_velocity = 10, gib_angles = 16, gib_spin = 22;
    void gib_capture(bool head);
    void gib_advance(GameWord actor, unsigned elapsed_units);
    void gib_toss(GameWord actor, unsigned record, bool head);
    void backpack_spawn();
    void backpack_advance(GameWord actor, unsigned elapsed_units);
    void grunt_ride_lift(GameWord next_pose);
    GameWord vector_yaw(GameWord x, GameWord y);
    GameWord vector_length(bool normalize = false);
    Json state() const;
    GameplayRenderSnapshot snapshot(bool consume_weapon);
};

// Qualification-only worker retains the independent VM/physics call stack.
// The normal synchronous service never creates a thread or waits at a hook.
class GameplaySession::Continuation
{
  public:
    explicit Continuation(Impl& engine);
    ~Continuation();
    Continuation(const Continuation&) = delete;
    Continuation& operator=(const Continuation&) = delete;
    std::string phase() const;
    std::string resume();
    bool result() const;

  private:
    void checkpoint(std::string_view phase);
    Impl& engine_;
    std::thread thread_;
    mutable std::mutex mutex_;
    std::condition_variable condition_;
    std::string phase_;
    std::exception_ptr error_;
    bool paused_{}, finished_{}, advance_{}, cancelled_{}, result_{};
};

} // namespace quake_bsp_reference
