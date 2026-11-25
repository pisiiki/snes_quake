; Shared frame waits for the playable renderer.
.macro BSP_SOUND_FX3_JOB_JOIN RenderScale
        FX3_JOB_JOIN
.endmacro

.macro BSP_SOUND_WAIT_FRAME RenderScale
        wai
.endmacro
