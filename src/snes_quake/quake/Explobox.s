; The stock E1M1 T_RadiusDamage call uses a 200-unit search and rebased Q3 positions.
ExploboxFindRadius:
        RW_assume a16i16
        lda     a:qcg+14
        cmp     #200*64
        beq     :+
        jmp     QuakeCTrap
:       stz     a:qcg+2
        ldx     #0
@Next:
        phx
        lda     f:ExploboxRadiusEdicts,x
        tax
        lda     a:qce+QC_FIELD_SOLID,x
        bne     :+
        jmp     @Skip
:       phx
        .repeat 3, Axis
        lda     a:qce+QC_FIELD_MINS+Axis*2,x
        clc
        adc     a:qce+QC_FIELD_MAXS+Axis*2,x
        cmp     #$8000
        ror
        clc
        adc     a:qce+QC_FIELD_ORIGIN+Axis*2,x
        sec
        sbc     a:qcg+8+Axis*2
        jsr     QCAbs
        cmp     #200*8+1
        bcs     @Outside
        sta     a:gr_vector+Axis*2
        .endrepeat
        jsr     GruntVectorSum
        lda     a:gr_sum_hi
        cmp     #.hiword(200*8*200*8)
        bcc     @Link
        bne     @Outside
        lda     a:gr_sum_lo
        cmp     #.loword(200*8*200*8)+1
        bcs     @Outside
@Link:  plx
        lda     a:qcg+2
        sta     a:qce+QC_FIELD_CHAIN,x
        stx     a:qcg+2
        bra     @Skip
@Outside:
        plx
@Skip:  plx
        inx
        inx
        cpx     #QC_RADIUS_COUNT*2
        bcs     :+
        jmp     @Next
:       rts
ExploboxRadiusEdicts:
        .repeat QC_RADIUS_COUNT, I
        .word   .ident(.sprintf("QC_RADIUS_EDICT_%d", I))
        .endrepeat

; Only vectors from the radius query reach this vlen. Scaling before the
; square preserves fractional damage without overflowing the 32-bit sum.
ExploboxLength:
        ldx     #4
@Axis:  lda     a:qcg+8,x
        jsr     QCAbs
        asl
        asl
        asl
        sta     a:gr_vector,x
        dex
        dex
        bpl     @Axis
        jsr     GruntVectorSum
        lda     a:gr_root
        sta     a:qcg+2
        rts

; Append the six stock view-parallel sprite frames to the ordinary depth sort.
ExploboxStage:
        RW_assume a16i16
        lda     a:qce+QC_EXPLOBOX+QC_FIELD_MODEL
        cmp     #QC_EXPLOSION_MODEL
        bne     @Cloud
        lda     a:qce+QC_EXPLOBOX+QC_FIELD_FRAME
        asl
        asl
        clc
        adc     #(QC_EXPLOSION_ROW << 8)
        sta     f:GSU_LIVE_POSE_ADDRESS,x
        .repeat 3, Axis
        lda     a:qce+QC_EXPLOBOX+QC_FIELD_ORIGIN+2*Axis
        .if Axis = 2
        sec
        sbc     #22*8
        .endif
        clc
        adc     #16
        .repeat 5
        cmp     #$8000
        ror
        .endrepeat
        sta     f:GSU_LIVE_POSE_ADDRESS+2+2*Axis,x
        .endrepeat
        txa
        clc
        adc     #GSU_GRUNT_POSE_BYTES
        tax
@Cloud: lda     a:qce+QC_EXPLOBOX+QC_EXPLOSION_LIFE
        beq     @Done
        eor     #$ffff
        clc
        adc     #(QC_EXPLOSION_PHASES*2+1)
        lsr
        asl
        phx
        tax
        lda     f:ExploboxCloudRows,x
        sta     a:gr_trial
        lda     f:ExploboxCloudRows+2,x
        sta     a:gr_sum_lo
        plx
@Tile:  cpx     #(GSU_ALIAS_LIVE_COUNT*GSU_GRUNT_POSE_BYTES)
        bcs     @Done
        lda     a:gr_trial
        xba
        sta     f:GSU_LIVE_POSE_ADDRESS,x
        .repeat 3, Axis
        lda     a:qce+QC_EXPLOBOX+QC_EXPLOSION_EMITTER+2*Axis
        sta     f:GSU_LIVE_POSE_ADDRESS+2+2*Axis,x
        .endrepeat
        txa
        clc
        adc     #GSU_GRUNT_POSE_BYTES
        tax
        inc     a:gr_trial
        lda     a:gr_trial
        cmp     a:gr_sum_lo
        bcc     @Tile
@Done:  rtl

ExploboxCloudRows:
        .repeat QC_EXPLOSION_PHASES, I
        .word .ident(.sprintf("QC_EXPLOSION_FIRST_%d", I))
        .endrepeat
        .word .ident(.sprintf("QC_EXPLOSION_END_%d", QC_EXPLOSION_PHASES-1))

; WinQuake treats a count of 255 in svc_particle as R_ParticleExplosion.
ExploboxParticles:
.ifdef QC_IMPACT_ROW
        lda     a:qcg+20
        cmp     #73*64
        bne     :+
        jsl     CombatImpactBlood
        rts
:
.endif
        lda     a:qcg+QC_GLOBAL_SELF
        cmp     #QC_EXPLOBOX
        bne     @Done
        lda     a:qcg+26
        cmp     #255*64
        bne     @Done
        lda     #QC_EXPLOSION_PHASES*2
        sta     a:qce+QC_EXPLOBOX+QC_EXPLOSION_LIFE
        .repeat 3, Axis
        lda     a:qcg+8+2*Axis
        .if Axis = 2
        sec
        sbc     #22*8
        .endif
        clc
        adc     #16
        .repeat 5
        cmp     #$8000
        ror
        .endrepeat
        sta     a:qce+QC_EXPLOBOX+QC_EXPLOSION_EMITTER+2*Axis
        .endrepeat
@Done:  rts

ExploboxTick:
        lda     a:qce+QC_EXPLOBOX+QC_EXPLOSION_LIFE
        beq     :+
        dec     a:qce+QC_EXPLOBOX+QC_EXPLOSION_LIFE
:
        lda     a:qce+QC_EXPLOBOX+QC_FIELD_THINK
        beq     @Done
        ldx     a:grunt_clock
        cpx     a:qce+QC_EXPLOBOX+QC_FIELD_NEXTTHINK
        bcc     @Done
        ldx     #QC_EXPLOBOX
        stx     a:qcg+QC_GLOBAL_SELF
        stz     a:qcg+QC_GLOBAL_OTHER
        ldx     #4096
        stx     z:qc_budget
        jmp     QuakeCInvokeOuter
@Done:  rts

ExploboxRemove:
        ldx     a:qcg+8
        cpx     #QC_EXPLOBOX
        beq     :+
        jmp     QuakeCTrap
:       stz     a:qce+QC_FIELD_MODEL,x
        stz     a:qce+QC_FIELD_SOLID,x
        stz     a:qce+QC_FIELD_THINK,x
        stz     a:qce+QC_FIELD_NEXTTHINK,x
ExploboxInvalidate:
.ifdef WALK_IMPACT_CACHE_BYTES
        .repeat WALK_IMPACT_CACHE_BYTES / WALK_IMPACT_CACHE_STRIDE, slot
        stz     a:w_impact_cache+slot*WALK_IMPACT_CACHE_STRIDE+26
        .endrepeat
.endif
        lda     f:control_revision
        inc
        sta     f:control_revision
        lda     f:pickup_pixels_dirty
        inc
        sta     f:pickup_pixels_dirty
        rts
