# Performance measurements

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

[Back to SNES Quake](../README.md).
