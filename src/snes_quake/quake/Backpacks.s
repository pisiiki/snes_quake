; Each soldier can drop one pack. Keep it in the unused end of that
; soldier's edict; the original QuakeC fields end before byte 400.
PACK_LIFE = 402
PACK_SHELLS = 404
PACK_ORIGIN = 406
PACK_VELOCITY = 412

BackpackSpawn:
        ; The stock DropBackpack has computed its payload and random toss
        ; by the time it calls setsize. Its shared VM edict is scratch.
        ldx     a:qcg+QC_GLOBAL_SELF
        cpx     #QC_GRUNT
        bcc     @Done
        cpx     #QC_DOG_FIRST
        bcs     @Done
        lda     #120*64
        sta     a:qce+PACK_LIFE,x
        lda     a:qce+QC_GRUNT_DROP+QC_FIELD_AMMO_SHELLS
        sta     a:qce+PACK_SHELLS,x
        .repeat 3, I
        lda     a:qce+QC_FIELD_ORIGIN+2*I,x
          .if I = 2
        sec
        sbc     #24*8
          .endif
        sta     a:qce+PACK_ORIGIN+2*I,x
        lda     a:qce+QC_GRUNT_DROP+QC_FIELD_VELOCITY+2*I
          .repeat 3
        cmp     #$8000
        ror
          .endrepeat
        sta     a:qce+PACK_VELOCITY+2*I,x
        .endrepeat
@Done:  rts

BackpackAdvance:
        sec
.ifdef QC_QUEUED_INPUT
        sbc     a:qc_elapsed_units
.else
        sbc     #1
.endif
        beq     @Expire
        bcs     @Live
@Expire:
        stz     a:qce+PACK_LIFE,x
        rts
@Live:
        sta     a:qce+PACK_LIFE,x
        lda     a:qce+PACK_VELOCITY,x
        ora     a:qce+PACK_VELOCITY+2,x
        ora     a:qce+PACK_VELOCITY+4,x
        beq     @Touch
        jsr     BackpackToss
        ldx     a:gr_tick_actor
@Touch:
        lda     a:shot_player+QC_FIELD_HEALTH
        beq     @Done
        bmi     @Done
        ; FL_ITEM expands the horizontal extent by 15, and the linked
        ; player has a one-unit margin. The drop's stock box is
        ; (-16,-16,0)..(16,16,56), and the player is 32x32x56.
        .repeat 3, I
        lda     a:shot_player+QC_FIELD_ORIGIN+2*I
        sec
        sbc     a:qce+PACK_ORIGIN+2*I,x
        clc
          .if I = 2
        adc     #33*8
        cmp     #(33+81)*8+1
          .else
        adc     #48*8
        cmp     #96*8+1
          .endif
        bcs     @Done
        .endrepeat
        stz     a:qce+PACK_LIFE,x
.ifdef QC_PICKUP_NOTICES
        lda     #NOTICE_BACKPACK
        jsl     PickupNotify
.endif
        lda     a:shot_player+QC_FIELD_AMMO_SHELLS
        clc
        adc     a:qce+PACK_SHELLS,x
        cmp     #100*64
        bcc     :+
        lda     #100*64
:       sta     a:shot_player+QC_FIELD_AMMO_SHELLS
        ldx     a:shot_player+QC_FIELD_WEAPON
        cpx     #64
        beq     :+
        cpx     #128
        bne     :++
:       sta     a:shot_player+QC_FIELD_CURRENTAMMO
:       inc     a:.loword(quakec_sounds)
        lda     #1
        jsl     GameplayPlaySoundLong
@Done:  rts

BackpackToss:
        lda     a:qce+PACK_VELOCITY+4,x
        sec
        sbc     #40*8
        sta     a:qce+PACK_VELOCITY+4,x
        .repeat 3, I
        lda     a:qce+PACK_ORIGIN+2*I,x
          .if I = 2
        clc
        adc     #24*8                   ; Stock hull 1 begins 24 below its origin.
          .endif
        asl
        sta     a:w_from+2*I
        lda     a:qce+PACK_VELOCITY+2*I,x
        jsr     DogVelocityStep
        clc
        adc     a:w_from+2*I
        sta     a:w_to+2*I
        .endrepeat
        jsr     WalkTrace
        php
        ldx     a:gr_tick_actor
        .repeat 3, I
        lda     a:w_result+2*I
        inc
        cmp     #$8000
        ror
          .if I = 2
        sec
        sbc     #24*8
          .endif
        sta     a:qce+PACK_ORIGIN+2*I,x
        .endrepeat
        plp
        bcc     @Done
        lda     a:w_normal+4
        bmi     @Wall
        cmp     #WALK_FLOOR_Z
        bcc     @Wall
        stz     a:qce+PACK_VELOCITY,x
        stz     a:qce+PACK_VELOCITY+2,x
        stz     a:qce+PACK_VELOCITY+4,x
@Done:  rts
@Wall:
        stz     a:w_dot
        stz     a:w_dot_high
        .repeat 3, I
        ldx     a:gr_tick_actor
        lda     a:qce+PACK_VELOCITY+2*I,x
        ldx     a:w_normal+2*I
        jsr     WalkMultiply
        lda     a:w_dot
        clc
        adc     z:w_mul_low
        sta     a:w_dot
        lda     a:w_dot_high
        adc     z:w_mul_high
        sta     a:w_dot_high
        .endrepeat
        lda     a:w_dot
        sta     z:w_mul_low
        lda     a:w_dot_high
        sta     z:w_mul_high
        jsr     WalkProductQ14
        sta     a:w_progress
        .repeat 3, I
        lda     a:w_normal+2*I
        ldx     a:w_progress
        jsr     WalkMultiply
        jsr     WalkProductQ14
        sta     a:w_temp
        ldx     a:gr_tick_actor
        lda     a:qce+PACK_VELOCITY+2*I,x
        sec
        sbc     a:w_temp
        sta     a:qce+PACK_VELOCITY+2*I,x
        .endrepeat
        rts

BackpackStage:
        ldy     #QC_GRUNT
        ldx     #(GSU_BACKPACK_FIRST*GSU_GRUNT_POSE_BYTES)
@Next:
        lda     a:qce+PACK_LIFE,y
.ifdef QC_GIB_FIRST_ROW
        bmi     @Skip
.endif
        beq     @Skip
.ifdef QC_ARMOR_COUNT
        lda     a:.loword(armor_yaw)
.else
        lda     f:fly_alias_phase_q32+2
        xba
        and     #$ff
.endif
        ora     #(QC_BACKPACK_ROW<<8)
        sta     f:GSU_LIVE_POSE_ADDRESS,x
        .repeat 3, I
        lda     a:qce+PACK_ORIGIN+2*I,y
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
@Skip:  tya
        clc
        adc     #QC_ENTITY_STRIDE
        tay
        cmp     #QC_DOG_FIRST
        bcs     :+
        jmp     @Next
:
.ifdef QC_NAIL_COUNT
        jsl     NailStage
.endif
.ifdef QC_EXPLOBOX
        jsl     ExploboxStage
.endif
.ifdef QC_GIB_FIRST_ROW
        jsr     GibStage
.endif
.ifdef QC_E1M1_TELEPORT
        jsr     TeleportStage
.endif
.ifdef QC_IMPACT_ROW
        jsl     CombatImpactStage
.endif
        txa
        .repeat 3
        lsr
        .endrepeat
        sta     f:GSU_DATA_BASE+GSU_BACKPACK_TOKEN_COUNT
        rts
