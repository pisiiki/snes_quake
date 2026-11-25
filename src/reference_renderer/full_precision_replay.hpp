#pragma once

#include "geometry.hpp"
#include "brushes.hpp"

namespace quake_bsp_reference {

struct SourceEntityTransform
{
    Vec3 origin;
    std::array<double, 3> angles;
    std::string model;
    int frame{};
};

using SourceEntityTransforms = std::map<int, SourceEntityTransform>;

struct FullPrecisionReplay
{
    struct Row
    {
        SourceCamera camera;
        SourceEntityTransforms entities;
    };

    std::vector<Row> rows;
    SourceEntityTransforms static_entities;
    SourceEntityTransforms baselines;
    std::vector<std::vector<int>> packed_alias_ids;

    [[nodiscard]] const SourceEntityTransform* last_observed(std::size_t pose, int id) const
    {
        for (std::size_t end = pose + 1; end != 0; --end)
        {
            const auto& entities = rows.at(end - 1).entities;
            if (const auto found = entities.find(id); found != entities.end())
                return &found->second;
        }
        return nullptr;
    }

    [[nodiscard]] const SourceEntityTransform* entity(std::size_t pose, int id, bool is_static, bool fly) const
    {
        const auto& entities = is_static ? static_entities : rows.at(pose).entities;
        if (const auto found = entities.find(id); found != entities.end())
            return &found->second;
        if (fly && !is_static)
        {
            if (const auto found = baselines.find(id); found != baselines.end())
                return &found->second;
            if (const auto found = static_entities.find(id); found != static_entities.end())
                return &found->second;
        }
        return nullptr;
    }
};

inline FullPrecisionReplay
load_full_precision_replay(const fs::path& path, const fs::path& track, const BrushReplay& brushes)
{
    const auto document = Json::parse(read_file(path));
    const auto camera_identity = document.at("cameraTrackFnv1a64").get<std::string>();
    if (document.at("schema") != "quake-reference-precision-v1" || camera_identity.size() != 16 ||
        camera_identity.find_first_not_of("0123456789abcdef") != std::string::npos ||
        std::stoull(camera_identity, nullptr, 16) != brush_fnv1a64(read_file(track)) ||
        document.at("sampleRate") != brushes.sample_rate ||
        document.at("firstServerTime").get<double>() != brushes.first_server_time)
    {
        fail("full precision replay does not match the camera and brush tracks");
    }
    const auto transform = [](const Json& row, std::size_t first, std::size_t size) {
        if (!row.is_array() || row.size() != size)
            fail("full precision replay has an invalid transform");
        std::array<double, 6> values{};
        for (std::size_t i = 0; i < values.size(); ++i)
        {
            values[i] = row.at(first + i).get<double>();
            if (!std::isfinite(values[i]))
                fail("full precision replay has a non-finite transform");
        }
        return SourceEntityTransform{{values[0], values[1], values[2]}, {values[3], values[4], values[5]}, {}};
    };
    const auto entities = [&](const Json& records) {
        if (!records.is_array())
            fail("full precision replay has an invalid entity list");
        SourceEntityTransforms result;
        for (const auto& record : records)
        {
            auto source = transform(record, 1, 9);
            source.model = record.at(7).get<std::string>();
            source.frame = record.at(8).get<int>();
            if (!record.at(0).is_number_integer() || !result.emplace(record.at(0).get<int>(), std::move(source)).second)
                fail("full precision replay has an invalid or duplicate entity identity");
        }
        return result;
    };
    FullPrecisionReplay result;
    const auto& rows = document.at("rows");
    if (!rows.is_array() || rows.size() != brushes.row_count())
        fail("full precision replay has the wrong number of rows");
    result.rows.reserve(rows.size());
    for (const auto& row : rows)
    {
        if (!row.is_array() || row.size() != 2)
            fail("full precision replay has an invalid row");
        const auto camera = transform(row.at(0), 0, 6);
        result.rows.push_back(
            {{camera.origin, camera.angles[0], camera.angles[1], camera.angles[2]}, entities(row.at(1))}
        );
    }
    result.static_entities = entities(document.at("staticEntities"));
    result.baselines = entities(document.at("baselines"));
    return result;
}

} // namespace quake_bsp_reference
