.if BSP_SOUND_ENABLED
        ; Mixer commands, queue management and chunk completion stay outside
        ; NMI. Warp arithmetic may send one nonblocking three-byte packet at
        ; each designated boundary; it never waits for the SPC or runs a loop.
.endif
