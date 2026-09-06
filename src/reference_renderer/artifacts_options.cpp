#include "artifacts_options.hpp"
#include "world.hpp"
#include "geometry.hpp"
#include "instrumentation.hpp"
#include "textured_live.hpp"
#include "live_demo.hpp"

namespace quake_bsp_reference {

namespace {
void store_u16(std::vector<std::uint8_t>& bytes, std::size_t offset, std::uint16_t value)
{
    bytes[offset] = static_cast<std::uint8_t>(value & 0xffU);
    bytes[offset + 1] = static_cast<std::uint8_t>(value >> 8U);
}
} // namespace

namespace {
void store_u32(std::vector<std::uint8_t>& bytes, std::size_t offset, std::uint32_t value)
{
    bytes[offset] = static_cast<std::uint8_t>(value & 0xffU);
    bytes[offset + 1] = static_cast<std::uint8_t>((value >> 8U) & 0xffU);
    bytes[offset + 2] = static_cast<std::uint8_t>((value >> 16U) & 0xffU);
    bytes[offset + 3] = static_cast<std::uint8_t>(value >> 24U);
}
} // namespace

namespace {
void write_bmp(const fs::path& path, std::span<const Rgb> pixels, int width, int height)
{
    if (width <= 0 || height <= 0)
    {
        fail("BMP dimensions must be positive");
    }
    const auto pixel_count = static_cast<std::size_t>(width) * static_cast<std::size_t>(height);
    if (pixels.size() != pixel_count)
    {
        fail("BMP pixel count disagrees with its dimensions");
    }
    const auto row_bytes = (static_cast<std::size_t>(width) * 3U + 3U) & ~std::size_t{3};
    const auto pixel_bytes = row_bytes * static_cast<std::size_t>(height);
    std::vector<std::uint8_t> bytes(54 + pixel_bytes, 0);
    bytes[0] = 'B';
    bytes[1] = 'M';
    store_u32(bytes, 2, static_cast<std::uint32_t>(bytes.size()));
    store_u32(bytes, 10, 54);
    store_u32(bytes, 14, 40);
    store_u32(bytes, 18, static_cast<std::uint32_t>(width));
    store_u32(bytes, 22, static_cast<std::uint32_t>(height));
    store_u16(bytes, 26, 1);
    store_u16(bytes, 28, 24);
    store_u32(bytes, 34, static_cast<std::uint32_t>(pixel_bytes));
    for (int y = 0; y < height; ++y)
    {
        const int source_y = height - 1 - y;
        const auto row = std::size_t{54} + static_cast<std::size_t>(y) * row_bytes;
        for (int x = 0; x < width; ++x)
        {
            const auto color = pixels[row_major_index(x, source_y, width)];
            const auto offset = row + static_cast<std::size_t>(x) * 3U;
            bytes[offset] = color.b;
            bytes[offset + 1] = color.g;
            bytes[offset + 2] = color.r;
        }
    }
    write_file(path, bytes);
}
} // namespace

namespace {
void write_index_outputs(
    const fs::path& prefix,
    std::string_view layer_suffix,
    std::span<const std::uint8_t> indices,
    std::span<const Rgb> palette
)
{
    const auto suffix = std::string(layer_suffix);
    write_file(with_suffix(prefix, suffix + ".idx"), indices);
    std::vector<Rgb> pixels;
    pixels.reserve(indices.size());
    for (const auto index : indices)
    {
        if (index >= palette.size())
        {
            fail("reference index escapes its palette");
        }
        pixels.push_back(palette[index]);
    }
    write_bmp(with_suffix(prefix, suffix + ".bmp"), pixels, kLogicalWidth, kLogicalHeight);
    std::vector<Rgb> native_pixels(std::size_t{256} * 224U);
    for (int y = 0; y < kLogicalHeight; ++y)
    {
        for (int x = 0; x < kLogicalWidth; ++x)
        {
            const auto color = pixels[logical_pixel_index(x, y)];
            const int native_x = x * 2;
            const int native_y = y * 2;
            native_pixels[row_major_index(native_x, native_y, 256)] = color;
            native_pixels[row_major_index(native_x + 1, native_y, 256)] = color;
            native_pixels[row_major_index(native_x, native_y + 1, 256)] = color;
            native_pixels[row_major_index(native_x + 1, native_y + 1, 256)] = color;
        }
    }
    write_bmp(with_suffix(prefix, suffix + ".native.bmp"), native_pixels, 256, 224);
}
} // namespace

namespace {
fs::path quake_sky_inspection_path(const fs::path& indices_path)
{
    return with_suffix(indices_path, ".json");
}
} // namespace

void write_quake_sky_artifacts(
    const fs::path& indices_path,
    std::span<const std::uint8_t> indices,
    const Json& inspection
)
{
    if (indices.size() != kLogicalPixels)
    {
        fail(
            "authentic Quake sky presentation must contain exactly 14336 "
            "bytes"
        );
    }
    write_file(indices_path, indices);
    const auto inspection_path = quake_sky_inspection_path(indices_path);
    std::ofstream output(inspection_path);
    if (!output)
    {
        fail("cannot create " + inspection_path.string());
    }
    output << inspection.dump(2) << '\n';
    if (!output)
    {
        fail("cannot write " + inspection_path.string());
    }
}

namespace {
void write_u16_plane(const fs::path& path, std::span<const std::uint16_t> values)
{
    std::vector<std::uint8_t> bytes(values.size() * 2);
    for (std::size_t index = 0; index < values.size(); ++index)
    {
        bytes[index * 2] = static_cast<std::uint8_t>(values[index] & 0xffU);
        bytes[index * 2 + 1] = static_cast<std::uint8_t>(values[index] >> 8U);
    }
    write_file(path, bytes);
}
} // namespace

void write_reference_outputs(const fs::path& prefix, const ReferenceFrame& frame, const SourceWorld& world)
{
    if (frame.material_indices.size() != frame.indices.size())
    {
        fail("reference frame is missing its material layer");
    }
    write_index_outputs(prefix, "", frame.indices, kPalette);
    write_index_outputs(prefix, ".material", frame.material_indices, world.live_material_palette);
    if (!frame.texture_indices.empty())
    {
        if (frame.texture_indices.size() != frame.indices.size() || frame.texture_s.size() != frame.indices.size() ||
            frame.texture_t.size() != frame.indices.size() ||
            frame.lightmap_texture_indices.size() != frame.indices.size() ||
            frame.lightmap_texture_levels.size() != frame.indices.size() ||
            frame.untextured_lightmap_indices.size() != frame.indices.size())
        {
            fail("reference frame has an invalid exact texture layer");
        }
        write_index_outputs(prefix, ".texture", frame.texture_indices, world.texture_palette);
        write_index_outputs(prefix, ".texture-lightmap", frame.lightmap_texture_indices, world.texture_palette);
        write_file(with_suffix(prefix, ".texture-lightmap.levels"), frame.lightmap_texture_levels);
        write_index_outputs(
            prefix,
            ".untextured-lightmap",
            frame.untextured_lightmap_indices,
            world.untextured_palette
        );
    }
    write_u16_plane(with_suffix(prefix, ".faces"), frame.faces);
}

void write_brush_ownership_outputs(const fs::path& prefix, const ReferenceFrame& frame)
{
    if (frame.entities.size() != frame.faces.size() || frame.models.size() != frame.faces.size())
    {
        fail("brush frame is missing its entity/model ownership planes");
    }
    write_u16_plane(with_suffix(prefix, ".entities"), frame.entities);
    write_u16_plane(with_suffix(prefix, ".models"), frame.models);
}

void write_raster_outputs(const fs::path& prefix, const RasterResult& result, const SourceWorld& world)
{
    if (result.frame.material_indices.size() != result.frame.faces.size())
    {
        fail("raster frame is missing its material layer");
    }
    write_index_outputs(prefix, "", result.frame.material_indices, world.live_material_palette);
    std::vector<std::uint8_t> faces(result.frame.faces.size() * 2);
    for (std::size_t index = 0; index < result.frame.faces.size(); ++index)
    {
        faces[index * 2] = static_cast<std::uint8_t>(result.frame.faces[index] & 0xffU);
        faces[index * 2 + 1] = static_cast<std::uint8_t>(result.frame.faces[index] >> 8U);
    }
    write_file(with_suffix(prefix, ".faces"), faces);
}

namespace {
std::vector<std::uint8_t> encode_i16_plane(std::span<const std::int16_t> values)
{
    std::vector<std::uint8_t> bytes(values.size() * 2);
    for (std::size_t index = 0; index < values.size(); ++index)
    {
        store_u16(bytes, index * 2, std::bit_cast<std::uint16_t>(values[index]));
    }
    return bytes;
}
} // namespace

void write_packed_texture_outputs(const fs::path& prefix, const PackedTextureRaster& result, const SourceWorld& world)
{
    if (result.indices.size() != kLogicalPixels || result.lightmapped_indices.size() != kLogicalPixels ||
        result.lightmap_levels.size() != kLogicalPixels ||
        result.untextured_lightmap_indices.size() != kLogicalPixels || result.faces.size() != kLogicalPixels ||
        result.s_q4.size() != kLogicalPixels || result.t_q4.size() != kLogicalPixels ||
        result.absolute_s_q4.size() != kLogicalPixels || result.absolute_t_q4.size() != kLogicalPixels ||
        result.depth_q6.size() != kLogicalPixels)
    {
        fail("packed texture raster has an invalid plane size");
    }
    write_index_outputs(prefix, "", result.indices, world.texture_palette);
    write_index_outputs(with_suffix(prefix, ".lightmapped"), "", result.lightmapped_indices, world.texture_palette);
    write_file(with_suffix(prefix, ".lightmapped.levels"), result.lightmap_levels);
    write_index_outputs(
        with_suffix(prefix, ".untextured-lightmap"),
        "",
        result.untextured_lightmap_indices,
        world.untextured_palette
    );
    std::vector<std::uint8_t> faces(result.faces.size() * 2);
    for (std::size_t index = 0; index < result.faces.size(); ++index)
    {
        store_u16(faces, index * 2, result.faces[index]);
    }
    write_file(with_suffix(prefix, ".faces"), faces);
    write_file(with_suffix(prefix, ".s-q4"), encode_i16_plane(result.s_q4));
    write_file(with_suffix(prefix, ".t-q4"), encode_i16_plane(result.t_q4));
    write_file(with_suffix(prefix, ".absolute-s-q4"), encode_i16_plane(result.absolute_s_q4));
    write_file(with_suffix(prefix, ".absolute-t-q4"), encode_i16_plane(result.absolute_t_q4));
    write_file(with_suffix(prefix, ".depth-q6"), encode_i16_plane(result.depth_q6));
    Json spans = Json::array();
    for (const auto& span : result.spans)
    {
        spans.push_back(
            {{"face", span.face},
             {"arbitrationGroup", span.arbitration_group},
             {"candidateSerial", span.candidate_serial},
             {"y", span.y},
             {"firstX", span.first_x},
             {"lastX", span.last_x},
             {"leftSQ4", span.left_s_q4},
             {"leftTQ4", span.left_t_q4},
             {"rightSQ4", span.right_s_q4},
             {"rightTQ4", span.right_t_q4},
             {"leftXQ7", span.left_x_q7},
             {"rightXQ7", span.right_x_q7},
             {"leftDepthQ6", span.left_depth_q6},
             {"rightDepthQ6", span.right_depth_q6}}
        );
    }
    std::ofstream span_output(with_suffix(prefix, ".spans.json"));
    if (!span_output)
    {
        fail("cannot write packed texture span transcript");
    }
    span_output << Json{{"schema", "quake-packed-texture-spans-v1"}, {"records", spans}}.dump(2) << '\n';
}

void write_packed_brush_outputs(const fs::path& prefix, const PackedTextureRaster& result, const SourceWorld& world)
{
    write_packed_texture_outputs(prefix, result, world);
    if (result.entities.size() != kLogicalPixels || result.models.size() != kLogicalPixels ||
        result.arbitration_depth_q6.size() != kLogicalPixels)
    {
        fail("packed brush raster is missing ownership planes");
    }
    write_u16_plane(with_suffix(prefix, ".entities"), result.entities);
    write_u16_plane(with_suffix(prefix, ".models"), result.models);
    write_file(with_suffix(prefix, ".arbitration-depth-q6"), encode_i16_plane(result.arbitration_depth_q6));
}

void write_owner_diff(
    const fs::path& path,
    const ReferenceFrame& before,
    const ReferenceFrame& after,
    std::span<const Rgb> palette
)
{
    if (before.faces.size() != after.faces.size() || before.material_indices.size() != before.faces.size() ||
        after.material_indices.size() != after.faces.size())
    {
        fail("owner-difference frames disagree");
    }
    std::vector<Rgb> pixels;
    pixels.reserve(before.faces.size());
    for (std::size_t index = 0; index < before.faces.size(); ++index)
    {
        if (before.faces[index] == after.faces[index])
        {
            const auto palette_index = after.material_indices[index];
            if (palette_index >= palette.size())
            {
                fail("owner-difference material index escapes its palette");
            }
            const auto color = palette[palette_index];
            pixels.push_back(
                {static_cast<std::uint8_t>(color.r / 5),
                 static_cast<std::uint8_t>(color.g / 5),
                 static_cast<std::uint8_t>(color.b / 5)}
            );
        }
        else if (before.faces[index] == kMissFace)
        {
            pixels.push_back({0, 255, 255});
        }
        else if (after.faces[index] == kMissFace)
        {
            pixels.push_back({255, 0, 255});
        }
        else
        {
            pixels.push_back({255, 255, 0});
        }
    }
    write_bmp(path, pixels, kLogicalWidth, kLogicalHeight);
}

PackedAudit audit_packed_colors(const fs::path& data_dir, const SourceWorld& world)
{
    const auto faces = read_file(data_dir / "QuakeBSPWorldFaces.bin");
    if (faces.size() != static_cast<std::size_t>(world.face_count) * 6)
    {
        fail("packed world-face stream has the wrong byte count");
    }
    PackedAudit audit;
    audit.records = world.face_count;
    for (int face = 0; face < world.face_count; ++face)
    {
        const auto offset = static_cast<std::size_t>(face) * 6;
        if (faces[offset + 2] == 0)
        {
            continue;
        }
        ++audit.drawable_records;
        const auto expected = world.colors[static_cast<std::size_t>(face)];
        if (faces[offset + 3] != expected.flat || faces[offset + 4] != expected.dither)
        {
            ++audit.color_mismatches;
        }
    }

    constexpr std::size_t record_bytes = 4;
    constexpr std::size_t distance_lut_bytes = kDistanceBucketLut.size();
    constexpr std::size_t shade_pair_count =
        static_cast<std::size_t>(kTextureFamilyCount) * static_cast<std::size_t>(kApparentLightLevels) * 8U;
    const auto shading = read_file(data_dir / "QuakeBSPWorldShading.bin");
    const auto records_bytes = static_cast<std::size_t>(world.face_count) * record_bytes;
    const auto expected_bytes = records_bytes + distance_lut_bytes + shade_pair_count * 2;
    if (shading.size() != expected_bytes || world.centroids.size() != static_cast<std::size_t>(world.face_count) ||
        world.live_base_colors.size() != static_cast<std::size_t>(world.face_count))
    {
        fail("packed world-shading stream has the wrong byte count");
    }
    audit.material_records = world.face_count;
    for (int face = 0; face < world.face_count; ++face)
    {
        const auto offset = static_cast<std::size_t>(face) * record_bytes;
        const auto signed_byte = [&](std::size_t component) {
            return static_cast<int>(std::bit_cast<std::int8_t>(shading[offset + component]));
        };
        const auto centroid = world.centroids[static_cast<std::size_t>(face)];
        const auto base = world.live_base_colors[static_cast<std::size_t>(face)];
        const int packed_base = static_cast<int>(base >> 4U) * kApparentLightLevels + static_cast<int>(base & 0x0fU);
        if (signed_byte(0) != centroid.x || signed_byte(1) != centroid.y || signed_byte(2) != centroid.z ||
            shading[offset + 3] != packed_base)
        {
            ++audit.material_record_mismatches;
        }
    }
    for (std::size_t distance = 0; distance < distance_lut_bytes; ++distance)
    {
        if (shading[records_bytes + distance] != kDistanceBucketLut[distance])
        {
            ++audit.distance_lut_mismatches;
        }
    }
    const auto table_offset = records_bytes + distance_lut_bytes;
    for (int base = 0; base < kTextureFamilyCount * kApparentLightLevels; ++base)
    {
        const int family = base / kApparentLightLevels;
        const int base_light = base % kApparentLightLevels;
        for (int bucket = 0; bucket < 8; ++bucket)
        {
            const int light = kDistanceShadeLut[static_cast<std::size_t>(base_light)][static_cast<std::size_t>(bucket)];
            const auto low = static_cast<std::uint8_t>(material_palette_index(family, light / 2));
            const auto high = static_cast<std::uint8_t>(material_palette_index(family, (light + 1) / 2));
            const auto pair = (static_cast<std::size_t>(base) * 8U + static_cast<std::size_t>(bucket)) * 2U;
            if (shading[table_offset + pair] != high ||
                shading[table_offset + pair + 1] != static_cast<std::uint8_t>((high << 4U) | low))
            {
                ++audit.shade_pair_mismatches;
            }
        }
    }
    return audit;
}

namespace {
int nearest_palette_index(const Rgb& color, std::span<const Rgb> palette)
{
    int best_index = 0;
    int best_distance = std::numeric_limits<int>::max();
    for (int index = 0; index < static_cast<int>(palette.size()); ++index)
    {
        const auto candidate = palette[static_cast<std::size_t>(index)];
        const int dr = static_cast<int>(color.r) - candidate.r;
        const int dg = static_cast<int>(color.g) - candidate.g;
        const int db = static_cast<int>(color.b) - candidate.b;
        const int distance = dr * dr + dg * dg + db * db;
        if (distance < best_distance)
        {
            best_distance = distance;
            best_index = index;
        }
    }
    return best_index;
}
} // namespace

namespace {
SnesFrame load_bmp_frame(std::span<const std::uint8_t> bytes, std::span<const Rgb> palette)
{
    require_range(bytes, 0, 54, "BMP header");
    const auto pixel_offset = read_u32(bytes, 10);
    const auto dib_bytes = read_u32(bytes, 14);
    const auto width = read_i32(bytes, 18);
    const auto signed_height = read_i32(bytes, 22);
    const auto planes = read_u16(bytes, 26);
    const auto bits_per_pixel = read_u16(bytes, 28);
    const auto compression = read_u32(bytes, 30);
    if (dib_bytes < 40 || width != 256 || std::abs(signed_height) != 224 || planes != 1 ||
        (bits_per_pixel != 24 && bits_per_pixel != 32) || compression != 0)
    {
        fail("SNES BMP must be an uncompressed 256x224 24/32-bit image");
    }
    const int height = std::abs(signed_height);
    const bool top_down = signed_height < 0;
    const auto row_bits = static_cast<std::size_t>(width) * static_cast<std::size_t>(bits_per_pixel);
    const auto row_bytes = ((row_bits + 31U) / 32U) * 4U;
    require_range(bytes, pixel_offset, row_bytes * static_cast<std::size_t>(height), "BMP pixels");
    std::vector<Rgb> pixels(static_cast<std::size_t>(width) * static_cast<std::size_t>(height));
    const int bytes_per_pixel = bits_per_pixel / 8;
    for (int y = 0; y < height; ++y)
    {
        const int source_y = top_down ? y : height - 1 - y;
        const auto row = static_cast<std::size_t>(pixel_offset) + static_cast<std::size_t>(source_y) * row_bytes;
        for (int x = 0; x < width; ++x)
        {
            const auto offset = row + static_cast<std::size_t>(x) * static_cast<std::size_t>(bytes_per_pixel);
            pixels[row_major_index(x, y, width)] = {bytes[offset + 2], bytes[offset + 1], bytes[offset]};
        }
    }
    SnesFrame frame;
    frame.format = "bmp-native-exact2x-nearest-palette";
    frame.logical.reserve(kLogicalPixels);
    for (int y = 0; y < height; y += 2)
    {
        for (int x = 0; x < width; x += 2)
        {
            const auto first = pixels[row_major_index(x, y, width)];
            if (pixels[row_major_index(x + 1, y, width)] != first ||
                pixels[row_major_index(x, y + 1, width)] != first ||
                pixels[row_major_index(x + 1, y + 1, width)] != first)
            {
                ++frame.bad_2x2;
            }
            frame.logical.push_back(static_cast<std::uint8_t>(nearest_palette_index(first, palette)));
        }
    }
    return frame;
}
} // namespace

SnesFrame load_snes_frame(const fs::path& path, std::span<const Rgb> palette)
{
    const auto bytes = read_file(path);
    if (bytes.size() >= 2 && bytes[0] == 'B' && bytes[1] == 'M')
    {
        return load_bmp_frame(bytes, palette);
    }
    SnesFrame frame;
    if (bytes.size() == kLogicalPixels)
    {
        frame.logical = bytes;
        frame.format = "logical-u8-128x112";
    }
    else if (bytes.size() == std::size_t{256} * 112U || bytes.size() == std::size_t{256} * 256U)
    {
        frame.logical.reserve(kLogicalPixels);
        for (int y = 0; y < kLogicalHeight; ++y)
        {
            const auto offset = static_cast<std::size_t>(y) * 256U;
            const auto first = bytes.begin() + static_cast<std::ptrdiff_t>(offset);
            frame.logical.insert(frame.logical.end(), first, first + kLogicalWidth);
        }
        frame.format =
            bytes.size() == std::size_t{256} * 256U ? "gsu-u8-256x256-left-viewport" : "gsu-u8-256x112-left-viewport";
    }
    else
    {
        fail("SNES frame must be a 128x112/256-stride u8 dump or 256x224 BMP");
    }
    const auto invalid =
        std::find_if(frame.logical.begin(), frame.logical.end(), [](std::uint8_t value) { return value > 15; });
    if (invalid != frame.logical.end())
    {
        fail("SNES frame contains a palette index above 15");
    }
    return frame;
}

namespace {
int circular_q4_error(std::int16_t packed_q4, double source, int dimension)
{
    const std::int64_t period = static_cast<std::int64_t>(dimension) * 16;
    if (!std::isfinite(source) || period <= 0 || period > 32767)
    {
        fail("texture fidelity received an invalid coordinate period");
    }
    const auto source_q4 = static_cast<std::int64_t>(std::floor(source * 16.0));
    std::int64_t delta = (static_cast<std::int64_t>(packed_q4) - source_q4) % period;
    if (delta < 0)
    {
        delta += period;
    }
    return static_cast<int>(std::min(delta, period - delta));
}
} // namespace

TextureMappingFidelity compare_texture_mapping_fidelity(
    const SourceWorld& world,
    const ReferenceFrame& source,
    const PackedTextureRaster& packed
)
{
    if (source.faces.size() != kLogicalPixels || source.texture_indices.size() != kLogicalPixels ||
        source.texture_s.size() != kLogicalPixels || source.texture_t.size() != kLogicalPixels ||
        packed.faces.size() != kLogicalPixels || packed.indices.size() != kLogicalPixels ||
        packed.absolute_s_q4.size() != kLogicalPixels || packed.absolute_t_q4.size() != kLogicalPixels)
    {
        fail("texture fidelity requires complete source and packed planes");
    }

    TextureMappingFidelity result;
    for (std::size_t pixel = 0; pixel < kLogicalPixels; ++pixel)
    {
        const auto source_face = source.faces[pixel];
        const auto packed_face = packed.faces[pixel];
        if (source_face != packed_face)
        {
            ++result.owner_mismatch_pixels;
            continue;
        }
        ++result.owner_match_pixels;
        if (source_face == kMissFace)
        {
            continue;
        }
        const auto face_index = static_cast<std::size_t>(source_face);
        if (face_index >= world.face_texture_infos.size())
        {
            fail("texture fidelity face escapes source texture information");
        }
        const int info_index = world.face_texture_infos[face_index];
        if (info_index < 0 || static_cast<std::size_t>(info_index) >= world.texture_infos.size())
        {
            fail("texture fidelity face has invalid texture information");
        }
        const auto& info = world.texture_infos[static_cast<std::size_t>(info_index)];
        if (info.texture_id < 0 || static_cast<std::size_t>(info.texture_id) >= world.textures.size())
        {
            fail("texture fidelity information has an invalid miptex");
        }
        const auto& texture = world.textures[static_cast<std::size_t>(info.texture_id)];
        const int s_error =
            circular_q4_error(packed.absolute_s_q4[pixel], source.texture_s[pixel], static_cast<int>(texture.width));
        const int t_error =
            circular_q4_error(packed.absolute_t_q4[pixel], source.texture_t[pixel], static_cast<int>(texture.height));
        ++result.comparable_pixels;
        result.total_s_error_q4 += s_error;
        result.total_t_error_q4 += t_error;
        result.max_s_error_q4 = std::max(result.max_s_error_q4, s_error);
        result.max_t_error_q4 = std::max(result.max_t_error_q4, t_error);
        result.exact_texel_pixels += source.texture_indices[pixel] == packed.indices[pixel];
        result.within_one_texel_pixels += s_error <= 16 && t_error <= 16;
        result.within_two_texel_pixels += s_error <= 32 && t_error <= 32;
        result.within_four_texel_pixels += s_error <= 64 && t_error <= 64;
        if (result.first_beyond_two_texels < 0 && (s_error > 32 || t_error > 32))
        {
            result.first_beyond_two_texels = static_cast<int>(pixel);
            result.first_face = source_face;
            result.first_source_s_q4 = static_cast<std::int64_t>(std::floor(source.texture_s[pixel] * 16.0));
            result.first_source_t_q4 = static_cast<std::int64_t>(std::floor(source.texture_t[pixel] * 16.0));
            result.first_packed_s_q4 = packed.absolute_s_q4[pixel];
            result.first_packed_t_q4 = packed.absolute_t_q4[pixel];
            result.first_s_error_q4 = s_error;
            result.first_t_error_q4 = t_error;
            result.first_source_index = source.texture_indices[pixel];
            result.first_packed_index = packed.indices[pixel];
        }
        if (result.first_beyond_four_texels < 0 && (s_error > 64 || t_error > 64))
        {
            result.first_beyond_four_texels = static_cast<int>(pixel);
        }
    }
    if (result.comparable_pixels == 0)
    {
        fail("texture fidelity found no same-owner geometry pixels");
    }
    return result;
}

PackedTextureComparison
compare_packed_texture_indices(const PackedTextureRaster& expected, std::span<const std::uint8_t> actual)
{
    if (expected.indices.size() != kLogicalPixels || actual.size() != kLogicalPixels)
    {
        fail("packed texture comparison requires a 128x112 raw index plane");
    }
    PackedTextureComparison result;
    for (std::size_t index = 0; index < actual.size(); ++index)
    {
        if (expected.indices[index] == actual[index])
        {
            ++result.exact_pixels;
            continue;
        }
        ++result.different_pixels;
        if (result.first_mismatch < 0)
        {
            result.first_mismatch = static_cast<int>(index);
            result.expected_index = expected.indices[index];
            result.actual_index = actual[index];
        }
    }
    return result;
}

Comparison compare_frames(const ReferenceFrame& reference, const SnesFrame& snes, int allowed_holes)
{
    if (snes.logical.size() != reference.material_indices.size())
    {
        fail("SNES logical frame size disagrees with the reference frame");
    }
    Comparison result;
    result.input_format = snes.format;
    result.bad_2x2 = snes.bad_2x2;
    for (std::size_t index = 0; index < reference.material_indices.size(); ++index)
    {
        const bool reference_hit = reference.faces[index] != kMissFace;
        const auto expected = reference.material_indices[index];
        const auto actual = snes.logical[index];
        result.exact_pixels += expected == actual;
        if (reference_hit && actual == 0)
        {
            ++result.snes_hole_pixels;
        }
        else if (!reference_hit && actual != 0)
        {
            ++result.snes_false_geometry_pixels;
        }
        else if (reference_hit && actual != 0 && expected != actual)
        {
            ++result.palette_mismatch_pixels;
        }
        else if (reference_hit && expected == actual)
        {
            ++result.geometry_palette_match_pixels;
        }
    }
    result.passed =
        reference.misses == 0 && result.bad_2x2 == 0 && result.snes_hole_pixels <= allowed_holes &&
        result.snes_false_geometry_pixels == 0;
    return result;
}

void write_diff(
    const fs::path& path,
    const ReferenceFrame& reference,
    const SnesFrame& snes,
    std::span<const Rgb> palette
)
{
    std::vector<Rgb> pixels;
    pixels.reserve(reference.material_indices.size());
    for (std::size_t index = 0; index < reference.material_indices.size(); ++index)
    {
        const bool reference_hit = reference.faces[index] != kMissFace;
        const auto expected = reference.material_indices[index];
        const auto actual = snes.logical[index];
        Rgb color{0, 0, 0};
        if (reference_hit && actual == 0)
        {
            color = {255, 0, 255};
        }
        else if (!reference_hit && actual != 0)
        {
            color = {0, 255, 255};
        }
        else if (expected != actual)
        {
            color = {255, 255, 0};
        }
        else
        {
            const auto source = palette[expected];
            color = {
                static_cast<std::uint8_t>(source.r / 5),
                static_cast<std::uint8_t>(source.g / 5),
                static_cast<std::uint8_t>(source.b / 5)
            };
        }
        pixels.push_back(color);
    }
    write_bmp(path, pixels, kLogicalWidth, kLogicalHeight);
}

namespace {
void declare_artifact_options(CLI::App& app, Options& options)
{
    app.add_option("--pak", options.pak, "Quake PAK containing the source BSP")->check(CLI::ExistingFile);
    app.add_option("--map", options.map_entry, "BSP PAK entry")->capture_default_str();
    app.add_option("--output-prefix", options.output_prefix, "Output path without an artifact suffix");
    app.add_option("--json", options.json_path, "Machine-readable report path");
    app.add_option("--data-dir", options.data_dir, "Packed assets for the audit and quantized-world layer")
        ->check(CLI::ExistingDirectory);
    app.add_option("--packet-source-faces", options.packet_source_faces, "Painter-ordered u16 source-face sidecar")
        ->check(CLI::ExistingFile);
    app.add_option("--snes-frame", options.snes_frame, "GSU byte dump or native 256x224 BMP to compare")
        ->check(CLI::ExistingFile);
    app.add_option(
           "--snes-texture-indices",
           options.snes_texture_indices,
           "Raw 128x112 SNES 8bpp indices to compare with the retained "
           "packed affine output"
    )
        ->check(CLI::ExistingFile);
    app.add_option(
        "--packed-albedo-indices",
        options.packed_albedo_indices,
        "Write only the raw packed-projective albedo plane"
    );
    app.add_option(
        "--packed-lightmap-indices",
        options.packed_lightmap_indices,
        "Write only the raw packed-projective lightmapped plane"
    );
    app.add_option(
        "--packed-lightmap-levels",
        options.packed_lightmap_levels,
        "Write only the raw packed-projective lightmap-level plane"
    );
    app.add_option(
        "--packed-render-indices",
        options.packed_render_indices,
        "Write the selected raw packed render plane"
    );
    app.add_option(
        "--brush-albedo-indices",
        options.brush_albedo_indices,
        "Write only the raw enabled-brush source albedo plane"
    );
    app.add_option(
        "--brush-lightmap-indices",
        options.brush_lightmap_indices,
        "Write only the raw enabled-brush source lightmapped plane"
    );
    app.add_option(
        "--brush-render-indices",
        options.brush_render_indices,
        "Write the selected raw source 2x3 brush render plane"
    );
    app.add_option(
        "--packed-brush-albedo-indices",
        options.packed_brush_albedo_indices,
        "Write raw packed enabled-brush projective albedo indices"
    );
    app.add_option(
        "--packed-brush-lightmap-indices",
        options.packed_brush_lightmap_indices,
        "Write raw packed enabled-brush projective lightmapped indices"
    );
    app.add_option(
        "--packed-brush-render-indices",
        options.packed_brush_render_indices,
        "Write the selected raw packed enabled-brush 2x3 render plane"
    );
    app.add_option(
        "--packed-alias-render-indices",
        options.packed_alias_render_indices,
        "Write the selected packed world/brush plane with post-opaque aliases"
    );
    app.add_option(
        "--quake-sky-indices",
        options.quake_sky_indices,
        "Write the ordered final presentation with authentic Quake sky"
    );
    app.add_option(
        "--fly-alias-render-indices",
        options.fly_alias_render_indices,
        "Write packed world plus the generated current-camera fly alias row"
    );
}
} // namespace

namespace {
void declare_replay_options(CLI::App& app, Options& options, RawOptionValues& raw)
{
    app.add_option(
           "--realtime-demo",
           options.realtime_demo_track,
           "Ten-byte configured fixed-rate camera track to loop in a window"
    )
        ->check(CLI::ExistingFile);
    app.add_option("--brush-replay", options.brush_replay, "QBR2 brush state aligned one-to-one with --realtime-demo")
        ->check(CLI::ExistingFile);
    app.add_option(
           "--external-bsp-replay",
           options.external_bsp_replay,
           "QER1 external BSP state aligned with --realtime-demo"
    )
        ->check(CLI::ExistingFile);
    app.add_option("--sound-replay", options.sound_replay, "QSR1 sound events aligned with --realtime-demo")
        ->check(CLI::ExistingFile);
    app.add_option("--alias-assets", options.alias_assets, "Directory containing QBA1 MDL/IDSP billboard assets")
        ->check(CLI::ExistingDirectory);
    app.add_option("--ordered-replay", options.ordered_replay, "QOR1 packed cameras and packets for ordered playback")
        ->check(CLI::ExistingFile);
    app.add_option(
        "--ordered-alias-visibility",
        options.ordered_alias_visibility,
        "Write the QAV1 packed opaque-depth visibility corpus for every "
        "ordered row"
    );
    app.add_flag("--ordered-2hz", options.ordered_2hz, "Render every derived 2 Hz row in canonical order");
    app.add_flag("--step-by-step", options.ordered_2hz, "Deprecated alias for --ordered-2hz");
    app.add_flag("--ordered-fast", options.ordered_fast, "Advance ordered 2 Hz rows after each completed render");
    app.add_option("--ordered-rate-hz", options.ordered_presentation_hz, "Timed ordered presentation rate: 2 or 20 Hz")
        ->check(CLI::IsMember({2, 20}))
        ->capture_default_str();
    app.add_option("--playback-speed", raw.playback_speed, "Live source-clock speed: realtime, half, or quarter")
        ->check(CLI::IsMember({"realtime", "half", "quarter"}))
        ->capture_default_str();
    app.add_flag("--no-brushes", options.no_brushes, "Start with dynamic brush rendering disabled");
    app.add_flag("--no-entities", options.no_entities, "Start with MDL/SPR billboard entity rendering disabled");
    app.add_flag(
        "--external-bsp-models",
        options.external_bsp_models,
        "Start with reference-only external BSP models enabled"
    );
    app.add_flag("--no-sound", options.no_sound, "Start with configured demo sound disabled");
    app.add_option("--volume", options.volume, "Reference sound volume from 0.0 to 1.0")
        ->check(CLI::Range(0.0F, 1.0F))
        ->capture_default_str();
    app.add_option(
           "--demo-pose",
           options.demo_pose,
           "Render one canonical fixed-rate demo row without opening a window"
    )
        ->check(CLI::NonNegativeNumber);
    app.add_option(
           "--fly-source-pose",
           options.fly_source_pose,
           "Bind static fly brush/external state to one canonical source row"
    )
        ->check(CLI::NonNegativeNumber);
    app.add_option("--alias-yaw-q8", options.alias_yaw_q8, "Immutable EF_ROTATE yaw in 1/256 turns")
        ->check(CLI::Range(0, 255));
    raw.surface_time_option =
        app.add_option(
               "--surface-time",
               options.surface_time,
               "Override server time for deterministic special surfaces"
        )
            ->check(CLI::NonNegativeNumber);
    app.add_option(
           "--packed-realtime-demo",
           options.packed_realtime_demo_track,
           "Five-byte packed SNES-parity camera track"
    )
        ->check(CLI::ExistingFile);
    app.add_option("--demo-timing", options.realtime_demo_timing, "Uint16 NTSC due tick for --packed-realtime-demo")
        ->check(CLI::ExistingFile);
    app.add_option(
        "--instrumentation-session",
        options.instrumentation_session,
        "Reference instrumentation session identifier"
    );
    app.add_option(
        "--instrumentation-pipe",
        options.instrumentation_pipe,
        "Reference instrumentation named-pipe identifier"
    );
    app.add_option("--allow-holes", options.allowed_holes, "Permitted reference-hit/SNES-zero pixels")
        ->check(CLI::NonNegativeNumber)
        ->capture_default_str();
}
} // namespace

namespace {
void declare_render_options(CLI::App& app, Options& options, RawOptionValues& raw)
{
    app.add_flag("--no-textures", options.no_textures, "Select untextured LightMap technique 7");
    app.add_option("--lighting", raw.lighting, "Selected lighting: none or lightmap")
        ->check(CLI::IsMember({"none", "lightmap"}))
        ->capture_default_str();
    app.add_flag("--self-test", options.self_test, "Run the internal BVH/ray/parity test");
    app.add_flag("--report-only", options.report_only, "Write JSON counters without framebuffer artifacts");
}
} // namespace

namespace {
void declare_camera_options(CLI::App& app, RawOptionValues& raw)
{
    const auto presets = std::set<std::string>{"spawn", "near", "far", "return-spawn", "yaw", "pitch"};
    auto* preset_option =
        app.add_option("--preset", raw.preset, "Named accepted camera")->check(CLI::IsMember(presets));
    auto* camera_option = app.add_option("--camera", raw.camera, "Packed camera: X Y Z YAW PITCH")->expected(5);
    preset_option->excludes(camera_option);
    camera_option->excludes(preset_option);
}
} // namespace

namespace {
void declare_options(CLI::App& app, Options& options, RawOptionValues& raw)
{
    app.footer(
        "Live controls: the slider seeks and pauses; Dynamic brushes, "
        "MDL/SPR entities, and external BSP models preserve the current pose; "
        "Textures selects technique 7 when off and technique 2 or 4 when on; "
        "Lighting selects None or LightMap; Space "
        "toggles pause; Esc closes."
    );
    declare_artifact_options(app, options);
    declare_replay_options(app, options, raw);
    declare_render_options(app, options, raw);
    declare_camera_options(app, raw);
}
} // namespace

namespace {
void parse_command_line(CLI::App& app, int argc, char** argv)
{
    try
    {
        app.parse(argc, argv);
    }
    catch (const CLI::ParseError& error)
    {
        std::exit(app.exit(error));
    }
}
} // namespace

namespace {
void normalize_camera(Options& options, const RawOptionValues& raw)
{
    if (!raw.preset.empty())
    {
        options.camera_label = raw.preset;
        options.camera = preset_camera(raw.preset);
    }
    else if (!raw.camera.empty())
    {
        options.camera = {raw.camera[0], raw.camera[1], raw.camera[2], raw.camera[3], raw.camera[4]};
        options.camera_label = "custom";
    }
}
} // namespace

namespace {
void normalize_lighting(Options& options, std::string_view lighting)
{
    if (lighting == "none")
    {
        options.lighting = Lighting::None;
    }
    else
    {
        options.lighting = Lighting::LightMap;
    }
}
} // namespace

namespace {
void normalize_playback_speed(Options& options, std::string_view speed)
{
    if (speed == "half")
    {
        options.playback_speed = PlaybackSpeed::Half;
    }
    else if (speed == "quarter")
    {
        options.playback_speed = PlaybackSpeed::Quarter;
    }
}
} // namespace

namespace {
void normalize_options(Options& options, const RawOptionValues& raw)
{
    options.surface_time_override = raw.surface_time_option->count() != 0;
    normalize_camera(options, raw);
    normalize_lighting(options, raw.lighting);
    normalize_playback_speed(options, raw.playback_speed);
}
} // namespace

namespace {
OptionFacts derive_option_facts(const Options& options)
{
    OptionFacts facts;
    facts.precise_demo = !options.realtime_demo_track.empty();
    facts.brush_demo = !options.brush_replay.empty();
    facts.packed_demo = !options.packed_realtime_demo_track.empty();
    facts.static_fly = !options.fly_alias_render_indices.empty();
    facts.ordered_sky = !options.quake_sky_indices.empty() && options.demo_pose >= 0;
    facts.fly_sky = !options.quake_sky_indices.empty() && facts.static_fly;
    facts.packed_brush_indices =
        !options.packed_brush_albedo_indices.empty() || !options.packed_brush_lightmap_indices.empty() ||
        !options.packed_brush_render_indices.empty() || !options.packed_alias_render_indices.empty() ||
        facts.ordered_sky;
    facts.brush_indices =
        !options.brush_albedo_indices.empty() || !options.brush_lightmap_indices.empty() ||
        !options.brush_render_indices.empty() || facts.packed_brush_indices;
    facts.raw_indices =
        facts.brush_indices || !options.packed_albedo_indices.empty() || !options.packed_lightmap_indices.empty() ||
        !options.packed_lightmap_levels.empty() || !options.packed_render_indices.empty() ||
        !options.fly_alias_render_indices.empty() || !options.quake_sky_indices.empty();
    return facts;
}
} // namespace

class OptionContractValidator
{
  public:
    OptionContractValidator(Options& options, const RawOptionValues& raw)
    :
    options_(options),
    raw_(raw),
    facts_(derive_option_facts(options))
    {
    }

    void validate()
    {
        validate_self_test_contract();
        if (options_.self_test)
        {
            return;
        }
        validate_required_inputs();
        validate_render_mode_contract();
        validate_source_replay_contract();
        validate_ordered_entry_contract();
        validate_sky_contract();
        validate_ordered_visibility_contract();
        validate_ordered_render_contract();
        validate_instrumentation_contract();
        validate_live_feature_contract();
        validate_demo_pose_contract();
        validate_static_fly_contract();
        validate_fly_sky_paths();
        validate_demo_pose_artifacts();
        validate_timing_contract();
        validate_output_contract();
        validate_camera_coordinates();
    }

  private:
    void validate_render_mode_contract() const
    {
        if (options_.flat || options_.material_view ||
            (options_.no_textures && options_.lighting != Lighting::LightMap))
        {
            fail("reference renderer supports only techniques 2, 4, and 7");
        }
    }

    void validate_self_test_contract() const
    {
        if (options_.self_test && (!options_.quake_sky_indices.empty() || options_.surface_time_override))
        {
            fail(
                "authentic sky artifact options cannot be combined with "
                "--self-test"
            );
        }
    }

    void validate_required_inputs() const
    {
        if (options_.pak.empty())
        {
            fail("--pak is required");
        }
        if (options_.output_prefix.empty() && !facts_.precise_demo && !facts_.packed_demo &&
            options_.fly_alias_render_indices.empty())
        {
            fail("--output-prefix is required");
        }
        if (facts_.precise_demo && facts_.packed_demo)
        {
            fail(
                "--realtime-demo and --packed-realtime-demo are mutually "
                "exclusive"
            );
        }
        if (facts_.precise_demo != facts_.brush_demo)
        {
            fail("--realtime-demo and --brush-replay must be supplied together");
        }
    }

    void validate_source_replay_contract() const
    {
        if (!options_.external_bsp_replay.empty() && !facts_.precise_demo)
        {
            fail("--external-bsp-replay requires --realtime-demo");
        }
        if (!options_.sound_replay.empty() && !facts_.precise_demo)
        {
            fail("--sound-replay requires --realtime-demo");
        }
        if (options_.external_bsp_models && options_.external_bsp_replay.empty())
        {
            fail("--external-bsp-models requires --external-bsp-replay");
        }
        if (options_.fly_alias_render_indices.empty() && facts_.precise_demo != !options_.alias_assets.empty())
        {
            fail("--realtime-demo and --alias-assets must be supplied together");
        }
        if (facts_.brush_demo && options_.map_entry != "maps/e1m3.bsp" && !options_.no_brushes)
        {
            fail(
                "the current brush replay contract supports only "
                "maps/e1m3.bsp"
            );
        }
    }

    void validate_ordered_entry_contract() const
    {
        if (options_.ordered_2hz && !facts_.precise_demo)
        {
            fail("--ordered-2hz requires --realtime-demo");
        }
        if (options_.ordered_2hz && (options_.ordered_replay.empty() || options_.data_dir.empty()))
        {
            fail("--ordered-2hz requires --ordered-replay and --data-dir");
        }
        if (!options_.ordered_replay.empty() && !options_.ordered_2hz && options_.demo_pose < 0 &&
            options_.ordered_alias_visibility.empty())
        {
            fail(
                "--ordered-replay requires --ordered-2hz, --demo-pose, or "
                "--ordered-alias-visibility"
            );
        }
    }

    void validate_sky_contract() const
    {
        if (!options_.quake_sky_indices.empty() &&
            ((!facts_.ordered_sky && !facts_.fly_sky) ||
             (facts_.ordered_sky && (options_.ordered_replay.empty() || options_.data_dir.empty()))))
        {
            fail(
                "--quake-sky-indices requires either ordered --demo-pose and "
                "--data-dir or a static --fly-alias-render-indices artifact"
            );
        }
        if (!options_.quake_sky_indices.empty() && (options_.no_textures || options_.material_view))
        {
            fail("--quake-sky-indices requires a textured render mode");
        }
        if (facts_.fly_sky && !options_.surface_time_override)
        {
            fail("static fly sky requires explicit --surface-time");
        }
        if (options_.surface_time_override && (!std::isfinite(options_.surface_time) || options_.surface_time < 0.0))
        {
            fail("--surface-time must be finite and nonnegative");
        }
    }

    void validate_ordered_visibility_contract() const
    {
        if (!options_.ordered_alias_visibility.empty() &&
            (!facts_.precise_demo || options_.ordered_replay.empty() || options_.data_dir.empty()))
        {
            fail(
                "--ordered-alias-visibility requires --realtime-demo, "
                "--brush-replay, --alias-assets, --ordered-replay, and "
                "--data-dir"
            );
        }
        if (!options_.ordered_alias_visibility.empty() &&
            (options_.demo_pose >= 0 || options_.ordered_2hz || options_.no_entities ||
             !options_.instrumentation_session.empty()))
        {
            fail(
                "--ordered-alias-visibility is a headless corpus export and "
                "cannot use demo-pose, live ordered playback, disabled "
                "entities, or instrumentation"
            );
        }
    }

    void validate_ordered_render_contract() const
    {
        if (options_.ordered_2hz && options_.material_view)
        {
            fail("--material-view is unavailable in packed ordered playback");
        }
        if (options_.ordered_2hz && options_.playback_speed != PlaybackSpeed::Realtime)
        {
            fail("--ordered-2hz cannot use --playback-speed");
        }
        if (options_.ordered_fast && !options_.ordered_2hz)
        {
            fail("--ordered-fast requires --ordered-2hz");
        }
        if (options_.ordered_presentation_hz != 2 && !options_.ordered_2hz)
        {
            fail("--ordered-rate-hz requires --ordered-2hz");
        }
    }

    void validate_instrumentation_contract()
    {
        if (options_.instrumentation_session.empty() != options_.instrumentation_pipe.empty())
        {
            if (options_.instrumentation_session.empty())
            {
                fail(
                    "--instrumentation-pipe requires "
                    "--instrumentation-session"
                );
            }
            options_.instrumentation_pipe = "quake-reference-" + options_.instrumentation_session;
        }
        if (!options_.instrumentation_session.empty() &&
            (!valid_reference_instrumentation_identifier(options_.instrumentation_session) ||
             !valid_reference_instrumentation_identifier(options_.instrumentation_pipe)))
        {
            fail(
                "reference instrumentation identifiers must use 1-64 ASCII "
                "letters, digits, dot, underscore, or dash"
            );
        }
        if (!options_.instrumentation_session.empty() && !facts_.precise_demo && !facts_.packed_demo)
        {
            fail("reference instrumentation requires a live demo");
        }
    }

    void validate_live_feature_contract() const
    {
        if (!facts_.precise_demo && !facts_.packed_demo && options_.playback_speed != PlaybackSpeed::Realtime)
        {
            fail("--playback-speed requires a live demo");
        }
        if (options_.no_brushes && !facts_.brush_demo && !facts_.static_fly)
        {
            fail("--no-brushes requires --brush-replay or a static fly capture");
        }
        if (options_.no_entities && !facts_.precise_demo && !facts_.static_fly)
        {
            fail("--no-entities requires --realtime-demo or a static fly capture");
        }
    }

    void validate_demo_pose_contract() const
    {
        if (options_.demo_pose >= 0 && !facts_.precise_demo)
        {
            fail("--demo-pose requires --realtime-demo and --brush-replay");
        }
        if (options_.demo_pose >= 0 && options_.ordered_2hz)
        {
            fail(
                "--demo-pose names a canonical row and cannot use "
                "--ordered-2hz"
            );
        }
        if (options_.demo_pose >= 0 && options_.playback_speed != PlaybackSpeed::Realtime)
        {
            fail(
                "--demo-pose names a canonical row and cannot use "
                "--playback-speed"
            );
        }
        if (options_.demo_pose >= 0 && options_.output_prefix.empty() &&
            !(options_.report_only && !options_.quake_sky_indices.empty()))
        {
            fail("--demo-pose requires --output-prefix");
        }
    }

    void validate_static_fly_contract() const
    {
        if (!options_.fly_alias_render_indices.empty() &&
            (options_.data_dir.empty() || options_.packet_source_faces.empty() || options_.alias_assets.empty() ||
             raw_.camera.empty()))
        {
            fail(
                "--fly-alias-render-indices requires --data-dir, "
                "--packet-source-faces, --alias-assets, and --camera"
            );
        }
        if (!options_.fly_alias_render_indices.empty() &&
            (options_.demo_pose >= 0 || facts_.precise_demo || facts_.packed_demo || options_.ordered_2hz ||
             !options_.ordered_replay.empty()))
        {
            fail("--fly-alias-render-indices is a static current-camera output");
        }
        if (options_.fly_alias_render_indices.empty() && options_.fly_source_pose != 0)
        {
            fail("--fly-source-pose requires --fly-alias-render-indices");
        }
    }

    void validate_fly_sky_paths() const
    {
        if (facts_.fly_sky &&
            fs::absolute(options_.quake_sky_indices).lexically_normal() ==
                fs::absolute(options_.fly_alias_render_indices).lexically_normal())
        {
            fail("static fly sky and raw fly outputs must use different paths");
        }
    }

    void validate_demo_pose_artifacts() const
    {
        if (options_.demo_pose >= 0 &&
            ((!facts_.packed_brush_indices &&
              (!options_.data_dir.empty() || !options_.packet_source_faces.empty() || !raw_.camera.empty())) ||
             !options_.json_path.empty() || !options_.snes_frame.empty() || !options_.snes_texture_indices.empty() ||
             !options_.packed_albedo_indices.empty() || !options_.packed_lightmap_indices.empty() ||
             !options_.packed_lightmap_levels.empty() || options_.allowed_holes != 0 ||
             !options_.packed_render_indices.empty() || options_.material_view || !raw_.preset.empty()))
        {
            fail(
                "--demo-pose cannot be combined with static audit, "
                "comparison, camera, or report options"
            );
        }
        if (facts_.brush_indices && options_.demo_pose < 0)
        {
            fail("--brush-*-indices requires --demo-pose");
        }
        if (options_.report_only && options_.demo_pose >= 0 && !facts_.brush_indices)
        {
            fail("--demo-pose --report-only requires a brush index output");
        }
    }

    void validate_timing_contract() const
    {
        if (facts_.precise_demo && !options_.realtime_demo_timing.empty())
        {
            fail(
                "--demo-timing is not used by the constant-step "
                "--realtime-demo"
            );
        }
        if (facts_.packed_demo != !options_.realtime_demo_timing.empty())
        {
            fail(
                "--packed-realtime-demo and --demo-timing must be supplied "
                "together"
            );
        }
    }

    void validate_output_contract() const
    {
        if (options_.report_only && options_.json_path.empty() && !facts_.raw_indices)
        {
            fail("--report-only requires --json");
        }
        if (!options_.packet_source_faces.empty() && options_.data_dir.empty())
        {
            fail("--packet-source-faces requires --data-dir");
        }
        if ((!options_.packed_albedo_indices.empty() || !options_.packed_lightmap_indices.empty() ||
             !options_.packed_lightmap_levels.empty() || !options_.packed_render_indices.empty()) &&
            (options_.data_dir.empty() || options_.packet_source_faces.empty()))
        {
            fail(
                "--packed-*-indices requires --data-dir and "
                "--packet-source-faces"
            );
        }
        if (facts_.packed_brush_indices &&
            (options_.data_dir.empty() ||
             (options_.ordered_replay.empty() && (options_.packet_source_faces.empty() || raw_.camera.empty()))))
        {
            fail(
                "--packed-brush-*-indices requires --data-dir plus either "
                "--ordered-replay or --packet-source-faces and --camera"
            );
        }
    }

    void validate_camera_coordinates() const
    {
        for (const int coordinate : {options_.camera.x, options_.camera.y, options_.camera.z})
        {
            if (coordinate < -128 || coordinate > 127)
            {
                fail("camera coordinates must fit signed bytes");
            }
        }
    }

    Options& options_;
    const RawOptionValues& raw_;
    const OptionFacts facts_;
};

Options parse_options(int argc, char** argv)
{
    Options options;
    RawOptionValues raw;
    CLI::App app{"Independent C++23 SNES Quake reference renderer", "quake_bsp_reference_renderer"};
    declare_options(app, options, raw);
    parse_command_line(app, argc, argv);
    normalize_options(options, raw);
    OptionContractValidator(options, raw).validate();
    return options;
}

Triangle
make_test_triangle(const Vec3& first, const Vec3& second, const Vec3& third, std::uint16_t face, FaceColor color)
{
    Triangle triangle;
    triangle.first = first;
    triangle.second = second;
    triangle.third = third;
    triangle.centroid = (first + second + third) * (1.0 / 3.0);
    triangle.bounds.include(first);
    triangle.bounds.include(second);
    triangle.bounds.include(third);
    triangle.face = face;
    triangle.color = color;
    return triangle;
}

} // namespace quake_bsp_reference
