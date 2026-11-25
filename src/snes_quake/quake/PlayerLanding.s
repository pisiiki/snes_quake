; Stock PlayerPostThink uses the previous step's airborne speed.
.include "Data/QuakeBSPLanding.i"

.pushseg
.segment "BSP_CPU_LANDING"
WalkLandingWater:
        .incbin "Data/QuakeBSPLandingWater.bin"
.popseg

WalkQueueLanding:
        jsr     WalkLandingInWater
        bcs     @Water
        lda     a:w_landing_velocity
        cmp     #.loword(-(650*256/60))
        bcs     @Soft
        lda     #GAMEPLAY_BODY_LAND_HARD
        bra     @Queue
@Soft:
        lda     #GAMEPLAY_BODY_LAND
        bra     @Queue
@Water:
        lda     #GAMEPLAY_BODY_LAND_WATER
@Queue:
        sta     a:w_landing_cue
        rts

; Stock PlayerPostThink processes the weapon frame before landing damage.
WalkFinishLanding:
        ldx     a:w_landing_cue
        stz     a:w_landing_cue
        lda     a:shot_player+QC_FIELD_HEALTH
        beq     @Done
        bmi     @Done
        cpx     #GAMEPLAY_BODY_LAND_HARD
        bne     @Sound
.if .defined(QC_ARMOR_COUNT) || .defined(QC_CAMPAIGN_ITEMS)
        lda     #5*64
        jsl     ArmorEnvironmentDamage
        sta     z:qc_rhs
        lda     a:shot_player+QC_FIELD_HEALTH
        sec
        sbc     z:qc_rhs
        ldx     #GAMEPLAY_BODY_LAND_HARD
.else
        sec
        sbc     #5*64
.endif
        sta     a:shot_player+QC_FIELD_HEALTH
        lda     #4
        sta     a:grunt_damage_flash
@Sound:
        txa
.if .defined(PLAYABLE_MAP_ID) && .defined(QC_E1M1_TELEPORT)
        ; The live E1M1 directory points at the shared body sample cache.
        .assert ^GameplayPlayBodySound = ^WalkFinishLanding, lderror, "Landing cue needs a near body dispatcher"
        jmp     GameplayPlayBodySound
.else
        inc     a:.loword(quakec_sounds)
        ; The landing class has a four-bit token and its own subtype.
        RW_push set:a8
        pha
        lda     f:SMPIO2
        inc
        and     #$0f
        ora     1,s
        sta     f:SMPIO0
        pla
        RW_pull
.endif
@Done:
        rts

; Evaluate only on a qualifying floor impact. Each node is
; {front, back, normal XYZ Q14, signed 32-bit bias}.
WalkLandingInWater:
        ldx     #WALK_LANDING_WATER_ROOT
@Node:
        bmi     @Leaf
        lda     f:WalkLandingWater+10,x
        sta     a:w_landing_sum
        lda     f:WalkLandingWater+12,x
        sta     a:w_landing_sum+2
        ldy     #0
@Axis:
        lda     f:WalkLandingWater+4,x
        beq     @Next
        phx
        tax
        lda     a:w_from,y
        jsr     WalkMultiply
        plx
        lda     a:w_landing_sum
        clc
        adc     z:w_mul_low
        sta     a:w_landing_sum
        lda     a:w_landing_sum+2
        adc     z:w_mul_high
        sta     a:w_landing_sum+2
@Next:
        inx
        inx
        iny
        iny
        cpy     #6
        bcc     @Axis
        txa
        sec
        sbc     #6
        tax
        lda     a:w_landing_sum+2
        bpl     @Front
        inx
        inx
@Front:
        lda     f:WalkLandingWater,x
        tax
        bra     @Node
@Leaf:
        cpx     #$ffff
        bne     @Dry
        sec
        rts
@Dry:
        clc
        rts
