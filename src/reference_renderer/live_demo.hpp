#pragma once

#include "world.hpp"
#include "geometry.hpp"
#include "instrumentation.hpp"
#include "brushes.hpp"
#include "audio.hpp"
#include "external_models.hpp"
#include "aliases.hpp"
#include "textured_live.hpp"

namespace quake_bsp_reference {

struct LiveDemoConfiguration
{
    std::string playback_contract;
    RenderMode initial_mode;
    bool initial_legacy_material{};
    PlaybackSpeed initial_playback_speed{PlaybackSpeed::Realtime};
    bool playback_speed_control{};
    PlaybackSchedule playback_schedule{PlaybackSchedule::NewestDue};
    int initial_presentation_rate_hz{2};
    int ordered_source_rate_hz{20};
    ReferenceInstrumentationConfig instrumentation_config;
    const QuakeSoundAssets* sound_assets{};
    bool initial_sound_enabled{};
    float initial_sound_volume{};
    bool legacy_material_control{};
    bool brush_control{};
    bool entity_control{};
    bool external_bsp_model_control{};
    bool initial_brushes{};
    bool initial_entities{};
    bool initial_external_bsp_models{};
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
    if (configuration.initial_presentation_rate_hz != 2 && configuration.initial_presentation_rate_hz != 20)
    {
        fail("ordered playback rate must be 2 or 20 Hz");
    }
    if (configuration.playback_schedule != PlaybackSchedule::NewestDue &&
        (configuration.ordered_source_rate_hz < configuration.initial_presentation_rate_hz ||
         configuration.ordered_source_rate_hz % configuration.initial_presentation_rate_hz != 0 ||
         configuration.ordered_source_rate_hz % 2 != 0 || configuration.ordered_source_rate_hz % 20 != 0))
    {
        fail("ordered playback source rate must support exact 2 and 20 Hz strides");
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
        state_.legacy_material = configuration_.initial_legacy_material;
        state_.playback_speed = configuration_.initial_playback_speed;
        state_.brushes_enabled = configuration_.initial_brushes;
        state_.entities_enabled = configuration_.initial_entities;
        state_.external_bsp_models = configuration_.initial_external_bsp_models;
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
            (kLogicalHeight * 4) + kPlaybackControlsHeight,
            SDL_WINDOW_RESIZABLE
        );
        if (window_ == nullptr)
        {
            fail(std::string("cannot create SDL3 window: ") + SDL_GetError());
        }
        SDL_SetWindowMinimumSize(window_, kMinimumLiveClientWidth, kLogicalHeight + kPlaybackControlsHeight);
        renderer_ = SDL_CreateRenderer(window_, nullptr);
        if (renderer_ == nullptr)
        {
            fail(std::string("cannot create SDL3 renderer: ") + SDL_GetError());
        }
        SDL_SetRenderVSync(renderer_, 1);
        texture_ = SDL_CreateTexture(
            renderer_,
            SDL_PIXELFORMAT_XRGB8888,
            SDL_TEXTUREACCESS_STREAMING,
            kLogicalWidth,
            kLogicalHeight
        );
        if (texture_ == nullptr)
        {
            fail(std::string("cannot create SDL3 texture: ") + SDL_GetError());
        }
        SDL_SetTextureScaleMode(texture_, SDL_SCALEMODE_NEAREST);
        upload_texture();

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
                (kLogicalHeight * (kMinimumLiveClientWidth / kLogicalWidth)) + kPlaybackControlsHeight
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
        if (commands.sound_volume.has_value())
        {
            state_.sound_volume = *commands.sound_volume;
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
        viewport_height_ = std::max(0, client_height - kPlaybackControlsHeight);
        ImGui::SetNextWindowPos(ImVec2{0.0F, static_cast<float>(viewport_height_)});
        ImGui::SetNextWindowSize(
            ImVec2{static_cast<float>(client_width_), static_cast<float>(kPlaybackControlsHeight)}
        );
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

    void draw_controls()
    {
        draw_playback_controls();
        draw_rendering_controls();
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
        int selected_rate = presentation_rate_hz_ == 2 ? 0 : 1;
        if (ImGui::Combo(
                "Rate",
                &selected_rate,
                kOrderedRateLabels.data(),
                static_cast<int>(kOrderedRateLabels.size())
            ))
        {
            presentation_rate_hz_ = selected_rate == 0 ? 2 : 20;
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
               configuration_.external_bsp_model_control || configuration_.legacy_material_control;
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
        draw_feature_toggle(
            configuration_.entity_control,
            "MDL/SPR entities",
            state_.entities_enabled,
            "mdlEntities",
            present
        );
        draw_feature_toggle(
            configuration_.external_bsp_model_control,
            "External BSP models",
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
            instrumentation_control_layout_ = control_layout_->finish(client_width_, kPlaybackControlsHeight);
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

    void refresh_render_if_dirty()
    {
        if (!frame_dirty_)
        {
            return;
        }
        render_current_pose();
        ++frame_generation_;
        pixels_dirty_ = true;
    }

    void render_current_pose()
    {
        auto render = render_pose_(
            current_pose_,
            state_.mode,
            state_.legacy_material,
            state_.brushes_enabled,
            state_.entities_enabled,
            state_.external_bsp_models
        );
        current_indices_ = std::move(render.indices);
        current_alias_inspection_ = std::move(render.alias_inspection);
        current_surface_inspection_ = std::move(render.surface_inspection);
        current_external_bsp_inspection_ = std::move(render.external_bsp_inspection);
        if (current_indices_.size() != kLogicalPixels)
        {
            fail("live frame is missing its selected color layer");
        }
    }

    void upload_pixels_if_dirty()
    {
        if (!pixels_dirty_)
        {
            return;
        }
        update_live_pixels(state_, current_indices_, world_);
        upload_texture();
    }

    void upload_texture()
    {
        if (!SDL_UpdateTexture(
                texture_,
                nullptr,
                state_.pixels.data(),
                kLogicalWidth * static_cast<int>(sizeof(std::uint32_t))
            ))
        {
            fail(std::string("cannot upload SDL3 texture: ") + SDL_GetError());
        }
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
        return playback_schedule_ == PlaybackSchedule::OrderedTimed && presentation_rate_hz_ == 2;
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
        append_feature_title(title, configuration_.entity_control, "MDL/SPR entities", state_.entities_enabled);
        append_feature_title(
            title,
            configuration_.external_bsp_model_control,
            "external BSP models",
            state_.external_bsp_models
        );
        append_audio_title(title);
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
        const int scale = std::max(1, std::min(client_width_ / kLogicalWidth, viewport_height_ / kLogicalHeight));
        const float output_width = static_cast<float>(kLogicalWidth * scale);
        const float output_height = static_cast<float>(kLogicalHeight * scale);
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
            current_pose_,
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
            ordered_frame_presented_ = true;
        }
    }

    void shutdown_presentation() noexcept
    {
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
    ReferenceInstrumentationConfig instrumentation
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
