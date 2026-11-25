# SNES Quake reference renderer

The desktop reference engine renders Quake and runs the port's gameplay rules.

## Build

Install Git, Python 3.13, CMake 3.25 or later, Ninja, and a C++23 compiler.
On Windows, install the Visual Studio C++ desktop workload. On Linux, install
your distribution's development libraries for X11, Wayland, EGL, XKB and IBus
for SDL3. The build fetches the pinned vcpkg dependencies.

From the repository root, run the build and then the renderer's self-test.

```sh
python tools/commands/snes_quake/build_quake_bsp_reference.py
out/reference_renderer/release/quake_bsp_reference_renderer --self-test
```

On Windows, append `.exe` to `quake_bsp_reference_renderer`.

## Run gameplay

The standalone cartridge build extracts `out/shareware/PAK0.PAK` from the
included ZIP. Use that PAK and the generated build report to prepare the
reference engine's gameplay inputs.

```sh
python build.py
python tools/commands/snes_quake/recover_quake_gameplay_aliases.py --snes-package out/snes_quake/playable/snes_quake-build.json --output out/reference_renderer/production-render-assets
python tools/commands/snes_quake/export_quake_gameplay_assets.py --pak out/shareware/PAK0.PAK --production-aliases out/reference_renderer/production-render-assets/production-aliases.json --output out/reference_renderer/gameplay-assets
out/reference_renderer/release/quake_bsp_reference_renderer --gameplay --pak out/shareware/PAK0.PAK --gameplay-assets out/reference_renderer/gameplay-assets/gameplay-maps.json --gameplay-map start
```

If you build the cartridge with `--pak`, use that same PAK path for the
reference asset export and renderer.

Use **Record tape** (F7) and **Play tape** (F6) in the gameplay window.
Pass `--gameplay-record-dir out/reference_renderer/gameplay-tapes` to save and
replay recordings from that directory. To compare with the ROM, use the same
tape, map, difficulty, and renderer settings on both sides.

