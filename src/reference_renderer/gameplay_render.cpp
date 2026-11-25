#include "gameplay_render.hpp"
#include "gameplay_intermission.hpp"
#include "aliases.hpp"
#include "packed_brushes.hpp"
#include "sky.hpp"
#include "textured_live.hpp"
#include "turbulence.hpp"
#include "x2_weapon.hpp"
#include "gameplay_x3_view.hpp"

namespace quake_bsp_reference {
namespace {
std::vector<std::uint8_t> pickup_font(std::span<const std::uint8_t> pak)
{
    const auto wad = extract_pak_entry(pak, "gfx.wad");
    const auto count = read_u32(wad, 4);
    const std::size_t directory = read_u32(wad, 8);
    if (directory > wad.size() || count > (wad.size() - directory) / 32)
        fail("invalid console WAD directory");
    for (std::uint32_t i = 0; i < count; ++i)
    {
        const auto entry = directory + i * 32;
        const std::string_view name(reinterpret_cast<const char*>(wad.data() + entry + 16), 8);
        if (name != "conchars" && name != "CONCHARS")
            continue;
        const std::size_t offset = read_u32(wad, entry);
        if (offset > wad.size() || wad.size() - offset < 16384 || read_u32(wad, entry + 4) != 16384 ||
            read_u32(wad, entry + 8) != 16384 || wad[entry + 13])
            fail("invalid console font dimensions");
        return {wad.begin() + offset, wad.begin() + offset + 16384};
    }
    fail("missing console font");
}

std::vector<std::uint8_t> pickup_text(const std::array<std::string_view, 4>& lines,
                                      std::span<const std::uint8_t> font)
{
    if (lines.front().empty())
        return {};
    std::vector<std::uint8_t> bits(32 * 32);
    for (std::size_t row = 0; row < lines.size(); ++row)
        for (std::size_t col = 0; col < lines[row].size(); ++col)
        {
            const auto ch = static_cast<unsigned char>(lines[row][col]);
            const auto origin = (ch / 16) * 1024 + (ch % 16) * 8;
            for (int y = 0; y < 8; ++y)
                for (int x = 0; x < 8; ++x)
                    if (font[origin + 128 * y + x])
                        bits[(8 * row + y) * 32 + col + 1] |= std::uint8_t(0x80U >> x);
        }
    return bits;
}

std::uint16_t pickup_color(std::uint16_t word, std::uint8_t index, const GameplayRenderSnapshot& snapshot)
{
    const int bonus = 50 * snapshot.pickup_bonus_ticks / 30;
    const bool immersed = snapshot.eye_contents == -3 || snapshot.eye_contents == -4;
    const int power = !immersed && (snapshot.damage_tint || snapshot.muzzle_tint) ? 0 :
                      snapshot.quad_tint ? 30 : snapshot.suit_tint ? 20 : 0;
    constexpr std::array<int, 3> water{130, 80, 50}, slime{0, 25, 5};
    constexpr std::array<int, 3> gold{215, 186, 69};
    std::uint16_t out = 0;
    for (int i = 0; i < 3; ++i)
    {
        int source = ((word >> (5 * i)) & 31) * 8;
        if (immersed)
        {
            const bool in_slime = snapshot.eye_contents == -4;
            const int destination = in_slime ? slime[i] : water[i];
            source += ((destination - source) * (in_slime ? 150 : 128)) >> 8;
        }
        if ((immersed || index) && snapshot.damage_tint && i == 0)
            source = std::min(248, source + 80);
        else if ((immersed || index) && !snapshot.damage_tint && snapshot.muzzle_tint)
            source = std::min(248, source + (i == 0 ? 64 : i == 1 ? 32 : 0));
        const int flash = source + (((gold[i] - source) * bonus) >> 8);
        const int target = ((snapshot.quad_tint && i == 2) || (!snapshot.quad_tint && i == 1)) ? 255 : 0;
        const int result = flash + (((target - flash) * power) >> 8);
        out |= std::uint16_t((result / 8) << (5 * i));
    }
    return out;
}

fs::path render_path(const GameplayAssets& assets, const char* key)
{
    const auto value = assets.manifest.at(key).get<std::string>();
    fs::path path(value);
    if (path.is_relative())
    {
        const auto base = assets.manifest.value("assetDirectory", "");
        const auto manifest = assets.manifest.value("manifestPath", "");
        if (base.empty() && manifest.empty())
            fail("relative gameplay rendering path has no manifest directory");
        path = (base.empty() ? fs::path(manifest).parent_path() : fs::path(base)) / path;
    }
    return fs::weakly_canonical(path);
}

fs::path billboard_path(const GameplayAssets& assets)
{
    if (!assets.manifest.contains("referenceData") || !assets.manifest.at("referenceData").is_string() ||
        assets.manifest.at("referenceData").get<std::string>().empty())
        fail("gameplay requires the production SNES billboard bundle; re-export gameplay assets");
    if (assets.manifest.at("referenceData") != "." || !assets.manifest.contains("billboards") ||
        assets.manifest.at("billboards").value("schema", "") != "quake-gameplay-production-billboards-v1")
        fail("gameplay requires a portable production SNES billboard binding");
    const auto found = assets.payloads.find("QuakeBSPAliasAssets.json");
    if (found == assets.payloads.end())
        fail("gameplay billboard metadata is not in the declared payload closure");
    const auto metadata = Json::parse(found->second.begin(), found->second.end());
    if (metadata.value("schema", "") != "quake-level-alias-assets-v1")
        fail("gameplay requires the production level billboard schema");
    for (const auto& item : metadata.at("outputs").items())
        if (!assets.payloads.contains(item.key()))
            fail("gameplay billboard chunk is not in the declared payload closure");
    const auto& packed = assets.manifest.at("billboards").at("packedWorld");
    if (packed.value("schema", "") != "quake-gameplay-production-world-v1" || packed.at("files").empty())
        fail("gameplay requires the complete production packed world and brushes");
    for (const auto& filename : packed.at("files"))
        if (!assets.payloads.contains(filename.get<std::string>()))
            fail("gameplay packed world/brush file is not in the declared payload closure");
    return render_path(assets, "referenceData");
}

std::size_t gameplay_sprite_base(const AliasAssets& assets, std::string_view model, unsigned frame, bool single_view)
{
    for (std::size_t base = 0; base < assets.sprites.size(); ++base)
    {
        const auto& first = assets.sprites[base];
        if (assets.model_names.at(first.model) != model || first.frame != frame || first.view != 0)
            continue;
        if (single_view)
            return base;
        if (base >= kAliasDirectionalTag || base + kAliasFlyRowCount > assets.sprites.size())
            fail("gameplay billboard frame has no complete eight-view range");
        for (std::size_t view = 0; view < kAliasFlyRowCount; ++view)
        {
            const auto& sprite = assets.sprites[base + view];
            if (sprite.model != first.model || sprite.frame != first.frame || sprite.view != view)
                fail("gameplay billboard frame views are not contiguous and exact");
        }
        return base;
    }
    fail("gameplay billboard frame is unavailable: " + std::string(model) + " frame " + std::to_string(frame));
}

// Same independent all-world front/guard policy as AllFrontWorld in
// fly_search/reference_world.py: no native packets, PVS or capacity limits.
PacketSelection gameplay_world_packet(
    const SourceWorld& world,
    const Camera& camera,
    std::span<const std::uint8_t> nodes,
    std::span<const std::uint8_t> planes
)
{
    if (nodes.empty() || nodes.size() % 10 || planes.empty() || planes.size() % 5)
        fail("gameplay packed BSP traversal streams are invalid");
    PacketSelection packet;
    packet.selected_faces.resize(static_cast<std::size_t>(world.face_count));
    packet.painter_ranks.resize(static_cast<std::size_t>(world.face_count), -1);
    const auto position = camera.position_q2();
    for (std::size_t face = 0; face < packet.selected_faces.size(); ++face)
    {
        const auto& p = world.packed_visibility_planes.at(face);
        const auto distance = std::bit_cast<std::int16_t>(
            static_cast<std::uint16_t>(position[0] * p.x + position[1] * p.y + position[2] * p.z - p.distance)
        );
        packet.selected_faces[face] = static_cast<std::uint8_t>(
            world.drawable_face_mask.at(face) && (world.plane_cull_guard_mask.at(face) || distance <= 0)
        );
    }
    struct Visit
    {
        std::int16_t node;
        bool emit;
    };
    std::vector<Visit> stack{{0, false}};
    std::vector<std::uint8_t> visited(nodes.size() / 10);
    while (!stack.empty())
    {
        const auto item = stack.back();
        stack.pop_back();
        if (item.node < 0)
            continue;
        const auto node = static_cast<std::size_t>(item.node);
        if (node >= visited.size())
            fail("gameplay packed painter names an invalid node");
        const auto offset = node * 10;
        if (item.emit)
        {
            if (visited[node] != 1)
                fail("gameplay packed painter revisits a node");
            visited[node] = 2;
            const auto first = read_u16(nodes, offset + 6);
            const auto count = read_u16(nodes, offset + 8);
            if (static_cast<std::size_t>(first) + count > packet.selected_faces.size())
                fail("gameplay packed node escapes world faces");
            for (std::size_t face = first; face < static_cast<std::size_t>(first) + count; ++face)
                if (packet.selected_faces[face])
                {
                    if (packet.painter_ranks[face] >= 0)
                        fail("gameplay packed painter emits a face twice");
                    packet.painter_ranks[face] = static_cast<int>(packet.source_faces.size());
                    packet.source_faces.push_back(static_cast<std::uint16_t>(face));
                }
            continue;
        }
        if (visited[node])
            fail("gameplay packed painter contains a repeated node");
        visited[node] = 1;
        const auto plane = static_cast<std::size_t>(read_u16(nodes, offset)) * 5;
        if (plane + 5 > planes.size())
            fail("gameplay packed node names an invalid plane");
        const std::array normal{decode_i8(planes[plane]), decode_i8(planes[plane + 1]), decode_i8(planes[plane + 2])};
        const auto coarse = std::bit_cast<std::int16_t>(static_cast<std::uint16_t>(
            camera.x * normal[0] + camera.y * normal[1] + camera.z * normal[2] - read_i16(planes, plane + 3)
        ));
        const int distance = 4 * coarse + camera.residual_q2[0] * normal[0] +
            camera.residual_q2[1] * normal[1] + camera.residual_q2[2] * normal[2];
        const auto front = read_i16(nodes, offset + 2);
        const auto back = read_i16(nodes, offset + 4);
        stack.push_back({distance < 0 ? back : front, false});
        stack.push_back({item.node, true});
        stack.push_back({distance < 0 ? front : back, false});
    }
    for (std::size_t face = 0; face < packet.selected_faces.size(); ++face)
        if (packet.selected_faces[face] && packet.painter_ranks[face] < 0)
            fail("gameplay packed painter did not emit a selected face");
    return packet;
}

template <typename T> void mirror_x(std::vector<T>& plane)
{
    if (plane.size() != kLogicalPixels)
        fail("gameplay native billboard composition requires a 128x112 plane");
    for (std::size_t y = 0; y < kLogicalHeight; ++y)
        for (std::size_t x = 0; x < kLogicalWidth / 2; ++x)
            std::swap(plane[y * kLogicalWidth + x], plane[(y + 1) * kLogicalWidth - 1 - x]);
}

} // namespace

std::vector<std::int16_t> gameplay_packed_opaque_depth(std::span<const double> source, const ViewTransform& view)
{
    if (source.size() != kLogicalPixels)
        fail("gameplay native depth conversion requires a 128x112 plane");
    // The raycaster stores its unnormalized ray parameter t. Native aliases
    // compare forward-axis Q6 distance, so preserve the Q6 basis norm and
    // its small forward/up nonorthogonality instead of assuming t is Z.
    constexpr auto missing = std::numeric_limits<std::int16_t>::max();
    std::vector<std::int16_t> result;
    result.reserve(source.size());
    for (int y = 0; y < kLogicalHeight; ++y)
        for (int x = 0; x < kLogicalWidth; ++x)
        {
            const auto ray = view_ray(view, x, y);
            const auto scaled =
                source[logical_pixel_index(x, y)] * dot(ray.direction, view.forward) * 64.0 / kWorldScale;
            result.push_back(
                !std::isfinite(scaled) || scaled >= missing ? missing
                : scaled <= 0                               ? std::int16_t{0}
                                                            : static_cast<std::int16_t>(std::lround(scaled))
            );
        }
    return result;
}

class GameplayRenderer::Impl
{
    struct Map
    {
        BspData bsp;
        fs::path data_dir;
        SourceWorld world;
        PackedBrushAssets brushes;
        std::vector<std::uint8_t> nodes, planes;
        std::vector<std::uint8_t> face_colors;
        std::vector<std::uint8_t> switched_colors;
        std::vector<std::uint8_t> intermission_qpics;
        std::vector<std::uint8_t> source_style_masks;
        unsigned switched_row_bytes{};
        unsigned switched_mask_count{};
        unsigned last_light_mask = ~0U;
        AliasAssets aliases;
        std::size_t gameplay_row{};
        std::vector<unsigned> native_sprite_frames;
        std::vector<std::uint8_t> native_pose_map;
        std::size_t dog_pose_map_offset = 0;
        std::optional<std::size_t> knight_key_row;
        std::map<std::pair<std::string, unsigned>, std::size_t> live_sprite_bases;
        X2WeaponAssets weapon;
        int first_software_pose = 256;
        Json shell_boxes;
        Json nail_boxes, health_boxes, explosive_boxes;
        std::vector<std::uint16_t> entrance_entities;
        std::vector<std::uint16_t> exit_entities;

        Map(std::span<const std::uint8_t> pak, const GameplayAssets& assets) :
        bsp(parse_bsp(
            extract_pak_entry(pak, assets.manifest.value("mapEntry", "maps/" + assets.map + ".bsp")),
            parse_quake_palette(extract_pak_entry(pak, "gfx/palette.lmp")),
            parse_quake_colormap(extract_pak_entry(pak, "gfx/colormap.lmp"))
        )),
        data_dir(billboard_path(assets)),
        world(build_quantized_world(data_dir, build_source_world(bsp))),
        brushes(load_packed_brush_assets(data_dir)),
        nodes(read_file(data_dir / "QuakeBSPWorldNodes.bin")),
        planes(read_file(data_dir / "QuakeBSPWorldPlanes.bin")),
        aliases(load_alias_assets(billboard_path(assets))),
        gameplay_row(aliases.rows.size()),
        weapon(render_path(assets, "weaponAssets")),
        shell_boxes(assets.manifest.at("metadata").at("gameplay").at("stockShells").at("boxes")),
        nail_boxes(assets.manifest.at("metadata").at("gameplay").value("stockNailgun", Json::object()).value("boxes", Json::array())),
        health_boxes(assets.manifest.at("metadata").at("gameplay").value("stockHealth", Json::object())
            .value("boxes", Json::array()))
        {
            const auto& gameplay = assets.manifest.at("metadata").at("gameplay");
            if (gameplay.contains("stockExplobox"))
                explosive_boxes.push_back(gameplay.at("stockExplobox"));
            const auto& binding = assets.manifest.at("billboards");
            if (const auto first = assets.constants.find("BSP_WEAPON_NAIL_IDLE"); first != assets.constants.end())
                first_software_pose = static_cast<int>(first->second);
            if (const auto pictures = assets.payloads.find("QuakeIntermission.qim"); pictures != assets.payloads.end())
                intermission_qpics = pictures->second;
            if (const auto found = assets.payloads.find("QuakeBSPFaceColors.bin"); found != assets.payloads.end())
            {
                if (found->second.size() != world.face_lightmaps.size() + brushes.faces.size())
                    fail("baked face table does not match the packed world and brush face counts");
                face_colors = found->second;
            }
            if (const auto found = assets.payloads.find("QuakeBSPSwitchedFaceColors.bin"); found != assets.payloads.end())
            {
                switched_colors = found->second;
                const bool t3_lights = assets.constants.contains("QC_T3_LIGHT_STYLE");
                switched_row_bytes = t3_lights ? 512 : 256;
                const auto palette_bytes = switched_colors.size() - face_colors.size();
                if (assets.map != "e1m1" || (t3_lights ? (palette_bytes != 32 * 512 && palette_bytes != 64 * 512)
                                                       : palette_bytes != 16 * 256))
                    fail("invalid E1M1 light style palette tables");
                switched_mask_count = static_cast<unsigned>(palette_bytes / switched_row_bytes);
                source_style_masks.reserve(bsp.faces.size());
                for (const auto& face : bsp.faces)
                {
                    unsigned mask = 0;
                    for (const auto style : face.light_styles)
                        if (style == 10 && switched_mask_count == 64)
                            mask |= 32;
                        else if (style == 32 && t3_lights)
                            mask |= 16;
                        else if (style >= 33 && style <= 36)
                            mask |= 1U << (style - 33);
                    source_style_masks.push_back(static_cast<std::uint8_t>(mask));
                }
                for (const auto& brush : brushes.faces)
                {
                    if (brush.source_face >= bsp.faces.size())
                        continue;
                    const auto& face = bsp.faces[brush.source_face];
                    if (source_style_masks[brush.source_face])
                        brushes.switched_light_sources.emplace(brush.packed_face, face);
                }
            }
            const auto entrance_count =
                assets.constants.contains("QC_ENTRANCE_COUNT") ? assets.constants.at("QC_ENTRANCE_COUNT") : 0;
            if (entrance_count)
            {
                const auto& leaves = assets.manifest.at("metadata").at("gameplay").at("stockEntranceDoors");
                if (entrance_count != 2 || leaves.size() != 2)
                    fail("gameplay entrance visual metadata must name two leaves");
                for (const auto& leaf : leaves)
                    entrance_entities.push_back(leaf.at("renderEntity").get<std::uint16_t>());
                if (entrance_entities[0] == entrance_entities[1])
                    fail("gameplay entrance visual metadata repeats a leaf");
            }
            if (assets.constants.contains("QC_EXIT_MOVER_COUNT"))
                for (const auto& mover : assets.manifest.at("metadata").at("gameplay").at("stockExitMachinery").at("movers"))
                    exit_entities.push_back(mover.at("renderEntity").get<std::uint16_t>());
            if (assets.constants.contains("QC_SECRET_DOOR_COUNT"))
                for (const auto& door : assets.manifest.at("metadata").at("gameplay").at("stockExitMachinery").at("secretDoors"))
                    exit_entities.push_back(door.at("renderEntity").get<std::uint16_t>());
            if (assets.constants.contains("QC_ORD_DOOR_COUNT"))
                for (const auto& door : assets.manifest.at("metadata").at("gameplay").at("stockExitMachinery").at("ordinaryDoors"))
                    exit_entities.push_back(door.at("renderEntity").get<std::uint16_t>());
            native_sprite_frames = binding.at("frames").get<std::vector<unsigned>>();
            if (const auto found = assets.constants.find("QC_DOG_FRAME_MAP_OFFSET");
                found != assets.constants.end())
                dog_pose_map_offset = static_cast<std::size_t>(found->second);
            if (const auto found = assets.constants.find("QC_KNIGHT_KEY_ROW");
                found != assets.constants.end())
                knight_key_row = static_cast<std::size_t>(found->second);
            if (const auto found = assets.payloads.find("QuakeBSPGruntFrames.bin"); found != assets.payloads.end())
                native_pose_map = found->second;
            else if (!native_sprite_frames.empty())
                fail("gameplay billboard catalog requires the declared native grunt pose map");
            if (!native_sprite_frames.empty())
                for (const auto frame : native_pose_map)
                    if (frame >= native_sprite_frames.size())
                        fail("gameplay native grunt pose map escapes the sprite frame catalog");
            if (binding.at("spriteCount").get<std::size_t>() != aliases.sprites.size() ||
                binding.at("rows").get<std::size_t>() != gameplay_row)
                fail("gameplay billboard binding disagrees with the production catalog");
            // Native standalone packages have animation/fly seed rows, not
            // live entity identities. Reserve a separate row even for the
            // intentionally empty E1M3 sprite package.
            aliases.rows.emplace_back();
            aliases.row_entity_ids.resize(aliases.rows.size());
            weapon.require_scene_palette(world.texture_palette);
            const auto metadata_bytes = read_file(data_dir / "QuakeBSPMetadata.json");
            const auto metadata = Json::parse(metadata_bytes.begin(), metadata_bytes.end());
            if (metadata.at("world").at("root_node").get<int>() != 0)
                fail("gameplay packed renderer requires the native root-node contract");
            for (const auto* boxes : {&shell_boxes, &health_boxes, &nail_boxes, &explosive_boxes})
            {
                for (const auto& box : *boxes)
                {
                    const auto entity = box.at("entityNumber").get<std::uint16_t>();
                    if (std::ranges::find(brushes.external_static_variants, entity,
                            &PackedBrushExternalStaticVariant::entity) == brushes.external_static_variants.end())
                        fail("gameplay pickup is absent from packed XSTATIC geometry");
                }
            }
        }

        void update_aliases(const GameplayRenderSnapshot& snapshot)
        {
            auto& row = aliases.rows.at(gameplay_row);
            auto& entities = aliases.row_entity_ids.at(gameplay_row);
            row.dynamic_states.clear();
            row.tokens.clear();
            entities.clear();
            if (aliases.static_states.size() > 128)
                fail("gameplay static billboard table exceeds the native token capacity");
            for (std::size_t index = 0; index < aliases.static_states.size(); ++index)
            {
                const auto entity = aliases.static_entity_ids.at(index);
                if (std::ranges::find(snapshot.actors, entity, &GameplayActorPose::entity) == snapshot.actors.end())
                    row.tokens.push_back({true, static_cast<std::uint8_t>(index), 0, 0});
            }
            for (const auto& actor : snapshot.actors)
            {
                if (!actor.visible)
                    continue;
                const auto dog = dog_pose_map_offset && actor.model == "progs/dog.mdl";
                const auto offset = dog ? dog_pose_map_offset : std::size_t{0};
                const auto end = dog || !dog_pose_map_offset ? native_pose_map.size() : dog_pose_map_offset;
                std::optional<std::size_t> explicit_row = actor.sprite_row;
                if (!explicit_row && knight_key_row && !actor.slot)
                    explicit_row = *knight_key_row;
                if (!explicit_row && (offset > end || actor.mdl_frame >= end - offset))
                    fail("gameplay actor " + std::to_string(actor.entity) + " (" + actor.model + ") frame "
                         + std::to_string(actor.mdl_frame) + " exceeds its native pose map of " + std::to_string(end-offset));
                const auto sprite_row = explicit_row ? *explicit_row : native_pose_map[offset + actor.mdl_frame];
                const auto frame = native_sprite_frames.at(sprite_row);
                const auto key = std::pair{actor.model, unsigned(sprite_row)};
                const bool direct = actor.model == "effects/combat-impact.spr" || actor.model == "effects/te_teleport.spr";
                auto found = live_sprite_bases.find(key);
                if (found == live_sprite_bases.end())
                {
                    const auto base = actor.sprite_row && !direct ? *actor.sprite_row * 8 :
                        gameplay_sprite_base(aliases, actor.model, frame, direct);
                    if (!direct && (dog_pose_map_offset || knight_key_row) && base != sprite_row * 8)
                        fail("gameplay billboard row disagrees with the native enemy catalog");
                    found = live_sprite_bases.emplace(key, base).first;
                }
                if (row.dynamic_states.size() >= 128)
                    fail("gameplay live billboard row exceeds the native token capacity");
                row.tokens.push_back({false, static_cast<std::uint8_t>(row.dynamic_states.size()), 0, 0});
                row.dynamic_states.push_back(
                    {static_cast<std::uint16_t>(direct ? found->second : found->second | kAliasDirectionalTag),
                     actor.render_origin_q2,
                     static_cast<std::int8_t>(kSinTable[actor.yaw]),
                     static_cast<std::int8_t>(kCosTable[actor.yaw])}
                );
                entities.push_back(actor.entity);
            }
        }

        std::vector<std::uint16_t> active_pickups(const GameplayRenderSnapshot& snapshot) const
        {
            std::vector<std::uint16_t> states;
            const auto append = [&](const Json& boxes, std::uint16_t mask) {
                for (std::size_t bit = 0; bit < boxes.size(); ++bit)
                    if (mask & (1U << bit))
                        states.push_back(boxes[bit].at("entityNumber").get<std::uint16_t>());
            };
            append(shell_boxes, snapshot.shell_mask);
            append(health_boxes, snapshot.health_mask);
            append(nail_boxes, snapshot.nail_mask);
            append(explosive_boxes, snapshot.explobox_solid);
            return states;
        }
    };

  public:
    Impl(const fs::path& pak, const std::vector<GameplayAssets>& maps) :
    pak_(read_file(pak))
    {
        for (const auto& assets : maps)
            assets_.emplace(assets.map, assets);
    }

    GameplayFrame render(const GameplayRenderSnapshot& snapshot)
    {
        auto& pointer = maps_[snapshot.map];
        if (!pointer)
            pointer = std::make_unique<Map>(pak_, assets_.at(snapshot.map));
        auto& map = *pointer;
        if (snapshot.render_scale != 2 && snapshot.render_scale != 3)
            fail("gameplay render scale must be 2 or 3");
        const bool x2 = snapshot.render_scale == 2;
        const bool baked = snapshot.technique == 3;
        if (!map.switched_colors.empty() && snapshot.switched_lights != map.last_light_mask)
        {
            const auto mask_count = map.switched_mask_count;
            const auto mask = static_cast<std::uint8_t>(snapshot.switched_lights & (mask_count - 1));
            map.world.switched_light_mask = mask;
            for (std::size_t i = 0; i < map.face_colors.size(); ++i)
            {
                const unsigned page = map.switched_row_bytes == 512 && i >= 2048 ? 256U : 0U;
                const auto token = map.switched_colors[mask_count * map.switched_row_bytes + i];
                map.face_colors[i] = map.switched_colors[mask * map.switched_row_bytes + page + token];
            }
            map.last_light_mask = mask;
        }
        if (baked && map.face_colors.empty())
            fail("baked rendering requires the playable face color table");
        const auto face_colors = baked ? std::span<const std::uint8_t>(map.face_colors)
                                       : std::span<const std::uint8_t>{};
        const RenderViewportScope viewport(x2 ? RenderScale::X2 : RenderScale::X3, 64, ViewportLayout::Playable);
        const QuakeTurbulencePhaseScope turbulence(static_cast<std::uint8_t>(snapshot.turbulence_phase_q24 >> 24U));
        RenderMode mode;
        if (snapshot.technique == 2 || baked)
            mode.lighting = Lighting::None;
        else if (snapshot.technique == 7)
            mode.textures = false;
        else if (snapshot.technique != 4)
            fail("unsupported gameplay render technique");
        mode.liquid_lighting = Lighting::None;
        mode.liquid_turbulence = LiquidTurbulence::SnesQ4;
        const auto view = packed_view_transform(map.world, snapshot.native_camera);
        const auto packet = gameplay_world_packet(map.world, snapshot.native_camera, map.nodes, map.planes);
        PackedTextureRaster frame;
        if (snapshot.brushes_enabled)
        {
            const auto visual = packed_brush_visual_state_at_pose(map.brushes, snapshot.brush_row);
            const auto pickups = map.active_pickups(snapshot);
            std::vector<PackedBrushInlineVariant> entrance;
            for (std::size_t leaf = 0; leaf < map.entrance_entities.size(); ++leaf)
                entrance.push_back(packed_brush_inline_variant_at_pose(
                    map.brushes,
                    snapshot.entrance_rows.at(leaf),
                    map.entrance_entities[leaf]
                ));
            for (std::size_t i = 0; i < map.exit_entities.size(); ++i)
                entrance.push_back(packed_brush_inline_variant_at_pose(
                    map.brushes, snapshot.exit_rows.at(i), map.exit_entities[i]
                ));
            frame = render_packed_brush_pipeline(
                map.world,
                packet,
                snapshot.native_camera,
                visual,
                map.data_dir,
                map.brushes,
                TextureRasterMode::projective_block8,
                snapshot.surface_time,
                snapshot.entities_enabled,
                snapshot.brush_row,
                true,
                std::span<const std::uint16_t>(pickups),
                std::span<const PackedBrushInlineVariant>(entrance),
                {},
                face_colors
            );
        }
        else
            frame = render_packed_texture_pipeline(
                map.world,
                packet,
                snapshot.native_camera,
                TextureRasterMode::projective_block8,
                snapshot.surface_time,
                face_colors
            );
        // Packed planes retain native miss/depth ownership but have no stale color.
        for (std::size_t pixel = 0; pixel < frame.faces.size(); ++pixel)
            if (frame.faces[pixel] == kMissFace)
                frame.indices[pixel] = frame.lightmapped_indices[pixel] = frame.untextured_lightmap_indices[pixel] = 0;
        Json sky_inspection{{"applied", false}};
        if (mode.textures && !baked)
        {
            auto& sky_plane = mode.lighting == Lighting::None ? frame.indices : frame.lightmapped_indices;
            const auto x3_sky_phase = x2 ? std::nullopt :
                std::optional{static_cast<std::uint32_t>((snapshot.sky_phase_q24 >> 8U) & 0x7FFFFF)};
            auto sky = render_quake_sky_presentation(
                sky_plane,
                frame.faces,
                frame.entities,
                map.world,
                view,
                snapshot.surface_time,
                "gameplay-video-tick",
                x3_sky_phase
            );
            sky_plane = std::move(sky.indices);
            sky_inspection = std::move(sky.inspection);
        }
        GameplayFrame result;
        result.world = selected_render_indices(frame, mode);
        AliasCoverage alias_coverage;
        Json actor_views = Json::array();
        if (snapshot.entities_enabled)
        {
            map.update_aliases(snapshot);
            const auto& row = map.aliases.rows.at(map.gameplay_row);
            for (const auto& projected :
                 ordered_packed_alias_views(snapshot.native_camera, map.aliases, map.gameplay_row))
            {
                const auto& token = row.tokens.at(projected.token);
                const auto& state =
                    token.is_static ? map.aliases.static_states.at(token.index) : row.dynamic_states.at(token.index);
                const auto& sprite = map.aliases.sprites.at(projected.sprite);
                const auto entity =
                    token.is_static ? map.aliases.static_entity_ids.at(token.index)
                                    : map.aliases.row_entity_ids.at(map.gameplay_row).at(token.index);
                actor_views.push_back(
                    {{"entity", entity},
                     {"sprite", projected.sprite},
                     {"model", map.aliases.model_names.at(sprite.model)},
                     {"frame", sprite.frame},
                     {"view", sprite.view},
                     {"originQ2", state.origin_q2},
                     {"size", {sprite.width, sprite.height}},
                     {"offset", {sprite.left, sprite.top}},
                     {"worldSize", {alias_world_width(sprite), alias_world_height(sprite)}},
                     {"depthQ6", projected.depth_q6}}
                );
            }
            if (!map.aliases.rows.at(map.gameplay_row).tokens.empty())
            {
                // Packed world and sprites share the same native Q6 depth and
                // canonical logical pixel order until physical presentation.
                result.world = compose_post_opaque_alias_indices(
                    result.world,
                    frame.depth_q6,
                    snapshot.native_camera,
                    map.aliases,
                    map.gameplay_row,
                    mode,
                    &alias_coverage
                );
            }
        }
        result.composite = result.world;
        const auto weapon_frame = mode.textures ? snapshot.weapon_frame : std::uint16_t{0};
        if (x2 && mode.textures)
            map.weapon.composite(result.composite, weapon_frame, 0, render_height());
        // X2 captures store reversed display rows with the weapon. X3
        // captures keep canonical source order for planar comparison.
        if (x2)
        {
            mirror_x(result.world);
            mirror_x(result.composite);
        }
        if (snapshot.intermission_stats)
            draw_intermission(result.composite, map.intermission_qpics, *snapshot.intermission_stats, render_width(), render_height());
        const auto palette = map.weapon.palette(snapshot.weapon_frame & 255);
        const auto color_word = [&](std::uint8_t index) {
            auto word =
                mode.textures ? read_u16(palette, 2U * index) : snes_color_word(map.world.untextured_palette.at(index));
            if (snapshot.pickup_bonus_ticks || snapshot.eye_contents == -3 || snapshot.eye_contents == -4 ||
                (!x2 && (snapshot.damage_tint || snapshot.muzzle_tint)))
                word = pickup_color(word, index, snapshot);
            else if (snapshot.quad_tint)
            {
                const int r = word & 31, g = (word >> 5) & 31, b = (word >> 10) & 31;
                word = std::uint16_t((r - (r * 30 + 255) / 256) | ((g - (g * 30 + 255) / 256) << 5) |
                                     ((b + (31 - b) * 30 / 256) << 10));
            }
            else if (snapshot.suit_tint)
            {
                const int r = word & 31, g = (word >> 5) & 31, b = (word >> 10) & 31;
                word = std::uint16_t((r - (r * 20 + 255) / 256) | ((g + (31 - g) * 20 / 256) << 5) |
                                     ((b - (b * 20 + 255) / 256) << 10));
            }
            return word;
        };
        if (!x2)
        {
            std::array<std::uint16_t, 256> colors{};
            for (std::size_t i = 0; i < colors.size(); ++i)
                colors[i] = color_word(static_cast<std::uint8_t>(i));
            result.visible_x3_bgr555 = gameplay_x3_visible(result.composite, map.weapon, weapon_frame,
                map.first_software_pose, render_height(), colors);
        }
        result.pixels.reserve(result.composite.size());
        for (const auto index : result.composite)
        {
            const auto word = color_word(index);
            const auto red = ((word & 31U) * 255U + 15U) / 31U;
            const auto green = (((word >> 5U) & 31U) * 255U + 15U) / 31U;
            const auto blue = (((word >> 10U) & 31U) * 255U + 15U) / 31U;
            result.pixels.push_back((red << 16U) | (green << 8U) | blue);
        }
        if (!snapshot.pickup_lines.front().empty())
        {
            if (notify_font_.empty())
                notify_font_ = pickup_font(pak_);
            result.pickup_text_mask = pickup_text(snapshot.pickup_lines, notify_font_);
        }
        result.inspection = {
            {"map", snapshot.map},
            {"videoTick", snapshot.video_tick},
            {"entranceRows", snapshot.entrance_rows},
            {"weaponFrame", weapon_frame},
            {"visibleWeaponLayer", !weapon_frame ? "none" :
                (weapon_frame & 255) >= map.first_software_pose ? "staged" : "native-obj"},
            {"renderScale", snapshot.render_scale},
            {"viewport", {{"width", render_width()}, {"height", render_height()}, {"rowStride", kLogicalWidth},
                          {"center", {render_center_x(), render_center_y()}}}},
            {"technique", snapshot.technique},
            {"brushesEnabled", snapshot.brushes_enabled},
            {"entitiesEnabled", snapshot.entities_enabled},
            {"renderProfile", x2 ? "snes-playable-x2" : "snes-playable-x3"},
            {"worldRenderer", "snes-packed-projective-block8-v1"},
            {"worldSelection", "all-world-front-guard-uncapped-v1"},
            {"selectedWorldFaces", packet.source_faces.size()},
            {"actorRenderer", "snes-packed-qba1-billboards-v1"},
            {"billboardPresentation", x2 ? "physical-x2-horizontal-row-flip" : "canonical-x3-planar-source"},
            {"liquidLighting", "none"},
            {"liquidTurbulence", "snes-q4"},
            {"liquids", quake_turbulence_inspection(frame)},
            {"aliases",
             {{"sourceSprites", map.aliases.sprites.size()},
              {"staticStates", map.aliases.static_states.size()},
              {"liveStates",
               snapshot.entities_enabled ? map.aliases.rows.at(map.gameplay_row).dynamic_states.size() : 0},
              {"tokens", alias_coverage.tokens},
              {"projected", alias_coverage.projected},
              {"plotPixels", alias_coverage.packed_plot_pixels},
              {"visiblePixels", alias_coverage.packed_visible_pixels},
              {"opaqueOccludedPixels", alias_coverage.packed_opaque_occluded_pixels},
              {"actors", std::move(actor_views)},
              {"coverage", packed_alias_inspection(snapshot.native_camera, map.aliases, map.gameplay_row, alias_coverage)}}},
            {"surface", std::move(sky_inspection)}
        };
        if (!map.source_style_masks.empty())
        {
            std::vector<unsigned> pixels_by_style_mask(map.switched_mask_count);
            for (const auto face : frame.faces)
                if (face < map.source_style_masks.size())
                    ++pixels_by_style_mask[map.source_style_masks[face]];
            result.inspection["switchedLighting"] = {{"mask", snapshot.switched_lights},
                {"worldPixelsBySourceStyleMask", pixels_by_style_mask}};
        }
        return result;
    }

  private:
    std::vector<std::uint8_t> pak_;
    std::vector<std::uint8_t> notify_font_;
    std::map<std::string, GameplayAssets> assets_;
    std::map<std::string, std::unique_ptr<Map>> maps_;
};

GameplayRenderer::GameplayRenderer(const fs::path& pak, const std::vector<GameplayAssets>& maps) :
impl_(std::make_unique<Impl>(pak, maps))
{
}
GameplayRenderer::~GameplayRenderer() = default;
GameplayFrame GameplayRenderer::render(const GameplayRenderSnapshot& snapshot)
{
    return impl_->render(snapshot);
}

} // namespace quake_bsp_reference
