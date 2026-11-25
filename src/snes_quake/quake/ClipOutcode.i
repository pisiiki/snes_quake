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

; Set a proof bit for a Q6 plane score <= -3. R3 and axis are halved,
; R0 accumulates bits and R5 is scratch. Packed Q2 and the Q6 matrix
; bound the score away from signed overflow, including the +2.
.macro BSP_CLASSIFY_CLIP_MARGIN_PLANE axis, subtract_axis, flag_bit
        .local Inside
        move    R5, R3
        with    R5
  .if subtract_axis
        sub     axis
  .else
        add     axis
  .endif
        with    R5
        add     #2
        bpl     Inside
        nop
        or      #flag_bit
Inside:
.endmacro
