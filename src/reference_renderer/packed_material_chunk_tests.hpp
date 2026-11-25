#pragma once

#include "packed_material_chunks.hpp"

namespace quake_bsp_reference {

inline bool run_packed_material_chunk_self_test()
{
    struct Fixture
    {
        Json metadata;
        std::map<std::string, std::vector<std::uint8_t>> files;
        std::vector<std::string> available;
        std::size_t reads = 0;
        PackedMaterialStreams load()
        {
            return read_packed_material_streams(metadata, available, [&](const auto& name, std::size_t) {
                ++reads;
                return files.at(name);
            });
        }
    };
    const auto fixture = [](int coordinate_count, int pixel_count) {
        Fixture result;
        auto& exact = result.metadata["world"]["packing"]["exact_textures"];
        for (const auto& [prefix, field, total, count, base] : {
                 std::tuple{"QuakeBSPWorldTextureCoordinates", "coordinate_chunks", "coordinate_bytes",
                            coordinate_count, 59},
                 std::tuple{"QuakeBSPWorldTexturePixels", "pixel_chunks", "stored_pixel_bytes", pixel_count, 26}})
        {
            exact[field] = Json::array();
            exact[total] = count * 4;
            for (int index = 0; index < count; ++index)
            {
                const auto name = std::string(prefix) + std::to_string(index) + ".bin";
                exact[field].push_back(Json{{"file", name}, {"bytes", 4}, {"gsu_rom_bank", base + index}});
                result.files[name] = std::vector<std::uint8_t>(4, static_cast<std::uint8_t>(index + 1));
                result.available.push_back(name);
            }
        }
        return result;
    };
    for (const auto& [coordinate_count, pixel_count] : {std::pair{3, 6}, std::pair{4, 11}, std::pair{4, 12}})
    {
        auto sample = fixture(coordinate_count, pixel_count);
        const auto streams = sample.load();
        if (streams.coordinates.size() != static_cast<std::size_t>(coordinate_count * 4) ||
            streams.pixels.size() != static_cast<std::size_t>(pixel_count * 4) ||
            sample.reads != static_cast<std::size_t>(coordinate_count + pixel_count))
            return false;
        for (std::size_t index = 0; index < streams.coordinates.size(); ++index)
            if (streams.coordinates[index] != static_cast<std::uint8_t>(index / 4 + 1))
                return false;
        for (std::size_t index = 0; index < streams.pixels.size(); ++index)
            if (streams.pixels[index] != static_cast<std::uint8_t>(index / 4 + 1))
                return false;
    }
    const auto rejects = [](auto sample) {
        try { sample.load(); }
        catch (const std::exception&) { return true; }
        return false;
    };
    auto too_many = fixture(4, 13);
    if (!rejects(too_many) || too_many.reads != 0) return false;
    auto empty_tail = fixture(4, 11);
    auto& empty_exact = empty_tail.metadata["world"]["packing"]["exact_textures"];
    empty_exact["coordinate_chunks"][2]["bytes"] = 2;
    empty_exact["coordinate_chunks"][3]["bytes"] = 0;
    empty_exact["coordinate_bytes"] = 10;
    empty_tail.files["QuakeBSPWorldTextureCoordinates2.bin"].resize(2);
    empty_tail.files["QuakeBSPWorldTextureCoordinates3.bin"].clear();
    const auto partial_streams = empty_tail.load();
    if (partial_streams.coordinates != std::vector<std::uint8_t>{1, 1, 1, 1, 2, 2, 2, 2, 3, 3})
        return false;
    empty_tail.files.erase("QuakeBSPWorldTextureCoordinates3.bin");
    if (!rejects(empty_tail)) return false;
    auto missing = fixture(4, 11);
    missing.files.erase("QuakeBSPWorldTextureCoordinates3.bin");
    if (!rejects(missing)) return false;
    auto short_file = fixture(4, 11);
    short_file.files["QuakeBSPWorldTexturePixels10.bin"].pop_back();
    if (!rejects(short_file)) return false;
    auto oversized = fixture(4, 11);
    oversized.metadata["world"]["packing"]["exact_textures"]["coordinate_chunks"][0]["bytes"] = 32769;
    if (!rejects(oversized)) return false;
    auto escaped = fixture(4, 11);
    escaped.metadata["world"]["packing"]["exact_textures"]["coordinate_chunks"][0]["file"] = "../outside.bin";
    if (!rejects(escaped)) return false;
    auto duplicate = fixture(4, 11);
    duplicate.metadata["world"]["packing"]["exact_textures"]["pixel_chunks"][1]["file"] =
        "QuakeBSPWorldTexturePixels0.bin";
    if (!rejects(duplicate)) return false;
    auto extra = fixture(3, 6);
    extra.available.push_back("QuakeBSPWorldTexturePixels6.bin");
    if (!rejects(extra)) return false;
    auto total = fixture(4, 11);
    total.metadata["world"]["packing"]["exact_textures"]["stored_pixel_bytes"] = 1;
    if (!rejects(total)) return false;
    auto banks = fixture(4, 11);
    banks.metadata["world"]["packing"]["exact_textures"]["pixel_chunks"][3]["gsu_rom_bank"] = 50;
    if (!rejects(banks)) return false;
    return true;
}

} // namespace quake_bsp_reference
