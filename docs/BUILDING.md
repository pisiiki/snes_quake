# Build SNES Quake

Run these commands from the repository root. The build initializes pinned
dependencies, extracts `third_party/quake106/quake106.zip`, compiles the level,
generates assets and assembles the ROM.

You need **64-bit CPython 3.11–3.14**, Git, CMake and a native C/C++ toolchain.
The hash-locked Python requirements pin NumPy 2.3.5 and Pillow 12.0.0.
**Building this source release requires an AVX2-capable CPU** for level and
asset regeneration. This requirement does not apply to the prebuilt ROM.

## Windows 10/11

Install Visual Studio 2026 C++ build tools with CMake, and MSYS2 UCRT64 with GNU
Make and a C compiler. Put MSYS2's `bash.exe` on `PATH` or set `MSYS2_BASH`.

```powershell
git clone <repository-url>
cd <repository-directory>
python -m venv .venv
& ./.venv/Scripts/python.exe -m pip install --require-hashes -r tools/requirements-build.txt
./build.ps1 -Python ./.venv/Scripts/python.exe
```

## Ubuntu

```sh
sudo apt update
sudo apt install build-essential cmake curl git libarchive-tools ninja-build pkg-config python3 python3-venv tar unzip zip
git clone <repository-url>
cd <repository-directory>
python3 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r tools/requirements-build.txt
PYTHON=.venv/bin/python sh ./build.sh
```

The finished ROM is **`out/snes_quake/quake.sfc`**. Verify an existing build with
`./build.ps1 -Check -Python ./.venv/Scripts/python.exe` or
`PYTHON=.venv/bin/python sh ./build.sh --check`.

Asset regeneration also retains `out/snes_quake/build/modern-bsp/PAK0.PAK`,
the level archive used by the reference renderer.

The build records its exact inputs in
`out/snes_quake/build/release-manifest.json`; check mode verifies that record.
`config/rom-config.json` owns the dependency pins and BSP options.
Production asset profiles live beside it under `config/profiles/`;
vendor patches live under `third_party/patches/`. These are required inputs.

See [run instructions and controls](../README.md#run-the-rom) or
[build the reference renderer](REFERENCE_RENDERER.md).
