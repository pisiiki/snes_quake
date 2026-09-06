#pragma once

#include "geometry.hpp"

namespace quake_bsp_reference {

struct QuakeSoundRecord
{
    std::uint16_t precache_index{};
    std::string name;
};

struct QuakeSoundEvent
{
    std::int32_t due_q16{};
    std::uint8_t kind{};
    std::uint16_t sound_slot{0xffff};
    std::uint16_t entity{};
    std::uint8_t channel{};
    std::uint8_t volume{};
    std::uint8_t attenuation{};
    Vec3 origin;
    std::uint32_t source_record{};

    double due_seconds() const
    {
        return static_cast<double>(due_q16) / 65536.0;
    }
};

struct QuakeSoundReplay
{
    std::uint16_t sample_rate{};
    float first_server_time{};
    std::uint64_t camera_fingerprint{};
    std::uint32_t camera_rows{};
    std::uint16_t view_entity{};
    std::vector<QuakeSoundRecord> sounds;
    std::vector<QuakeSoundEvent> events;

    double duration_seconds() const
    {
        return static_cast<double>(camera_rows) / sample_rate;
    }
};

struct QuakeWave
{
    int sample_rate{};
    std::vector<float> samples;
    std::optional<std::size_t> loop_start;
};

struct QuakeSoundAssets
{
    QuakeSoundReplay replay;
    std::vector<QuakeWave> waves;
};

QuakeSoundAssets load_quake_sound_assets(
    const fs::path& replay_path,
    std::span<const std::uint8_t> pak_bytes,
    const fs::path& camera_track,
    std::size_t expected_rows,
    std::uint16_t expected_rate
);

class QuakeAudioSession
{
  public:
    explicit QuakeAudioSession(const QuakeSoundAssets* assets);
    ~QuakeAudioSession();

    QuakeAudioSession(const QuakeAudioSession&) = delete;
    QuakeAudioSession& operator=(const QuakeAudioSession&) = delete;

    void synchronize(
        double seconds,
        std::uint64_t loop,
        const ViewTransform& listener,
        bool enabled,
        float volume,
        bool timing_compatible,
        std::string incompatibility_reason,
        bool paused
    );
    Json inspection();

  private:
    class Impl;
    std::unique_ptr<Impl> impl_;
};

bool run_quake_audio_self_test();

} // namespace quake_bsp_reference
