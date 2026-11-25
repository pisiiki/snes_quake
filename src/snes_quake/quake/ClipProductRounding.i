; Signed Q12 geometry rounded to nearest, with half ties toward +infinity.
; The fourth LSR leaves product bit11 in Carry. Round the low nibble before
; combining it with high<<4; ADD propagates a rounded nibble of16 correctly.
.macro BSP_SIGNED_MUL_SHIFT_NEAREST12 dest, source, multiplier
        move    R6, multiplier
        from    source
        lmult
        with    R4
        hib
  .repeat 4
        with    R4
        lsr
  .endrepeat
        with    R4
        adc     #0
        move    R6, R4
  .repeat 4
        add     R0
  .endrepeat
        add     R6
        move    dest, R0
.endmacro

; Geometry precision changes only in ordinary 2x; F3 retains its established ABI.
.macro BSP_CLIP_MUL_VIEW12 dest, source, multiplier
  .if BSP_RENDER_SCALE = 2
        BSP_SIGNED_MUL_SHIFT_NEAREST12 dest, source, multiplier
  .else
        BSP_SIGNED_MUL_SHIFT_TRUNC12 dest, source, multiplier
  .endif
.endmacro

