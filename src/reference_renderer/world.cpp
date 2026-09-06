#include "world.hpp"

namespace quake_bsp_reference {

bool is_quake_sky_texture_name(std::string_view name)
{
    return name.size() >= 3 && name[0] == 's' && name[1] == 'k' && name[2] == 'y';
}

bool is_quake_turbulent_texture_name(std::string_view name)
{
    return name.starts_with("*");
}

static_assert(kQuakeColormapLevels == (1 << kQuakeColormapBits));

static_assert(kUntexturedPalette.front() == Rgb{0, 0, 0});
static_assert(kUntexturedPalette[kUntexturedBrightIndex] == Rgb{255, 255, 255});
static_assert(kUntexturedPalette[kUntexturedDiagnosticIndex] == Rgb{255, 0, 255});
static_assert(untextured_lightmap_index(0) == kUntexturedBrightIndex);
static_assert(untextured_lightmap_index(63) == 0);

// Index zero stays diagnostic pink. Three map-derived five-color ramps fill
// indices 1..15; solid/adjacent checker pairs yield nine apparent levels per
// family without allowing geometry to emit index zero.
static_assert(1 + kTextureFamilyCount * kPhysicalColorsPerFamily == 16);
static_assert(kApparentLightLevels == kPhysicalColorsPerFamily * 2 - 1);

[[noreturn]] void fail(const std::string& message)
{
    throw std::runtime_error(message);
}

void require_range(std::span<const std::uint8_t> bytes, std::size_t offset, std::size_t count, std::string_view label)
{
    if (offset > bytes.size() || count > bytes.size() - offset)
    {
        fail(std::string(label) + " escapes its containing file");
    }
}

std::uint16_t read_u16(std::span<const std::uint8_t> bytes, std::size_t offset)
{
    require_range(bytes, offset, 2, "uint16");
    return static_cast<std::uint16_t>(bytes[offset]) | static_cast<std::uint16_t>(bytes[offset + 1] << 8U);
}

std::int16_t read_i16(std::span<const std::uint8_t> bytes, std::size_t offset)
{
    return std::bit_cast<std::int16_t>(read_u16(bytes, offset));
}

std::int8_t decode_i8(std::uint8_t value)
{
    return std::bit_cast<std::int8_t>(value);
}

std::int16_t wrap_i16(int value)
{
    return std::bit_cast<std::int16_t>(static_cast<std::uint16_t>(value));
}

std::uint32_t read_u32(std::span<const std::uint8_t> bytes, std::size_t offset)
{
    require_range(bytes, offset, 4, "uint32");
    return static_cast<std::uint32_t>(bytes[offset]) | (static_cast<std::uint32_t>(bytes[offset + 1]) << 8U) |
           (static_cast<std::uint32_t>(bytes[offset + 2]) << 16U) |
           (static_cast<std::uint32_t>(bytes[offset + 3]) << 24U);
}

std::int32_t read_i32(std::span<const std::uint8_t> bytes, std::size_t offset)
{
    return std::bit_cast<std::int32_t>(read_u32(bytes, offset));
}

float read_f32(std::span<const std::uint8_t> bytes, std::size_t offset)
{
    return std::bit_cast<float>(read_u32(bytes, offset));
}

std::vector<std::uint8_t> read_file(const fs::path& path)
{
    std::ifstream stream(path, std::ios::binary | std::ios::ate);
    if (!stream)
    {
        fail("cannot open " + path.string());
    }
    const auto size = stream.tellg();
    if (size < 0)
    {
        fail("cannot determine the size of " + path.string());
    }
    std::vector<std::uint8_t> bytes(static_cast<std::size_t>(size));
    stream.seekg(0);
    if (!bytes.empty())
    {
        stream.read(reinterpret_cast<char*>(bytes.data()), size);
    }
    if (!stream)
    {
        fail("cannot read " + path.string());
    }
    return bytes;
}

void write_file(const fs::path& path, std::span<const std::uint8_t> bytes)
{
    if (!path.parent_path().empty())
    {
        fs::create_directories(path.parent_path());
    }
    std::ofstream stream(path, std::ios::binary);
    if (!stream)
    {
        fail("cannot create " + path.string());
    }
    if (!bytes.empty())
    {
        stream.write(reinterpret_cast<const char*>(bytes.data()), static_cast<std::streamsize>(bytes.size()));
    }
    if (!stream)
    {
        fail("cannot write " + path.string());
    }
}

namespace {
std::string pak_name(std::span<const std::uint8_t> bytes)
{
    const auto end = std::find(bytes.begin(), bytes.end(), std::uint8_t{0});
    return std::string(bytes.begin(), end);
}
} // namespace

std::vector<std::uint8_t> extract_pak_entry(std::span<const std::uint8_t> bytes, std::string_view requested)
{
    require_range(bytes, 0, 12, "PAK header");
    if (std::string_view(reinterpret_cast<const char*>(bytes.data()), 4) != "PACK")
    {
        fail("source file is not a Quake PAK");
    }
    const auto directory_offset = read_i32(bytes, 4);
    const auto directory_bytes = read_i32(bytes, 8);
    if (directory_offset < 0 || directory_bytes < 0 || directory_bytes % 64 != 0)
    {
        fail("PAK directory has invalid bounds");
    }
    require_range(
        bytes,
        static_cast<std::size_t>(directory_offset),
        static_cast<std::size_t>(directory_bytes),
        "PAK directory"
    );
    for (int offset = 0; offset < directory_bytes; offset += 64)
    {
        const auto record = static_cast<std::size_t>(directory_offset) + static_cast<std::size_t>(offset);
        const auto name = pak_name(bytes.subspan(record, 56));
        if (name != requested)
        {
            continue;
        }
        const auto entry_offset = read_i32(bytes, record + 56);
        const auto entry_bytes = read_i32(bytes, record + 60);
        if (entry_offset < 0 || entry_bytes < 0)
        {
            fail("PAK entry has invalid bounds: " + name);
        }
        require_range(bytes, static_cast<std::size_t>(entry_offset), static_cast<std::size_t>(entry_bytes), name);
        return std::vector<std::uint8_t>(bytes.begin() + entry_offset, bytes.begin() + entry_offset + entry_bytes);
    }
    fail("PAK does not contain " + std::string(requested));
}

namespace {
std::span<const std::uint8_t> lump_bytes(std::span<const std::uint8_t> bsp, const Lump& lump)
{
    require_range(bsp, lump.offset, lump.bytes, "BSP lump");
    return bsp.subspan(lump.offset, lump.bytes);
}
} // namespace

namespace {
void require_record_alignment(std::span<const std::uint8_t> bytes, std::size_t record_bytes, std::string_view label)
{
    if (bytes.size() % record_bytes != 0)
    {
        fail(std::string(label) + " is not record-aligned");
    }
}
} // namespace

std::array<Rgb, 256> parse_quake_palette(std::span<const std::uint8_t> bytes)
{
    if (bytes.size() != std::size_t{256} * 3U)
    {
        fail("gfx/palette.lmp must contain exactly 256 RGB colors");
    }
    std::array<Rgb, 256> palette{};
    for (std::size_t index = 0; index < palette.size(); ++index)
    {
        palette[index] = {bytes[index * 3], bytes[index * 3 + 1], bytes[index * 3 + 2]};
    }
    return palette;
}

QuakeColormap parse_quake_colormap(std::span<const std::uint8_t> bytes)
{
    constexpr std::size_t table_bytes =
        static_cast<std::size_t>(kQuakeColormapLevels) * static_cast<std::size_t>(kQuakePaletteColors);
    // The final byte records Quake's 32 fullbright colors. The remap table
    // itself already preserves those indices at every light level.
    if (bytes.size() != table_bytes + 1 || bytes.back() != 32)
    {
        fail(
            "gfx/colormap.lmp must contain 64 palette maps and the "
            "fullbright count"
        );
    }
    QuakeColormap colormap{};
    for (std::size_t level = 0; level < colormap.size(); ++level)
    {
        std::ranges::copy(bytes.subspan(level * kQuakePaletteColors, kQuakePaletteColors), colormap[level].begin());
    }
    return colormap;
}

namespace {
std::uint8_t snes_channel(std::uint8_t channel)
{
    const int quantized = (static_cast<int>(channel) * 31 + 127) / 255;
    return static_cast<std::uint8_t>((quantized * 255 + 15) / 31);
}
} // namespace

std::uint16_t snes_color_word(const Rgb& color)
{
    const auto quantize = [](std::uint8_t channel) {
        return (static_cast<std::uint16_t>(channel) * 31U + 127U) / 255U;
    };
    return static_cast<std::uint16_t>(quantize(color.r) | (quantize(color.g) << 5U) | (quantize(color.b) << 10U));
}

std::array<Rgb, 256> make_snes_palette(const std::array<Rgb, 256>& source)
{
    std::array<Rgb, 256> palette{};
    std::ranges::transform(source, palette.begin(), [](const Rgb& color) {
        return Rgb{snes_channel(color.r), snes_channel(color.g), snes_channel(color.b)};
    });
    return palette;
}

namespace {
double circular_hue_distance(double first, double second)
{
    const double direct = std::abs(first - second);
    return std::min(direct, 360.0 - direct);
}
} // namespace

namespace {
Hsv rgb_to_hsv(const Rgb& color)
{
    const int red = color.r;
    const int green = color.g;
    const int blue = color.b;
    const int maximum = std::max({red, green, blue});
    const int minimum = std::min({red, green, blue});
    const int delta = maximum - minimum;
    Hsv result;
    result.value = maximum / 255.0;
    if (maximum == 0)
    {
        return result;
    }
    result.saturation = static_cast<double>(delta) / maximum;
    if (delta == 0)
    {
        return result;
    }

    if (maximum == red)
    {
        result.hue = 60.0 * std::fmod(static_cast<double>(green - blue) / delta, 6.0);
    }
    else if (maximum == green)
    {
        result.hue = 60.0 * (static_cast<double>(blue - red) / delta + 2.0);
    }
    else
    {
        result.hue = 60.0 * (static_cast<double>(red - green) / delta + 4.0);
    }
    if (result.hue < 0.0)
    {
        result.hue += 360.0;
    }
    return result;
}
} // namespace

namespace {
std::uint8_t nearest_texture_family(double hue, const std::array<double, kTextureFamilyCount>& family_hues)
{
    std::size_t family = 0;
    double best_distance = circular_hue_distance(hue, family_hues[0]);
    for (std::size_t candidate = 1; candidate < family_hues.size(); ++candidate)
    {
        const double distance = circular_hue_distance(hue, family_hues[candidate]);
        if (distance < best_distance)
        {
            family = candidate;
            best_distance = distance;
        }
    }
    return static_cast<std::uint8_t>(family);
}
} // namespace

namespace {
std::vector<MipTexture> parse_mip_textures(std::span<const std::uint8_t> bytes)
{
    require_range(bytes, 0, 4, "texture lump header");
    const int texture_count = read_i32(bytes, 0);
    if (texture_count < 0 || static_cast<std::size_t>(texture_count) > (bytes.size() - 4) / 4)
    {
        fail("texture lump has an invalid texture count");
    }
    std::vector<MipTexture> textures(static_cast<std::size_t>(texture_count));
    for (int texture_id = 0; texture_id < texture_count; ++texture_id)
    {
        const auto texture_offset = read_i32(bytes, 4 + texture_id * 4);
        if (texture_offset < 0)
        {
            continue;
        }
        const auto offset = static_cast<std::size_t>(texture_offset);
        require_range(bytes, offset, 40, "mip texture header");
        const auto texture = bytes.subspan(offset);
        const auto name = pak_name(texture.first(16));
        const auto width = read_u32(texture, 16);
        const auto height = read_u32(texture, 20);
        const auto mip_offset = read_u32(texture, 24);
        if (width == 0 || height == 0 || width > std::numeric_limits<std::uint32_t>::max() / height)
        {
            fail("mip texture has invalid level-zero dimensions");
        }
        const auto pixel_count = static_cast<std::size_t>(width) * static_cast<std::size_t>(height);
        require_range(texture, mip_offset, pixel_count, "mip texture level zero");
        auto& parsed = textures[static_cast<std::size_t>(texture_id)];
        parsed.name = name;
        parsed.width = width;
        parsed.height = height;
        const auto first_pixel = texture.begin() + static_cast<std::ptrdiff_t>(mip_offset);
        parsed.level_zero.assign(first_pixel, first_pixel + static_cast<std::ptrdiff_t>(pixel_count));
        parsed.present = true;
        parsed.turbulent = is_quake_turbulent_texture_name(parsed.name);
    }
    return textures;
}
} // namespace

namespace {
std::vector<TextureEvidence> texture_evidence(std::span<const MipTexture> textures)
{
    std::vector<TextureEvidence> evidence(textures.size());
    for (std::size_t texture_id = 0; texture_id < textures.size(); ++texture_id)
    {
        auto& entry = evidence[texture_id];
        for (const auto palette_index : textures[texture_id].level_zero)
        {
            ++entry.palette_pixels[palette_index];
            ++entry.pixel_count;
        }
    }
    return evidence;
}
} // namespace

namespace {
double hue_bin_center(int bin)
{
    return (static_cast<double>(bin) + 0.5) * 360.0 / kHueBinCount;
}
} // namespace

namespace {
int hue_bin(double hue)
{
    return std::clamp(static_cast<int>(std::floor(hue * kHueBinCount / 360.0)), 0, kHueBinCount - 1);
}
} // namespace

namespace {
std::vector<std::uint32_t> count_texture_face_usage(const BspData& bsp)
{
    std::vector<std::uint32_t> usage(bsp.texture_evidence.size());
    for (const auto& face : bsp.faces)
    {
        if (face.texture_info < 0 || static_cast<std::size_t>(face.texture_info) >= bsp.texture_infos.size())
        {
            continue;
        }
        const int texture_id = bsp.texture_infos[static_cast<std::size_t>(face.texture_info)].texture_id;
        if (texture_id >= 0 && static_cast<std::size_t>(texture_id) < bsp.texture_evidence.size())
        {
            ++usage[static_cast<std::size_t>(texture_id)];
        }
    }
    return usage;
}
} // namespace

namespace {
std::array<double, kTextureFamilyCount> select_texture_family_hues(
    const BspData& bsp,
    const std::array<Rgb, 256>& palette,
    std::span<const std::uint32_t> face_usage
)
{
    std::array<double, kHueBinCount> histogram{};
    for (std::size_t texture_id = 0; texture_id < bsp.texture_evidence.size(); ++texture_id)
    {
        if (face_usage[texture_id] == 0)
        {
            continue;
        }
        std::array<double, kHueBinCount> texture_histogram{};
        double texture_weight{};
        const auto& evidence = bsp.texture_evidence[texture_id];
        for (std::size_t index = 0; index < palette.size(); ++index)
        {
            if (evidence.palette_pixels[index] == 0)
            {
                continue;
            }
            const auto hsv = rgb_to_hsv(palette[index]);
            if (hsv.value < 0.04 || hsv.saturation < 0.12)
            {
                continue;
            }
            const double weight =
                evidence.palette_pixels[index] * std::pow(hsv.saturation, 1.5) * std::pow(hsv.value, 0.6);
            texture_histogram[static_cast<std::size_t>(hue_bin(hsv.hue))] += weight;
            texture_weight += weight;
        }
        if (texture_weight <= 0.0)
        {
            continue;
        }
        const double scale = std::sqrt(face_usage[texture_id]) / texture_weight;
        for (std::size_t bin = 0; bin < histogram.size(); ++bin)
        {
            histogram[bin] += texture_histogram[bin] * scale;
        }
    }

    const double total_weight = std::accumulate(histogram.begin(), histogram.end(), 0.0);
    if (total_weight <= 0.0)
    {
        return {25.0, 70.0, 235.0};
    }

    std::array<double, kTextureFamilyCount> best_hues{25.0, 70.0, 235.0};
    double best_cost = std::numeric_limits<double>::infinity();
    for (int first = 0; first < kHueBinCount; ++first)
    {
        for (int second = first + 1; second < kHueBinCount; ++second)
        {
            for (int third = second + 1; third < kHueBinCount; ++third)
            {
                const std::array<double, kTextureFamilyCount> candidate =
                    {hue_bin_center(first), hue_bin_center(second), hue_bin_center(third)};
                if (std::min(
                        {circular_hue_distance(candidate[0], candidate[1]),
                         circular_hue_distance(candidate[0], candidate[2]),
                         circular_hue_distance(candidate[1], candidate[2])}
                    ) < kMinimumFamilyHueSeparation)
                {
                    continue;
                }
                double cost{};
                for (int bin = 0; bin < kHueBinCount; ++bin)
                {
                    if (histogram[static_cast<std::size_t>(bin)] == 0.0)
                    {
                        continue;
                    }
                    const double hue = hue_bin_center(bin);
                    const double distance = std::min(
                        {circular_hue_distance(hue, candidate[0]),
                         circular_hue_distance(hue, candidate[1]),
                         circular_hue_distance(hue, candidate[2])}
                    );
                    cost += histogram[static_cast<std::size_t>(bin)] * distance * distance;
                }
                if (cost < best_cost)
                {
                    best_cost = cost;
                    best_hues = candidate;
                }
            }
        }
    }
    return best_hues;
}
} // namespace

namespace {
std::array<double, kTextureFamilyCount> texture_family_fractions(
    const TextureEvidence& evidence,
    const std::array<Rgb, 256>& palette,
    const std::array<double, kTextureFamilyCount>& family_hues
)
{
    std::array<double, kTextureFamilyCount> fractions{};
    double considered_pixels{};
    for (std::size_t index = 0; index < palette.size(); ++index)
    {
        const auto pixels = evidence.palette_pixels[index];
        if (pixels == 0)
        {
            continue;
        }
        const auto hsv = rgb_to_hsv(palette[index]);
        if (hsv.value < 0.025 || hsv.saturation < 0.12)
        {
            continue;
        }
        fractions[nearest_texture_family(hsv.hue, family_hues)] += pixels;
        considered_pixels += pixels;
    }
    if (considered_pixels > 0.0)
    {
        for (auto& value : fractions)
        {
            value /= considered_pixels;
        }
    }
    return fractions;
}
} // namespace

namespace {
double weighted_quantile(std::vector<std::pair<double, double>>& samples, double quantile, double fallback)
{
    if (samples.empty())
    {
        return fallback;
    }
    std::sort(samples.begin(), samples.end(), [](const auto& first, const auto& second) {
        return first.first < second.first;
    });
    const double total = std::accumulate(samples.begin(), samples.end(), 0.0, [](double sum, const auto& sample) {
        return sum + sample.second;
    });
    const double target = total * quantile;
    double cumulative{};
    for (const auto& [value, weight] : samples)
    {
        cumulative += weight;
        if (cumulative >= target)
        {
            return value;
        }
    }
    return samples.back().first;
}
} // namespace

namespace {
Rgb hsv_to_rgb555(const Hsv& hsv)
{
    const double chroma = hsv.value * hsv.saturation;
    const double sector = hsv.hue / 60.0;
    const double secondary = chroma * (1.0 - std::abs(std::fmod(sector, 2.0) - 1.0));
    double red{};
    double green{};
    double blue{};
    switch (static_cast<int>(std::floor(sector)) % 6)
    {
    case 0:
        red = chroma;
        green = secondary;
        break;
    case 1:
        red = secondary;
        green = chroma;
        break;
    case 2:
        green = chroma;
        blue = secondary;
        break;
    case 3:
        green = secondary;
        blue = chroma;
        break;
    case 4:
        red = secondary;
        blue = chroma;
        break;
    default:
        red = chroma;
        blue = secondary;
        break;
    }
    const double match = hsv.value - chroma;
    const auto quantize = [&](double channel) {
        const int level = std::clamp(static_cast<int>(std::lround((channel + match) * 31.0)), 0, 31);
        return static_cast<std::uint8_t>((level * 255 + 15) / 31);
    };
    return {quantize(red), quantize(green), quantize(blue)};
}
} // namespace

namespace {
std::array<Rgb, 16> make_texture_material_palette(const std::array<Hsv, kTextureFamilyCount>& endpoints)
{
    constexpr std::array<double, kPhysicalColorsPerFamily> ramp_positions = {0.18, 0.32, 0.48, 0.70, 1.0};
    std::array<Rgb, 16> palette{};
    palette[0] = {255, 0, 255};
    constexpr double dark_value = 16.0 / 255.0;
    for (int family = 0; family < kTextureFamilyCount; ++family)
    {
        for (int step = 0; step < kPhysicalColorsPerFamily; ++step)
        {
            const double position = ramp_positions[static_cast<std::size_t>(step)];
            const auto& endpoint = endpoints[static_cast<std::size_t>(family)];
            const Hsv color{
                endpoint.hue,
                endpoint.saturation * (0.60 + 0.40 * position),
                dark_value + (endpoint.value - dark_value) * position,
            };
            const auto palette_index =
                std::size_t{1} + static_cast<std::size_t>(family) * kPhysicalColorsPerFamily +
                static_cast<std::size_t>(step);
            palette[palette_index] = hsv_to_rgb555(color);
        }
    }
    return palette;
}
} // namespace

namespace {
void assign_texture_families(BspData& bsp, const std::array<Rgb, 256>& palette)
{
    const auto face_usage = count_texture_face_usage(bsp);
    const auto used_texture_count = static_cast<std::size_t>(
        std::count_if(face_usage.begin(), face_usage.end(), [](std::uint32_t usage) { return usage != 0; })
    );
    if (used_texture_count == 0)
    {
        fail("BSP faces do not reference any embedded textures");
    }
    bsp.texture_family_hues = select_texture_family_hues(bsp, palette, face_usage);

    std::array<double, kTextureFamilyCount> baseline{};
    for (std::size_t texture_id = 0; texture_id < face_usage.size(); ++texture_id)
    {
        if (face_usage[texture_id] == 0)
        {
            continue;
        }
        const auto fractions =
            texture_family_fractions(bsp.texture_evidence[texture_id], palette, bsp.texture_family_hues);
        for (std::size_t family = 0; family < baseline.size(); ++family)
        {
            baseline[family] += fractions[family];
        }
    }
    for (auto& value : baseline)
    {
        value /= static_cast<double>(used_texture_count);
    }

    // Quake's dark brown ramp occurs in nearly every E1M3 texture. Relative
    // enrichment lets a texture's distinctive accents select its nearest
    // map-derived hue instead of letting that shared shadow ramp always win.
    constexpr double smoothing = 0.03;
    bsp.texture_families.resize(bsp.texture_evidence.size());
    for (std::size_t texture_id = 0; texture_id < bsp.texture_evidence.size(); ++texture_id)
    {
        const auto fractions =
            texture_family_fractions(bsp.texture_evidence[texture_id], palette, bsp.texture_family_hues);
        std::size_t best_family = 0;
        double best_score = (fractions[0] + smoothing) / (baseline[0] + smoothing);
        for (std::size_t family = 1; family < fractions.size(); ++family)
        {
            const double score = (fractions[family] + smoothing) / (baseline[family] + smoothing);
            if (score > best_score)
            {
                best_family = family;
                best_score = score;
            }
        }
        bsp.texture_families[texture_id] = static_cast<std::uint8_t>(best_family);
    }

    std::array<std::vector<std::pair<double, double>>, kTextureFamilyCount> saturation_samples;
    std::array<std::vector<std::pair<double, double>>, kTextureFamilyCount> value_samples;
    for (std::size_t texture_id = 0; texture_id < face_usage.size(); ++texture_id)
    {
        if (face_usage[texture_id] == 0)
        {
            continue;
        }
        const auto family = bsp.texture_families[texture_id];
        const auto& evidence = bsp.texture_evidence[texture_id];
        double aligned_pixels{};
        for (std::size_t index = 0; index < palette.size(); ++index)
        {
            const auto hsv = rgb_to_hsv(palette[index]);
            if (hsv.value >= 0.025 && hsv.saturation >= 0.12 &&
                circular_hue_distance(hsv.hue, bsp.texture_family_hues[family]) <= 50.0)
            {
                aligned_pixels += evidence.palette_pixels[index];
            }
        }
        if (aligned_pixels <= 0.0)
        {
            continue;
        }
        const double texture_scale = std::sqrt(face_usage[texture_id]) / aligned_pixels;
        for (std::size_t index = 0; index < palette.size(); ++index)
        {
            const auto pixels = evidence.palette_pixels[index];
            if (pixels == 0)
            {
                continue;
            }
            const auto hsv = rgb_to_hsv(palette[index]);
            if (hsv.value < 0.025 || hsv.saturation < 0.12 ||
                circular_hue_distance(hsv.hue, bsp.texture_family_hues[family]) > 50.0)
            {
                continue;
            }
            const double weight = pixels * texture_scale;
            saturation_samples[family].push_back({hsv.saturation, weight});
            value_samples[family].push_back({hsv.value, weight});
        }
    }

    std::array<Hsv, kTextureFamilyCount> endpoints{};
    for (std::size_t family = 0; family < endpoints.size(); ++family)
    {
        const double saturation = std::clamp(weighted_quantile(saturation_samples[family], 0.75, 0.58), 0.48, 0.72);
        const double source_bright = weighted_quantile(value_samples[family], 0.97, 0.38);
        endpoints[family] = {
            bsp.texture_family_hues[family],
            saturation,
            std::clamp(0.55 + 0.60 * source_bright, 0.74, 0.86),
        };
    }
    bsp.live_material_palette = make_texture_material_palette(endpoints);
}
} // namespace

BspData parse_bsp(std::span<const std::uint8_t> bsp, const std::array<Rgb, 256>& palette, const QuakeColormap& colormap)
{
    require_range(bsp, 0, 4 + kBspLumpCount * 8, "BSP header");
    if (read_i32(bsp, 0) != kBspVersion)
    {
        fail("expected a Quake version-29 BSP file");
    }
    std::array<Lump, kBspLumpCount> lumps{};
    for (int index = 0; index < kBspLumpCount; ++index)
    {
        const auto offset = read_i32(bsp, 4 + index * 8);
        const auto length = read_i32(bsp, 8 + index * 8);
        if (offset < 0 || length < 0)
        {
            fail("BSP lump has negative bounds");
        }
        lumps[index] = {static_cast<std::size_t>(offset), static_cast<std::size_t>(length)};
        require_range(bsp, lumps[index].offset, lumps[index].bytes, "BSP lump");
    }

    BspData result;
    result.source_palette = palette;
    result.texture_palette = make_snes_palette(palette);
    result.texture_colormap = colormap;
    result.textures = parse_mip_textures(lump_bytes(bsp, lumps[kLumpTextures]));
    result.texture_evidence = texture_evidence(result.textures);

    const auto plane_bytes = lump_bytes(bsp, lumps[kLumpPlanes]);
    require_record_alignment(plane_bytes, 20, "plane lump");
    for (std::size_t offset = 0; offset < plane_bytes.size(); offset += 20)
    {
        result.planes.push_back({
            {read_f32(plane_bytes, offset), read_f32(plane_bytes, offset + 4), read_f32(plane_bytes, offset + 8)},
            read_f32(plane_bytes, offset + 12),
        });
    }

    const auto vertex_bytes = lump_bytes(bsp, lumps[kLumpVertices]);
    require_record_alignment(vertex_bytes, 12, "vertex lump");
    for (std::size_t offset = 0; offset < vertex_bytes.size(); offset += 12)
    {
        result.vertices.push_back(
            {read_f32(vertex_bytes, offset), read_f32(vertex_bytes, offset + 4), read_f32(vertex_bytes, offset + 8)}
        );
    }

    const auto texture_info_bytes = lump_bytes(bsp, lumps[kLumpTexinfo]);
    require_record_alignment(texture_info_bytes, 40, "texture-info lump");
    for (std::size_t offset = 0; offset < texture_info_bytes.size(); offset += 40)
    {
        result.texture_infos.push_back({
            {read_f32(texture_info_bytes, offset),
             read_f32(texture_info_bytes, offset + 4),
             read_f32(texture_info_bytes, offset + 8)},
            read_f32(texture_info_bytes, offset + 12),
            {read_f32(texture_info_bytes, offset + 16),
             read_f32(texture_info_bytes, offset + 20),
             read_f32(texture_info_bytes, offset + 24)},
            read_f32(texture_info_bytes, offset + 28),
            read_i32(texture_info_bytes, offset + 32),
        });
    }

    const auto face_bytes = lump_bytes(bsp, lumps[kLumpFaces]);
    require_record_alignment(face_bytes, 20, "face lump");
    for (std::size_t offset = 0; offset < face_bytes.size(); offset += 20)
    {
        result.faces.push_back(
            {read_i16(face_bytes, offset),
             read_i16(face_bytes, offset + 2),
             read_i32(face_bytes, offset + 4),
             read_i16(face_bytes, offset + 8),
             read_i16(face_bytes, offset + 10),
             {face_bytes[offset + 12], face_bytes[offset + 13], face_bytes[offset + 14], face_bytes[offset + 15]},
             read_i32(face_bytes, offset + 16)}
        );
    }

    const auto lighting_bytes = lump_bytes(bsp, lumps[kLumpLighting]);
    result.lighting.assign(lighting_bytes.begin(), lighting_bytes.end());

    const auto edge_bytes = lump_bytes(bsp, lumps[kLumpEdges]);
    require_record_alignment(edge_bytes, 4, "edge lump");
    for (std::size_t offset = 0; offset < edge_bytes.size(); offset += 4)
    {
        result.edges.push_back({read_u16(edge_bytes, offset), read_u16(edge_bytes, offset + 2)});
    }

    const auto surf_edge_bytes = lump_bytes(bsp, lumps[kLumpSurfEdges]);
    require_record_alignment(surf_edge_bytes, 4, "surfedge lump");
    for (std::size_t offset = 0; offset < surf_edge_bytes.size(); offset += 4)
    {
        result.surf_edges.push_back(read_i32(surf_edge_bytes, offset));
    }

    const auto model_bytes = lump_bytes(bsp, lumps[kLumpModels]);
    require_record_alignment(model_bytes, 64, "model lump");
    for (std::size_t offset = 0; offset < model_bytes.size(); offset += 64)
    {
        result.models.push_back({
            {read_f32(model_bytes, offset), read_f32(model_bytes, offset + 4), read_f32(model_bytes, offset + 8)},
            {read_f32(model_bytes, offset + 12),
             read_f32(model_bytes, offset + 16),
             read_f32(model_bytes, offset + 20)},
            {read_f32(model_bytes, offset + 24),
             read_f32(model_bytes, offset + 28),
             read_f32(model_bytes, offset + 32)},
            read_i32(model_bytes, offset + 56),
            read_i32(model_bytes, offset + 60),
        });
    }
    if (result.models.empty())
    {
        fail("BSP contains no models");
    }
    assign_texture_families(result, palette);
    return result;
}

double face_intensity(const Vec3& normal, const Vec3& centroid, const Vec3& bounds_min, const Vec3& bounds_max)
{
    constexpr Vec3 light{2.0, -3.0, 5.0};
    constexpr Vec3 position_weights{0.18, -0.12, 0.20};
    const double normal_length = std::sqrt(length_squared(normal));
    const double light_length = std::sqrt(length_squared(light));
    if (normal_length <= 0.0)
    {
        fail("face has a zero source normal");
    }
    double lambert = dot(normal, light) / (normal_length * light_length);
    lambert = std::clamp(lambert, 0.0, 1.0);

    Vec3 normalized{};
    for (int axis = 0; axis < 3; ++axis)
    {
        const double span = bounds_max[axis] - bounds_min[axis];
        if (span <= 0.0)
        {
            fail("world bounds have a non-positive span");
        }
        const double value = (centroid[axis] - bounds_min[axis]) * 2.0 / span - 1.0;
        if (axis == 0)
        {
            normalized.x = std::clamp(value, -1.0, 1.0);
        }
        else if (axis == 1)
        {
            normalized.y = std::clamp(value, -1.0, 1.0);
        }
        else
        {
            normalized.z = std::clamp(value, -1.0, 1.0);
        }
    }
    double position_light = 0.5 + dot(position_weights, normalized);
    position_light = std::clamp(position_light, 0.0, 1.0);
    const double raw_intensity = 0.90 * lambert + 0.30 * position_light;
    return std::clamp((raw_intensity - 0.06) / 0.94, 0.0, 1.0);
}

FaceColor shade_face(double intensity)
{
    const int flat_level = std::min(14, static_cast<int>(std::floor(intensity * 14.0 + 0.5)));
    const int checker_level = std::min(28, static_cast<int>(std::floor(intensity * 28.0 + 0.5)));
    const int checker_low = 1 + checker_level / 2;
    const int checker_high = checker_low + checker_level % 2;
    return {static_cast<std::uint8_t>(1 + flat_level), static_cast<std::uint8_t>((checker_high << 4) | checker_low)};
}

void append_face_triangles(SourceWorld& world, std::span<const Vec3> polygon, std::uint16_t face, FaceColor color)
{
    std::vector<Vec3> cleaned;
    cleaned.reserve(polygon.size());
    for (const auto& vertex : polygon)
    {
        if (cleaned.empty() || !exactly_equal(cleaned.back(), vertex))
        {
            cleaned.push_back(vertex);
        }
    }
    if (cleaned.size() > 1 && exactly_equal(cleaned.front(), cleaned.back()))
    {
        cleaned.pop_back();
    }
    if (cleaned.size() < 3)
    {
        return;
    }
    for (std::size_t index = 1; index + 1 < cleaned.size(); ++index)
    {
        const auto edge_a = cleaned[index] - cleaned[0];
        const auto edge_b = cleaned[index + 1] - cleaned[0];
        if (length_squared(cross(edge_a, edge_b)) <= 1e-18)
        {
            continue;
        }
        Triangle triangle;
        triangle.first = cleaned[0];
        triangle.second = cleaned[index];
        triangle.third = cleaned[index + 1];
        triangle.centroid = (triangle.first + triangle.second + triangle.third) * (1.0 / 3.0);
        triangle.bounds.include(triangle.first);
        triangle.bounds.include(triangle.second);
        triangle.bounds.include(triangle.third);
        triangle.face = face;
        triangle.color = color;
        world.triangles.push_back(triangle);
    }
}

std::vector<Vec3> polygon_for_face(const BspData& bsp, const SourceFace& face)
{
    if (face.first_edge < 0 || face.edge_count < 0 ||
        static_cast<std::size_t>(face.first_edge) > bsp.surf_edges.size() ||
        static_cast<std::size_t>(face.edge_count) > bsp.surf_edges.size() - static_cast<std::size_t>(face.first_edge))
    {
        fail("source face has an invalid surfedge span");
    }
    std::vector<Vec3> polygon;
    polygon.reserve(static_cast<std::size_t>(face.edge_count));
    for (int index = 0; index < face.edge_count; ++index)
    {
        const auto surf_edge =
            bsp.surf_edges[static_cast<std::size_t>(face.first_edge) + static_cast<std::size_t>(index)];
        if (surf_edge == std::numeric_limits<std::int32_t>::min())
        {
            fail("source face uses INT_MIN as a surfedge");
        }
        const auto edge_index = static_cast<std::size_t>(std::abs(surf_edge));
        if (edge_index >= bsp.edges.size())
        {
            fail("source face references an invalid edge");
        }
        const auto edge = bsp.edges[edge_index];
        const auto vertex_index = surf_edge >= 0 ? edge.first : edge.second;
        if (vertex_index >= bsp.vertices.size())
        {
            fail("source edge references an invalid vertex");
        }
        polygon.push_back(bsp.vertices[vertex_index]);
    }
    return polygon;
}

FaceLightmap make_face_lightmap(
    const SourceFace& face,
    std::span<const Vec3> polygon,
    const TextureInfo& texture_info,
    std::string_view texture_name,
    std::size_t lighting_bytes
)
{
    if (polygon.empty())
    {
        fail("cannot derive lightmap bounds for an empty face");
    }
    double min_s = std::numeric_limits<double>::infinity();
    double min_t = std::numeric_limits<double>::infinity();
    double max_s = -std::numeric_limits<double>::infinity();
    double max_t = -std::numeric_limits<double>::infinity();
    for (const auto& vertex : polygon)
    {
        const double s = dot(texture_info.s_axis, vertex) + texture_info.s_offset;
        const double t = dot(texture_info.t_axis, vertex) + texture_info.t_offset;
        min_s = std::min(min_s, s);
        min_t = std::min(min_t, t);
        max_s = std::max(max_s, s);
        max_t = std::max(max_t, t);
    }
    const auto checked_block = [](double value, bool upper) {
        constexpr int minimum_block = std::numeric_limits<int>::min() / 16;
        constexpr int maximum_block = std::numeric_limits<int>::max() / 16;
        const double block = upper ? std::ceil(value / 16.0) : std::floor(value / 16.0);
        if (!std::isfinite(block) || block < static_cast<double>(minimum_block) ||
            block > static_cast<double>(maximum_block))
        {
            fail("source face has invalid lightmap bounds");
        }
        return static_cast<int>(block);
    };
    const int min_block_s = checked_block(min_s, false);
    const int min_block_t = checked_block(min_t, false);
    const int max_block_s = checked_block(max_s, true);
    const int max_block_t = checked_block(max_t, true);

    FaceLightmap lightmap;
    lightmap.texture_min_s = min_block_s * 16;
    lightmap.texture_min_t = min_block_t * 16;
    lightmap.width = max_block_s - min_block_s + 1;
    lightmap.height = max_block_t - min_block_t + 1;
    lightmap.light_offset = face.light_offset;
    lightmap.missing_level =
        is_quake_sky_texture_name(texture_name) || texture_name.starts_with("*") ? 0 : kQuakeColormapLevels - 1;
    lightmap.styles = face.light_styles;
    if (lightmap.width <= 0 || lightmap.height <= 0)
    {
        fail("source face has an empty lightmap grid");
    }

    bool terminated = false;
    for (const auto style : lightmap.styles)
    {
        if (style == 255)
        {
            terminated = true;
        }
        else if (terminated)
        {
            fail("source face has a light style after its terminator");
        }
        else
        {
            ++lightmap.style_count;
        }
    }
    if (lightmap.light_offset == -1)
    {
        if (lightmap.style_count != 0)
        {
            fail("unlightmapped source face has active light styles");
        }
        return lightmap;
    }
    if (lightmap.light_offset < 0 || lightmap.style_count == 0)
    {
        fail("source face has inconsistent lightmap metadata");
    }
    const auto samples = static_cast<std::size_t>(lightmap.width) * static_cast<std::size_t>(lightmap.height);
    const auto offset = static_cast<std::size_t>(lightmap.light_offset);
    const auto required = samples * static_cast<std::size_t>(lightmap.style_count);
    if (offset > lighting_bytes || required > lighting_bytes - offset)
    {
        fail("source face lightmap escapes the lighting lump");
    }
    return lightmap;
}

std::uint8_t orientation_light_level(const Vec3& normal)
{
    constexpr Vec3 light{2.0, -3.0, 5.0};
    const double normal_length = std::sqrt(length_squared(normal));
    const double light_length = std::sqrt(length_squared(light));
    if (normal_length <= 0.0)
    {
        fail("face has a zero source normal");
    }
    const double lambert = std::clamp(dot(normal, light) / (normal_length * light_length), 0.0, 1.0);
    const double brightness = 0.25 + 0.75 * lambert;
    return static_cast<std::uint8_t>(std::clamp(
        static_cast<int>(std::floor(brightness * (kApparentLightLevels - 1) + 0.5)),
        0,
        kApparentLightLevels - 1
    ));
}

namespace {
std::int16_t pack_centroid_coordinate(double coordinate, double origin)
{
    const auto packed = std::lround((coordinate - origin) / kWorldScale);
    if (packed < std::numeric_limits<std::int16_t>::min() || packed > std::numeric_limits<std::int16_t>::max())
    {
        fail("face centroid exceeds the signed 16-bit packed map range");
    }
    return static_cast<std::int16_t>(packed);
}
} // namespace

SourceWorld build_source_world(const BspData& bsp)
{
    const auto& model = bsp.models.front();
    if (model.first_face != 0 || model.face_count <= 0 || static_cast<std::size_t>(model.face_count) > bsp.faces.size())
    {
        fail("world-model face range is unsupported or invalid");
    }
    SourceWorld world;
    world.bounds_min = model.mins;
    world.bounds_max = model.maxs;
    world.origin = (model.mins + model.maxs) * 0.5;
    world.first_face = model.first_face;
    world.face_count = model.face_count;
    world.texture_family_hues = bsp.texture_family_hues;
    world.live_material_palette = bsp.live_material_palette;
    world.source_palette = bsp.source_palette;
    world.texture_palette = bsp.texture_palette;
    world.untextured_palette = make_untextured_palette(world.texture_palette);
    world.texture_colormap = bsp.texture_colormap;
    world.textures = bsp.textures;
    world.texture_infos = bsp.texture_infos;
    world.lighting = bsp.lighting;
    world.face_texture_infos.resize(static_cast<std::size_t>(model.face_count));
    world.face_sky_mask.resize(static_cast<std::size_t>(model.face_count));
    world.face_lightmaps.resize(static_cast<std::size_t>(model.face_count));
    world.colors.resize(static_cast<std::size_t>(model.face_count));
    world.visibility_planes.resize(static_cast<std::size_t>(model.face_count));
    world.live_base_colors.resize(static_cast<std::size_t>(model.face_count));
    world.centroids.resize(static_cast<std::size_t>(model.face_count));

    for (int local_face = 0; local_face < model.face_count; ++local_face)
    {
        const int source_face_id = model.first_face + local_face;
        const auto& face = bsp.faces[static_cast<std::size_t>(source_face_id)];
        if (face.plane < 0 || static_cast<std::size_t>(face.plane) >= bsp.planes.size())
        {
            fail("source face references an invalid plane");
        }
        if (face.texture_info < 0 || static_cast<std::size_t>(face.texture_info) >= bsp.texture_infos.size())
        {
            fail("source face references invalid texture information");
        }
        const auto texture_id = bsp.texture_infos[static_cast<std::size_t>(face.texture_info)].texture_id;
        if (texture_id < 0 || static_cast<std::size_t>(texture_id) >= bsp.texture_families.size() ||
            static_cast<std::size_t>(texture_id) >= bsp.textures.size() ||
            !bsp.textures[static_cast<std::size_t>(texture_id)].present)
        {
            fail("source face references an invalid embedded texture");
        }
        const auto local_face_index = static_cast<std::size_t>(local_face);
        world.face_texture_infos[local_face_index] = face.texture_info;
        world.face_sky_mask[local_face_index] = static_cast<std::uint8_t>(
            is_quake_sky_texture_name(bsp.textures[static_cast<std::size_t>(texture_id)].name)
        );
        const auto& texture_info = bsp.texture_infos[static_cast<std::size_t>(face.texture_info)];
        const auto texture_family = bsp.texture_families[static_cast<std::size_t>(texture_id)];
        auto polygon = polygon_for_face(bsp, face);
        if (polygon.empty())
        {
            continue;
        }
        world.face_lightmaps[local_face_index] = make_face_lightmap(
            face,
            polygon,
            texture_info,
            bsp.textures[static_cast<std::size_t>(texture_id)].name,
            bsp.lighting.size()
        );
        Vec3 centroid{};
        for (const auto& vertex : polygon)
        {
            centroid = centroid + vertex;
        }
        centroid = centroid * (1.0 / static_cast<double>(polygon.size()));
        const auto& source_plane = bsp.planes[static_cast<std::size_t>(face.plane)];
        auto normal = source_plane.normal;
        double plane_distance = source_plane.distance;
        if (face.side != 0)
        {
            normal = normal * -1.0;
            plane_distance = -plane_distance;
        }
        world.visibility_planes[static_cast<std::size_t>(local_face)] = {normal, plane_distance};
        const double intensity = face_intensity(normal, centroid, model.mins, model.maxs);
        const auto color = shade_face(intensity);
        world.colors[static_cast<std::size_t>(local_face)] = color;
        world.live_base_colors[static_cast<std::size_t>(local_face)] =
            static_cast<std::uint8_t>((texture_family << 4U) | orientation_light_level(normal));
        world.centroids[static_cast<std::size_t>(local_face)] = {
            pack_centroid_coordinate(centroid.x, world.origin.x),
            pack_centroid_coordinate(centroid.y, world.origin.y),
            pack_centroid_coordinate(centroid.z, world.origin.z),
        };

        append_face_triangles(world, polygon, static_cast<std::uint16_t>(local_face), color);
    }
    if (world.triangles.empty())
    {
        fail("world model produced no reference triangles");
    }
    return world;
}

SourceWorld build_quantized_world(const fs::path& data_dir, const SourceWorld& source)
{
    const auto vertex_bytes = read_file(data_dir / "QuakeBSPWorldVertices.bin");
    auto index_bytes = read_file(data_dir / "QuakeBSPWorldIndices0.bin");
    const auto second_indices = read_file(data_dir / "QuakeBSPWorldIndices1.bin");
    index_bytes.insert(index_bytes.end(), second_indices.begin(), second_indices.end());
    const auto face_bytes = read_file(data_dir / "QuakeBSPWorldFaces.bin");
    const auto plane_bytes = read_file(data_dir / "QuakeBSPWorldFacePlanes.bin");
    const auto reciprocal_bytes = read_file(data_dir / "QuakeBSPReciprocal.bin");
    auto texture_coordinate_bytes = read_file(data_dir / "QuakeBSPWorldTextureCoordinates0.bin");
    for (int chunk = 1; chunk < 3; ++chunk)
    {
        const auto next = read_file(data_dir / ("QuakeBSPWorldTextureCoordinates" + std::to_string(chunk) + ".bin"));
        texture_coordinate_bytes.insert(texture_coordinate_bytes.end(), next.begin(), next.end());
    }
    const auto face_texture_id_bytes = read_file(data_dir / "QuakeBSPWorldFaceTextureIds.bin");
    const auto texture_directory_bytes = read_file(data_dir / "QuakeBSPWorldTextureDirectory.bin");
    const auto turbulence_table_bytes = read_file(data_dir / "QuakeBSPTurbulenceTable.bin");
    std::vector<std::uint8_t> texture_pixel_bytes;
    for (int chunk = 0; chunk < 6; ++chunk)
    {
        const auto next = read_file(data_dir / ("QuakeBSPWorldTexturePixels" + std::to_string(chunk) + ".bin"));
        texture_pixel_bytes.insert(texture_pixel_bytes.end(), next.begin(), next.end());
    }
    if (vertex_bytes.empty() || vertex_bytes.size() % 4 != 0 || index_bytes.empty() || index_bytes.size() % 2 != 0 ||
        face_bytes.size() != static_cast<std::size_t>(source.face_count) * kPackedFaceRecordBytes ||
        plane_bytes.size() != static_cast<std::size_t>(source.face_count) * kPackedFacePlaneRecordBytes ||
        reciprocal_bytes.size() != 2048 ||
        texture_coordinate_bytes.size() != index_bytes.size() / 2 * kPackedTextureCoordinateBytes ||
        face_texture_id_bytes.size() != static_cast<std::size_t>(source.face_count) ||
        texture_directory_bytes.empty() || texture_directory_bytes.size() % kPackedTextureDirectoryBytes != 0 ||
        turbulence_table_bytes.size() != 128 ||
        texture_pixel_bytes.empty())
    {
        fail(
            "packed quantized-world stream has the wrong byte count: "
            "vertices=" +
            std::to_string(vertex_bytes.size()) + ", indices=" + std::to_string(index_bytes.size()) +
            ", faces=" + std::to_string(face_bytes.size()) + ", planes=" + std::to_string(plane_bytes.size()) +
            ", faceCount=" + std::to_string(source.face_count) +
            ", texcoords=" + std::to_string(texture_coordinate_bytes.size()) +
            ", faceTextureIds=" + std::to_string(face_texture_id_bytes.size()) +
            ", textureDirectory=" + std::to_string(texture_directory_bytes.size()) +
            ", texturePixels=" + std::to_string(texture_pixel_bytes.size())
        );
    }

    SourceWorld world;
    world.origin = source.origin;
    world.bounds_min = source.bounds_min;
    world.bounds_max = source.bounds_max;
    world.first_face = source.first_face;
    world.face_count = source.face_count;
    world.texture_family_hues = source.texture_family_hues;
    world.live_material_palette = source.live_material_palette;
    world.source_palette = source.source_palette;
    world.texture_palette = source.texture_palette;
    world.untextured_palette = source.untextured_palette;
    world.texture_colormap = source.texture_colormap;
    world.face_lightmaps = source.face_lightmaps;
    world.lighting = source.lighting;
    std::ranges::copy(turbulence_table_bytes, world.turbulence_table.begin());
    world.colors = source.colors;
    world.visibility_planes = source.visibility_planes;
    world.live_base_colors = source.live_base_colors;
    world.centroids = source.centroids;
    world.packed_visibility_planes.reserve(static_cast<std::size_t>(world.face_count));
    world.drawable_face_mask.resize(static_cast<std::size_t>(world.face_count));
    world.plane_cull_guard_mask.resize(static_cast<std::size_t>(world.face_count));
    world.packed_vertex_fraction_bits = 2;
    world.face_vertex_ids.resize(static_cast<std::size_t>(world.face_count));
    world.face_texture_coordinates.resize(static_cast<std::size_t>(world.face_count));
    world.face_texture_ids = face_texture_id_bytes;
    world.face_sky_mask = source.face_sky_mask;
    world.reciprocal_table.reserve(reciprocal_bytes.size() / 2);
    for (std::size_t offset = 0; offset < reciprocal_bytes.size(); offset += 2)
    {
        world.reciprocal_table.push_back(read_u16(reciprocal_bytes, offset));
    }

    std::uint8_t first_texture_bank = std::numeric_limits<std::uint8_t>::max();
    for (std::size_t offset = 0; offset < texture_directory_bytes.size(); offset += kPackedTextureDirectoryBytes)
    {
        first_texture_bank = std::min(first_texture_bank, texture_directory_bytes[offset]);
    }
    world.packed_textures.reserve(texture_directory_bytes.size() / kPackedTextureDirectoryBytes);
    for (std::size_t offset = 0; offset < texture_directory_bytes.size(); offset += kPackedTextureDirectoryBytes)
    {
        const auto bank = texture_directory_bytes[offset];
        const auto address = read_u16(texture_directory_bytes, offset + 1);
        const auto width = read_u16(texture_directory_bytes, offset + 3);
        const auto height = read_u16(texture_directory_bytes, offset + 5);
        const auto flags = texture_directory_bytes[offset + 7];
        auto expected_flags =
            std::has_single_bit(width) && std::has_single_bit(height)
                ? kPackedTextureFlagPowerOfTwoAxes
                : std::uint8_t{0};
        const auto pixel_count = static_cast<std::size_t>(width) * static_cast<std::size_t>(height);
        if ((address & 0x7fffU) + pixel_count <= kPackedRomBankBytes)
        {
            expected_flags |= kPackedTextureFlagSingleBank;
        }
        if ((flags & kPackedTextureFlagTurbulent) != 0)
        {
            expected_flags |= kPackedTextureFlagTurbulent;
            if (width != 64 || height != 64)
            {
                fail("packed turbulent texture is not 64x64");
            }
        }
        if (bank < first_texture_bank || address < 0x8000 || width == 0 || height == 0 || flags != expected_flags)
        {
            fail("packed exact-texture directory has an invalid record");
        }
        const auto pixel_offset =
            static_cast<std::size_t>(bank - first_texture_bank) * kPackedRomBankBytes + (address & 0x7fffU);
        require_range(texture_pixel_bytes, pixel_offset, pixel_count, "packed exact texture");
        MipTexture texture;
        texture.name = "packed-" + std::to_string(world.packed_textures.size());
        texture.width = width;
        texture.height = height;
        const auto first_pixel = texture_pixel_bytes.begin() + static_cast<std::ptrdiff_t>(pixel_offset);
        texture.level_zero.assign(first_pixel, first_pixel + static_cast<std::ptrdiff_t>(pixel_count));
        texture.present = true;
        texture.turbulent = (flags & kPackedTextureFlagTurbulent) != 0;
        world.packed_textures.push_back(std::move(texture));
    }

    std::vector<Vec3> vertices;
    vertices.reserve(vertex_bytes.size() / 4);
    world.packed_vertices.reserve(vertex_bytes.size() / 4);
    for (std::size_t offset = 0; offset < vertex_bytes.size(); offset += 4)
    {
        const int residual = vertex_bytes[offset + 3];
        const PackedVertex packed{
            static_cast<std::int16_t>(decode_i8(vertex_bytes[offset]) * 4 + (residual & 3)),
            static_cast<std::int16_t>(decode_i8(vertex_bytes[offset + 1]) * 4 + ((residual >> 2) & 3)),
            static_cast<std::int16_t>(decode_i8(vertex_bytes[offset + 2]) * 4 + ((residual >> 4) & 3)),
        };
        world.packed_vertices.push_back(packed);
        vertices.push_back(
            world.origin +
            Vec3{
                static_cast<double>(packed.x) * kWorldScale / 4.0,
                static_cast<double>(packed.y) * kWorldScale / 4.0,
                static_cast<double>(packed.z) * kWorldScale / 4.0
            }
        );
    }
    std::vector<std::uint16_t> indices;
    indices.reserve(index_bytes.size() / 2);
    for (std::size_t offset = 0; offset < index_bytes.size(); offset += 2)
    {
        const auto index = read_u16(index_bytes, offset);
        if (index >= vertices.size())
        {
            fail("packed quantized-world index escapes the vertex stream");
        }
        indices.push_back(index);
    }
    for (int face = 0; face < world.face_count; ++face)
    {
        const auto plane_offset = static_cast<std::size_t>(face) * kPackedFacePlaneRecordBytes;
        world.packed_visibility_planes.push_back(
            {decode_i8(plane_bytes[plane_offset]),
             decode_i8(plane_bytes[plane_offset + 1]),
             decode_i8(plane_bytes[plane_offset + 2]),
             read_i16(plane_bytes, plane_offset + 3)}
        );

        const auto face_offset = static_cast<std::size_t>(face) * kPackedFaceRecordBytes;
        const auto first_index = read_u16(face_bytes, face_offset);
        const auto vertex_count = face_bytes[face_offset + 2];
        const auto flags = face_bytes[face_offset + 5];
        if ((flags & ~kPackedFaceKnownFlags) != 0)
        {
            fail("packed face uses unknown flag bits");
        }
        if (vertex_count == 0)
        {
            if ((flags & kPackedFaceFlagNonDrawable) == 0 || (flags & kPackedFaceFlagPlaneCullGuard) != 0)
            {
                fail("packed non-drawable face is missing its reject flag");
            }
            continue;
        }
        if (vertex_count < 3 || (flags & kPackedFaceFlagNonDrawable) != 0 || first_index > indices.size() ||
            vertex_count > indices.size() - first_index)
        {
            fail("packed drawable face has an invalid index span");
        }
        ++world.drawable_faces;
        world.drawable_face_mask[static_cast<std::size_t>(face)] = 1;
        world.plane_cull_guard_mask[static_cast<std::size_t>(face)] =
            static_cast<std::uint8_t>((flags & kPackedFaceFlagPlaneCullGuard) != 0);
        std::vector<Vec3> polygon;
        polygon.reserve(vertex_count);
        auto& face_vertices = world.face_vertex_ids[static_cast<std::size_t>(face)];
        face_vertices.reserve(vertex_count);
        auto& face_coordinates = world.face_texture_coordinates[static_cast<std::size_t>(face)];
        face_coordinates.reserve(vertex_count);
        for (std::size_t index = first_index; index < static_cast<std::size_t>(first_index) + vertex_count; ++index)
        {
            polygon.push_back(vertices[indices[index]]);
            face_vertices.push_back(indices[index]);
            const auto coordinate_offset = index * kPackedTextureCoordinateBytes;
            face_coordinates.push_back(
                {read_i16(texture_coordinate_bytes, coordinate_offset),
                 read_i16(texture_coordinate_bytes, coordinate_offset + 2)}
            );
        }
        append_face_triangles(
            world,
            polygon,
            static_cast<std::uint16_t>(face),
            world.colors[static_cast<std::size_t>(face)]
        );
    }
    if (world.triangles.empty())
    {
        fail("packed quantized world produced no reference triangles");
    }
    return world;
}

} // namespace quake_bsp_reference
