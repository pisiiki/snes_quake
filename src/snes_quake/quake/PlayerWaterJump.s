; Stock CheckWaterJump and SV_WaterJump. The point hull's Q3 Z is
; relative to the edict origin; the walk hull's Q4 Z is relative to the eye.
.pushseg
.segment "BSP_CPU_LANDING"
WalkWaterJump:
        lda     a:walk_water_level
        bne     @Wet
        stz     a:walk_ledge_ticks
@No:    clc
        rtl
@Wet:   ldx     a:walk_ledge_ticks
        bne     @Move
        cmp     #2
        bne     @No
        jsr     WalkWaterJumpTrace
        bcc     @No
        lda     #225*256/60
        sta     a:w_velocity_z
        lda     #1
        sta     a:w_jump_consumed
        lda     #2*60/WALK_WATER_VBLANKS
        sta     a:walk_ledge_ticks
@Move:  dec     a:walk_ledge_ticks
        stz     a:w_wish+4             ; Release the yaw scratch before the horizontal sweep.
        stz     a:w_support_valid
        lda     a:walk_ledge_push_x
        sta     a:w_wish
.ifdef QC_QUEUED_INPUT
        sta     a:w_velocity_x
.endif
        lda     a:walk_ledge_push_y
        sta     a:w_wish+2
.ifdef QC_QUEUED_INPUT
        sta     a:w_velocity_y
        lda     #1
        sta     a:w_run_swimming
.endif
        lda     a:w_velocity_z
        .repeat WALK_WATER_VBLANKS-1
        clc
        adc     a:w_velocity_z
        .endrepeat
        clc
        adc     #8
        .repeat 4
        cmp     #$8000
        ror
        .endrepeat
        sec
        rtl

WalkWaterJumpTrace:
        .repeat 3, Axis
        lda     a:w_from+2*Axis
        sta     a:w_base+2*Axis
        cmp     #$8000
        ror
        sta     a:w_from+2*Axis
        .endrepeat
        lda     f:pitch_level
        and     #CAMERA_ANGLE_MASK
        asl
        tax
        lda     f:CameraMoveCos,x
        asl
        sta     a:w_swim_pitch_cos
        asl
        clc
        adc     a:w_swim_pitch_cos
        sta     a:w_swim_pitch_cos       ; 24 stock units at Q3 / 32.
        .repeat 2, Axis
        lda     f:yaw_index
        and     #CAMERA_ANGLE_MASK
        asl
        tax
        .if Axis = 0
        lda     f:CameraMoveCos,x
        .else
        lda     f:CameraMoveSin,x
        .endif
        ldx     a:w_swim_pitch_cos
        jsl     WalkWaterJumpProduct
        lda     z:w_mul_low
        clc
        adc     #16
        .repeat 5
        cmp     #$8000
        ror
        .endrepeat
        clc
        adc     a:w_from+2*Axis
        sta     a:w_to+2*Axis
        .endrepeat
        lda     a:w_from+4
        clc
        adc     #8*8
        sta     a:w_from+4
        sta     a:w_to+4
        jsl     WalkWaterJumpPoint
        bcc     @Restore
        ; A start in solid has no usable surface normal.
        lda     a:w_normal
        ora     a:w_normal+2
        ora     a:w_normal+4
        beq     @Miss
        .repeat 2, Axis
        lda     a:w_normal+2*Axis
        neg
        ldx     #50*16*WALK_WATER_VBLANKS/60
        jsl     WalkWaterJumpNormal
        sta     a:walk_ledge_push_x+2*Axis
        .endrepeat
        lda     a:w_from+4
        clc
        adc     #24*8
        sta     a:w_from+4
        sta     a:w_to+4
        jsl     WalkWaterJumpPoint
        bcs     @Miss
        sec
        bra     @Restore
@Miss:  clc
@Restore:
        .repeat 3, Axis
        lda     a:w_base+2*Axis
        sta     a:w_from+2*Axis
        .endrepeat
        rts
.popseg

WalkWaterJumpPoint:
        jsr     ShotHull::WalkTrace
        rtl
WalkWaterJumpProduct:
        jsr     WalkMultiply
        rtl
WalkWaterJumpNormal:
        jsr     WalkMultiply
        jsr     WalkProductQ14
        rtl
