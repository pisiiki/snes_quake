; WinQuake PF_aim. The input forward vector is Q6, edict positions are Q3.
; Trace without firing pellets, activating shootable doors, or publishing trace globals.
PlayerAim:
        .repeat 3, I
        lda     a:qcg+8+2*I
        pha
        .endrepeat
        lda     a:qcg+20
        pha
        lda     a:qcg+26
        pha
        lda     a:qcg+QC_GLOBAL_TRACE_ENT
        pha
        stz     a:qcg+20
        lda     #QC_ENTITY_STRIDE
        sta     a:qcg+26
        stz     a:aim_best
        lda     #3810                   ; ceil(0.93 * 4096)
        sta     a:aim_score

        .repeat 3, I
        lda     a:shot_player+QC_FIELD_ORIGIN+2*I
        .if I = 2
        clc
        adc     #20*8
        .endif
        sta     a:w_from+2*I
        lda     a:qcg+QC_GLOBAL_FORWARD+2*I
        xba
        and     #$ff00                  ; 2048 * 8 / 64
        clc
        adc     a:w_from+2*I
        sta     a:w_to+2*I
        .endrepeat
        jsl     PlayerAimTrace
        tax
        beq     @Acquire
        lda     a:qce+QC_FIELD_TAKEDAMAGE,x
        cmp     #2*64                   ; DAMAGE_AIM
        bne     @Acquire
        jmp     @Finish
@Acquire:
        lda     #QC_GRUNT
@Next:
        sta     a:aim_actor
        tax
        lda     a:qce+QC_FIELD_TAKEDAMAGE,x
        cmp     #2*64
        bne     @Advance
        ldy     #0
@Center:
        lda     a:qce+QC_FIELD_MINS,x
        clc
        adc     a:qce+QC_FIELD_MAXS,x
        cmp     #$8000
        ror
        clc
        adc     a:qce+QC_FIELD_ORIGIN,x
        sta     a:w_to,y
        sec
        sbc     a:w_from,y
        sta     a:qcg+8,y
        inx
        inx
        iny
        iny
        cpy     #6
        bcc     @Center
        jsl     PlayerAimNormalize
        jsr     PlayerAimScore
        bmi     @Advance
        cmp     a:aim_score
        bcc     @Advance
        pha
        jsl     PlayerAimTrace
        cmp     a:aim_actor
        bne     @Hidden
        sta     a:aim_best
        pla
        sta     a:aim_score
        bra     @Advance
@Hidden:
        pla
@Advance:
        lda     a:aim_actor
        cmp     #QC_EXPLOBOX
        beq     @Finish
        clc
        adc     #QC_ENTITY_STRIDE
        cmp     #QC_GRUNT_DROP
        bcc     @Next
        lda     #QC_EXPLOBOX
        bra     @Next
@Finish:
        ldx     a:aim_best
        bne     @Adjust
        ldx     #4
@Forward:
        lda     a:qcg+QC_GLOBAL_FORWARD,x
        sta     a:qcg+2,x
        dex
        dex
        bpl     @Forward
        bra     @Restore
@Adjust:
        .repeat 3, I
        lda     a:qce+QC_FIELD_ORIGIN+2*I,x
        sec
        sbc     a:shot_player+QC_FIELD_ORIGIN+2*I
        sta     a:qcg+8+2*I
        .endrepeat
        stz     a:aim_distance
        ldy     #0
@Range:
        lda     a:qcg+QC_GLOBAL_FORWARD,y
        sta     z:qc_rhs
        lda     a:qcg+8,y
        phy
        jsl     PlayerAimMultiply
        ply
        clc
        adc     a:aim_distance
        sta     a:aim_distance
        iny
        iny
        cpy     #6
        bcc     @Range
        .repeat 2, I
        lda     a:qcg+QC_GLOBAL_FORWARD+2*I
        sta     z:qc_rhs
        lda     a:aim_distance
        jsl     PlayerAimMultiply
        sta     a:qcg+8+2*I
        .endrepeat
        jsl     PlayerAimNormalize
@Restore:
        .repeat 3, I
        lda     a:qcg+2+2*I
        sta     a:.loword(aim_vector_wram)+2*I
        .endrepeat
        pla
        sta     a:qcg+QC_GLOBAL_TRACE_ENT
        pla
        sta     a:qcg+26
        pla
        sta     a:qcg+20
        .repeat 3, I
        pla
        sta     a:qcg+12-2*I
        .endrepeat
        rtl

; Dot(unit,forward) in signed Q12 so the stock .93 threshold does not
; round down to a wider aim cone. Normalization itself uses the VM's Q6 ABI.
PlayerAimScore:
        stz     a:aim_dot
        ldy     #0
@Axis:
        lda     a:qcg+QC_GLOBAL_FORWARD,y
        .repeat 6
        asl
        .endrepeat
        sta     z:qc_rhs
        lda     a:qcg+2,y
        phy
        jsl     PlayerAimMultiply
        ply
        clc
        adc     a:aim_dot
        sta     a:aim_dot
        iny
        iny
        cpy     #6
        bcc     @Axis
        lda     a:aim_dot
        rts

.pushseg
.segment "BSP_QUAKEC"
PlayerAimNormalize:
        jsr     GruntNormalize
        rtl
PlayerAimMultiply:
        jsr     QCMulRound
        rtl
PlayerAimTrace:
.ifdef PLAYABLE_POINT_SIGHT_CACHE
        jsr     ShotHull::WalkSightTrace
.else
        jsr     ShotHull::WalkTrace
.endif
        stz     a:qcg+QC_GLOBAL_TRACE_ENT
        bcs     :+
        lda     #4096
        sta     z:w_lo
:       jsr     GruntTraceActor
        lda     a:qcg+QC_GLOBAL_TRACE_ENT
        rtl
.popseg
