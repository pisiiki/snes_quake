; Mouse 2 contributes movement buttons and signed fine-angle look deltas.
; One raw count is 1/256 turn. 3x consumes up to four counts every video tick;
; 2x consumes eight every other tick. Both retain the bounded accumulator.
FLY_MOUSE_STEP = 8
FLY_MOUSE_LIMIT = FLY_MOUSE_STEP * 2 - 1

InitFlyMouse:
        RW_assume a16i16
        ldx     #FlyMouseStateEnd-FlyMouseState-2
@Clear:
        stz     FlyMouseState,x
        dex
        dex
        bpl     @Clear
        rts

; libSFX has already completed automatic joypad readout. Only consume the
; mouse's remaining 16 serial bits while flying with the menu closed. Port 1
; keeps stock joypad polling; no synthetic cursor or mouse fallback is needed.
PollFlyMouse:
        RW_assume a16i16
        inc     fly_mouse_poll_counter
        stz     fly_mouse_status
        stz     fly_mouse_raw_x
        RW      a8
        lda     JOY2L
        and     #$0F
        cmp     #$01
        bne     @Done
        sta     fly_mouse_status
        lda     JOY2L
        and     #$C0
        sta     fly_mouse_buttons
        ldx     #8
@Y:
        lda     JOYB
        lsr
        rol     fly_mouse_raw_y
        dex
        bne     @Y
        ldx     #8
@X:
        lda     JOYB
        lsr
        rol     fly_mouse_raw_x
        dex
        bne     @X
        lda     fly_mouse_raw_x
        bpl     :+
        and     #$7F
        neg
:
        sta     fly_mouse_raw_x
        lda     fly_mouse_raw_y
        bpl     :+
        and     #$7F
        neg
:
        sta     fly_mouse_raw_y
@Done:
        RW      a16
        rts

ReadFlyMouseControls:
        RW_assume a16i16
        stz     fly_mouse_yaw_step
        stz     fly_mouse_pitch_step
        lda     fly_mouse_status
        and     #$00FF
        cmp     #$0001
        beq     @Mouse
@Clear:
        stz     fly_mouse_dx
        stz     fly_mouse_dy
        rts
@Mouse:
        lda     fly_mouse_raw_x
        and     #$00FF
        cmp     #$0080
        bcc     :+
        ora     #$FF00
:
        clc
        adc     fly_mouse_dx
        jsr     ClampFlyMouseDelta
        sta     fly_mouse_dx
        lda     fly_mouse_raw_y
        and     #$00FF
        cmp     #$0080
        bcc     :+
        ora     #$FF00
:
        clc
        adc     fly_mouse_dy
        jsr     ClampFlyMouseDelta
        sta     fly_mouse_dy
        lda     fly_mouse_buttons
        and     #$0040
        beq     :+
        lda     camera_input_buttons
        ora     #JOY_X
        sta     camera_input_buttons
:
        lda     fly_mouse_buttons
        and     #$0080
        beq     :+
        lda     camera_input_buttons
        ora     #JOY_B
        sta     camera_input_buttons
:
        lda     fly_playback_mode
        cmp     #RUNTIME_MENU_PLAYBACK_FLY3X
        beq     @Consume
        lda     control_divider
        and     #$0001
        bne     @Done
@Consume:
        lda     fly_mouse_dx
        beq     @Vertical
        jsr     ConsumeFlyMouseStep
        sta     fly_mouse_yaw_step
        lda     fly_mouse_dx
        sec
        sbc     fly_mouse_yaw_step
        sta     fly_mouse_dx
@Vertical:
        lda     fly_mouse_dy
        beq     @Done
        jsr     ConsumeFlyMouseStep
        sta     fly_mouse_pitch_step
        lda     fly_mouse_dy
        sec
        sbc     fly_mouse_pitch_step
        sta     fly_mouse_dy
        lda     fly_mouse_pitch_step
        neg
        sta     fly_mouse_pitch_step
@Done:
        rts

ConsumeFlyMouseStep:
        RW_assume a16i16
        bmi     @Negative
        cmp     fly_look_step_limit
        bcc     @Done
        lda     fly_look_step_limit
        rts
@Negative:
        neg
        cmp     fly_look_step_limit
        bcc     :+
        lda     fly_look_step_limit
:
        neg
@Done:
        rts

ClampFlyMouseDelta:
        RW_assume a16i16
        bmi     @Negative
        cmp     #FLY_MOUSE_LIMIT+1
        bcc     @Done
        lda     #FLY_MOUSE_LIMIT
        rts
@Negative:
        cmp     #.loword(-FLY_MOUSE_LIMIT)
        bcs     @Done
        lda     #.loword(-FLY_MOUSE_LIMIT)
@Done:
        rts
