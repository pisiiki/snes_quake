#pragma once

#include "world.hpp"

namespace quake_bsp_reference {

class X2WeaponAssets
{
  public:
    explicit X2WeaponAssets(const fs::path& path)
    :
    bytes_(read_file(path))
    {
        constexpr std::array<std::uint8_t, 3> magic{'Q', 'W', 'V'};
        if (bytes_.size() < header_bytes || !std::ranges::equal(magic, std::span(bytes_).first(3)) ||
            bytes_[3] != '4' ||
            read_u16(bytes_, 4) != kLogicalWidth || read_u16(bytes_, 6) != kLogicalHeight)
        {
            fail("invalid X2 weapon asset header");
        }
        pose_count_ = read_u16(bytes_, 8);
        pose_stride_ = 2;
        idle_offset_ = header_bytes + pose_count_ * pose_stride_;
        const auto frame_count = static_cast<std::size_t>(read_u16(bytes_, 10));
        const auto lookup_end = idle_offset_ + frame_count + 1;
        if (pose_count_ == 0 || frame_count > 255 || lookup_end > bytes_.size())
        {
            fail("invalid X2 weapon lookup size or frame count");
        }
        if (bytes_[idle_offset_] != 0 ||
            std::ranges::any_of(
                std::span(bytes_).subspan(idle_offset_, frame_count + 1),
                [&](std::uint8_t id) { return id > frame_count; }
            ))
        {
            fail("invalid X2 weapon pose or idle lookup");
        }
        for (std::size_t pose = 0; pose < pose_count_; ++pose)
        {
            const auto frame = frame_for_pose(pose);
            const auto bob = bob_for_pose(pose);
            if (frame > frame_count || std::abs(bob) > bob_limit || (frame == 0 && bob != 0))
                fail("invalid X2 weapon pose or bob lookup");
        }

        scene_palette_offset_ = lookup_end;
        auto offset = lookup_end + 2 * palette_bytes;
        if (offset > bytes_.size())
            fail("truncated QWV4 scene palettes");
        const auto base = scene_palette(false);
        const auto flash = scene_palette(true);
        constexpr std::array<unsigned, 3> tint{31, 24, 12};
        for (std::size_t index = 0; index < 256; ++index)
        {
            const auto word = read_u16(base, index * 2);
            const auto actual = read_u16(flash, index * 2);
            unsigned expected = 0;
            for (unsigned channel = 0; channel < tint.size(); ++channel)
                expected |= ((7 * ((word >> (5 * channel)) & 31) + tint[channel] + 4) / 8) << (5 * channel);
            if ((word & 0x8000) || actual != expected)
                fail("invalid QWV4 base or flash palette");
        }
        frame_offsets_.reserve(frame_count);
        for (std::size_t frame = 0; frame < frame_count; ++frame)
        {
            if (bytes_.size() - offset < frame_header_bytes)
            {
                fail("truncated X2 weapon frame header");
            }
            const auto crop = crop_at(offset);
            const bool empty = crop.width == 0 || crop.height == 0;
            if ((empty && (crop.x || crop.y || crop.width || crop.height)) || crop.x + crop.width > kLogicalWidth ||
                crop.y + crop.height > kLogicalHeight + (pose_stride_ == 2 ? bob_limit : 0))
            {
                fail("invalid X2 weapon frame crop");
            }
            frame_offsets_.push_back(offset);
            if (bytes_[offset + crop_bytes] > 1)
                fail("invalid QWV4 flash flag");
            offset += frame_header_bytes;
            const auto pixel_count = crop.width * crop.height;
            if (pixel_count > bytes_.size() - offset)
            {
                fail("truncated X2 weapon crop pixels");
            }
            offset += pixel_count;
        }
        if (offset != bytes_.size())
        {
            fail("trailing X2 weapon asset data");
        }
        for (std::size_t frame = 0; frame <= frame_count; ++frame)
            if (flash_for_frame(idle_for_frame(frame)))
                fail("QWV4 idle frame cannot flash");
    }

    [[nodiscard]] std::size_t pose_count() const
    {
        return pose_count_;
    }

    [[nodiscard]] std::size_t frame_for_pose(std::size_t pose) const
    {
        if (pose >= pose_count_)
        {
            fail("X2 weapon source pose is outside the asset");
        }
        return bytes_[header_bytes + pose * pose_stride_];
    }

    [[nodiscard]] int bob_for_pose(std::size_t pose) const
    {
        if (pose >= pose_count_)
            fail("X2 weapon source pose is outside the asset");
        if (pose_stride_ == 1)
            return 0;
        const int encoded = bytes_[header_bytes + pose * pose_stride_ + 1];
        return encoded < 128 ? encoded : encoded - 256;
    }

    [[nodiscard]] std::size_t idle_for_frame(std::size_t frame) const
    {
        if (frame > frame_offsets_.size())
        {
            fail("X2 weapon frame is outside the asset");
        }
        return bytes_[idle_offset_ + frame];
    }

    [[nodiscard]] bool flash_for_frame(std::size_t frame) const
    {
        return frame != 0 && bytes_[frame_offset(frame) + crop_bytes] != 0;
    }

    [[nodiscard]] std::span<const std::uint8_t> scene_palette(bool flash = false) const
    {
        return std::span(bytes_).subspan(scene_palette_offset_ + (flash ? palette_bytes : 0), palette_bytes);
    }

    [[nodiscard]] std::span<const std::uint8_t> palette(std::size_t frame) const
    {
        return scene_palette(flash_for_frame(frame));
    }

    void require_scene_palette(const std::array<Rgb, 256>& palette) const
    {
        const auto base = scene_palette();
        for (std::size_t i = 0; i < palette.size(); ++i)
            if (read_u16(base, 2 * i) != snes_color_word(palette[i]))
                fail("QWV4 weapon and world scene palettes differ");
    }

    void composite(std::span<std::uint8_t> world, std::size_t frame, int bob = 0, int clip_height = kLogicalHeight) const
    {
        if (world.size() != kLogicalPixels || clip_height < 0 || clip_height > kLogicalHeight)
        {
            fail("X2 weapon composition requires a 128x112 world plane and a valid clip height");
        }
        for_each_opaque(frame, bob, [&](std::size_t position, std::uint8_t pixel) { world[position] = pixel; },
                        clip_height);
    }

    template <typename Visitor> void for_each_opaque(std::size_t frame, int bob, Visitor visit,
                                                      int clip_height = kLogicalHeight) const
    {
        if (frame == 0)
        {
            return;
        }
        const auto offset = frame_offset(frame);
        const auto crop = crop_at(offset);
        const auto source = std::span(bytes_).subspan(offset + frame_header_bytes);
        for (std::size_t y = 0; y < crop.height; ++y)
        {
            const int destination_y = static_cast<int>(crop.y + y) + bob;
            if (destination_y < 0 || destination_y >= clip_height)
                continue;
            const auto destination_row = static_cast<std::size_t>(destination_y) * kLogicalWidth + crop.x;
            for (std::size_t x = 0; x < crop.width; ++x)
            {
                if (const auto pixel = source[y * crop.width + x]; pixel != 0)
                {
                    visit(destination_row + x, pixel);
                }
            }
        }
    }

  private:
    static constexpr std::size_t header_bytes = 12;
    static constexpr std::size_t crop_bytes = 4;
    static constexpr std::size_t frame_header_bytes = crop_bytes + 1;
    static constexpr std::size_t palette_bytes = 512;
    static constexpr int bob_limit = 3;

    struct Crop
    {
        std::size_t x, y, width, height;
    };

    [[nodiscard]] Crop crop_at(std::size_t offset) const
    {
        return {bytes_[offset], bytes_[offset + 1], bytes_[offset + 2], bytes_[offset + 3]};
    }

    [[nodiscard]] std::size_t frame_offset(std::size_t frame) const
    {
        if (frame > frame_offsets_.size())
        {
            fail("X2 weapon frame is outside the asset");
        }
        return frame_offsets_[frame - 1];
    }

    std::vector<std::uint8_t> bytes_;
    std::size_t pose_count_{};
    std::size_t pose_stride_{};
    std::size_t idle_offset_{};
    std::size_t scene_palette_offset_{};
    std::vector<std::size_t> frame_offsets_;
};

} // namespace quake_bsp_reference
