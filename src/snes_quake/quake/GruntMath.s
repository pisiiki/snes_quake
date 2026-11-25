; Length and unit vector for stock range, infront, FireBullets and blood
; effects. Scale all components together before squaring to fit 32 bits.
GruntLength:
        jsr     GruntVectorLength
        lda     a:gr_root
        ldx     a:gr_length_shift
        beq     @Return
@Scale:
        asl
        bmi     @Saturate
        dex
        bne     @Scale
@Return:
        sta     a:qcg+2
        rts
@Saturate:
        lda     #$7fff
        bra     @Return

GruntNormalize:
        jsr     GruntVectorLength
        stz     a:gr_math_axis
        lda     a:gr_root
        sta     z:w_denominator
        stz     z:w_denominator_high
@Axis:
        ldy     a:gr_math_axis
        lda     a:gr_root
        beq     @Store
        lda     a:gr_vector,y
        sta     z:w_numerator
        stz     z:w_numerator_high
        jsr     ShotHull::WalkFraction
        clc
        adc     #32
        .repeat 6
        lsr
        .endrepeat
        ldy     a:gr_math_axis
        pha
        lda     a:qcg+8,y
        bpl     @Positive
        pla
        jsr     QCNegate
        bra     @Store
@Positive:
        pla
@Store:
        sta     a:qcg+2,y
        iny
        iny
        sty     a:gr_math_axis
        cpy     #6
        bcc     @Axis
        rts

GruntVectorLength:
        ldx     #4
        stz     a:gr_length_shift
@Abs:
        lda     a:qcg+8,x
        jsr     QCAbs
        sta     a:gr_vector,x
        dex
        dex
        bpl     @Abs
@Fit:
        lda     a:gr_vector
        ora     a:gr_vector+2
        ora     a:gr_vector+4
        cmp     #$2000
        bcc     GruntVectorSum
        lsr     a:gr_vector
        lsr     a:gr_vector+2
        lsr     a:gr_vector+4
        inc     a:gr_length_shift
        bra     @Fit
GruntVectorSum:
        stz     a:gr_sum_lo
        stz     a:gr_sum_hi
        ldy     #4
@Square:
        lda     a:gr_vector,y
        tax
        jsr     WalkMultiply
        lda     z:w_mul_low
        clc
        adc     a:gr_sum_lo
        sta     a:gr_sum_lo
        lda     z:w_mul_high
        adc     a:gr_sum_hi
        sta     a:gr_sum_hi
        dey
        dey
        bpl     @Square
        ; The old fourteen trial bits capped the root at $3fff.
        lda     a:gr_sum_hi
        cmp     #$1000
        bcc     @RootSetup
        lda     #$3fff
        bra     @RootDone
@RootSetup:
.if .defined(PLAYABLE_E1M1_TRACE_LAYOUT) && .defined(PLAYABLE_MAP_ID)
        jsl     GruntSeedRoot
.else
        ; The upper twelve bits contain six digits. The lower word feeds
        ; the next eight, with the same partial root and remainder.
        .repeat 4
        asl
        .endrepeat
        sta     z:w_mul_high
        ldx     #6
        ldy     #0
        tya
.endif
@SeedReady:
        jsr     @RootDigits
        pha
        lda     a:gr_sum_lo
        sta     z:w_mul_high
        pla
        ldx     #8
        jsr     @RootDigits
        tya
@RootDone:
        sta     a:gr_root
        ora     #1                     ; Keep the last legacy trial value.
        sta     a:gr_trial
        tax
        ldy     #$fffe
        stz     a:gr_bit
        lda     #0
        sec
        rts
@RootDigits:
        ; A holds the remainder and Y the partial root. Before the last
        ; digit, root <= 8191, so 4*remainder+3 <= 65531 fits a word.
        asl     z:w_mul_high
        rol
        asl     z:w_mul_high
        rol
        sta     z:w_mul_a
        tya
        asl
        tay
        asl
        inc
        sta     z:w_mul_b
        lda     z:w_mul_a
        sec
        sbc     z:w_mul_b
        bcs     @RootAccept
        adc     z:w_mul_b              ; Restore the remainder with carry clear.
        bra     @RootNext
@RootAccept:
        iny
@RootNext:
        dex
        bne     @RootDigits
        rts

.if .defined(PLAYABLE_E1M1_TRACE_LAYOUT) && .defined(PLAYABLE_MAP_ID)
        ; Preserve BSP_QUAKEC size so the packed texture window stays put.
        .res 13 - (@SeedReady - @RootSetup), $ea
.pushseg
.segment "BSP_CPU_WALK_RESUME"
GruntSeedRoot:
        RW_assume a16i16
        ; Decode the first three radix-four digits. Shift the six remaining
        ; high bits into the positions consumed by the restoring loop.
        asl
        asl
        xba
        sta     z:w_mul_high
        and     #$003f
        tax
        lda     f:GruntRootPrefix,x
        tax
        and     #$0070
        .repeat 4
        lsr
        .endrepeat
        tay
        txa
        and     #$000f
        ldx     #3
        rtl

GruntRootPrefix:
        ; Prefixes with root R run from R² through (R+1)²-1.
        .repeat 8, Root
          .repeat 2*Root+1, Remainder
            .byte (Root << 4) | Remainder
          .endrepeat
        .endrepeat
        .byte 0                         ; The final word load ignores this byte.
.popseg
.endif

GruntVectorYaw:
        lda     a:qcg+8
        ora     a:qcg+10
        beq     @Return
        lda     a:qcg+8
        jsr     QCAbs
        sta     z:w_denominator
        lda     a:qcg+10
        jsr     QCAbs
        sta     z:w_numerator
        cmp     z:w_denominator
        bcc     @Divide
        ldx     z:w_denominator
        sta     z:w_denominator
        stx     z:w_numerator
        lda     #1
        bra     @Flag
@Divide:
        lda     #0
@Flag:
        pha
        stz     z:w_numerator_high
        stz     z:w_denominator_high
        jsr     ShotHull::WalkFraction
        clc
        adc     #32
        .repeat 5
        lsr
        .endrepeat
        and     #$fffe
        tax
        pla
        beq     @Shallow
        lda     #90*64
        sec
        sbc     f:GruntAtan,x
        bra     @Quadrant
@Shallow:
        lda     f:GruntAtan,x
@Quadrant:
        ldx     a:qcg+8
        bpl     @Half
        sta     a:gr_trial
        lda     #180*64
        sec
        sbc     a:gr_trial
@Half:
        ldx     a:qcg+10
        bpl     @Return
        beq     @Return
        cmp     #0
        beq     @Return
        sta     a:gr_trial
        lda     #360*64
        sec
        sbc     a:gr_trial
@Return:
        sta     a:qcg+2
        rts

GruntChangeYaw:
        GRUNT_FIELD lda, QC_FIELD_IDEAL_YAW
        sec
        GRUNT_FIELD sbc, QC_FIELD_ANGLES+2
        bmi     @Left
        cmp     #180*64+1
        bcc     @Clamp
        sbc     #360*64
        bra     @Clamp
@Left:
        cmp     #.loword(-180*64)
        bcs     @Clamp
        clc
        adc     #360*64
@Clamp:
        cmp     #0                      ; The wrap comparisons left their own sign.
        bmi     @ClampLeft
        GRUNT_FIELD cmp, QC_FIELD_YAW_SPEED
        bcc     @Turn
        GRUNT_FIELD lda, QC_FIELD_YAW_SPEED
        bra     @Turn
@ClampLeft:
        pha
        GRUNT_FIELD lda, QC_FIELD_YAW_SPEED
        jsr     QCNegate
        sta     a:gr_trial
        pla
        cmp     a:gr_trial
        bcs     @Turn
        lda     a:gr_trial
@Turn:
        clc
        GRUNT_FIELD adc, QC_FIELD_ANGLES+2
        bpl     :+
        clc
        adc     #360*64
        bra     @Save
:       cmp     #360*64
        bcc     @Save
        sbc     #360*64
@Save:
        GRUNT_FIELD sta, QC_FIELD_ANGLES+2
        rts

QCOpDot:
.ifdef PLAYABLE_E1M1_LAZY_QC_OPERANDS
        jsr     QCReadOperands
.endif
        stz     a:gr_sum_lo
        .repeat 3, I
        ldx     z:qc_a
        lda     a:qcg+2*I,x
        pha
        ldx     z:qc_b
        lda     a:qcg+2*I,x
        sta     z:qc_rhs
        pla
        jsr     QCMulRound
        clc
        adc     a:gr_sum_lo
        sta     a:gr_sum_lo
        .endrepeat
        jmp     QCStoreResult

GruntAtan:
        .incbin "Data/QuakeBSPGruntAtan.bin"
