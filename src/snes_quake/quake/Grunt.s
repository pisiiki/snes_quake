; The existing avatar controller owns movement. Give QuakeC the real body
; pose in the same Q3 space that the point hull and hitscan use. Its
; Z origin already incorporates the 22-unit eye-to-body offset.
GruntSyncPlayer:
        lda     a:shot_player+QC_FIELD_HEALTH
        beq     @Done
        bmi     @Done
        ldx     #4
@Axis:
        lda     a:w_from,x
        cmp     #$8000
        ror
        tay
        sec
        sbc     a:shot_player+QC_FIELD_ORIGIN,x
        pha
        tya
        sta     a:shot_player+QC_FIELD_ORIGIN,x
        pla
        ; A local controller tick moves at most 16 units. Ignore debugger
        ; placement/reset jumps when estimating the stock velocity input.
        clc
.ifdef QC_QUEUED_INPUT
        adc     #384
        cmp     #769
        bcs     @Zero
        sec
        sbc     #384
        asl
        asl
        sta     a:gr_trial
        asl
        asl
        clc
        adc     a:gr_trial
.else
        adc     #128
        cmp     #257
        bcs     @Zero
        sec
        sbc     #128
        asl
        asl
        sta     a:gr_trial
        .repeat 4
        asl
        .endrepeat
        sec
        sbc     a:gr_trial
.endif
        bra     @Velocity
@Zero:
        lda     #0
@Velocity:
        sta     a:shot_player+QC_FIELD_VELOCITY,x
        dex
        dex
        bpl     @Axis
        lda     a:shot_player+QC_FIELD_ORIGIN+4
        sec
        sbc     #25*8
        sta     a:shot_player+QC_FIELD_ABSMIN+4
@Done:  rts

GruntInitRoster:
.if QC_GRUNT_COUNT = 0
        rts

.else
        lda     #QC_GRUNT
        sta     a:gr_tick_actor
        ldx     #QC_GRUNT
@Actor:
        lda     f:QuakeCInitEdicts,x
        inx
        inx
        bit     a:gr_skill_mask
        beq     @Include
        txa
        clc
        adc     #QC_GRUNT_INIT_WORDS*2
        tax
        bra     @Next
@Include:
        ldy     #0
@Field:
        lda     f:QuakeCInitEdicts,x
        sta     z:qc_tmp
        phx
        tyx
        lda     f:QuakeCInitGruntFields,x
        clc
        adc     a:gr_tick_actor
        tax
        lda     z:qc_tmp
        sta     a:qce,x
        plx
        inx
        inx
        iny
        iny
        cpy     #QC_GRUNT_INIT_WORDS*2
        bcc     @Field
@Next:
        lda     a:gr_tick_actor
        clc
        adc     #QC_ENTITY_STRIDE
        sta     a:gr_tick_actor
        cmp     #QC_GRUNT_DROP
        bcc     @Actor
        rts

.endif
; Separate the combat clock from the local time used by the pushers. Rebase
; active deadlines together before signed Q6 time can overflow.
GruntTick:
.ifdef QC_IMPACT_ROW
        jsl     CombatImpactTick
.endif
.ifdef QC_FLUORESCENT_STYLE
        lda     a:qc_fluorescent_phase
.ifdef QC_QUEUED_INPUT
        clc
        adc     a:qc_elapsed_units
.else
        inc
.endif
        cmp     #160
        bcc     :+
        sbc     #160
:       sta     a:qc_fluorescent_phase
.endif
.ifdef QC_QUEUED_INPUT
        lda     a:grunt_clock
        clc
        adc     a:qc_elapsed_units
        sta     a:grunt_clock
.else
        inc     a:grunt_clock
        lda     a:grunt_clock
.endif
        cmp     #$6000
.if QC_GRUNT_COUNT = 0
        bcc     @BasicTime
        sbc     #$4000
        sta     a:grunt_clock
        ldx     #QC_ENTITY_STRIDE
        GruntRebaseField QC_FIELD_ATTACK_FINISHED
        GruntRebaseField QC_FIELD_NEXTTHINK
        lda     a:grunt_clock
@BasicTime:
        sta     a:qcg+QC_GLOBAL_TIME
        rts
.else
        bcs     :+
        jmp     @Time
:       sbc     #$4000
        sta     a:grunt_clock
        ldx     #QC_GRUNT
@Rebase:
        GruntRebaseField QC_FIELD_NEXTTHINK
        GruntRebaseField QC_FIELD_ATTACK_FINISHED
        GruntRebaseField QC_FIELD_SHOW_HOSTILE
        GruntRebaseField QC_FIELD_PAIN_FINISHED
        txa
        clc
        adc     #QC_ENTITY_STRIDE
        tax
        cmp     #QC_GRUNT_DROP
        bcc     @Rebase
.ifdef QC_EXPLOBOX
        ldx     #QC_EXPLOBOX
        GruntRebaseField QC_FIELD_NEXTTHINK
.endif
        ldx     #QC_ENTITY_STRIDE
        GruntRebaseField QC_FIELD_ATTACK_FINISHED
        GruntRebaseField QC_FIELD_SHOW_HOSTILE
        GruntRebaseField QC_FIELD_NEXTTHINK
.ifdef QC_POWERUP_COUNT
        GruntRebaseField QC_FIELD_SUPER_DAMAGE_FINISHED
        GruntRebaseField QC_FIELD_RADSUIT_FINISHED
        GruntRebaseField QC_FIELD_SUPER_SOUND
        lda     a:.loword(quad_warn_next)
        jsr     GruntRebaseTime
        sta     a:.loword(quad_warn_next)
        lda     a:.loword(suit_warn_next)
        jsr     GruntRebaseTime
        sta     a:.loword(suit_warn_next)
        lda     a:walk_slime_damage_next
        jsr     GruntRebaseTime
        sta     a:walk_slime_damage_next
.endif
        lda     a:qcg+QC_GLOBAL_SIGHT_ENTITY_TIME
        jsr     GruntRebaseTime
        sta     a:qcg+QC_GLOBAL_SIGHT_ENTITY_TIME
        lda     a:grunt_clock
@Time:
        sta     a:qcg+QC_GLOBAL_TIME
.ifdef QC_POWERUP_COUNT
.ifdef QC_INTERMISSION_COUNT
        lda     f:intermission_phase
        cmp     #2
        beq     @SkipPowerup
.endif
        jsl     PowerupTick
@SkipPowerup:
.endif
        lda     a:shot_player+QC_FIELD_HEALTH
        sta     a:gr_old_health
        ldx     #QC_GRUNT
@Thinker:
        stx     a:gr_tick_actor
.ifdef QC_GIB_FIRST_ROW
        lda     a:qce+GIB_RECORDS+GIB_ROW,x
        bpl     :+
        jsr     GibAdvance
        jmp     @Next
:
.endif
.ifdef QC_BACKPACK_COUNT
        lda     a:qce+PACK_LIFE,x
        beq     :+
        jsr     BackpackAdvance
        ldx     a:gr_tick_actor
:
.endif
.ifdef QC_DOG_FIRST
        cpx     #QC_DOG_FIRST
        bcc     :+
        jsr     DogAdvance
        ldx     a:gr_tick_actor
:
.endif
        lda     a:grunt_clock
        cmp     a:qce+QC_FIELD_NEXTTHINK,x
        bcc     @Next
        lda     a:qce+QC_FIELD_THINK,x
        beq     @Next
        ldy     a:qce+QC_FIELD_ENEMY,x
        bne     @Invoke
        ldy     a:qce+QC_FIELD_HEALTH,x
        bmi     @Invoke
        beq     @Invoke
.ifdef QC_PATROL_TOKEN
        ldy     a:qce+QC_FIELD_MOVETARGET,x
        bmi     @Invoke
.endif
        ; Idle actors outside stock sight range can defer their callbacks.
        .repeat 2, I
        lda     a:shot_player+QC_FIELD_ORIGIN+2*I
        sec
        sbc     a:qce+QC_FIELD_ORIGIN+2*I,x
        clc
        adc     #1024*8
        cmp     #2048*8
        bcs     @Next
        .endrepeat
        lda     a:qce+QC_FIELD_THINK,x
@Invoke:
        stx     a:qcg+QC_GLOBAL_SELF
        stz     a:qcg+QC_GLOBAL_OTHER
        ldx     #4096
        stx     z:qc_budget
        jsr     QuakeCInvokeOuter
@Next:
        lda     a:gr_tick_actor
        clc
        adc     #QC_ENTITY_STRIDE
        tax
        cmp     #QC_GRUNT_DROP
        bcc     @Thinker
.ifdef QC_EXPLOBOX
        jsr     ExploboxTick
.endif
        lda     a:shot_player+QC_FIELD_HEALTH
        eor     #$8000
        sta     a:gr_trial
        lda     a:gr_old_health
        eor     #$8000
        cmp     a:gr_trial
        bcc     :+
        beq     :+
        lda     #4
        sta     a:grunt_damage_flash
:
.endif
GruntPublishPose:
.if QC_GRUNT_COUNT = 0
        rts

.else
        lda     a:grunt+QC_FIELD_FRAME
        .repeat 6
        lsr
        .endrepeat
        sta     a:grunt_frame
        lda     a:grunt+QC_FIELD_ANGLES+2
        jsr     GruntAngleIndex
        sta     a:grunt_yaw
        rts

.endif
GruntRebaseTime:
        sec
        sbc     #$4000
        bcs     :+
        lda     #0
:       rts

GruntCounterIndex:
        sec
        sbc     #QC_GRUNT
        xba
        and     #$ff
        tax
        rts

GruntBuiltin:
.ifdef QC_EXPLOBOX
        cmp     #.loword(-22)
        bne     :+
        jmp     ExploboxFindRadius
:       cmp     #.loword(-15)
        bne     :+
        jmp     ExploboxRemove
:
.endif
        cmp     #.loword(-13)           ; vectoyaw
        bne     :+
        jmp     GruntVectorYaw
:       cmp     #.loword(-17)           ; checkclient (one local player)
        beq     @CheckClient
        cmp     #.loword(-38)           ; ceil
        beq     @Ceil
.ifdef QC_DOG_FIRST
        cmp     #.loword(-40)           ; checkbottom(entity)
        bne     :+
        jmp     DogCheckBottom
:
.endif
        cmp     #.loword(-49)           ; ChangeYaw
        bne     :+
        jmp     GruntChangeYaw
:       cmp     #.loword(-32)           ; walkmove
        bne     :+
        jmp     GruntWalkMove
:       cmp     #.loword(-67)           ; movetogoal
        bne     :+
        jmp     GruntMoveToGoal
:
        cmp     #.loword(-48)           ; particle effect message
.ifdef QC_EXPLOBOX
        bne     :+
        jmp     ExploboxParticles
:
.else
        beq     @NoOutput
.endif
        cmp     #.loword(-14)           ; spawn: bounded, unpresented death drop
        beq     @Spawn
        cmp     #.loword(-3)            ; setmodel (death drop)
        beq     @SetModel
        cmp     #.loword(-4)            ; setsize (death drop)
.ifdef QC_BACKPACK_COUNT
        bne     @OtherBuiltin
.ifdef QC_GIB_FIRST_ROW
        ldx     a:qcg+8
        lda     a:qce+QC_FIELD_MODEL,x
        cmp     #QC_BACKPACK_MODEL
        beq     :+
        jmp     GibSetSize
:
.endif
        jmp     BackpackSpawn
.else
        beq     @NoOutput
.endif
@OtherBuiltin:
        jmp     ShotgunBuiltin
@CheckClient:
        lda     a:shot_player+QC_FIELD_HEALTH
        beq     @Blocked
        bmi     @Blocked
        lda     #QC_ENTITY_STRIDE
        bra     @Return
@Ceil:
        lda     a:qcg+8
        clc
        adc     #63
        and     #$ffc0
        bra     @Return
@Spawn:
        lda     #QC_GRUNT_DROP
        bra     @Return
@SetModel:
        ldx     a:qcg+8
.ifdef QC_EXPLOBOX
        cpx     #QC_EXPLOBOX
        bne     :+
        jsr     ExploboxInvalidate
        bra     @Model
:
.endif
        cpx     #QC_GRUNT_DROP
.ifdef QC_GIB_FIRST_ROW
        beq     :+
        cpx     a:qcg+QC_GLOBAL_SELF
        bne     @BadEdict
        lda     a:qcg+14
        cmp     #QC_GIB_MODEL_0
        beq     :+
        cmp     #QC_GIB_MODEL_1
        bne     @BadEdict
:
.else
        bne     @BadEdict
.endif
@Model: lda     a:qcg+14
        sta     a:qce+QC_FIELD_MODEL,x
@NoOutput:
        rts
@Blocked:
        lda     #0
@Return:
        sta     a:qcg+2
        rts
@BadEdict:
        jmp     QuakeCTrap

.ifdef PLAYABLE_E1M1_LINKED_BUILTINS
QCCheckClientBuiltin = @CheckClient
.endif
GruntSound:
        ldx     #0
@Sample:
        cmp     f:GruntSoundIds,x
        beq     @Play
        inx
        inx
        cpx     #GruntSoundIdsEnd-GruntSoundIds
        bcc     @Sample
        rts
@Play:
        cpx     #2                      ; Stock attack sample on grunt shot.
        bne     :+
        inc     a:grunt_shots
        phx
        lda     a:qcg+8                 ; Stock sound emitter.
        jsr     GruntCounterIndex
        inc     a:gr_actor_shots,x
        plx
:       txa
        lsr
.ifdef QC_DOG_FIRST
        cmp     #6
        bcc     :+
        clc
        adc     #GAMEPLAY_DOG_SAMPLE_FIRST-6
        jmp     GameplayPlaySound
:
.elseif .defined(QC_KNIGHT_ROSTER)
        cmp     #6
        bcc     :+
        clc
        adc     #GAMEPLAY_KNIGHT_SAMPLE_FIRST-6
        jmp     GameplayPlaySound
:
.endif
        inc
        inc
        jmp     GameplayPlaySound

GruntSoundIds:
        .repeat 6, I
        .word .ident(.sprintf("QC_GRUNT_SOUND_%d", I))
        .endrepeat
.ifdef QC_DOG_FIRST
        .repeat 5, I
        .word .ident(.sprintf("QC_DOG_SOUND_%d", I))
        .endrepeat
.elseif .defined(QC_KNIGHT_ROSTER)
        .repeat 6, I
        .word .ident(.sprintf("QC_KNIGHT_SOUND_%d", I))
        .endrepeat
.endif
GruntSoundIdsEnd:
GruntFrameRows:
        .incbin "Data/QuakeBSPGruntFrames.bin"

; Freeze every live edict before issuing the FX3 job. The simulation can
; continue updating WRAM while the renderer reads this cartridge RAM copy.
GruntStageRoster:
.if QC_GRUNT_COUNT = 0
        rtl

.else
        phb
        pea     $7f7f
        plb
        plb
        stz     a:gr_render_offset
        ldy     #QC_GRUNT
@Actor:
        lda     a:qce+QC_FIELD_MODEL,y
        bne     @Visible
        lda     #GSU_HIDDEN_ACTOR_POSE                  ; No model in this immutable pose.
        bra     @Store
@Visible:
.ifdef QC_GIB_FIRST_ROW
        lda     a:qce+GIB_RECORDS+GIB_ROW,y
        bpl     :+
        and     #$00ff
        bra     @Angle
:
.endif
        cpy     #QC_GRUNT
        bne     @Live
        lda     a:grunt_frame
        tax
        lda     f:GruntFrameRows,x
        and     #$ff
        xba
        ora     a:grunt_yaw
        bra     @Store
@Live:
        lda     a:qce+QC_FIELD_FRAME,y
        .repeat 6
        lsr
        .endrepeat
.ifdef QC_DOG_FIRST
        cpy     #QC_DOG_FIRST
        bcc     :+
        clc
        adc     #QC_DOG_FRAME_MAP_OFFSET
:
.endif
        tax
        lda     f:GruntFrameRows,x
        and     #$ff
@Angle: xba
        pha
        lda     a:qce+QC_FIELD_ANGLES+2,y
        jsr     GruntAngleIndex
        ora     1,s
        plx
@Store:
        ldx     a:gr_render_offset
        sta     f:GSU_LIVE_POSE_ADDRESS,x
        .repeat 3, I
        lda     a:qce+QC_FIELD_ORIGIN+2*I,y
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
        sta     a:gr_render_offset
        tya
        clc
        adc     #QC_ENTITY_STRIDE
        tay
        cmp     #QC_GRUNT_DROP
        bcs     :+
        jmp     @Actor
:
.ifdef QC_ARMOR_COUNT
        .repeat QC_ARMOR_COUNT, I
        .scope
        base = (QC_GRUNT_COUNT+I)*GSU_GRUNT_POSE_BYTES
        lda     f:QuakeCArmorMask
        bit     #(1 << I)
        beq     hidden
        ; Stock EF_ROTATE turns at 100 degrees per game second.
        lda     a:.loword(armor_yaw)
        ora     #(.ident(.sprintf("QC_ARMOR_%d_SPRITEROW", I)) << 8)
        bra     store
hidden: lda     #GSU_HIDDEN_ACTOR_POSE
store:  sta     f:GSU_LIVE_POSE_ADDRESS+base
        .repeat 3, J
        lda     #.loword(.ident(.sprintf("QC_ARMOR_%d_%c", I, 88+J)))
        sta     f:GSU_LIVE_POSE_ADDRESS+2+base+2*J
        .endrepeat
        .endscope
        .endrepeat
.endif
.ifdef QC_NAIL_COUNT
        base = (GSU_BACKPACK_FIRST-1-.defined(QC_SSG_ROW))*GSU_GRUNT_POSE_BYTES
        lda     f:QuakeCNailMask
        bit     #(1 << QC_NAIL_COUNT)
        beq     :+
        lda     a:.loword(armor_yaw)
        ora     #(QC_NAILGUN_ROW << 8)
        bra     :++
:       lda     #GSU_HIDDEN_ACTOR_POSE
:       sta     f:GSU_LIVE_POSE_ADDRESS+base
        .repeat 3, Axis
        lda     #.loword(.ident(.sprintf("QC_NAILGUN_%c", 88+Axis)))
        sta     f:GSU_LIVE_POSE_ADDRESS+2+base+2*Axis
        .endrepeat
.endif
.ifdef QC_SSG_ROW
        jsl     SuperShotgunStage
.endif
.ifdef QC_BACKPACK_COUNT
.ifdef QC_POWERUP_COUNT
        jsl     PowerupStage
.endif
        jsr     BackpackStage
.endif
.ifdef QC_KNIGHT_KEY_ROW
        ; The pickup shares the live depth sort. Hide only its own slot.
        lda     a:.loword(quakec_e1m2_key)
        beq     :+
        lda     #GSU_HIDDEN_ACTOR_POSE
        bra     :++
:       lda     #(QC_KNIGHT_KEY_ROW << 8) | QC_KNIGHT_KEY_YAW
:       sta     f:GSU_LIVE_POSE_ADDRESS+QC_GRUNT_COUNT*GSU_GRUNT_POSE_BYTES
        lda     #.loword(QC_KNIGHT_KEY_X)
        sta     f:GSU_LIVE_POSE_ADDRESS+2+QC_GRUNT_COUNT*GSU_GRUNT_POSE_BYTES
        lda     #.loword(QC_KNIGHT_KEY_Y)
        sta     f:GSU_LIVE_POSE_ADDRESS+2+QC_GRUNT_COUNT*GSU_GRUNT_POSE_BYTES+2
        lda     #.loword(QC_KNIGHT_KEY_Z)
        sta     f:GSU_LIVE_POSE_ADDRESS+2+QC_GRUNT_COUNT*GSU_GRUNT_POSE_BYTES+4
.ifdef QC_CAMPAIGN_ITEMS
        ldx     #((QC_GRUNT_COUNT+1)*GSU_GRUNT_POSE_BYTES)
        jsl     NailStage
        txa
        lsr
        lsr
        lsr
        sta     f:GSU_DATA_BASE+GSU_CAMPAIGN_POSE_COUNT
.endif
.endif
        plb
        rtl

.endif
; Entity angles remain Q6 degrees in the VM, while presentation and sine
; tables use a byte per turn. One byte-angle step is exactly 90 Q6 units.
GruntAngleIndex:
        ldx     #0
        .repeat 8, I
        cmp     #(90 << (7-I))
        bcc     :+
        sbc     #(90 << (7-I))
        sta     a:gr_trial
        txa
        ora     #(1 << (7-I))
        tax
        ; Preserve the remainder between compare steps.
        lda     a:gr_trial
:       .endrepeat
        txa
        rts
