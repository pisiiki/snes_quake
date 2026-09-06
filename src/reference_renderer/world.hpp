#pragma once

#include <algorithm>
#include <array>
#include <atomic>
#include <bit>
#include <chrono>
#include <cctype>
#include <cmath>
#include <compare>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <functional>
#include <iomanip>
#include <iostream>
#include <limits>
#include <map>
#include <memory>
#include <mutex>
#include <numbers>
#include <numeric>
#include <optional>
#include <set>
#include <span>
#include <sstream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <thread>
#include <tuple>
#include <utility>
#include <vector>

#include <CLI/CLI.hpp>
#include <SDL3/SDL.h>
#include <SDL3/SDL_main.h>
#include <imgui.h>
#include <imgui_impl_sdl3.h>
#include <imgui_impl_sdlrenderer3.h>
#include <nlohmann/json.hpp>

#include "vector_math.hpp"

#ifdef _WIN32
#define NOMINMAX
#include <windows.h>
#include <sddl.h>
#endif

namespace quake_bsp_reference {

namespace fs = std::filesystem;

using Json = nlohmann::ordered_json;

bool is_quake_sky_texture_name(std::string_view name);
bool is_quake_turbulent_texture_name(std::string_view name);

inline constexpr int kLogicalWidth = 128;
inline constexpr int kLogicalHeight = 112;
inline constexpr int kLogicalPixels = kLogicalWidth * kLogicalHeight;

constexpr std::size_t row_major_index(int x, int y, int row_width) noexcept
{
    const auto row = static_cast<std::ptrdiff_t>(y) * static_cast<std::ptrdiff_t>(row_width);
    return static_cast<std::size_t>(row + static_cast<std::ptrdiff_t>(x));
}

constexpr std::size_t logical_pixel_index(int x, int y) noexcept
{
    return row_major_index(x, y, kLogicalWidth);
}

inline constexpr double kFocalLength = 96.0;
inline constexpr double kWorldScale = 16.0;
inline constexpr double kFaceVisibilityEpsilon = 0.01;
inline constexpr double kHitTieEpsilon = 1e-7;
inline constexpr std::uint16_t kMissFace = 0xffff;
inline constexpr std::uint8_t kUnwrittenIndex = 0xcd;
inline constexpr int kBspVersion = 29;
inline constexpr int kBspLumpCount = 15;
inline constexpr int kLumpPlanes = 1;
inline constexpr int kLumpTextures = 2;
inline constexpr int kLumpVertices = 3;
inline constexpr int kLumpTexinfo = 6;
inline constexpr int kLumpFaces = 7;
inline constexpr int kLumpLighting = 8;
inline constexpr int kLumpEdges = 12;
inline constexpr int kLumpSurfEdges = 13;
inline constexpr int kLumpModels = 14;
inline constexpr int kPackedWorldVertexCount = 7216;
inline constexpr int kPackedWorldIndexCount = 21588;
inline constexpr int kPackedFaceRecordBytes = 6;
inline constexpr int kPackedFacePlaneRecordBytes = 5;
inline constexpr std::uint8_t kPackedFaceFlagNonDrawable = 0x01;
inline constexpr std::uint8_t kPackedFaceFlagPlaneCullGuard = 0x02;
inline constexpr std::uint8_t kPackedFaceKnownFlags = kPackedFaceFlagNonDrawable | kPackedFaceFlagPlaneCullGuard;
inline constexpr int kPackedTextureCoordinateBytes = 4;
inline constexpr int kPackedTextureDirectoryBytes = 8;
inline constexpr int kPackedRomBankBytes = 32768;
inline constexpr std::uint8_t kPackedTextureFlagPowerOfTwoAxes = 1;
inline constexpr std::uint8_t kPackedTextureFlagSingleBank = 2;
inline constexpr std::uint8_t kPackedTextureFlagTurbulent = 4;
inline constexpr int kQuakeColormapLevels = 64;
inline constexpr int kQuakePaletteColors = 256;
inline constexpr int kQuakeColormapBits = 6;
inline constexpr int kQuakeNeutralLightStyleScale = 12 * 22;

constexpr std::uint8_t exact_lightmap_colormap_level(std::uint8_t source_level) noexcept
{
    return source_level;
}

constexpr bool exact_lightmap_colormap_is_identity() noexcept
{
    for (int level = 0; level < kQuakeColormapLevels; ++level)
    {
        if (exact_lightmap_colormap_level(static_cast<std::uint8_t>(level)) != level)
        {
            return false;
        }
    }
    return true;
}
static_assert(exact_lightmap_colormap_is_identity());

using QuakeColormap = std::array<std::array<std::uint8_t, kQuakePaletteColors>, kQuakeColormapLevels>;

inline constexpr int kUntexturedRampColors = 64;
inline constexpr std::uint8_t kUntexturedBrightIndex = kUntexturedRampColors - 1;
inline constexpr std::uint8_t kUntexturedDiagnosticIndex = 239;
inline constexpr std::uint8_t kUntexturedQuakeTailFirstIndex = 240;
inline constexpr std::array<int, 32> kSinTable = {
    0, 12,  24,  36,  45,  53,  59,  63,  64,  63,  59,  53,  45,  36,  24,  12,
    0, -12, -24, -36, -45, -53, -59, -63, -64, -63, -59, -53, -45, -36, -24, -12,
};

inline constexpr std::array<int, 32> kCosTable = {
    64,  63,  59,  53,  45,  36,  24,  12,  0, -12, -24, -36, -45, -53, -59, -63,
    -64, -63, -59, -53, -45, -36, -24, -12, 0, 12,  24,  36,  45,  53,  59,  63,
};

struct Rgb
{
    std::uint8_t r{};
    std::uint8_t g{};
    std::uint8_t b{};

    auto operator<=>(const Rgb&) const = default;
};

constexpr std::uint8_t expand_five_bit_color(int value)
{
    return static_cast<std::uint8_t>((value * 255 + 15) / 31);
}

constexpr auto make_untextured_palette(const std::array<Rgb, kQuakePaletteColors>& texture_palette)
{
    auto result = texture_palette;
    std::fill(result.begin(), result.begin() + kUntexturedQuakeTailFirstIndex, Rgb{});
    for (int index = 0; index < kUntexturedRampColors; ++index)
    {
        // A strict RGB gray ramp has only 32 BGR555 colors. Walk the 93
        // individual channel increments instead, keeping channels within one
        // code of each other, to obtain 64 neutral-looking monotonic colors.
        const int channel_step = (index * (31 * 3) + (kUntexturedRampColors - 1) / 2) / (kUntexturedRampColors - 1);
        const int base = channel_step / 3;
        const int remainder = channel_step % 3;
        const int red = base + (remainder >= 1 ? 1 : 0);
        const int green = base + (remainder >= 2 ? 1 : 0);
        const int blue = base;
        result[static_cast<std::size_t>(index)] =
            {expand_five_bit_color(red), expand_five_bit_color(green), expand_five_bit_color(blue)};
    }
    // 64..238 are reserved black. Index 239 is deliberately conspicuous so
    // uncovered pixels and UI/background use cannot masquerade as geometry.
    // 240..255 retain the exact Quake palette tail because OBJ palette 7 owns
    // that CGRAM range in the SNES menu.
    result[kUntexturedDiagnosticIndex] = {255, 0, 255};
    return result;
}

inline constexpr std::array<Rgb, kQuakePaletteColors> kEmptyTexturePalette{};
inline constexpr auto kUntexturedPalette = make_untextured_palette(kEmptyTexturePalette);

constexpr std::uint8_t untextured_lightmap_index(std::uint8_t lightmap_level)
{
    return static_cast<std::uint8_t>(kUntexturedBrightIndex - std::min<int>(lightmap_level, kUntexturedRampColors - 1));
}

inline constexpr std::array<Rgb, 16> kPalette = {{
    {255, 0, 255},
    {36, 32, 40},
    {51, 42, 44},
    {67, 52, 48},
    {82, 62, 52},
    {97, 71, 57},
    {112, 81, 61},
    {128, 91, 65},
    {143, 101, 69},
    {158, 119, 83},
    {173, 137, 98},
    {188, 155, 112},
    {203, 174, 127},
    {218, 192, 141},
    {233, 210, 156},
    {248, 228, 170},
}};

inline constexpr int kTextureFamilyCount = 3;
inline constexpr int kPhysicalColorsPerFamily = 5;
inline constexpr int kApparentLightLevels = 9;
inline constexpr int kHueBinCount = 72;
inline constexpr double kMinimumFamilyHueSeparation = 38.0;

constexpr auto make_distance_shade_lut()
{
    std::array<std::array<std::uint8_t, 8>, kApparentLightLevels> result{};
    for (int base = 0; base < kApparentLightLevels; ++base)
    {
        for (int distance = 0; distance < 8; ++distance)
        {
            result[static_cast<std::size_t>(base)][static_cast<std::size_t>(distance)] =
                static_cast<std::uint8_t>((base * (10 - distance) + 5) / 10);
        }
    }
    return result;
}

inline constexpr auto kDistanceShadeLut = make_distance_shade_lut();

constexpr auto make_distance_bucket_lut()
{
    std::array<std::uint8_t, 128> result{};
    for (int distance = 0; distance < static_cast<int>(result.size()); ++distance)
    {
        result[static_cast<std::size_t>(distance)] = static_cast<std::uint8_t>(std::clamp((distance - 8) / 13, 0, 7));
    }
    return result;
}

inline constexpr auto kDistanceBucketLut = make_distance_bucket_lut();

[[noreturn]] void fail(const std::string& message);

void require_range(std::span<const std::uint8_t> bytes, std::size_t offset, std::size_t count, std::string_view label);

std::uint16_t read_u16(std::span<const std::uint8_t> bytes, std::size_t offset);

std::int16_t read_i16(std::span<const std::uint8_t> bytes, std::size_t offset);

std::int8_t decode_i8(std::uint8_t value);

std::int16_t wrap_i16(int value);

std::uint32_t read_u32(std::span<const std::uint8_t> bytes, std::size_t offset);

std::int32_t read_i32(std::span<const std::uint8_t> bytes, std::size_t offset);

float read_f32(std::span<const std::uint8_t> bytes, std::size_t offset);

std::vector<std::uint8_t> read_file(const fs::path& path);

void write_file(const fs::path& path, std::span<const std::uint8_t> bytes);

std::vector<std::uint8_t> extract_pak_entry(std::span<const std::uint8_t> bytes, std::string_view requested);

struct Lump
{
    std::size_t offset{};
    std::size_t bytes{};
};

struct Plane
{
    Vec3 normal;
    double distance{};
};

struct SourceFace
{
    int plane{};
    int side{};
    int first_edge{};
    int edge_count{};
    int texture_info{};
    std::array<std::uint8_t, 4> light_styles{255, 255, 255, 255};
    int light_offset{-1};
};

struct Edge
{
    std::uint16_t first{};
    std::uint16_t second{};
};

struct Model
{
    Vec3 mins;
    Vec3 maxs;
    Vec3 origin;
    int first_face{};
    int face_count{};
};

struct TextureEvidence
{
    std::array<std::uint32_t, 256> palette_pixels{};
    std::uint32_t pixel_count{};
};

struct MipTexture
{
    std::string name;
    std::uint32_t width{};
    std::uint32_t height{};
    std::vector<std::uint8_t> level_zero;
    bool present{};
    bool turbulent{};
};

struct TextureInfo
{
    Vec3 s_axis;
    double s_offset{};
    Vec3 t_axis;
    double t_offset{};
    int texture_id{};
};

struct BspData
{
    std::array<Rgb, 256> source_palette{};
    std::array<Rgb, 256> texture_palette{};
    QuakeColormap texture_colormap{};
    std::vector<Plane> planes;
    std::vector<Vec3> vertices;
    std::vector<MipTexture> textures;
    std::vector<TextureInfo> texture_infos;
    std::vector<TextureEvidence> texture_evidence;
    std::vector<std::uint8_t> texture_families;
    std::array<double, kTextureFamilyCount> texture_family_hues{};
    std::array<Rgb, 16> live_material_palette{};
    std::vector<std::uint8_t> lighting;
    std::vector<SourceFace> faces;
    std::vector<Edge> edges;
    std::vector<std::int32_t> surf_edges;
    std::vector<Model> models;
};

std::array<Rgb, 256> parse_quake_palette(std::span<const std::uint8_t> bytes);

QuakeColormap parse_quake_colormap(std::span<const std::uint8_t> bytes);

std::uint16_t snes_color_word(const Rgb& color);

std::array<Rgb, 256> make_snes_palette(const std::array<Rgb, 256>& source);

struct Hsv
{
    double hue{};
    double saturation{};
    double value{};
};

BspData
parse_bsp(std::span<const std::uint8_t> bsp, const std::array<Rgb, 256>& palette, const QuakeColormap& colormap);

struct FaceColor
{
    std::uint8_t flat{};
    std::uint8_t dither{};
};

double face_intensity(const Vec3& normal, const Vec3& centroid, const Vec3& bounds_min, const Vec3& bounds_max);

FaceColor shade_face(double intensity);

struct Aabb
{
    Vec3 minimum{
        std::numeric_limits<double>::infinity(),
        std::numeric_limits<double>::infinity(),
        std::numeric_limits<double>::infinity()
    };
    Vec3 maximum{
        -std::numeric_limits<double>::infinity(),
        -std::numeric_limits<double>::infinity(),
        -std::numeric_limits<double>::infinity()
    };

    void include(const Vec3& value)
    {
        minimum.x = std::min(minimum.x, value.x);
        minimum.y = std::min(minimum.y, value.y);
        minimum.z = std::min(minimum.z, value.z);
        maximum.x = std::max(maximum.x, value.x);
        maximum.y = std::max(maximum.y, value.y);
        maximum.z = std::max(maximum.z, value.z);
    }

    void include(const Aabb& value)
    {
        include(value.minimum);
        include(value.maximum);
    }
};

struct Triangle
{
    Vec3 first;
    Vec3 second;
    Vec3 third;
    Vec3 centroid;
    Aabb bounds;
    std::uint16_t face{};
    FaceColor color;
};

struct PackedCentroid
{
    std::int16_t x{};
    std::int16_t y{};
    std::int16_t z{};
};

struct PackedPlane
{
    std::int8_t x{};
    std::int8_t y{};
    std::int8_t z{};
    std::int16_t distance{};
};

struct PackedVertex
{
    std::int16_t x{};
    std::int16_t y{};
    std::int16_t z{};
};

struct PackedTextureCoordinate
{
    std::int16_t s_q4{};
    std::int16_t t_q4{};
};

struct FaceLightmap
{
    int texture_min_s{};
    int texture_min_t{};
    int width{};
    int height{};
    int light_offset{-1};
    std::uint8_t missing_level{kQuakeColormapLevels - 1};
    std::array<std::uint8_t, 4> styles{255, 255, 255, 255};
    int style_count{};
    bool precombined_compact_levels{};
};

struct SourceWorld
{
    Vec3 origin;
    Vec3 bounds_min;
    Vec3 bounds_max;
    int first_face{};
    int face_count{};
    int drawable_faces{};
    int packed_vertex_fraction_bits{};
    std::array<double, kTextureFamilyCount> texture_family_hues{};
    std::array<Rgb, 16> live_material_palette{};
    std::array<Rgb, 256> source_palette{};
    std::array<Rgb, 256> texture_palette{};
    std::array<Rgb, 256> untextured_palette{};
    QuakeColormap texture_colormap{};
    std::vector<MipTexture> textures;
    std::vector<TextureInfo> texture_infos;
    std::vector<int> face_texture_infos;
    std::vector<FaceLightmap> face_lightmaps;
    std::vector<std::uint8_t> lighting;
    std::vector<FaceColor> colors;
    std::vector<Plane> visibility_planes;
    std::vector<std::uint8_t> live_base_colors;
    std::vector<std::uint8_t> drawable_face_mask;
    std::vector<std::uint8_t> plane_cull_guard_mask;
    std::vector<PackedCentroid> centroids;
    std::vector<PackedPlane> packed_visibility_planes;
    std::vector<PackedVertex> packed_vertices;
    std::vector<std::vector<std::uint16_t>> face_vertex_ids;
    std::vector<std::vector<PackedTextureCoordinate>> face_texture_coordinates;
    std::vector<std::uint8_t> face_texture_ids;
    std::vector<std::uint8_t> face_sky_mask;
    std::vector<MipTexture> packed_textures;
    std::array<std::uint8_t, 128> turbulence_table{};
    std::vector<std::uint16_t> reciprocal_table;
    std::vector<Triangle> triangles;
};

void append_face_triangles(SourceWorld& world, std::span<const Vec3> polygon, std::uint16_t face, FaceColor color);

std::vector<Vec3> polygon_for_face(const BspData& bsp, const SourceFace& face);

FaceLightmap make_face_lightmap(
    const SourceFace& face,
    std::span<const Vec3> polygon,
    const TextureInfo& texture_info,
    std::string_view texture_name,
    std::size_t lighting_bytes
);

std::uint8_t orientation_light_level(const Vec3& normal);

SourceWorld build_source_world(const BspData& bsp);

SourceWorld build_quantized_world(const fs::path& data_dir, const SourceWorld& source);

} // namespace quake_bsp_reference
