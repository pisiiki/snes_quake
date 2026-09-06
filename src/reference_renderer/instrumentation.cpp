#include "instrumentation.hpp"

namespace quake_bsp_reference {

namespace {

constexpr std::string_view kReferenceInstrumentationProtocol = "quake-reference-instrumentation-v1";
constexpr std::uint32_t kReferenceInstrumentationMaxMessageBytes = 1U << 20U;
constexpr std::size_t kReferenceInstrumentationHistory = 64;

} // namespace
bool valid_reference_instrumentation_identifier(std::string_view value)
{
    return !value.empty() && value.size() <= 64 && std::all_of(value.begin(), value.end(), [](unsigned char byte) {
        return byte < 128U && (std::isalnum(byte) != 0 || byte == '-' || byte == '_' || byte == '.');
    });
}

std::uint64_t reference_instrumentation_hash(std::span<const std::uint8_t> bytes)
{
    std::uint64_t value = 0xCBF29CE484222325ULL;
    for (const auto byte : bytes)
    {
        value = (value ^ byte) * 0x100000001B3ULL;
    }
    return value;
}

std::string reference_instrumentation_hex(std::uint64_t value)
{
    std::ostringstream stream;
    stream << std::hex << std::setfill('0') << std::setw(16) << value;
    return stream.str();
}

std::string reference_instrumentation_bytes_hex(std::span<const std::uint8_t> bytes)
{
    constexpr char digits[] = "0123456789abcdef";
    std::string result(bytes.size() * 2U, '0');
    for (std::size_t index = 0; index < bytes.size(); ++index)
    {
        result[index * 2U] = digits[bytes[index] >> 4U];
        result[index * 2U + 1U] = digits[bytes[index] & 0x0FU];
    }
    return result;
}

class ReferenceControlLayout::Impl
{
  public:
    explicit Impl(ImVec2 origin)
    :
    origin_(origin)
    {
    }

    void begin_row(std::string name)
    {
        end_row();
        row_name_ = std::move(name);
        row_items_ = Json::array();
        row_initialized_ = false;
    }

    void add_item(std::string_view name)
    {
        if (row_name_.empty())
        {
            fail("instrumented control item has no row");
        }
        const auto minimum = ImGui::GetItemRectMin();
        const auto maximum = ImGui::GetItemRectMax();
        const float left = minimum.x - origin_.x;
        const float top = minimum.y - origin_.y;
        const float right = maximum.x - origin_.x;
        const float bottom = maximum.y - origin_.y;
        row_items_.push_back(Json{{"name", name}, {"rect", Json::array({left, top, right, bottom})}});
        if (!row_initialized_)
        {
            row_left_ = left;
            row_top_ = top;
            row_right_ = right;
            row_bottom_ = bottom;
            row_initialized_ = true;
            return;
        }
        row_left_ = std::min(row_left_, left);
        row_top_ = std::min(row_top_, top);
        row_right_ = std::max(row_right_, right);
        row_bottom_ = std::max(row_bottom_, bottom);
    }

    Json finish(int client_width, int controls_height)
    {
        end_row();
        bool within_bounds = true;
        for (const auto& row : rows_)
        {
            const auto& rect = row.at("rect");
            const bool row_within =
                rect.at(0).get<float>() >= 0.0F && rect.at(1).get<float>() >= 0.0F &&
                rect.at(2).get<float>() <= static_cast<float>(client_width) &&
                rect.at(3).get<float>() <= static_cast<float>(controls_height);
            within_bounds = within_bounds && row_within;
        }
        return Json{
            {"clientWidth", client_width},
            {"controlsHeight", controls_height},
            {"withinBounds", within_bounds},
            {"rows", rows_}
        };
    }

  private:
    void end_row()
    {
        if (row_name_.empty())
        {
            return;
        }
        if (!row_initialized_)
        {
            fail("instrumented control row has no items");
        }
        rows_.push_back(
            Json{
                {"name", row_name_},
                {"rect", Json::array({row_left_, row_top_, row_right_, row_bottom_})},
                {"items", row_items_}
            }
        );
        row_name_.clear();
        row_items_ = Json::array();
        row_initialized_ = false;
    }

    ImVec2 origin_{};
    Json rows_ = Json::array();
    std::string row_name_;
    Json row_items_ = Json::array();
    bool row_initialized_{};
    float row_left_{};
    float row_top_{};
    float row_right_{};
    float row_bottom_{};
};

class ReferenceInstrumentationServer::Impl
{
  public:
    explicit Impl(ReferenceInstrumentationConfig config)
    :
    config_(std::move(config)),
    epoch_(Clock::now())
    {
        if (!config_.enabled())
        {
            return;
        }
#ifdef _WIN32
        server_thread_ = std::thread([this] { server_loop(); });
#else
        fail("reference instrumentation currently requires Windows named pipes");
#endif
    }

    ~Impl()
    {
        stop();
    }

    Impl(const Impl&) = delete;
    Impl& operator=(const Impl&) = delete;

    [[nodiscard]] bool enabled() const
    {
        return config_.enabled();
    }

    ReferenceInstrumentationCommands take_commands()
    {
        std::lock_guard lock(mutex_);
        auto commands = pending_commands_;
        pending_commands_ = {};
        return commands;
    }

    void capture_window(SDL_Renderer* renderer, const std::string& path, std::size_t pose)
    {
        Json result{{"path", path}, {"pose", pose}, {"status", "fail"}};
        SDL_Surface* surface = SDL_RenderReadPixels(renderer, nullptr);
        if (surface != nullptr)
        {
            result["width"] = surface->w;
            result["height"] = surface->h;
            if (SDL_SaveBMP(surface, path.c_str()))
            {
                result["status"] = "pass";
            }
            SDL_DestroySurface(surface);
        }
        if (result["status"] != "pass")
        {
            result["error"] = SDL_GetError();
        }
        std::lock_guard lock(mutex_);
        window_capture_ = std::move(result);
    }

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
    )
    {
        if (!enabled())
        {
            return;
        }
        const auto now = Clock::now();
        const auto elapsed_us = std::chrono::duration_cast<std::chrono::microseconds>(now - epoch_).count();
        std::lock_guard lock(mutex_);
        const bool fresh_pose = !ready_ || pose != pose_ || loop != loop_;
        ready_ = true;
        pose_ = pose;
        pose_count_ = pose_count;
        loop_ = loop;
        paused_ = paused;
        schedule_ = schedule;
        presentation_rate_hz_ = presentation_rate_hz;
        mode_ = live_state.mode;
        brushes_enabled_ = live_state.brushes_enabled;
        entities_enabled_ = live_state.entities_enabled;
        external_bsp_models_ = live_state.external_bsp_models;
        playback_speed_ = live_state.playback_speed;
        frame_generation_ = frame_generation;
        frame_indices_.assign(indices.begin(), indices.end());
        frame_hash_ = reference_instrumentation_hash(frame_indices_);
        if (live_state.pixels.size() != frame_indices_.size())
        {
            fail("instrumented RGB frame and index plane disagree");
        }
        frame_rgb_.clear();
        frame_rgb_.reserve(live_state.pixels.size() * 3U);
        for (const auto color : live_state.pixels)
        {
            frame_rgb_.push_back(static_cast<std::uint8_t>((color >> 16U) & 0xffU));
            frame_rgb_.push_back(static_cast<std::uint8_t>((color >> 8U) & 0xffU));
            frame_rgb_.push_back(static_cast<std::uint8_t>(color & 0xffU));
        }
        control_layout_ = std::move(control_layout);
        alias_inspection_ = std::move(alias_inspection);
        surface_inspection_ = std::move(surface_inspection);
        external_bsp_inspection_ = std::move(external_bsp_inspection);
        audio_inspection_ = std::move(audio_inspection);
        if (fresh_pose)
        {
            ++presentation_count_;
            presentation_history_.push_back(
                Json{
                    {"presentation", presentation_count_},
                    {"pose", pose_},
                    {"loop", loop_},
                    {"monotonicUs", elapsed_us},
                    {"frameGeneration", frame_generation_}
                }
            );
            if (presentation_history_.size() > kReferenceInstrumentationHistory)
            {
                presentation_history_.erase(presentation_history_.begin());
            }
        }
    }

  private:
    using Clock = std::chrono::steady_clock;

    static std::string schedule_name(PlaybackSchedule schedule)
    {
        switch (schedule)
        {
        case PlaybackSchedule::NewestDue:
            return "source-rate";
        case PlaybackSchedule::OrderedTimed:
            return "timed";
        case PlaybackSchedule::OrderedRenderCompletion:
            return "fast";
        }
        return "unknown";
    }

    static std::string playback_speed_name(PlaybackSpeed speed)
    {
        switch (speed)
        {
        case PlaybackSpeed::Realtime:
            return "realtime";
        case PlaybackSpeed::Half:
            return "half";
        case PlaybackSpeed::Quarter:
            return "quarter";
        }
        return "unknown";
    }

    Json status_locked() const
    {
        Json status{
            {"protocol", kReferenceInstrumentationProtocol},
            {"sessionId", config_.session_id},
            {"pipeName", config_.pipe_name},
            {"capabilities",
             Json::array(
                 {"status",
                  "captureFrame",
                  "captureWindow",
                  "inspectAliases",
                  "pause",
                  "resume",
                  "seek",
                  "setPace",
                  "setRate",
                  "setExternalBspModels",
                  "setSound",
                  "setVolume",
                  "shutdown"}
             )},
            {"ready", ready_},
            {"windowCapture", window_capture_},
            {"serverError", server_error_.empty() ? Json(nullptr) : Json(server_error_)}
        };
#ifdef _WIN32
        status["processId"] = GetCurrentProcessId();
#endif
        if (!ready_)
        {
            return status;
        }
        status.update(
            Json{
                {"pose", pose_},
                {"poseCount", pose_count_},
                {"loop", loop_},
                {"paused", paused_},
                {"schedule", schedule_name(schedule_)},
                {"presentationRateHz", presentation_rate_hz_},
                {"playbackSpeed", playback_speed_name(playback_speed_)},
                {"presentationCount", presentation_count_},
                {"presentationHistory", presentation_history_},
                {"frame",
                 Json{
                     {"generation", frame_generation_},
                     {"width", kLogicalWidth},
                     {"height", kLogicalHeight},
                     {"bytes", frame_indices_.size()},
                     {"fnv1a64", reference_instrumentation_hex(frame_hash_)}
                 }},
                {"render",
                 Json{
                     {"textures", mode_.textures},
                     {"technique", render_mode_technique(mode_)},
                     {"lighting", static_cast<int>(mode_.lighting)},
                     {"dynamicBrushes", brushes_enabled_},
                     {"configuredDynamicBrushes", brushes_enabled_},
                     {"mdlEntities", entities_enabled_},
                     {"configuredMdlEntities", entities_enabled_},
                     {"externalBspModels", external_bsp_models_},
                     {"configuredExternalBspModels", external_bsp_models_},
                     {"externalBsp", external_bsp_inspection_},
                     {"surface", surface_inspection_}
                 }},
                {"audio", audio_inspection_},
                {"controls", control_layout_}
            }
        );
        return status;
    }

    Json capture_locked() const
    {
        if (!ready_)
        {
            throw std::runtime_error("reference renderer has not presented a logical frame");
        }
        return Json{
            {"protocol", kReferenceInstrumentationProtocol},
            {"pose", pose_},
            {"loop", loop_},
            {"generation", frame_generation_},
            {"width", kLogicalWidth},
            {"height", kLogicalHeight},
            {"format", "indexed8"},
            {"rgbFormat", "rgb888"},
            {"surface", surface_inspection_},
            {"fnv1a64", reference_instrumentation_hex(frame_hash_)},
            {"indicesHex", reference_instrumentation_bytes_hex(frame_indices_)},
            {"rgb888Hex", reference_instrumentation_bytes_hex(frame_rgb_)}
        };
    }

    Json alias_inspection_locked() const
    {
        if (!ready_)
        {
            throw std::runtime_error("reference renderer has not presented alias diagnostics");
        }
        auto result = alias_inspection_;
        result["protocol"] = kReferenceInstrumentationProtocol;
        result["pose"] = pose_;
        result["displayedSample"] = pose_ + 1U;
        result["loop"] = loop_;
        result["generation"] = frame_generation_;
        result["frameFnv1a64"] = reference_instrumentation_hex(frame_hash_);
        return result;
    }

    Json handle_request(const Json& request)
    {
        if (!request.is_object() || request.value("jsonrpc", "") != "2.0" || !request.contains("id") ||
            !request.contains("method") || !request.at("method").is_string())
        {
            throw std::runtime_error("invalid JSON-RPC request");
        }
        const auto method = request.at("method").get<std::string>();
        const auto params = request.value("params", Json::object());
        if (!params.is_object())
        {
            throw std::runtime_error("JSON-RPC params must be an object");
        }
        std::lock_guard lock(mutex_);
        if (method == "status")
        {
            return status_locked();
        }
        if (method == "captureFrame")
        {
            return capture_locked();
        }
        if (method == "captureWindow")
        {
            const auto path = params.at("path").get<std::string>();
            const fs::path destination(path);
            if (!ready_ || !paused_ || !destination.is_absolute() || destination.extension() != ".bmp" ||
                fs::exists(destination))
            {
                throw std::runtime_error("window capture requires a paused frame and a new absolute BMP path");
            }
            if (pending_commands_.window_capture_path.has_value())
            {
                throw std::runtime_error("a window capture is already pending");
            }
            window_capture_ = nullptr;
            pending_commands_.window_capture_path = path;
            return Json{{"accepted", true}, {"path", path}};
        }
        if (method == "inspectAliases")
        {
            return alias_inspection_locked();
        }
        if (method == "pause" || method == "resume")
        {
            pending_commands_.paused = method == "pause";
            return Json{{"accepted", true}};
        }
        if (method == "seek")
        {
            if (!ready_)
            {
                throw std::runtime_error("seek requires initialized live playback");
            }
            if (!params.contains("pose") || !params.at("pose").is_number_integer())
            {
                throw std::runtime_error("seek requires an integer pose");
            }
            const auto pose = params.at("pose").get<std::int64_t>();
            if (pose < 0 || static_cast<std::uint64_t>(pose) >= pose_count_)
            {
                throw std::runtime_error("seek pose is out of range");
            }
            pending_commands_.pose = static_cast<std::size_t>(pose);
            pending_commands_.paused = true;
            return Json{{"accepted", true}, {"pose", pose}};
        }
        if (method == "setPace")
        {
            if (!ready_ || schedule_ == PlaybackSchedule::NewestDue)
            {
                throw std::runtime_error("setPace requires ordered live playback");
            }
            const auto pace = params.value("pace", "");
            if (pace == "timed")
            {
                pending_commands_.pace = PlaybackSchedule::OrderedTimed;
            }
            else if (pace == "fast")
            {
                pending_commands_.pace = PlaybackSchedule::OrderedRenderCompletion;
            }
            else
            {
                throw std::runtime_error("pace must be timed or fast");
            }
            return Json{{"accepted", true}, {"pace", pace}};
        }
        if (method == "setRate")
        {
            if (!ready_ || schedule_ == PlaybackSchedule::NewestDue)
            {
                throw std::runtime_error("setRate requires ordered live playback");
            }
            const int rate = params.value("rateHz", 0);
            if (rate != 2 && rate != 20)
            {
                throw std::runtime_error("rateHz must be 2 or 20");
            }
            pending_commands_.presentation_rate_hz = rate;
            return Json{{"accepted", true}, {"rateHz", rate}};
        }
        if (method == "setExternalBspModels")
        {
            if (!ready_ || !external_bsp_inspection_.value("available", false))
            {
                throw std::runtime_error("setExternalBspModels requires an external BSP replay");
            }
            if (!params.contains("enabled") || !params.at("enabled").is_boolean())
            {
                throw std::runtime_error("setExternalBspModels requires boolean enabled");
            }
            const bool enabled = params.at("enabled").get<bool>();
            pending_commands_.external_bsp_models = enabled;
            return Json{{"accepted", true}, {"enabled", enabled}};
        }
        if (method == "setSound")
        {
            if (!ready_ || !audio_inspection_.value("configured", false))
            {
                throw std::runtime_error("setSound requires a configured sound replay");
            }
            if (!params.contains("enabled") || !params.at("enabled").is_boolean())
            {
                throw std::runtime_error("setSound requires boolean enabled");
            }
            const bool enabled = params.at("enabled").get<bool>();
            pending_commands_.sound_enabled = enabled;
            return Json{{"accepted", true}, {"enabled", enabled}};
        }
        if (method == "setVolume")
        {
            if (!ready_ || !audio_inspection_.value("configured", false))
            {
                throw std::runtime_error("setVolume requires a configured sound replay");
            }
            if (!params.contains("volume") || !params.at("volume").is_number())
            {
                throw std::runtime_error("setVolume requires numeric volume");
            }
            const auto volume = params.at("volume").get<float>();
            if (!std::isfinite(volume) || volume < 0.0F || volume > 1.0F)
            {
                throw std::runtime_error("volume must be from 0.0 to 1.0");
            }
            pending_commands_.sound_volume = volume;
            return Json{{"accepted", true}, {"volume", volume}};
        }
        if (method == "shutdown")
        {
            pending_commands_.shutdown = true;
            return Json{{"accepted", true}};
        }
        throw std::runtime_error("unknown reference instrumentation method");
    }

    Json response_for(const Json& request)
    {
        const Json id = request.is_object() && request.contains("id") ? request.at("id") : Json(nullptr);
        try
        {
            return Json{{"jsonrpc", "2.0"}, {"id", id}, {"result", handle_request(request)}};
        }
        catch (const std::exception& error)
        {
            return Json{{"jsonrpc", "2.0"}, {"id", id}, {"error", Json{{"code", -32602}, {"message", error.what()}}}};
        }
    }

    void set_server_error_noexcept(std::string_view message) noexcept
    {
        try
        {
            std::lock_guard lock(mutex_);
            server_error_.assign(message);
        }
        catch (...)
        {
            // The background thread cannot safely propagate an error while
            // attempting to record its original failure.
        }
    }

    void stop() noexcept
    {
        stopping_.store(true);
#ifdef _WIN32
        if (server_thread_.joinable())
        {
            CancelSynchronousIo(static_cast<HANDLE>(server_thread_.native_handle()));
            server_thread_.join();
        }
#endif
    }

#ifdef _WIN32
    class CurrentUserPipeSecurity
    {
      public:
        CurrentUserPipeSecurity()
        {
            HANDLE token{};
            if (!OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &token))
            {
                throw_windows("cannot open the current process token");
            }
            DWORD bytes{};
            GetTokenInformation(token, TokenUser, nullptr, 0, &bytes);
            std::vector<DWORD> storage((bytes + sizeof(DWORD) - 1U) / sizeof(DWORD));
            if (bytes == 0 || !GetTokenInformation(token, TokenUser, storage.data(), bytes, &bytes))
            {
                CloseHandle(token);
                throw_windows("cannot read the current user SID");
            }
            CloseHandle(token);
            const auto* user = reinterpret_cast<const TOKEN_USER*>(storage.data());
            LPWSTR sid_text{};
            if (!ConvertSidToStringSidW(user->User.Sid, &sid_text))
            {
                throw_windows("cannot encode the current user SID");
            }
            const std::wstring sddl = std::wstring(L"D:P(A;;GA;;;") + sid_text + L")";
            LocalFree(sid_text);
            if (!ConvertStringSecurityDescriptorToSecurityDescriptorW(
                    sddl.c_str(),
                    SDDL_REVISION_1,
                    &descriptor_,
                    nullptr
                ))
            {
                throw_windows("cannot create the named-pipe security descriptor");
            }
            attributes_.nLength = sizeof(attributes_);
            attributes_.lpSecurityDescriptor = descriptor_;
            attributes_.bInheritHandle = FALSE;
        }

        ~CurrentUserPipeSecurity()
        {
            if (descriptor_ != nullptr)
            {
                LocalFree(descriptor_);
            }
        }

        SECURITY_ATTRIBUTES* get()
        {
            return &attributes_;
        }

      private:
        static void throw_windows(std::string_view context)
        {
            throw std::runtime_error(std::string(context) + " (Windows error " + std::to_string(GetLastError()) + ")");
        }

        PSECURITY_DESCRIPTOR descriptor_{};
        SECURITY_ATTRIBUTES attributes_{};
    };

    static bool read_exact(HANDLE pipe, void* destination, std::size_t bytes)
    {
        auto* output = static_cast<std::uint8_t*>(destination);
        std::size_t offset = 0;
        while (offset < bytes)
        {
            DWORD transferred{};
            const auto chunk =
                static_cast<DWORD>(std::min<std::size_t>(bytes - offset, std::numeric_limits<DWORD>::max()));
            if (!ReadFile(pipe, output + offset, chunk, &transferred, nullptr) || transferred == 0)
            {
                const auto error = GetLastError();
                if (error == ERROR_BROKEN_PIPE || error == ERROR_OPERATION_ABORTED || error == ERROR_NO_DATA)
                {
                    return false;
                }
                throw std::runtime_error(
                    "reference instrumentation read failed (Windows error " + std::to_string(error) + ")"
                );
            }
            offset += transferred;
        }
        return true;
    }

    static bool write_exact(HANDLE pipe, const void* source, std::size_t bytes)
    {
        const auto* input = static_cast<const std::uint8_t*>(source);
        std::size_t offset = 0;
        while (offset < bytes)
        {
            DWORD transferred{};
            const auto chunk =
                static_cast<DWORD>(std::min<std::size_t>(bytes - offset, std::numeric_limits<DWORD>::max()));
            if (!WriteFile(pipe, input + offset, chunk, &transferred, nullptr) || transferred == 0)
            {
                const auto error = GetLastError();
                if (error == ERROR_BROKEN_PIPE || error == ERROR_OPERATION_ABORTED || error == ERROR_NO_DATA)
                {
                    return false;
                }
                throw std::runtime_error(
                    "reference instrumentation write failed (Windows error " + std::to_string(error) + ")"
                );
            }
            offset += transferred;
        }
        return true;
    }

    void serve_connection(HANDLE pipe)
    {
        while (!stopping_.load())
        {
            std::uint32_t request_bytes{};
            if (!read_exact(pipe, &request_bytes, sizeof(request_bytes)))
            {
                return;
            }
            if (request_bytes == 0 || request_bytes > kReferenceInstrumentationMaxMessageBytes)
            {
                throw std::runtime_error("reference instrumentation request size is invalid");
            }
            std::string payload(request_bytes, '\0');
            if (!read_exact(pipe, payload.data(), payload.size()))
            {
                return;
            }
            Json request;
            try
            {
                request = Json::parse(payload);
            }
            catch (const std::exception& error)
            {
                const auto response = Json{
                    {"jsonrpc", "2.0"},
                    {"id", nullptr},
                    {"error", Json{{"code", -32700}, {"message", error.what()}}}
                }.dump();
                const auto response_bytes = static_cast<std::uint32_t>(response.size());
                if (!write_exact(pipe, &response_bytes, sizeof(response_bytes)) ||
                    !write_exact(pipe, response.data(), response.size()))
                {
                    return;
                }
                continue;
            }
            const auto response = response_for(request).dump();
            if (response.size() > kReferenceInstrumentationMaxMessageBytes)
            {
                throw std::runtime_error("reference instrumentation response is too large");
            }
            const auto response_bytes = static_cast<std::uint32_t>(response.size());
            if (!write_exact(pipe, &response_bytes, sizeof(response_bytes)) ||
                !write_exact(pipe, response.data(), response.size()))
            {
                return;
            }
        }
    }

    void server_loop() noexcept
    {
        try
        {
            CurrentUserPipeSecurity security;
            const std::wstring pipe_path =
                std::wstring(L"\\\\.\\pipe\\") + std::wstring(config_.pipe_name.begin(), config_.pipe_name.end());
            while (!stopping_.load())
            {
                HANDLE pipe = CreateNamedPipeW(
                    pipe_path.c_str(),
                    PIPE_ACCESS_DUPLEX,
                    PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_WAIT | PIPE_REJECT_REMOTE_CLIENTS,
                    1,
                    kReferenceInstrumentationMaxMessageBytes,
                    kReferenceInstrumentationMaxMessageBytes,
                    0,
                    security.get()
                );
                if (pipe == INVALID_HANDLE_VALUE)
                {
                    throw std::runtime_error(
                        "cannot create reference instrumentation pipe (Windows "
                        "error " +
                        std::to_string(GetLastError()) + ")"
                    );
                }
                const bool connected =
                    ConnectNamedPipe(pipe, nullptr) != FALSE || GetLastError() == ERROR_PIPE_CONNECTED;
                if (connected && !stopping_.load())
                {
                    try
                    {
                        serve_connection(pipe);
                    }
                    catch (const std::exception& error)
                    {
                        set_server_error_noexcept(error.what());
                    }
                    catch (...)
                    {
                        set_server_error_noexcept("unknown reference instrumentation connection error");
                    }
                }
                DisconnectNamedPipe(pipe);
                CloseHandle(pipe);
            }
        }
        catch (const std::exception& error)
        {
            if (!stopping_.load())
            {
                set_server_error_noexcept(error.what());
            }
        }
        catch (...)
        {
            if (!stopping_.load())
            {
                set_server_error_noexcept("unknown reference instrumentation server error");
            }
        }
    }
#endif

    ReferenceInstrumentationConfig config_;
    Clock::time_point epoch_;
    mutable std::mutex mutex_;
    std::atomic<bool> stopping_{};
    std::thread server_thread_;
    ReferenceInstrumentationCommands pending_commands_;
    bool ready_{};
    std::size_t pose_{};
    std::size_t pose_count_{};
    std::uint64_t loop_{};
    bool paused_{};
    PlaybackSchedule schedule_{PlaybackSchedule::NewestDue};
    int presentation_rate_hz_{2};
    RenderMode mode_{};
    bool brushes_enabled_{};
    bool entities_enabled_{};
    bool external_bsp_models_{};
    PlaybackSpeed playback_speed_{PlaybackSpeed::Realtime};
    std::uint64_t frame_generation_{};
    std::uint64_t frame_hash_{};
    std::vector<std::uint8_t> frame_indices_;
    std::vector<std::uint8_t> frame_rgb_;
    Json alias_inspection_ = Json{
        {"schema", "quake-reference-alias-inspection-v1"},
        {"available", false},
        {"reason", "alias diagnostics are not available"}
    };
    Json surface_inspection_ = Json{
        {"schema", "quake-reference-surface-inspection-v1"},
        {"available", false},
        {"reason", "dynamic surface diagnostics are not available"}
    };
    Json external_bsp_inspection_ = Json{
        {"schema", "quake-reference-external-bsp-inspection-v2"},
        {"available", false},
        {"reason", "external BSP diagnostics are not available"}
    };
    Json audio_inspection_ = Json{
        {"schema", "quake-reference-audio-inspection-v1"},
        {"configured", false},
        {"available", false},
        {"enabled", false},
        {"effective", false},
        {"reason", "sound replay is not configured"}
    };
    std::uint64_t presentation_count_{};
    Json presentation_history_ = Json::array();
    Json control_layout_ = Json::object();
    Json window_capture_ = nullptr;
    std::string server_error_;
};
ReferenceControlLayout::ReferenceControlLayout(ImVec2 origin)
:
impl_(std::make_unique<Impl>(origin))
{
}

ReferenceControlLayout::~ReferenceControlLayout() = default;
ReferenceControlLayout::ReferenceControlLayout(ReferenceControlLayout&&) noexcept = default;
ReferenceControlLayout& ReferenceControlLayout::operator=(ReferenceControlLayout&&) noexcept = default;

void ReferenceControlLayout::begin_row(std::string name)
{
    impl_->begin_row(std::move(name));
}

void ReferenceControlLayout::add_item(std::string_view name)
{
    impl_->add_item(name);
}

Json ReferenceControlLayout::finish(int client_width, int controls_height)
{
    return impl_->finish(client_width, controls_height);
}

ReferenceInstrumentationServer::ReferenceInstrumentationServer(ReferenceInstrumentationConfig config)
:
impl_(std::make_unique<Impl>(std::move(config)))
{
}

ReferenceInstrumentationServer::~ReferenceInstrumentationServer() = default;

bool ReferenceInstrumentationServer::enabled() const
{
    return impl_->enabled();
}

ReferenceInstrumentationCommands ReferenceInstrumentationServer::take_commands()
{
    return impl_->take_commands();
}

void ReferenceInstrumentationServer::capture_window(SDL_Renderer* renderer, const std::string& path, std::size_t pose)
{
    impl_->capture_window(renderer, path, pose);
}

void ReferenceInstrumentationServer::publish(
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
)
{
    impl_->publish(
        pose,
        pose_count,
        loop,
        paused,
        schedule,
        presentation_rate_hz,
        live_state,
        frame_generation,
        indices,
        std::move(control_layout),
        std::move(alias_inspection),
        std::move(surface_inspection),
        std::move(external_bsp_inspection),
        std::move(audio_inspection)
    );
}

} // namespace quake_bsp_reference
