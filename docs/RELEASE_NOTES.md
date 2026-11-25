# SNES Quake release notes

[Current playable preview](#v010-playable-preview) · [v0.0.3 renderer demo](#v003-renderer-demo)

## v0.0.3 renderer demo

These historical notes cover the E1M3 renderer demo. The original notes are
available from the [v0.0.3 tag](https://github.com/pisiiki/snes_quake/blob/v0.0.3/docs/RELEASE_NOTES.md).

### Changes since v0.0.2

- **SNES Mouse support:** look around in Fly mode and use the left/right buttons to move forward/back. Optional WASD movement works alongside mouse look; see [mouse setup and controls](https://github.com/pisiiki/snes_quake/blob/v0.0.3/README.md#mouse-look-and-movement).
- **X3 and X3 WARP:** render at 85×74 and reproject frames using Mode 7 and HDMA, with warp transforms updated at 30 Hz. X3 Warp parameters have been retrained for the updated renderer and display timing.
- **Smoother replay data:** camera and moving entities are sampled at 30 Hz, with entity interpolation and explicit handling of cuts and animation poses.
- **Rendering performance improvements:** see the current qualified measurements below. Changes in replay cadence prevent a direct FPS percentage comparison with v0.0.2.
- **Broader CPU compatibility:** Windows and Linux source builds now use SSE2 lighting tools; AVX2 is no longer required.
- **Updated demonstrations:** separate realtime X2 and X3 WARP videos, refreshed screenshots and clearer mouse/build instructions.

### v0.0.2 baseline

- E1M3 rendering at X2 (128×112), with textures, lightmaps, sky, liquids and moving level geometry.
- Monsters, items and sprite effects, with realtime sound and ordered or realtime demo playback.
- Fly-camera exploration and the in-ROM rendering/settings menu.
- Desktop reference-renderer controls, image comparisons and qualified performance measurements.

### Qualified performance

**Default realtime demo playback: 2.832 fresh FPS.**
Across the full E1M3 demo, the current ROM produces 210 new
images over 4,456 emulated NTSC display frames, with
textures, lighting, moving level objects, monsters, items and sound enabled.
Playback stays on time: it skips scene updates when rendering cannot keep up,
with 0 ticks of measured playhead drift.

The separate ordered benchmark completes 223 fresh
presentations in 5,069 emulated NTSC display frames across the full
step-by-step playback test: **2.644 cold-run fresh FPS** with
the same rendering features enabled. After the first presentation, the remaining
222 transitions complete in 5,002
frames, or **2.667 sustained fresh FPS**.

Fresh FPS counts newly completed framebuffers per emulated SNES second;
repeated display frames do not count. Emulator fast-forward changes wall-clock
test time, not these emulated results. Demo camera and entity data are sampled
at 30 Hz, and warp transforms update at 30 Hz; NTSC display refresh is about
60 Hz. These rates do not measure newly completed framebuffers.
The 3 Hz selection schedule chooses
camera poses and is not the renderer frame rate.

### Known limitations

- This is a renderer demonstration, not a complete Quake game port.
- The included content path is the shareware demo1.dem on maps/e1m3.bsp; gameplay, AI, save games, networking, and the Quake console are not implemented.
- Rendering offers X2 (128x112) and X3 (85x74) indexed color at a 256x224 display. X3 warp smooths camera movement but does not increase completed-frame detail or animate entities between rendered frames. Detail and frame rate vary with scene complexity.
- Interactive fly mode is a development camera and does not provide Quake movement or collision semantics.

### Compatibility

- Run quake.sfc with the current [MesenCE development build](https://github.com/nesdev-org/MesenCE#development-builds).
- Source builds have been verified on Windows and Ubuntu Linux; see [building instructions](https://github.com/pisiiki/snes_quake/blob/v0.0.3/docs/BUILDING.md).

## v0.1.0 playable preview

SNES Quake moves from the E1M3 renderer demo to an early playable port. Choose a
skill in START and enter E1M1 through the Episode 1 portal. The five included
maps are START and E1M1–E1M4. Proper gameplay is currently available in START
and E1M1.

- **Gameplay.** Supported QuakeC routines drive monsters, pickups, doors, and
  lifts. Play with the SNES controller and optional SNES Mouse. The ROM now
  runs live gameplay in place of the prerecorded `.dem` scheduler.
- **Rendering.** Choose Textures + Lightmaps, Flat, or Lightmaps at X2
  (128×100) or X3 (85×67). The HUD stays at full resolution, and hardware
  sprites draw the first-person weapon. The playable renderer retires X3 WARP.
- **Streaming and audio.** MSU-1 streams code and assets and plays selected
  sounds in stereo alongside the SNES sound engine.
- **Reference engine.** The optional C++ desktop application can run gameplay,
  record and replay tapes, and help compare state and rendered frames with the
  ROM. Its local asset tools use the same PAK and generated cartridge package.
  [Reference renderer build guide](../src/reference_renderer/README.md)

Follow the [build instructions](../README.md#build-from-source) to install the
pinned dependencies and run `python build.py`. The build verifies and extracts
the original bundled Quake 1.06 shareware ZIP. Keep the generated
`snes_quake.sfc`, `snes_quake.msu`, and all 24 PCM tracks together. See the
[third-party notices](THIRD_PARTY.md) for game data and dependency terms.

Fresh Windows and Ubuntu builds both produced cartridges that booted to START
in stock MesenCE. The gameplay and renderer-feature videos use a 300% emulator
GSU clock. FXPak Pro / Mk. III compatibility is still unverified.
