#pragma once

#include "world.hpp"

namespace quake_bsp_reference {

struct PackedMaterialStreams
{
    std::vector<std::uint8_t> coordinates;
    std::vector<std::uint8_t> pixels;
};

template <class Reader>
std::vector<std::uint8_t> read_material_chunk_family(
    const Json& exact,
    std::string_view field,
    std::string_view total_field,
    std::string_view prefix,
    std::size_t maximum_chunks,
    const std::vector<std::string>& available,
    Reader&& reader
)
{
    constexpr std::size_t bank_bytes = 32768;
    const auto& chunks = exact.at(std::string(field));
    if (!chunks.is_array() || chunks.empty() || chunks.size() > maximum_chunks)
        fail("packed material chunk count is invalid: " + std::string(field));
    const auto& total_value = exact.at(std::string(total_field));
    if (!total_value.is_number_integer() || total_value.get<std::int64_t>() < 1 ||
        total_value.get<std::uint64_t>() > maximum_chunks * bank_bytes)
        fail("packed material byte total is invalid: " + std::string(total_field));
    const auto required_bytes = total_value.get<std::size_t>();
    std::vector<std::size_t> sizes;
    std::set<std::string> declared;
    std::size_t declared_bytes = 0;
    std::optional<std::int64_t> first_bank;
    for (std::size_t index = 0; index < chunks.size(); ++index)
    {
        const auto& chunk = chunks.at(index);
        const auto name = std::string(prefix) + std::to_string(index) + ".bin";
        const auto& byte_value = chunk.at("bytes");
        const auto& bank_value = chunk.at("gsu_rom_bank");
        if (!chunk.at("file").is_string() || chunk.at("file").get<std::string>() != name ||
            !byte_value.is_number_integer() || byte_value.get<std::int64_t>() < 0 ||
            byte_value.get<std::uint64_t>() > bank_bytes || !bank_value.is_number_integer() ||
            bank_value.get<std::int64_t>() < 0 || bank_value.get<std::int64_t>() > 127)
            fail("packed material chunk declaration is invalid: " + name);
        const auto bank = bank_value.get<std::int64_t>();
        if (!first_bank)
            first_bank = bank;
        if (bank != *first_bank + static_cast<std::int64_t>(index))
            fail("packed material chunk banks are not contiguous: " + name);
        sizes.push_back(byte_value.get<std::size_t>());
        declared_bytes += sizes.back();
        declared.insert(name);
    }
    if (declared_bytes != required_bytes)
        fail("packed material chunks disagree with their declared byte total");
    for (const auto& name : available)
        if (name.starts_with(prefix) && name.ends_with(".bin") && !declared.contains(name))
            fail("unexpected undeclared packed material chunk: " + name);
    std::vector<std::uint8_t> result;
    result.reserve(required_bytes);
    for (std::size_t index = 0; index < chunks.size(); ++index)
    {
        const auto name = std::string(prefix) + std::to_string(index) + ".bin";
        const auto next = reader(name, sizes[index]);
        if (next.size() != sizes[index])
            fail("packed material chunk byte count differs from metadata: " + name);
        result.insert(result.end(), next.begin(), next.end());
    }
    return result;
}

template <class Reader>
PackedMaterialStreams read_packed_material_streams(
    const Json& metadata, const std::vector<std::string>& available, Reader&& reader
)
{
    const auto& exact = metadata.at("world").at("packing").at("exact_textures");
    return {
        read_material_chunk_family(exact, "coordinate_chunks", "coordinate_bytes",
                                   "QuakeBSPWorldTextureCoordinates", 4, available, reader),
        read_material_chunk_family(exact, "pixel_chunks", "stored_pixel_bytes",
                                   "QuakeBSPWorldTexturePixels", 12, available, reader),
    };
}

} // namespace quake_bsp_reference
