#pragma once

#include "alias_storage_layout.hpp"

namespace quake_bsp_reference {

inline bool run_alias_storage_loader_self_test()
{
    const auto base = fs::temp_directory_path();
    const auto name = "quake-alias-loader-" +
        std::to_string(std::chrono::steady_clock::now().time_since_epoch().count());
    const auto root = base / name;
    if (!fs::create_directory(root))
        fail("cannot reserve alias-loader fixture directory");
    struct Cleanup
    {
        fs::path root, base;
        ~Cleanup()
        {
            if (root.parent_path() == base && root.filename().string().starts_with("quake-alias-loader-"))
            {
                std::error_code error;
                fs::remove_all(root, error);
            }
        }
    } cleanup{root, base};
    const auto write = [](const fs::path& path, const std::vector<std::uint8_t>& bytes) {
        std::ofstream output(path, std::ios::binary);
        output.write(reinterpret_cast<const char*>(bytes.data()), static_cast<std::streamsize>(bytes.size()));
        if (!output) fail("cannot write alias-loader fixture");
    };
    const auto fixture = [&](std::string_view label, bool sprite) {
        const auto directory = root / label;
        fs::create_directory(directory);
        std::vector<std::uint8_t> bytes(kAliasHalfbankBytes);
        const auto word = [&](std::size_t at, std::uint16_t value) {
            bytes[at] = static_cast<std::uint8_t>(value);
            bytes[at + 1] = static_cast<std::uint8_t>(value >> 8);
        };
        bytes[0] = 'Q'; bytes[1] = 'B'; bytes[2] = 'A'; bytes[3] = '1';
        word(4, 6); word(6, 44); word(8, 8); word(10, sprite ? 1 : 0);
        word(18, 1); word(20, 44); word(24, 108); word(28, 122);
        if (sprite)
        {
            bytes[108] = 0x61; // Physical halfbank 66, unlike legacy chunk0.
            word(110, 512);
            bytes[112] = 1; bytes[113] = 1; bytes[114] = 1; bytes[115] = 1;
            bytes[512] = 18; // Encoded canonical texel17; no actor states.
        }
        write(directory / "QuakeBSPAliasRuntime0.bin", bytes);
        Json metadata{{"schema", "quake-level-alias-assets-v1"},
            {"format", {{"storagePhysicalHalfbanks", Json::array({66})}, {"chunkCount", 1},
                         {"flyFacingRecordCount", 0}, {"flyFacingPackageOffset", 128}}},
            {"instrumentation", {{"modelNames", sprite ? Json::array({"progs/fixture.mdl"}) : Json::array()}}}};
        std::ofstream(directory / "QuakeBSPAliasAssets.json") << metadata.dump();
        return std::pair{directory, metadata};
    };
    const auto [empty_directory, empty_metadata] = fixture("empty", false);
    const auto empty = load_alias_assets(empty_directory);
    if (!empty.sprites.empty() || empty.rows.size() != 8 ||
        std::ranges::any_of(empty.rows, [](const auto& row) { return !row.dynamic_states.empty() || !row.tokens.empty(); }))
        return false;
    const auto [directory, metadata] = fixture("relocated", true);
    const auto relocated = load_alias_assets(directory);
    if (relocated.sprites.size() != 1 || relocated.sprites[0].pixels != std::vector<std::uint8_t>{17})
        return false;
    const auto rejects = [&](Json invalid) {
        std::ofstream(directory / "QuakeBSPAliasAssets.json") << invalid.dump();
        try { load_alias_assets(directory); }
        catch (const std::exception&) { return true; }
        return false;
    };
    auto duplicate = metadata;
    duplicate["format"]["storagePhysicalHalfbanks"] = Json::array({66, 66});
    if (!rejects(duplicate)) return false;
    auto outside = metadata;
    outside["format"]["storagePhysicalHalfbanks"] = Json::array({128});
    if (!rejects(outside)) return false;
    auto unknown = metadata;
    unknown["schema"] = "unknown";
    if (!rejects(unknown)) return false;
    auto facing = metadata;
    facing["format"]["flyFacingRecordBytes"] = 4;
    if (!rejects(facing)) return false;
    // Level animation rows are all live directional states, including rows
    // preceding the final eight camera-facing defaults.
    const auto directional_directory = root / "directional";
    fs::create_directory(directional_directory);
    std::vector<std::uint8_t> directional_bytes(kAliasHalfbankBytes);
    const auto directional_word = [&](std::size_t at, std::uint16_t value) {
        directional_bytes[at] = static_cast<std::uint8_t>(value);
        directional_bytes[at + 1] = static_cast<std::uint8_t>(value >> 8);
    };
    directional_bytes[0] = 'Q'; directional_bytes[1] = 'B';
    directional_bytes[2] = 'A'; directional_bytes[3] = '1';
    directional_word(4, 6); directional_word(6, 44); directional_word(8, 87);
    directional_word(10, 632); directional_word(14, 1); directional_word(16, 1);
    directional_word(18, 1); directional_word(20, 44); directional_word(24, 740);
    directional_word(28, 9588);
    for (std::size_t row = 0; row < 87; ++row)
    {
        const auto frame = row < 79 ? row : 0;
        const auto at = 44 + row * 8;
        directional_bytes[at] = 0x61; directional_bytes[at + 1] = 1;
        directional_word(at + 2, static_cast<std::uint16_t>(9600 + frame * 8));
        directional_bytes[at + 4] = 0x61; directional_bytes[at + 5] = 1;
        directional_word(at + 6, static_cast<std::uint16_t>(10240 + frame * 6));
    }
    for (std::size_t frame = 0; frame < 79; ++frame)
    {
        directional_word(9600 + frame * 8, static_cast<std::uint16_t>(kAliasDirectionalTag | (frame * 8)));
        directional_word(10240 + frame * 6 + 2, 0xffff);
        directional_bytes[10240 + frame * 6 + 4] = 1;
        for (std::size_t view = 0; view < 8; ++view)
        {
            const auto sprite = frame * 8 + view;
            const auto at = 740 + sprite * 14;
            directional_bytes[at] = 0x61;
            directional_word(at + 2, static_cast<std::uint16_t>(11000 + sprite));
            directional_bytes[at + 4] = 1; directional_bytes[at + 5] = 1;
            directional_bytes[at + 6] = 1; directional_bytes[at + 7] = 1;
            directional_bytes[at + 8] = static_cast<std::uint8_t>(frame < 29 ? frame : frame + 11);
            directional_bytes[at + 9] = static_cast<std::uint8_t>(view);
            directional_bytes[11000 + sprite] = static_cast<std::uint8_t>(18 + view);
        }
    }
    directional_bytes[10720] = 0x80;
    auto directional_metadata = metadata;
    directional_metadata["format"]["flyFacingRecordCount"] = 1;
    directional_metadata["format"]["flyFacingPackageOffset"] = 10720;
    write(directional_directory / "QuakeBSPAliasRuntime0.bin", directional_bytes);
    std::ofstream(directional_directory / "QuakeBSPAliasAssets.json") << directional_metadata.dump();
    const auto directional = load_alias_assets(directional_directory);
    if (directional.rows.size() != 87 || directional.sprites.size() != 632)
        return false;
    for (std::size_t row = 0; row < directional.rows.size(); ++row)
    {
        const auto frame = row < 79 ? row : 0;
        const auto& states = directional.rows[row].dynamic_states;
        if (states.size() != 1 || states[0].yaw_sin_q6 != -128 || states[0].yaw_cos_q6 != 0 ||
            states[0].sprite != static_cast<std::uint16_t>(kAliasDirectionalTag | (frame * 8)))
            return false;
    }
    auto legacy_directional = directional_metadata;
    legacy_directional["schema"] = "quake-bsp-billboards-v8";
    std::ofstream(directional_directory / "QuakeBSPAliasAssets.json") << legacy_directional.dump();
    bool legacy_rejected = false;
    try { load_alias_assets(directional_directory); }
    catch (const std::exception& error)
    {
        legacy_rejected = std::string(error.what()).find("state names an invalid sprite range") != std::string::npos;
    }
    if (!legacy_rejected) return false;
    const auto legacy = alias_storage_layout(std::nullopt, kAliasStorageLocations.size());
    return std::ranges::equal(legacy, kAliasStorageLocations);
}

} // namespace quake_bsp_reference
