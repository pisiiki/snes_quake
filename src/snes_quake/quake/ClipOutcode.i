; Return in R0 the four exact frustum-plane outcode bits for the Q6
; CLIP_RIGHT/UP/DEPTH coordinate left by ClipTransformVertex.
.macro BSP_CLASSIFY_CLIP_OUTCODE right_scale, up_scale
        .local Plane0Inside, Plane1Inside, Plane2Inside, Plane3Inside
        move    R0, #0
        lm      R4, (CLIP_DEPTH)
        with    R4
        asr
        lm      R5, (CLIP_RIGHT)
        with    R5
        asr
.if (BSP_RENDER_SCALE = 3) && (BSP_WARP_SOURCE_FOCAL < BSP_VIEW_CENTER_X)
right_scale:
        nop
        nop
.endif
        move    R6, R4
        with    R6
        add     R5
        bpl     Plane0Inside
        nop
        with    R0
        or      #1
Plane0Inside:
        move    R6, R4
        with    R6
        sub     R5
        bpl     Plane1Inside
        nop
        with    R0
        or      #2
Plane1Inside:
        lm      R5, (CLIP_UP)
        with    R5
        asr
.if (BSP_RENDER_SCALE = 3) && (BSP_WARP_SOURCE_FOCAL < BSP_VIEW_CENTER_X)
up_scale:
        nop
        nop
.endif
        move    R6, R4
        with    R6
        sub     R5
        bpl     Plane2Inside
        nop
        with    R0
        or      #4
Plane2Inside:
        move    R6, R4
        with    R6
        add     R5
        bpl     Plane3Inside
        nop
        with    R0
        or      #8
Plane3Inside:
.endmacro
