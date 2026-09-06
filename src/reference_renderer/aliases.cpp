#include "aliases.hpp"
#include "world.hpp"
#include "geometry.hpp"
#include "brushes.hpp"
#include "external_models.hpp"

namespace quake_bsp_reference {

namespace {
int alias_mul_shift(int value, int multiplier, int shift)
{
    return wrap_i16((value * multiplier) >> shift);
}
} // namespace

std::size_t alias_sprite_id(const AliasState& state)
{
    return state.sprite & kAliasDirectionalMask;
}

std::size_t alias_directional_view(int forward, int right)
{
    const auto magnitude = [](int value) {
        const auto absolute = value < 0 ? -static_cast<std::int64_t>(value) : value;
        return static_cast<std::uint32_t>(std::min<std::int64_t>(absolute, 0x7fff));
    };
    const auto abs_forward = magnitude(forward);
    const auto abs_right = magnitude(right);
    if (abs_forward == 0 && abs_right == 0)
    {
        return 0;
    }
    const bool right_major = abs_right > abs_forward;
    const auto major = right_major ? abs_right : abs_forward;
    const auto minor = right_major ? abs_forward : abs_right;
    // 577 / 1393 straddles tan(22.5 degrees) closely enough to classify
    // every signed Q6 component exactly while keeping 16x16 products.
    const bool diagonal = static_cast<std::uint64_t>(minor) * 1393U >= static_cast<std::uint64_t>(major) * 577U;
    if (diagonal)
    {
        if (right < 0)
        {
            return forward < 0 ? 5U : 7U;
        }
        return forward < 0 ? 3U : 1U;
    }
    if (right_major)
    {
        return right < 0 ? 6U : 2U;
    }
    return forward < 0 ? 4U : 0U;
}

std::size_t alias_resolved_sprite_id(const AliasState& state, int dx, int dy, std::uint8_t rotation_yaw_q8)
{
    const auto base = alias_sprite_id(state);
    if ((state.sprite & kAliasDirectionalTag) == 0)
    {
        return base;
    }
    int sine = state.yaw_sin_q6, cosine = state.yaw_cos_q6;
    if (sine == -128)
    {
        const double angle = rotation_yaw_q8 * (2.0 * std::numbers::pi / 256.0);
        sine = static_cast<int>(std::round(std::sin(angle) * 64));
        cosine = static_cast<int>(std::round(std::cos(angle) * 64));
    }
    const int forward = wrap_i16(-wrap_i16(alias_mul_shift(dx, cosine, 2) + alias_mul_shift(dy, sine, 2)));
    const int right = wrap_i16(-wrap_i16(alias_mul_shift(dy, cosine, 2) - alias_mul_shift(dx, sine, 2)));
    return base + alias_directional_view(forward, right);
}

int alias_world_width(const AliasSprite& sprite)
{
    return sprite.world_width == 0 ? sprite.width : sprite.world_width;
}

int alias_world_height(const AliasSprite& sprite)
{
    return sprite.world_height == 0 ? sprite.height : sprite.world_height;
}

std::size_t alias_fly_row(const AliasAssets& assets, const Camera& camera)
{
    if (assets.rows.size() < kAliasFlyRowCount)
    {
        fail("QBA1 has no complete eight-angle fly row set");
    }
    const auto orbit = static_cast<std::size_t>(((table_index(camera.yaw) + 2) >> 2) & 7);
    return assets.rows.size() - kAliasFlyRowCount + orbit;
}

std::uint64_t alias_read_u64(std::span<const std::uint8_t> bytes, std::size_t offset)
{
    if (offset + 8 > bytes.size())
    {
        fail("alias u64 read exceeds the asset package");
    }
    std::uint64_t value{};
    for (int byte = 0; byte < 8; ++byte)
    {
        value |= static_cast<std::uint64_t>(bytes[offset + byte]) << (byte * 8U);
    }
    return value;
}

namespace {
std::size_t alias_location_offset(std::uint8_t bank, std::uint16_t address, std::size_t size, std::size_t chunk_count)
{
    for (std::size_t chunk = 0; chunk < chunk_count; ++chunk)
    {
        const auto [expected_bank, base] = kAliasStorageLocations.at(chunk);
        if (bank == expected_bank && address >= base &&
            static_cast<std::size_t>(address - base) + size <= kAliasHalfbankBytes)
        {
            return chunk * kAliasHalfbankBytes + (address - base);
        }
    }
    fail("alias asset pointer escapes its declared storage regions");
}
} // namespace

namespace {
AliasState parse_alias_state(std::span<const std::uint8_t> bytes, std::size_t offset)
{
    if (offset + kAliasStateBytes > bytes.size())
    {
        fail("alias state exceeds the asset package");
    }
    return {
        read_u16(bytes, offset),
        {read_i16(bytes, offset + 2), read_i16(bytes, offset + 4), read_i16(bytes, offset + 6)},
    };
}
} // namespace

AliasAssets load_alias_assets(const fs::path& directory)
{
    auto first = read_file(directory / "QuakeBSPAliasRuntime0.bin");
    if (first.size() != kAliasHalfbankBytes ||
        !std::equal(first.begin(), first.begin() + 4, std::array<std::uint8_t, 4>{'Q', 'B', 'A', '1'}.begin()) ||
        read_u16(first, 4) != 6 || read_u16(first, 6) != kAliasHeaderBytes)
    {
        fail("invalid QBA1 alias asset header");
    }
    const auto row_count = read_u16(first, 8);
    const auto sprite_count = read_u16(first, 10);
    const auto static_count = read_u16(first, 12);
    const auto maximum_dynamic = read_u16(first, 14);
    const auto maximum_visible = read_u16(first, 16);
    const auto chunk_count = read_u16(first, 18);
    const auto row_directory = read_u32(first, 20);
    const auto sprite_directory = read_u32(first, 24);
    const auto static_offset = read_u32(first, 28);
    const auto static_bytes = read_u32(first, 32);
    const auto package_bytes = static_cast<std::size_t>(chunk_count) * kAliasHalfbankBytes;
    const auto directory_fits = [package_bytes](std::size_t offset, std::size_t size) {
        return size != 0 && offset + size <= package_bytes &&
               offset / kAliasHalfbankBytes == (offset + size - 1) / kAliasHalfbankBytes;
    };
    if (row_count < kAliasFlyRowCount || chunk_count == 0 || chunk_count > kAliasStorageLocations.size() ||
        static_bytes != static_cast<std::size_t>(static_count) * kAliasStateBytes ||
        !directory_fits(row_directory, static_cast<std::size_t>(row_count) * kAliasRowBytes) ||
        !directory_fits(sprite_directory, static_cast<std::size_t>(sprite_count) * kAliasSpriteBytes))
    {
        fail("QBA1 alias counts or directories are inconsistent");
    }
    std::vector<std::uint8_t> bytes;
    bytes.reserve(static_cast<std::size_t>(chunk_count) * kAliasHalfbankBytes);
    bytes.insert(bytes.end(), first.begin(), first.end());
    for (std::size_t chunk = 1; chunk < chunk_count; ++chunk)
    {
        const auto payload = read_file(directory / ("QuakeBSPAliasRuntime" + std::to_string(chunk) + ".bin"));
        if (payload.size() != kAliasHalfbankBytes)
        {
            fail("QBA1 alias halfbank has the wrong size");
        }
        bytes.insert(bytes.end(), payload.begin(), payload.end());
    }
    if (static_offset + static_bytes > bytes.size())
    {
        fail("QBA1 static state table exceeds the package");
    }

    AliasAssets assets;
    assets.camera_fingerprint = alias_read_u64(bytes, 36);
    assets.package_fingerprint = brush_fnv1a64(bytes);
    assets.static_states.reserve(static_count);
    for (std::size_t index = 0; index < static_count; ++index)
    {
        assets.static_states.push_back(parse_alias_state(bytes, static_offset + index * kAliasStateBytes));
    }
    assets.sprites.reserve(sprite_count);
    for (std::size_t index = 0; index < sprite_count; ++index)
    {
        const auto offset = sprite_directory + index * kAliasSpriteBytes;
        const auto bank = bytes[offset];
        const auto address = read_u16(bytes, offset + 2);
        AliasSprite sprite;
        sprite.model = bytes[offset + 1];
        sprite.width = bytes[offset + 4];
        sprite.height = bytes[offset + 5];
        sprite.world_width = bytes[offset + 6];
        sprite.world_height = bytes[offset + 7];
        sprite.frame = bytes[offset + 8];
        sprite.view = bytes[offset + 9];
        sprite.left = read_i16(bytes, offset + 10);
        sprite.top = read_i16(bytes, offset + 12);
        const auto pixel_count = static_cast<std::size_t>(sprite.width) * sprite.height;
        if (pixel_count == 0)
        {
            fail("QBA1 sprite has an empty projected extent");
        }
        const auto pixel_offset = alias_location_offset(bank, address, pixel_count, chunk_count);
        sprite.pixels.reserve(pixel_count);
        for (std::size_t pixel = 0; pixel < pixel_count; ++pixel)
        {
            const auto encoded = bytes[pixel_offset + pixel];
            sprite.pixels.push_back(encoded == 0U ? 0xffU : static_cast<std::uint8_t>(encoded - 1U));
        }
        assets.sprites.push_back(std::move(sprite));
    }
    for (const auto& state : assets.static_states)
    {
        if ((state.sprite & kAliasDirectionalTag) != 0 || alias_sprite_id(state) >= assets.sprites.size())
        {
            fail("QBA1 static state names an invalid sprite");
        }
    }

    assets.rows.reserve(row_count);
    for (std::size_t row_index = 0; row_index < row_count; ++row_index)
    {
        const bool fly = row_index >= row_count - kAliasFlyRowCount;
        const auto offset = row_directory + row_index * kAliasRowBytes;
        const auto state_bank = bytes[offset];
        const auto state_count = bytes[offset + 1];
        const auto state_address = read_u16(bytes, offset + 2);
        const auto group_bank = bytes[offset + 4];
        const auto group_count = bytes[offset + 5];
        const auto group_address = read_u16(bytes, offset + 6);
        if (state_count > maximum_dynamic || (state_count == 0) != (state_bank == 0 && state_address == 0) ||
            (group_count == 0) != (group_bank == 0 && group_address == 0))
        {
            fail("QBA1 row has an invalid empty-pointer contract");
        }
        AliasRow row;
        if (state_count != 0)
        {
            const auto state_offset = alias_location_offset(
                state_bank,
                state_address,
                static_cast<std::size_t>(state_count) * kAliasStateBytes,
                chunk_count
            );
            row.dynamic_states.reserve(state_count);
            for (std::size_t state = 0; state < state_count; ++state)
            {
                const auto parsed = parse_alias_state(bytes, state_offset + state * kAliasStateBytes);
                const auto base = alias_sprite_id(parsed);
                if (base >= assets.sprites.size() ||
                    ((parsed.sprite & kAliasDirectionalTag) != 0 &&
                     (!fly || base + kAliasFlyRowCount > assets.sprites.size())))
                {
                    fail("QBA1 state names an invalid sprite range");
                }
                if ((parsed.sprite & kAliasDirectionalTag) != 0)
                {
                    const auto& first_view = assets.sprites[base];
                    for (std::size_t view = 0; view < kAliasFlyRowCount; ++view)
                    {
                        const auto& candidate = assets.sprites[base + view];
                        if (candidate.model != first_view.model || candidate.frame != first_view.frame ||
                            candidate.view != view)
                        {
                            fail("QBA1 directional sprite range is not eight contiguous views");
                        }
                    }
                }
                row.dynamic_states.push_back(parsed);
            }
        }
        if (group_count != 0)
        {
            auto cursor = alias_location_offset(group_bank, group_address, 1, chunk_count);
            const auto group_chunk_end = (cursor / kAliasHalfbankBytes + 1) * kAliasHalfbankBytes;
            for (std::size_t group = 0; group < group_count; ++group)
            {
                if (cursor + kAliasGroupHeaderBytes > group_chunk_end)
                {
                    fail("QBA1 group header crosses its halfbank");
                }
                const auto leaf = read_u16(bytes, cursor);
                const auto parent = read_u16(bytes, cursor + 2);
                const auto token_count = bytes[cursor + 4];
                cursor += kAliasGroupHeaderBytes;
                if (cursor + token_count > group_chunk_end)
                {
                    fail("QBA1 group tokens cross their halfbank");
                }
                for (std::size_t token = 0; token < token_count; ++token)
                {
                    const auto value = bytes[cursor++];
                    const bool is_static = (value & 0x80U) != 0;
                    const auto state = static_cast<std::uint8_t>(value & 0x7fU);
                    if ((is_static && state >= assets.static_states.size()) ||
                        (!is_static && state >= row.dynamic_states.size()))
                    {
                        fail("QBA1 row token names an invalid state");
                    }
                    row.tokens.push_back({is_static, state, leaf, parent});
                }
            }
        }
        if (row.tokens.size() > maximum_visible)
        {
            fail("QBA1 row exceeds its declared visible-state maximum");
        }
        assets.rows.push_back(std::move(row));
    }
    const auto metadata_path = directory / "QuakeBSPAliasAssets.json";
    bool fly_facing_loaded = false;
    if (fs::exists(metadata_path))
    {
        const auto metadata_bytes = read_file(metadata_path);
        const auto metadata = Json::parse(std::string(metadata_bytes.begin(), metadata_bytes.end()));
        const auto& format = metadata.at("format");
        const auto facing_bytes = format.at("flyFacingRecordBytes").get<std::size_t>();
        const auto facing_count = format.at("flyFacingRecordCount").get<std::size_t>();
        const auto facing_offset = format.at("flyFacingPackageOffset").get<std::size_t>();
        if (facing_bytes != kAliasFlyFacingBytes || facing_offset + facing_count * facing_bytes > bytes.size())
        {
            fail("QBA1 fly-facing table is invalid");
        }
        const auto first_fly_row = assets.rows.size() - kAliasFlyRowCount;
        for (std::size_t row_index = first_fly_row; row_index < assets.rows.size(); ++row_index)
        {
            auto& states = assets.rows[row_index].dynamic_states;
            if (states.size() != facing_count)
            {
                fail("QBA1 fly row disagrees with the facing table");
            }
            for (std::size_t state = 0; state < states.size(); ++state)
            {
                states[state].yaw_sin_q6 = static_cast<std::int8_t>(bytes[facing_offset + state * facing_bytes]);
                states[state].yaw_cos_q6 = static_cast<std::int8_t>(bytes[facing_offset + state * facing_bytes + 1]);
            }
        }
        fly_facing_loaded = true;
        for (const auto& model : metadata.at("models"))
        {
            assets.model_names.push_back(model.at("name").get<std::string>());
            assets.model_kinds.push_back(model.at("kind").get<std::string>());
        }
        const auto& instrumentation = metadata.at("instrumentation");
        assets.static_entity_ids = instrumentation.at("staticEntityIds").get<std::vector<int>>();
        assets.row_entity_ids.resize(assets.rows.size());
        for (const auto& effect_row : instrumentation.at("effectStates"))
        {
            const auto row = effect_row.at("row").get<std::size_t>();
            if (row >= assets.rows.size())
            {
                fail("QBA1 effect inspection row escapes the runtime package");
            }
            auto& entities = assets.row_entity_ids[row];
            entities.assign(assets.rows[row].dynamic_states.size(), -1);
            for (const auto& state : effect_row.at("states"))
            {
                const auto index = state.at("index").get<std::size_t>();
                if (index >= entities.size())
                {
                    fail("QBA1 effect inspection state escapes its runtime row");
                }
                entities[index] = state.at("entity").get<int>();
            }
        }
        if (assets.model_names.size() != assets.model_kinds.size() ||
            assets.static_entity_ids.size() != assets.static_states.size())
        {
            fail(
                "QBA1 inspection metadata counts disagree with the runtime "
                "package"
            );
        }
        for (const auto& sprite : assets.sprites)
        {
            if (sprite.model >= assets.model_names.size())
            {
                fail("QBA1 inspection metadata omits a runtime model");
            }
        }
    }
    if (!fly_facing_loaded && std::ranges::any_of(assets.rows, [](const AliasRow& row) {
            return std::ranges::any_of(row.dynamic_states, [](const AliasState& state) {
                return (state.sprite & kAliasDirectionalTag) != 0;
            });
        }))
    {
        fail("QBA1 directional states require fly-facing metadata");
    }
    return assets;
}

void require_alias_camera_identity(const AliasAssets& assets, const fs::path& camera_track)
{
    const auto actual = brush_fnv1a64(read_file(camera_track));
    if (actual != assets.camera_fingerprint)
    {
        fail("alias assets and precise camera track do not match");
    }
}

namespace {
bool alias_pixel_wins(const ReferenceFrame& frame, std::size_t pixel, double depth)
{
    if (frame.faces[pixel] == kMissFace || depth < frame.depths[pixel] - kHitTieEpsilon)
    {
        return true;
    }
    if (std::abs(depth - frame.depths[pixel]) > kHitTieEpsilon)
    {
        return false;
    }
    // The generated token stream is already ordered far-to-near, including
    // its deterministic entity tie. A later alias token wins an equal-depth
    // alias pixel; equal-depth world/brush pixels retain painter authority.
    return frame.faces[pixel] == kAliasFace;
}
} // namespace

namespace {
void refresh_alias_frame_summary(ReferenceFrame& frame)
{
    frame.hits = 0;
    frame.misses = 0;
    std::set<std::uint16_t> unique_faces;
    for (const auto face : frame.faces)
    {
        if (face == kMissFace)
        {
            ++frame.misses;
        }
        else
        {
            ++frame.hits;
            unique_faces.insert(face);
        }
    }
    frame.unique_faces = static_cast<int>(unique_faces.size());
}
} // namespace

void compose_alias_billboards(
    ReferenceFrame& frame,
    const SourceWorld& world,
    const ViewTransform& view,
    const AliasAssets& assets,
    std::size_t sample_index,
    AliasCoverage* coverage
)
{
    for_each_alias_pixel(
        world,
        view,
        assets,
        sample_index,
        [&](std::size_t pixel,
            double depth,
            std::uint8_t texel,
            int source_x,
            int source_y,
            const AliasState& state,
            const AliasToken& token) {
            if (coverage != nullptr)
            {
                ++coverage->ideal_candidate_pixels;
            }
            if (!alias_pixel_wins(frame, pixel, depth))
            {
                if (coverage != nullptr && frame.faces[pixel] != kAliasFace)
                {
                    ++coverage->ideal_opaque_occluded_pixels;
                }
                return;
            }
            const auto index = texel;
            frame.faces[pixel] = kAliasFace;
            frame.entities[pixel] = static_cast<std::uint16_t>((token.is_static ? 0x8000U : 0U) | token.index);
            const auto& sprite = assets.sprites.at(alias_sprite_id(state));
            frame.models[pixel] = static_cast<std::uint8_t>(sprite.model + 1U);
            frame.depths[pixel] = depth;
            frame.indices[pixel] = static_cast<std::uint8_t>(index & 0x0fU);
            frame.material_indices[pixel] = 0;
            frame.texture_indices[pixel] = index;
            frame.texture_s[pixel] = source_x;
            frame.texture_t[pixel] = source_y;
            frame.lightmap_texture_indices[pixel] = index;
            frame.lightmap_texture_levels[pixel] = 0;
            frame.untextured_lightmap_indices[pixel] = kUntexturedBrightIndex;
        }
    );
    refresh_alias_frame_summary(frame);
}

namespace {
int alias_project_component_q7(int component, int depth)
{
    if (depth <= 0)
    {
        fail("alias projection depth must be positive");
    }
    const bool negative = component < 0;
    const int magnitude = negative ? -component : component;
    const int quotient = static_cast<int>(static_cast<std::int64_t>(magnitude) * 2048 / depth);
    const int projected = quotient * 6;
    return negative ? -projected : projected;
}
} // namespace

PackedAliasAxisProjection project_packed_alias_axis(
    int first_component,
    int last_component,
    int depth,
    int center_q7,
    bool inverted,
    int logical_extent
)
{
    const int direction = inverted ? -1 : 1;
    PackedAliasAxisProjection projection;
    projection.first_q7 = center_q7 + direction * alias_project_component_q7(first_component, depth);
    projection.last_q7 = center_q7 + direction * alias_project_component_q7(last_component, depth);
    projection.span_q7 = projection.last_q7 - projection.first_q7;
    if (projection.span_q7 <= 0)
    {
        return projection;
    }

    // Classify the two original edges before clipping.  In particular, do
    // not add a separately saturated extent to the first projected edge:
    // that can pull a rectangle whose two edges are off the same side back
    // onto the screen.  Keeping these raw Q7 endpoints also preserves the
    // full-scale DDA phase when only one edge is clipped.
    projection.first_pixel = (projection.first_q7 + 63) >> 7;
    projection.last_pixel = (projection.last_q7 - 64) >> 7;
    projection.visible =
        projection.first_pixel < logical_extent && projection.last_pixel >= 0 &&
        projection.last_pixel >= projection.first_pixel;
    projection.clipped = projection.visible && (projection.first_pixel < 0 || projection.last_pixel >= logical_extent);
    return projection;
}

std::vector<PackedAliasView>
ordered_packed_alias_views(const Camera& camera, const AliasAssets& assets, std::size_t sample_index)
{
    if (sample_index >= assets.rows.size())
    {
        fail("packed alias render sample index is out of range");
    }
    const int yaw = table_index(camera.yaw);
    const int pitch = table_index(camera.pitch);
    const auto& row = assets.rows[sample_index];
    std::vector<PackedAliasView> views;
    views.reserve(row.tokens.size());
    for (std::size_t token_ordinal = 0; token_ordinal < row.tokens.size(); ++token_ordinal)
    {
        const auto& token = row.tokens[token_ordinal];
        const auto& state = token.is_static ? assets.static_states.at(token.index) : row.dynamic_states.at(token.index);
        const int dx = wrap_i16(state.origin_q2[0] - camera.x * 4);
        const int dy = wrap_i16(state.origin_q2[1] - camera.y * 4);
        const int dz = wrap_i16(state.origin_q2[2] - camera.z * 4);
        const auto sprite = alias_resolved_sprite_id(state, dx, dy, assets.rotation_yaw_q8);
        const int forward = wrap_i16(alias_mul_shift(dx, kCosTable[yaw], 2) + alias_mul_shift(dy, kSinTable[yaw], 2));
        const int right = wrap_i16(alias_mul_shift(dy, kCosTable[yaw], 2) - alias_mul_shift(dx, kSinTable[yaw], 2));
        const int up =
            wrap_i16(alias_mul_shift(dz, kCosTable[pitch], 2) - alias_mul_shift(forward, kSinTable[pitch], 6));
        const int depth =
            wrap_i16(alias_mul_shift(forward, kCosTable[pitch], 6) + alias_mul_shift(dz, kSinTable[pitch], 2));
        views.push_back({token_ordinal, right, up, depth, sprite});
    }
    std::sort(views.begin(), views.end(), [](const PackedAliasView& left, const PackedAliasView& right) {
        if (left.depth_q6 != right.depth_q6)
        {
            return left.depth_q6 > right.depth_q6;
        }
        return left.token < right.token;
    });
    return views;
}

std::vector<std::uint8_t> compose_post_opaque_alias_indices(
    std::span<const std::uint8_t> opaque_indices,
    std::span<const std::int16_t> opaque_depth_q6,
    const Camera& camera,
    const AliasAssets& assets,
    std::size_t sample_index,
    RenderMode mode,
    AliasCoverage* coverage,
    AliasVisibilityRow* visibility
)
{
    if (opaque_indices.size() != kLogicalPixels || opaque_depth_q6.size() != kLogicalPixels)
    {
        fail("post-opaque alias base has incomplete color or depth");
    }
    std::vector<std::uint8_t> composed(opaque_indices.begin(), opaque_indices.end());
    std::vector<std::int16_t> alias_owner;
    std::vector<std::size_t> record_by_token;
    std::map<std::pair<std::size_t, std::size_t>, std::size_t> overwrite_pixels;
    if (coverage != nullptr)
    {
        alias_owner.assign(kLogicalPixels, -1);
        record_by_token.assign(assets.rows.at(sample_index).tokens.size(), std::numeric_limits<std::size_t>::max());
    }
    if (visibility != nullptr)
    {
        visibility->tokens.clear();
        visibility->tokens.resize(assets.rows.at(sample_index).tokens.size());
    }
    for_each_packed_alias_pixel(
        camera,
        assets,
        sample_index,
        [&](std::size_t pixel, int alias_depth_q6, std::uint8_t texel, std::size_t token_ordinal) {
            const bool visible = alias_depth_q6 < opaque_depth_q6[pixel];
            if (visibility != nullptr)
            {
                visibility->tokens.at(token_ordinal).candidates.push_back(static_cast<std::uint8_t>(visible));
            }
            if (!visible)
            {
                if (coverage != nullptr)
                {
                    ++coverage->packed_opaque_occluded_pixels;
                    ++coverage->records.back().opaque_occluded_pixels;
                }
                return;
            }
            if (coverage != nullptr)
            {
                const auto current_record = coverage->records.size() - 1U;
                record_by_token.at(token_ordinal) = current_record;
                const auto prior_owner = alias_owner[pixel];
                if (prior_owner >= 0)
                {
                    const auto earlier_token = static_cast<std::size_t>(prior_owner);
                    const auto earlier_record = record_by_token.at(earlier_token);
                    if (earlier_record == std::numeric_limits<std::size_t>::max())
                    {
                        fail("alias overwrite owner has no coverage record");
                    }
                    ++coverage->records[current_record].overwrote_alias_pixels;
                    ++coverage->records[earlier_record].overwritten_by_alias_pixels;
                    ++overwrite_pixels[{earlier_token, token_ordinal}];
                }
                alias_owner[pixel] = static_cast<std::int16_t>(token_ordinal);
            }
            composed[pixel] = mode.textures ? texel : kUntexturedBrightIndex;
            if (coverage != nullptr)
            {
                ++coverage->packed_visible_pixels;
                ++coverage->records.back().visible_pixels;
            }
        },
        coverage
    );
    if (coverage != nullptr)
    {
        for (const auto owner : alias_owner)
        {
            if (owner < 0)
            {
                continue;
            }
            const auto record = record_by_token.at(static_cast<std::size_t>(owner));
            if (record == std::numeric_limits<std::size_t>::max())
            {
                fail("final alias owner has no coverage record");
            }
            ++coverage->records[record].final_owned_pixels;
        }
        for (const auto& [tokens, pixels] : overwrite_pixels)
        {
            coverage->overwrites.push_back({tokens.first, tokens.second, pixels});
        }
    }
    return composed;
}

Json packed_alias_inspection(
    const Camera& camera,
    const AliasAssets& assets,
    std::size_t source_pose,
    const AliasCoverage& coverage
)
{
    Json aliases = Json::array();
    std::map<std::size_t, int> depth_by_token;
    for (const auto& record : coverage.records)
    {
        const auto& sprite = assets.sprites.at(record.sprite);
        const auto entity =
            record.is_static
                ? (record.state < assets.static_entity_ids.size() ? assets.static_entity_ids[record.state] : -1)
                : (source_pose < assets.row_entity_ids.size() &&
                           record.state < assets.row_entity_ids[source_pose].size()
                       ? assets.row_entity_ids[source_pose][record.state]
                       : -1);
        const auto model_name =
            sprite.model < assets.model_names.size() ? assets.model_names[sprite.model] : std::string{};
        const auto model_kind =
            sprite.model < assets.model_kinds.size() ? assets.model_kinds[sprite.model] : std::string{};
        depth_by_token.emplace(record.token, record.depth_q6);
        aliases.push_back(
            Json{
                {"paintOrdinal", record.paint_ordinal},
                {"tokenOrdinal", record.token},
                {"rawToken", static_cast<int>((record.is_static ? 0x80U : 0U) | record.state)},
                {"state",
                 Json{{"kind", record.is_static ? "static" : "dynamic"}, {"index", record.state}, {"entity", entity}}},
                {"sprite",
                 Json{
                     {"id", record.sprite},
                     {"model", sprite.model},
                     {"modelName", model_name},
                     {"modelKind", model_kind},
                     {"frame", sprite.frame},
                     {"projectedView", sprite.view},
                     {"sourceFrame", sprite.frame},
                     {"sourceView", sprite.view},
                     {"sourceSubframe", model_kind == "spr" ? sprite.view : 0},
                     {"sourceWidth", sprite.width},
                     {"sourceHeight", sprite.height},
                     {"worldWidth", alias_world_width(sprite)},
                     {"worldHeight", alias_world_height(sprite)},
                     {"left", sprite.left},
                     {"top", sprite.top}
                 }},
                {"group", Json{{"leaf", record.leaf}, {"parent", record.parent}}},
                {"originQ2", Json::array({record.origin_q2[0], record.origin_q2[1], record.origin_q2[2]})},
                {"viewQ6", Json{{"right", record.right_q6}, {"up", record.up_q6}, {"depth", record.depth_q6}}},
                {"bounds",
                 Json{
                     {"firstX", record.first_x},
                     {"firstY", record.first_y},
                     {"lastX", record.last_x},
                     {"lastY", record.last_y},
                     {"clipped",
                      record.first_x < 0 || record.first_y < 0 || record.last_x >= kLogicalWidth ||
                          record.last_y >= kLogicalHeight}
                 }},
                {"pixels",
                 Json{
                     {"plot", record.plot_pixels},
                     {"opaqueVisible", record.visible_pixels},
                     {"opaqueOccluded", record.opaque_occluded_pixels},
                     {"overwroteAlias", record.overwrote_alias_pixels},
                     {"overwrittenByAlias", record.overwritten_by_alias_pixels},
                     {"finalOwned", record.final_owned_pixels}
                 }}
            }
        );
    }
    Json overwrites = Json::array();
    std::size_t farther_over_nearer_pixels{};
    for (const auto& overwrite : coverage.overwrites)
    {
        const auto earlier_depth = depth_by_token.at(overwrite.earlier_token);
        const auto later_depth = depth_by_token.at(overwrite.later_token);
        const bool farther_over_nearer = later_depth > earlier_depth;
        if (farther_over_nearer)
        {
            farther_over_nearer_pixels += overwrite.pixels;
        }
        overwrites.push_back(
            Json{
                {"earlierToken", overwrite.earlier_token},
                {"laterToken", overwrite.later_token},
                {"pixels", overwrite.pixels},
                {"earlierDepthQ6", earlier_depth},
                {"laterDepthQ6", later_depth},
                {"fartherOverNearer", farther_over_nearer}
            }
        );
    }
    return Json{
        {"schema", "quake-reference-alias-inspection-v1"},
        {"available", true},
        {"sourcePose", source_pose},
        {"camera",
         Json{{"x", camera.x}, {"y", camera.y}, {"z", camera.z}, {"yaw", camera.yaw}, {"pitch", camera.pitch}}},
        {"orderingContract", "global-depth-q6-far-to-near-stable-token-ties"},
        {"summary",
         Json{
             {"tokens", coverage.tokens},
             {"projected", coverage.projected},
             {"clipped", coverage.clipped},
             {"plotPixels", coverage.packed_plot_pixels},
             {"opaqueVisiblePixels", coverage.packed_visible_pixels},
             {"opaqueOccludedPixels", coverage.packed_opaque_occluded_pixels},
             {"aliasOverwritePairs", coverage.overwrites.size()},
             {"fartherOverNearerPixels", farther_over_nearer_pixels}
         }},
        {"aliases", std::move(aliases)},
        {"overwrites", std::move(overwrites)}
    };
}

ReferenceFrame render_source_reference_with_aliases(
    const SourceWorld& world,
    const Bvh& world_bvh,
    const BrushScene& scene,
    const AliasAssets& aliases,
    const SourceCamera& camera,
    const BrushReplay& replay,
    std::size_t sample_index,
    bool flat,
    bool brushes_enabled,
    bool aliases_enabled,
    AliasCoverage* coverage,
    const ExternalBspScene* external_scene,
    const ExternalBspReplay* external_replay,
    bool external_models_enabled,
    ExternalBspCoverage* external_coverage
)
{
    auto frame = render_source_reference_with_brushes(
        world,
        world_bvh,
        scene,
        camera,
        replay,
        sample_index,
        flat,
        brushes_enabled
    );
    if (external_replay != nullptr)
    {
        if (sample_index >= external_replay->row_count())
        {
            fail("external BSP source pose is out of range");
        }
        if (external_coverage != nullptr)
        {
            *external_coverage = external_bsp_row_coverage(*external_replay, sample_index);
        }
        if (external_models_enabled)
        {
            if (external_scene == nullptr)
            {
                fail("external BSP rendering has no loaded model scene");
            }
            compose_source_external_bsp_models(
                *external_scene,
                external_replay->row(sample_index),
                sample_index,
                external_bsp_server_time(*external_replay, sample_index),
                flat,
                source_view_transform(camera),
                frame,
                external_coverage
            );
        }
    }
    else if (external_models_enabled)
    {
        fail("external BSP rendering requires a QER1 replay");
    }
    if (aliases_enabled)
    {
        compose_alias_billboards(frame, world, source_view_transform(camera), aliases, sample_index, coverage);
    }
    return frame;
}

} // namespace quake_bsp_reference
