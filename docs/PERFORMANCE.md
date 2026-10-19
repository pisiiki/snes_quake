# Performance measurements

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

[Back to SNES Quake](../README.md).
