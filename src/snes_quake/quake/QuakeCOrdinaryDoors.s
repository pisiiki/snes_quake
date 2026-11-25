; Eight authored ordinary movers. State 0 rests, 1 moves out, 2 waits,
; 3 returns and 4 stays open. Positions come directly from stock Q6 callbacks.
QCOrdDoorsTick:
        lda     a:qc_ord_shot_cooldown
        beq     :+
        dec     a:qc_ord_shot_cooldown
:       lda     a:qc_ord_hint_wait
        beq     :+
        dec     a:qc_ord_hint_wait
:       lda     a:qce+QC_ENTITY_STRIDE+QC_FIELD_HEALTH
        beq     @Motion
        bmi     @Motion
        lda     a:.loword(qc_sd_eye)+2
        xba
        lsr
        lsr
        and     #63
        tax
        lda     f:QCOrdTouchYMask,x
        and     #$ff
        beq     @Motion
        sta     a:qc_ord_interest
        ldx     #12                     ; *16 is a shootable receiver.
        ldy     #2
@Box:   lsr     a:qc_ord_interest
        bcc     @Next
        lda     a:.loword(qc_ord_state),y
        bne     @Next
        jsr     QCOrdTouches
        bcc     @Next
        phx
        phy
        tyx
        jsr     QCOrdUse
        ply
        plx
@Next:  txa
        clc
        adc     #12
        tax
        iny
        iny
        cpy     #2*QC_ORD_DOOR_COUNT
        bcc     @Box
        lda     a:qc_ord_interest
        beq     @Motion
        lda     a:qc_ord_hint_wait
        ora     a:.loword(qc_ord_state)+14
        bne     @Motion
        jsr     QCOrdTouches
        bcc     @Motion
        lda     #128
        sta     a:qc_ord_hint_wait
        sta     a:.loword(hub_warning_ticks)
        lda     #QC_ORD_DOOR_HINT_GATE
        sta     a:.loword(hub_warning_gate)
        inc     a:.loword(hub_warning_events)
        lda     #10
        jsr     QCSecretSound
@Motion:
        lda     a:qc_ord_in_motion
        beq     @Done
        ldx     #0
@Door:  lda     a:.loword(qc_ord_state),x
        beq     @Skip
        cmp     #4
        beq     @Skip
        phx
        jsr     QCOrdAdvance
        plx
@Skip:  inx
        inx
        cpx     #2*QC_ORD_DOOR_COUNT
        bcc     @Door
@Done:  rts

QCOrdTouches:
.repeat 3, I
        lda     a:.loword(qc_sd_eye)+I*2
        sec
        sbc     f:QCOrdBoxes+I*4,x
        cmp     f:QCOrdBoxes+I*4+2,x
        bcs     @Outside
.endrepeat
        sec
        rts
@Outside:
        clc
        rts
.assert QCOrdHintBox-QCOrdBoxes = 12*QC_ORD_DOOR_COUNT, error, "ordinary door hint follows trigger bounds"

QCOrdShot:
        lda     a:qc_ord_shot_cooldown
        bne     QCOrdReturn
        lda     #13
        sta     a:qc_ord_shot_cooldown
        ldx     #0
        lda     a:.loword(qc_ord_state)
        cmp     #2
        bne     @Try
        lda     f:QCOrdWait
        sta     a:.loword(qc_ord_wait)
        rts
@Try:   cmp     #3
        bne     @Rest
        jmp     QCHydraulicReverse
@Rest:  cmp     #0
        bne     QCOrdReturn
QCOrdUse:
        inc     a:qc_ord_in_motion
        lda     #0
QCOrdBegin:
        sta     a:.loword(qc_ord_age),x
        lda     #1
        sta     a:.loword(qc_ord_state),x
        cpx     #6
        bcc     QCOrdOpenSound
        cpx     #14                     ; *38 is silent.
        beq     QCOrdReturn
        lda     f:QCExitBits-6,x
        ora     a:.loword(qc_ord_lights)
        sta     a:.loword(qc_ord_lights)
        inc     a:.loword(quakec_sounds) ; Relay and motor are simultaneous.
        lda     #7
        jsl     GameplayPlayTrackLong
QCOrdReturn:
        rts
QCOrdOpenSound:
        cpx     #4
        bne     @Hydro
        lda     #6
        jsl     GameplayPlayTrackLong
        rts
@Hydro: lda     #GAMEPLAY_AUX_LIFT_RUN
QCOrdAuxSound:
        inc     a:.loword(quakec_sounds)
        jsl     GameplayPlayAuxSound
        rts

QCOrdAdvance:
        cmp     #2
        bne     @Travel
        dec     a:.loword(qc_ord_wait),x
        bne     QCOrdReturn
        inc     a:.loword(qc_ord_state),x
        stz     a:.loword(qc_ord_age),x
        cpx     #4
        bne     QCOrdOpenSound
        rts
@Travel:
        inc     a:.loword(qc_ord_age),x
        cpx     #0
        bne     @Table
        jsr     QCHydraulicStep
        bcc     @Position
        rts
@Table:
        cmp     #1
        bne     @Back
        lda     f:QCOrdOutBase,x
        clc
        adc     a:.loword(qc_ord_age),x
        asl
        phx
        tax
        lda     f:QCOrdOut,x
        plx
        bra     @Position
@Back:  lda     f:QCOrdBackBase,x
        clc
        adc     a:.loword(qc_ord_age),x
        asl
        phx
        tax
        lda     f:QCOrdBack,x
        plx
@Position:
        cmp     a:.loword(qc_ord_offsets),x
        beq     @CheckEnd
        sta     a:.loword(qc_ord_offsets),x
        sec
        sbc     f:QCOrdRest,x
        bpl     :+
        eor     #$ffff
        inc
:       clc
        adc     #32
.repeat 6
        lsr
.endrepeat
        cmp     a:.loword(qc_ord_pose),x
        beq     :+
        sta     a:.loword(qc_ord_pose),x
        inc     a:.loword(qc_sd_revision)
:       stz     a:w_support_valid
        lda     #1
        sta     a:qc_exit_collision_dirty
@CheckEnd:
        lda     a:.loword(qc_ord_age),x
        cmp     f:QCOrdDuration,x
        bne     @Done
        lda     a:.loword(qc_ord_state),x
        cmp     #3
        bne     @OutEnd
        stz     a:.loword(qc_ord_state),x
        dec     a:qc_ord_in_motion
        bra     @Sound
@OutEnd:
        lda     f:QCOrdWait,x
        beq     @Permanent
        sta     a:.loword(qc_ord_wait),x
        inc     a:.loword(qc_ord_state),x
        cpx     #4
        bne     @Sound
        inc     a:.loword(quakec_activations)
        ldx     #QC_DOOR
        ldy     #QC_ENTITY_STRIDE
        lda     a:qce+QC_DOOR+QC_FIELD_USE
        jmp     QuakeCEvent
@Permanent:
        dec     a:qc_ord_in_motion
        lda     #4
        sta     a:.loword(qc_ord_state),x
@Sound: cpx     #4
        beq     @Done
        cpx     #14
        beq     @Done
        bcc     :+
        rts
:       cpx     #4
        bcs     @RelayStop
        lda     #GAMEPLAY_AUX_LIFT_END
        jmp     QCOrdAuxSound
@RelayStop:
        lda     #8
        jsl     GameplayPlayTrackLong
@Done:  rts

; *15 immediately follows the two platforms in the dynamic hull selector
; table and shares their checked push, rollback and pending-player position.
.assert qc_ord_offsets = quakec_platform_q4+4, error, "hydraulic door offset must follow both platforms"
QCHydraulicStep:
        ldy     a:.loword(qc_ord_wait)
        beq     @Sweep
        ; SUB_CalcMove uses zero velocity and then snaps for trips < 0.1 s.
        lda     a:.loword(qc_ord_age)
        cmp     f:QCOrdDuration
        beq     @Snap
        lda     a:.loword(qc_ord_offsets)
        clc
        rts
@Snap:  stz     a:.loword(qc_ord_wait)
        lda     a:.loword(qc_ord_state)
        cmp     #1
        beq     @Zero
        lda     f:QCOrdRest
        clc
        rts
@Zero:  lda     #0
        clc
        rts
@Sweep: lda     a:.loword(qc_ord_offsets)
        ldy     a:.loword(qc_ord_state)
        cpy     #1
        bne     @Down
        clc
        adc     #25                     ; 100 units/s in Q4 per Q6 tick.
        bmi     @Candidate
        lda     #0
        bra     @Candidate
@Down:  sec
        sbc     #25
        cmp     f:QCOrdRest
        bcs     @Candidate
        lda     f:QCOrdRest
@Candidate:
        sta     a:qc_plat_next
        sec
        sbc     a:.loword(qc_ord_offsets)
        sta     a:qc_plat_delta
        ldx     #4
@Eye:   lda     a:.loword(qc_sd_eye),x
        sta     a:qc_exit_eye,x
        dex
        dex
        bpl     @Eye
        ldx     #4
        stx     a:qc_plat_slot
        jsr     QCPlatformCarry
        ldx     #0
        bcs     @Blocked
        ; A supported descent temporarily publishes the new hull for its sweep.
        lda     a:qc_plat_next
        sec
        sbc     a:qc_plat_delta
        sta     a:.loword(qc_ord_offsets)
.ifdef PLAYABLE_E1M1_WALK_RESUME_BYTES
        jsl     MarkTraceResultCacheDirty
.endif
        lda     a:qc_plat_next
        clc
        rts
@Blocked:
        lda     #2*64
.ifdef QC_ARMOR_COUNT
        jsl     ArmorEnvironmentDamage
.endif
        eor     #$ffff
        sec
        adc     a:qce+QC_ENTITY_STRIDE+QC_FIELD_HEALTH
        sta     a:qce+QC_ENTITY_STRIDE+QC_FIELD_HEALTH
        lda     #4
        sta     a:grunt_damage_flash
        jsr     QCHydraulicReverse
        sec
        rts

QCHydraulicReverse:
        lda     a:.loword(qc_ord_state)
        eor     #2
        sta     a:.loword(qc_ord_state)
        cmp     #1
        beq     @Outward
        lda     a:.loword(qc_ord_offsets)
        sec
        sbc     f:QCOrdRest
        bra     @Distance
@Outward:
        lda     #0
        sec
        sbc     a:.loword(qc_ord_offsets)
@Distance:
        stz     a:.loword(qc_ord_wait)
        cmp     #160
        bcs     @Long
        inc     a:.loword(qc_ord_wait)
        lda     f:QCOrdDuration
        sec
        sbc     #7
        bra     @Set
@Long:  tay
        lda     f:QCOrdDuration
        tax
        tya
@Tick:  dex
        sec
        sbc     #25
        beq     @Age
        bcs     @Tick
@Age:   txa
@Set:   sta     a:.loword(qc_ord_age)
        ldx     #0
        jmp     QCOrdOpenSound
