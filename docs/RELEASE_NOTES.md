# SNES Quake 0.0.2 — renderer progress release

This source release captures the currently qualified renderer and reproducible
build pipeline. [Build the ROM from source](BUILDING.md) on Windows or Linux.
Prebuilt ROMs are not distributed. Quake game assets retain their original terms;
see [third-party notices](THIRD_PARTY.md).

## Highlights

- Quake's original colors, textures and lighting
- Animated skies and liquids, plus moving doors, lifts and other level objects in demo and fly modes
- Detailed monster and item images, rotating weapon pickups, and sprite effects
- During demo playback, monsters, pickups and sprite effects are hidden correctly behind walls and moving doors
- Native SNES sound synchronized with realtime demo playback
- Realtime demo playback, step-by-step playback for comparisons, and a fly camera for exploring the level
- A runtime menu for rendering, playback, level objects, monsters and items, colors, and sound

## Qualified performance

**Default realtime demo playback: 2.374 fresh FPS.**
Across the full E1M3 demo, the current ROM produces 176 new
images over 4,455 emulated NTSC display frames, with
textures, lighting, moving level objects, monsters, items and sound enabled.
Playback stays on time: it skips scene updates when rendering cannot keep up,
with 0 ticks of measured playhead drift.

The separate ordered benchmark completes 149 fresh
presentations in 4,536 emulated NTSC display frames across the full
step-by-step playback test: **1.974 cold-run fresh FPS** with
the same rendering features enabled. After the first presentation, the remaining
148 transitions complete in 4,486
frames, or **1.983 sustained fresh FPS**.

Fresh FPS counts newly completed framebuffers per emulated SNES second;
repeated display frames do not count. Emulator fast-forward changes wall-clock
test time, not these emulated results. The 2 Hz selection schedule chooses
camera poses and is not the renderer frame rate.

## Known limitations

- This is a renderer demonstration, not a complete Quake game port.
- The included content path is the shareware demo1.dem on maps/e1m3.bsp; gameplay, AI, save games, networking, and the Quake console are not implemented.
- Rendering is 128x112 indexed color presented at 256x224, so detail and frame rate vary substantially with scene complexity.
- Interactive fly mode is a development camera and does not provide Quake movement or collision semantics.
- In fly mode, sprites can appear through doors and other inline brush models.

## Compatibility

- Run quake.sfc with the current [MesenCE development build](https://github.com/nesdev-org/MesenCE#development-builds).
- Source builds have been verified on Windows and Ubuntu Linux; see [building instructions](BUILDING.md).
