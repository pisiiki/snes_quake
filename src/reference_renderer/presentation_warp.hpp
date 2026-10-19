#pragma once

#include "geometry.hpp"

namespace quake_bsp_reference {

struct PresentationWarp
{
    int x{};
    int y{};
    int zoom{};
};

struct WarpSettings
{
    bool projective{true};
    double depth{192.0}; // Quake units along the rendered forward basis; zero means infinity.
    bool hdma{};
    int bands{16};
    std::vector<int> inverse_depth_profile;
};

inline thread_local WarpSettings active_warp_settings;
WarpSettings parse_warp_settings(std::string_view model, double depth, int bands = 16, std::vector<int> profile = {});
std::string_view warp_model_name(const WarpSettings& settings);

struct HdmaBand
{
    std::array<int, 8> registers{}; // A, B, C, D, X, Y, HOFS, VOFS.
    bool valid{};
    bool operator==(const HdmaBand&) const = default;
};
using HdmaWarp = std::vector<HdmaBand>;
HdmaWarp hdma_camera_warp(const ViewTransform& current, const ViewTransform& rendered, const WarpSettings& settings);
std::vector<std::uint32_t> present_hdma_x3(std::span<const std::uint32_t> pixels, const HdmaWarp& bands);
Json hdma_warp_json(const HdmaWarp& bands);
void run_hdma_warp_tests();

struct ProjectiveWarp
{
    // Row-major inverse homography: destination logical coordinates -> source.
    std::array<double, 9> inverse{1, 0, 0, 0, 1, 0, 0, 0, 1};
    bool valid{true};
    bool operator==(const ProjectiveWarp&) const = default;
};

ProjectiveWarp projective_camera_warp(const ViewTransform& current, const ViewTransform& rendered, double depth);
std::vector<std::uint32_t> present_projective_x3(std::span<const std::uint32_t> pixels, const ProjectiveWarp& warp);

PresentationWarp camera_warp(const ViewTransform& current, const ViewTransform& rendered);
std::vector<std::uint8_t> compact_viewport(std::span<const std::uint8_t> indices, RenderScale scale);
std::vector<std::uint32_t> present_x3(std::span<const std::uint32_t> pixels, PresentationWarp warp);
Json warp_camera_json(const ViewTransform& camera);
void run_presentation_warp_tests();

} // namespace quake_bsp_reference
