; State 0 closed, 1/3 opening legs, 2/6 corner dwells, 4 open dwell,
; 5/7 closing legs, 8 permanently open. Distance along the path is Q5.
QCSecretDoorsTick:
        lda     a:qc_sd_hint_wait
        beq     :+
        dec     a:qc_sd_hint_wait
:       lda     a:qce+QC_ENTITY_STRIDE+QC_FIELD_HEALTH
        beq     @NoTouches
        bpl     @LivingPlayer
@NoTouches:
        jmp     @Motion
@LivingPlayer:
        ldx     #4
        lda     f:walk_pending
        beq     @Camera
@Pending:
        lda     f:WalkPendingXYZ,x
        sta     a:.loword(qc_sd_eye),x
        dex
        dex
        bpl     @Pending
        bra     @Touch
@Camera:
        lda     f:camera_x,x
        sta     a:.loword(qc_sd_eye),x
        dex
        dex
        bpl     @Camera
@Touch:
        ldx     #0
        ldy     #0
@Box:
        jsr     QCSecretTouches
        bcc     @Next
        phx
        phy
        tyx
        cpy     #4
        bcs     @StartDoor
        lda     f:QCT3TouchBits,x
        bit     a:.loword(qc_t3_state_wram)
        bne     @Touched
        ora     a:.loword(qc_t3_state_wram)
        eor     #16
        sta     a:.loword(qc_t3_state_wram)
        lda     #9                      ; misc/trigger1.wav, independent of the door's SPC voice.
        jsl     GameplayPlayTrackLong
        tyx
@StartDoor:
        lda     f:QCSecretTouchOwners,x
        tax
        jsr     QCSecretDoorStart
@Touched:
        ply
        plx
@Next:  txa
        clc
        adc     #12
        tax
        iny
        iny
        cpy     #2*QC_SECRET_DOOR_TOUCH_COUNT
        bcc     @Box
        lda     a:qc_sd_hint_wait
        ora     a:.loword(qc_sd_state)+12
        bne     @Motion
        ; The hint bounds immediately follow the four touch volumes.
        jsr     QCSecretTouches
        bcc     @Motion
        lda     #128
        sta     a:qc_sd_hint_wait
        sta     a:.loword(hub_warning_ticks)
        lda     #QC_SECRET_DOOR_HINT_GATE
        sta     a:.loword(hub_warning_gate)
        inc     a:.loword(hub_warning_events)
        lda     #10
        jsr     QCSecretSound
@Motion:
        ldx     #0
@Door:  lda     a:.loword(qc_sd_state),x
        beq     @Skip
        cmp     #8
        beq     @Skip
        stx     a:qc_sd_slot
        jsr     QCSecretDoorAdvance
        ldx     a:qc_sd_slot
@Skip:  inx
        inx
        cpx     #2*QC_SECRET_DOOR_COUNT
        bcc     @Door
        rts

QCSecretTouches:
.repeat 3, I
        lda     a:.loword(qc_sd_eye)+I*2
        sec
        sbc     f:QCSecretTouchBoxes+I*4,x
        cmp     f:QCSecretTouchBoxes+I*4+2,x
        bcs     @Outside
.endrepeat
        sec
        rts
@Outside:
        clc
        rts
.assert QCSecretHintBox-QCSecretTouchBoxes = 12*QC_SECRET_DOOR_TOUCH_COUNT, error, "secret door hint bounds must follow touch volumes"

QCSecretDoorShot:
        ; Point-hull terminals -64..-70 identify doors, -71 their shootable switch.
        lda     a:qcg+QC_GLOBAL_SELF
        cmp     #QC_ENTITY_STRIDE
        beq     @Player
        cmp     #QC_GRUNT_DROP
        bne     QCSecretReturn
        lda     a:qcg+26
        cmp     #QC_ENTITY_STRIDE
        bne     QCSecretReturn
@Player:
        lda     a:qcg+20
        ora     a:qcg+QC_GLOBAL_TRACE_ENT
        bne     QCSecretReturn
        lda     a:qc_sd_source
        cmp     #.loword(-72)
        bne     :+
        jmp     QCOrdShot
:       lda     #$ffc0
        sec
        sbc     a:qc_sd_source
        cmp     #8
        bcs     QCSecretReturn
        tax
        lda     f:QCSecretShotOwners,x
        and     #$00ff
        cmp     #$ff
        beq     QCSecretReturn
        tax
QCSecretDoorStart:
        lda     a:.loword(qc_sd_state),x
        bne     QCSecretReturn
        inc     a:.loword(qc_sd_state),x
        lda     #GAMEPLAY_SECRET_DOOR_STOP
        jsr     QCSecretSound
        lda     #GAMEPLAY_SECRET_DOOR_MOVE
QCSecretSound:
        inc     a:.loword(quakec_sounds)
        jsl     GameplayPlaySoundLong
QCSecretReturn:
        rts

QCSecretDoorAdvance:
        lsr
        bcs     @Moving
        dec     a:.loword(qc_sd_wait),x
        bne     QCSecretReturn
        inc     a:.loword(qc_sd_state),x
        lda     #GAMEPLAY_SECRET_DOOR_MOVE
        bra     QCSecretSound
@Moving:
        lda     a:.loword(qc_sd_state),x
        cmp     #5
        bcs     @Closing
        cmp     #1
        beq     @FirstOut
        lda     f:QCSecretTravelQ5,x
        bra     @Opening
@FirstOut:
        lda     #512
@Opening:
        sta     a:qc_sd_data
        lda     a:.loword(qc_sd_travel),x
        clc
        adc     #25
        cmp     a:qc_sd_data
        bcc     @Store
        bra     @Stop
@Closing:
        lda     a:.loword(qc_sd_state),x
        cmp     #7
        beq     :+
        lda     #512
        bra     @ReturnTarget
:       lda     #0
@ReturnTarget:
        sta     a:qc_sd_data
        lda     a:.loword(qc_sd_travel),x
        sec
        sbc     #25
        bcc     @Stop
        cmp     a:qc_sd_data
        bcc     @Stop
        bne     @Store
@Stop:  inc     a:.loword(qc_sd_state),x
        lda     a:.loword(qc_sd_state),x
        cmp     #8
        beq     @Closed
        cmp     #4
        beq     @Opened
        lda     #64
        bra     @Wait
@Opened:
        lda     f:QCSecretOpenWait,x
        bne     @Wait
        lda     #8
        sta     a:.loword(qc_sd_state),x
        bra     @Sound
@Closed:
        stz     a:.loword(qc_sd_state),x
        bra     @Sound
@Wait:  sta     a:.loword(qc_sd_wait),x
@Sound: lda     #GAMEPLAY_SECRET_DOOR_STOP
        jsr     QCSecretSound
        lda     a:qc_sd_data
@Store: sta     a:.loword(qc_sd_travel),x
        ; Round Q5 to Q4, ties to even, just like the original sampled BSP poses.
        lsr
        bcc     :+
        bit     #1
        beq     :+
        inc
:       sta     a:qc_sd_data
        clc
        adc     #32
.repeat 6
        lsr
.endrepeat
        cmp     a:.loword(qc_sd_pose),x
        beq     :+
        sta     a:.loword(qc_sd_pose),x
        inc     a:.loword(qc_sd_revision)
:       txa
        asl
        clc
        adc     f:QCSecretFirstAxis,x
        tay
        lda     a:qc_sd_data
        cmp     #257
        bcc     :+
        lda     #256
:       pha
        lda     f:QCSecretFirstSign,x
        beq     :+
        pla
        eor     #$ffff
        inc
        pha
:       pla
        sta     a:.loword(qc_sd_offsets),y
        tya
        eor     #2
        tay
        lda     a:qc_sd_data
        sec
        sbc     #256
        bcs     :+
        lda     #0
:       pha
        lda     f:QCSecretSecondSign,x
        beq     :+
        pla
        eor     #$ffff
        inc
        pha
:       pla
        sta     a:.loword(qc_sd_offsets),y
        stz     a:w_support_valid
.ifdef WALK_IMPACT_CACHE_BYTES
        jsr     QCPlatformInvalidateImpacts
.endif
        lda     #1
        sta     a:qc_exit_collision_dirty
@Done:  rts
