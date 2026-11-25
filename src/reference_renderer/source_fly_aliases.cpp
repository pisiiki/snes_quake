#include "source_fly_aliases.hpp"

namespace quake_bsp_reference {
namespace {
std::string hash_bytes(std::span<const std::uint8_t> bytes)
{
    std::ostringstream stream;
    stream << std::hex << std::setfill('0') << std::setw(16) << brush_fnv1a64(bytes);
    return stream.str();
}

void require_bytes(std::span<const std::uint8_t> bytes, std::size_t cursor, std::size_t count)
{
    if (cursor > bytes.size() || count > bytes.size() - cursor)
        fail("QFA1 record exceeds its payload");
}
} // namespace

SourceFlyAliases load_source_fly_aliases(
    const fs::path& path,
    std::span<const std::uint8_t> pak,
    const fs::path& camera,
    const BrushReplay& brushes,
    const AliasAssets& original,
    std::string_view map_entry
)
{
    const auto bytes = read_file(path);
    if (bytes.size() < 8 || bytes.size() > 64U * 1024U * 1024U ||
        std::string(bytes.begin(), bytes.begin() + 4) != "QFA1")
        fail("QFA1 header or file size is invalid");
    const auto header_size = read_u32(bytes, 4);
    if (header_size == 0 || header_size > 1024U * 1024U)
        fail("QFA1 metadata size is invalid");
    require_bytes(bytes, 8, header_size);
    const auto metadata = Json::parse(bytes.begin() + 8, bytes.begin() + 8 + header_size);
    const std::span<const std::uint8_t> payload(bytes.data() + 8 + header_size, bytes.size() - 8 - header_size);
    if (metadata.at("schema") != "quake-source-fly-aliases-v1" ||
        metadata.at("mapEntry").get<std::string>() != map_entry ||
        metadata.at("cameraFnv64") != hash_bytes(read_file(camera)) || metadata.at("pakFnv64") != hash_bytes(pak) ||
        metadata.at("paletteFnv64") != hash_bytes(extract_pak_entry(pak, "gfx/palette.lmp")) ||
        metadata.at("colormapFnv64") != hash_bytes(extract_pak_entry(pak, "gfx/colormap.lmp")) ||
        metadata.at("payloadFnv64") != hash_bytes(payload) ||
        std::stoull(metadata.at("aliasPackageFnv64").get<std::string>(), nullptr, 16) != original.package_fingerprint ||
        metadata.at("poses") != brushes.row_count() || metadata.at("sampleRate") != brushes.sample_rate ||
        std::abs(metadata.at("firstServerTime").get<double>() - brushes.first_server_time) > 0.000001)
        fail("QFA1 source, color, camera, clock, alias package, or payload binding mismatch");
    SourceFlyAliases result;
    auto& assets = result.assets;
    assets.camera_fingerprint = original.camera_fingerprint;
    assets.package_fingerprint = brush_fnv1a64(bytes);
    for (const auto& model : metadata.at("models"))
    {
        assets.model_names.push_back(model.at("name").get<std::string>());
        assets.model_kinds.push_back(model.at("kind").get<std::string>());
    }
    if (assets.model_names != original.model_names || assets.model_kinds != original.model_kinds)
        fail("QFA1 model inventory differs from the original alias package");
    assets.model_rotates = original.model_rotates;
    const auto sprite_count = metadata.at("sprites").get<std::size_t>();
    if (sprite_count == 0 || sprite_count > 0x8000U)
        fail("QFA1 sprite count escapes the directional ID range");
    std::size_t cursor = 0;
    for (std::size_t index = 0; index < sprite_count; ++index)
    {
        require_bytes(payload, cursor, 15);
        AliasSprite sprite;
        sprite.width = payload[cursor];
        sprite.height = payload[cursor + 1];
        sprite.world_width = payload[cursor + 2];
        sprite.world_height = payload[cursor + 3];
        sprite.model = payload[cursor + 4];
        sprite.frame = payload[cursor + 5];
        sprite.view = payload[cursor + 6];
        sprite.left = read_i16(payload, cursor + 7);
        sprite.top = read_i16(payload, cursor + 9);
        const auto count = read_u32(payload, cursor + 11);
        cursor += 15;
        if (count == 0 || count != static_cast<std::size_t>(sprite.width) * sprite.height ||
            sprite.model >= assets.model_names.size())
            fail("QFA1 sprite dimensions or model are invalid");
        require_bytes(payload, cursor, count);
        sprite.pixels.assign(payload.begin() + cursor, payload.begin() + cursor + count);
        cursor += count;
        assets.sprites.push_back(std::move(sprite));
    }
    if (cursor != metadata.at("statesOffset").get<std::size_t>())
        fail("QFA1 state directory does not follow its sprites");
    std::size_t total_states = 0;
    for (std::size_t pose = 0; pose < brushes.row_count(); ++pose)
    {
        require_bytes(payload, cursor, 3);
        const auto count = read_u16(payload, cursor);
        result.rotations.push_back(payload[cursor + 2]);
        cursor += 3;
        if (count >= 128)
            fail("QFA1 row exceeds seven-bit token capacity");
        AliasRow row;
        std::vector<int> entities;
        for (std::uint16_t index = 0; index < count; ++index)
        {
            require_bytes(payload, cursor, 16);
            AliasState state;
            state.sprite = read_u16(payload, cursor);
            for (std::size_t axis = 0; axis < 3; ++axis)
                state.origin_q2[axis] = read_i16(payload, cursor + 2 + axis * 2);
            state.yaw_sin_q6 = static_cast<std::int8_t>(payload[cursor + 8]);
            state.yaw_cos_q6 = static_cast<std::int8_t>(payload[cursor + 9]);
            const auto entity = read_u16(payload, cursor + 10);
            const auto leaf = read_u16(payload, cursor + 12);
            const auto parent = read_u16(payload, cursor + 14);
            cursor += 16;
            const auto base = alias_sprite_id(state);
            if (base >= assets.sprites.size() || std::ranges::find(entities, entity) != entities.end())
                fail("QFA1 state sprite is invalid or entity is repeated");
            if ((state.sprite & kAliasDirectionalTag) != 0)
            {
                if (base + 8 > assets.sprites.size())
                    fail("QFA1 directional sprite range exceeds its atlas");
                for (std::size_t view = 0; view < 8; ++view)
                    if (assets.sprites[base + view].view != view ||
                        assets.sprites[base + view].model != assets.sprites[base].model ||
                        assets.sprites[base + view].frame != assets.sprites[base].frame)
                        fail("QFA1 directional sprites are not contiguous matching views");
            }
            row.dynamic_states.push_back(state);
            entities.push_back(entity);
            if (parent != 0xffffU)
                row.tokens.push_back({false, static_cast<std::uint8_t>(index), leaf, parent});
        }
        total_states += count;
        assets.rows.push_back(std::move(row));
        assets.row_entity_ids.push_back(std::move(entities));
    }
    if (cursor != payload.size() || total_states != metadata.at("totalStates").get<std::size_t>())
        fail("QFA1 total state count or trailing bytes mismatch");
    result.provenance = {
        {"schema", "quake-source-fly-aliases-v1"},
        {"policy", metadata.at("policy")},
        {"payloadSha256", metadata.at("payloadSha256")},
        {"membershipSha256", metadata.at("membershipSha256")},
        {"poses", assets.rows.size()},
        {"sprites", assets.sprites.size()},
        {"sourceBindingVerified", true}
    };
    return result;
}

} // namespace quake_bsp_reference
