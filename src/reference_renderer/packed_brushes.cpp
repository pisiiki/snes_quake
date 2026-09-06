#include "packed_brushes.hpp"
#include "world.hpp"
#include "geometry.hpp"
#include "textured_live.hpp"
#include "turbulence.hpp"

namespace quake_bsp_reference {

namespace {
const PackedBrushSection& packed_brush_section(const PackedBrushAssets& assets, std::string_view name)
{
    const auto found = std::ranges::find(assets.sections, name, &PackedBrushSection::name);
    if (found == assets.sections.end())
    {
        fail("QBSA lacks section " + std::string(name));
    }
    return *found;
}
} // namespace

namespace {
std::vector<std::vector<std::uint8_t>>
load_numbered_brush_banks(const fs::path& data_dir, std::string_view stem, int count)
{
    std::vector<std::vector<std::uint8_t>> banks;
    banks.reserve(static_cast<std::size_t>(count));
    for (int index = 0; index < count; ++index)
    {
        auto bytes = read_file(data_dir / (std::string(stem) + std::to_string(index) + ".bin"));
        if (bytes.size() != kBrushRomBankBytes)
        {
            fail(std::string(stem) + " bank has the wrong byte count");
        }
        banks.push_back(std::move(bytes));
    }
    return banks;
}
} // namespace

namespace {
std::vector<PackedBrushSection> load_brush_runtime_sections(const fs::path& data_dir)
{
    const auto first = read_file(data_dir / "QuakeBSPBrushRuntime0.bin");
    if (first.size() != kBrushRomBankBytes)
    {
        fail("QuakeBSPBrushRuntime0 bank has the wrong byte count");
    }
    const auto bank_count = read_u16(first, 6);
    if (bank_count == 0)
    {
        fail("QBSA runtime header names no banks");
    }
    auto banks = load_numbered_brush_banks(data_dir, "QuakeBSPBrushRuntime", bank_count);
    const auto& header = banks.front();
    if (std::string_view(reinterpret_cast<const char*>(header.data()), 4) != "QBSA" || read_u16(header, 4) != 1 ||
        read_u16(header, 6) != banks.size())
    {
        fail("unsupported QBSA runtime header");
    }
    const auto section_count = read_u16(header, 22);
    constexpr std::size_t header_bytes = 32;
    constexpr std::size_t section_bytes = 16;
    require_range(
        header,
        header_bytes,
        static_cast<std::size_t>(section_count) * section_bytes,
        "QBSA section directory"
    );
    std::uint8_t first_bank = 0xff;
    for (std::size_t index = 0; index < section_count; ++index)
    {
        first_bank = std::min(first_bank, header[header_bytes + index * section_bytes + 8]);
    }
    std::vector<PackedBrushSection> sections;
    sections.reserve(section_count);
    for (std::size_t index = 0; index < section_count; ++index)
    {
        const auto offset = header_bytes + index * section_bytes;
        std::string name(reinterpret_cast<const char*>(header.data() + offset), 8);
        if (const auto end = name.find('\0'); end != std::string::npos)
        {
            name.resize(end);
        }
        const auto bank = header[offset + 8];
        const auto address = read_u16(header, offset + 9);
        const auto bytes = read_u16(header, offset + 11);
        const auto record_bytes = header[offset + 13];
        const auto record_count = read_u16(header, offset + 14);
        if (bank < first_bank || static_cast<std::size_t>(bank - first_bank) >= banks.size() || address < 0x8000)
        {
            fail("QBSA section has an invalid bank/address");
        }
        const auto bank_index = static_cast<std::size_t>(bank - first_bank);
        const auto bank_offset = static_cast<std::size_t>(address - 0x8000);
        require_range(banks[bank_index], bank_offset, bytes, "QBSA " + name + " section");
        sections.push_back({
            std::move(name),
            std::vector<std::uint8_t>(
                banks[bank_index].begin() + static_cast<std::ptrdiff_t>(bank_offset),
                banks[bank_index].begin() + static_cast<std::ptrdiff_t>(bank_offset + bytes)
            ),
            bank,
            address,
            record_bytes,
            record_count,
        });
    }
    return sections;
}
} // namespace

namespace {
PackedVertex decode_brush_q2_vertex(std::span<const std::uint8_t> bytes, std::size_t offset)
{
    require_range(bytes, offset, 4, "QBSF vertex");
    const int residual = bytes[offset + 3];
    return {
        static_cast<std::int16_t>(decode_i8(bytes[offset]) * 4 + (residual & 3)),
        static_cast<std::int16_t>(decode_i8(bytes[offset + 1]) * 4 + ((residual >> 2) & 3)),
        static_cast<std::int16_t>(decode_i8(bytes[offset + 2]) * 4 + ((residual >> 4) & 3)),
    };
}
} // namespace

PackedBrushAssets load_packed_brush_assets(const fs::path& data_dir)
{
    PackedBrushAssets assets;
    assets.sections = load_brush_runtime_sections(data_dir);
    const auto runtime_header = read_file(data_dir / "QuakeBSPBrushRuntime0.bin");
    assets.leaf_count = read_u16(runtime_header, 20);
    if (assets.leaf_count == 0)
    {
        fail("QBSA runtime header names no world leaves");
    }
    auto fragment_banks = load_numbered_brush_banks(data_dir, "QuakeBSPBrushFragments", 1);
    const auto& first_fragment_header = fragment_banks.front();
    if (std::string_view(reinterpret_cast<const char*>(first_fragment_header.data()), 4) != "QBSF" ||
        read_u32(first_fragment_header, 4) != 4)
    {
        fail("unsupported QBSF fragment header");
    }
    const int bank_count = static_cast<int>(read_u32(first_fragment_header, 8));
    fragment_banks = load_numbered_brush_banks(data_dir, "QuakeBSPBrushFragments", bank_count);
    const auto& header = fragment_banks.front();
    const auto descriptor_first = read_u32(header, 12);
    const auto descriptor_banks = read_u32(header, 16);
    const auto vertex_first = read_u32(header, 20);
    const auto vertex_banks = read_u32(header, 24);
    const auto variant_count = read_u32(header, 28);
    const auto bucket_count = read_u32(header, 32);
    const auto fragment_count = read_u32(header, 36);
    const auto vertex_count = read_u32(header, 40);
    const auto face_count = read_u32(header, 44);
    const auto variant_location = read_u32(header, 48);
    const auto face_location = read_u32(header, 52);
    const auto bucket_location = read_u32(header, 56);
    const auto variant_bank = variant_location >> 16;
    const auto face_bank = face_location >> 16;
    const auto bucket_bank = bucket_location >> 16;
    const auto variant_offset = variant_location & 0xffff;
    const auto face_offset = face_location & 0xffff;
    const auto bucket_offset = bucket_location & 0xffff;
    if (descriptor_first + descriptor_banks > fragment_banks.size() ||
        vertex_first + vertex_banks > fragment_banks.size() || variant_bank >= fragment_banks.size() ||
        face_bank >= fragment_banks.size() || bucket_bank >= fragment_banks.size())
    {
        fail("QBSF payload bank ranges escape the package");
    }
    const auto& variants = fragment_banks[variant_bank];
    const auto& faces = fragment_banks[face_bank];
    const auto& buckets = fragment_banks[bucket_bank];
    std::vector<std::uint8_t> descriptors;
    for (std::size_t bank = descriptor_first; bank < descriptor_first + descriptor_banks; ++bank)
    {
        descriptors.insert(descriptors.end(), fragment_banks[bank].begin(), fragment_banks[bank].end());
    }
    std::vector<std::uint8_t> vertices;
    for (std::size_t bank = vertex_first; bank < vertex_first + vertex_banks; ++bank)
    {
        vertices.insert(vertices.end(), fragment_banks[bank].begin(), fragment_banks[bank].end());
    }
    require_range(variants, variant_offset, static_cast<std::size_t>(variant_count) * 24, "QBSF variants");
    require_range(faces, face_offset, static_cast<std::size_t>(face_count) * 16, "QBSF faces");
    require_range(buckets, bucket_offset, static_cast<std::size_t>(bucket_count) * 8, "QBSF buckets");
    require_range(descriptors, 0, static_cast<std::size_t>(fragment_count) * 8, "QBSF fragments");
    require_range(vertices, 0, static_cast<std::size_t>(vertex_count) * 4, "QBSF vertices");
    assets.variants.reserve(variant_count);
    for (std::size_t index = 0; index < variant_count; ++index)
    {
        const auto offset = variant_offset + index * 24;
        assets.variants.push_back(
            {variants[offset],
             read_i16(variants, offset + 2),
             read_i16(variants, offset + 4),
             read_i16(variants, offset + 6),
             read_u16(variants, offset + 8),
             read_u16(variants, offset + 10),
             {read_i16(variants, offset + 12), read_i16(variants, offset + 14), read_i16(variants, offset + 16)},
             {read_u16(variants, offset + 18), read_u16(variants, offset + 20), read_u16(variants, offset + 22)}}
        );
    }
    assets.faces.reserve(face_count);
    for (std::size_t index = 0; index < face_count; ++index)
    {
        const auto offset = face_offset + index * 16;
        assets.faces.push_back(
            {read_u16(faces, offset),
             read_u16(faces, offset + 2),
             read_u16(faces, offset + 4),
             faces[offset + 6],
             decode_i8(faces[offset + 7]),
             decode_i8(faces[offset + 8]),
             read_i16(faces, offset + 9),
             read_i16(faces, offset + 11),
             faces[offset + 13],
             faces[offset + 14],
             faces[offset + 15]}
        );
    }
    assets.buckets.reserve(bucket_count);
    for (std::size_t index = 0; index < bucket_count; ++index)
    {
        const auto offset = bucket_offset + index * 8;
        assets.buckets.push_back(
            {read_u16(buckets, offset),
             read_u16(buckets, offset + 2),
             buckets[offset + 4],
             buckets[offset + 5] != 0,
             read_u16(buckets, offset + 6)}
        );
    }
    assets.fragments.reserve(fragment_count);
    for (std::size_t index = 0; index < fragment_count; ++index)
    {
        const auto offset = index * 8;
        assets.fragments.push_back(
            {read_u16(descriptors, offset), read_u32(descriptors, offset + 2), descriptors[offset + 6]}
        );
    }
    assets.vertices.reserve(vertex_count);
    for (std::size_t index = 0; index < vertex_count; ++index)
    {
        assets.vertices.push_back(decode_brush_q2_vertex(vertices, index * 4));
    }
    const auto& replay = packed_brush_section(assets, "REPLAY");
    if (replay.bytes.size() < 32 || read_u16(replay.bytes, 4) != 2 ||
        std::string_view(reinterpret_cast<const char*>(replay.bytes.data()), 4) != "QBSE")
    {
        fail("unsupported compact brush replay");
    }
    const auto entity_count = read_u16(replay.bytes, 18);
    require_range(replay.bytes, 32, static_cast<std::size_t>(entity_count) * 6, "QBSE entity directory");
    assets.entities.reserve(entity_count);
    for (std::size_t slot = 0; slot < entity_count; ++slot)
    {
        const auto offset = 32 + slot * 6;
        assets.entities.push_back(
            {read_u16(replay.bytes, offset),
             replay.bytes[offset + 2],
             replay.bytes[offset + 3],
             read_u16(replay.bytes, offset + 4)}
        );
    }
    assets.external_entity_slot_first = assets.entities.size();
    const auto metadata_bytes = read_file(data_dir / "QuakeBSPBrushAssets.json");
    const auto metadata =
        Json::parse(std::string(reinterpret_cast<const char*>(metadata_bytes.data()), metadata_bytes.size()));
    const auto& visual_states = metadata.at("visualStates");
    const bool external_supported =
        visual_states.contains("externalBsp") && visual_states.at("externalBsp").at("supported").get<bool>();
    std::size_t external_fly_static_count = 0;
    std::size_t external_fly_extra_slot_count = 0;
    if (external_supported)
    {
        const auto& external = visual_states.at("externalBsp");
        const auto first = external.at("firstEntitySlot").get<std::size_t>();
        const auto count = external.at("entitySlotCount").get<std::size_t>();
        if (first + count != assets.entities.size())
        {
            fail("external BSP slots are not the compact replay suffix");
        }
        assets.external_entity_slot_first = first;
        assets.external_active_row_bytes = external.at("activeRowBytes").get<std::size_t>();
        external_fly_static_count = external.at("flyStaticCount").get<std::size_t>();
        external_fly_extra_slot_count = external.at("flyExtraSlotCount").get<std::size_t>();
    }
    const auto& static_variants = packed_brush_section(assets, "VSTATIC");
    if (static_variants.record_bytes != 4 ||
        static_variants.bytes.size() != static_cast<std::size_t>(static_variants.record_count) * 4)
    {
        fail("QBSA VSTATIC directory is inconsistent");
    }
    assets.static_variants.reserve(static_variants.record_count);
    for (std::size_t index = 0; index < static_variants.record_count; ++index)
    {
        const auto offset = index * 4;
        const auto geometry = read_u16(static_variants.bytes, offset + 2);
        if (geometry >= assets.variants.size())
        {
            fail("QBSA VSTATIC escapes QBSF variants");
        }
        assets.static_variants.push_back({read_u16(static_variants.bytes, offset), geometry});
    }
    if (external_supported)
    {
        const auto& external_static = packed_brush_section(assets, "XSTATIC");
        if (external_static.record_bytes != 5 || external_static.record_count != external_fly_static_count ||
            external_static.bytes.size() != static_cast<std::size_t>(external_static.record_count) * 5)
        {
            fail("QBSA XSTATIC directory is inconsistent");
        }
        const auto fly_extra_slot_first = assets.entities.size() + assets.static_variants.size();
        const auto fly_extra_slot_limit = fly_extra_slot_first + external_fly_extra_slot_count;
        assets.external_static_variants.reserve(external_static.record_count);
        for (std::size_t index = 0; index < external_static.record_count; ++index)
        {
            const auto offset = index * 5;
            const auto entity = read_u16(external_static.bytes, offset);
            const auto geometry = read_u16(external_static.bytes, offset + 2);
            const auto slot = external_static.bytes[offset + 4];
            const bool compact_slot =
                slot >= assets.external_entity_slot_first && slot < assets.entities.size() &&
                assets.entities[slot].entity == entity;
            const bool fly_extra_slot = slot >= fly_extra_slot_first && slot < fly_extra_slot_limit;
            if (geometry >= assets.variants.size() || (!compact_slot && !fly_extra_slot))
            {
                fail("QBSA XSTATIC escapes the external replay suffix");
            }
            assets.external_static_variants.push_back({entity, geometry, slot});
        }
    }
    const auto& planes = packed_brush_section(assets, "PLANES");
    if (planes.record_bytes != 5 || planes.record_count != assets.faces.size() ||
        planes.bytes.size() != static_cast<std::size_t>(planes.record_count) * 5)
    {
        fail("QBSA brush face-plane directory is inconsistent");
    }
    assets.face_planes.reserve(planes.record_count);
    for (std::size_t index = 0; index < planes.record_count; ++index)
    {
        const auto offset = index * 5;
        assets.face_planes.push_back(
            {decode_i8(planes.bytes[offset]),
             decode_i8(planes.bytes[offset + 1]),
             decode_i8(planes.bytes[offset + 2]),
             read_i16(planes.bytes, offset + 3)}
        );
    }
    return assets;
}

namespace {
PackedBrushVisualState decode_packed_brush_visual_state(const PackedBrushAssets& assets, std::uint16_t state)
{
    if (state == 0)
    {
        fail("packed brush reference requires a nonzero visual state");
    }
    const auto& states = packed_brush_section(assets, "VSTATES");
    const auto& transforms = packed_brush_section(assets, "VTRANS");
    const auto& textures = packed_brush_section(assets, "VTEX");
    if (states.record_bytes != 8 || transforms.record_bytes != 2 || textures.record_bytes != 3 ||
        state > states.record_count)
    {
        fail("QBSA visual-state directory is inconsistent");
    }
    const auto offset = static_cast<std::size_t>(state - 1) * 8;
    const auto first_transform = read_u16(states.bytes, offset);
    const auto first_texture = read_u16(states.bytes, offset + 2);
    const auto transform_count = states.bytes[offset + 6];
    const auto texture_count = states.bytes[offset + 7];
    PackedBrushVisualState output;
    output.transforms.reserve(transform_count);
    for (std::size_t index = 0; index < transform_count; ++index)
    {
        const auto entry = static_cast<std::size_t>(first_transform + index) * 2;
        require_range(transforms.bytes, entry, 2, "QBSA VTRANS");
        output.transforms.emplace_back(transforms.bytes[entry], transforms.bytes[entry + 1]);
    }
    output.textures.reserve(texture_count);
    for (std::size_t index = 0; index < texture_count; ++index)
    {
        const auto entry = static_cast<std::size_t>(first_texture + index) * 3;
        require_range(textures.bytes, entry, 3, "QBSA VTEX");
        output.textures.push_back({textures.bytes[entry], textures.bytes[entry + 1], textures.bytes[entry + 2]});
    }
    return output;
}
} // namespace

std::uint16_t packed_brush_visual_state_at_pose(const PackedBrushAssets& assets, std::size_t pose)
{
    const auto& rows = packed_brush_section(assets, "ROWSTATE");
    if (rows.record_bytes != 2 || rows.bytes.size() != static_cast<std::size_t>(rows.record_count) * 2U ||
        pose >= rows.record_count)
    {
        fail("QBSA ROWSTATE cannot resolve the requested enabled pose");
    }
    const auto state = read_u16(rows.bytes, pose * 2);
    if (state == 0)
    {
        fail("QBSA ROWSTATE contains disabled state zero");
    }
    return state;
}

namespace {
bool packed_external_static_active(const PackedBrushAssets& assets, std::size_t pose, std::size_t static_index)
{
    const auto& rows = packed_brush_section(assets, "XACTIVE");
    const auto row_count = packed_brush_section(assets, "ROWSTATE").record_count;
    if (assets.external_active_row_bytes == 0 || rows.record_bytes != 1 || rows.record_count != rows.bytes.size() ||
        rows.bytes.size() != row_count * assets.external_active_row_bytes || pose >= row_count ||
        static_index >= assets.external_static_variants.size() || static_index >= assets.external_active_row_bytes * 8)
    {
        fail("QBSA XACTIVE cannot resolve the requested fly state");
    }
    const auto byte = pose * assets.external_active_row_bytes + static_index / 8;
    return (rows.bytes[byte] & (1U << (static_index & 7))) != 0;
}

std::vector<PackedBrushToken> build_packed_brush_tokens(
    PackedBrushAssets& assets,
    const PacketSelection& packet,
    const Camera& camera,
    const PackedBrushVisualState& visual,
    const fs::path& data_dir,
    std::span<const PackedBrushActiveGeometry> extra_geometry = {}
)
{
    const auto& variant_map = packed_brush_section(assets, "VFRAG");
    std::vector<std::uint16_t> leaf_heads(assets.leaf_count);
    assets.active_geometry_by_slot.assign(assets.entities.size(), 0xffff);
    assets.links.clear();
    const auto activate = [&](std::uint8_t slot, std::uint16_t geometry) {
        if (slot >= assets.entities.size() || geometry >= assets.variants.size())
        {
            fail("QBSA active geometry escapes its packed directories");
        }
        const auto& variant = assets.variants[geometry];
        assets.active_geometry_by_slot[slot] = geometry;
        for (std::size_t bucket_index = variant.first_bucket;
             bucket_index < static_cast<std::size_t>(variant.first_bucket) + variant.bucket_count;
             ++bucket_index)
        {
            if (bucket_index >= assets.buckets.size())
            {
                fail("QBSF variant escapes its bucket directory");
            }
            const auto& bucket = assets.buckets[bucket_index];
            if (bucket.leaf >= leaf_heads.size())
            {
                fail("QBSF bucket names an invalid world leaf");
            }
            if (bucket.solid)
            {
                continue;
            }
            for (std::size_t fragment = bucket.first_fragment;
                 fragment < static_cast<std::size_t>(bucket.first_fragment) + bucket.fragment_count;
                 ++fragment)
            {
                if (fragment >= assets.fragments.size() || assets.links.size() >= 1024)
                {
                    fail("QBSF active link capacity is exceeded");
                }
                assets.links.push_back({static_cast<std::uint16_t>(fragment), leaf_heads[bucket.leaf], slot});
                leaf_heads[bucket.leaf] = static_cast<std::uint16_t>(assets.links.size());
            }
        }
    };
    for (const auto& [slot, local_variant] : visual.transforms)
    {
        if (slot >= assets.entities.size())
        {
            fail("QBSA transform names an invalid entity slot");
        }
        const auto& entity = assets.entities[slot];
        if (local_variant >= entity.variant_count)
        {
            fail("QBSA transform names an invalid local variant");
        }
        const auto global_variant = static_cast<std::size_t>(entity.first_variant + local_variant);
        require_range(variant_map.bytes, global_variant * 2, 2, "QBSA VFRAG");
        const auto geometry = read_u16(variant_map.bytes, global_variant * 2);
        if (geometry >= assets.variants.size())
        {
            fail("QBSA VFRAG escapes QBSF variants");
        }
        activate(slot, geometry);
    }
    for (const auto active : extra_geometry)
    {
        activate(active.slot, active.geometry);
    }
    const auto nodes = read_file(data_dir / "QuakeBSPWorldNodes.bin");
    const auto planes = read_file(data_dir / "QuakeBSPWorldPlanes.bin");
    if (nodes.empty() || nodes.size() % 10 != 0 || planes.empty() || planes.size() % 5 != 0)
    {
        fail("packed brush traversal assets have invalid record sizes");
    }
    assets.tokens.clear();
    struct StackItem
    {
        std::int16_t node{};
        bool emit{};
    };
    std::vector<StackItem> stack{{0, false}};
    while (!stack.empty())
    {
        const auto item = stack.back();
        stack.pop_back();
        if (item.node < 0)
        {
            const auto leaf = static_cast<std::uint16_t>(~item.node);
            if (leaf >= leaf_heads.size())
            {
                fail("world node names an invalid brush leaf");
            }
            auto head = leaf_heads[leaf];
            if (head != 0)
            {
                assets.tokens.push_back({PackedBrushTokenKind::leaf_marker, leaf});
            }
            while (head != 0)
            {
                const auto link = static_cast<std::size_t>(head - 1);
                assets.tokens.push_back({PackedBrushTokenKind::brush, static_cast<std::uint16_t>(link)});
                head = assets.links.at(link).prior_head;
            }
            continue;
        }
        const auto node = static_cast<std::size_t>(item.node);
        require_range(nodes, node * 10, 10, "world BSP node");
        const auto node_offset = node * 10;
        if (item.emit)
        {
            const auto first_face = read_u16(nodes, node_offset + 6);
            const auto face_count = read_u16(nodes, node_offset + 8);
            for (std::size_t face = first_face; face < static_cast<std::size_t>(first_face) + face_count; ++face)
            {
                if (face < packet.selected_faces.size() && packet.selected_faces[face] != 0)
                {
                    assets.tokens.push_back({PackedBrushTokenKind::world, static_cast<std::uint16_t>(face)});
                }
            }
            continue;
        }
        const auto plane = read_u16(nodes, node_offset);
        require_range(planes, static_cast<std::size_t>(plane) * 5, 5, "world BSP plane");
        const auto plane_offset = static_cast<std::size_t>(plane) * 5;
        const int distance =
            camera.x * decode_i8(planes[plane_offset]) + camera.y * decode_i8(planes[plane_offset + 1]) +
            camera.z * decode_i8(planes[plane_offset + 2]) - read_i16(planes, plane_offset + 3);
        const auto front = read_i16(nodes, node_offset + 2);
        const auto back = read_i16(nodes, node_offset + 4);
        const auto near_child = distance < 0 ? back : front;
        const auto far_child = distance < 0 ? front : back;
        stack.push_back({near_child, false});
        stack.push_back({item.node, true});
        stack.push_back({far_child, false});
    }
    return assets.tokens;
}
} // namespace

namespace {
void append_packed_brush_textures(SourceWorld& world, const PackedBrushAssets& assets, const fs::path& data_dir)
{
    const auto& directory = packed_brush_section(assets, "TEXDIR");
    if (directory.record_bytes != kPackedTextureDirectoryBytes ||
        directory.bytes.size() != static_cast<std::size_t>(directory.record_count) * kPackedTextureDirectoryBytes)
    {
        fail("QBSA TEXDIR is inconsistent");
    }
    if (directory.record_count == 0)
    {
        return;
    }
    std::uint8_t first_bank = 0xff;
    std::size_t required_bytes = 0;
    for (std::size_t index = 0; index < directory.record_count; ++index)
    {
        const auto offset = index * kPackedTextureDirectoryBytes;
        first_bank = std::min(first_bank, directory.bytes[offset]);
    }
    for (std::size_t index = 0; index < directory.record_count; ++index)
    {
        const auto offset = index * kPackedTextureDirectoryBytes;
        const auto bank = directory.bytes[offset];
        const auto address = read_u16(directory.bytes, offset + 1);
        const auto width = read_u16(directory.bytes, offset + 3);
        const auto height = read_u16(directory.bytes, offset + 5);
        const auto flags = directory.bytes[offset + 7];
        auto expected_flags =
            std::has_single_bit(width) && std::has_single_bit(height)
                ? kPackedTextureFlagPowerOfTwoAxes
                : std::uint8_t{0};
        const auto pixel_count = static_cast<std::size_t>(width) * height;
        if ((address & 0x7fffU) + pixel_count <= kPackedRomBankBytes)
        {
            expected_flags |= kPackedTextureFlagSingleBank;
        }
        if ((flags & kPackedTextureFlagTurbulent) != 0)
        {
            expected_flags |= kPackedTextureFlagTurbulent;
            if (width != 64 || height != 64)
            {
                fail("packed brush turbulent texture is not 64x64");
            }
        }
        if (bank < first_bank || address < 0x8000 || width == 0 || height == 0 || flags != expected_flags)
        {
            fail("QBSA TEXDIR has an invalid texture record");
        }
        const auto linear = static_cast<std::size_t>(bank - first_bank) * kBrushRomBankBytes + (address - 0x8000);
        required_bytes = std::max(required_bytes, linear + pixel_count);
    }
    const int bank_count = static_cast<int>((required_bytes + kBrushRomBankBytes - 1) / kBrushRomBankBytes);
    const auto banks = load_numbered_brush_banks(data_dir, "QuakeBSPBrushTexturePixels", bank_count);
    std::vector<std::uint8_t> pixels;
    pixels.reserve(banks.size() * kBrushRomBankBytes);
    for (const auto& bank : banks)
    {
        pixels.insert(pixels.end(), bank.begin(), bank.end());
    }
    world.packed_textures.reserve(world.packed_textures.size() + directory.record_count);
    for (std::size_t index = 0; index < directory.record_count; ++index)
    {
        const auto offset = index * kPackedTextureDirectoryBytes;
        const auto bank = directory.bytes[offset];
        const auto address = read_u16(directory.bytes, offset + 1);
        const auto width = read_u16(directory.bytes, offset + 3);
        const auto height = read_u16(directory.bytes, offset + 5);
        const auto flags = directory.bytes[offset + 7];
        const auto pixel_count = static_cast<std::size_t>(width) * height;
        const auto linear = static_cast<std::size_t>(bank - first_bank) * kBrushRomBankBytes + (address - 0x8000);
        require_range(pixels, linear, pixel_count, "packed brush texture");
        MipTexture texture;
        texture.name = "packed-brush-" + std::to_string(world.packed_textures.size());
        texture.width = width;
        texture.height = height;
        texture.level_zero.assign(
            pixels.begin() + static_cast<std::ptrdiff_t>(linear),
            pixels.begin() + static_cast<std::ptrdiff_t>(linear + pixel_count)
        );
        texture.present = true;
        texture.turbulent = (flags & kPackedTextureFlagTurbulent) != 0;
        world.packed_textures.push_back(std::move(texture));
    }
}
} // namespace

namespace {
std::vector<std::uint8_t> decode_packed_brush_lightmap_samples(
    const PackedBrushSection& samples,
    std::uint16_t address,
    std::uint8_t phase,
    std::size_t sample_count
)
{
    if (address < samples.address || phase > 3)
    {
        fail("QBSA LIGHTDIR has an invalid packed sample location");
    }
    const auto byte_offset = static_cast<std::size_t>(address - samples.address);
    const auto phase_byte_offset = static_cast<std::size_t>(phase > 1 ? phase - 1 : 0);
    if (byte_offset < phase_byte_offset || (byte_offset - phase_byte_offset) % 3 != 0)
    {
        fail("QBSA LIGHTDIR packed address and phase disagree");
    }
    const auto sample_offset = (byte_offset - phase_byte_offset) / 3 * 4 + phase;
    std::vector<std::uint8_t> decoded;
    decoded.reserve(sample_count);
    for (std::size_t sample = 0; sample < sample_count; ++sample)
    {
        const auto bit_offset = (sample_offset + sample) * 6;
        const auto packed_offset = bit_offset / 8;
        require_range(samples.bytes, packed_offset, 1, "QBSA packed brush lightmap samples");
        auto word = static_cast<std::uint16_t>(samples.bytes[packed_offset]);
        if (packed_offset + 1 < samples.bytes.size())
        {
            word |= static_cast<std::uint16_t>(samples.bytes[packed_offset + 1]) << 8;
        }
        decoded.push_back(static_cast<std::uint8_t>((word >> (bit_offset & 7)) & 0x3f));
    }
    return decoded;
}

std::uint16_t append_packed_brush_lightmaps(SourceWorld& world, const PackedBrushAssets& assets)
{
    const auto& directory = packed_brush_section(assets, "LIGHTDIR");
    const auto& samples = packed_brush_section(assets, "LIGHTS");
    if (directory.record_bytes != 7 || directory.record_count != assets.faces.size() ||
        directory.bytes.size() != static_cast<std::size_t>(directory.record_count) * 7 || samples.record_bytes != 1)
    {
        fail("QBSA brush lightmap sections are inconsistent");
    }
    if (world.face_lightmaps.size() > std::numeric_limits<std::uint16_t>::max() - assets.faces.size())
    {
        fail("packed brush lightmap face namespace exceeds uint16");
    }
    const auto first = static_cast<std::uint16_t>(world.face_lightmaps.size());
    world.face_lightmaps.reserve(world.face_lightmaps.size() + assets.faces.size());
    for (std::size_t face = 0; face < assets.faces.size(); ++face)
    {
        const auto offset = face * 7;
        const auto encoded_bank = directory.bytes[offset];
        FaceLightmap lightmap;
        if (encoded_bank == 0xff)
        {
            const auto encoded_level = read_u16(directory.bytes, offset + 1);
            if (encoded_level != 0x00c0 && encoded_level != 0x00ff)
            {
                fail("QBSA LIGHTDIR has an invalid missing-sample level");
            }
            lightmap.light_offset = -1;
            lightmap.missing_level = static_cast<std::uint8_t>(encoded_level - 0x00c0);
            world.face_lightmaps.push_back(lightmap);
            continue;
        }
        const auto address = read_u16(directory.bytes, offset + 1);
        const auto width = directory.bytes[offset + 3];
        const auto height = directory.bytes[offset + 4];
        const auto phase = static_cast<std::uint8_t>(encoded_bank >> 6);
        const auto bank = static_cast<std::uint8_t>(encoded_bank & 0x3f);
        if (bank != samples.bank || address < samples.address || width == 0 || height == 0)
        {
            fail("QBSA LIGHTDIR has an invalid sample range");
        }
        const auto sample_count = static_cast<std::size_t>(width) * height;
        const auto decoded_samples = decode_packed_brush_lightmap_samples(samples, address, phase, sample_count);
        lightmap.texture_min_s = decode_i8(directory.bytes[offset + 5]) * 16;
        lightmap.texture_min_t = decode_i8(directory.bytes[offset + 6]) * 16;
        lightmap.width = width;
        lightmap.height = height;
        lightmap.light_offset = static_cast<int>(world.lighting.size());
        lightmap.styles = {0, 255, 255, 255};
        lightmap.style_count = 1;
        lightmap.precombined_compact_levels = true;
        for (const auto level : decoded_samples)
        {
            if (level == 0 || level > 63)
            {
                fail("QBSA brush lightmap level escapes 1..63");
            }
            world.lighting.push_back(level);
        }
        world.face_lightmaps.push_back(lightmap);
    }
    return first;
}
} // namespace

namespace {
std::int16_t packed_brush_coordinate(
    const SourceWorld& world,
    const PackedBrushVariant& variant,
    const PackedVertex& vertex,
    std::int8_t axis_code,
    std::int16_t offset
)
{
    if (axis_code == 0 || std::abs(static_cast<int>(axis_code)) > 3)
    {
        fail("QBSF face has an invalid signed unit texture axis");
    }
    const auto axis = static_cast<std::size_t>(std::abs(static_cast<int>(axis_code)) - 1);
    const std::array<int, 3> packed{vertex.x, vertex.y, vertex.z};
    const std::array<int, 3> origin_q3{variant.origin_x_q3, variant.origin_y_q3, variant.origin_z_q3};
    const std::array<double, 3> world_origin{world.origin.x, world.origin.y, world.origin.z};
    const auto rounded_world_origin = static_cast<int>(std::lround(world_origin[axis]));
    if (world_origin[axis] != rounded_world_origin)
    {
        fail("packed brush texture coordinates require integer world origin");
    }
    int value = packed[axis] * 64 + rounded_world_origin * 16 - origin_q3[axis] * 2;
    if (axis_code < 0)
    {
        value = -value;
    }
    return wrap_i16(value + offset * 16);
}
} // namespace

namespace {
std::uint8_t
packed_brush_texture_id(const PackedBrushVisualState& visual, const PackedBrushLink& link, const PackedBrushFace& face)
{
    auto texture = static_cast<std::uint8_t>(face.base_texture);
    for (const auto& override_record : visual.textures)
    {
        if (override_record[0] == link.slot && override_record[1] == face.local_face)
        {
            texture = override_record[2];
            break;
        }
    }
    return texture;
}
} // namespace

namespace {
bool packed_brush_face_is_visible(
    const PackedBrushAssets& assets,
    const PackedBrushVariant& variant,
    const PackedBrushFace& face,
    const Camera& camera
)
{
    const auto& plane = assets.face_planes.at(face.packed_face);
    const std::array<double, 3> local_camera_q2{
        camera.x * 4.0 - variant.origin_x_q3 / 32.0,
        camera.y * 4.0 - variant.origin_y_q3 / 32.0,
        camera.z * 4.0 - variant.origin_z_q3 / 32.0,
    };
    const double value =
        plane.x * local_camera_q2[0] + plane.y * local_camera_q2[1] + plane.z * local_camera_q2[2] - plane.distance;
    return value < 0.0;
}
} // namespace

namespace {
PackedTextureRaster make_packed_brush_raster()
{
    PackedTextureRaster result;
    result.indices.assign(kLogicalPixels, kUnwrittenIndex);
    result.lightmapped_indices.assign(kLogicalPixels, kUnwrittenIndex);
    result.lightmap_levels.resize(kLogicalPixels);
    result.untextured_lightmap_indices.assign(kLogicalPixels, kUntexturedDiagnosticIndex);
    result.faces.resize(kLogicalPixels, kMissFace);
    result.entities.resize(kLogicalPixels);
    result.models.resize(kLogicalPixels);
    result.s_q4.resize(kLogicalPixels);
    result.t_q4.resize(kLogicalPixels);
    result.absolute_s_q4.resize(kLogicalPixels);
    result.absolute_t_q4.resize(kLogicalPixels);
    result.depth_q6.assign(kLogicalPixels, std::numeric_limits<std::int16_t>::max());
    result.turbulent_pixels.resize(kLogicalPixels);
    result.arbitration_groups.resize(kLogicalPixels, 0xffff);
    result.arbitration_depth_q6.resize(kLogicalPixels);
    return result;
}
} // namespace

namespace {
void raster_packed_brush_world_face(
    PackedTextureRaster& result,
    const SourceWorld& world,
    const Camera& camera,
    std::uint16_t face,
    TextureRasterMode mode
)
{
    const auto& vertex_ids = world.face_vertex_ids.at(face);
    const auto& coordinates = world.face_texture_coordinates.at(face);
    if (vertex_ids.size() < 3 || vertex_ids.size() != coordinates.size())
    {
        fail("mixed brush stream has an invalid world polygon");
    }
    const auto texture_id = world.face_texture_ids.at(face);
    if (texture_id == 0xff)
    {
        return;
    }
    result.current_depth_arbitration = false;
    result.current_source_face = face;
    result.current_entity = 0;
    result.current_model = 0;
    std::vector<TexturedViewVertex> polygon;
    polygon.reserve(vertex_ids.size());
    for (std::size_t index = 0; index < vertex_ids.size(); ++index)
    {
        polygon.push_back(
            {transform_packed_vertex(world, world.packed_vertices.at(vertex_ids[index]), camera),
             coordinates[index].s_q4,
             coordinates[index].t_q4}
        );
    }
    ++result.stats.input_faces;
    raster_packed_texture_polygon(result, world, polygon, world.packed_textures.at(texture_id), face, mode);
}
} // namespace

namespace {
void raster_packed_brush_fragment(
    PackedTextureRaster& result,
    const SourceWorld& world,
    const Camera& camera,
    const PackedBrushAssets& assets,
    const PackedBrushVisualState& visual,
    std::uint16_t lightmap_face_base,
    std::uint8_t slot,
    std::uint16_t geometry,
    std::uint16_t fragment_index,
    TextureRasterMode mode
)
{
    if (slot >= assets.entities.size() || geometry >= assets.variants.size() ||
        fragment_index >= assets.fragments.size())
    {
        fail("mixed brush candidate escapes its packed directories");
    }
    const auto& fragment = assets.fragments[fragment_index];
    const auto& face = assets.faces.at(fragment.packed_face);
    const auto& variant = assets.variants[geometry];
    if (!packed_brush_face_is_visible(assets, variant, face, camera))
    {
        return;
    }
    const PackedBrushLink material_link{fragment_index, 0, slot};
    const auto texture_id = packed_brush_texture_id(visual, material_link, face);
    result.current_source_face = face.source_face;
    result.current_entity = assets.entities[slot].entity;
    result.current_model = face.inline_model;
    if (fragment.vertex_count < 3 || fragment.first_vertex > assets.vertices.size() ||
        fragment.vertex_count > assets.vertices.size() - fragment.first_vertex)
    {
        fail("mixed brush candidate has an invalid QBSF polygon");
    }
    std::vector<TexturedViewVertex> polygon;
    polygon.reserve(fragment.vertex_count);
    for (std::size_t index = fragment.first_vertex;
         index < static_cast<std::size_t>(fragment.first_vertex) + fragment.vertex_count;
         ++index)
    {
        const auto& vertex = assets.vertices[index];
        polygon.push_back(
            {transform_packed_vertex(world, vertex, camera),
             packed_brush_coordinate(world, variant, vertex, face.s_axis, face.s_offset),
             packed_brush_coordinate(world, variant, vertex, face.t_axis, face.t_offset)}
        );
    }
    ++result.current_candidate_serial;
    ++result.stats.input_faces;
    raster_packed_texture_polygon(
        result,
        world,
        polygon,
        world.packed_textures.at(texture_id),
        static_cast<std::uint16_t>(lightmap_face_base + fragment.packed_face),
        mode
    );
}
} // namespace

namespace {
PackedTextureRaster finish_packed_brush_raster(PackedTextureRaster result)
{
    std::set<std::uint16_t> unique_faces;
    for (const auto face : result.faces)
    {
        if (face == kMissFace)
        {
            ++result.misses;
        }
        else
        {
            ++result.hits;
            unique_faces.insert(face);
        }
    }
    result.unique_faces = static_cast<int>(unique_faces.size());
    result.stats.unique_samples = result.hits;
    result.stats.unwritten_samples = result.misses;
    return result;
}
} // namespace

PackedBrushGroupBounds packed_brush_group_bounds(const PackedTextureRaster& raster)
{
    std::set<std::uint16_t> groups;
    for (const auto& fragment : raster.projected_fragments)
    {
        groups.insert(fragment.arbitration_group);
    }
    for (const auto& span : raster.spans)
    {
        if (span.arbitration_group != 0xffff)
        {
            groups.insert(span.arbitration_group);
        }
    }

    PackedBrushGroupBounds bounds;
    bounds.groups = static_cast<int>(groups.size());
    for (const auto group : groups)
    {
        int admitted = 0;
        int projected_vertices = 0;
        for (const auto& fragment : raster.projected_fragments)
        {
            if (fragment.arbitration_group == group)
            {
                ++admitted;
                projected_vertices += fragment.projected_vertices;
            }
        }
        if (admitted > bounds.max_admitted_fragments)
        {
            bounds.max_admitted_fragments = admitted;
            bounds.admitted_group = group;
        }
        if (projected_vertices > bounds.max_projected_vertices)
        {
            bounds.max_projected_vertices = projected_vertices;
            bounds.projected_group = group;
        }

        std::array<std::set<std::uint32_t>, kLogicalHeight> row_candidates;
        std::array<bool, kLogicalHeight> scan_rows{};
        std::vector<int> pixel_candidates(kLogicalPixels);
        int span_count = 0;
        int group_max_pixel_candidates = 0;
        for (const auto& span : raster.spans)
        {
            if (span.arbitration_group != group)
            {
                continue;
            }
            if (span.y < 0 || span.y >= kLogicalHeight || span.first_x < 0 || span.last_x >= kLogicalWidth ||
                span.first_x > span.last_x)
            {
                fail("packed brush span escapes the logical viewport");
            }
            ++span_count;
            scan_rows[static_cast<std::size_t>(span.y)] = true;
            row_candidates[static_cast<std::size_t>(span.y)].insert(span.candidate_serial);
            for (int x = span.first_x; x <= span.last_x; ++x)
            {
                const auto pixel = logical_pixel_index(x, span.y);
                const int candidates = ++pixel_candidates[pixel];
                group_max_pixel_candidates = std::max(group_max_pixel_candidates, candidates);
                if (candidates > bounds.max_pixel_candidates)
                {
                    bounds.max_pixel_candidates = candidates;
                    bounds.pixel_group = group;
                    bounds.pixel = static_cast<int>(pixel);
                }
            }
        }
        const int rows = static_cast<int>(std::ranges::count(scan_rows, true));
        if (rows > bounds.max_scan_rows)
        {
            bounds.max_scan_rows = rows;
            bounds.scan_rows_group = group;
        }
        int group_max_row_candidates = 0;
        for (int y = 0; y < kLogicalHeight; ++y)
        {
            const int candidates = static_cast<int>(row_candidates[static_cast<std::size_t>(y)].size());
            group_max_row_candidates = std::max(group_max_row_candidates, candidates);
            if (candidates > bounds.max_row_candidates)
            {
                bounds.max_row_candidates = candidates;
                bounds.row_group = group;
                bounds.row = y;
            }
        }
        bounds.records.push_back(
            {group,
             admitted,
             projected_vertices,
             rows,
             span_count,
             group_max_row_candidates,
             group_max_pixel_candidates}
        );
    }
    return bounds;
}

namespace {
bool directed_graph_has_cycle(const std::vector<std::vector<bool>>& edges)
{
    std::vector<int> indegree(edges.size());
    for (std::size_t from = 0; from < edges.size(); ++from)
    {
        for (std::size_t to = 0; to < edges.size(); ++to)
        {
            indegree[to] += edges[from][to];
        }
    }
    std::vector<std::size_t> ready;
    for (std::size_t node = 0; node < indegree.size(); ++node)
    {
        if (indegree[node] == 0)
        {
            ready.push_back(node);
        }
    }
    std::size_t visited = 0;
    while (!ready.empty())
    {
        const auto from = ready.back();
        ready.pop_back();
        ++visited;
        for (std::size_t to = 0; to < edges.size(); ++to)
        {
            if (edges[from][to] && --indegree[to] == 0)
            {
                ready.push_back(to);
            }
        }
    }
    return visited != edges.size();
}
} // namespace

PackedBrushOrderingAnalysis
packed_brush_ordering_analysis(const PackedTextureRaster& raster, const PackedBrushGroupBounds& bounds)
{
    PackedBrushOrderingAnalysis analysis;
    analysis.groups = static_cast<int>(bounds.records.size());
    for (const auto& group : bounds.records)
    {
        std::vector<PackedBrushProjectedFragment> fragments;
        for (const auto& fragment : raster.projected_fragments)
        {
            if (fragment.arbitration_group == group.leaf)
            {
                fragments.push_back(fragment);
            }
        }
        std::vector<PackedBrushCandidateSample> samples;
        for (const auto& sample : raster.candidate_samples)
        {
            if (sample.arbitration_group == group.leaf)
            {
                samples.push_back(sample);
            }
        }
        std::ranges::sort(samples, {}, [](const PackedBrushCandidateSample& sample) {
            return std::pair{sample.pixel, sample.candidate_serial};
        });
        const auto fragment_index = [&](std::uint32_t serial) {
            const auto found = std::ranges::find(fragments, serial, &PackedBrushProjectedFragment::candidate_serial);
            if (found == fragments.end())
            {
                fail("packed brush sample has no projected fragment");
            }
            return static_cast<std::size_t>(std::distance(fragments.begin(), found));
        };
        const auto nearer = [&](const PackedBrushCandidateSample& left, const PackedBrushCandidateSample& right) {
            if (left.depth_q6 != right.depth_q6)
            {
                return left.depth_q6 < right.depth_q6;
            }
            const auto& left_fragment = fragments[fragment_index(left.candidate_serial)];
            const auto& right_fragment = fragments[fragment_index(right.candidate_serial)];
            return std::tuple{
                       left_fragment.entity,
                       left_fragment.model,
                       left_fragment.source_face,
                       left_fragment.candidate_serial
                   } <
                   std::tuple{
                       right_fragment.entity,
                       right_fragment.model,
                       right_fragment.source_face,
                       right_fragment.candidate_serial
                   };
        };

        std::vector<std::vector<bool>> winner_edges(fragments.size(), std::vector<bool>(fragments.size()));
        std::vector<std::vector<bool>> pairwise_edges(fragments.size(), std::vector<bool>(fragments.size()));
        std::vector<std::size_t> centroid_order(fragments.size());
        std::iota(centroid_order.begin(), centroid_order.end(), 0);
        std::ranges::sort(centroid_order, [&](std::size_t left, std::size_t right) {
            const auto& a = fragments[left];
            const auto& b = fragments[right];
            return std::tuple{a.centroid_depth_q6, a.entity, a.model, a.source_face, a.candidate_serial} >
                   std::tuple{b.centroid_depth_q6, b.entity, b.model, b.source_face, b.candidate_serial};
        });
        std::vector<std::size_t> centroid_rank(fragments.size());
        for (std::size_t rank = 0; rank < centroid_order.size(); ++rank)
        {
            centroid_rank[centroid_order[rank]] = rank;
        }

        int overlap_pixels = 0;
        int centroid_mismatches = 0;
        std::size_t first = 0;
        while (first < samples.size())
        {
            std::size_t end = first + 1;
            while (end < samples.size() && samples[end].pixel == samples[first].pixel)
            {
                if (samples[end].candidate_serial == samples[end - 1].candidate_serial)
                {
                    fail("brush fragment emitted a duplicate pixel sample");
                }
                ++end;
            }
            if (end - first > 1)
            {
                ++overlap_pixels;
            }
            std::size_t winner = first;
            std::size_t centroid_winner = fragment_index(samples[first].candidate_serial);
            for (std::size_t index = first + 1; index < end; ++index)
            {
                if (nearer(samples[index], samples[winner]))
                {
                    winner = index;
                }
                const auto candidate = fragment_index(samples[index].candidate_serial);
                if (centroid_rank[candidate] > centroid_rank[centroid_winner])
                {
                    centroid_winner = candidate;
                }
            }
            const auto winner_fragment = fragment_index(samples[winner].candidate_serial);
            centroid_mismatches += centroid_winner != winner_fragment;
            for (std::size_t index = first; index < end; ++index)
            {
                const auto candidate = fragment_index(samples[index].candidate_serial);
                if (candidate != winner_fragment)
                {
                    winner_edges[candidate][winner_fragment] = true;
                }
                for (std::size_t other = index + 1; other < end; ++other)
                {
                    const auto other_candidate = fragment_index(samples[other].candidate_serial);
                    if (nearer(samples[index], samples[other]))
                    {
                        pairwise_edges[other_candidate][candidate] = true;
                    }
                    else
                    {
                        pairwise_edges[candidate][other_candidate] = true;
                    }
                }
            }
            first = end;
        }
        const bool winner_cycle = directed_graph_has_cycle(winner_edges);
        const bool pairwise_cycle = directed_graph_has_cycle(pairwise_edges);
        analysis.overlap_groups += overlap_pixels != 0;
        analysis.winner_cycle_groups += winner_cycle;
        analysis.pairwise_cycle_groups += pairwise_cycle;
        analysis.centroid_mismatch_groups += centroid_mismatches != 0;
        analysis.centroid_mismatch_pixels += centroid_mismatches;
        analysis.records.push_back({group.leaf, overlap_pixels, winner_cycle, pairwise_cycle, centroid_mismatches});
    }
    return analysis;
}

PackedTextureRaster render_packed_brush_pipeline(
    SourceWorld world,
    const PacketSelection& packet,
    const Camera& camera,
    std::uint16_t visual_state,
    const fs::path& data_dir,
    PackedBrushAssets assets,
    TextureRasterMode mode,
    double surface_time,
    bool external_bsp_enabled,
    std::optional<std::size_t> fly_source_pose,
    bool fly_static_brushes
)
{
    auto visual = decode_packed_brush_visual_state(assets, visual_state);
    std::vector<PackedBrushActiveGeometry> fly_geometry;
    if (fly_source_pose.has_value())
    {
        if (fly_static_brushes)
        {
            std::erase_if(visual.transforms, [&](const auto& transform) {
                return transform.first >= assets.external_entity_slot_first;
            });
            fly_geometry.reserve(assets.static_variants.size() + assets.external_static_variants.size());
            for (const auto& record : assets.static_variants)
            {
                if (assets.entities.size() >= 256)
                {
                    fail("QBSA fly static slots exceed uint8 capacity");
                }
                const auto slot = static_cast<std::uint8_t>(assets.entities.size());
                const auto inline_model = assets.variants.at(record.geometry_variant).inline_model;
                assets.entities.push_back({record.entity, inline_model, 0, 0});
                fly_geometry.push_back({slot, record.geometry_variant});
            }
            if (external_bsp_enabled)
            {
                for (const auto& record : assets.external_static_variants)
                {
                    if (record.slot < assets.entities.size())
                    {
                        continue;
                    }
                    if (record.slot != assets.entities.size() || assets.entities.size() >= 256)
                    {
                        fail("QBSA fly external slots are not contiguous");
                    }
                    const auto inline_model = assets.variants.at(record.geometry_variant).inline_model;
                    assets.entities.push_back({record.entity, inline_model, 0, 0});
                }
                for (std::size_t index = 0; index < assets.external_static_variants.size(); ++index)
                {
                    if (!packed_external_static_active(assets, *fly_source_pose, index))
                    {
                        continue;
                    }
                    const auto& record = assets.external_static_variants[index];
                    fly_geometry.push_back({record.slot, record.geometry_variant});
                }
            }
        }
        else
        {
            std::erase_if(visual.transforms, [&](const auto& transform) {
                return transform.first < assets.external_entity_slot_first;
            });
            std::erase_if(visual.textures, [&](const auto& texture) {
                return texture[0] < assets.external_entity_slot_first;
            });
        }
    }
    if (!external_bsp_enabled)
    {
        std::erase_if(visual.transforms, [&](const auto& transform) {
            return transform.first >= assets.external_entity_slot_first;
        });
        std::erase_if(visual.textures, [&](const auto& texture) {
            return texture[0] >= assets.external_entity_slot_first;
        });
    }
    append_packed_brush_textures(world, assets, data_dir);
    const auto lightmap_face_base = append_packed_brush_lightmaps(world, assets);
    build_packed_brush_tokens(assets, packet, camera, visual, data_dir, fly_geometry);

    auto result = make_packed_brush_raster();
    result.turbulence_phase = quake_turbulence_phase(surface_time);
    bool brush_group_active = false;
    for (const auto& token : assets.tokens)
    {
        if (token.kind == PackedBrushTokenKind::leaf_marker)
        {
            result.current_arbitration_group = token.value;
            result.current_depth_arbitration = true;
            brush_group_active = true;
        }
        else if (token.kind == PackedBrushTokenKind::world)
        {
            brush_group_active = false;
            raster_packed_brush_world_face(result, world, camera, token.value, mode);
        }
        else
        {
            if (!brush_group_active || !result.current_depth_arbitration)
            {
                fail("brush token is not preceded by its leaf marker");
            }
            const auto& link = assets.links.at(token.value);
            if (link.slot >= assets.active_geometry_by_slot.size())
            {
                fail("brush token names an invalid entity slot");
            }
            const auto geometry = assets.active_geometry_by_slot[link.slot];
            if (geometry == 0xffff)
            {
                fail("brush token names an inactive geometry slot");
            }
            raster_packed_brush_fragment(
                result,
                world,
                camera,
                assets,
                visual,
                lightmap_face_base,
                link.slot,
                geometry,
                link.fragment,
                mode
            );
        }
    }
    auto finished = finish_packed_brush_raster(std::move(result));
    if (mode == TextureRasterMode::projective_block8)
    {
    }
    return finished;
}

PackedTextureRaster render_direct_qbsf_brush_authority(
    SourceWorld world,
    const PacketSelection& packet,
    const Camera& camera,
    std::uint16_t visual_state,
    const fs::path& data_dir,
    const PackedBrushAssets& assets
)
{
    const auto visual = decode_packed_brush_visual_state(assets, visual_state);
    append_packed_brush_textures(world, assets, data_dir);
    const auto lightmap_face_base = append_packed_brush_lightmaps(world, assets);
    const auto& variant_map = packed_brush_section(assets, "VFRAG");
    std::vector<std::vector<PackedBrushDirectFragment>> leaves(assets.leaf_count);
    for (const auto& [slot, local_variant] : visual.transforms)
    {
        if (slot >= assets.entities.size())
        {
            fail("direct QBSF transform names an invalid entity slot");
        }
        const auto& entity = assets.entities[slot];
        if (local_variant >= entity.variant_count)
        {
            fail("direct QBSF transform names an invalid local variant");
        }
        const auto mapped = static_cast<std::size_t>(entity.first_variant + local_variant);
        require_range(variant_map.bytes, mapped * 2, 2, "direct QBSF VFRAG");
        const auto geometry = read_u16(variant_map.bytes, mapped * 2);
        const auto& variant = assets.variants.at(geometry);
        for (std::size_t bucket_index = variant.first_bucket;
             bucket_index < static_cast<std::size_t>(variant.first_bucket) + variant.bucket_count;
             ++bucket_index)
        {
            const auto& bucket = assets.buckets.at(bucket_index);
            if (bucket.leaf >= leaves.size())
            {
                fail("direct QBSF bucket names an invalid leaf");
            }
            if (bucket.solid)
            {
                continue;
            }
            for (std::size_t fragment = bucket.first_fragment;
                 fragment < static_cast<std::size_t>(bucket.first_fragment) + bucket.fragment_count;
                 ++fragment)
            {
                if (fragment >= assets.fragments.size())
                {
                    fail("direct QBSF fragment range escapes its directory");
                }
                leaves[bucket.leaf].push_back({geometry, static_cast<std::uint16_t>(fragment), slot});
            }
        }
    }

    const auto nodes = read_file(data_dir / "QuakeBSPWorldNodes.bin");
    const auto planes = read_file(data_dir / "QuakeBSPWorldPlanes.bin");
    if (nodes.empty() || nodes.size() % 10 != 0 || planes.empty() || planes.size() % 5 != 0)
    {
        fail("direct QBSF traversal assets have invalid record sizes");
    }
    auto result = make_packed_brush_raster();
    struct StackItem
    {
        std::int16_t node{};
        bool emit{};
    };
    std::vector<StackItem> stack{{0, false}};
    while (!stack.empty())
    {
        const auto item = stack.back();
        stack.pop_back();
        if (item.node < 0)
        {
            const auto leaf = static_cast<std::uint16_t>(~item.node);
            if (leaf >= leaves.size())
            {
                fail("direct QBSF traversal names an invalid leaf");
            }
            result.current_arbitration_group = leaf;
            result.current_depth_arbitration = true;
            for (const auto& candidate : leaves[leaf])
            {
                raster_packed_brush_fragment(
                    result,
                    world,
                    camera,
                    assets,
                    visual,
                    lightmap_face_base,
                    candidate.slot,
                    candidate.geometry,
                    candidate.fragment,
                    TextureRasterMode::projective_block8
                );
            }
            continue;
        }
        const auto node = static_cast<std::size_t>(item.node);
        require_range(nodes, node * 10, 10, "direct QBSF world node");
        const auto offset = node * 10;
        if (item.emit)
        {
            const auto first_face = read_u16(nodes, offset + 6);
            const auto face_count = read_u16(nodes, offset + 8);
            for (std::size_t face = first_face; face < static_cast<std::size_t>(first_face) + face_count; ++face)
            {
                if (face < packet.selected_faces.size() && packet.selected_faces[face] != 0)
                {
                    raster_packed_brush_world_face(
                        result,
                        world,
                        camera,
                        static_cast<std::uint16_t>(face),
                        TextureRasterMode::projective_block8
                    );
                }
            }
            continue;
        }
        const auto plane = read_u16(nodes, offset);
        require_range(planes, static_cast<std::size_t>(plane) * 5, 5, "direct QBSF world plane");
        const auto plane_offset = static_cast<std::size_t>(plane) * 5;
        const int distance =
            camera.x * decode_i8(planes[plane_offset]) + camera.y * decode_i8(planes[plane_offset + 1]) +
            camera.z * decode_i8(planes[plane_offset + 2]) - read_i16(planes, plane_offset + 3);
        const auto front = read_i16(nodes, offset + 2);
        const auto back = read_i16(nodes, offset + 4);
        const auto near_child = distance < 0 ? back : front;
        const auto far_child = distance < 0 ? front : back;
        stack.push_back({near_child, false});
        stack.push_back({item.node, true});
        stack.push_back({far_child, false});
    }
    auto finished = finish_packed_brush_raster(std::move(result));
    return finished;
}

} // namespace quake_bsp_reference
