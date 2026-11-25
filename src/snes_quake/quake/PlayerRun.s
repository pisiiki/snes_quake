; Horizontal velocity is Q4 displacement per three-VBlank step.
RUN_MAX_SPEED = 256
RUN_WALK_SPEED = 160
RUN_STOP_SPEED = 80
RUN_AIR_CAP = 24
RUN_MAX_AXIS = 1600

.macro WALK_RUN_DOT first, second
        stz     a:w_dot
        stz     a:w_dot_high
        .repeat 2, axis
        lda     a:first+2*axis
        ldx     a:second+2*axis
        jsr     WalkMultiply
        lda     a:w_dot
        clc
        adc     z:w_mul_low
        sta     a:w_dot
        lda     a:w_dot_high
        adc     z:w_mul_high
        sta     a:w_dot_high
        .endrepeat
.endmacro

; Called while the player's pre-jump grounded state is still available.
WalkRunMove:
        stz     a:w_run_swimming
        lda     a:w_grounded
        beq     @Accelerate
        lda     a:w_velocity_x
        ora     a:w_velocity_y
        beq     @Accelerate
        ; At full cardinal speed, even edge friction removes at most
        ; 102 Q4. The 128 Q4 acceleration restores that exact velocity.
        lda     a:w_velocity_x
        cmp     a:w_wish
        bne     @Friction
        lda     a:w_velocity_y
        cmp     a:w_wish+2
        bne     @Friction
        lda     a:w_velocity_x
        bne     @MovingX
        lda     a:w_velocity_y
        bra     @Speed
@MovingX:
        ldx     a:w_velocity_y
        bne     @Friction
@Speed:
        cmp     #RUN_MAX_SPEED
        beq     @Cardinal
        cmp     #.loword(-RUN_MAX_SPEED)
        bne     @Friction
@Cardinal:
        lda     a:w_wish+4
        bne     @Friction              ; Brake if Always Run was just disabled.
        rts
@Friction:
        jsr     WalkRunFriction
@Accelerate:
        lda     a:w_wish
        ora     a:w_wish+2
        bne     :+
        jmp     @Displacement
:       WALK_RUN_DOT w_velocity_x, w_wish
        lda     a:w_dot
        sta     z:w_mul_low
        lda     a:w_dot_high
        sta     z:w_mul_high
        jsr     WalkRunRoundedQ8
        sta     a:w_temp
        lda     a:w_wish+4
        bne     :+
        lda     #RUN_MAX_SPEED
:       tay
        lsr                            ; Quake accelerates at 10 × wish speed / 20 Hz.
        sta     a:w_run_gain
        lda     a:w_grounded
        beq     @Air
        tya
        bra     @Add
@Air:
        lda     #RUN_AIR_CAP
@Add:
        sec
        sbc     a:w_temp
        beq     @Displacement
        bmi     @Displacement
        cmp     a:w_run_gain
        bcc     :+
        lda     a:w_run_gain
:       sta     a:w_run_gain
        ldy     #2
@Axis:
        lda     a:w_wish,y
        ldx     a:w_run_gain
        jsr     WalkMultiply
        jsr     WalkRunRoundedQ8
        clc
        adc     a:w_velocity_x,y
        jsr     WalkRunClampAxis
        sta     a:w_velocity_x,y
        dey
        dey
        bpl     @Axis
@Displacement:
        lda     a:w_velocity_x
        sta     a:w_wish
        lda     a:w_velocity_y
        sta     a:w_wish+2
        rts

WalkRunFriction:
        jsr     WalkRunSpeed
        lda     a:w_run_speed
        cmp     #RUN_STOP_SPEED
        bcs     :+
        lda     #RUN_STOP_SPEED
:       sta     a:w_run_drop
        jsr     WalkRunEdgeSupport
        lda     a:w_run_drop
        bcs     :+
        asl                             ; Default edgefriction doubles friction.
:       clc
        adc     #2
        sta     a:w_run_drop
        lda     #5                      ; 4 / 20 seconds per step.
        sta     z:w_denominator
@Retry:
        lda     f:video_tick
        sta     z:w_mul_nmi
        lda     a:w_run_drop
        jsr     WalkDivideByte
        tax
        lda     f:video_tick
        cmp     z:w_mul_nmi
        bne     @Retry
        stx     a:w_run_drop
        lda     a:w_run_speed
        sec
        sbc     a:w_run_drop
        beq     @Stop
        bcc     @Stop
        jsr     WalkRunRatio
        sta     a:w_run_gain
        ldy     #2
@Scale:
        lda     a:w_velocity_x,y
        ldx     a:w_run_gain
        jsr     WalkMultiply
        lda     z:w_mul_low
        clc
        adc     #2048
        sta     z:w_mul_low
        bcc     :+
        inc     z:w_mul_high
:       jsr     WalkProductQ12
        sta     a:w_velocity_x,y
        dey
        dey
        bpl     @Scale
        rts
@Stop:
        stz     a:w_velocity_x
        stz     a:w_velocity_y
        rts

; Compute floor(sqrt(vx? + vy?)). Cardinal movement only needs abs().
WalkRunSpeed:
        lda     a:w_velocity_x
        beq     @OnlyY
        ldx     a:w_velocity_y
        beq     @Magnitude
        WALK_RUN_DOT w_velocity_x, w_velocity_x
        bra     WalkSquaredMagnitude
@OnlyY:
        lda     a:w_velocity_y
@Magnitude:
        cmp     #0
        bpl     :+
        neg
:       sta     a:w_run_speed
        rts

WalkSquaredMagnitude:
        stz     a:w_run_speed
        stz     a:w_temp
        ldx     #16
@Digit:
        .repeat 2
        asl     a:w_dot
        rol     a:w_dot_high
        rol     a:w_temp
        .endrepeat
        asl     a:w_run_speed
        lda     a:w_run_speed
        asl
        inc
        sta     a:w_run_trial
        lda     a:w_temp
        sec
        sbc     a:w_run_trial
        bcc     :+
        sta     a:w_temp
        inc     a:w_run_speed
:       dex
        bne     @Digit
        rts

; Stock SV_UserFriction probes from the feet, sixteen units forward and
; thirty-four down. The packed point hull is Q3 with eye height rebased.
WalkRunEdgeSupport:
        ldy     #2
@Axis:
        lda     a:w_velocity_x,y
        bpl     :+
        neg
:       jsr     WalkRunRatio
        clc
        adc     #16
        .repeat 5
        lsr
        .endrepeat
        ldx     a:w_velocity_x,y
        bpl     :+
        neg
:       sta     a:w_run_trial
        lda     a:w_from,y
        sta     a:w_base,y
        cmp     #$8000
        ror
        clc
        adc     a:w_run_trial
        sta     a:w_from,y
        sta     a:w_to,y
        dey
        dey
        bpl     @Axis
        lda     a:w_from+4
        sta     a:w_base+4
        cmp     #$8000
        ror
        sec
        sbc     #24*8
        sta     a:w_from+4
        sec
        sbc     #34*8
        sta     a:w_to+4
        jsr     ShotHull::WalkTrace
        .repeat 3, axis
        lda     a:w_base+2*axis
        sta     a:w_from+2*axis
        .endrepeat
        rts

WalkRunRatio:
        sta     z:w_numerator
        stz     z:w_numerator_high
        lda     a:w_run_speed
        sta     z:w_denominator
        stz     z:w_denominator_high
        jmp     WalkFraction

WalkRunRoundedQ8:
        lda     z:w_mul_low
        clc
        adc     #128
        xba
        and     #$00ff
        sta     a:w_temp
        lda     z:w_mul_high
        adc     #0
        xba
        and     #$ff00
        ora     a:w_temp
        rts

WalkRunClampAxis:
        bmi     @Negative
        cmp     #RUN_MAX_AXIS+1
        bcc     @Done
        lda     #RUN_MAX_AXIS
        rts
@Negative:
        cmp     #.loword(-RUN_MAX_AXIS)
        bcs     @Done
        lda     #.loword(-RUN_MAX_AXIS)
@Done:
        rts

WalkRunBeginSlide:
        lda     a:w_wish
        sta     a:w_run_slide
        lda     a:w_wish+2
        sta     a:w_run_slide+2
        rts

; Clip full velocity on each accepted-path plane. The movement sweep
; separately clips only the remaining displacement for this tick.
WalkRunClipSlide:
        lda     a:w_run_swimming
        bne     @Done
        lda     a:w_enter
        cmp     #WALK_NO_PLANE
        beq     @Blocked
        WALK_RUN_DOT w_run_slide, w_normal
        lda     a:w_dot_high
        bpl     @Done
        sta     z:w_mul_high
        lda     a:w_dot
        sta     z:w_mul_low
        jsr     WalkProductQ14
        sta     a:w_run_gain
        ldy     #2
@Axis:
        lda     a:w_normal,y
        ldx     a:w_run_gain
        jsr     WalkMultiply
        jsr     WalkProductQ14
        sta     a:w_temp
        lda     a:w_run_slide,y
        sec
        sbc     a:w_temp
        jsr     WalkRunClampAxis
        sta     a:w_run_slide,y
        dey
        dey
        bpl     @Axis
@Done:
        rts
@Blocked:
        stz     a:w_run_slide
        stz     a:w_run_slide+2
        rts

WalkRunSaveSlide:
        lda     a:w_run_swimming
        bne     @Done
        lda     a:w_run_slide
        sta     a:w_velocity_x
        lda     a:w_run_slide+2
        sta     a:w_velocity_y
@Done:
        rts
