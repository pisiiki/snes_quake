.ifndef __QUAKE_VIEW_DOT_ARITHMETIC_I__
__QUAKE_VIEW_DOT_ARITHMETIC_I__ = 1

.macro BSP_VIEW_DOT_SAVE
        move R12, R4
        move R7, R0
.endmacro
.macro BSP_VIEW_DOT_PRODUCT axis, coefficient
        lm R6, (coefficient)
        from axis
        lmult
.endmacro
.macro BSP_VIEW_DOT_ADD
        with R4
        add R12
        adc R7
.endmacro
.macro BSP_VIEW_DOT_ROUND_STORE shift, address
  .repeat shift
        asr
        with R4
        ror
  .endrepeat
        from R4
        adc #0
        sm (address), R0
.endmacro
; Extract bits 8..23 without MERGE, which is an FX3 command port.
; ROL obtains the original low-word bit 7 for the same nearest rounding.
; R4 retains the unrounded word and R5 is volatile; R8 stays untouched.
.macro BSP_VIEW_DOT_ROUND_STORE8 address
        lob
        swap
        from R4
        to R5
        hib
        or R5
        move R5, R0
        with R4
        swap
        with R4
        rol
        adc #0
        move R4, R5
        sm (address), R0
.endmacro

.macro BSP_VIEW_DOT_RIGHT output
    lm R6,(GSU_VIEW_MATRIX_CY)
    from R2
    lmult
    BSP_VIEW_DOT_SAVE
    lm R6,(GSU_VIEW_MATRIX_SY)
    from R1
    lmult
    from R12
    to R4
    sub R4
    from R7
    to R0
    sbc R0
    BSP_VIEW_DOT_ROUND_STORE 2,output
.endmacro

.macro BSP_VIEW_DOT_AXIS3 coef_x, coef_y, coef_z, output
    BSP_VIEW_DOT_PRODUCT R1,coef_x
    BSP_VIEW_DOT_SAVE
    BSP_VIEW_DOT_PRODUCT R2,coef_y
    BSP_VIEW_DOT_ADD
    BSP_VIEW_DOT_SAVE
    BSP_VIEW_DOT_PRODUCT R3,coef_z
    BSP_VIEW_DOT_ADD
    BSP_VIEW_DOT_ROUND_STORE8 output
.endmacro

.endif
