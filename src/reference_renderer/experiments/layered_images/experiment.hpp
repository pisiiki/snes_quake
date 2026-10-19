#pragma once
#include "geometry.hpp"
#include "presentation_warp.hpp"

namespace layered_images {
using namespace quake_bsp_reference;
using Clock = std::chrono::steady_clock;
inline double seconds(Clock::time_point start) { return std::chrono::duration<double>(Clock::now()-start).count(); }
inline constexpr int width = 85, height = 74;
inline constexpr int display_pixels = 256 * 224;
struct Sample {
    float depth{};
    std::array<float,3> normal{};
    std::uint32_t rgb{};
    std::uint16_t face{kMissFace};
    std::uint16_t reserved{};
};
static_assert(sizeof(Sample) == 24);
struct Capture {
    int padding{}, density{}, layers{}, w{}, h{};
    ViewTransform view;
    std::vector<Sample> samples;
    std::vector<std::uint32_t> source;
    Json metadata;
    const Sample& at(int layer, int x, int y) const {
        return samples.at(static_cast<std::size_t>((layer*h+y)*w+x));
    }
};
struct Image {
    std::vector<std::uint32_t> rgb = std::vector<std::uint32_t>(display_pixels);
    std::vector<float> depth = std::vector<float>(display_pixels, std::numeric_limits<float>::infinity());
    std::size_t samples{}, fragments{}, bytes{};
};
// Optional native cost-probe stream; absent in all quality measurements.
extern thread_local std::ofstream* native_stream;
extern thread_local std::map<std::uint32_t,std::uint16_t> native_palette;
Json read_json(const fs::path& path);
void save_json(const fs::path& path, const Json& data);
void save_rgb(const fs::path& path, std::span<const std::uint32_t> pixels);
std::vector<std::uint32_t> load_rgb(const fs::path& path);
ViewTransform json_view(const Json& value);
Json view_json(const ViewTransform& view);
void capture_job(const fs::path& pak, const Json& job, const fs::path& output);
Capture load_capture(const fs::path& output);
Image reproject(const Capture& capture, const ViewTransform& target, const Json& variant);
Json metrics(const Image& predicted, std::span<const std::uint32_t> target,
             std::span<const std::uint32_t> previous, std::span<const std::uint32_t> previous_target);
void evaluate_job(const fs::path& capture, const Json& variants, const fs::path& output, bool pictures);
void self_test();
void export_live_geometry(const fs::path& pak,const Json& job,const fs::path& output);
} // namespace layered_images
