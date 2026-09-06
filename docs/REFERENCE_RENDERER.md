# Reference renderer

The C++ reference application lets you compare the original level geometry and
lighting with the SNES renderer. Its window includes playback, rendering, sound
and timeline controls.

First [build the ROM and regenerate its assets](BUILDING.md) on an AVX2-capable
machine, using the default build without the qualified-assets option. This
creates the level archive below. From the repository root, use the same Python
environment to build the reference application:

```powershell
./.venv/Scripts/python.exe tools/commands/snes_quake/build_quake_bsp_reference.py
```

On Linux, use `.venv/bin/python` instead. The builder installs the pinned SDL3,
Dear ImGui, CLI11 and JSON dependencies through vcpkg. The application requires
a C++23 compiler; it uses the same native toolchain described in the build guide.

Launch the reference tool with the generated E1M3 level and replay inputs:

```powershell
./out/reference_renderer/release/quake_bsp_reference_renderer.exe `
  --pak out/snes_quake/build/modern-bsp/PAK0.PAK `
  --realtime-demo src/snes_quake/Data/QuakeBSPDemoPrecise.bin `
  --brush-replay src/snes_quake/Data/QuakeBSPBrushReplay.bin `
  --external-bsp-replay src/snes_quake/Data/QuakeBSPExternalModels.bin `
  --external-bsp-models `
  --sound-replay src/snes_quake/Data/QuakeBSPReferenceSoundReplay.bin `
  --alias-assets src/snes_quake/Data `
  --data-dir src/snes_quake/Data `
  --ordered-replay src/snes_quake/Data/QuakeBSPOrderedReplay20Hz.bin `
  --ordered-2hz
```

On Linux, the executable has no `.exe` suffix; use backslashes for shell line
continuations or put the arguments on one line.

Use the window's playback and speed controls to pause or advance, the timeline
to seek, and the checkboxes to compare textures, lighting, moving level objects,
monsters and items. Sound has its own enable and volume controls.

The source is in `src/reference_renderer/`. The executable's `--help` describes
its image-export and replay options; `--self-test` runs its internal checks.
Formatting is available through the CMake `quake_bsp_reference_format` and
`quake_bsp_reference_format_check` targets after configuration.

[Back to the screenshots](../README.md#reference-renderer).
