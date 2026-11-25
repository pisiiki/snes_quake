; Decode the two point-impact temp entities and the stock svc_particle blood.
; World positions are rebased Q3. Delta is 1/8 Q3 per 20 Hz gameplay tick.
CombatImpactByte:
        lda     a:qcg+14
        cmp     #23*64                  ; svc_temp_entity starts a new message
        bne     @Type
        lda     #1
        sta     a:impact_message
        rtl
@Type:  ldx     a:impact_message
        cpx     #1
        bne     @Cancel
        ldx     #0                      ; TE_SPIKE, ten neutral particles
        cmp     #0
        beq     @Coords
        ldx     #5                      ; TE_GUNSHOT, twenty neutral particles
        cmp     #2*64
        bne     @Cancel
@Coords:
        stx     a:impact_style
        lda     #2
        sta     a:impact_message
        rtl
@Cancel:
        stz     a:impact_message
        rtl

CombatImpactCoord:
        ldx     a:impact_message
        cpx     #2
        bcc     @Done
        lda     a:qcg+14
        sta     a:impact_origin-2,x
        stz     a:impact_delta-2,x
        inx
        inx
        cpx     #8
        beq     @Spawn
        stx     a:impact_message
@Done:  rtl
@Spawn: stz     a:impact_message
        jmp     CombatImpactSpawn

CombatImpactBlood:
        lda     a:qcg+26
        beq     :+
        bpl     @Valid
:       rtl
@Valid:
        ldx     #10                     ; blood rows for 8/18/40/80 particles
        cmp     #9*64
        bcc     @Count
        ldx     #15
        cmp     #19*64
        bcc     @Count
        ldx     #20
        cmp     #41*64
        bcc     @Count
        ldx     #25
@Count: stx     a:impact_style
        ldy     #0
@Axis:  lda     a:qcg+8,y
        sta     a:impact_origin,y
        lda     a:qcg+QC_GLOBAL_SELF
        cmp     #QC_GRUNT_DROP
        bne     @Direction
        ; spawn_touchblood adds vel*.01 to its origin before SpawnBlood
        ; sends dir=vel*.1. Its Q6-to-Q3 coefficient .01/8 cannot be
        ; encoded in the VM operand. Recover the displacement as dirQ6/80.
        lda     a:qcg+14,y
        bpl     :+
        jsr     CombatImpactNegate
:       clc
        adc     #40
        ldx     #0
@Divide:
        cmp     #80
        bcc     @Offset
        sbc     #80
        inx
        bra     @Divide
@Offset:
        lda     a:qcg+14,y
        bpl     :+
        txa
        jsr     CombatImpactNegate
        bra     @Add
:       txa
@Add:   clc
        adc     a:impact_origin,y
        sta     a:impact_origin,y
@Direction:
        lda     a:qcg+14,y              ; MSG_WriteChar clamps dir * 16
        bpl     :+
        clc
        adc     #3
:       .repeat 2
        cmp     #$8000
        ror
        .endrepeat
        bmi     @Negative
        cmp     #128
        bcc     @Wire
        lda     #127
        bra     @Wire
@Negative:
        cmp     #$ff80
        bcs     @Wire
        lda     #$ff80
@Wire:  sta     a:impact_delta,y
        asl
        clc
        adc     a:impact_delta,y
        sta     a:impact_delta,y
        iny
        iny
        cpy     #6
        bcc     @Axis
        jmp     CombatImpactSpawn

CombatImpactNegate:
        eor     #$ffff
        inc
        rts

.pushseg
.segment "BSP_QUAKEC"
CombatImpactSpikeBlood:
        phx
        ldx     a:.loword(nail_slot)
        .repeat 3, I
        lda     a:qcg+QC_GLOBAL_TRACE_ENDPOS+2*I
        sta     a:qce+QC_GRUNT_DROP+QC_FIELD_ORIGIN+2*I
        lda     f:nails+NAIL_DELTA+2*I,x
        sta     a:qce+QC_GRUNT_DROP+QC_FIELD_VELOCITY+2*I
        .endrepeat
        lda     #9*64
        sta     a:qcg+8
        lda     #4096
        sta     z:qc_budget
        lda     #QC_NAIL_BLOOD
        jsr     QuakeCInvokeOuter
        plx
        rts
.popseg

; The native nail sweep sends TE_SPIKE at a solid surface.
CombatImpactSpike:
        stz     a:impact_style
        .repeat 3, I
        lda     a:qcg+QC_GLOBAL_TRACE_ENDPOS+2*I
        sta     a:impact_origin+2*I
        stz     a:impact_delta+2*I
        .endrepeat
CombatImpactSpawn:
        ldx     a:impact_next
        txa
        jsr     CombatImpactNext
        cmp     #IMPACT_END
        bcc     :+
        lda     #0
:       sta     a:impact_next
        lda     a:impact_records+IMPACT_LIFE,x
        bne     :+
        inc     a:impact_active
:       lda     #9
        sta     a:impact_records+IMPACT_LIFE,x
        lda     a:impact_style
        clc
        adc     #QC_IMPACT_ROW
        sta     a:impact_records+IMPACT_ROW,x
        .repeat 3, I
        lda     a:impact_origin+2*I
        sta     a:impact_records+IMPACT_POS+2*I,x
        lda     a:impact_delta+2*I
        sta     a:impact_records+IMPACT_DELTA+2*I,x
        stz     a:impact_records+IMPACT_REM+2*I,x
        .endrepeat
        rtl

CombatImpactTick:
        lda     a:impact_active
        beq     @Done
        ldx     #0
@Scan:  lda     a:impact_records+IMPACT_LIFE,x
        beq     @Next
        dec     a:impact_records+IMPACT_LIFE,x
        beq     @Expired
        ldy     #3
@Move:  lda     a:impact_records+IMPACT_REM,x
        clc
        adc     a:impact_records+IMPACT_DELTA,x
        pha
        and     #7
        sta     a:impact_records+IMPACT_REM,x
        pla
        .repeat 3
        cmp     #$8000
        ror
        .endrepeat
        clc
        adc     a:impact_records+IMPACT_POS,x
        sta     a:impact_records+IMPACT_POS,x
        inx
        inx
        dey
        bne     @Move
        txa
        sec
        sbc     #6
        bra     @Advance
@Expired:
        dec     a:impact_active
        beq     @Done
@Next:  txa
@Advance:
        jsr     CombatImpactNext
        tax
        cpx     #IMPACT_END
        bcc     @Scan
@Done:  rtl

; Append to the regular depth-tested live pose list, in stable slot order.
CombatImpactStage:
        lda     a:impact_active
        bne     :+
        rtl
:
        ldy     #0
@Scan:  lda     a:impact_records+IMPACT_LIFE,y
        bne     :+
        jmp     @Next
:
        cpx     #GSU_ALIAS_LIVE_COUNT*GSU_GRUNT_POSE_BYTES
        bcc     :+
        rtl
:
        eor     #$ffff
        clc
        adc     #10
        lsr
        clc
        adc     a:impact_records+IMPACT_ROW,y
        xba
        sta     f:GSU_LIVE_POSE_ADDRESS,x
        .repeat 3, I
        lda     a:impact_records+IMPACT_POS+2*I,y
        .if I = 2
        sec
        sbc     #22*8
        .endif
        clc
        adc     #16
        .repeat 5
        cmp     #$8000
        ror
        .endrepeat
        sta     f:GSU_LIVE_POSE_ADDRESS+2+2*I,x
        .endrepeat
        txa
        clc
        adc     #GSU_GRUNT_POSE_BYTES
        tax
@Next:  tya
        jsr     CombatImpactNext
        tay
        cpy     #IMPACT_END
        bcs     @Done
        jmp     @Scan
@Done:  rtl

CombatImpactNext:
        clc
        adc     #IMPACT_RECORD
        pha
        and     #QC_ENTITY_STRIDE-1
        cmp     #IMPACT_PER_EDICT*IMPACT_RECORD
        beq     :+
        pla
        rts
:       pla
        clc
        adc     #QC_ENTITY_STRIDE-IMPACT_PER_EDICT*IMPACT_RECORD
        rts
