; Stock player_nail1/player_nail2 alternate the muzzle by four units.
; A swept point travels 50 world units per 20 Hz tick. Signed quarter-Q3
; remainders preserve the original 1000 units/second on diagonal shots.
NailStage:
        lda     a:.loword(nail_active)
        bne     :+
        rtl
:
        phb
        pea     $7e7e
        plb
        plb
        ldy     #0
@Scan:  lda     a:.loword(NailProjectiles)+NAIL_LIFE,y
        beq     @Next
        lda     a:.loword(NailProjectiles)+NAIL_YAW,y
        ora     #(QC_SPIKE_ROW<<8)
        sta     f:GSU_LIVE_POSE_ADDRESS,x
        .repeat 3, Axis
        lda     a:.loword(NailProjectiles)+NAIL_POS+2*Axis,y
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
@Next:  tya
        clc
        adc     #NAIL_RECORD
        tay
        cpy     #NAIL_RECORD*NAIL_CAPACITY
        bcs     :+
        jmp     @Scan
:       plb
        rtl

NailFireTick:
        RW_assume a16i16
        and     #JOY_L
        tay
        lda     a:shot_player+QC_FIELD_HEALTH
        beq     @Stop
        bmi     @Stop
        lda     a:.loword(nail_frame)
        beq     @Idle
        dec     a:.loword(nail_next_frame)
        bne     @Done
        bra     @CheckHeld
@Idle:  lda     a:grunt_clock
        cmp     a:shot_player+QC_FIELD_ATTACK_FINISHED
        bcc     @Done
@CheckHeld:
        cpy     #0
        beq     @Stop
        lda     a:shot_player+QC_FIELD_AMMO_NAILS
        beq     @Empty
        jmp     NailSpawn
@Empty: lda     a:shot_player+QC_FIELD_AMMO_SHELLS
        beq     @Axe
        sta     a:shot_player+QC_FIELD_CURRENTAMMO
        ldx     #64
        cmp     #2*64
        bcc     :+
        lda     a:shot_player+QC_FIELD_ITEMS
        bit     #2
        beq     :+
        ldx     #2*64
:       stx     a:shot_player+QC_FIELD_WEAPON
        bra     @Stop
@Axe:   stz     a:shot_player+QC_FIELD_CURRENTAMMO
        lda     #1
        sta     f:axe_selected
@Stop:  stz     a:.loword(nail_frame)
@Done:  rts

NailSpawn:
        ldx     #0
@Find:  lda     f:nails+NAIL_LIFE,x
        beq     @Free
        txa
        clc
        adc     #NAIL_RECORD
        tax
        cpx     #NAIL_RECORD*NAIL_CAPACITY
        bcc     @Find
        rts
@Free:  stx     a:.loword(nail_slot)
        lda     #QC_ENTITY_STRIDE
        sta     a:qcg+QC_GLOBAL_SELF
        lda     f:yaw_index
        and     #CAMERA_ANGLE_MASK
        sta     f:nails+NAIL_YAW,x
        sta     a:shot_yaw
        lda     f:pitch_level
        and     #CAMERA_ANGLE_MASK
        sta     a:shot_pitch
        jsr     ShotgunMakeVectors
.ifdef QC_STOCK_AIM
        jsl     PlayerAim
.endif
        lda     a:.loword(nail_frame)
        and     #7
        inc
        sta     a:.loword(nail_frame)
        ldx     a:.loword(nail_slot)
        .repeat 3, Axis
        .if Axis < 2
        lda     a:qcg+QC_GLOBAL_RIGHT+2*Axis
        pha
        lda     a:.loword(nail_frame)
        lsr
        pla
        bcs     :+
        eor     #$ffff
        inc
:       cmp     #$8000
        ror
        .else
        lda     #16*8
        .endif
        clc
        adc     a:shot_player+QC_FIELD_ORIGIN+2*Axis
        sta     f:nails+NAIL_POS+2*Axis,x
.ifdef QC_STOCK_AIM
        lda     a:qcg+2+2*Axis
.else
        lda     a:qcg+QC_GLOBAL_FORWARD+2*Axis
.endif
        sta     a:.loword(nail_math)
        asl
        asl
        asl
        sta     a:.loword(nail_math8)
        asl
        clc
        adc     a:.loword(nail_math8)
        clc
        adc     a:.loword(nail_math)
        sta     f:nails+NAIL_DELTA+2*Axis,x
        .endrepeat
        lda     #0
        sta     f:nails+NAIL_REMAINDER,x
        lda     #120
        sta     f:nails+NAIL_LIFE,x
        inc     a:.loword(nail_active)
        inc     a:.loword(nail_shots)
        lda     #2
        sta     a:.loword(nail_next_frame)
        lda     a:grunt_clock
        clc
        adc     #13
        sta     a:shot_player+QC_FIELD_ATTACK_FINISHED
        lda     a:shot_player+QC_FIELD_AMMO_NAILS
        sec
        sbc     #64
        sta     a:shot_player+QC_FIELD_AMMO_NAILS
        sta     a:shot_player+QC_FIELD_CURRENTAMMO
.ifdef QC_POWERUP_COUNT
        jsl     PowerupAttack
.endif
        inc     a:.loword(quakec_sounds)
.ifdef PLAYABLE_MAP_ID
        jsl     NailPlayMuzzle
        rts
.else
        lda     #0
        jsl     SuperShotgunLoadSample
        lda     #GAMEPLAY_NAIL_FIRE
        jmp     GameplayPlaySound
.endif

NailFlightTick:
        ldx     #0
@Scan:  lda     f:nails+NAIL_LIFE,x
        bne     :+
        jmp     @Next
:       stx     a:.loword(nail_slot)
        stz     a:.loword(nail_remainder)
        .repeat 3, Axis
        lda     f:nails+NAIL_POS+2*Axis,x
        sta     a:qcg+8+2*Axis
        lda     f:nails+NAIL_REMAINDER,x
        .repeat 2*Axis
        lsr
        .endrepeat
        and     #3
        clc
        adc     f:nails+NAIL_DELTA+2*Axis,x
        pha
        and     #3
        .repeat 2*Axis
        asl
        .endrepeat
        ora     a:.loword(nail_remainder)
        sta     a:.loword(nail_remainder)
        pla
        cmp     #$8000
        ror
        cmp     #$8000
        ror
        clc
        adc     a:qcg+8+2*Axis
        sta     a:qcg+14+2*Axis
        sta     f:nails+NAIL_POS+2*Axis,x
        .endrepeat
        lda     a:.loword(nail_remainder)
        sta     f:nails+NAIL_REMAINDER,x
        stz     a:qcg+20
        lda     #QC_ENTITY_STRIDE
        sta     a:qcg+26
        lda     #QC_GRUNT_DROP
        sta     a:qcg+QC_GLOBAL_SELF
        jsr     ShotgunTrace
        ldx     a:.loword(nail_slot)
        lda     a:qcg+QC_GLOBAL_TRACE_FRACTION
        cmp     #64
        bcc     @Impact
        lda     f:nails+NAIL_LIFE,x
        dec
        sta     f:nails+NAIL_LIFE,x
        bne     @Next
        bra     @Remove
@Impact:
        ldx     a:qcg+QC_GLOBAL_TRACE_ENT
        beq     @World
        lda     a:qce+QC_FIELD_TAKEDAMAGE,x
        beq     @World
        inc     a:.loword(nail_actor_hits)
.ifdef QC_IMPACT_ROW
        jsr     CombatImpactSpikeBlood
.endif
        stx     a:qcg+8
        lda     #QC_GRUNT_DROP
        sta     a:qcg+14
        sta     a:qcg+QC_GLOBAL_SELF
        lda     #QC_ENTITY_STRIDE
        sta     a:qcg+20
        sta     a:qce+QC_GRUNT_DROP+QC_FIELD_OWNER
        lda     #9*64
        sta     a:qcg+26
        .repeat 3, Axis
        lda     a:qcg+QC_GLOBAL_TRACE_ENDPOS+2*Axis
        sta     a:qce+QC_GRUNT_DROP+QC_FIELD_ORIGIN+2*Axis
        .endrepeat
        lda     a:grunt_clock
        sta     a:qcg+QC_GLOBAL_TIME
        lda     #4096
        sta     z:qc_budget
        lda     #QC_NAIL_DAMAGE_FUNCTION
        jsr     QuakeCInvokeOuter
        jsr     GruntPublishPose
        bra     @Remove
@World: inc     a:.loword(nail_world_hits)
.ifdef QC_IMPACT_ROW
        jsl     CombatImpactSpike
.endif
        jsr     NailImpactSound
@Remove:
        ldx     a:.loword(nail_slot)
        lda     #0
        sta     f:nails+NAIL_LIFE,x
        dec     a:.loword(nail_active)
@Next:  txa
        clc
        adc     #NAIL_RECORD
        tax
        cpx     #NAIL_RECORD*NAIL_CAPACITY
        bcs     @Done
        jmp     @Scan
@Done:  rts

; TE_SPIKE selects tink1 four times in five. On the remaining branch
; ric1/ric2/ric3 have relative weights 1:1:2, as in CL_ParseTEnt.
NailEffectRandom:
        lda     a:.loword(nail_effect_rng)
        lsr
        bcc     :+
        eor     #$b400
:       sta     a:.loword(nail_effect_rng)
        xba
        and     #$ff
        rts

NailImpactSound:
        jsr     NailEffectRandom
@Mod5:  cmp     #5
        bcc     @Choose
        sbc     #5
        bra     @Mod5
@Choose:
        cmp     #0
        beq     @Ricochet
        lda     #GAMEPLAY_NAIL_TINK
        bra     @Play
@Ricochet:
        jsr     NailEffectRandom
        and     #3
        cmp     #1
        beq     @Ric1
        cmp     #2
        beq     @Ric2
        lda     #GAMEPLAY_NAIL_RIC1+2
        bra     @Play
@Ric2:  lda     #GAMEPLAY_NAIL_RIC1+1
        bra     @Play
@Ric1:  lda     #GAMEPLAY_NAIL_RIC1
@Play:  pha
        sec
        sbc     #GAMEPLAY_NAIL_FIRE       ; Build-independent stock cue index.
        sta     a:.loword(nail_impact_sound)
        pla
        inc     a:.loword(quakec_sounds)
        jmp     GameplayPlaySound
