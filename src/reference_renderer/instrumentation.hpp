#pragma once

#include "geometry.hpp"

namespace quake_bsp_reference {

struct ReferenceInstrumentationConfig
{
    std::string session_id;
    std::string pipe_name;

    [[nodiscard]] bool enabled() const
    {
        return !session_id.empty();
    }
};

bool valid_reference_instrumentation_identifier(std::string_view value);

struct ReferenceInstrumentationCommands
{
    std::optional<bool> paused;
    std::optional<PlaybackSchedule> pace;
    std::optional<int> presentation_rate_hz;
    std::optional<std::size_t> pose;
    std::optional<bool> external_bsp_models;
    std::optional<bool> sound_enabled;
    std::optional<float> sound_volume;
    std::optional<std::string> window_capture_path;
    bool shutdown{};
};

class ReferenceControlLayout
{
  public:
    explicit ReferenceControlLayout(ImVec2 origin);
    ~ReferenceControlLayout();

    ReferenceControlLayout(const ReferenceControlLayout&) = delete;
    ReferenceControlLayout& operator=(const ReferenceControlLayout&) = delete;
    ReferenceControlLayout(ReferenceControlLayout&&) noexcept;
    ReferenceControlLayout& operator=(ReferenceControlLayout&&) noexcept;

    void begin_row(std::string name);
    void add_item(std::string_view name);
    Json finish(int client_width, int controls_height);

  private:
    class Impl;
    std::unique_ptr<Impl> impl_;
};

class ReferenceInstrumentationServer
{
  public:
    explicit ReferenceInstrumentationServer(ReferenceInstrumentationConfig config);
    ~ReferenceInstrumentationServer();

    ReferenceInstrumentationServer(const ReferenceInstrumentationServer&) = delete;
    ReferenceInstrumentationServer& operator=(const ReferenceInstrumentationServer&) = delete;

    [[nodiscard]] bool enabled() const;
    ReferenceInstrumentationCommands take_commands();
    void capture_window(SDL_Renderer* renderer, const std::string& path, std::size_t pose);
    void publish(
        std::size_t pose,
        std::size_t pose_count,
        std::uint64_t loop,
        bool paused,
        PlaybackSchedule schedule,
        int presentation_rate_hz,
        const LiveWindowState& live_state,
        std::uint64_t frame_generation,
        std::span<const std::uint8_t> indices,
        Json control_layout,
        Json alias_inspection,
        Json surface_inspection,
        Json external_bsp_inspection,
        Json audio_inspection
    );

  private:
    class Impl;
    std::unique_ptr<Impl> impl_;
};

} // namespace quake_bsp_reference
