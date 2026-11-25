; Cartridge host for the stock starting shotgun. Coordinates in the shooting
; callback use rebased Q3; VM time, directions and player scalars stay Q6.
ShotgunService:
.ifdef QC_CAMPAIGN_ITEMS
        jsr     PowerupServiceTrack
.endif
        lda     a:shot_clock
        cmp     #BSP_WEAPON_LIVE_TICKS
        bcs     @Ready
.ifdef QC_QUEUED_INPUT
        adc     #QC_INPUT_VBLANKS
        cmp     #BSP_WEAPON_LIVE_TICKS
        bcc     :+
        lda     #BSP_WEAPON_LIVE_TICKS
:
        sta     a:shot_clock
.else
        inc     a:shot_clock
.endif
@Ready:
        lda     f:QC_INPUT_MENU_OPEN
        ora     f:QC_INPUT_RELEASE_GATE
        bne     ShotgunServiceDone
.if .defined(QC_NAIL_COUNT) || .defined(QC_CAMPAIGN_ITEMS)
        lda     a:.loword(nail_active)
        beq     :+
        jsr     NailFlightTick
:
.endif
.if .defined(QC_QUEUED_INPUT) .and .defined(PLAYABLE_RECORDED_TAPE)
        jsl     GameplayApplyRecordedWeapon
.endif
        lda     f:QC_INPUT_BUTTONS
.ifdef QC_QUEUED_INPUT
        ldx     a:.loword(axe_selected)
        beq     :+
        jmp     AxeService
:
.endif
.if .defined(QC_NAIL_COUNT) || .defined(QC_CAMPAIGN_ITEMS)
        ldx     a:shot_player+QC_FIELD_WEAPON
        cpx     #4*64
        bne     :+
        jmp     NailFireTick
:
.endif
        and     #JOY_L
        beq     ShotgunServiceDone
        lda     a:shot_player+QC_FIELD_HEALTH
        beq     ShotgunServiceDone
        bmi     ShotgunServiceDone
        lda     a:shot_player+QC_FIELD_AMMO_SHELLS
.ifdef QC_SSG_SOUND
        bne     :+
        lda     a:shot_player+QC_FIELD_WEAPON
        cmp     #2*64
        bne     ShotgunServiceDone
        jsl     SuperShotgunEmpty
        rts
:
.else
        beq     ShotgunServiceDone
.endif
        lda     a:grunt_clock
        cmp     a:shot_player+QC_FIELD_ATTACK_FINISHED
        bcc     ShotgunServiceDone
        jsr     ShotgunFireBegin
ShotgunFireEnd:
        rts
ShotgunServiceDone:
        rts

.ifdef QC_QUEUED_INPUT
AxeService:
        pha
        lda     a:shot_player+QC_FIELD_HEALTH
        beq     @Dead
        bmi     @Dead
        lda     a:.loword(axe_pending)
        beq     @Attack
        lda     a:shot_clock
        cmp     #12                     ; Third stock pose, 0.2 seconds.
        bcc     @Attack
        stz     a:.loword(axe_pending)
        lda     a:grunt_clock
        sta     a:qcg+QC_GLOBAL_TIME
        lda     #QC_ENTITY_STRIDE
        sta     a:qcg+QC_GLOBAL_SELF
        stz     a:qcg+QC_GLOBAL_OTHER
        lda     f:yaw_index
        and     #CAMERA_ANGLE_MASK
        sta     a:shot_yaw
        lda     f:pitch_level
        and     #CAMERA_ANGLE_MASK
        sta     a:shot_pitch
        lda     #4096
        sta     z:qc_budget
        lda     #QC_AXE_FUNCTION
        jsr     QuakeCInvokeOuter
        jsr     GruntPublishPose
@Attack:
        pla
        and     #JOY_L
        beq     @Done
        lda     a:grunt_clock
        cmp     a:shot_player+QC_FIELD_ATTACK_FINISHED
        bcc     @Done
        clc
        adc     #32                     ; Stock half-second cooldown in Q6.
        sta     a:shot_player+QC_FIELD_ATTACK_FINISHED
        stz     a:shot_clock
        inc     a:.loword(axe_pending)
        inc     a:.loword(axe_swings)
.ifdef QC_POWERUP_COUNT
        jsl     PowerupAttack
.endif
        lda     #8
        jmp     GameplayPlaySound
@Dead:
        stz     a:.loword(axe_pending)
        pla
@Done:
        rts
.endif

ShotgunFireBegin:
        sta     a:qcg+QC_GLOBAL_TIME
        lda     #QC_ENTITY_STRIDE
        sta     a:qcg+QC_GLOBAL_SELF
        stz     a:qcg+QC_GLOBAL_OTHER
        lda     #64
        sta     a:shot_player+QC_FIELD_BUTTON0
        lda     f:yaw_index
        and     #CAMERA_ANGLE_MASK
        sta     a:shot_yaw
        lda     f:pitch_level
        and     #CAMERA_ANGLE_MASK
        sta     a:shot_pitch
        lda     #4096
        sta     z:qc_budget
        lda     #QC_WEAPON_FRAME
        jsr     QuakeCInvokeOuter
        stz     a:shot_clock
        jmp     GruntPublishPose

ShotgunBuiltin:
        cmp     #.loword(-1)
        bne     :+
        jmp     ShotgunMakeVectors
:       cmp     #.loword(-7)
        beq     ShotgunRandom
        cmp     #.loword(-9)
        bne     :+
        jmp     GruntNormalize
:
        cmp     #.loword(-16)
        bne     :+
        jmp     ShotgunTrace
:       cmp     #.loword(-44)
        beq     ShotgunAim
        cmp     #.loword(-52)
        beq     ShotgunWriteByte
        cmp     #.loword(-56)
        beq     ShotgunWriteCoord
        jmp     QuakeCTrap

ShotgunRandom:
        lda     a:shot_rng
        bne     :+
        lda     f:QC_RNG_TICK
        ora     #1
:       lsr
        bcc     :+
        eor     #$b400
:       sta     a:shot_rng
        xba
        and     #63
        sta     a:qcg+2
        rts

ShotgunAim:
.ifdef QC_STOCK_AIM
        jsl     PlayerAim
        rts
.endif
ShotgunForward:
        ; Straight or untargeted shots keep the current forward vector.
        ldx     #4
@Copy:
        lda     a:qcg+QC_GLOBAL_FORWARD,x
        sta     a:qcg+2,x
        dex
        dex
        bpl     @Copy
        rts

ShotgunWriteByte:
.ifdef QC_IMPACT_ROW
        jsl     CombatImpactByte
.endif
        ; Consume the stock SVC_TEMPENTITY and TE_GUNSHOT bytes locally.
        inc     a:shot_effect_word
        rts
ShotgunWriteCoord:
.ifdef QC_IMPACT_ROW
        jsl     CombatImpactCoord
.endif
        inc     a:shot_effect_word
        lda     a:shot_effect_word
        cmp     #5
        bne     :+
        lda     a:qcg+QC_GLOBAL_SELF
        cmp     #QC_ENTITY_STRIDE
        bne     :+
.ifdef QC_QUEUED_INPUT
        ldx     a:.loword(axe_selected)
        bne     :+
.endif
        inc     a:.loword(shotgun_impact_events)
:       rts

ShotgunMakeVectors:
        lda     a:qcg+QC_GLOBAL_SELF
        cmp     #QC_GRUNT
        bcc     @Player
        cmp     #QC_GRUNT_DROP
        bcs     @Player
        lda     a:qcg+10
        jsr     GruntAngleIndex
        sta     a:shot_yaw
        lda     a:qcg+8
        beq     :+
        jsr     GruntAngleIndex
        jsr     QCNegate
        and     #CAMERA_ANGLE_MASK
:       sta     a:shot_pitch
@Player:
        ldx     a:shot_yaw
        lda     f:CameraAngleSin,x
        jsr     ShotgunSignedByte
        sta     a:shot_yaw_sin
        sta     a:qcg+QC_GLOBAL_RIGHT
        lda     f:CameraAngleCos,x
        jsr     ShotgunSignedByte
        sta     a:shot_yaw_cos
        jsr     QCNegate
        sta     a:qcg+QC_GLOBAL_RIGHT+2
        stz     a:qcg+QC_GLOBAL_RIGHT+4
        ldx     a:shot_pitch
        lda     f:CameraAngleCos,x
        jsr     ShotgunSignedByte
        sta     a:shot_pitch_cos
        sta     a:qcg+QC_GLOBAL_UP+4
        lda     f:CameraAngleSin,x
        jsr     ShotgunSignedByte
        sta     a:qcg+QC_GLOBAL_FORWARD+4
        jsr     QCNegate
        sta     a:shot_pitch_sin
        lda     a:shot_pitch_cos
        sta     z:qc_rhs
        lda     a:shot_yaw_cos
        jsr     QCMulRound
        sta     a:qcg+QC_GLOBAL_FORWARD
        lda     a:shot_yaw_sin
        jsr     QCMulRound
        sta     a:qcg+QC_GLOBAL_FORWARD+2
        lda     a:shot_pitch_sin
        sta     z:qc_rhs
        lda     a:shot_yaw_cos
        jsr     QCMulRound
        sta     a:qcg+QC_GLOBAL_UP
        lda     a:shot_yaw_sin
        jsr     QCMulRound
        sta     a:qcg+QC_GLOBAL_UP+2
        rts
ShotgunSignedByte:
        and     #$ff
        cmp     #$80
        bcc     :+
        ora     #$ff00
:       rts

ShotgunTrace:
.ifdef QC_SECRET_DOOR_COUNT
        stz     a:qc_sd_source
.endif
        stz     a:shot_effect_word
        lda     a:qcg+QC_GLOBAL_SELF
        cmp     #QC_ENTITY_STRIDE
        bne     @Load
.ifdef QC_QUEUED_INPUT
        ldx     a:.loword(axe_selected)
        bne     @Load
.endif
        inc     a:.loword(shotgun_pellets)
@Load:
        ldx     #4
@Args:
        lda     a:qcg+8,x
        sta     a:w_from,x
        lda     a:qcg+14,x
        sta     a:w_to,x
        dex
        dex
        bpl     @Args
.ifdef PLAYABLE_POINT_SIGHT_CACHE
        jsr     ShotHull::WalkSightTrace
.else
        jsr     ShotHull::WalkTrace
.endif
        stz     a:qcg+QC_GLOBAL_TRACE_ENT
        bcs     :+
        lda     #4096
        sta     z:w_lo
        bra     @Actor
:       lda     z:w_node
.ifdef QC_SECRET_DOOR_COUNT
        sta     a:qc_sd_source
.endif
.ifdef QC_E1M3_GOLD_KEY
        cmp     #QC_E1M3_SHOT_TERMINAL
        bne     :+
        lda     a:qcg+QC_GLOBAL_SELF
        cmp     #QC_ENTITY_STRIDE
        bne     @Actor
        inc     a:qc_e1m3_stair_button_hit
        bra     @Actor
:
.endif
        cmp     #$fffd
        bne     :+
        lda     #QC_DOOR
        bra     @Entity
:       cmp     #$fffc
        bne     @Actor
        lda     #QC_BUTTON
@Entity:
        sta     a:qcg+QC_GLOBAL_TRACE_ENT
@Actor:
        jsr     GruntTraceActor
.ifdef QC_SECRET_DOOR_COUNT
        jsr     QCSecretDoorShot
.endif
        lda     z:w_lo
        cmp     #4096
        bcs     @Miss
        lda     a:qcg+QC_GLOBAL_SELF
        cmp     #QC_ENTITY_STRIDE
        bne     @Fraction
.ifdef QC_QUEUED_INPUT
        ldx     a:.loword(axe_selected)
        beq     @PelletHit
        ldx     a:qcg+QC_GLOBAL_TRACE_ENT
        beq     @Fraction
        lda     a:qce+QC_FIELD_TAKEDAMAGE,x
        beq     @Fraction
        inc     a:.loword(axe_hits)
        bra     @Fraction
@PelletHit:
.endif
        inc     a:.loword(shotgun_hits)
@Fraction:
        lda     z:w_lo
        .repeat 6
        lsr
        .endrepeat
        cmp     #64
        bcc     @Result
        lda     #63
        bra     @Result
@Miss:
        lda     #64
@Result:
        sta     a:qcg+QC_GLOBAL_TRACE_FRACTION
        ldx     #4
@Vector:
        lda     a:w_result,x
        sta     a:qcg+QC_GLOBAL_TRACE_ENDPOS,x
        lda     a:w_normal,x
        xba
        jsr     ShotgunSignedByte
        sta     a:qcg+QC_GLOBAL_TRACE_NORMAL,x
        dex
        dex
        bpl     @Vector
        rts

ShotgunFired:
        inc     a:.loword(shotgun_shots)
        RW_push set:a8
        lda     #3
        sta     f:shotgun_flash
        RW_pull
.if .defined(QC_NAIL_COUNT) || .defined(QC_CAMPAIGN_ITEMS)
        jmp     NailShotgunSound
.else
        lda     #0
.endif
GameplayPlaySound:
        jsl     GameplayPlaySoundLong
        rts

GameplayPlayBodySound:
        inc     a:.loword(quakec_sounds)
        ; Port 0 sends a body cue. Port 2's read direction echoes its token.
        RW_push set:a8
        pha
.if .defined(PLAYABLE_MAP_ID) && .defined(QC_E1M1_TELEPORT)
        jsl     IndustrialPrepareBody
.endif
        lda     f:SMPIO2
        inc
        and     #GAMEPLAY_BODY_TOKEN
        ora     1,s
        sta     f:SMPIO0
        pla
        RW_pull
        rts

QCOpGreater:
        jsr     QCSignedCompare
        bcc     @False
        beq     @False
        jmp     QCTrue
@False:
        jmp     QCFalse
QCOpLessEqual:
        jsr     QCSignedCompare
        bcc     @True
        beq     @True
        jmp     QCFalse
@True:
        jmp     QCTrue
QCOpBitOr:
        jsr     QCOperands
        ora     a:qcg,y
        and     #$ffc0
        jmp     QCStoreResult
QCOpSub:
        jsr     QCOperands
        sec
        sbc     a:qcg,y
        jmp     QCStoreResult
QCOpAddVector:
        QC_LOAD_AB_XY 1
.ifdef PLAYABLE_E1M1_LAZY_QC_OPERANDS
        sty     z:qc_b
.endif
        .repeat 3, I
        lda     a:qcg+I*2,x
        clc
        adc     a:qcg+I*2,y
        ldy     z:qc_c
        sta     a:qcg+I*2,y
        ldy     z:qc_b
        .endrepeat
        jmp     QuakeCDispatch
QCOpState:
.ifdef PLAYABLE_E1M1_LAZY_QC_OPERANDS
        QC_LOAD_AB_XY 0
        sty     z:qc_b
        txy
        ldx     a:qcg+QC_GLOBAL_SELF
.else
        ldx     a:qcg+QC_GLOBAL_SELF
        ldy     z:qc_a
.endif
        lda     a:qcg,y
        sta     a:qce+QC_FIELD_FRAME,x
        lda     a:qcg+QC_GLOBAL_TIME
        clc
        adc     #6                      ; 0.1 seconds in Q6.
        sta     a:qce+QC_FIELD_NEXTTHINK,x
        ldy     z:qc_b
        lda     a:qcg,y
        sta     a:qce+QC_FIELD_THINK,x
        jmp     QuakeCDispatch
QCOpMul:
        jsr     QCOperands
        pha
        lda     a:qcg,y
        sta     z:qc_rhs
        pla
        jsr     QCMulRound
        jmp     QCStoreResult

QCMulRound:
        cmp     #0
        bne     :+
        rts
:       jsr     QCAbsOperands
        lda     a:qc_lo
        ora     z:qc_factor
        cmp     #256
        bcs     @Wide
        ; The common small scalar case needs one hardware product. Use
        ; the same NMI retry rule as the shared wide walk multiply.
@Retry:
        lda     f:video_tick
        sta     a:qc_hi
        RW      a8
        lda     a:qc_lo
        sta     f:WRMPYA
        lda     z:qc_factor
        sta     f:WRMPYB
        RW      a16
        nop
        nop
        nop
        lda     f:RDMPYL
        sta     z:qc_prod_lo
        lda     f:video_tick
        cmp     a:qc_hi
        bne     @Retry
        stz     z:qc_prod_hi
        bra     @Round
@Wide:
        lda     a:qc_lo
        ldx     z:qc_factor
        jsr     WalkMultiply
        lda     z:w_mul_low
        sta     z:qc_prod_lo
        lda     z:w_mul_high
        sta     z:qc_prod_hi
@Round:
        lda     z:qc_prod_lo
        clc
        adc     #32
        sta     z:qc_prod_lo
        bcc     :+
        inc     z:qc_prod_hi
:
        .repeat 6
        lsr     z:qc_prod_hi
        ror     z:qc_prod_lo
        .endrepeat
        lda     z:qc_prod_lo
        jmp     QCApplySign
