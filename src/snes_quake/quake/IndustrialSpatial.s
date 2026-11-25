; Stock stationary emitters use ATTN_STATIC. Combine emitters referencing the
; same waveform before updating its DSP voice, as Quake's static mixer does.
industrial_candidates = industrial_delta+4 ; Pan uses only X and Y deltas.
IndustrialTick:
        RW_assume a16i16
        phx
        phy
        phb
        pea     $0000
        plb
        plb
        inc     a:industrial_update
        lda     a:industrial_update
        lsr
        bcs     :+
        jmp     @Return
:       ; Select a conservative emitter mask using the high nibble of Q4 Y.
        lda     f:camera_y
        xba
        and     #$00f0
        lsr
        lsr
        lsr
        tax
        lda     f:IndustrialEmitterBands,x
        sta     a:industrial_candidates
        ldx     #6
@Clear: stz     a:industrial_left,x
        stz     a:industrial_right,x
        dex
        dex
        bpl     @Clear
        stz     a:industrial_spot
        jmp     @Candidate
@Spot:  stz     a:industrial_square
        .repeat 3, I
        ldx     a:industrial_spot
        lda     f:IndustrialSpots+I*2,x
        sec
        sbc     f:.ident(.sprintf("camera_%c", 120+I))
        .if I < 2
        sta     a:industrial_delta+I*2
        .endif
        bpl     :+
        neg
:       cmp     #INDUSTRIAL_HEARING_LIMIT_Q4
        bcc     :+
        jmp     @Next
:       clc
        adc     #128
        xba
        and     #255
        asl
        tax
        lda     f:TeleportAxisSquares,x
        clc
        adc     a:industrial_square
        sta     a:industrial_square
        .endrepeat
        ldx     #0
@Radius:cmp     f:TeleportRingSquares,x
        bcc     @Audible
        inx
        inx
        cpx     #32
        bcc     @Radius
        jmp     @Next
@Audible:
        txa
        eor     #30
        inc
        inc
        asl
        ldx     a:industrial_spot
        pha
        lda     f:IndustrialSpots+8,x
        cmp     #128
        pla
        bcc     :+
        asl
:       sta     a:industrial_gain
        jsr     IndustrialPan
        ldx     a:industrial_spot
        lda     f:IndustrialSpots+6,x
        tax
        lda     a:industrial_gain
        clc
        adc     a:industrial_pan
        clc
        adc     a:industrial_left,x
        cmp     #128
        bcc     :+
        lda     #127
:       sta     a:industrial_left,x
        lda     a:industrial_gain
        sec
        sbc     a:industrial_pan
        clc
        adc     a:industrial_right,x
        cmp     #128
        bcc     :+
        lda     #127
:       sta     a:industrial_right,x
@Next:  lda     a:industrial_spot
        clc
        adc     #10
        sta     a:industrial_spot
@Candidate:
        lsr     a:industrial_candidates
        bcc     :+
        jmp     @Spot
:       bne     @Next
@Mix:   ldx     #0
@Voice: lda     a:industrial_left,x
        ora     a:industrial_right,x
        tay
        ora     a:industrial_previous,x
        beq     @Skip
        tya
        sta     a:industrial_previous,x
        RW      a8
        lda     #GAMEPLAY_INDUSTRIAL_GAIN
        jsr     IndustrialCommand
        lda     f:IndustrialVoices,x
        jsr     IndustrialSend
        txa
        lsr
        clc
        adc     #GAMEPLAY_INDUSTRIAL_SRCN
        jsr     IndustrialSend
        lda     f:IndustrialPitches,x
        jsr     IndustrialSend
        lda     f:IndustrialPitches+1,x
        jsr     IndustrialSend
        lda     a:industrial_left,x
        jsr     IndustrialSend
        lda     a:industrial_right,x
        jsr     IndustrialSend
        lda     f:IndustrialMasks,x
        jsr     IndustrialSend
        RW      a16
@Skip:  inx
        inx
        cpx     #8
        bcc     @Voice
@Return:plb
        ply
        plx
        rtl
IndustrialPan:
        ; Listener-relative azimuth quantized to eight directions. For vertical
        ; separation alone both ears receive the same amount.
        ldx     #0
        lda     a:industrial_delta
        bpl     :+
        neg
        ldx     #4
:       sta     a:industrial_pan
        ldy     #2
        lda     a:industrial_delta+2
        bpl     :+
        neg
        ldy     #6
:       sta     a:industrial_square
        ora     a:industrial_pan
        bne     :+
        stz     a:industrial_pan
        rts
:       lda     a:industrial_square
        asl
        cmp     a:industrial_pan
        bcc     @Angle
        lda     a:industrial_pan
        asl
        cmp     a:industrial_square
        bcs     @Diagonal
        tyx
        bra     @Angle
@Diagonal:
        tya
        cmp     #2
        bne     @South
        txa
        lsr
        inc
        tax
        bra     @Angle
@South: txa
        lsr
        eor     #7
        tax
@Angle: lda     f:yaw_index
        clc
        adc     #16
        .repeat 5
        lsr
        .endrepeat
        sta     a:industrial_pan
        txa
        sec
        sbc     a:industrial_pan
        and     #7
        beq     @Center
        cmp     #4
        beq     @Center
        tay
        and     #1
        beq     @Side
        lda     a:industrial_gain
        lsr
        lsr
        sec
        sbc     a:industrial_gain
        neg                             ; Approximate sin(45 degrees) by three quarters.
        bra     @Signed
@Side:  lda     a:industrial_gain
@Signed:cpy     #4
        bcc     @Store
        neg
@Store: sta     a:industrial_pan
        rts
@Center:stz     a:industrial_pan
        rts
; The CPU module bank has room for the emitter data without growing the
; relocated walk segment. Both tables use long addressing from that segment.
.pushseg
.segment "CODE"
IndustrialSpots:
        INDUSTRIAL_SOURCE_TABLE
IndustrialEmitterBands:
        INDUSTRIAL_Y_BANDS
.popseg
IndustrialVoices: .word $30,$10,$50,$40
IndustrialMasks:  .word $08,$02,$20,$10
IndustrialPitches: .word INDUSTRIAL_PITCH_0, INDUSTRIAL_PITCH_1, INDUSTRIAL_PITCH_2, INDUSTRIAL_PITCH_3
