#include "audio.hpp"
#include "brushes.hpp"

namespace quake_bsp_reference {

namespace {

constexpr std::uint16_t kSoundReplayVersion = 1;
constexpr std::size_t kSoundReplayHeaderBytes = 36;
constexpr std::size_t kSoundReplaySoundBytes = 64;
constexpr std::size_t kSoundReplayEventBytes = 22;
constexpr int kSoundEventStart = 1;
constexpr int kSoundEventStop = 2;
constexpr int kSoundEventStatic = 3;
constexpr std::uint16_t kNoSoundSlot = 0xffff;
constexpr int kAudioOutputRate = 44100;
constexpr std::size_t kDynamicSoundChannels = 8;

struct QuakeMixChannel
{
    bool active{};
    std::uint16_t sound_slot{};
    std::uint16_t entity{};
    std::uint8_t channel{};
    std::uint8_t volume{};
    std::uint8_t attenuation{};
    Vec3 origin;
    double sample_position{};
};

class QuakeSoundMixer
{
  public:
    explicit QuakeSoundMixer(const QuakeSoundAssets& assets)
    :
    assets_(assets)
    {
    }

    void set_listener(const ViewTransform& listener)
    {
        listener_ = listener;
    }
    void set_volume(float value)
    {
        volume_ = std::clamp(value, 0.0F, 1.0F);
    }
    void set_mixing(bool value)
    {
        mixing_ = value;
    }

    void seek(double seconds)
    {
        const double target = std::clamp(seconds, 0.0, assets_.replay.duration_seconds());
        dynamic_ = {};
        statics_.clear();
        next_event_ = 0;
        timeline_seconds_ =
            assets_.replay.events.empty() ? 0.0 : std::min(0.0, assets_.replay.events.front().due_seconds());
        while (next_event_ < assets_.replay.events.size() && assets_.replay.events[next_event_].due_seconds() <= target)
        {
            const auto due = assets_.replay.events[next_event_].due_seconds();
            advance_channels(due - timeline_seconds_);
            timeline_seconds_ = due;
            apply_event(assets_.replay.events[next_event_++]);
        }
        advance_channels(target - timeline_seconds_);
        timeline_seconds_ = target;
        ++seek_count_;
    }

    void mix(std::span<float> stereo)
    {
        if (stereo.size() % 2U != 0)
        {
            return;
        }
        std::ranges::fill(stereo, 0.0F);
        if (!mixing_)
        {
            return;
        }
        for (std::size_t frame = 0; frame < stereo.size() / 2U; ++frame)
        {
            if (timeline_seconds_ >= assets_.replay.duration_seconds())
            {
                seek(0.0);
                ++mixed_loop_count_;
            }
            while (next_event_ < assets_.replay.events.size() &&
                   assets_.replay.events[next_event_].due_seconds() <= timeline_seconds_ + 0.5 / kAudioOutputRate)
            {
                apply_event(assets_.replay.events[next_event_++]);
            }
            float left{};
            float right{};
            for (auto& channel : dynamic_)
            {
                mix_channel(channel, left, right);
            }
            for (auto& channel : statics_)
            {
                mix_channel(channel, left, right);
            }
            stereo[frame * 2U] = std::clamp(left * volume_, -1.0F, 1.0F);
            stereo[frame * 2U + 1U] = std::clamp(right * volume_, -1.0F, 1.0F);
            timeline_seconds_ += 1.0 / kAudioOutputRate;
            ++mixed_frames_;
        }
    }

    double timeline_seconds() const
    {
        return timeline_seconds_;
    }
    std::uint64_t mixed_frames() const
    {
        return mixed_frames_;
    }
    std::uint64_t processed_events() const
    {
        return processed_events_;
    }
    std::uint64_t seek_count() const
    {
        return seek_count_;
    }
    std::uint64_t mixed_loop_count() const
    {
        return mixed_loop_count_;
    }
    std::uint64_t ignored_static_sounds() const
    {
        return ignored_static_sounds_;
    }
    std::uint32_t last_source_record() const
    {
        return last_source_record_;
    }
    int last_event_kind() const
    {
        return last_event_kind_;
    }
    std::size_t active_dynamic() const
    {
        return std::ranges::count_if(dynamic_, &QuakeMixChannel::active);
    }
    std::size_t active_static() const
    {
        return std::ranges::count_if(statics_, &QuakeMixChannel::active);
    }

  private:
    const QuakeSoundAssets& assets_;
    ViewTransform listener_{};
    std::array<QuakeMixChannel, kDynamicSoundChannels> dynamic_{};
    std::vector<QuakeMixChannel> statics_;
    std::size_t next_event_{};
    double timeline_seconds_{};
    float volume_{0.7F};
    bool mixing_{};
    std::uint64_t mixed_frames_{};
    std::uint64_t processed_events_{};
    std::uint64_t seek_count_{};
    std::uint64_t mixed_loop_count_{};
    std::uint64_t ignored_static_sounds_{};
    std::uint32_t last_source_record_{};
    int last_event_kind_{};

    void advance_channel(QuakeMixChannel& channel, double seconds)
    {
        if (!channel.active || seconds <= 0.0)
        {
            return;
        }
        const auto& wave = assets_.waves.at(channel.sound_slot);
        channel.sample_position += seconds * wave.sample_rate;
        normalize_position(channel, wave);
    }

    static void normalize_position(QuakeMixChannel& channel, const QuakeWave& wave)
    {
        if (channel.sample_position < static_cast<double>(wave.samples.size()))
        {
            return;
        }
        if (!wave.loop_start.has_value())
        {
            channel.active = false;
            return;
        }
        const double loop = static_cast<double>(*wave.loop_start);
        const double length = static_cast<double>(wave.samples.size()) - loop;
        channel.sample_position = loop + std::fmod(channel.sample_position - loop, length);
    }

    void advance_channels(double seconds)
    {
        for (auto& channel : dynamic_)
        {
            advance_channel(channel, seconds);
        }
        for (auto& channel : statics_)
        {
            advance_channel(channel, seconds);
        }
    }

    double remaining_seconds(const QuakeMixChannel& channel) const
    {
        if (!channel.active)
        {
            return 0.0;
        }
        const auto& wave = assets_.waves.at(channel.sound_slot);
        return (static_cast<double>(wave.samples.size()) - channel.sample_position) / wave.sample_rate;
    }

    QuakeMixChannel* pick_dynamic(std::uint16_t entity, std::uint8_t channel_number)
    {
        if (channel_number != 0)
        {
            const auto selected = std::ranges::find_if(dynamic_, [&](const QuakeMixChannel& candidate) {
                return candidate.active && candidate.entity == entity && candidate.channel == channel_number;
            });
            if (selected != dynamic_.end())
            {
                return &*selected;
            }
        }
        QuakeMixChannel* selected{};
        double least_life = std::numeric_limits<double>::max();
        for (auto& candidate : dynamic_)
        {
            if (candidate.active && candidate.entity == assets_.replay.view_entity &&
                entity != assets_.replay.view_entity)
            {
                continue;
            }
            const auto life = remaining_seconds(candidate);
            if (life < least_life)
            {
                least_life = life;
                selected = &candidate;
            }
        }
        return selected;
    }

    void apply_event(const QuakeSoundEvent& event)
    {
        ++processed_events_;
        last_source_record_ = event.source_record;
        last_event_kind_ = event.kind;
        if (event.kind == kSoundEventStop)
        {
            for (auto& channel : dynamic_)
            {
                if (channel.active && channel.entity == event.entity && channel.channel == event.channel)
                {
                    channel.active = false;
                    break;
                }
            }
            return;
        }
        if (event.kind == kSoundEventStatic)
        {
            if (!assets_.waves.at(event.sound_slot).loop_start.has_value())
            {
                ++ignored_static_sounds_;
                return;
            }
            statics_.push_back({true, event.sound_slot, 0, 0, event.volume, event.attenuation, event.origin, 0.0});
            return;
        }
        auto* channel = pick_dynamic(event.entity, event.channel);
        if (channel != nullptr)
        {
            *channel = {
                true,
                event.sound_slot,
                event.entity,
                event.channel,
                event.volume,
                event.attenuation,
                event.origin,
                0.0
            };
        }
    }

    std::pair<float, float> spatial_volume(const QuakeMixChannel& channel) const
    {
        const float master = static_cast<float>(channel.volume) / 255.0F;
        if (channel.entity == assets_.replay.view_entity)
        {
            return {master, master};
        }
        const Vec3 delta = channel.origin - listener_.origin;
        const double distance = std::sqrt(dot(delta, delta));
        const Vec3 direction = distance > 0.0 ? delta * (1.0 / distance) : Vec3{};
        const double pan = dot(listener_.screen_right, direction);
        const double attenuation = distance * static_cast<double>(channel.attenuation) / 64000.0;
        return {
            static_cast<float>(master * std::max(0.0, (1.0 - pan) * (1.0 - attenuation))),
            static_cast<float>(master * std::max(0.0, (1.0 + pan) * (1.0 - attenuation))),
        };
    }

    void mix_channel(QuakeMixChannel& channel, float& left, float& right)
    {
        if (!channel.active)
        {
            return;
        }
        const auto& wave = assets_.waves.at(channel.sound_slot);
        normalize_position(channel, wave);
        if (!channel.active)
        {
            return;
        }
        const auto first = static_cast<std::size_t>(channel.sample_position);
        std::size_t second = first + 1U;
        if (second >= wave.samples.size())
        {
            second = wave.loop_start.value_or(first);
        }
        const float fraction = static_cast<float>(channel.sample_position - static_cast<double>(first));
        const float sample = std::lerp(wave.samples[first], wave.samples[second], fraction);
        const auto [left_volume, right_volume] = spatial_volume(channel);
        left += sample * left_volume;
        right += sample * right_volume;
        channel.sample_position += static_cast<double>(wave.sample_rate) / kAudioOutputRate;
        normalize_position(channel, wave);
    }
};

std::uint64_t sound_read_u64(std::span<const std::uint8_t> bytes, std::size_t offset)
{
    require_range(bytes, offset, 8, "uint64");
    std::uint64_t result{};
    for (unsigned byte = 0; byte < 8; ++byte)
    {
        result |= static_cast<std::uint64_t>(bytes[offset + byte]) << (byte * 8U);
    }
    return result;
}

bool valid_quake_sound_name(std::string_view name)
{
    if (name.empty() || name.size() > 61 || name.front() == '/' || !name.ends_with(".wav") ||
        name.find(':') != std::string_view::npos || name.find('\\') != std::string_view::npos)
    {
        return false;
    }
    std::size_t begin{};
    while (begin <= name.size())
    {
        const auto end = name.find('/', begin);
        const auto part = name.substr(begin, end == std::string_view::npos ? name.size() - begin : end - begin);
        if (part.empty() || part == "." || part == "..")
        {
            return false;
        }
        if (end == std::string_view::npos)
        {
            break;
        }
        begin = end + 1U;
    }
    return std::ranges::all_of(name, [](unsigned char value) {
        return value >= 0x20 && value <= 0x7e && !std::isupper(value);
    });
}

QuakeSoundReplay parse_quake_sound_replay(std::span<const std::uint8_t> bytes)
{
    require_range(bytes, 0, kSoundReplayHeaderBytes, "QSR1 header");
    if (std::string_view(reinterpret_cast<const char*>(bytes.data()), 4) != "QSR1" ||
        read_u16(bytes, 4) != kSoundReplayVersion || read_u16(bytes, 6) == 0 || !std::isfinite(read_f32(bytes, 8)) ||
        read_f32(bytes, 8) < 0.0F || read_u32(bytes, 20) == 0 || read_u16(bytes, 30) != kSoundReplaySoundBytes ||
        read_u16(bytes, 32) != kSoundReplayEventBytes || read_u16(bytes, 34) == 0)
    {
        fail("QSR1 sound replay has an invalid header");
    }
    QuakeSoundReplay replay;
    replay.sample_rate = read_u16(bytes, 6);
    replay.first_server_time = read_f32(bytes, 8);
    replay.camera_fingerprint = sound_read_u64(bytes, 12);
    replay.camera_rows = read_u32(bytes, 20);
    const auto event_count = read_u32(bytes, 24);
    const auto sound_count = read_u16(bytes, 28);
    replay.view_entity = read_u16(bytes, 34);
    const std::size_t expected =
        kSoundReplayHeaderBytes + static_cast<std::size_t>(sound_count) * kSoundReplaySoundBytes +
        static_cast<std::size_t>(event_count) * kSoundReplayEventBytes;
    if (bytes.size() != expected)
    {
        fail("QSR1 sound replay byte count disagrees with its header");
    }
    std::size_t cursor = kSoundReplayHeaderBytes;
    replay.sounds.reserve(sound_count);
    std::uint16_t previous_precache{};
    for (std::uint16_t slot = 0; slot < sound_count; ++slot)
    {
        const auto precache = read_u16(bytes, cursor);
        const auto name_bytes = bytes[cursor + 2U];
        if (precache <= previous_precache || name_bytes == 0 || name_bytes > 61)
        {
            fail("QSR1 has a noncanonical sound record");
        }
        const std::string name(
            bytes.begin() + static_cast<std::ptrdiff_t>(cursor + 3U),
            bytes.begin() + static_cast<std::ptrdiff_t>(cursor + 3U + name_bytes)
        );
        if (!valid_quake_sound_name(name))
        {
            fail("QSR1 has an unsafe or unsupported sound name");
        }
        replay.sounds.push_back({precache, name});
        previous_precache = precache;
        cursor += kSoundReplaySoundBytes;
    }
    replay.events.reserve(event_count);
    std::int32_t previous_due = std::numeric_limits<std::int32_t>::min();
    for (std::uint32_t index = 0; index < event_count; ++index)
    {
        QuakeSoundEvent event;
        event.due_q16 = read_i32(bytes, cursor);
        event.kind = bytes[cursor + 4U];
        event.sound_slot = read_u16(bytes, cursor + 5U);
        event.entity = read_u16(bytes, cursor + 7U);
        event.channel = bytes[cursor + 9U];
        event.volume = bytes[cursor + 10U];
        event.attenuation = bytes[cursor + 11U];
        event.origin = {
            read_i16(bytes, cursor + 12U) / 8.0,
            read_i16(bytes, cursor + 14U) / 8.0,
            read_i16(bytes, cursor + 16U) / 8.0
        };
        event.source_record = read_u32(bytes, cursor + 18U);
        if (event.due_q16 < previous_due || event.channel > 7 ||
            (event.kind != kSoundEventStart && event.kind != kSoundEventStop && event.kind != kSoundEventStatic) ||
            (event.kind == kSoundEventStop && event.sound_slot != kNoSoundSlot) ||
            (event.kind != kSoundEventStop && event.sound_slot >= replay.sounds.size()))
        {
            fail("QSR1 has an invalid sound event");
        }
        replay.events.push_back(event);
        previous_due = event.due_q16;
        cursor += kSoundReplayEventBytes;
    }
    return replay;
}

bool sound_fourcc(std::span<const std::uint8_t> bytes, std::size_t offset, std::string_view value)
{
    return offset <= bytes.size() && value.size() <= bytes.size() - offset &&
           std::equal(value.begin(), value.end(), bytes.begin() + static_cast<std::ptrdiff_t>(offset));
}

QuakeWave parse_quake_wave(std::span<const std::uint8_t> bytes, std::string_view name)
{
    require_range(bytes, 0, 12, "WAV header");
    if (!sound_fourcc(bytes, 0, "RIFF") || !sound_fourcc(bytes, 8, "WAVE"))
    {
        fail("Quake sound is not RIFF/WAVE: " + std::string(name));
    }
    const auto riff_bytes = static_cast<std::size_t>(read_u32(bytes, 4));
    if (riff_bytes < 4 || riff_bytes > bytes.size() - 8U)
    {
        fail("Quake WAV RIFF bounds are invalid: " + std::string(name));
    }
    std::size_t fmt_offset{};
    std::size_t fmt_bytes{};
    std::size_t data_offset{};
    std::size_t data_bytes{};
    std::optional<std::size_t> loop_start;
    const std::size_t riff_end = 8U + riff_bytes;
    for (std::size_t chunk = 12; chunk + 8U <= riff_end;)
    {
        const auto chunk_bytes = static_cast<std::size_t>(read_u32(bytes, chunk + 4U));
        const auto payload = chunk + 8U;
        if (payload > riff_end || chunk_bytes > riff_end - payload)
        {
            // Several original id1 WAVs carry a malformed trailing LIST/INFO
            // size after a complete fmt/data pair. WinQuake ignores that
            // editor metadata, so retain the playable payload as well.
            if (fmt_offset != 0 && data_offset != 0)
            {
                break;
            }
            fail("Quake WAV chunk escapes RIFF: " + std::string(name));
        }
        if (sound_fourcc(bytes, chunk, "fmt "))
        {
            fmt_offset = payload;
            fmt_bytes = chunk_bytes;
        }
        else if (sound_fourcc(bytes, chunk, "data"))
        {
            data_offset = payload;
            data_bytes = chunk_bytes;
        }
        else if (sound_fourcc(bytes, chunk, "cue ") && chunk_bytes >= 28U && read_u32(bytes, payload) != 0)
        {
            loop_start = read_u32(bytes, payload + 24U);
        }
        chunk = payload + chunk_bytes + (chunk_bytes & 1U);
    }
    if (fmt_offset == 0 || fmt_bytes < 16 || data_offset == 0 || read_u16(bytes, fmt_offset) != 1 ||
        read_u16(bytes, fmt_offset + 2U) != 1)
    {
        fail("Quake WAV must be mono PCM: " + std::string(name));
    }
    const auto sample_rate = read_u32(bytes, fmt_offset + 4U);
    const auto bits = read_u16(bytes, fmt_offset + 14U);
    if (sample_rate == 0 || sample_rate > 192000 || (bits != 8 && bits != 16) || data_bytes % (bits / 8U) != 0)
    {
        fail("Quake WAV has unsupported PCM parameters: " + std::string(name));
    }
    QuakeWave wave;
    wave.sample_rate = static_cast<int>(sample_rate);
    const auto sample_count = data_bytes / (bits / 8U);
    wave.samples.reserve(sample_count);
    if (bits == 8)
    {
        for (std::size_t index = 0; index < sample_count; ++index)
        {
            wave.samples.push_back((static_cast<float>(bytes[data_offset + index]) - 128.0F) / 128.0F);
        }
    }
    else
    {
        for (std::size_t index = 0; index < sample_count; ++index)
        {
            wave.samples.push_back(static_cast<float>(read_i16(bytes, data_offset + index * 2U)) / 32768.0F);
        }
    }
    if (wave.samples.empty())
    {
        fail("Quake WAV contains no samples: " + std::string(name));
    }
    if (loop_start.has_value())
    {
        if (*loop_start >= wave.samples.size())
        {
            fail("Quake WAV loop point escapes samples: " + std::string(name));
        }
        wave.loop_start = loop_start;
    }
    return wave;
}

} // namespace

QuakeSoundAssets load_quake_sound_assets(
    const fs::path& replay_path,
    std::span<const std::uint8_t> pak_bytes,
    const fs::path& camera_track,
    std::size_t expected_rows,
    std::uint16_t expected_rate
)
{
    QuakeSoundAssets assets;
    assets.replay = parse_quake_sound_replay(read_file(replay_path));
    if (assets.replay.camera_fingerprint != brush_fnv1a64(read_file(camera_track)) ||
        assets.replay.camera_rows != expected_rows || assets.replay.sample_rate != expected_rate)
    {
        fail("QSR1 sound replay disagrees with the configured camera track");
    }
    assets.waves.reserve(assets.replay.sounds.size());
    for (const auto& sound : assets.replay.sounds)
    {
        const auto entry = "sound/" + sound.name;
        assets.waves.push_back(parse_quake_wave(extract_pak_entry(pak_bytes, entry), entry));
    }
    return assets;
}

namespace {

std::string sound_event_name(int kind)
{
    switch (kind)
    {
    case kSoundEventStart:
        return "start";
    case kSoundEventStop:
        return "stop";
    case kSoundEventStatic:
        return "static";
    default:
        return "none";
    }
}

enum class AudioCallbackFailure : std::uint8_t {
    none,
    stream_write,
    callback_exception,
};

class AudioCallbackFailureChannel
{
  public:
    void publish(AudioCallbackFailure failure) noexcept
    {
        auto expected = AudioCallbackFailure::none;
        failure_.compare_exchange_strong(expected, failure, std::memory_order_release, std::memory_order_relaxed);
    }

    [[nodiscard]] const char* message() const noexcept
    {
        switch (failure_.load(std::memory_order_acquire))
        {
        case AudioCallbackFailure::none:
            return nullptr;
        case AudioCallbackFailure::stream_write:
            return "SDL audio stream write failed";
        case AudioCallbackFailure::callback_exception:
            return "audio callback failed";
        }
        return nullptr;
    }

  private:
    std::atomic<AudioCallbackFailure> failure_{AudioCallbackFailure::none};
};

// The callback catch path can run after allocation failure. Keep its only
// reporting operation lock-free and statically nonthrowing on supported hosts.
static_assert(std::atomic<AudioCallbackFailure>::is_always_lock_free);
static_assert(noexcept(std::declval<AudioCallbackFailureChannel&>().publish(AudioCallbackFailure::callback_exception)));

} // namespace

class QuakeAudioSession::Impl
{
  public:
    explicit Impl(const QuakeSoundAssets* assets)
    :
    assets_(assets),
    mixer_(assets != nullptr ? std::make_unique<QuakeSoundMixer>(*assets) : nullptr)
    {
        if (assets_ == nullptr)
        {
            reason_ = "no sound replay configured";
            return;
        }
        if (!SDL_InitSubSystem(SDL_INIT_AUDIO))
        {
            reason_ = std::string("SDL audio unavailable: ") + SDL_GetError();
            return;
        }
        audio_subsystem_ = true;
        const SDL_AudioSpec spec{SDL_AUDIO_F32, 2, kAudioOutputRate};
        stream_ = SDL_OpenAudioDeviceStream(SDL_AUDIO_DEVICE_DEFAULT_PLAYBACK, &spec, audio_callback, this);
        if (stream_ == nullptr)
        {
            reason_ = std::string("cannot open SDL audio device: ") + SDL_GetError();
            return;
        }
        available_ = true;
        reason_ = "paused";
    }

    ~Impl()
    {
        shutdown();
    }

    void synchronize(
        double seconds,
        std::uint64_t loop,
        const ViewTransform& listener,
        bool enabled,
        float volume,
        bool timing_compatible,
        std::string incompatibility_reason,
        bool paused
    )
    {
        requested_enabled_ = enabled;
        requested_volume_ = std::clamp(volume, 0.0F, 1.0F);
        const bool should_mix = available_ && enabled && timing_compatible && !paused;
        bool resume{};
        bool pause{};
        if (stream_ != nullptr && SDL_LockAudioStream(stream_))
        {
            mixer_->set_listener(listener);
            mixer_->set_volume(requested_volume_);
            const bool discontinuity =
                loop != transport_loop_ || std::abs(mixer_->timeline_seconds() - seconds) > 0.20 ||
                (should_mix && !effective_);
            if (discontinuity)
            {
                mixer_->seek(seconds);
            }
            transport_loop_ = loop;
            mixer_->set_mixing(should_mix);
            resume = should_mix && !effective_;
            pause = !should_mix && effective_;
            effective_ = should_mix;
            SDL_UnlockAudioStream(stream_);
        }
        if (!available_)
        {
            return;
        }
        if (!enabled)
        {
            reason_ = "disabled";
        }
        else if (!timing_compatible)
        {
            reason_ = std::move(incompatibility_reason);
        }
        else if (paused)
        {
            reason_ = "paused";
        }
        else
        {
            reason_ = "playing";
        }
        if (pause && !SDL_PauseAudioStreamDevice(stream_))
        {
            device_error_ = SDL_GetError();
        }
        if (resume && !SDL_ResumeAudioStreamDevice(stream_))
        {
            device_error_ = SDL_GetError();
            effective_ = false;
            reason_ = "SDL audio resume failed";
        }
    }

    Json inspection()
    {
        const char* const callback_error = callback_error_.message();
        Json result{
            {"schema", "quake-reference-audio-inspection-v1"},
            {"configured", assets_ != nullptr},
            {"available", available_},
            {"enabled", requested_enabled_},
            {"effective", effective_},
            {"volume", requested_volume_},
            {"reason", reason_},
            {"outputRateHz", kAudioOutputRate},
            {"outputChannels", 2},
            {"deviceError", callback_error != nullptr ? callback_error : device_error_.c_str()}
        };
        if (assets_ == nullptr)
        {
            result["soundCount"] = 0;
            result["eventCount"] = 0;
            return result;
        }
        result["soundCount"] = assets_->waves.size();
        result["eventCount"] = assets_->replay.events.size();
        result["durationSeconds"] = assets_->replay.duration_seconds();
        if (stream_ != nullptr && SDL_LockAudioStream(stream_))
        {
            result["timelineSeconds"] = mixer_->timeline_seconds();
            result["mixedFrames"] = mixer_->mixed_frames();
            result["processedEvents"] = mixer_->processed_events();
            result["activeDynamicChannels"] = mixer_->active_dynamic();
            result["activeStaticChannels"] = mixer_->active_static();
            result["seekCount"] = mixer_->seek_count();
            result["mixedLoopCount"] = mixer_->mixed_loop_count();
            result["ignoredNonLoopingStaticSounds"] = mixer_->ignored_static_sounds();
            result["lastEvent"] = Json{
                {"kind", sound_event_name(mixer_->last_event_kind())},
                {"sourceRecord", mixer_->last_source_record()}
            };
            SDL_UnlockAudioStream(stream_);
        }
        return result;
    }

  private:
    const QuakeSoundAssets* assets_{};
    std::unique_ptr<QuakeSoundMixer> mixer_;
    SDL_AudioStream* stream_{};
    bool audio_subsystem_{};
    bool available_{};
    bool requested_enabled_{};
    bool effective_{};
    float requested_volume_{0.7F};
    std::uint64_t transport_loop_{};
    std::string reason_;
    std::string device_error_;
    AudioCallbackFailureChannel callback_error_;
    std::vector<float> callback_buffer_;

    void shutdown()
    {
        if (stream_ != nullptr)
        {
            SDL_DestroyAudioStream(stream_);
            stream_ = nullptr;
        }
        if (audio_subsystem_)
        {
            SDL_QuitSubSystem(SDL_INIT_AUDIO);
            audio_subsystem_ = false;
        }
    }

    static void SDLCALL audio_callback(void* userdata, SDL_AudioStream* stream, int additional_amount, int) noexcept
    {
        auto& self = *static_cast<Impl*>(userdata);
        if (additional_amount <= 0)
        {
            return;
        }
        try
        {
            const auto frames = static_cast<std::size_t>(
                (additional_amount + static_cast<int>(sizeof(float) * 2U) - 1) / static_cast<int>(sizeof(float) * 2U)
            );
            self.callback_buffer_.resize(frames * 2U);
            self.mixer_->mix(self.callback_buffer_);
            if (!SDL_PutAudioStreamData(
                    stream,
                    self.callback_buffer_.data(),
                    static_cast<int>(self.callback_buffer_.size() * sizeof(float))
                ))
            {
                self.callback_error_.publish(AudioCallbackFailure::stream_write);
            }
        }
        catch (...)
        {
            self.callback_error_.publish(AudioCallbackFailure::callback_exception);
        }
    }
};

QuakeAudioSession::QuakeAudioSession(const QuakeSoundAssets* assets)
:
impl_(std::make_unique<Impl>(assets))
{
}

QuakeAudioSession::~QuakeAudioSession() = default;

void QuakeAudioSession::synchronize(
    double seconds,
    std::uint64_t loop,
    const ViewTransform& listener,
    bool enabled,
    float volume,
    bool timing_compatible,
    std::string incompatibility_reason,
    bool paused
)
{
    impl_->synchronize(
        seconds,
        loop,
        listener,
        enabled,
        volume,
        timing_compatible,
        std::move(incompatibility_reason),
        paused
    );
}

Json QuakeAudioSession::inspection()
{
    return impl_->inspection();
}

namespace {

bool run_audio_callback_failure_self_test()
{
    AudioCallbackFailureChannel first_failure;
    first_failure.publish(AudioCallbackFailure::stream_write);
    first_failure.publish(AudioCallbackFailure::callback_exception);
    if (std::string_view(first_failure.message()) != "SDL audio stream write failed")
    {
        return false;
    }

    AudioCallbackFailureChannel concurrent_failure;
    std::atomic<bool> start{};
    std::atomic<bool> done{};
    std::jthread publisher([&] {
        while (!start.load(std::memory_order_acquire))
        {
            std::this_thread::yield();
        }
        concurrent_failure.publish(AudioCallbackFailure::callback_exception);
        done.store(true, std::memory_order_release);
    });
    start.store(true, std::memory_order_release);
    bool concurrent_read_valid = true;
    while (!done.load(std::memory_order_acquire))
    {
        const char* const observed = concurrent_failure.message();
        concurrent_read_valid =
            concurrent_read_valid && (observed == nullptr || std::string_view(observed) == "audio callback failed");
    }
    publisher.join();
    return concurrent_read_valid && std::string_view(concurrent_failure.message()) == "audio callback failed";
}

} // namespace

bool run_quake_audio_self_test()
{
    QuakeSoundAssets assets;
    assets.replay.sample_rate = 20;
    assets.replay.camera_rows = 40;
    assets.replay.view_entity = 1;
    assets.replay.sounds = {{1, "test/loop.wav"}, {2, "test/shot.wav"}};
    assets.replay.events = {
        {-32768, kSoundEventStatic, 0, 0, 0, 255, 64, {0, 0, 0}, 1},
        {0, kSoundEventStart, 1, 7, 2, 255, 64, {0, 0, 0}, 2},
        {32768, kSoundEventStop, kNoSoundSlot, 7, 2, 0, 0, {}, 3},
    };
    assets.waves = {
        {4, {0.5F, -0.5F, 0.25F, -0.25F}, 1U},
        {4, {1.0F, 0.5F, -0.5F, -1.0F}, std::nullopt},
    };
    QuakeSoundMixer mixer(assets);
    mixer.set_listener({{}, {1, 0, 0}, {0, -1, 0}, {0, 0, 1}});
    mixer.set_volume(1.0F);
    mixer.seek(0.0);
    mixer.set_mixing(true);
    std::array<float, 32> output{};
    mixer.mix(output);
    const bool audible = std::ranges::any_of(output, [](float sample) { return sample != 0.0F; });
    mixer.seek(1.0);
    return run_audio_callback_failure_self_test() && audible && mixer.processed_events() >= 3 &&
           mixer.active_dynamic() == 0 && mixer.active_static() == 1 && mixer.ignored_static_sounds() == 0;
}

} // namespace quake_bsp_reference
