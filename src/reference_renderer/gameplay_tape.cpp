#include "gameplay_tape.hpp"

namespace quake_bsp_reference {
namespace {
constexpr std::string_view tape_schema = "quake-gameplay-tape-v1";
constexpr auto buttons = std::to_array<std::string_view>(
    {"B", "Y", "Select", "Start", "Up", "Down", "Left", "Right", "A", "X", "L", "R"}
);

GameplayInput legacy_input(const Json& hold)
{
    const auto& held = hold.at("buttons");
    if (hold.at("clock") != "video" || !held.is_array())
        fail("legacy holds require video clocks and a button array");
    GameplayInput input;
    for (const auto& button : held)
    {
        const auto name = button.get<std::string>();
        const auto found = std::ranges::find(buttons, name);
        if (found == buttons.end())
            fail("unknown SNES button " + name);
        const auto bit = static_cast<std::uint16_t>(0x8000U >> (found - buttons.begin()));
        if (input.joypad & bit)
            fail("duplicate SNES button " + name);
        input.joypad |= bit;
    }
    return input;
}
} // namespace

void GameplayTape::append(const GameplayInput& input)
{
    if (ticks == max_ticks)
        fail("gameplay tape reached its video tick limit");
    if (!holds.empty() && holds.back().input == input)
        ++holds.back().ticks;
    else
        holds.push_back({1, input});
    ++ticks;
}

GameplayTape parse_gameplay_tape(const Json& value, std::string_view legacy_map)
{
    GameplayTape tape;
    const bool legacy = value.is_array();
    if (legacy)
    {
        if (legacy_map.empty())
            fail("a legacy tape requires a map from its filename");
        tape.map = legacy_map;
    }
    else
    {
        if (!value.is_object() || value.at("schema").get<std::string>() != tape_schema || value.at("clock") != "video")
            fail("unsupported gameplay tape format");
        tape.map = value.at("initialMap").get<std::string>();
        const auto& skill = value.at("skill");
        if (tape.map.empty() || !skill.is_number_integer() || skill < 0 || skill > 3 ||
            !value.at("alwaysRun").is_boolean())
            fail("invalid gameplay tape start settings");
        tape.skill = skill.get<std::uint8_t>();
        tape.always_run = value.at("alwaysRun").get<bool>();
    }
    const auto& holds = legacy ? value : value.at("holds");
    if (!holds.is_array() || holds.empty())
        fail("expected a nonempty array of input holds");
    tape.finish_level = legacy && holds.back().value("label", "") == "finish-" + tape.map;
    for (const auto& hold : holds)
    {
        const auto& ticks = hold.at("ticks");
        if (!ticks.is_number_integer() || ticks <= 0 || ticks > GameplayTape::max_ticks - tape.ticks)
            fail("each hold needs positive video ticks within the tape limit");
        const auto duration = ticks.get<unsigned>();
        const auto input = legacy ? legacy_input(hold) : gameplay_input_from_json(hold.at("input"));
        tape.holds.push_back({duration, input});
        tape.ticks += duration;
    }
    return tape;
}

GameplayTape read_gameplay_tape(const fs::path& path, std::string_view legacy_map)
{
    try
    {
        const auto bytes = read_file(path);
        auto tape = parse_gameplay_tape(Json::parse(bytes.begin(), bytes.end()), legacy_map);
        tape.path = path;
        return tape;
    }
    catch (const std::exception& error)
    {
        fail("cannot load gameplay tape " + path.string() + ": " + error.what());
    }
}

Json gameplay_tape_json(const GameplayTape& tape)
{
    Json holds = Json::array();
    for (const auto& [ticks, input] : tape.holds)
        holds.push_back({{"ticks", ticks}, {"input", {
            {"joypad", input.joypad}, {"mouseDx", input.mouse_dx}, {"mouseDy", input.mouse_dy},
            {"mouseButtons", input.mouse_buttons}, {"mouseConnected", input.mouse_connected},
            {"cycleWeapon", input.cycle_weapon}
        }}});
    return {{"schema", tape_schema}, {"clock", "video"}, {"initialMap", tape.map}, {"skill", tape.skill},
            {"alwaysRun", tape.always_run}, {"holds", std::move(holds)}};
}

fs::path save_gameplay_tape(const fs::path& directory, const GameplayTape& tape)
{
    const auto folder = fs::absolute(directory);
    fs::create_directories(folder);
    const auto text = gameplay_tape_json(tape).dump(2) + "\n";
    const auto stamp = std::chrono::duration_cast<std::chrono::milliseconds>(
        std::chrono::system_clock::now().time_since_epoch()).count();
    for (unsigned suffix = 0; ; ++suffix)
    {
        const auto name = std::to_string(stamp) + "-" + std::to_string(suffix);
        const auto path = folder / (name + ".gameplay-tape.json");
        const auto temporary = folder / (name + ".gameplay-tape.tmp");
        if (fs::exists(path))
            continue;
        std::ofstream stream(temporary, std::ios::binary | std::ios::noreplace);
        if (!stream && fs::exists(temporary))
            continue;
        if (!stream)
            fail("cannot create gameplay tape in " + folder.string());
        try
        {
            stream.write(text.data(), static_cast<std::streamsize>(text.size()));
            stream.close();
            if (!stream)
                fail("cannot write gameplay tape in " + folder.string());
            if (!fs::exists(path))
            {
                fs::rename(temporary, path);
                return path;
            }
            fs::remove(temporary);
        }
        catch (...)
        {
            std::error_code ignored;
            fs::remove(temporary, ignored);
            throw;
        }
    }
}

} // namespace quake_bsp_reference
