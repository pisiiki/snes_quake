MainLoop:
        RW_forced a16i16
.if BSP_SOUND_ENABLED
        ; Keep the 60 Hz command schedule live even when a frame is reused or
        ; the menu has no render job to overlap. Stream refills remain bounded.
        jsr     QuakeSoundServiceMain
.endif
