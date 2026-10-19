#pragma once

#include "world.hpp"
#include "presentation_warp.hpp"
#include <future>
#include <tuple>
#include "geometry.hpp"
#include "instrumentation.hpp"
#include "brushes.hpp"
#include "audio.hpp"
#include "external_models.hpp"
#include "aliases.hpp"
#include "textured_live.hpp"
#include "particles.hpp"

namespace quake_bsp_reference {

struct LiveDemoConfiguration
{
    std::string playback_contract;
    RenderMode initial_mode;
    bool initial_legacy_material{};
    PlaybackSpeed initial_playback_speed{PlaybackSpeed::Realtime};
    bool playback_speed_control{};
    PlaybackSchedule playback_schedule{PlaybackSchedule::NewestDue};
    int initial_presentation_rate_hz{3};
    int ordered_source_rate_hz{30};
    ReferenceInstrumentationConfig instrumentation_config;
    const QuakeSoundAssets* sound_assets{};
    bool initial_sound_enabled{};
    float initial_sound_volume{};
    bool legacy_material_control{};
    bool brush_control{};
    bool entity_control{};
    bool external_bsp_model_control{};
    bool particle_control{};
    bool initial_brushes{};
    bool initial_entities{};
    bool initial_external_bsp_models{};
    bool initial_particles{};
    std::function<ViewTransform(std::size_t)> camera_at_pose{};
    bool scene_pose_control{};
    std::function<void(std::optional<SourceCamera>)> capture_camera_setter{};
};

template <typename CameraType>
void validate_live_demo(
    const std::vector<CameraType>& cameras,
    double duration_seconds,
    const LiveDemoConfiguration& configuration
)
{
    if (cameras.empty() || !std::isfinite(duration_seconds) || duration_seconds <= 0.0)
    {
        fail("live demo requires a non-empty track and positive duration");
    }
    if (cameras.size() > static_cast<std::size_t>(std::numeric_limits<int>::max()))
    {
        fail("demo track has too many poses for the playback slider");
    }
    if (configuration.initial_presentation_rate_hz != 3 && configuration.initial_presentation_rate_hz != 30)
    {
        fail("ordered playback rate must be 3 or 30 Hz");
    }
    if (configuration.playback_schedule != PlaybackSchedule::NewestDue &&
        (configuration.ordered_source_rate_hz < configuration.initial_presentation_rate_hz ||
         configuration.ordered_source_rate_hz % configuration.initial_presentation_rate_hz != 0 ||
         configuration.ordered_source_rate_hz % 3 != 0 || configuration.ordered_source_rate_hz % 30 != 0))
    {
        fail("ordered playback source rate must support exact 3 and 30 Hz strides");
    }
    if (!is_supported_render_mode(configuration.initial_mode) || configuration.initial_legacy_material ||
        configuration.legacy_material_control)
    {
        fail("live reference renderer supports only techniques 2, 4, and 7");
    }
}

struct LiveDemoTick
{
    double delta_seconds{};
};

template <typename CameraType, typename PoseAtTime, typename TimeAtPose, typename ListenerAtPose, typename RenderPose>
class LiveDemoSession
{
  public:
    LiveDemoSession(
        const SourceWorld& world,
        const std::vector<CameraType>& cameras,
        double duration_seconds,
        PoseAtTime pose_at_time,
        TimeAtPose time_at_pose,
        ListenerAtPose listener_at_pose,
        RenderPose render_pose,
        LiveDemoConfiguration configuration
    )
    :
    world_(world),
    cameras_(cameras),
    duration_seconds_(duration_seconds),
    pose_at_time_(std::move(pose_at_time)),
    time_at_pose_(std::move(time_at_pose)),
    listener_at_pose_(std::move(listener_at_pose)),
    render_pose_(std::move(render_pose)),
    configuration_(std::move(configuration)),
    playback_schedule_(configuration_.playback_schedule),
    presentation_rate_hz_(configuration_.initial_presentation_rate_hz)
    {
    }

    ~LiveDemoSession()
    {
        shutdown_presentation();
    }

    int run()
    {
        initialize_state();
        initialize_presentation();
        initialize_clock();
        while (running_)
        {
            run_iteration();
        }
        shutdown_presentation();
        return 0;
    }

  private:
    using Clock = std::chrono::steady_clock;

    void initialize_state()
    {
        state_.mode = configuration_.initial_mode;
        state_.scale = active_render_scale;
        warp_settings_ = active_warp_settings;
        state_.legacy_material = configuration_.initial_legacy_material;
        state_.playback_speed = configuration_.initial_playback_speed;
        state_.brushes_enabled = configuration_.initial_brushes;
        state_.entities_enabled = configuration_.initial_entities;
        state_.external_bsp_models = configuration_.initial_external_bsp_models;
        state_.particles_available = configuration_.particle_control;
        state_.particles_enabled = state_.particles_available && configuration_.initial_particles;
        state_.sound_enabled = configuration_.initial_sound_enabled;
        state_.sound_volume = configuration_.initial_sound_volume;
        instrumentation_ =
            std::make_unique<ReferenceInstrumentationServer>(std::move(configuration_.instrumentation_config));
        render_current_pose();
        update_live_pixels(state_, current_indices_, world_);
    }

    void initialize_presentation()
    {
        SDL_SetMainReady();
        if (!SDL_Init(SDL_INIT_VIDEO))
        {
            fail(std::string("cannot initialize SDL3: ") + SDL_GetError());
        }
        sdl_initialized_ = true;
        const std::string initial_title = "E1M3 demo1 - C++ reference | " + configuration_.playback_contract;
        window_ = SDL_CreateWindow(
            initial_title.c_str(),
            kMinimumLiveClientWidth,
            (kLogicalHeight * 4) + controls_height(),
            SDL_WINDOW_RESIZABLE
        );
        if (window_ == nullptr)
        {
            fail(std::string("cannot create SDL3 window: ") + SDL_GetError());
        }
        SDL_SetWindowMinimumSize(window_, kMinimumLiveClientWidth, kLogicalHeight + controls_height());
        renderer_ = SDL_CreateRenderer(window_, nullptr);
        if (renderer_ == nullptr)
        {
            fail(std::string("cannot create SDL3 renderer: ") + SDL_GetError());
        }
        SDL_SetRenderVSync(renderer_, 1);
        pixels_dirty_ = true;
        upload_pixels_if_dirty();

        IMGUI_CHECKVERSION();
        ImGui::CreateContext();
        imgui_context_initialized_ = true;
        ImGui::GetIO().IniFilename = nullptr;
        ImGui::StyleColorsDark();
        if (!ImGui_ImplSDL3_InitForSDLRenderer(window_, renderer_))
        {
            fail("cannot initialize Dear ImGui SDL3 backends");
        }
        imgui_sdl_initialized_ = true;
        if (!ImGui_ImplSDLRenderer3_Init(renderer_))
        {
            fail("cannot initialize Dear ImGui SDL3 backends");
        }
        imgui_renderer_initialized_ = true;
        audio_ = std::make_unique<QuakeAudioSession>(configuration_.sound_assets);
    }

    void initialize_clock()
    {
        previous_tick_ = Clock::now();
    }

    void run_iteration()
    {
        const auto commands = instrumentation_->take_commands();
        reset_iteration();
        if (commands.window_capture_path.has_value())
        {
            SDL_SetWindowSize(
                window_,
                kMinimumLiveClientWidth,
                (kLogicalHeight * (kMinimumLiveClientWidth / kLogicalWidth)) + controls_height()
            );
            ImGui::GetIO().AddMousePosEvent(-FLT_MAX, -FLT_MAX);
        }
        apply_session_commands(commands);
        poll_events();
        if (!running_)
        {
            return;
        }
        const auto tick = update_clock();
        apply_requested_pose(commands);
        advance_playback(tick.delta_seconds);
        begin_controls();
        draw_controls();
        finish_controls();
        commit_requested_pose();
        refresh_render_if_dirty();
        upload_pixels_if_dirty();
        synchronize_audio();
        update_window_title();
        present(commands.window_capture_path);
        publish_instrumentation();
        mark_ordered_frame_presented();
        SDL_Delay(1);
    }

    void reset_iteration()
    {
        requested_pose_ = current_pose_;
        frame_dirty_ = false;
        pixels_dirty_ = false;
        instrumentation_control_layout_ = Json::object();
        control_layout_.reset();
    }

    void reset_ordered_timing()
    {
        ordered_wall_seconds_ = 0.0;
        ordered_frame_presented_ = false;
    }

    void apply_session_commands(const ReferenceInstrumentationCommands& commands)
    {
        if (commands.paused.has_value())
        {
            state_.paused = *commands.paused;
            if (!state_.paused)
                clear_capture_overrides();
        }
        if (commands.pace.has_value() && playback_schedule_ != PlaybackSchedule::NewestDue)
        {
            playback_schedule_ = *commands.pace;
            reset_ordered_timing();
        }
        if (commands.presentation_rate_hz.has_value() && playback_schedule_ != PlaybackSchedule::NewestDue)
        {
            presentation_rate_hz_ = *commands.presentation_rate_hz;
            reset_ordered_timing();
        }
        if (commands.external_bsp_models.has_value() && state_.external_bsp_models != *commands.external_bsp_models)
        {
            state_.external_bsp_models = *commands.external_bsp_models;
            frame_dirty_ = true;
        }
        if (commands.sound_enabled.has_value())
        {
            state_.sound_enabled = *commands.sound_enabled;
        }
        if (commands.particles_enabled.has_value() && state_.particles_enabled != *commands.particles_enabled)
        {
            state_.particles_enabled = *commands.particles_enabled;
            frame_dirty_ = true;
        }
        if (commands.sound_volume.has_value())
        {
            state_.sound_volume = *commands.sound_volume;
        }
        if (commands.render_scale.has_value() && state_.scale != *commands.render_scale)
        {
            state_.scale = *commands.render_scale;
            frame_dirty_ = true;
            view_pose_override_.reset();
        }
        if (commands.view_pose.has_value())
            view_pose_override_ = commands.view_pose;
        if (commands.warp_settings.has_value())
            warp_settings_ = *commands.warp_settings;
        if (commands.scene_pose.has_value())
        {
            scene_pose_override_ =
                *commands.scene_pose < 0
                    ? std::nullopt
                    : std::optional<std::size_t>(static_cast<std::size_t>(*commands.scene_pose));
            ++render_epoch_;
            frame_dirty_ = true;
        }
        if (commands.capture_camera.has_value())
        {
            // Drain a previous async render before changing its captured camera.
            if (pending_render_.valid())
                static_cast<void>(pending_render_.get());
            configuration_.capture_camera_setter(*commands.capture_camera);
            capture_camera_active_ = commands.capture_camera->has_value();
            ++render_epoch_;
            frame_dirty_ = true;
        }
        if (commands.shutdown)
        {
            running_ = false;
        }
    }

    void poll_events()
    {
        SDL_Event event{};
        while (SDL_PollEvent(&event))
        {
            ImGui_ImplSDL3_ProcessEvent(&event);
            if (event.type == SDL_EVENT_QUIT || event.type == SDL_EVENT_WINDOW_CLOSE_REQUESTED)
            {
                running_ = false;
            }
            if (event.type == SDL_EVENT_KEY_DOWN && !event.key.repeat)
            {
                process_key(event.key.key);
            }
        }
    }

    void process_key(SDL_Keycode key)
    {
        if (key == SDLK_ESCAPE)
        {
            running_ = false;
        }
        else if (key == SDLK_SPACE)
        {
            state_.paused = !state_.paused;
            if (!state_.paused)
                clear_capture_overrides();
        }
    }

    LiveDemoTick update_clock()
    {
        const auto now = Clock::now();
        const double delta = std::chrono::duration<double>(now - previous_tick_).count();
        previous_tick_ = now;
        return {delta};
    }

    void apply_requested_pose(const ReferenceInstrumentationCommands& commands)
    {
        if (!commands.pose.has_value())
        {
            return;
        }
        ++render_epoch_;
        frame_dirty_ = true;
        view_pose_override_.reset();
        requested_pose_ = *commands.pose;
        playback_seconds_ = time_at_pose_(requested_pose_);
        reset_ordered_timing();
        state_.paused = true;
    }

    void advance_playback(double delta_seconds)
    {
        if (state_.paused)
        {
            return;
        }
        switch (playback_schedule_)
        {
        case PlaybackSchedule::OrderedRenderCompletion:
            advance_render_completion_playback();
            return;
        case PlaybackSchedule::OrderedTimed:
            advance_timed_playback(delta_seconds);
            return;
        case PlaybackSchedule::NewestDue:
            advance_newest_due_playback(delta_seconds);
            return;
        }
    }

    void advance_render_completion_playback()
    {
        if (ordered_frame_presented_)
        {
            advance_ordered_pose();
        }
    }

    void advance_timed_playback(double delta_seconds)
    {
        ordered_wall_seconds_ += delta_seconds;
        if (consume_ordered_demo_deadline(
                1.0 / static_cast<double>(presentation_rate_hz_),
                ordered_frame_presented_,
                ordered_wall_seconds_
            ))
        {
            advance_ordered_pose();
        }
    }

    void advance_ordered_pose()
    {
        const auto advance = advance_ordered_demo_pose(cameras_.size(), requested_pose_, ordered_pose_stride());
        if (advance.wrapped)
        {
            ++loop_;
        }
        playback_seconds_ = time_at_pose_(requested_pose_);
    }

    [[nodiscard]] std::size_t ordered_pose_stride() const
    {
        return static_cast<std::size_t>(configuration_.ordered_source_rate_hz / presentation_rate_hz_);
    }

    void advance_newest_due_playback(double delta_seconds)
    {
        playback_seconds_ += playback_source_delta(delta_seconds, state_.playback_speed);
        while (playback_seconds_ >= duration_seconds_)
        {
            playback_seconds_ -= duration_seconds_;
            ++loop_;
        }
        requested_pose_ = pose_at_time_(playback_seconds_);
    }

    void begin_controls()
    {
        ImGui_ImplSDLRenderer3_NewFrame();
        ImGui_ImplSDL3_NewFrame();
        ImGui::NewFrame();

        int client_height{};
        SDL_GetWindowSize(window_, &client_width_, &client_height);
        viewport_height_ = std::max(0, client_height - controls_height());
        ImGui::SetNextWindowPos(ImVec2{0.0F, static_cast<float>(viewport_height_)});
        ImGui::SetNextWindowSize(ImVec2{static_cast<float>(client_width_), static_cast<float>(controls_height())});
        constexpr ImGuiWindowFlags controls_flags =
            ImGuiWindowFlags_NoTitleBar | ImGuiWindowFlags_NoMove | ImGuiWindowFlags_NoResize |
            ImGuiWindowFlags_NoCollapse | ImGuiWindowFlags_NoSavedSettings;
        ImGui::Begin("Playback", nullptr, controls_flags);
        if (instrumentation_->enabled())
        {
            control_layout_.emplace(ImGui::GetWindowPos());
        }
    }

    void begin_control_row(std::string_view name)
    {
        if (control_layout_.has_value())
        {
            control_layout_->begin_row(std::string(name));
        }
    }

    void record_control(std::string_view name)
    {
        if (control_layout_.has_value())
        {
            control_layout_->add_item(name);
        }
    }

    [[nodiscard]] bool ordered_pace_control() const
    {
        return playback_schedule_ == PlaybackSchedule::OrderedTimed ||
               playback_schedule_ == PlaybackSchedule::OrderedRenderCompletion;
    }

    [[nodiscard]] int controls_height() const
    {
        return kPlaybackControlsHeight + (warp_settings_.hdma ? 23 : 0) +
               (warp_settings_.hdma && !warp_settings_.inverse_depth_profile.empty() ? 23 : 0);
    }

    void draw_controls()
    {
        draw_playback_controls();
        draw_rendering_controls();
        draw_hdma_controls();
        draw_feature_controls();
        draw_audio_controls();
        draw_contract_control();
        draw_seek_control();
    }

    void draw_playback_controls()
    {
        begin_control_row("playback");
        if (ImGui::Button(state_.paused ? "Resume" : "Pause"))
        {
            state_.paused = !state_.paused;
            if (!state_.paused)
                clear_capture_overrides();
        }
        record_control("pause");
        ImGui::SameLine();
        ImGui::Text("Sample %zu / %zu", requested_pose_ + 1, cameras_.size());
        record_control("sample");
        draw_playback_speed_control();
        draw_ordered_pace_controls();
    }

    void draw_playback_speed_control()
    {
        if (!configuration_.playback_speed_control)
        {
            return;
        }
        ImGui::SameLine();
        ImGui::SetNextItemWidth(110.0F);
        int selected_speed = static_cast<int>(state_.playback_speed);
        if (ImGui::Combo(
                "Speed",
                &selected_speed,
                kPlaybackSpeedLabels.data(),
                static_cast<int>(kPlaybackSpeedLabels.size())
            ))
        {
            state_.playback_speed = static_cast<PlaybackSpeed>(selected_speed);
        }
        record_control("speed");
    }

    void draw_ordered_pace_controls()
    {
        if (!ordered_pace_control())
        {
            return;
        }
        ImGui::SameLine();
        ImGui::SetNextItemWidth(110.0F);
        int selected_pace = playback_schedule_ == PlaybackSchedule::OrderedTimed ? 0 : 1;
        if (ImGui::Combo(
                "Pace",
                &selected_pace,
                kOrderedPaceLabels.data(),
                static_cast<int>(kOrderedPaceLabels.size())
            ))
        {
            playback_schedule_ =
                selected_pace == 0 ? PlaybackSchedule::OrderedTimed : PlaybackSchedule::OrderedRenderCompletion;
            reset_ordered_timing();
        }
        record_control("pace");
        ImGui::SameLine();
        ImGui::SetNextItemWidth(70.0F);
        int selected_rate = presentation_rate_hz_ == 3 ? 0 : 1;
        if (ImGui::Combo(
                "Rate",
                &selected_rate,
                kOrderedRateLabels.data(),
                static_cast<int>(kOrderedRateLabels.size())
            ))
        {
            presentation_rate_hz_ = selected_rate == 0 ? 3 : 30;
            reset_ordered_timing();
        }
        record_control("presentationRate");
    }

    void draw_rendering_controls()
    {
        begin_control_row("rendering");
        draw_surface_control();
        ImGui::SameLine();
        ImGui::SetNextItemWidth(110.0F);
        constexpr std::array supported_lighting_labels{"None", "LightMap"};
        int selected_lighting = state_.mode.lighting == Lighting::None ? 0 : 1;
        ImGui::BeginDisabled(!state_.mode.textures);
        if (ImGui::Combo(
                "Lighting",
                &selected_lighting,
                supported_lighting_labels.data(),
                static_cast<int>(supported_lighting_labels.size())
            ))
        {
            state_.mode.lighting = selected_lighting == 0 ? Lighting::None : Lighting::LightMap;
            frame_dirty_ = true;
        }
        record_control("lighting");
        ImGui::EndDisabled();
        ImGui::SameLine();
        ImGui::SetNextItemWidth(90.0F);
        int liquid_lighting = state_.mode.liquid_lighting == Lighting::None ? 0 : 1;
        ImGui::BeginDisabled(!state_.mode.textures || state_.mode.lighting == Lighting::None);
        if (ImGui::Combo("Liquid lighting", &liquid_lighting, supported_lighting_labels.data(), 2))
        {
            state_.mode.liquid_lighting = liquid_lighting == 0 ? Lighting::None : Lighting::LightMap;
            frame_dirty_ = true;
        }
        record_control("liquidLighting");
        ImGui::EndDisabled();
        int liquid_turbulence = state_.mode.liquid_turbulence == LiquidTurbulence::SnesQ4 ? 1 : 0;
        ImGui::SetNextItemWidth(90.0F);
        ImGui::BeginDisabled(!state_.mode.textures);
        if (ImGui::Combo("Liquid turbulence", &liquid_turbulence, "none\0snes-q4\0"))
        {
            state_.mode.liquid_turbulence = liquid_turbulence == 0 ? LiquidTurbulence::None : LiquidTurbulence::SnesQ4;
            frame_dirty_ = true;
        }
        record_control("liquidTurbulence");
        ImGui::EndDisabled();
        ImGui::SameLine();
        ImGui::SetNextItemWidth(100.0F);
        int selected_scale = static_cast<int>(state_.scale);
        if (ImGui::Combo(
                "Scale",
                &selected_scale,
                kRenderScaleLabels.data(),
                static_cast<int>(kRenderScaleLabels.size())
            ))
        {
            state_.scale = static_cast<RenderScale>(selected_scale);
            frame_dirty_ = true;
            view_pose_override_.reset();
        }
        record_control("scale");
        ImGui::SameLine();
        ImGui::SetNextItemWidth(100.0F);
        int model = warp_settings_.hdma ? 2 : warp_settings_.projective ? 0 : 1;
        if (ImGui::Combo("Warp", &model, "Projective\0Mode 7\0HDMA\0"))
        {
            warp_settings_.projective = model == 0;
            warp_settings_.hdma = model == 2;
        }
        record_control("warpModel");
        ImGui::SameLine();
        ImGui::SetNextItemWidth(85.0F);
        float depth = static_cast<float>(warp_settings_.depth);
        if (ImGui::DragFloat("Depth", &depth, 1.0F, 0.0F, 8192.0F, "%.0f") && std::isfinite(depth))
            warp_settings_.depth = depth < 1.0F ? 0.0 : std::min(8192.0, static_cast<double>(depth));
        record_control("warpDepth");
        if (ImGui::IsItemHovered())
            ImGui::SetTooltip("Quake units along the rendered forward axis. Zero uses rotation only.");
    }

    void draw_hdma_controls()
    {
        if (!warp_settings_.hdma)
            return;
        begin_control_row("hdma");
        constexpr std::array counts{1, 8, 16, 32, 224};
        int selected = static_cast<int>(std::find(counts.begin(), counts.end(), warp_settings_.bands) - counts.begin());
        ImGui::SetNextItemWidth(115.0F);
        if (ImGui::Combo("Bands", &selected, "1\0 8\0 16\0 32\0 Per scanline\0"))
            warp_settings_.bands = counts[static_cast<std::size_t>(selected)];
        record_control("warpBands");
        ImGui::SameLine();
        int shape =
            warp_settings_.inverse_depth_profile.empty() ? 0
            : warp_settings_.inverse_depth_profile.size() == 3
                ? 1
                : 2;
        ImGui::SetNextItemWidth(115.0F);
        if (ImGui::Combo("Depth profile", &shape, "Uniform\0Three values\0Five values\0"))
        {
            const int q =
                std::clamp(static_cast<int>(std::nearbyint(65536.0 / std::max(16.0, warp_settings_.depth))), 8, 4096);
            warp_settings_.inverse_depth_profile.assign(shape == 0 ? 0U : shape == 1 ? 3U : 5U, q);
        }
        record_control("warpProfile");
        if (!warp_settings_.inverse_depth_profile.empty())
        {
            begin_control_row("depthProfile");
            for (std::size_t i = 0; i < warp_settings_.inverse_depth_profile.size(); ++i)
            {
                if (i != 0)
                    ImGui::SameLine();
                auto& q = warp_settings_.inverse_depth_profile[i];
                float value = q == 0 ? 8192.0F : 65536.0F / static_cast<float>(q);
                ImGui::SetNextItemWidth(70.0F);
                const auto label = "Depth " + std::to_string(i + 1);
                if (ImGui::DragFloat(label.c_str(), &value, 1.0F, 16.0F, 8192.0F, "%.1f") && std::isfinite(value))
                {
                    for (auto& existing : warp_settings_.inverse_depth_profile)
                        existing = std::max(8, existing);
                    q = std::clamp(
                        static_cast<int>(std::nearbyint(65536.0 / std::clamp(value, 16.0F, 8192.0F))),
                        8,
                        4096
                    );
                }
                record_control("warpDepth" + std::to_string(i + 1));
            }
        }
    }

    void draw_surface_control()
    {
        if (ImGui::Checkbox("Textures", &state_.mode.textures))
        {
            if (!state_.mode.textures)
            {
                state_.mode.lighting = Lighting::LightMap;
            }
            frame_dirty_ = true;
        }
        record_control("textures");
    }

    [[nodiscard]] bool has_feature_controls() const
    {
        return configuration_.brush_control || configuration_.entity_control ||
               configuration_.external_bsp_model_control || configuration_.legacy_material_control ||
               configuration_.particle_control;
    }

    void draw_feature_controls()
    {
        if (!has_feature_controls())
        {
            return;
        }
        begin_control_row("features");
        bool present = false;
        draw_feature_toggle(
            configuration_.brush_control,
            "Dynamic brushes",
            state_.brushes_enabled,
            "dynamicBrushes",
            present
        );
        draw_feature_toggle(configuration_.entity_control, "Entities", state_.entities_enabled, "mdlEntities", present);
        draw_feature_toggle(
            configuration_.external_bsp_model_control,
            "Source BSP models",
            state_.external_bsp_models,
            "externalBspModels",
            present
        );
        draw_feature_toggle(
            configuration_.legacy_material_control,
            "Legacy material",
            state_.legacy_material,
            "legacyMaterial",
            present
        );
        draw_feature_toggle(
            configuration_.particle_control,
            "Particles",
            state_.particles_enabled,
            "particles",
            present
        );
    }

    void
    draw_feature_toggle(bool available, const char* label, bool& value, std::string_view control_name, bool& present)
    {
        if (!available)
        {
            return;
        }
        if (present)
        {
            ImGui::SameLine();
        }
        if (ImGui::Checkbox(label, &value))
        {
            frame_dirty_ = true;
        }
        record_control(control_name);
        present = true;
    }

    void draw_audio_controls()
    {
        if (configuration_.sound_assets == nullptr)
        {
            return;
        }
        begin_control_row("audio");
        ImGui::Checkbox("Sound", &state_.sound_enabled);
        record_control("sound");
        ImGui::SameLine();
        ImGui::SetNextItemWidth(180.0F);
        ImGui::SliderFloat("Volume", &state_.sound_volume, 0.0F, 1.0F, "%.2f");
        record_control("volume");
    }

    void draw_contract_control()
    {
        begin_control_row("contract");
        ImGui::TextUnformatted(configuration_.playback_contract.c_str());
        record_control("contract");
    }

    void draw_seek_control()
    {
        begin_control_row("seek");
        ImGui::SetNextItemWidth(-1.0F);
        int requested_pose = static_cast<int>(requested_pose_);
        if (ImGui::SliderInt("##playback", &requested_pose, 0, static_cast<int>(cameras_.size()) - 1, ""))
        {
            ++render_epoch_;
            frame_dirty_ = true;
            view_pose_override_.reset();
            requested_pose_ = static_cast<std::size_t>(requested_pose);
            playback_seconds_ = time_at_pose_(requested_pose_);
            reset_ordered_timing();
            state_.paused = true;
        }
        record_control("seek");
    }

    void finish_controls()
    {
        if (control_layout_.has_value())
        {
            instrumentation_control_layout_ = control_layout_->finish(client_width_, controls_height());
        }
        ImGui::End();
    }

    void commit_requested_pose()
    {
        if (requested_pose_ != current_pose_)
        {
            current_pose_ = requested_pose_;
            frame_dirty_ = true;
        }
    }

    void clear_capture_overrides()
    {
        view_pose_override_.reset();
        if (capture_camera_active_)
        {
            if (pending_render_.valid())
                static_cast<void>(pending_render_.get());
            configuration_.capture_camera_setter(std::nullopt);
            capture_camera_active_ = false;
            ++render_epoch_;
            frame_dirty_ = true;
        }
        if (scene_pose_override_.has_value())
        {
            scene_pose_override_.reset();
            ++render_epoch_;
            frame_dirty_ = true;
        }
    }

    using RenderKey = std::tuple<RenderMode, bool, bool, bool, bool, RenderScale, std::optional<std::size_t>, bool>;

    RenderKey render_key() const
    {
        return {
            state_.mode,
            state_.legacy_material,
            state_.brushes_enabled,
            state_.entities_enabled,
            state_.external_bsp_models,
            state_.scale,
            scene_pose_override_,
            state_.particles_enabled
        };
    }

    void refresh_render_if_dirty()
    {
        if (state_.scale == RenderScale::X3Warp && !state_.paused)
        {
            if (pending_render_.valid() &&
                pending_render_.wait_for(std::chrono::seconds(0)) == std::future_status::ready)
            {
                auto render = pending_render_.get();
                if (pending_key_ == render_key() && pending_loop_ == loop_ && pending_epoch_ == render_epoch_)
                {
                    accept_render(std::move(render), pending_pose_, pending_key_);
                    ++frame_generation_;
                    pixels_dirty_ = true;
                }
            }
            if (!pending_render_.valid() &&
                (frame_dirty_ || rendered_pose_ != current_pose_ || rendered_key_ != render_key()))
            {
                pending_pose_ = current_pose_;
                pending_key_ = render_key();
                pending_loop_ = loop_;
                pending_epoch_ = render_epoch_;
                pending_render_ = std::async(
                    std::launch::async,
                    [this,
                     pose = current_pose_,
                     scene = scene_pose_override_.value_or(current_pose_),
                     mode = state_.mode,
                     legacy = state_.legacy_material,
                     brushes = state_.brushes_enabled,
                     entities = state_.entities_enabled,
                     external = state_.external_bsp_models,
                     particles = state_.particles_enabled,
                     scale = state_.scale] {
                        const RenderViewportScope viewport(scale);
                        return render_pose_(pose, scene, mode, legacy, brushes, entities, external, particles);
                    }
                );
            }
            return;
        }
        if (pending_render_.valid())
            pending_render_.get();
        if (!frame_dirty_ && rendered_key_ == render_key())
            return;
        render_current_pose();
        ++frame_generation_;
        pixels_dirty_ = true;
    }

    void accept_render(LiveRenderResult render, std::size_t pose, const RenderKey& key)
    {
        current_indices_ = compact_viewport(render.indices, std::get<RenderScale>(key));
        current_alias_inspection_ = std::move(render.alias_inspection);
        current_surface_inspection_ = std::move(render.surface_inspection);
        current_external_bsp_inspection_ = std::move(render.external_bsp_inspection);
        rendered_pose_ = pose;
        rendered_scene_pose_ = std::get<std::optional<std::size_t>>(key).value_or(pose);
        rendered_loop_ = loop_;
        rendered_key_ = key;
        rendered_view_ = listener_at_pose_(pose);
    }

    void render_current_pose()
    {
        const RenderViewportScope viewport(state_.scale);
        accept_render(
            render_pose_(
                current_pose_,
                scene_pose_override_.value_or(current_pose_),
                state_.mode,
                state_.legacy_material,
                state_.brushes_enabled,
                state_.entities_enabled,
                state_.external_bsp_models,
                state_.particles_enabled
            ),
            current_pose_,
            render_key()
        );
    }

    std::size_t presentation_pose() const
    {
        if (view_pose_override_.has_value())
            return *view_pose_override_;
        if (state_.scale == RenderScale::X3Warp && playback_schedule_ == PlaybackSchedule::OrderedTimed)
        {
            // Read the newest recorded source sample due between ordered images.
            // Pausing freezes this clock; the image schedule still visits every row.
            const auto ahead =
                static_cast<std::size_t>(std::max(0.0, ordered_wall_seconds_) * configuration_.ordered_source_rate_hz);
            return current_pose_ + std::min(ahead, cameras_.size() - 1 - current_pose_);
        }
        return current_pose_;
    }

    void upload_pixels_if_dirty()
    {
        // A scale change keeps the old image until a matching render completes.
        const auto image_scale = std::get<RenderScale>(rendered_key_);
        if (pixels_dirty_)
            update_live_pixels(state_, current_indices_, world_);
        const auto view_pose = presentation_pose();
        const auto view =
            configuration_.camera_at_pose ? configuration_.camera_at_pose(view_pose) : listener_at_pose_(view_pose);
        const bool enabled =
            state_.scale == RenderScale::X3Warp && image_scale != RenderScale::X2 && rendered_loop_ == loop_;
        const bool use_projective = enabled && warp_settings_.projective;
        const bool use_hdma = enabled && warp_settings_.hdma;
        const auto warp =
            enabled && !use_projective && !use_hdma ? camera_warp(view, rendered_view_) : PresentationWarp{};
        const auto hdma = use_hdma ? hdma_camera_warp(view, rendered_view_, warp_settings_) : HdmaWarp{};
        const auto projective =
            use_projective ? projective_camera_warp(view, rendered_view_, warp_settings_.depth) : ProjectiveWarp{};
        const bool changed =
            warp.x != applied_warp_.x || warp.y != applied_warp_.y || warp.zoom != applied_warp_.zoom ||
            use_projective != applied_projective_enabled_ || projective != applied_projective_ || hdma != applied_hdma_;
        applied_warp_ = warp;
        applied_projective_ = projective;
        applied_projective_enabled_ = use_projective;
        applied_hdma_ = hdma;
        if (pixels_dirty_ || changed)
        {
            if (image_scale != RenderScale::X2)
                state_.display_pixels =
                    use_hdma ? present_hdma_x3(state_.pixels, hdma)
                    : use_projective
                        ? present_projective_x3(state_.pixels, projective)
                        : present_x3(state_.pixels, warp);
            upload_texture(image_scale);
            ++display_generation_;
        }
        state_.presentation = Json{
            {"scale", render_scale_name(state_.scale)},
            {"imageScale", render_scale_name(image_scale)},
            {"referenceProjection", image_scale == RenderScale::X2 ? "snes-x2-center64-v1" : kX3ProjectionContract},
            {"imageCenter", image_scale == RenderScale::X2 ? Json::array({64, 56}) : Json::array({kX3CenterX, 37})},
            {"imageFocal", image_scale == RenderScale::X2 ? 96 : 64},
            {"warpModel", warp_model_name(warp_settings_)},
            {"warpDepth", warp_settings_.depth},
            {"warpBands", warp_settings_.bands},
            {"inverseDepthProfileQ16", warp_settings_.inverse_depth_profile},
            {"hdma", hdma_warp_json(hdma)},
            {"projectiveActive", use_projective},
            {"inverseHomography", projective.inverse},
            {"projectiveValid", projective.valid},
            {"renderedPose", rendered_pose_},
            {"renderedScenePose", rendered_scene_pose_},
            {"scenePoseControl", configuration_.scene_pose_control},
            {"captureCameraControl", static_cast<bool>(configuration_.capture_camera_setter)},
            {"captureCameraActive", capture_camera_active_},
            {"scenePoseFrozen", scene_pose_override_.has_value()},
            {"viewPose", view_pose},
            {"displayGeneration", display_generation_},
            {"renderPending", pending_render_.valid()},
            {"interpolated", false},
            {"renderedCamera", warp_camera_json(rendered_view_)},
            {"viewCamera", warp_camera_json(view)},
            {"shiftX", warp.x},
            {"shiftY", warp.y},
            {"zoom", warp.zoom}
        };
    }

    void upload_texture(RenderScale scale)
    {
        const int width = scale == RenderScale::X2 ? 128 : 256;
        const int height = scale == RenderScale::X2 ? 112 : 224;
        if (texture_ == nullptr || texture_width_ != width || texture_height_ != height)
        {
            if (texture_ != nullptr)
                SDL_DestroyTexture(texture_);
            texture_ =
                SDL_CreateTexture(renderer_, SDL_PIXELFORMAT_XRGB8888, SDL_TEXTUREACCESS_STREAMING, width, height);
            if (texture_ == nullptr)
                fail(std::string("cannot create SDL3 texture: ") + SDL_GetError());
            SDL_SetTextureScaleMode(texture_, SDL_SCALEMODE_NEAREST);
            texture_width_ = width;
            texture_height_ = height;
        }
        const auto& pixels = scale == RenderScale::X2 ? state_.pixels : state_.display_pixels;
        if (!SDL_UpdateTexture(texture_, nullptr, pixels.data(), width * static_cast<int>(sizeof(std::uint32_t))))
            fail(std::string("cannot upload SDL3 texture: ") + SDL_GetError());
    }

    void synchronize_audio()
    {
        audio_->synchronize(
            playback_seconds_,
            loop_,
            listener_at_pose_(current_pose_),
            state_.sound_enabled,
            state_.sound_volume,
            audio_timing_compatible(),
            audio_timing_reason(),
            state_.paused
        );
        current_audio_inspection_ = audio_->inspection();
    }

    [[nodiscard]] bool audio_timing_compatible() const
    {
        if (playback_schedule_ == PlaybackSchedule::NewestDue)
        {
            return state_.playback_speed == PlaybackSpeed::Realtime;
        }
        return playback_schedule_ == PlaybackSchedule::OrderedTimed && presentation_rate_hz_ == 3;
    }

    [[nodiscard]] std::string audio_timing_reason() const
    {
        if (playback_schedule_ == PlaybackSchedule::OrderedRenderCompletion)
        {
            return "suppressed for render-completion pacing";
        }
        if (playback_schedule_ == PlaybackSchedule::OrderedTimed)
        {
            return "suppressed for diagnostic ordered rate";
        }
        return "suppressed for non-realtime source speed";
    }

    void update_window_title()
    {
        std::ostringstream title;
        title << "E1M3 demo1 - C++ reference | pose " << (current_pose_ + 1) << '/' << cameras_.size();
        title << " | " << configuration_.playback_contract;
        append_playback_title(title);
        append_render_title(title);
        append_feature_title(title, configuration_.brush_control, "dynamic brushes", state_.brushes_enabled);
        append_feature_title(title, configuration_.entity_control, "entities", state_.entities_enabled);
        append_feature_title(
            title,
            configuration_.external_bsp_model_control,
            "source BSP models",
            state_.external_bsp_models
        );
        append_audio_title(title);
        append_feature_title(title, configuration_.particle_control, "particles", state_.particles_enabled);
        title << " | loop " << loop_;
        if (state_.paused)
        {
            title << " | PAUSED";
        }
        title << " | Slider: seek  Space: pause  Esc: close";
        SDL_SetWindowTitle(window_, title.str().c_str());
    }

    void append_playback_title(std::ostringstream& title) const
    {
        if (configuration_.playback_speed_control)
        {
            title << " | " << kPlaybackSpeedLabels.at(static_cast<std::size_t>(state_.playback_speed));
        }
        else if (ordered_pace_control())
        {
            title << " | "
                  << (playback_schedule_ == PlaybackSchedule::OrderedTimed
                          ? "Timed " + std::to_string(presentation_rate_hz_) + " Hz"
                          : "Fast");
        }
    }

    void append_render_title(std::ostringstream& title) const
    {
        if (state_.legacy_material)
        {
            title << " | legacy 27-color material experiment";
        }
        else
        {
            title << " | " << render_mode_name(state_.mode);
            if (!state_.mode.textures)
            {
                title << " | 64-color neutral BGR555 ramp";
            }
            title << " | static SNES BGR555 palette";
        }
    }

    void append_feature_title(std::ostringstream& title, bool visible, std::string_view label, bool enabled) const
    {
        if (!visible)
        {
            return;
        }
        title << " | " << label << ' ' << feature_title_state(enabled);
    }

    [[nodiscard]] const char* feature_title_state(bool enabled) const
    {
        return enabled ? "ON" : "OFF";
    }

    void append_audio_title(std::ostringstream& title) const
    {
        if (configuration_.sound_assets == nullptr)
        {
            return;
        }
        title << " | sound "
              << (current_audio_inspection_.at("effective").get<bool>()
                      ? "ON"
                      : current_audio_inspection_.at("reason").get<std::string>());
    }

    void present(const std::optional<std::string>& window_capture_path)
    {
        SDL_SetRenderDrawColor(renderer_, 0, 0, 0, 255);
        SDL_RenderClear(renderer_);
        const int scale = std::max(1, std::min(client_width_ / texture_width_, viewport_height_ / texture_height_));
        const float output_width = static_cast<float>(texture_width_ * scale);
        const float output_height = static_cast<float>(texture_height_ * scale);
        const SDL_FRect destination{
            (static_cast<float>(client_width_) - output_width) * 0.5F,
            (static_cast<float>(viewport_height_) - output_height) * 0.5F,
            output_width,
            output_height
        };
        SDL_RenderTexture(renderer_, texture_, nullptr, &destination);
        ImGui::Render();
        ImGui_ImplSDLRenderer3_RenderDrawData(ImGui::GetDrawData(), renderer_);
        if (window_capture_path.has_value())
        {
            instrumentation_->capture_window(renderer_, *window_capture_path, current_pose_);
        }
        SDL_RenderPresent(renderer_);
    }

    void publish_instrumentation()
    {
        instrumentation_->publish(
            rendered_pose_,
            cameras_.size(),
            loop_,
            state_.paused,
            playback_schedule_,
            presentation_rate_hz_,
            state_,
            frame_generation_,
            current_indices_,
            std::move(instrumentation_control_layout_),
            current_alias_inspection_,
            current_surface_inspection_,
            current_external_bsp_inspection_,
            std::move(current_audio_inspection_)
        );
    }

    void mark_ordered_frame_presented()
    {
        if (playback_schedule_ == PlaybackSchedule::OrderedTimed ||
            playback_schedule_ == PlaybackSchedule::OrderedRenderCompletion)
        {
            ordered_frame_presented_ = rendered_pose_ == current_pose_ && rendered_key_ == render_key();
        }
    }

    void shutdown_presentation() noexcept
    {
        if (pending_render_.valid())
            pending_render_.wait();
        audio_.reset();
        if (imgui_renderer_initialized_)
        {
            ImGui_ImplSDLRenderer3_Shutdown();
            imgui_renderer_initialized_ = false;
        }
        if (imgui_sdl_initialized_)
        {
            ImGui_ImplSDL3_Shutdown();
            imgui_sdl_initialized_ = false;
        }
        if (imgui_context_initialized_)
        {
            ImGui::DestroyContext();
            imgui_context_initialized_ = false;
        }
        if (texture_ != nullptr)
        {
            SDL_DestroyTexture(texture_);
            texture_ = nullptr;
        }
        if (renderer_ != nullptr)
        {
            SDL_DestroyRenderer(renderer_);
            renderer_ = nullptr;
        }
        if (window_ != nullptr)
        {
            SDL_DestroyWindow(window_);
            window_ = nullptr;
        }
        if (sdl_initialized_)
        {
            SDL_Quit();
            sdl_initialized_ = false;
        }
    }

    const SourceWorld& world_;
    const std::vector<CameraType>& cameras_;
    double duration_seconds_;
    PoseAtTime pose_at_time_;
    TimeAtPose time_at_pose_;
    ListenerAtPose listener_at_pose_;
    RenderPose render_pose_;
    LiveDemoConfiguration configuration_;
    PlaybackSchedule playback_schedule_;
    int presentation_rate_hz_;
    std::unique_ptr<ReferenceInstrumentationServer> instrumentation_;
    std::unique_ptr<QuakeAudioSession> audio_;
    LiveWindowState state_;
    std::future<LiveRenderResult> pending_render_;
    RenderKey pending_key_, rendered_key_;
    std::size_t pending_pose_{}, rendered_pose_{};
    std::optional<std::size_t> view_pose_override_;
    std::optional<std::size_t> scene_pose_override_;
    bool capture_camera_active_{};
    std::size_t rendered_scene_pose_{};
    std::uint64_t pending_loop_{}, rendered_loop_{}, pending_epoch_{}, render_epoch_{}, display_generation_{};
    ViewTransform rendered_view_{};
    PresentationWarp applied_warp_{};
    WarpSettings warp_settings_;
    ProjectiveWarp applied_projective_;
    HdmaWarp applied_hdma_;
    bool applied_projective_enabled_{};
    int texture_width_{}, texture_height_{};
    std::vector<std::uint8_t> current_indices_;
    Json current_alias_inspection_;
    Json current_surface_inspection_;
    Json current_external_bsp_inspection_;
    Json current_audio_inspection_;
    Json instrumentation_control_layout_;
    std::optional<ReferenceControlLayout> control_layout_;
    Clock::time_point previous_tick_;
    double playback_seconds_{};
    double ordered_wall_seconds_{};
    std::uint64_t frame_generation_{1};
    std::size_t current_pose_{};
    std::size_t requested_pose_{};
    std::uint64_t loop_{1};
    bool ordered_frame_presented_{};
    bool running_{true};
    bool frame_dirty_{};
    bool pixels_dirty_{};
    int client_width_{};
    int viewport_height_{};
    SDL_Window* window_{};
    SDL_Renderer* renderer_{};
    SDL_Texture* texture_{};
    bool sdl_initialized_{};
    bool imgui_context_initialized_{};
    bool imgui_sdl_initialized_{};
    bool imgui_renderer_initialized_{};
};

template <typename CameraType, typename PoseAtTime, typename TimeAtPose, typename ListenerAtPose, typename RenderPose>
int run_live_demo(
    const SourceWorld& world,
    const std::vector<CameraType>& cameras,
    double duration_seconds,
    PoseAtTime pose_at_time,
    TimeAtPose time_at_pose,
    ListenerAtPose listener_at_pose,
    RenderPose render_pose,
    LiveDemoConfiguration configuration
)
{
    validate_live_demo(cameras, duration_seconds, configuration);
    return LiveDemoSession<CameraType, PoseAtTime, TimeAtPose, ListenerAtPose, RenderPose>(
               world,
               cameras,
               duration_seconds,
               std::move(pose_at_time),
               std::move(time_at_pose),
               std::move(listener_at_pose),
               std::move(render_pose),
               std::move(configuration)
    )
        .run();
}

int run_source_realtime_demo(
    const SourceWorld& world,
    const Bvh& bvh,
    const BrushScene& brush_scene,
    const BrushReplay& brush_replay,
    const AliasAssets& alias_assets,
    const fs::path& track_path,
    bool flat,
    RenderMode initial_mode,
    bool initial_legacy_material,
    PlaybackSpeed initial_playback_speed,
    bool brushes_enabled,
    bool entities_enabled,
    const ExternalBspScene* external_scene,
    const ExternalBspReplay* external_replay,
    bool external_bsp_models_enabled,
    const QuakeSoundAssets* sound_assets,
    bool sound_enabled,
    float sound_volume,
    ReferenceInstrumentationConfig instrumentation,
    const ParticleReplay* particles = nullptr,
    bool particles_enabled = false
);

int run_packed_realtime_demo(
    const SourceWorld& world,
    const Bvh& bvh,
    const fs::path& track_path,
    const fs::path& timing_path,
    bool flat,
    RenderMode initial_mode,
    bool initial_legacy_material,
    PlaybackSpeed initial_playback_speed,
    ReferenceInstrumentationConfig instrumentation
);

fs::path with_suffix(const fs::path& prefix, std::string_view suffix);

} // namespace quake_bsp_reference
