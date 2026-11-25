; SV_WaterMove retains a three-axis velocity. Work in Q4 per three-field tick
; and convert the vertical component at the existing Q8/VBlank ABI boundary.
.pushseg
.segment "BSP_CPU_LANDING"
WalkWaterMove:
        lda     a:w_wish+4
        sta     a:w_unstepped          ; Sampled yaw, as a word-table offset.
        lda     a:w_buttons
        and     #(JOY_X | JOY_B)
        cmp     #JOY_X
        beq     @Forward
        cmp     #JOY_B
        beq     @Forward
        lda     #0
        bra     @Command
@Forward:
        lda     a:w_buttons
        bit     #QC_INPUT_WALK
        beq     :+
        lda     #160                  ; 200 units/second when walking.
        bra     :++
:       lda     #320                  ; 400 units/second before the speed cap.
:       ldx     a:w_buttons
        bpl     @Command              ; JOY_B is the sign bit.
        neg
@Command:
        sta     a:w_run_drop
        lda     f:pitch_level
        and     #CAMERA_ANGLE_MASK
        asl
        sta     a:w_unstepped+2
        tax
        lda     f:CameraRunCos,x
        ldx     a:w_run_drop
        jsl     WalkWaterRoundedQ8
        sta     a:w_unstepped+4         ; Pitched forward command in XY.
        ldx     a:w_unstepped+2
        lda     f:CameraRunSin,x
        ldx     a:w_run_drop
        jsl     WalkWaterRoundedQ8
        sta     a:w_wish+4
        lda     a:w_buttons
        and     #(JOY_Y | JOY_A)
        cmp     #JOY_Y
        beq     @Left
        cmp     #JOY_A
        beq     @Right
        lda     a:w_run_drop
        bne     :+
        lda     #.loword(-48)          ; Idle swim drifts down at 60 units/s.
        sta     a:w_wish+4
:       lda     #0
        bra     @Strafe
@Left:  lda     #280
        bra     @Strafe
@Right: lda     #.loword(-280)
@Strafe:
        sta     a:w_run_drop
        .repeat 2, Axis
        ldx     a:w_unstepped
        .if Axis = 0
        lda     f:CameraRunCos,x
        .else
        lda     f:CameraRunSin,x
        .endif
        ldx     a:w_unstepped+4
        jsl     WalkWaterRoundedQ8
        sta     a:w_wish+2*Axis
        ldx     a:w_unstepped
        .if Axis = 0
        lda     f:CameraRunSin,x
        .else
        lda     f:CameraRunCos,x
        .endif
        ldx     a:w_run_drop
        jsl     WalkWaterRoundedQ8
        .if Axis = 0
        neg
        .endif
        clc
        adc     a:w_wish+2*Axis
        sta     a:w_wish+2*Axis
        .endrepeat

        lda     a:w_velocity_z
        asl
        clc
        adc     a:w_velocity_z
        clc
        adc     #8
        .repeat 4
        cmp     #$8000
        ror
        .endrepeat
        sta     a:w_base+4
        lda     a:w_velocity_x
        sta     a:w_base
        lda     a:w_velocity_y
        sta     a:w_base+2
        ldy     #4
@Friction:
        lda     a:w_base,y
        ldx     #13108                ; ceil(4/5 * 16384), truncating toward zero.
        jsr     WalkWaterDrag
        sta     a:w_base,y
        dey
        dey
        bpl     @Friction
        ldx     #w_base
        jsr     WalkWaterLength
        lda     a:w_run_speed
        sta     a:w_run_drop
        ldx     #w_wish
        jsr     WalkWaterLength
        lda     a:w_run_speed
        cmp     #257
        bcc     :+
        lda     #256                 ; sv_maxspeed, 320 units/s.
:       ldx     #179                 ; Scale the capped wishspeed by 0.7.
        jsl     WalkWaterRoundedQ8
        tay
        lsr
        sta     a:w_run_gain         ; sv_accelerate * frametime = 1/2.
        tya
        sec
        sbc     a:w_run_drop
        bcc     @NoGain
        beq     @NoGain
        cmp     a:w_run_gain
        bcc     :+
        lda     a:w_run_gain
:       jsl     WalkWaterRatio
        bra     @Gain
@NoGain:
        lda     #0
@Gain:  sta     a:w_run_gain
        ldy     #4
@Accelerate:
        lda     a:w_wish,y
        ldx     a:w_run_gain
        jsl     WalkWaterRoundedQ12
        clc
        adc     a:w_base,y
        ldx     a:w_water_drag
        jsr     WalkWaterDrag
        sta     a:w_wish,y
        dey
        dey
        bpl     @Accelerate
        lda     a:w_wish
        sta     a:w_velocity_x
        lda     a:w_wish+2
        sta     a:w_velocity_y
        lda     a:w_wish+4
        pha
        php
        bpl     :+
        neg
:       ldx     #21846               ; floor(abs(z) * 16/3), within the axis bound.
        jsl     WalkWaterScaleQ12
        plp
        bpl     :+
        neg
:       sta     a:w_velocity_z
        stz     a:w_wish+4
        pla
        rtl

WalkWaterDrag:
        cmp     #0
        bpl     @Positive
        neg
        jsl     WalkWaterJumpNormal
        neg
        rts
@Positive:
        jsl     WalkWaterJumpNormal
        rts

; X selects three signed Q4 components in walk RAM.
WalkWaterLength:
        stz     a:w_dot
        stz     a:w_dot_high
        ldy     #3
@Axis:  lda     a:$0000,x
        phx
        tax
        jsl     WalkWaterJumpProduct
        lda     a:w_dot
        clc
        adc     z:w_mul_low
        sta     a:w_dot
        lda     a:w_dot_high
        adc     z:w_mul_high
        sta     a:w_dot_high
        plx
        inx
        inx
        dey
        bne     @Axis
        jsl     WalkWaterSqrt
        rts
.popseg

WalkWaterRoundedQ8:
        jsr     WalkMultiply
        jsr     WalkRunRoundedQ8
        rtl
WalkWaterScaleQ12:
        jsr     WalkMultiply
        jsr     WalkProductQ12
        rtl
WalkWaterRoundedQ12:
        jsr     WalkMultiply
        lda     z:w_mul_low
        clc
        adc     #2048
        sta     z:w_mul_low
        bcc     :+
        inc     z:w_mul_high
:       jsr     WalkProductQ12
        rtl
WalkWaterRatio:
        jsr     WalkRunRatio
        rtl
WalkWaterSqrt:
        jsr     WalkSquaredMagnitude
        rtl

.include "quake/WaterPalette.s"
