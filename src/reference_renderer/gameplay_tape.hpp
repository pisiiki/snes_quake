#pragma once

#include "gameplay.hpp"

namespace quake_bsp_reference {

struct GameplayTapeHold
{
    unsigned ticks{};
    GameplayInput input;
};

struct GameplayTape
{
    static constexpr unsigned max_ticks = 1'000'000;

    std::string map;
    std::uint8_t skill{1};
    bool always_run{true};
    bool finish_level{};
    std::vector<GameplayTapeHold> holds;
    unsigned ticks{};
    fs::path path;

    void append(const GameplayInput& input);
};

GameplayTape read_gameplay_tape(const fs::path& path, std::string_view legacy_map = {});
GameplayTape parse_gameplay_tape(const Json& value, std::string_view legacy_map = {});
Json gameplay_tape_json(const GameplayTape& tape);
fs::path save_gameplay_tape(const fs::path& directory, const GameplayTape& tape);

} // namespace quake_bsp_reference
