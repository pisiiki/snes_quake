#pragma once

#include "world.hpp"
#include "geometry.hpp"
#include "brushes.hpp"
#include "external_models.hpp"

namespace quake_bsp_reference {

inline constexpr std::size_t kAliasHalfbankBytes = 0x8000;
inline constexpr std::size_t kAliasHeaderBytes = 44;
inline constexpr std::size_t kAliasRowBytes = 8;
inline constexpr std::size_t kAliasSpriteBytes = 14;
inline constexpr std::size_t kAliasStateBytes = 8;
inline constexpr std::size_t kAliasFlyFacingBytes = 2;
inline constexpr std::size_t kAliasGroupHeaderBytes = 5;
inline constexpr std::uint16_t kAliasFace = 0xfffe;
inline constexpr std::uint16_t kAliasDirectionalTag = 0x8000;
inline constexpr std::uint16_t kAliasDirectionalMask = 0x7fff;
inline constexpr std::size_t kAliasFlyRowCount = 8;
inline constexpr std::array<std::pair<std::uint8_t, std::uint16_t>, 17> kAliasStorageLocations{{
    {0x6b, 0x8000}, {0x6c, 0x0000}, {0x6c, 0x8000}, {0x6d, 0x0000}, {0x6d, 0x8000}, {0x6e, 0x0000}, {0x6e, 0x8000},
    {0x0e, 0x8000}, {0x38, 0x8000}, {0x39, 0x8000}, {0x3a, 0x8000}, {0x3b, 0x8000}, {0x3c, 0x8000}, {0x3d, 0x8000},
    {0x3e, 0x8000}, {0x25, 0x8000}, {0x0f, 0x8000},
}};

struct AliasSprite
{
    std::uint8_t width{};
    std::uint8_t height{};
    std::int16_t left{};
    std::int16_t top{};
    std::vector<std::uint8_t> pixels;
    std::uint8_t world_width{};
    std::uint8_t world_height{};
    std::uint8_t model{};
    std::uint8_t frame{};
    std::uint8_t view{};
};

struct AliasState
{
    std::uint16_t sprite{};
    std::array<std::int16_t, 3> origin_q2{};
    std::int8_t yaw_sin_q6{};
    std::int8_t yaw_cos_q6{};
};

struct AliasToken
{
    bool is_static{};
    std::uint8_t index{};
    std::uint16_t leaf{};
    std::uint16_t parent{};
};

struct AliasRow
{
    std::vector<AliasState> dynamic_states;
    std::vector<AliasToken> tokens;
};

struct AliasAssets
{
    std::uint8_t rotation_yaw_q8{};
    std::uint64_t camera_fingerprint{};
    std::uint64_t package_fingerprint{};
    std::vector<AliasSprite> sprites;
    std::vector<AliasState> static_states;
    std::vector<AliasRow> rows;
    std::vector<std::string> model_names;
    std::vector<std::string> model_kinds;
    std::vector<int> static_entity_ids;
    std::vector<std::vector<int>> row_entity_ids;
};

struct AliasTokenVisibility
{
    std::vector<std::uint8_t> candidates;
};

struct AliasVisibilityRow
{
    std::vector<AliasTokenVisibility> tokens;
};

struct AliasCoverageRecord
{
    std::size_t paint_ordinal{};
    std::size_t token{};
    std::uint16_t sprite{};
    bool is_static{};
    std::uint8_t state{};
    std::uint16_t leaf{};
    std::uint16_t parent{};
    std::array<std::int16_t, 3> origin_q2{};
    int right_q6{};
    int up_q6{};
    int depth_q6{};
    int first_x{};
    int first_y{};
    int last_x{};
    int last_y{};
    std::size_t plot_pixels{};
    std::size_t visible_pixels{};
    std::size_t opaque_occluded_pixels{};
    std::size_t overwrote_alias_pixels{};
    std::size_t overwritten_by_alias_pixels{};
    std::size_t final_owned_pixels{};
};

std::size_t alias_sprite_id(const AliasState& state);

std::size_t alias_directional_view(int forward, int right);

std::size_t alias_resolved_sprite_id(const AliasState& state, int dx, int dy, std::uint8_t rotation_yaw_q8 = 0);

int alias_world_width(const AliasSprite& sprite);

int alias_world_height(const AliasSprite& sprite);

std::size_t alias_fly_row(const AliasAssets& assets, const Camera& camera);

struct AliasOverwriteRecord
{
    std::size_t earlier_token{};
    std::size_t later_token{};
    std::size_t pixels{};
};

struct AliasCoverage
{
    std::size_t tokens{};
    std::size_t projected{};
    std::size_t clipped{};
    std::uint64_t model_mask{};
    std::size_t minimum_projected_area{};
    std::size_t maximum_projected_area{};
    std::size_t packed_plot_pixels{};
    std::size_t packed_visible_pixels{};
    std::size_t packed_opaque_occluded_pixels{};
    std::size_t ideal_candidate_pixels{};
    std::size_t ideal_opaque_occluded_pixels{};
    std::vector<AliasCoverageRecord> records;
    std::vector<AliasOverwriteRecord> overwrites;
};

std::uint64_t alias_read_u64(std::span<const std::uint8_t> bytes, std::size_t offset);

AliasAssets load_alias_assets(const fs::path& directory);

void require_alias_camera_identity(const AliasAssets& assets, const fs::path& camera_track);

template <typename Consumer>
void for_each_alias_pixel(
    const SourceWorld& world,
    const ViewTransform& view,
    const AliasAssets& assets,
    std::size_t sample_index,
    Consumer&& consume
)
{
    if (sample_index >= assets.rows.size())
    {
        fail("alias render sample index is out of range");
    }
    const auto& row = assets.rows[sample_index];
    for (const auto& token : row.tokens)
    {
        const auto& state = token.is_static ? assets.static_states.at(token.index) : row.dynamic_states.at(token.index);
        const auto& sprite = assets.sprites.at(alias_sprite_id(state));
        const Vec3 origin = {
            world.origin.x + state.origin_q2[0] * (kWorldScale / 4.0),
            world.origin.y + state.origin_q2[1] * (kWorldScale / 4.0),
            world.origin.z + state.origin_q2[2] * (kWorldScale / 4.0),
        };
        const auto delta = origin - view.origin;
        const double depth = dot(delta, view.forward);
        if (depth <= 1e-7)
        {
            continue;
        }
        const double center_right = dot(delta, view.screen_right);
        const double center_up = dot(delta, view.up);
        const double left = 64.0 + (center_right + sprite.left) * kFocalLength / depth;
        const double right = 64.0 + (center_right + sprite.left + alias_world_width(sprite)) * kFocalLength / depth;
        const double top = 56.0 - (center_up + sprite.top) * kFocalLength / depth;
        const double bottom = 56.0 - (center_up + sprite.top - alias_world_height(sprite)) * kFocalLength / depth;
        if (!(right > left) || !(bottom > top))
        {
            continue;
        }
        const int first_x = std::max(0, static_cast<int>(std::ceil(left - 0.5 - 1e-9)));
        const int last_x = std::min(kLogicalWidth - 1, static_cast<int>(std::floor(right - 0.5 + 1e-9)));
        const int first_y = std::max(0, static_cast<int>(std::ceil(top - 0.5 - 1e-9)));
        const int last_y = std::min(kLogicalHeight - 1, static_cast<int>(std::floor(bottom - 0.5 + 1e-9)));
        for (int y = first_y; y <= last_y; ++y)
        {
            const auto source_y = std::min(
                static_cast<int>(sprite.height) - 1,
                std::max(0, static_cast<int>((y + 0.5 - top) * sprite.height / (bottom - top)))
            );
            for (int x = first_x; x <= last_x; ++x)
            {
                const auto source_x = std::min(
                    static_cast<int>(sprite.width) - 1,
                    std::max(0, static_cast<int>((x + 0.5 - left) * sprite.width / (right - left)))
                );
                const auto texel = sprite.pixels.at(static_cast<std::size_t>(source_y) * sprite.width + source_x);
                if (texel == 0xffU)
                {
                    continue;
                }
                const auto pixel = logical_pixel_index(x, y);
                consume(pixel, depth, texel, source_x, source_y, state, token);
            }
        }
    }
}

void compose_alias_billboards(
    ReferenceFrame& frame,
    const SourceWorld& world,
    const ViewTransform& view,
    const AliasAssets& assets,
    std::size_t sample_index,
    AliasCoverage* coverage = nullptr
);

struct PackedAliasAxisProjection
{
    int first_q7{};
    int last_q7{};
    int span_q7{};
    int first_pixel{};
    int last_pixel{};
    bool visible{};
    bool clipped{};
};

PackedAliasAxisProjection project_packed_alias_axis(
    int first_component,
    int last_component,
    int depth,
    int center_q7,
    bool inverted,
    int logical_extent
);

struct PackedAliasView
{
    std::size_t token{};
    int right_q6{};
    int up_q6{};
    int depth_q6{};
    std::size_t sprite{};
};

std::vector<PackedAliasView>
ordered_packed_alias_views(const Camera& camera, const AliasAssets& assets, std::size_t sample_index);

template <typename Consumer>
void for_each_packed_alias_pixel(
    const Camera& camera,
    const AliasAssets& assets,
    std::size_t sample_index,
    Consumer&& consume,
    AliasCoverage* coverage = nullptr
)
{
    if (coverage != nullptr)
    {
        coverage->tokens = assets.rows[sample_index].tokens.size();
    }
    const auto& row = assets.rows[sample_index];
    const auto views = ordered_packed_alias_views(camera, assets, sample_index);
    for (std::size_t paint_ordinal = 0; paint_ordinal < views.size(); ++paint_ordinal)
    {
        const auto& view = views[paint_ordinal];
        const auto token_ordinal = view.token;
        const auto& tokens = row.tokens;
        const auto& token = tokens[token_ordinal];
        const auto& state = token.is_static ? assets.static_states.at(token.index) : row.dynamic_states.at(token.index);
        const auto& sprite = assets.sprites.at(view.sprite);
        const int right = view.right_q6;
        const int up = view.up_q6;
        const int depth = view.depth_q6;
        if (depth < 64)
        {
            continue;
        }

        const int left_component = wrap_i16(right + sprite.left * 4);
        const int right_component = wrap_i16(right + (sprite.left + alias_world_width(sprite)) * 4);
        const int top_component = wrap_i16(up + sprite.top * 4);
        const int bottom_component = wrap_i16(up + (sprite.top - alias_world_height(sprite)) * 4);
        const auto horizontal =
            project_packed_alias_axis(left_component, right_component, depth, 8192, false, kLogicalWidth);
        const auto vertical =
            project_packed_alias_axis(top_component, bottom_component, depth, 7168, true, kLogicalHeight);
        if (!horizontal.visible || !vertical.visible)
        {
            continue;
        }
        const int left_q7 = horizontal.first_q7;
        const int span_x_q7 = horizontal.span_q7;
        const int top_q7 = vertical.first_q7;
        const int span_y_q7 = vertical.span_q7;
        const int first_x = horizontal.first_pixel;
        const int raw_last_x = horizontal.last_pixel;
        const int first_y = vertical.first_pixel;
        const int raw_last_y = vertical.last_pixel;
        if (coverage != nullptr)
        {
            ++coverage->projected;
            if (horizontal.clipped || vertical.clipped)
            {
                ++coverage->clipped;
            }
            if (sprite.model >= 64)
            {
                fail("alias coverage model mask exceeds 64 models");
            }
            coverage->model_mask |= std::uint64_t{1} << sprite.model;
            const auto width = static_cast<std::size_t>(
                static_cast<std::ptrdiff_t>(raw_last_x) - static_cast<std::ptrdiff_t>(first_x) + 1
            );
            const auto height = static_cast<std::size_t>(
                static_cast<std::ptrdiff_t>(raw_last_y) - static_cast<std::ptrdiff_t>(first_y) + 1
            );
            const auto area = width * height;
            if (coverage->minimum_projected_area == 0 || area < coverage->minimum_projected_area)
            {
                coverage->minimum_projected_area = area;
            }
            coverage->maximum_projected_area = std::max(coverage->maximum_projected_area, area);
            coverage->records.push_back(
                {paint_ordinal,
                 token_ordinal,
                 static_cast<std::uint16_t>(view.sprite),
                 token.is_static,
                 token.index,
                 token.leaf,
                 token.parent,
                 state.origin_q2,
                 right,
                 up,
                 depth,
                 first_x,
                 first_y,
                 raw_last_x,
                 raw_last_y}
            );
        }
        const int last_x = std::min(kLogicalWidth - 1, raw_last_x);
        const int last_y = std::min(kLogicalHeight - 1, raw_last_y);
        for (int y = std::max(0, first_y); y <= last_y; ++y)
        {
            const int source_y = std::clamp(
                ((y * 128 + 64 - top_q7) * sprite.height) / span_y_q7,
                0,
                static_cast<int>(sprite.height) - 1
            );
            for (int x = std::max(0, first_x); x <= last_x; ++x)
            {
                const int source_x = std::clamp(
                    ((x * 128 + 64 - left_q7) * sprite.width) / span_x_q7,
                    0,
                    static_cast<int>(sprite.width) - 1
                );
                const auto texel = sprite.pixels.at(static_cast<std::size_t>(source_y) * sprite.width + source_x);
                if (texel != 0xffU)
                {
                    if (coverage != nullptr)
                    {
                        ++coverage->packed_plot_pixels;
                        ++coverage->records.back().plot_pixels;
                    }
                    consume(logical_pixel_index(x, y), depth, texel, token_ordinal);
                }
            }
        }
    }
}

std::vector<std::uint8_t> compose_post_opaque_alias_indices(
    std::span<const std::uint8_t> opaque_indices,
    std::span<const std::int16_t> opaque_depth_q6,
    const Camera& camera,
    const AliasAssets& assets,
    std::size_t sample_index,
    RenderMode mode,
    AliasCoverage* coverage = nullptr,
    AliasVisibilityRow* visibility = nullptr
);

Json packed_alias_inspection(
    const Camera& camera,
    const AliasAssets& assets,
    std::size_t source_pose,
    const AliasCoverage& coverage
);

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
    AliasCoverage* coverage = nullptr,
    const ExternalBspScene* external_scene = nullptr,
    const ExternalBspReplay* external_replay = nullptr,
    bool external_models_enabled = false,
    ExternalBspCoverage* external_coverage = nullptr
);

} // namespace quake_bsp_reference
