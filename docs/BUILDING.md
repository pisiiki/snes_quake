# Build instructions

Clone the [SNES Quake repository](https://github.com/pisiiki/snes_quake) using the commands below.

Run these commands from the repository root. The build initializes pinned
dependencies, generates assets and assembles the ROM. It extracts
`third_party/quake106/quake106.zip`, compiles the level and regenerates assets.

You need **64-bit CPython 3.11–3.14**, Git, CMake and a native C/C++ toolchain.
The hash-locked Python requirements pin NumPy 2.3.5 and Pillow 12.0.0.
The x64 lighting baseline is SSE2; AVX2 is not required. The build also compiles
the reference renderer to generate the visibility data from source.

## Windows 10/11

Install Visual Studio 2026 C++ build tools with CMake, and MSYS2 UCRT64 with GNU
Make and a C compiler. Put MSYS2's `bash.exe` on `PATH` or set `MSYS2_BASH`.

```powershell
git clone https://github.com/pisiiki/snes_quake.git
cd snes_quake
python -m venv .venv
& ./.venv/Scripts/python.exe -m pip install --require-hashes -r tools/requirements-build.txt
./build.ps1 -Python ./.venv/Scripts/python.exe
```

## Ubuntu

```sh
sudo apt update
sudo apt install build-essential cmake curl git libarchive-tools ninja-build pkg-config python3 python3-venv tar unzip zip
git clone https://github.com/pisiiki/snes_quake.git
cd snes_quake
python3 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r tools/requirements-build.txt
PYTHON=.venv/bin/python sh ./build.sh
```

The finished ROM is **`out/snes_quake/quake.sfc`**. Verify an existing build with
`./build.ps1 -Check -Python ./.venv/Scripts/python.exe` or
`PYTHON=.venv/bin/python sh ./build.sh --check`.

Asset regeneration also retains `out/snes_quake/build/modern-bsp/PAK0.PAK`,
the level archive used by the reference renderer.

## Generation provenance and local reuse

The release contains no extracted Quake game data, generated runtime assets or
prebuilt ROMs. It retains the untouched shareware ZIP and README screenshots.
The build generates every file in `src/snes_quake/Data/` locally. The qualified
file list, byte counts and SHA-256 hashes are recorded in
`src/snes_quake/generated-assets.json`, bound to the release configuration and
qualified ROM. No earlier build or development workspace files are needed.
After a successful local build you can reuse those local outputs explicitly:

```powershell
./build.ps1 -QualifiedAssets -Python ./.venv/Scripts/python.exe
```

```sh
PYTHON=.venv/bin/python sh ./build.sh --qualified-assets
```

Missing, stale, extra or corrupted assets stop this build before assembly.
`src/snes_quake/asset-generation.json` binds the actual lightmap recipe, tool and
dependency identities, effective ISA, settings and resulting output hashes.
Changing the recipe triggers renewed qualification by exact asset/ROM comparison.
Different bytes stop the release build with a requalification-required diagnostic;
the receipt retains the candidate recipe and failure. Identical bytes receive a
new equivalence receipt bound to the existing behavioral evidence.
Checkout paths and elapsed times are excluded from the generation fingerprint.
`src/snes_quake/generated-assets.json` retains the qualified baseline recipe,
so a fresh build can compare its actual recipe without shipping lightmap bytes.
Local reuse rejects changed producer inputs or a missing/stale receipt.
Use `-Check -QualifiedAssets` or `--check --qualified-assets` to verify an
existing build without regenerating assets. Generated Data and its local receipt
are ignored by Git and must never be committed or published.

The build records its exact inputs in
`out/snes_quake/build/release-manifest.json`; check mode verifies that record.
`config/rom-config.json` owns the dependency pins and BSP options.
Production asset profiles live beside it under `config/profiles/`;
vendor patches live under `third_party/patches/`. These are required inputs.

See [run instructions and controls](../README.md#run-the-rom) or
[build the reference renderer](REFERENCE_RENDERER.md).
