cmake_minimum_required(VERSION 3.25)

project(quake_bsp_reference_renderer VERSION 0.1.0 LANGUAGES CXX)

set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

find_package(CLI11 CONFIG REQUIRED)
find_package(SDL3 CONFIG REQUIRED)
find_package(imgui CONFIG REQUIRED)
find_package(nlohmann_json CONFIG REQUIRED)

set(REFERENCE_RENDERER_LIBRARIES
    CLI11::CLI11
    SDL3::SDL3
    imgui::imgui
    nlohmann_json::nlohmann_json
)

function(configure_reference_renderer_compile_target target)
    target_compile_features(${target} PRIVATE cxx_std_23)
    target_compile_definitions(${target} PRIVATE SDL_MAIN_HANDLED)
    target_link_libraries(${target} PRIVATE ${REFERENCE_RENDERER_LIBRARIES})

    set_target_properties(${target} PROPERTIES CXX_EXTENSIONS OFF)

    if(MSVC)
        target_compile_options(${target} PRIVATE
            /Brepro
            /EHsc
            /permissive-
            /utf-8
            /W4
            /WX
        )
        target_link_options(${target} PRIVATE /Brepro)
    else()
        target_compile_options(${target} PRIVATE
            -Wall
            -Wextra
            -Wpedantic
            -Werror
        )
    endif()
endfunction()

add_executable(quake_bsp_reference_renderer
    alias_tests.cpp
    aliases.cpp
    application.cpp
    artifacts_options.cpp
    audio.cpp
    brushes.cpp
    external_models.cpp
    external_models_packed.cpp
    geometry.cpp
    instrumentation.cpp
    live_demo.cpp
    ordered_replay.cpp
    packed_brushes.cpp
    report.cpp
    main.cpp
    sky.cpp
    sky_tests.cpp
    tests_reports.cpp
    textured_live.cpp
    turbulence.cpp
    world.cpp
)
configure_reference_renderer_compile_target(quake_bsp_reference_renderer)

if(WIN32)
    target_link_libraries(quake_bsp_reference_renderer PRIVATE advapi32)
endif()

set_target_properties(quake_bsp_reference_renderer PROPERTIES
    RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}"
)

file(GLOB REFERENCE_RENDERER_HEADERS CONFIGURE_DEPENDS
    "${CMAKE_CURRENT_SOURCE_DIR}/*.h"
    "${CMAKE_CURRENT_SOURCE_DIR}/*.hh"
    "${CMAKE_CURRENT_SOURCE_DIR}/*.hpp"
    "${CMAKE_CURRENT_SOURCE_DIR}/*.hxx"
)

file(GLOB REFERENCE_RENDERER_FORMAT_SOURCES CONFIGURE_DEPENDS
    "${CMAKE_CURRENT_SOURCE_DIR}/*.cpp"
)
set(REFERENCE_RENDERER_FORMAT_FILES
    ${REFERENCE_RENDERER_FORMAT_SOURCES}
    ${REFERENCE_RENDERER_HEADERS}
)
list(SORT REFERENCE_RENDERER_FORMAT_FILES)
list(LENGTH REFERENCE_RENDERER_FORMAT_FILES REFERENCE_RENDERER_FORMAT_FILE_COUNT)
message(STATUS
    "Reference renderer formatter inputs: ${REFERENCE_RENDERER_FORMAT_FILE_COUNT}"
)

set(REFERENCE_RENDERER_CONSTEXPR_SPACING_CHECK
    "${CMAKE_CURRENT_BINARY_DIR}/check-inline-constexpr-spacing.cmake"
)
string(CONFIGURE [==[
if(NOT DEFINED REFERENCE_RENDERER_FILES)
    set(REFERENCE_RENDERER_FILES "@REFERENCE_RENDERER_FORMAT_FILES@")
endif()

set(violations)
foreach(path IN LISTS REFERENCE_RENDERER_FILES)
    file(STRINGS "${path}" lines)
    set(previous_inline_constexpr FALSE)
    set(blank_after_inline_constexpr FALSE)
    foreach(line IN LISTS lines)
        string(STRIP "${line}" stripped)
        if(stripped STREQUAL "")
            if(previous_inline_constexpr)
                set(blank_after_inline_constexpr TRUE)
            endif()
        elseif(stripped MATCHES "^inline[ \t]+constexpr.*;")
            if(previous_inline_constexpr AND blank_after_inline_constexpr)
                list(APPEND violations "${path}")
                break()
            endif()
            set(previous_inline_constexpr TRUE)
            set(blank_after_inline_constexpr FALSE)
        else()
            set(previous_inline_constexpr FALSE)
            set(blank_after_inline_constexpr FALSE)
        endif()
    endforeach()
endforeach()

list(LENGTH REFERENCE_RENDERER_FILES file_count)
if(violations)
    list(JOIN violations ", " violation_list)
    message(FATAL_ERROR
        "ERROR inline constexpr spacing: blank lines separate consecutive "
        "declarations in ${violation_list}"
    )
endif()
message(STATUS "PASS inline constexpr spacing: files=${file_count}")
]==] REFERENCE_RENDERER_CONSTEXPR_SPACING_CHECK_CONTENT @ONLY)
file(GENERATE
    OUTPUT "${REFERENCE_RENDERER_CONSTEXPR_SPACING_CHECK}"
    CONTENT "${REFERENCE_RENDERER_CONSTEXPR_SPACING_CHECK_CONTENT}"
)

find_program(REFERENCE_RENDERER_CLANG_FORMAT
    NAMES clang-format clang-format-22
    DOC "Clang-Format executable for the reference renderer"
)
find_program(REFERENCE_RENDERER_PYTHON
    NAMES python python3
    HINTS "$ENV{CONDA_PREFIX}" "$ENV{USERPROFILE}/anaconda3"
    NO_DEFAULT_PATH
    DOC "Python interpreter for reference-renderer workspace tools"
)
if(NOT REFERENCE_RENDERER_PYTHON)
    find_program(REFERENCE_RENDERER_PYTHON
        NAMES python3 python
        DOC "Python interpreter for reference-renderer workspace tools"
    )
endif()
set(REFERENCE_RENDERER_FORMATTER
    "${CMAKE_CURRENT_SOURCE_DIR}/../../tools/commands/snes_quake/format_quake_bsp_reference.py"
)
if(REFERENCE_RENDERER_CLANG_FORMAT AND REFERENCE_RENDERER_PYTHON)
    add_custom_target(quake_bsp_reference_format
        COMMAND
            "${CMAKE_COMMAND}" -E time
            "${REFERENCE_RENDERER_PYTHON}"
            "${REFERENCE_RENDERER_FORMATTER}"
            --clang-format "${REFERENCE_RENDERER_CLANG_FORMAT}"
            --style-file "${CMAKE_CURRENT_SOURCE_DIR}/.clang-format"
            -- ${REFERENCE_RENDERER_FORMAT_FILES}
        DEPENDS
            "${REFERENCE_RENDERER_FORMATTER}"
            "${CMAKE_CURRENT_SOURCE_DIR}/.clang-format"
        WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}"
        COMMENT "Formatting owned reference-renderer C++ files"
        USES_TERMINAL
        VERBATIM
    )
    add_custom_target(quake_bsp_reference_format_check
        COMMAND
            "${CMAKE_COMMAND}" -E time
            "${REFERENCE_RENDERER_PYTHON}"
            "${REFERENCE_RENDERER_FORMATTER}"
            --clang-format "${REFERENCE_RENDERER_CLANG_FORMAT}"
            --style-file "${CMAKE_CURRENT_SOURCE_DIR}/.clang-format"
            --check -- ${REFERENCE_RENDERER_FORMAT_FILES}
        COMMAND
            "${CMAKE_COMMAND}" -E time
            "${CMAKE_COMMAND}" -P
            "${REFERENCE_RENDERER_CONSTEXPR_SPACING_CHECK}"
        WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}"
        COMMENT "Checking owned reference-renderer C++ formatting"
        USES_TERMINAL
        VERBATIM
    )
elseif(REFERENCE_RENDERER_CLANG_FORMAT)
    message(STATUS
        "Reference renderer formatter targets unavailable: Python 3 was not found"
    )
endif()

set(REFERENCE_RENDERER_HEADER_PROBES)
foreach(header IN LISTS REFERENCE_RENDERER_HEADERS)
    file(READ "${header}" header_contents)
    string(FIND "${header_contents}" "\n" first_line_end)
    if(first_line_end EQUAL -1)
        set(first_line "${header_contents}")
    else()
        string(SUBSTRING "${header_contents}" 0 ${first_line_end} first_line)
    endif()
    string(STRIP "${first_line}" first_line)
    if(NOT first_line STREQUAL "#pragma once")
        message(FATAL_ERROR
            "Reference renderer header must begin with #pragma once: ${header}"
        )
    endif()

    file(TO_CMAKE_PATH "${header}" header_include_path)
    string(SHA256 header_hash "${header_include_path}")
    string(SUBSTRING "${header_hash}" 0 12 header_id)
    set(probe_target "quake_bsp_reference_header_${header_id}")
    set(probe_source
        "${CMAKE_CURRENT_BINARY_DIR}/header-probes/${header_id}.cpp"
    )
    file(GENERATE OUTPUT "${probe_source}" CONTENT
        "#include \"${header_include_path}\"\n#include \"${header_include_path}\"\n"
    )

    add_library(${probe_target} OBJECT "${probe_source}")
    configure_reference_renderer_compile_target(${probe_target})
    list(APPEND REFERENCE_RENDERER_HEADER_PROBES ${probe_target})
endforeach()

list(LENGTH REFERENCE_RENDERER_HEADERS REFERENCE_RENDERER_HEADER_COUNT)
message(STATUS
    "Reference renderer standalone header probes: ${REFERENCE_RENDERER_HEADER_COUNT}"
)

add_custom_target(quake_bsp_reference_header_checks ALL)
if(REFERENCE_RENDERER_HEADER_PROBES)
    add_dependencies(
        quake_bsp_reference_header_checks
        ${REFERENCE_RENDERER_HEADER_PROBES}
    )
endif()
