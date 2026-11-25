#pragma once

#include "gameplay.hpp"

namespace quake_bsp_reference {

// Render WinQuake's original 320x200 layout on the active console viewport.
// Source qpics are immutable original palette indices. Only the title is opaque.
inline void draw_intermission(std::vector<std::uint8_t>& screen, std::span<const std::uint8_t> file,
    const std::array<std::uint16_t, 5>& stats, int width, int height)
{
    struct Picture
    {
        unsigned width, height;
        std::span<const std::uint8_t> pixels;
    };
    if (file.size() < 4 || std::string_view(reinterpret_cast<const char*>(file.data()), 4) != "QIM1")
        fail("missing E1M1 intermission qpics");
    std::vector<Picture> pictures;
    for (std::size_t offset = 4; offset < file.size();)
    {
        if (file.size() - offset < 4)
            fail("truncated intermission qpic header");
        const unsigned w = file[offset] | (unsigned(file[offset+1]) << 8);
        const unsigned h = file[offset+2] | (unsigned(file[offset+3]) << 8);
        offset += 4;
        const auto count = std::size_t(w) * h;
        if (!w || !h || count > file.size() - offset)
            fail("truncated intermission qpic");
        pictures.push_back({w, h, file.subspan(offset, count)});
        offset += count;
    }
    if (pictures.size() != 14)
        fail("incomplete intermission qpic directory");
    const auto draw = [&](unsigned id, int ox, int oy) {
        const auto& p = pictures.at(id);
        for (int y = (oy * height + 199) / 200; y < ((oy + int(p.height)) * height + 199) / 200; ++y)
            for (int x = (ox * width + 319) / 320; x < ((ox + int(p.width)) * width + 319) / 320; ++x)
            {
                const auto value = p.pixels[std::size_t(y * 200 / height - oy) * p.width + (x * 320 / width - ox)];
                if (id == 0 || value != 255)
                    screen.at(std::size_t(y) * kLogicalWidth + (width == 85 ? width - 1 - x : x)) = value;
            }
    };
    const auto number = [&](int x, int y, unsigned v) {
        const auto s = std::to_string(v);
        const auto digits = std::min<std::size_t>(3, s.size());
        x += int(3 - digits) * 24;
        for (const auto digit : s.substr(s.size() - digits))
        {
            draw(4 + unsigned(digit - '0'), x, y);
            x += 24;
        }
    };
    draw(0, 64, 24);
    draw(1, 0, 56);
    number(160, 64, stats[0] / 60);
    draw(2, 234, 64);
    draw(4 + stats[0] % 60 / 10, 246, 64);
    draw(4 + stats[0] % 10, 266, 64);
    for (int pair = 0; pair < 2; ++pair)
    {
        const int y = 104 + 40 * pair;
        number(160, y, stats[1 + 2 * pair]);
        draw(3, 232, y);
        number(240, y, stats[2 + 2 * pair]);
    }
}

} // namespace quake_bsp_reference
