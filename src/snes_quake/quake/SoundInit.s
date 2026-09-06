.if BSP_SOUND_ENABLED
        jsr     QuakeSoundInit
        RW      a8
.endif
