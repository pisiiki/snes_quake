#include "gameplay_application.hpp"
#include "audio.hpp"
#include "gameplay_render.hpp"
#include "gameplay_script.hpp"
#include "gameplay_tape.hpp"
#include "viewport.hpp"

namespace quake_bsp_reference {
namespace {
std::vector<GameplayAssets> load_maps(const std::vector<fs::path>& inputs)
{
    std::vector<GameplayAssets> result;
    for (const auto& path : inputs)
    {
        const auto bytes = read_file(path);
        const auto value = Json::parse(bytes.begin(), bytes.end());
        if (value.value("schema", "") == "quake-gameplay-mapset-v1")
        {
            for (const auto& entry : value.at("maps"))
            {
                const auto manifest = path.parent_path() / entry.at("manifest").get<std::string>();
                if (entry.contains("bytes") && fs::file_size(manifest) != entry.at("bytes").get<std::uintmax_t>())
                    fail("gameplay mapset manifest size differs");
                auto assets = load_gameplay_assets(manifest);
                if (assets.map != entry.at("map").get<std::string>())
                    fail("gameplay mapset manifest names another map");
                result.push_back(std::move(assets));
            }
        }
        else
            result.push_back(load_gameplay_assets(path));
    }
    if (result.empty())
        fail("gameplay asset set is empty");
    return result;
}

void write_json(const fs::path& path, const Json& value)
{
    if (!path.parent_path().empty())
        fs::create_directories(path.parent_path());
    const auto text = value.dump(2) + "\n";
    write_file(path, {reinterpret_cast<const std::uint8_t*>(text.data()), text.size()});
}

std::string safe_label(std::string_view label)
{
    std::string result;
    for (const char byte : label)
        result.push_back(
            (byte >= 'a' && byte <= 'z') || (byte >= 'A' && byte <= 'Z') || (byte >= '0' && byte <= '9') ||
                    byte == '-' || byte == '_'
                ? byte
                : '-'
        );
    return result;
}

Json capture_artifacts(
    const fs::path& prefix,
    std::size_t index,
    std::string_view label,
    const GameplayRenderSnapshot& snapshot,
    const GameplayFrame& frame
)
{
    if (prefix.empty())
        return {{"rendered", true}, {"pixels", frame.composite.size()}, {"inspection", frame.inspection}};
    const fs::path stem(prefix.string() + "-" + std::to_string(index) + "-" + safe_label(label));
    if (!stem.parent_path().empty())
        fs::create_directories(stem.parent_path());
    const fs::path world(stem.string() + ".world.idx"), composite(stem.string() + ".final.idx");
    write_file(world, frame.world);
    write_file(composite, frame.composite);
    const fs::path visible(stem.string() + ".visible.bgr555");
    if (!frame.visible_x3_bgr555.empty())
        write_file(visible, frame.visible_x3_bgr555);
    if (!frame.pickup_text_mask.empty())
        write_file(stem.string() + ".notify.1bpp", frame.pickup_text_mask);
    const fs::path state(stem.string() + ".snapshot.json");
    write_json(state, gameplay_snapshot_json(snapshot));
    Json result = {
        {"rendered", true},
        {"world", world.string()},
        {"composite", composite.string()},
        {"snapshot", state.string()},
        {"pixels", frame.composite.size()},
        {"inspection", frame.inspection}
    };
    if (!frame.visible_x3_bgr555.empty())
        result["visibleComposite"] = visible.string();
    return result;
}

std::vector<GameplayTape> load_tapes(const fs::path& directory, const std::vector<std::string>& maps)
{
    std::vector<GameplayTape> tapes;
    if (!directory.empty())
        for (const auto& map : maps)
        {
            const auto path = directory / (map + "-gameplay-route.json");
            if (fs::exists(path))
                tapes.push_back(read_gameplay_tape(path, map));
        }
    return tapes;
}

std::string tape_name(const GameplayTape& tape)
{
    if (tape.path.filename().string().ends_with("-gameplay-route.json"))
        return "Benchmark route";
    return tape.path.stem().stem().string();
}

constexpr std::array kGameplayTechniques{4U, 2U, 7U, 3U};
constexpr std::array kGameplayTechniqueNames{"Textures + lightmaps", "Textures", "Lightmaps", "Baked face colors"};
constexpr std::array kGameplaySkillNames{"Easy", "Normal", "Hard", "Nightmare"};

class PlayableWindow
{
  public:
    PlayableWindow(GameplaySession& session, GameplayRenderer& renderer, const GameplayApplicationOptions& options,
                   std::vector<std::string> map_names, bool has_face_colors) :
    session_(session),
    renderer_(renderer),
    options_(options),
    instrumentation_(options.instrumentation),
    map_names_(std::move(map_names)),
    tapes_(load_tapes(options.tape_dir, map_names_)),
    recording_dir_(options.tape_record_dir.empty() ? fs::path("gameplay-tapes") : options.tape_record_dir),
    selected_map_(options.initial_map),
    has_face_colors_(has_face_colors),
    sound_enabled_(!options.no_sound),
    sound_volume_(options.sound_volume)
    {
        load_recordings();
        SDL_SetMainReady();
        if (!SDL_Init(SDL_INIT_VIDEO))
            fail(std::string("cannot initialize gameplay SDL: ") + SDL_GetError());
        initialized_ = true;
        window_ = SDL_CreateWindow("SNES Quake independent gameplay", 768, 672, SDL_WINDOW_RESIZABLE);
        if (!window_)
            fail(std::string("cannot create gameplay window: ") + SDL_GetError());
        sdl_renderer_ = SDL_CreateRenderer(window_, nullptr);
        if (!sdl_renderer_)
            fail(std::string("cannot create gameplay renderer: ") + SDL_GetError());
        SDL_SetRenderVSync(sdl_renderer_, 1);
        texture_ = SDL_CreateTexture(
            sdl_renderer_,
            SDL_PIXELFORMAT_XRGB8888,
            SDL_TEXTUREACCESS_STREAMING,
            kLogicalWidth,
            kLogicalHeight
        );
        if (!texture_)
            fail(std::string("cannot create gameplay texture: ") + SDL_GetError());
        SDL_SetTextureScaleMode(texture_, SDL_SCALEMODE_NEAREST);
        IMGUI_CHECKVERSION();
        ImGui::CreateContext();
        imgui_ = true;
        ImGui::GetIO().IniFilename = nullptr;
        ImGui::StyleColorsDark();
        if (!ImGui_ImplSDL3_InitForSDLRenderer(window_, sdl_renderer_))
            fail("cannot initialize gameplay ImGui SDL backend");
        imgui_sdl_ = true;
        if (!ImGui_ImplSDLRenderer3_Init(sdl_renderer_))
            fail("cannot initialize gameplay ImGui renderer backend");
        imgui_renderer_ = true;
        audio_pak_ = read_file(options_.pak);
        audio_ = std::make_unique<QuakeAudioSession>(std::span<const std::uint8_t>(audio_pak_));
        session_.set_live_sound(sound_enabled_);
    }

    ~PlayableWindow()
    {
        audio_.reset();
        if (window_)
            SDL_SetWindowRelativeMouseMode(window_, false);
        if (imgui_renderer_)
            ImGui_ImplSDLRenderer3_Shutdown();
        if (imgui_sdl_)
            ImGui_ImplSDL3_Shutdown();
        if (imgui_)
            ImGui::DestroyContext();
        if (texture_)
            SDL_DestroyTexture(texture_);
        if (sdl_renderer_)
            SDL_DestroyRenderer(sdl_renderer_);
        if (window_)
            SDL_DestroyWindow(window_);
        if (initialized_)
            SDL_Quit();
    }

    int run()
    {
        auto previous = std::chrono::steady_clock::now();
        double accumulated = 0.0;
        constexpr double tick_seconds = 1.0 / 60.0988118623484;
        while (running_)
        {
            const auto commands = instrumentation_.take_commands();
            if (commands.shutdown)
                break;
            if (commands.paused)
                paused_ = *commands.paused;
            if (commands.sound_enabled && sound_enabled_ != *commands.sound_enabled)
            {
                sound_enabled_ = *commands.sound_enabled;
                session_.set_live_sound(sound_enabled_);
            }
            if (commands.sound_volume)
                sound_volume_ = *commands.sound_volume;
            for (auto event : commands.input_events)
            {
                if (event.type == SDL_EVENT_KEY_DOWN || event.type == SDL_EVENT_KEY_UP)
                {
                    event.key.windowID = SDL_GetWindowID(window_);
                    event.key.key = SDL_GetKeyFromScancode(event.key.scancode, event.key.mod, false);
                }
                SDL_PushEvent(&event);
            }
            events();
            if (!running_)
                break;
            for (const auto& request : commands.gameplay_requests)
            {
                completed_command_ = request.at("id").get<std::uint64_t>();
                if (recording_)
                {
                    last_command_ = {{"passed", false}, {"error", "stop recording before running a gameplay script"}};
                    continue;
                }
                if (playing_tape_)
                    stop_tape();
                last_tape_.reset();
                session_.set_live_sound(false);
                try
                {
                    const auto result = run_gameplay_script(
                        session_,
                        request.at("script"),
                        [&](const GameplayRenderSnapshot& snapshot, std::size_t index, std::string_view label) {
                            last_frame_ = renderer_.render(snapshot);
                            snapshot_ = snapshot;
                            dirty_ = false;
                            ++generation_;
                            return capture_artifacts(options_.output_prefix, index, label, snapshot, last_frame_);
                        }
                    );
                    last_command_ = {{"passed", true}, {"states", result.at("states")}};
                    if (result.at("states").empty() || !result.at("states").back().contains("renderSnapshot"))
                        dirty_ = true;
                }
                catch (const std::exception& error)
                {
                    last_command_ = {{"passed", false}, {"error", error.what()}};
                    dirty_ = true;
                }
                session_.set_live_sound(sound_enabled_);
                paused_ = true;
            }
            ImGui_ImplSDLRenderer3_NewFrame();
            ImGui_ImplSDL3_NewFrame();
            ImGui::NewFrame();
            controls();
            const auto now = std::chrono::steady_clock::now();
            const auto elapsed = std::chrono::duration<double>(now - previous).count();
            previous = now;
            if (paused_ || std::exchange(reset_clock_, false))
                accumulated = 0.0;
            else
            {
                accumulated += std::clamp(elapsed, 0.0, 0.25);
                while (!paused_ && !reset_clock_ && accumulated >= tick_seconds)
                {
                    tick();
                    accumulated -= tick_seconds;
                }
            }
            if (dirty_)
            {
                snapshot_ = session_.render_snapshot();
                last_frame_ = renderer_.render(snapshot_);
                dirty_ = false;
                ++generation_;
            }
            update_audio();
            if (!SDL_UpdateTexture(texture_, nullptr, last_frame_.pixels.data(), kLogicalWidth * sizeof(std::uint32_t)))
                fail(std::string("cannot upload gameplay frame: ") + SDL_GetError());
            int width = 0, height = 0;
            SDL_GetWindowSize(window_, &width, &height);
            const auto available = std::max(1, height - controls_height);
            const auto& viewport = last_frame_.inspection.at("viewport");
            const bool x3 = last_frame_.inspection.at("renderScale") == 3;
            const float source_width = viewport.at("width").get<float>();
            const float source_height = x3 ? kPlayableWorldHeight / 3.0F : viewport.at("height").get<float>();
            const float scale =
                std::min(width / source_width, available / source_height);
            const SDL_FRect destination{
                (width - source_width * scale) * 0.5F,
                (available - source_height * scale) * 0.5F,
                source_width * scale,
                source_height * scale
            };
            SDL_SetRenderDrawColor(sdl_renderer_, 0, 0, 0, 255);
            SDL_RenderClear(sdl_renderer_);
            const SDL_FRect source{0, 0, source_width, source_height};
            // X3's backing plane is canonical. Mirror only its on-screen world.
            const auto flip = x3 ? SDL_FLIP_HORIZONTAL : SDL_FLIP_NONE;
            SDL_RenderTextureRotated(sdl_renderer_, texture_, &source, &destination, 0.0, nullptr, flip);
            draw_pickup_text(destination);
            draw_centerprint(destination);
            ImGui::Render();
            ImGui_ImplSDLRenderer3_RenderDrawData(ImGui::GetDrawData(), sdl_renderer_);
            SDL_RenderPresent(sdl_renderer_);
            if (commands.window_capture_path)
                instrumentation_.capture_window(sdl_renderer_, *commands.window_capture_path, snapshot_.video_tick);
            publish(width);
            SDL_Delay(1);
        }
        if (recorded_ && !finish_recording())
            fail(recording_error_);
        if (!options_.report.empty())
            write_json(
                options_.report,
                {{"schema", "quake-gameplay-live-report-v1"}, {"passed", true}, {"finalState", session_.state()}}
            );
        return 0;
    }

  private:
    void update_audio()
    {
        const auto generation = session_.sound_generation();
        if (generation != audio_generation_)
        {
            audio_->reset_live();
            audio_generation_ = generation;
        }
        audio_->synchronize(0.0, 0, source_view_transform(snapshot_.source_camera),
                            sound_enabled_, sound_volume_, true, {}, paused_);
        for (const auto& event : session_.take_sounds())
            audio_->play_live(event.name, event.entity, event.channel, event.volume, event.attenuation, event.origin);
    }

    void draw_pickup_text(const SDL_FRect& viewport)
    {
        const auto& mask = last_frame_.pickup_text_mask;
        if (mask.empty())
            return;
        auto* draw = ImGui::GetForegroundDrawList();
        const float dx = viewport.w / 256.0F, dy = viewport.h / kPlayableWorldHeight;
        for (int y = 0; y < 32; ++y)
            for (int x = 0; x < 256; ++x)
                if (mask[y * 32 + x / 8] & (0x80U >> (x & 7)))
                    draw->AddRectFilled({viewport.x + x * dx, viewport.y + y * dy},
                                        {viewport.x + (x + 1) * dx, viewport.y + (y + 1) * dy}, IM_COL32_WHITE);
    }

    void draw_centerprint(const SDL_FRect& viewport)
    {
        auto message = session_.centerprint();
        if (message.empty())
            return;
        auto* font = ImGui::GetFont();
        auto* draw = ImGui::GetForegroundDrawList();
        const float row_height = viewport.h * (10.0F / kPlayableWorldHeight);
        const float size = row_height;
        float y = viewport.y + viewport.h * (78.0F / kPlayableWorldHeight);
        const auto draw_line = [&](std::string_view line)
        {
            const auto* end = line.data() + line.size();
            const float width = ImGui::CalcTextSize(line.data(), end).x * size / ImGui::GetFontSize();
            const float x = viewport.x + (viewport.w - width) * 0.5F;
            draw->AddText(font, size, {x + 1, y + 1}, IM_COL32(0, 0, 0, 255), line.data(), end);
            draw->AddText(font, size, {x, y}, IM_COL32(255, 255, 255, 255), line.data(), end);
            y += row_height;
        };
        for (;;)
        {
            const auto newline = message.find('\n');
            auto line = message.substr(0, newline);
            while (line.size() > 32)
            {
                const auto space = line.rfind(' ', 32);
                if (space == std::string_view::npos)
                    break;
                draw_line(line.substr(0, space));
                line.remove_prefix(space + 1);
            }
            draw_line(line);
            if (newline == std::string_view::npos)
                break;
            message.remove_prefix(newline + 1);
        }
    }

    void clear_input()
    {
        keys_.fill(false);
        mouse_dx_ = mouse_dy_ = 0;
        mouse_buttons_ = 0;
        cycle_weapon_ = false;
    }

    void load_recordings()
    {
        try
        {
            if (!fs::exists(recording_dir_))
                return;
            std::vector<fs::path> paths;
            for (const auto& entry : fs::directory_iterator(recording_dir_))
                if (entry.is_regular_file() && entry.path().filename().string().ends_with(".gameplay-tape.json"))
                    paths.push_back(entry.path());
            std::ranges::sort(paths);
            for (const auto& path : paths)
                try
                {
                    auto tape = read_gameplay_tape(path);
                    if (std::ranges::find(map_names_, tape.map) != map_names_.end())
                        tapes_.push_back(std::move(tape));
                }
                catch (const std::exception& error)
                {
                    recording_error_ = error.what();
                }
        }
        catch (const std::exception& error)
        {
            recording_error_ = error.what();
        }
    }

    void reset(std::string_view map, std::optional<std::uint8_t> skill = std::nullopt)
    {
        const auto phase = session_.service_phase();
        if (!phase.empty() && phase != "done")
            session_.service_tick();
        const auto selected = skill ? *skill : session_.state().at("skillSelected").get<std::uint8_t>();
        session_.reset(map, selected);
        clear_input();
        paused_ = false;
        reset_clock_ = true;
        last_tape_.reset();
        dirty_ = true;
    }

    std::optional<std::size_t> selected_tape() const
    {
        if (chosen_tape_)
            return chosen_tape_;
        const auto selected = std::ranges::find(tapes_, selected_map_, &GameplayTape::map);
        if (selected == tapes_.end())
            return std::nullopt;
        return static_cast<std::size_t>(selected - tapes_.begin());
    }

    void toggle_tape()
    {
        if (recording_)
            return;
        if (playing_tape_)
        {
            stop_tape();
            return;
        }
        if (const auto index = selected_tape())
        {
            const auto& tape = tapes_[*index];
            live_always_run_ = session_.always_run();
            reset(tape.map, tape.skill);
            session_.set_always_run(tape.always_run);
            session_.use_queued_input(true);
            captured_ = false;
            SDL_SetWindowRelativeMouseMode(window_, false);
            last_tape_ = index;
            tape_tick_ = 0;
            tape_hold_ = 0;
            tape_hold_left_ = tape.holds.front().ticks;
            playing_tape_ = true;
            paused_ = false;
            reset_clock_ = true;
        }
    }

    void stop_tape()
    {
        session_.set_always_run(live_always_run_);
        playing_tape_ = false;
        paused_ = false;
        reset_clock_ = true;
        clear_input();
    }

    void toggle_recording()
    {
        if (playing_tape_)
            return;
        if (recorded_)
        {
            finish_recording();
            return;
        }
        recording_error_.clear();
        last_recording_.clear();
        recorded_.emplace();
        recorded_->map = selected_map_;
        recorded_->skill = session_.state().at("skillSelected").get<std::uint8_t>();
        recorded_->always_run = session_.always_run();
        reset(recorded_->map, recorded_->skill);
        session_.use_queued_input(true);
        recording_ = true;
        paused_ = false;
        reset_clock_ = true;
    }

    bool finish_recording()
    {
        recording_ = false;
        paused_ = false;
        reset_clock_ = true;
        clear_input();
        if (!recorded_->ticks)
        {
            recorded_.reset();
            return true;
        }
        try
        {
            recorded_->path = save_gameplay_tape(recording_dir_, *recorded_);
            last_recording_ = recorded_->path;
            tapes_.push_back(std::move(*recorded_));
            chosen_tape_ = tapes_.size() - 1;
            selected_map_ = tapes_.back().map;
            recorded_.reset();
            recording_error_.clear();
            return true;
        }
        catch (const std::exception& error)
        {
            recording_error_ = error.what();
            return false;
        }
    }

    void tick()
    {
        if (playing_tape_)
        {
            const auto& tape = tapes_[*last_tape_];
            session_.step(tape.holds[tape_hold_].input);
            if (++tape_tick_ == tape.ticks)
            {
                if (tape.finish_level && !session_.state().at("pendingMap").get_ref<const std::string&>().empty())
                    session_.service_tick();
                stop_tape();
            }
            else if (--tape_hold_left_ == 0)
                tape_hold_left_ = tape.holds[++tape_hold_].ticks;
        }
        else
        {
            const auto live_input = held_input();
            session_.step(live_input);
            if (recording_)
            {
                recorded_->append(live_input);
                if (recorded_->ticks == GameplayTape::max_ticks)
                    finish_recording();
            }
        }
        mouse_dx_ = mouse_dy_ = 0;
        cycle_weapon_ = false;
        dirty_ = true;
    }

    void select_map(std::string_view map)
    {
        if (auto available = std::ranges::find(map_names_, map); available != map_names_.end() && *available != selected_map_)
        {
            selected_map_ = *available;
            chosen_tape_.reset();
        }
    }

    void events()
    {
        SDL_Event event;
        while (SDL_PollEvent(&event))
        {
            ImGui_ImplSDL3_ProcessEvent(&event);
            if (event.type == SDL_EVENT_QUIT)
                running_ = false;
            if (event.type == SDL_EVENT_WINDOW_FOCUS_LOST)
            {
                keys_.fill(false);
                cycle_weapon_ = false;
                captured_ = false;
                SDL_SetWindowRelativeMouseMode(window_, false);
            }
            if (event.type == SDL_EVENT_KEY_DOWN || event.type == SDL_EVENT_KEY_UP)
            {
                if (!playing_tape_)
                    keys_[event.key.scancode] = event.type == SDL_EVENT_KEY_DOWN;
                if (event.type == SDL_EVENT_KEY_DOWN && !event.key.repeat)
                {
                    if (event.key.key == SDLK_ESCAPE)
                    {
                        captured_ = false;
                        cycle_weapon_ = false;
                        SDL_SetWindowRelativeMouseMode(window_, false);
                    }
                    if (!ImGui::GetIO().WantCaptureKeyboard)
                    {
                        if (event.key.key == SDLK_P)
                            paused_ = !paused_;
                        if (event.key.key == SDLK_F6)
                        {
                            toggle_tape();
                            continue;
                        }
                        if (event.key.key == SDLK_F7)
                        {
                            toggle_recording();
                            continue;
                        }
                        if (playing_tape_)
                            continue;
                        if (!recording_)
                        {
                            if (event.key.key == SDLK_F1)
                                select_map("e1m1");
                            if (event.key.key == SDLK_F2)
                                select_map("start");
                            if (event.key.key == SDLK_F3)
                                select_map("e1m3");
                            if (event.key.key == SDLK_F4)
                                select_map("e1m2");
                            if (event.key.key == SDLK_F5)
                                select_map("e1m4");
                            if (event.key.key == SDLK_RETURN && !captured_)
                                reset(selected_map_);
                        }
                        if (event.key.key == SDLK_1 || event.key.key == SDLK_2)
                            cycle_weapon_ = !cycle_weapon_;
                    }
                }
            }
            if (playing_tape_)
                continue;
            if (event.type == SDL_EVENT_MOUSE_BUTTON_DOWN || event.type == SDL_EVENT_MOUSE_BUTTON_UP)
            {
                const bool down = event.type == SDL_EVENT_MOUSE_BUTTON_DOWN;
                int height = 0;
                SDL_GetWindowSize(window_, nullptr, &height);
                if (down && event.button.button == SDL_BUTTON_LEFT && event.button.y < height - controls_height)
                {
                    captured_ = true;
                    SDL_SetWindowRelativeMouseMode(window_, true);
                }
                const auto bit =
                    event.button.button == SDL_BUTTON_LEFT ? 0x40U
                    : event.button.button == SDL_BUTTON_RIGHT
                        ? 0x80U
                        : 0U;
                if (down)
                    mouse_buttons_ |= static_cast<std::uint8_t>(bit);
                else
                    mouse_buttons_ &= static_cast<std::uint8_t>(~bit);
            }
            if (event.type == SDL_EVENT_MOUSE_WHEEL && captured_ && event.wheel.integer_y % 2 != 0)
                cycle_weapon_ = !cycle_weapon_;
            if (event.type == SDL_EVENT_MOUSE_MOTION && captured_)
            {
                mouse_dx_ += event.motion.xrel;
                mouse_dy_ += event.motion.yrel;
            }
        }
    }

    GameplayInput held_input() const
    {
        GameplayInput input;
        if (ImGui::GetIO().WantCaptureKeyboard)
            return input;
        const auto add = [&](SDL_Scancode key, std::uint16_t bit) {
            if (keys_[key])
                input.joypad |= bit;
        };
        add(SDL_SCANCODE_W, 0x0040);
        add(SDL_SCANCODE_S, 0x8000);
        add(SDL_SCANCODE_A, 0x4000);
        add(SDL_SCANCODE_D, 0x0080);
        add(SDL_SCANCODE_LEFT, 0x0200);
        add(SDL_SCANCODE_RIGHT, 0x0100);
        add(SDL_SCANCODE_UP, 0x0800);
        add(SDL_SCANCODE_DOWN, 0x0400);
        add(SDL_SCANCODE_SPACE, 0x0010);
        add(SDL_SCANCODE_LCTRL, 0x0020);
        input.cycle_weapon = cycle_weapon_;
        input.mouse_connected = captured_;
        input.mouse_buttons = captured_ ? mouse_buttons_ & 0x40 : 0;
        if (captured_ && (mouse_buttons_ & 0x80))
            input.joypad |= 0x0010;
        input.mouse_dx = static_cast<std::int16_t>(std::clamp(mouse_dx_, -127.0F, 127.0F));
        input.mouse_dy = static_cast<std::int16_t>(std::clamp(mouse_dy_, -127.0F, 127.0F));
        return input;
    }

    void controls()
    {
        int width = 0, height = 0;
        SDL_GetWindowSize(window_, &width, &height);
        ImGui::SetNextWindowPos(ImVec2(0, static_cast<float>(height - controls_height)));
        ImGui::SetNextWindowSize(ImVec2(static_cast<float>(width), static_cast<float>(controls_height)));
        ImGui::Begin(
            "Gameplay",
            nullptr,
            ImGuiWindowFlags_NoDecoration | ImGuiWindowFlags_NoMove | ImGuiWindowFlags_NoSavedSettings |
                ImGuiWindowFlags_NoResize
        );
        ImGui::BeginDisabled(playing_tape_ || recording_);
        ImGui::SetNextItemWidth(100.0F);
        if (ImGui::BeginCombo("Level", selected_map_.c_str()))
        {
            for (const auto& map : map_names_)
            {
                if (ImGui::Selectable(map.c_str(), map == selected_map_))
                    select_map(map);
            }
            ImGui::EndCombo();
        }
        ImGui::SameLine();
        if (ImGui::Button("Load"))
            reset(selected_map_);
        ImGui::SameLine();
        if (ImGui::Button("Restart"))
            reset(snapshot_.map.empty() ? options_.initial_map : snapshot_.map);
        ImGui::SameLine();
        bool always_run = session_.always_run();
        if (ImGui::Checkbox("Always Run", &always_run))
            session_.set_always_run(always_run);
        ImGui::SetNextItemWidth(170.0F);
        const auto selected_technique = std::ranges::find(kGameplayTechniques, snapshot_.technique);
        const auto current_mode = selected_technique == kGameplayTechniques.end()
            ? 0U : static_cast<unsigned>(selected_technique - kGameplayTechniques.begin());
        if (ImGui::BeginCombo("Rendering mode", kGameplayTechniqueNames[current_mode]))
        {
            const auto count = kGameplayTechniques.size() - (has_face_colors_ ? 0U : 1U);
            for (std::size_t i = 0; i < count; ++i)
                if (ImGui::Selectable(kGameplayTechniqueNames[i], current_mode == i))
                {
                    session_.set_render_technique(kGameplayTechniques[i]);
                    dirty_ = true;
                }
            ImGui::EndCombo();
        }
        ImGui::EndDisabled();
        ImGui::SameLine();
        ImGui::Checkbox("Paused (P)", &paused_);
        ImGui::SameLine();
        if (ImGui::Button("One tick"))
            tick();
        ImGui::BeginDisabled(playing_tape_);
        if (ImGui::Button(recording_ ? "Stop & save (F7)" : recorded_ ? "Retry save (F7)" : "Record tape (F7)"))
            toggle_recording();
        ImGui::EndDisabled();
        ImGui::SameLine();
        const auto selected = selected_tape();
        ImGui::BeginDisabled(playing_tape_ || recording_ || !selected);
        ImGui::SetNextItemWidth(160.0F);
        if (ImGui::BeginCombo("Tape", selected ? tape_name(tapes_[*selected]).c_str() : "None"))
        {
            for (std::size_t i = 0; i < tapes_.size(); ++i)
            {
                if (tapes_[i].map == selected_map_ && ImGui::Selectable(tape_name(tapes_[i]).c_str(), selected == i))
                    chosen_tape_ = i;
            }
            ImGui::EndCombo();
        }
        ImGui::EndDisabled();
        ImGui::SameLine();
        ImGui::BeginDisabled(recording_ || (!playing_tape_ && !selected));
        if (ImGui::Button(playing_tape_ ? "Stop tape (F6)" : "Play tape (F6)"))
            toggle_tape();
        ImGui::EndDisabled();
        if (recorded_)
        {
            ImGui::SameLine();
            ImGui::Text("%s: %u ticks", recording_ ? "Recording" : "Unsaved", recorded_->ticks);
        }
        else if (last_tape_)
        {
            const auto& tape = tapes_[*last_tape_];
            ImGui::SameLine();
            ImGui::Text("%s: %u/%u ticks%s", tape.map.c_str(), tape_tick_, tape.ticks,
                        playing_tape_ ? "" : tape_tick_ == tape.ticks ? " (finished)" : " (stopped)");
        }
        else if (!last_recording_.empty())
        {
            ImGui::SameLine();
            ImGui::Text("Saved %s", last_recording_.filename().string().c_str());
        }
        if (!recording_error_.empty())
            ImGui::TextWrapped("%s", recording_error_.c_str());
        ImGui::TextUnformatted(
            "Click view to aim; Esc releases mouse. WASD move; arrows look; RMB/Space jump; LMB/Ctrl fire; wheel or 1/2 selects weapon."
        );
        const auto state = session_.state();
        const auto& player = state.at("player");
        const int health = std::bit_cast<std::int16_t>(player.at("health").get<std::uint16_t>()) / 64;
        const unsigned shells = player.at("ammoShells").get<std::uint16_t>() / 64U;
        ImGui::Text("Health: %d    Shells: %u", health, shells);
        ImGui::SameLine();
        ImGui::BeginDisabled(playing_tape_ || recording_);
        auto skill = state.at("skillActive").get<int>();
        ImGui::SetNextItemWidth(110.0F);
        if (ImGui::Combo("Difficulty", &skill, kGameplaySkillNames.data(),
                         static_cast<int>(kGameplaySkillNames.size())))
            session_.set_skill(static_cast<std::uint8_t>(skill));
        ImGui::EndDisabled();
        ImGui::Text(
            "Render: SNES billboards | 2x | Brushes %s | Entities %s",
            snapshot_.brushes_enabled ? "on" : "off",
            snapshot_.entities_enabled ? "on" : "off"
        );
        if (ImGui::CollapsingHeader("Diagnostics"))
        {
            const auto text = state.dump(2);
            ImGui::TextWrapped("%s", text.c_str());
        }
        ImGui::End();
    }

    void publish(int width)
    {
        LiveWindowState state;
        state.paused = paused_;
        state.pixels = last_frame_.pixels;
        state.display_pixels = state.pixels;
        state.brushes_enabled = snapshot_.brushes_enabled;
        state.entities_enabled = state.external_bsp_models = snapshot_.entities_enabled;
        state.presentation = {
            {"gameplayMode", true},
            {"gameplay", session_.state()},
            {"gameplayLastCommandId", completed_command_},
            {"gameplayLastResult", last_command_}
        };
        if (last_tape_)
        {
            const auto& tape = tapes_[*last_tape_];
            state.presentation["gameplayTape"] = {
                {"map", tape.map},
                {"path", tape.path.string()},
                {"playing", playing_tape_},
                {"ticks", tape_tick_},
                {"totalTicks", tape.ticks}
            };
        }
        state.presentation["gameplayRecording"] = {
            {"active", recording_},
            {"ticks", recorded_ ? recorded_->ticks : 0},
            {"path", last_recording_.string()},
            {"error", recording_error_}
        };
        instrumentation_.publish(
            snapshot_.video_tick,
            65536,
            0,
            paused_,
            PlaybackSchedule::NewestDue,
            30,
            state,
            generation_,
            last_frame_.composite,
            {{"clientWidth", width}, {"controlsHeight", controls_height}},
            Json::object(),
            last_frame_.inspection,
            Json::object(),
            audio_->inspection()
        );
    }

    static constexpr int controls_height = 180;
    GameplaySession& session_;
    GameplayRenderer& renderer_;
    const GameplayApplicationOptions& options_;
    ReferenceInstrumentationServer instrumentation_;
    std::vector<std::string> map_names_;
    std::vector<GameplayTape> tapes_;
    fs::path recording_dir_;
    std::string selected_map_;
    bool has_face_colors_{};
    SDL_Window* window_{};
    SDL_Renderer* sdl_renderer_{};
    SDL_Texture* texture_{};
    bool initialized_{}, imgui_{}, imgui_sdl_{}, imgui_renderer_{};
    bool running_{true}, paused_{}, dirty_{true}, captured_{};
    bool live_always_run_{true};
    bool playing_tape_{}, recording_{}, reset_clock_{};
    std::optional<std::size_t> chosen_tape_, last_tape_;
    std::optional<GameplayTape> recorded_;
    fs::path last_recording_;
    std::string recording_error_;
    unsigned tape_tick_{}, tape_hold_left_{};
    std::size_t tape_hold_{};
    std::array<bool, SDL_SCANCODE_COUNT> keys_{};
    float mouse_dx_{}, mouse_dy_{};
    std::uint8_t mouse_buttons_{};
    bool cycle_weapon_{};
    std::uint64_t generation_{}, completed_command_{};
    Json last_command_ = Json::object();
    GameplayRenderSnapshot snapshot_;
    GameplayFrame last_frame_;
    std::vector<std::uint8_t> audio_pak_;
    std::unique_ptr<QuakeAudioSession> audio_;
    std::uint64_t audio_generation_{};
    bool sound_enabled_{};
    float sound_volume_{0.7F};
};
} // namespace

int run_gameplay_application(const GameplayApplicationOptions& options)
{
    const auto started = std::chrono::steady_clock::now();
    auto assets = load_maps(options.assets);
    GameplayRenderer renderer(options.pak, assets);
    const bool has_face_colors = std::ranges::all_of(assets, [](const auto& asset) {
        return asset.payloads.contains("QuakeBSPFaceColors.bin");
    });
    std::vector<std::string> map_names;
    for (const auto& asset : assets)
        map_names.push_back(asset.map);
    GameplaySession session(std::move(assets), options.initial_map);
    int result = 0;
    if (!options.script.empty())
    {
        const auto bytes = read_file(options.script);
        const auto script = Json::parse(bytes.begin(), bytes.end());
        auto report = run_gameplay_script(
            session,
            script,
            [&](const GameplayRenderSnapshot& snapshot, std::size_t index, std::string_view label) {
                return capture_artifacts(options.output_prefix, index, label, snapshot, renderer.render(snapshot));
            }
        );
        report["script"] = options.script.string();
        report["assetManifests"] = Json::array();
        for (const auto& path : options.assets)
            report["assetManifests"].push_back(fs::absolute(path).string());
        report["elapsedSeconds"] = std::chrono::duration<double>(std::chrono::steady_clock::now() - started).count();
        write_json(options.report, report);
    }
    else
    {
        session.use_queued_input(true);
        if (options.face_colors && !has_face_colors)
            fail("baked face colors require an updated playable gameplay asset bundle");
        if (options.face_colors)
            session.set_render_technique(3);
        result = PlayableWindow(session, renderer, options, std::move(map_names), has_face_colors).run();
    }
    std::cout << "Gameplay " << (result == 0 ? "passed" : "failed") << "; elapsed="
              << std::chrono::duration<double>(std::chrono::steady_clock::now() - started).count() << "s\n";
    return result;
}

} // namespace quake_bsp_reference
