#pragma once

#include "instrumentation.hpp"

namespace quake_bsp_reference {

struct GameplayApplicationOptions
{
    fs::path pak;
    std::vector<fs::path> assets;
    std::string initial_map{"start"};
    fs::path script;
    fs::path tape_dir;
    fs::path tape_record_dir;
    fs::path report;
    fs::path output_prefix;
    ReferenceInstrumentationConfig instrumentation;
    bool face_colors{};
    bool no_sound{};
    float sound_volume{0.7F};
};

int run_gameplay_application(const GameplayApplicationOptions& options);

} // namespace quake_bsp_reference
