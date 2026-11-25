#include "source_fly_scene.hpp"

namespace quake_bsp_reference {
namespace {
const PackedBrushSection& section(const PackedBrushAssets& assets, std::string_view name, int stride)
{
    const auto found = std::ranges::find(assets.sections, name, &PackedBrushSection::name);
    if (found == assets.sections.end() || found->record_bytes != stride ||
        (stride != 0 && found->bytes.size() != static_cast<std::size_t>(found->record_count) * stride))
        fail("source Fly has an invalid QBSA " + std::string(name) + " section");
    return *found;
}

bool same_state(const BrushEntityState& left, const BrushEntityState& right)
{
    return left.entity == right.entity && left.model_index == right.model_index &&
           left.inline_model == right.inline_model && left.frame == right.frame &&
           exactly_equal(left.origin, right.origin) && left.angles == right.angles;
}
} // namespace

BrushReplay complete_source_fly_brush_replay(
    const BrushReplay& replay,
    const PackedBrushAssets& assets,
    std::span<const std::uint8_t> compact
)
{
    const auto& directory = section(assets, "REPLAY", 0).bytes;
    require_range(compact, 0, directory.size(), "source Fly QBSE directory");
    require_range(compact, 0, 32, "source Fly QBSE header");
    if (directory.size() != 32 + assets.entities.size() * 8 || read_u16(compact, 4) != 3 ||
        read_u16(compact, 6) != replay.sample_rate || read_brush_u64(compact, 8) != replay.camera_track_fnv1a64 ||
        read_u16(compact, 16) != replay.row_count() || read_u16(compact, 18) != assets.entities.size() ||
        read_u16(compact, 30) != 0 || read_u16(directory, 30) != 1)
        fail("source Fly QBSE does not match the source replay");
    for (std::size_t index = 0; index < directory.size(); ++index)
        if (index != 30 && compact[index] != directory[index])
            fail("source Fly runtime and offline QBSE directories differ");
    const auto variant_offset = directory.size();
    const auto variant_count = read_u16(compact, 24);
    require_range(compact, variant_offset, static_cast<std::size_t>(variant_count) * 7, "source Fly variants");
    const auto& rows = section(assets, "ROWSTATE", 2);
    const auto& fly = section(assets, "FLYSTATE", 2);
    const auto& states = section(assets, "VSTATES", 8);
    const auto& transforms = section(assets, "VTRANS", 3);
    if (rows.record_count != replay.row_count() || replay.row_count() > 65536)
        fail("source Fly row count differs from the camera replay");

    BrushReplay result{replay.sample_rate, replay.first_server_time, replay.camera_track_fnv1a64, {}, {}};
    result.row_snapshots.reserve(replay.row_count());
    result.snapshots.reserve(replay.row_count());
    for (std::size_t pose = 0; pose < replay.row_count(); ++pose)
    {
        const auto original = replay.row(pose);
        std::vector<BrushEntityState> complete;
        const auto add = [&](BrushEntityState fallback) {
            const auto existing = std::ranges::find(original, fallback.entity, &BrushEntityState::entity);
            if (existing != original.end())
            {
                if (existing->model_index != fallback.model_index || existing->inline_model != fallback.inline_model)
                    fail("source Fly packed identity disagrees with its recorded brush");
                // Native admission can fall back or quantize; keep available source poses and frames.
                complete.push_back(*existing);
            }
            else
            {
                // FLYSTATE resolves absent slots' animated textures at signon time.
                fallback.freeze_texture_animation = true;
                complete.push_back(fallback);
            }
        };
        auto state = read_u16(rows.bytes, pose * 2);
        if (state == 0 || state > fly.record_count)
            fail("source Fly ROWSTATE escapes FLYSTATE");
        state = read_u16(fly.bytes, static_cast<std::size_t>(state - 1) * 2);
        if (state == 0 || state > states.record_count)
            fail("source Fly state escapes VSTATES");
        const auto entry = static_cast<std::size_t>(state - 1) * 8;
        const auto first = read_u16(states.bytes, entry);
        const auto count = states.bytes[entry + 6];
        require_range(
            transforms.bytes,
            static_cast<std::size_t>(first) * 3,
            static_cast<std::size_t>(count) * 3,
            "source Fly visual transforms"
        );
        for (std::size_t index = first; index < static_cast<std::size_t>(first) + count; ++index)
        {
            const auto slot = transforms.bytes[index * 3];
            if (slot >= assets.entities.size())
                fail("source Fly transform names an invalid entity slot");
            if (slot >= assets.external_entity_slot_first)
                continue; // External pickups keep their independently frozen QER1 membership.
            const auto& entity = assets.entities[slot];
            const auto local = read_u16(transforms.bytes, index * 3 + 1);
            const auto variant = static_cast<std::size_t>(entity.first_variant) + local;
            if (local >= entity.variant_count || variant >= variant_count)
                fail("source Fly transform names an invalid local variant");
            const auto offset = variant_offset + variant * 7;
            add(
                {entity.entity,
                 static_cast<std::uint16_t>(entity.inline_model + 1),
                 entity.inline_model,
                 compact[offset + 6],
                 {read_i16(compact, offset) / 8.0,
                  read_i16(compact, offset + 2) / 8.0,
                  read_i16(compact, offset + 4) / 8.0},
                 {}}
            );
        }
        for (const auto& record : assets.static_variants)
        {
            const auto& variant = assets.variants.at(record.geometry_variant);
            add(
                {record.entity,
                 static_cast<std::uint16_t>(variant.inline_model + 1),
                 variant.inline_model,
                 0,
                 {variant.origin_x_q3 / 8.0, variant.origin_y_q3 / 8.0, variant.origin_z_q3 / 8.0},
                 {}}
            );
        }
        std::ranges::sort(complete, {}, &BrushEntityState::entity);
        if (std::ranges::adjacent_find(complete, {}, &BrushEntityState::entity) != complete.end())
            fail("source Fly completed brush set contains duplicate entities");
        for (const auto& entity : original)
            if (std::ranges::find(complete, entity.entity, &BrushEntityState::entity) == complete.end())
                fail("source Fly completed set omitted a recorded brush");
        result.row_snapshots.push_back(static_cast<std::uint16_t>(pose));
        result.snapshots.push_back({std::move(complete)});
    }
    return result;
}

bool run_source_fly_scene_self_test()
{
    PackedBrushAssets assets;
    assets.entities = {{25, 11, 2, 0}, {99, 90, 1, 2}};
    assets.external_entity_slot_first = 1;
    assets.variants = {{35, 0, 0, 0}};
    assets.static_variants = {{60, 0}};
    std::vector<std::uint8_t> compact(32 + 16 + 21);
    const auto word = [&](std::size_t offset, int value) {
        compact[offset] = static_cast<std::uint8_t>(value);
        compact[offset + 1] = static_cast<std::uint8_t>(value >> 8);
    };
    compact[0] = 'Q';
    compact[1] = 'B';
    compact[2] = 'S';
    compact[3] = 'E';
    word(4, 3);
    word(6, 30);
    word(16, 2);
    word(18, 2);
    word(24, 3);
    word(32, 25);
    compact[34] = 11;
    word(36, 2);
    word(40, 99);
    compact[42] = 90;
    word(44, 1);
    word(46, 2);
    word(48, 24);
    compact[54] = 1; // Missing signon state: x=3, alternate texture frame 1.
    word(55, 40);    // Recorded state: x=5.
    std::vector<std::uint8_t> directory(compact.begin(), compact.begin() + 48);
    directory[30] = 1;
    assets.sections = {
        {"REPLAY", directory, 0, 0, 0, 0},
        {"ROWSTATE", {1, 0, 2, 0}, 0, 0, 2, 2},
        {"FLYSTATE", {1, 0, 2, 0}, 0, 0, 2, 2},
        {"VSTATES", {0, 0, 0, 0, 0, 0, 2, 0, 2, 0, 0, 0, 0, 0, 1, 0}, 0, 0, 8, 2},
        {"VTRANS", {0, 0, 0, 1, 0, 0, 0, 1, 0}, 0, 0, 3, 3}
    };
    BrushReplay original{30, 1.5, 0, {0, 1}, {}};
    original.snapshots.emplace_back();
    original.snapshots.push_back({{{25, 12, 11, 2, {5.125, 0, 0}, {}}}});
    const auto completed = complete_source_fly_brush_replay(original, assets, compact);
    const bool correct =
        original.row(0).empty() && original.row(1).size() == 1 && completed.row(0).size() == 2 &&
        completed.row(1).size() == 2 && completed.row(0)[0].origin.x == 3 && completed.row(0)[0].frame == 1 &&
        completed.row(0)[0].freeze_texture_animation && completed.row(0)[1].entity == 60 &&
        same_state(original.row(1)[0], completed.row(1)[0]) && !completed.row(1)[0].freeze_texture_animation;
    compact[8] = 1;
    try
    {
        static_cast<void>(complete_source_fly_brush_replay(original, assets, compact));
    }
    catch (const std::exception&)
    {
        return correct;
    }
    return false;
}

} // namespace quake_bsp_reference
