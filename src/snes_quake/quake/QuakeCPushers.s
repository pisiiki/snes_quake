; The foreground owns all mutable QuakeC state. NMI only records a contact
; and reads the published brush poses while resolving camera-axis moves.
QC_STEP_RATE = 64
QC_VIDEO_RATE = 60
QC_EYE_HEIGHT = 22
QC_PHASE_STEP = QC_STEP_RATE - QC_VIDEO_RATE
.assert QC_BUTTON_STEPS = 2, error, "QuakeC row stride expects three button poses"

.ifndef QC_BASIC_GAMEPLAY
        .pushseg
        .segment "BSP_QUAKEC_BYTECODE"
; A holds the sample handle. The entrance master and lift share the
; resident hydraulic cues. The linked entrance follower is silent.
QuakeCPusherSound:
        ldx     a:qcg+8
        cpx     #QC_BUTTON
        beq     @Button
        cpx     #QC_DOOR
.if QC_ENTRANCE_COUNT > 0
        beq     @Hydraulic
        cpx     #QC_ENTRANCE_0
.endif
        bne     @Other
@Hydraulic:
        cmp     #QC_LIFT_MOVE_SOUND
        beq     @Move
        cmp     #QC_LIFT_STOP_SOUND
        bne     @Other
        ldx     #GAMEPLAY_AUX_LIFT_END
        bra     @Send
@Move:  ldx     #GAMEPLAY_AUX_LIFT_RUN
        bra     @Send
@Button:
        cmp     #QC_LIFT_BUTTON_SOUND
        bne     @Other
        ldx     #GAMEPLAY_AUX_BUTTON
@Send:  ldy     a:qcg+14
        cpy     #2*64                   ; QuakeC CHAN_VOICE.
        bne     @Other
        txa
        jsl     GameplayPlayAuxSound
        sec
        rtl
@Other: clc
        rtl
        .popseg
.endif

.macro QC_INSIDE value, lower, upper, origin, exit
        lda     f:value
        sec
        sbc     #.loword(((lower) - (origin)) * 16)
        cmp     #((upper) - (lower)) * 16
        bcs     exit
.endmacro

QuakeCPlayerSolid:
.if .defined(QC_BASIC_GAMEPLAY)
        clc
        rtl
.else
        RW_assume a16i16
        lda     f:quakec_door_pose
        jsr     QCDoorContainsPlayer
        bcs     @Done
        jsr     QCButtonContainsPlayer
        bcc     @Done
        lda     #1
        sta     f:quakec_contact
        sec
@Done:
        rtl

.endif
QCDoorContainsPlayer:
        asl
        tax
.if BSP_PLAYER_WALK
        lda     f:walk_pending
        beq     @Live
        QC_INSIDE WalkPendingXYZ, QC_DOOR_MIN_X, QC_DOOR_MAX_X, BSP_WORLD_ORIGIN_X, @Outside
        QC_INSIDE WalkPendingXYZ+2, QC_DOOR_MIN_Y, QC_DOOR_MAX_Y, BSP_WORLD_ORIGIN_Y, @Outside
        lda     f:WalkPendingXYZ+4
        bra     @DoorZ
@Live:
.endif
        QC_INSIDE camera_x, QC_DOOR_MIN_X, QC_DOOR_MAX_X, BSP_WORLD_ORIGIN_X, @Outside
        QC_INSIDE camera_y, QC_DOOR_MIN_Y, QC_DOOR_MAX_Y, BSP_WORLD_ORIGIN_Y, @Outside
        lda     f:camera_z
@DoorZ:
        sec
        sbc     f:QCDoorTranslations,x
        sec
        sbc     #.loword((QC_DOOR_MIN_Z + QC_EYE_HEIGHT - BSP_WORLD_ORIGIN_Z) * 16)
        cmp     #(QC_DOOR_MAX_Z - QC_DOOR_MIN_Z) * 16
        bcs     @Outside
        sec
        rts
@Outside:
        clc
        rts

QCButtonContainsPlayer:
        QC_INSIDE camera_y, QC_BUTTON_MIN_Y, QC_BUTTON_MAX_Y, BSP_WORLD_ORIGIN_Y, @Outside
        QC_INSIDE camera_z, QC_BUTTON_MIN_Z + QC_EYE_HEIGHT, QC_BUTTON_MAX_Z + QC_EYE_HEIGHT, BSP_WORLD_ORIGIN_Z, @Outside
        lda     f:quakec_button_pose
        asl
        tax
        lda     f:camera_x
        sec
        sbc     f:QCButtonTranslations,x
        sec
        sbc     #.loword((QC_BUTTON_MIN_X - BSP_WORLD_ORIGIN_X) * 16)
        cmp     #(QC_BUTTON_MAX_X - QC_BUTTON_MIN_X) * 16
        bcs     @Outside
        sec
        rts
@Outside:
        clc
        rts

QCDoorTranslations:
        .repeat QC_DOOR_STEPS + 1, I
        .word   .loword(-I * QC_DOOR_TRAVEL / (QC_DOOR_STEPS * 4))
        .endrepeat
QCButtonTranslations:
        .repeat QC_BUTTON_STEPS + 1, I
        .word   .loword(-I * QC_BUTTON_TRAVEL / (QC_BUTTON_STEPS * 4))
        .endrepeat

; Call during the real textured job, after issuing FX3 R15. The same
; once-per-vblank latch also admits simulation from MainLoop when idle.
.ifdef PLAYABLE_MAP_ID
  .if PLAYABLE_MAP_ID = PLAYABLE_E1M1_MAP_ID
        PLAYABLE_E1M1_FULL_X3_REFILL = 1
  .endif
.endif
QuakeCServiceFX3:
        RW_assume a16i16
        lda     f:FX3_R15
        beq     @Done
        lda     f:QC_INPUT_TICK
        cmp     f:quakec_last_tick
        beq     @Done
        lda     f:quakec_fx3_ticks
        inc
        sta     f:quakec_fx3_ticks
.ifdef PLAYABLE_COORDINATE_COOP
        lda     f:active_render_scale
        cmp     #2
  .ifdef PLAYABLE_E1M1_FULL_X3_REFILL
        bne     @CheckFullX3
  .else
        bne     @Service
  .endif
@Yield:
        lda     #1
  .ifdef PLAYABLE_COORDINATE_YIELD_DP
        sta     z:SpriteStreamCoordinateYield
        jsl     QuakeCService
        stz     z:SpriteStreamCoordinateYield
  .else
        sta     f:SpriteStreamCoordinateYield
        jsl     QuakeCService
        lda     #0
        sta     f:SpriteStreamCoordinateYield
  .endif
        rtl
  .ifdef PLAYABLE_E1M1_FULL_X3_REFILL
@CheckFullX3:
        jsl     QuakeCCheckFullX3Refill
        beq     @Yield
  .endif
@Service:
.endif
        bra     QuakeCService
@Done:
        rtl

.if .defined(PLAYABLE_E1M1_FULL_X3_REFILL) && .defined(PLAYABLE_COORDINATE_COOP)
        .pushseg
        .segment "CODE"
; A is the active render scale. Return Z set for a live Full X3 refill.
; This cold admission check need not occupy the linked QuakeC record bank.
QuakeCCheckFullX3Refill:
        RW_assume a16i16
        cmp     #3
        bne     @Return
        lda     f:render_coverage_mode
        bne     @Return
        lda     f:render_camera+10
        and     #$00FF
        cmp     #BSP_TECHNIQUE_TEXTURED_LIGHTMAP
@Return:
        rtl
        .popseg
.endif

QuakeCService:
        RW_assume a16i16
.ifdef PICKUP_BLEND
        lda     f:pickup_palette_wanted
        beq     :+
        cmp     f:pickup_palette_ready
        beq     :+
        jsl     PickupBuildPalette
:
.endif
.ifdef QC_QUEUED_INPUT
  .ifdef PLAYABLE_MAP_ID
        lda     f:playable_switch_pending
        bne     QuakeCServiceDone
  .else
        .res    6, $EA
  .endif
.endif
        lda     f:quake_restart_pending
        bne     QuakeCServiceDone
        lda     f:quakec_fault
        bne     QuakeCServiceDone
        lda     f:QC_INPUT_TICK
        cmp     f:quakec_last_tick
        beq     QuakeCServiceDone
        lda     f:quakec_last_tick
        inc
        sta     f:quakec_last_tick
        phb
        pea     $7f7f
        plb
        plb
.ifdef QC_E1M2_DEFER_UPLOAD
        inc     z:QCE1M2SimulationActive
.endif
QuakeCSimulationBegin:
.ifdef QC_QUEUED_INPUT
        jsl     GameplayConsumeInput
.ifdef QC_INTERMISSION_COUNT
        jsl     IntermissionService
        bcs     QuakeCSimulationCleanup
.endif
        jsl     GameplayCheckRespawn
        bcs     QuakeCSimulationCleanup
.endif
.if BSP_PLAYER_WALK
        jsr     WalkService
        lda     f:QC_INPUT_MENU_OPEN
        ora     f:QC_INPUT_RELEASE_GATE
        bne     :+
        jsr     GruntSyncPlayer
:       jsr     QuakeCShellTouch
.endif
        jsr     ShotgunService
.if BSP_PLAYER_WALK
        lda     a:w_landing_cue
        beq     :+
        jsr     WalkFinishLanding
:
.endif
        jsr     QuakeCStep
.ifdef QC_QUEUED_INPUT
        jsl     GameplayPublishPose
.else
        lda     a:qc_phase
        clc
        adc     #QC_PHASE_STEP
        cmp     #QC_VIDEO_RATE
        bcc     @Phase
        sbc     #QC_VIDEO_RATE
        sta     a:qc_phase
        jsr     QuakeCStep
        bra     @Finish
@Phase:
        sta     a:qc_phase
@Finish:
.endif
QuakeCSimulationCleanup:
.ifdef QC_E1M2_DEFER_UPLOAD
        stz     z:QCE1M2SimulationActive
.endif
QuakeCSimulationEnd:
        plb
.ifdef PICKUP_BLEND
        ; Finish the simulation transaction before preparing presentation data.
        lda     f:pickup_peak_pending
        beq     QuakeCServiceDone
        lda     #0
        sta     f:pickup_peak_pending
        jsl     PickupPalettePeak
.endif
QuakeCServiceDone:
        rtl

; E1M2 movers read the effective eye without moving it during Q6 substeps.
.if .defined(QC_QUEUED_INPUT) .and .defined(QC_E1M2_GROUP_COUNT) .and (!.defined(QC_E1M3_GOLD_KEY))
.assert .defined(QC_BASIC_GAMEPLAY) && QC_HUB_TELEPORT_COUNT = 0, error, "Mover eye requires stationary substeps"
QC_E1M2_SNAPSHOT_EYE = 1
.endif
QuakeCStep:
        inc     a:.loword(quakec_ticks)
.ifdef QC_QUEUED_INPUT
        ; Pusher deadlines retain their Q6 time base. Advance three units
        ; every 50 ms and one extra on every fifth step. Evaluate AI once.
        ldx     #(QC_STEP_RATE / QC_SIMULATION_HZ)
        lda     a:qc_phase
        clc
        adc     #(QC_STEP_RATE .mod QC_SIMULATION_HZ)
        cmp     #QC_SIMULATION_HZ
        bcc     :+
        sbc     #QC_SIMULATION_HZ
        inx
:
        sta     a:qc_phase
        stx     a:qc_elapsed_units
        stx     a:qc_mover_steps
  .ifdef QC_E1M2_SNAPSHOT_EYE
        jsl     QCE1M2SampleEye
  .endif
@MoveStep:
.endif
.if !.defined(QC_BASIC_GAMEPLAY)
        lda     f:quakec_contact
        beq     @Movers
        stz     a:.loword(quakec_contact)
        lda     a:qce+QC_BUTTON+QC_FIELD_STATE
        cmp     #64                    ; STATE_BOTTOM, where a touch can fire.
        bne     @Movers
        inc     a:.loword(quakec_activations)
        ldx     #QC_BUTTON
        ldy     #QC_ENTITY_STRIDE      ; Player edict.
        lda     a:qce+QC_BUTTON+QC_FIELD_TOUCH
        jsr     QuakeCEvent
@Movers:
        ldx     #QC_BUTTON
        ldy     #QC_BUTTON_MOVE
        jsr     QuakeCAdvancePusher
        ldx     #QC_DOOR
        ldy     #QC_DOOR_MOVE
        jsr     QuakeCAdvancePusher
        lda     f:quakec_door_pose
        asl
        clc
        adc     f:quakec_door_pose
        adc     f:quakec_button_pose
        sta     f:quakec_brush_row
        jsr     QuakeCEntranceTick
.ifdef QC_EXIT_MOVER_COUNT
        jsr     QuakeCExitTick
  .ifdef QC_SECRET_DOOR_COUNT
        jsr     QCSecretDoorsTick
        jsr     QCOrdDoorsTick
  .endif
.endif
.endif
.ifdef QC_E1M2_GROUP_COUNT
        jsr     QuakeCE1M2Tick
.endif
.if QC_HUB_ENABLED .or .defined(QC_EPISODE_EXIT_ENABLED)
.ifdef QC_INTERMISSION_COUNT
        lda     f:intermission_phase
        cmp     #2
        beq     :+
.endif
        jsr     QuakeCHubTick
:
.endif
.ifdef QC_QUEUED_INPUT
        dec     a:qc_mover_steps
        beq     :+
        jmp     @MoveStep
:
.endif
        lda     f:QC_INPUT_MENU_OPEN
        ora     f:QC_INPUT_RELEASE_GATE
        bne     :+
.ifdef QC_MEGA_COUNT
.ifdef QC_INTERMISSION_COUNT
        lda     f:intermission_phase
        cmp     #2
        beq     @SkipRot
.endif
        jsl     QuakeCMegaRot
@SkipRot:
.endif
        jsr     GruntTick
:       rts

; Rebase pusher movement to local time zero. Stock damage checks use
; the shared game clock even when the inflictor is a blocked door.
QuakeCEvent:
        stx     a:qcg+QC_GLOBAL_SELF
        sty     a:qcg+QC_GLOBAL_OTHER
        stz     a:qce+QC_FIELD_LTIME,x
        pha
        lda     a:grunt_clock
        sta     a:qcg+QC_GLOBAL_TIME
        lda     #512
        sta     z:qc_budget
        pla
        inc     a:.loword(quakec_callbacks)
        jsr     QuakeCInvokeOuter
QuakeCEventEnd:
        rts

QuakeCAdvancePusher:
        lda     a:qce+QC_FIELD_NEXTTHINK,x
        beq     @Idle
        bpl     @Active
@Idle:
        rts
@Active:
        dec     a:qce+QC_FIELD_NEXTTHINK,x
        stx     a:qc_entity
        tya
        clc
        adc     a:qc_entity
        tax
        stx     a:qc_axis
        lda     a:qce+QC_FIELD_VELOCITY,x
        bne     :+
        jmp     @Think
:       sta     a:qc_displacement
        ldx     a:qc_entity
        lda     a:qce+QC_PUSHER_FRACTION,x
        clc
        adc     a:qc_displacement
        pha
        and     #$3f
        sta     a:qc_fraction
        pla
        .repeat 6
        cmp     #$8000
        ror
        .endrepeat
        ldx     a:qc_axis
        clc
        adc     a:qce+QC_FIELD_ORIGIN,x
        sta     a:qc_candidate
        ldy     a:qc_entity
        lda     a:qce+QC_FIELD_NEXTTHINK,y
        bne     @Quantize
        lda     a:qce+QC_FIELD_FINALDEST,x
        sta     a:qc_candidate
@Quantize:
        jsr     QuakeCQuantizePose
        ldx     a:qc_entity
        cpx     #QC_DOOR
        bne     @Button
        lda     a:qc_displacement
        bmi     @Door
        lda     a:qc_pose
        cmp     f:quakec_door_pose
        beq     @Door
@CheckPlayer:
.ifdef QC_E1M1_PLATFORM_FIRST
        jsl     QCDoorCarryPlayer
.else
        lda     f:video_tick
        sta     a:qc_collision_tick
        lda     a:qc_pose
        jsr     QCDoorContainsPlayer
        php
        lda     f:video_tick
        cmp     a:qc_collision_tick
        beq     @Stable
        plp
        bra     @CheckPlayer
@Stable:
        plp
.endif
        bcs     @Blocked
@Door:
        jsr     GruntRideLift
        lda     a:qc_pose
.ifdef PLAYABLE_E1M1_WALK_RESUME_BYTES
        php
        cmp     f:quakec_door_pose
        beq     @DoorStored
.endif
        sta     f:quakec_door_pose
.ifdef PLAYABLE_E1M1_WALK_RESUME_BYTES
        jsl     MarkTraceResultCacheDirty
@DoorStored:
        plp
.endif
        bra     @Commit
@Button:
        lda     a:qc_pose
.ifdef PLAYABLE_E1M1_WALK_RESUME_BYTES
        php
        cmp     f:quakec_button_pose
        beq     @ButtonStored
.endif
        sta     f:quakec_button_pose
.ifdef PLAYABLE_E1M1_WALK_RESUME_BYTES
        jsl     MarkTraceResultCacheDirty
@ButtonStored:
        plp
.endif
@Commit:
        ldx     a:qc_axis
        lda     a:qc_candidate
        sta     a:qce+QC_FIELD_ORIGIN,x
        ldx     a:qc_entity
        lda     a:qc_fraction
        sta     a:qce+QC_PUSHER_FRACTION,x
@Think:
        ldx     a:qc_entity
        lda     a:qce+QC_FIELD_NEXTTHINK,x
        bne     @Done
        ldy     #0
        lda     a:qce+QC_FIELD_THINK,x
        jmp     QuakeCEvent
@Blocked:
        ldx     #QC_DOOR
        inc     a:qce+QC_FIELD_NEXTTHINK,x
        inc     a:.loword(quakec_door_blocks)
        ldy     #QC_ENTITY_STRIDE
        lda     a:qce+QC_FIELD_BLOCKED,x
        jmp     QuakeCEvent
@Done:
        rts

QuakeCQuantizePose:
        ldx     a:qc_entity
        cpx     #QC_DOOR
        beq     @Door
        lda     #QC_BUTTON_TRAVEL / QC_BUTTON_STEPS
        ldy     #QC_BUTTON_STEPS
        bra     @Limits
@Door:
        lda     #QC_DOOR_TRAVEL / QC_DOOR_STEPS
        ldy     #QC_DOOR_STEPS
@Limits:
        sta     a:qc_interval
        sty     a:qc_max_pose
        ldx     #0
        lda     a:qc_candidate
        bpl     @Pose
        jsr     QCNegate
        pha
        lda     a:qc_interval
        lsr
        clc
        adc     1,s
        plx
        ldx     #0
@Bucket:
        cmp     a:qc_interval
        bcc     @Pose
        sbc     a:qc_interval
        inx
        cpx     a:qc_max_pose
        bcc     @Bucket
@Pose:
        stx     a:qc_pose
        rts
