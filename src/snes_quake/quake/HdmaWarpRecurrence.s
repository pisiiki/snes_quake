.segment "HDMA_WARP_CODE"
; Prepare affine ray and cofactor recurrences once. Eight guard bits prevent
; cumulative row rounding. Translation follows the fitted three-knot profile.
HdmaPrepareRotation:
        .repeat 3, row
          HDMA_MUL z:hdma_matrix-hdma_work+row*6, #.loword(-21), z:hdma_ray-hdma_work+row*2
          HDMA_MUL z:hdma_matrix-hdma_work+row*6+2, #2293, z:hdma_partial-hdma_work
          clc
          adc   z:hdma_ray-hdma_work+row*2
          clc
          adc   z:hdma_matrix-hdma_work+row*6+4
          jsr   HdmaQ12ToAccum
          .repeat 2, word
            lda z:hdma_product-hdma_work+word*2
            sta z:hdma_accum-hdma_work+row*4+word*2
          .endrepeat
          lda   z:hdma_matrix-hdma_work+row*6+2
          ldx   #.loword(-19115)
          ldy   #11
          jsr   HdmaShiftProduct
          .repeat 2, word
            lda z:hdma_product-hdma_work+word*2
            sta z:hdma_steps-hdma_work+row*4+word*2
          .endrepeat
        .endrepeat
        .repeat 2, row
          HDMA_MUL z:hdma_matrix-hdma_work+row*6, z:hdma_matrix-hdma_work+14, z:hdma_cross-hdma_work
          HDMA_MUL z:hdma_matrix-hdma_work+row*6+2, z:hdma_matrix-hdma_work+12, z:hdma_partial-hdma_work
          lda   z:hdma_cross-hdma_work
          sec
          sbc   z:hdma_partial-hdma_work
          sta   z:hdma_cross-hdma_work
          HDMA_MUL z:hdma_cross-hdma_work, #.loword(-21), hdma_cofactor_constants+row*2
          neg
          sta   hdma_cofactor_constants+row*2
          HDMA_MUL z:hdma_matrix-hdma_work+row*6+2, z:hdma_matrix-hdma_work+16, z:hdma_partial-hdma_work
          clc
          adc   hdma_cofactor_constants+row*2
          sta   hdma_cofactor_constants+row*2
          HDMA_MUL z:hdma_matrix-hdma_work+row*6+4, z:hdma_matrix-hdma_work+14, z:hdma_partial-hdma_work
          lda   hdma_cofactor_constants+row*2
          sec
          sbc   z:hdma_partial-hdma_work
          sta   hdma_cofactor_constants+row*2
          HDMA_MUL z:hdma_cross-hdma_work, #2293, z:hdma_ray-hdma_work
          HDMA_MUL z:hdma_matrix-hdma_work+row*6, z:hdma_matrix-hdma_work+16, z:hdma_partial-hdma_work
          clc
          adc   z:hdma_ray-hdma_work
          sta   z:hdma_ray-hdma_work
          HDMA_MUL z:hdma_matrix-hdma_work+row*6+4, z:hdma_matrix-hdma_work+12, z:hdma_partial-hdma_work
          lda   z:hdma_ray-hdma_work
          sec
          sbc   z:hdma_partial-hdma_work
          jsr   HdmaQ12ToAccum
          .repeat 2, word
            lda z:hdma_product-hdma_work+word*2
            sta z:hdma_accum-hdma_work+(3+row)*4+word*2
          .endrepeat
          lda   z:hdma_cross-hdma_work
          ldx   #.loword(-19115)
          ldy   #11
          jsr   HdmaShiftProduct
          .repeat 2, word
            lda z:hdma_product-hdma_work+word*2
            sta z:hdma_steps-hdma_work+(3+row)*4+word*2
          .endrepeat
        .endrepeat
        rts

.macro HDMA_TRANSLATION_RECURRENCES routine, focal
routine:
        .repeat 3, axis
          .repeat 3, knot
            lda z:hdma_translation-hdma_work+axis*2
            .if knot = 0
              ldx #(WARP_DEPTH_0_Q10 * (64 + (axis < 2)*(focal-64)) + 32)/64
            .elseif knot = 1
              ldx #(WARP_DEPTH_1_Q10 * (64 + (axis < 2)*(focal-64)) + 32)/64
            .else
              ldx #(WARP_DEPTH_2_Q10 * (64 + (axis < 2)*(focal-64)) + 32)/64
            .endif
            jsr HdmaMultiplyQ10
            sta z:hdma_depth_values-hdma_work+knot*2
          .endrepeat
          lda   z:hdma_depth_values-hdma_work+2
          sec
          sbc   z:hdma_depth_values-hdma_work
          sta   z:hdma_depth_delta-hdma_work
          lda   z:hdma_depth_values-hdma_work
          jsr   HdmaQ12ToAccum
          .repeat 2, word
            lda z:hdma_product-hdma_work+word*2
            sta z:hdma_accum-hdma_work+(5+axis)*4+word*2
          .endrepeat
          lda   z:hdma_depth_delta-hdma_work
          ldx   #WARP_DEPTH_LEFTSTART
          ldy   #WARP_DEPTH_LEFTSTART_SHIFT
          jsr   HdmaShiftProduct
          lda   z:hdma_accum-hdma_work+(5+axis)*4
          clc
          adc   z:hdma_product-hdma_work
          sta   z:hdma_accum-hdma_work+(5+axis)*4
          lda   z:hdma_accum-hdma_work+(5+axis)*4+2
          adc   z:hdma_product-hdma_work+2
          sta   z:hdma_accum-hdma_work+(5+axis)*4+2
          lda   z:hdma_depth_delta-hdma_work
          ldx   #WARP_DEPTH_LEFTSTEP
          ldy   #WARP_DEPTH_LEFTSTEP_SHIFT
          jsr   HdmaShiftProduct
          .repeat 2, word
            lda z:hdma_product-hdma_work+word*2
            sta z:hdma_steps-hdma_work+(5+axis)*4+word*2
          .endrepeat
          lda   z:hdma_depth_values-hdma_work+4
          sec
          sbc   z:hdma_depth_values-hdma_work+2
          sta   z:hdma_depth_delta-hdma_work
          lda   z:hdma_depth_values-hdma_work+2
          jsr   HdmaQ12ToAccum
          .repeat 2, word
            lda z:hdma_product-hdma_work+word*2
            sta hdma_bottom+axis*4+word*2
          .endrepeat
          lda   z:hdma_depth_delta-hdma_work
          ldx   #WARP_DEPTH_RIGHTSTART
          ldy   #WARP_DEPTH_RIGHTSTART_SHIFT
          jsr   HdmaShiftProduct
          lda   hdma_bottom+axis*4
          clc
          adc   z:hdma_product-hdma_work
          sta   hdma_bottom+axis*4
          lda   hdma_bottom+axis*4+2
          adc   z:hdma_product-hdma_work+2
          sta   hdma_bottom+axis*4+2
          lda   z:hdma_depth_delta-hdma_work
          ldx   #WARP_DEPTH_RIGHTSTEP
          ldy   #WARP_DEPTH_RIGHTSTEP_SHIFT
          jsr   HdmaShiftProduct
          .repeat 2, word
            lda z:hdma_product-hdma_work+word*2
            sta hdma_bottom_steps+axis*4+word*2
          .endrepeat
        .endrepeat
        rts

.endmacro
HDMA_TRANSLATION_RECURRENCES HdmaPrepareRecurrences, 64
HDMA_TRANSLATION_RECURRENCES HdmaPrepareOverscanRecurrences, BSP_WARP_SOURCE_FOCAL

HdmaAdvanceRecurrences:
        .repeat 8, value
          lda   z:hdma_accum-hdma_work+value*4
          clc
          adc   z:hdma_steps-hdma_work+value*4
          sta   z:hdma_accum-hdma_work+value*4
          lda   z:hdma_accum-hdma_work+value*4+2
          adc   z:hdma_steps-hdma_work+value*4+2
          sta   z:hdma_accum-hdma_work+value*4+2
        .endrepeat
        rts

HdmaQ12ToAccum:
        sta     z:hdma_product-hdma_work+1
        cmp     #$8000
        RW      a8
        lda     #0
        sbc     #0
        eor     #$FF
        sta     z:hdma_product-hdma_work+3
        stz     z:hdma_product-hdma_work
        RW      a16
        rts

HdmaShiftProduct:
        cmp     #0
        beq     @Zero
        cpx     #0
        beq     @Zero
        jsr     HdmaMultiply
        ; Compiled callers shift by 9..12. Move the first eight bits as
        ; bytes, then perform only the remaining one to four arithmetic bits.
        lda     z:hdma_product-hdma_work+1
        sta     z:hdma_product-hdma_work
        lda     z:hdma_product-hdma_work+3
        and     #255
        cmp     #128
        bcc     :+
        ora     #$FF00
:
        sta     z:hdma_product-hdma_work+2
        tya
        sec
        sbc     #8
        tay
@Shift:
        lda     z:hdma_product-hdma_work+2
        cmp     #$8000
        ror
        sta     z:hdma_product-hdma_work+2
        ror     z:hdma_product-hdma_work
        dey
        bne     @Shift
        rts
@Zero:
        stz     z:hdma_product-hdma_work
        stz     z:hdma_product-hdma_work+2
        rts

; Signed Q12 value times 2^(factor/1024). Two lookup reads replace division
; and multiplication; logarithmic quantization is explicitly in the oracle.
.macro HDMA_LOG_SCALE routine, exponent, minimum
routine:
        sta     z:hdma_log_sign-hdma_work
        beq     @Zero
        bpl     :+
        neg
:
        cmp     #$8000
        bcs     @Overflow
        asl
        tax
        lda     f:HdmaLog,x
        clc
        adc     z:hdma_log_factor-hdma_work
        bmi     @Small
        cmp     #15360
        bcs     @Overflow
        asl
        tax
        lda     f:exponent,x
@Sign:
        bit     z:hdma_log_sign-hdma_work
        bpl     :+
        neg
:
        rts
@Small:
        cmp     #.loword(minimum)
        bcc     @Zero
        lda     #1
        bra     @Sign
@Overflow:
        inc     z:hdma_fault-hdma_work
@Zero:
        lda     #0
        rts

.endmacro
HDMA_LOG_SCALE HdmaLogScale, HdmaExp, -1024
HDMA_LOG_SCALE HdmaOverscanLogScale, HdmaOverscanExp, WARP_FOCAL_EXP_MINIMUM
