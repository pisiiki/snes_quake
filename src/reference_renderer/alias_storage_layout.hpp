#pragma once

#include "aliases.hpp"

namespace quake_bsp_reference {

inline bool is_level_alias_metadata(const Json& metadata)
{
    const auto schema = metadata.at("schema").get<std::string>();
    if (schema != "quake-bsp-billboards-v8" && schema != "quake-level-alias-assets-v1")
        fail("unsupported alias asset metadata schema: " + schema);
    return schema == "quake-level-alias-assets-v1";
}

inline std::vector<std::pair<std::uint8_t, std::uint16_t>> alias_storage_layout(
    const std::optional<Json>& metadata, std::size_t chunk_count
)
{
    if (chunk_count == 0 || (!metadata && chunk_count > kAliasStorageLocations.size()))
        fail("QBA1 alias halfbank count is invalid");
    if (!metadata)
        return {kAliasStorageLocations.begin(), kAliasStorageLocations.begin() + chunk_count};
    is_level_alias_metadata(*metadata);
    const auto& format = metadata->at("format");
    const auto& physical = format.at("storagePhysicalHalfbanks");
    if (!physical.is_array() || physical.size() < chunk_count || physical.size() > 128 ||
        format.at("chunkCount").get<std::size_t>() != chunk_count)
        fail("QBA1 declared halfbank map disagrees with its package");
    std::set<int> seen;
    std::vector<std::pair<std::uint8_t, std::uint16_t>> result;
    for (const auto& value : physical)
    {
        if (!value.is_number_integer() || value.get<std::int64_t>() < 0 || value.get<std::int64_t>() > 127)
            fail("QBA1 physical halfbank escapes its address domain");
        const auto bank = value.get<int>();
        if (!seen.insert(bank).second)
            fail("QBA1 physical halfbank map contains a duplicate");
        if (result.size() < chunk_count)
        {
            const auto gsu_bank = bank < 64 ? bank : 0x60 + (bank - 64) / 2;
            const auto address = bank < 64 || (bank & 1) ? 0x8000 : 0;
            result.emplace_back(static_cast<std::uint8_t>(gsu_bank), static_cast<std::uint16_t>(address));
        }
    }
    return result;
}

} // namespace quake_bsp_reference
