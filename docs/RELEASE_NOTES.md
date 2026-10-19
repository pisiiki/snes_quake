# SNES Quake release notes

Changes are listed by version, newest first. The current release is **v0.0.3**.

This source release captures the currently qualified renderer and reproducible
build pipeline. Follow the [build instructions](BUILDING.md) for Windows or Linux.
Prebuilt ROMs are not distributed. Quake game assets retain their original terms;
see [third-party notices](THIRD_PARTY.md).

## v0.0.3 — Changes since 0.0.2

- **SNES Mouse support:** look around in Fly mode and use the left/right buttons to move forward/back. Optional WASD movement works alongside mouse look; see [mouse setup and controls](../README.md#mouse-look-and-movement).
- **X3 and X3 WARP:** render at 85×74 and reproject frames using Mode 7 and HDMA, with warp transforms updated at 30 Hz. X3 Warp parameters have been retrained for the updated renderer and display timing.
- **Smoother replay data:** camera and moving entities are sampled at 30 Hz, with entity interpolation and explicit handling of cuts and animation poses.
- **Rendering performance improvements:** see the current qualified measurements below. Changes in replay cadence prevent a direct FPS percentage comparison with v0.0.2.
- **Broader CPU compatibility:** Windows and Linux source builds now use SSE2 lighting tools; AVX2 is no longer required.
- **Updated demonstrations:** separate realtime X2 and X3 WARP videos, refreshed screenshots and clearer mouse/build instructions.

## v0.0.2 — Previous release baseline

- E1M3 rendering at X2 (128×112), with textures, lightmaps, sky, liquids and moving level geometry.
- Monsters, items and sprite effects, with realtime sound and ordered or realtime demo playback.
- Fly-camera exploration and the in-ROM rendering/settings menu.
- Desktop reference-renderer controls, image comparisons and qualified performance measurements.

## Qualified performance — v0.0.3

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

## Known limitations

- This is a renderer demonstration, not a complete Quake game port.
- The included content path is the shareware demo1.dem on maps/e1m3.bsp; gameplay, AI, save games, networking, and the Quake console are not implemented.
- Rendering offers X2 (128x112) and X3 (85x74) indexed color at a 256x224 display. X3 warp smooths camera movement but does not increase completed-frame detail or animate entities between rendered frames. Detail and frame rate vary with scene complexity.
- Interactive fly mode is a development camera and does not provide Quake movement or collision semantics.

## Compatibility

- Run quake.sfc with the current [MesenCE development build](https://github.com/nesdev-org/MesenCE#development-builds).
- Source builds have been verified on Windows and Ubuntu Linux; see [building instructions](BUILDING.md).
