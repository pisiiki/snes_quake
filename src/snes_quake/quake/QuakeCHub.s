; Authored START and episode trigger volumes. The foreground queues complete teleports;
; the ordinary NMI position publisher commits XYZ, yaw and pitch together.
QuakeCHubTick:
        RW_assume a16i16
.if QC_HUB_ENABLED .or .defined(QC_EPISODE_EXIT_ENABLED)
  .if QC_HUB_SKILL_COUNT = 0
  .ifdef QC_E1M1_HINTS
        lda     a:shot_player+QC_FIELD_HEALTH
        beq     @ExitIdle
        bmi     @ExitIdle
        jsr     QuakeCHubAdvanceWarning
    .ifdef QC_E1M1_TELEPORT
        jsr     QuakeCEpisodeTeleportClock
    .endif
        bra     @Gates
  .else
        ; An episode map has one exit. Skip the XYZ sample far from its X span.
        lda     a:w_pending
        beq     @CameraX
        lda     a:w_pending_xyz
        bra     @ExitX
@CameraX:
        lda     f:camera_x
@ExitX:
        sec
        sbc     #.loword(QC_HUB_EXIT_MIN_X)
        cmp     #QC_HUB_EXIT_X_SPAN
        bcs     @ExitIdle
        lda     a:shot_player+QC_FIELD_HEALTH
        beq     @ExitIdle
        bpl     @Gates
  .endif
@ExitIdle:
        rts
  .else
        jsr     QuakeCHubAdvanceWarning
        lda     f:hub_teleport_cooldown
        beq     @Gates
        dec
        sta     f:hub_teleport_cooldown
  .ifdef QC_HUB_ARRIVAL_Q6
        cmp     #QC_HUB_TELEPORT_COOLDOWN-QC_HUB_ARRIVAL_Q6
        bne     @Gates
        inc     a:.loword(quakec_sounds)
        lda     #GAMEPLAY_AUX_ARRIVAL
        jsl     GameplayPlayAuxSound
  .endif
  .endif
@Gates:
        lda     f:QC_INPUT_MENU_OPEN
        ora     f:QC_INPUT_RELEASE_GATE
        ora     f:walk_pending_yaw_valid
  .ifdef PLAYABLE_MAP_ID
        ora     f:playable_switch_pending
  .else
        ; Source-only preview budgets the final long-address gate exactly.
        .res    4, $EA
  .endif
        beq     @Sample
        rts
@Sample:
        lda     f:video_tick
        sta     a:hub_sample_tick
        lda     a:w_pending
        beq     @Live
        lda     a:w_pending_xyz
        sta     f:hub_point
        lda     a:w_pending_xyz+2
        sta     f:hub_point+2
        lda     a:w_pending_xyz+4
        sta     f:hub_point+4
        bra     @Stable
@Live:
        lda     f:camera_x
        sta     f:hub_point
        lda     f:camera_y
        sta     f:hub_point+2
        lda     f:camera_z
        sta     f:hub_point+4
@Stable:
.ifdef QC_HUB_WARNING_COUNT
        lda     f:yaw_index
        and     #$00ff
        sta     a:hub_sample_yaw
.endif
        lda     f:video_tick
        cmp     a:hub_sample_tick
        bne     @Gates
  .if QC_HUB_SKILL_COUNT > 0
        ldx     #QC_HUB_SKILL_OFFSET
@Skill:
        jsr     QuakeCHubContains
        bcc     @NextSkill
        lda     f:QuakeCHubData+12,x
        sta     f:quake_skill_selected
        bra     @Teleports
@NextSkill:
        txa
        clc
        adc     #QC_HUB_SKILL_RECORD_BYTES
        tax
        cpx     #QC_HUB_SKILL_OFFSET+QC_HUB_SKILL_COUNT*QC_HUB_SKILL_RECORD_BYTES
        bcc     @Skill
@Teleports:
.ifdef QC_HUB_WARNING_COUNT
        jsr     QuakeCHubTouchWarning
.endif
  .endif
  .if QC_HUB_TELEPORT_COUNT > 0
        lda     f:hub_teleport_cooldown
        beq     :+
        jmp     @Exits
:       ldx     #QC_HUB_TELEPORT_OFFSET
@Teleport:
        jsr     QuakeCHubContains
        bcs     @QueueTeleport
        txa
        clc
        adc     #QC_HUB_TELEPORT_RECORD_BYTES
        tax
        cpx     #QC_HUB_TELEPORT_OFFSET+QC_HUB_TELEPORT_COUNT*QC_HUB_TELEPORT_RECORD_BYTES
        bcc     @Teleport
        jmp     @Exits
@QueueTeleport:
.ifdef QC_E1M1_TELEPORT
        .repeat 3, I
        lda     f:hub_point+2*I
        clc
        adc     #.loword(32 - (I = 2)*22*16)
        .repeat 6
        cmp     #$8000
        ror
        .endrepeat
        sta     f:teleport_departure_q2+2*I
        .endrepeat
.endif
        stz     a:w_pending
        lda     f:QuakeCHubData+12,x
        sta     a:w_pending_xyz
        lda     f:QuakeCHubData+14,x
        sta     a:w_pending_xyz+2
        lda     f:QuakeCHubData+16,x
        sta     a:w_pending_xyz+4
        lda     f:QuakeCHubData+18,x
        sta     f:walk_pending_yaw
.ifdef QC_QUEUED_INPUT
    .ifdef QC_E1M1_TELEPORT
        lda     #300*16/20              ; t6 launches east at 300 Quake units/s.
        sta     a:w_velocity_x
    .else
        stz     a:w_velocity_x
    .endif
        stz     a:w_velocity_y
.endif
        stz     a:w_velocity_z
        stz     a:w_grounded
        stz     a:w_support_valid
        stz     a:w_button_contact
        stz     a:w_failed_step_tick
        lda     #$ffff
        sta     a:w_failed_step_plane
        lda     #QC_HUB_TELEPORT_COOLDOWN
        sta     f:hub_teleport_cooldown
.ifdef QC_E1M1_TELEPORT
        jsr     TeleportDeathTouch
.endif
        lda     f:hub_teleports
        inc
        sta     f:hub_teleports
        lda     #1
        sta     f:walk_pending_yaw_valid
        sta     a:w_pending
        rts
  .endif
@Exits:
.ifdef QC_SECRET_COUNT
        jsr     QuakeCHubSecrets
.endif
.ifdef QC_E1M1_HINTS
        jsr     QuakeCHubTouchWarning
        ; The trigger_once records kill the linked hint before SUB_UseTargets
        ; can call it. An already published centerprint expires normally.
        lda     f:quake_skill_active
        cmp     #2
        bcs     :+
        ldx     #QC_HINT_DISMISS_OFFSET
        jsr     QuakeCHubDismissHint
        ldx     #QC_HINT_DISMISS_OFFSET+14
        jsr     QuakeCHubDismissHint
:
.endif
        ldx     #QC_HUB_EXIT_OFFSET
@Exit:
        jsr     QuakeCHubContains
        bcc     @NextExit
@ExitCall:
  .ifdef PLAYABLE_MAP_ID
    .if (QC_HUB_SKILL_COUNT > 0) .or (PLAYABLE_MAP_COUNT > QC_EPISODE_EXIT_MAP_ID)
        lda     f:QuakeCHubData+12,x
      .ifdef QC_INTERMISSION_COUNT
        jsl     IntermissionTouch
      .else
        jsl     PlayableRequestMapLong
      .endif
    .else
        .res    8, $EA
    .endif
  .else
        ; Keep the final load/call footprint before cartridge allocation.
        .res    8, $EA
  .endif
.assert *-@ExitCall = 8, error, "Exit request must fit the preview allocation"
        rts
@NextExit:
        txa
        clc
        adc     #QC_HUB_EXIT_RECORD_BYTES
        tax
        cpx     #QC_HUB_EXIT_OFFSET+QC_HUB_EXIT_COUNT*QC_HUB_EXIT_RECORD_BYTES
        bcc     @Exit
.endif
        rts

.if QC_HUB_ENABLED .or .defined(QC_EPISODE_EXIT_ENABLED)
  .if QC_HUB_SKILL_COUNT > 0
.assert QC_HUB_SKILL_COUNT = 4, error, "START must retain all four authored skills"
.assert QC_HUB_TELEPORT_COUNT > 0, error, "START hallway teleports are required"
  .else
    .ifdef QC_E1M1_TELEPORT
.assert QC_HUB_TELEPORT_COUNT = 1, error, "E1M1 must retain t6"
    .else
.assert QC_HUB_TELEPORT_COUNT = 0, error, "Unexpected episode teleport"
    .endif
  .endif
.assert QC_HUB_EXIT_COUNT = 1, error, "Each supported trigger table must contain one exit"
.assert QC_HUB_SKILL_RECORD_BYTES = 14, error, "Hub skill record changed"
.assert QC_HUB_TELEPORT_RECORD_BYTES = 20, error, "Hub teleport record changed"
.assert QC_HUB_EXIT_RECORD_BYTES = 14, error, "Hub exit record changed"
.assert QC_HUB_TELEPORT_COOLDOWN = 45, error, "Hub cooldown must match the independent host"

.ifdef QC_E1M1_TELEPORT
; spawn_tdeath grows the player's hull by one unit. Linking both edicts
; adds one unit to each side. Killed clamps a 50000-point telefrag to -99.
TeleportDeathTouch:
        ldx     #QC_GRUNT
@Actor: lda     a:qce+QC_FIELD_HEALTH,x
        beq     @Skip
        bmi     @Skip
        lda     a:qce+QC_FIELD_TAKEDAMAGE,x
        bne     @Bounds
@Skip:  jmp     @Next
@Bounds:
        .repeat 3,I
        lda     a:qce+QC_FIELD_ORIGIN+I*2,x
        sec
        sbc     #.loword(.ident(.sprintf("QC_TELEPORT_BODY_%c",88+I)))
        tay
        clc
        adc     a:qce+QC_FIELD_MAXS+I*2,x
        clc
        adc     #(19+8*(I=2))*8
        bmi     @Next
        tya
        clc
        adc     a:qce+QC_FIELD_MINS+I*2,x
        sec
        sbc     #(19+16*(I=2))*8+1
        bpl     @Next
        .endrepeat
        phx
        lda     #.loword(-99*64)
        sta     a:qce+QC_FIELD_HEALTH,x
        stx     a:qcg+8                ; Killed(targ, teledeath).
        stx     a:qcg+QC_GLOBAL_OTHER
        lda     #QC_GRUNT_DROP
        sta     a:qcg+14
        sta     a:qcg+QC_GLOBAL_SELF
        lda     a:grunt_clock
        sta     a:qcg+QC_GLOBAL_TIME
        lda     #4096
        sta     z:qc_budget
        lda     #QC_TELEFRAG_KILLED
        jsr     QuakeCInvokeOuter
        plx
@Next:  txa
        clc
        adc     #QC_ENTITY_STRIDE
        tax
        cmp     #QC_GRUNT_DROP
        bcs     @Done
        jmp     @Actor
@Done:  rts

; Freeze both TE_TELEPORT clouds into the same alias pose list as living actors.
TeleportStage:
        lda     f:hub_teleport_cooldown
        cmp     #QC_HUB_TELEPORT_COOLDOWN-21
        bcs     :+
        rts
:
        eor     #$ffff
        clc
        adc     #QC_HUB_TELEPORT_COOLDOWN+1
        asl
        phx
        tax
        lda     f:TeleportFogRows,x
        plx
        tay
        .repeat 6, E
        cpx     #(GSU_ALIAS_LIVE_COUNT*GSU_GRUNT_POSE_BYTES)
        bcc     :+
        rts
:       tya
        .if (E .mod 3) > 0
        clc
        adc     #((E .mod 3) << 8)
        .endif
        sta     f:GSU_LIVE_POSE_ADDRESS,x
        .repeat 3, I
        .if E < 3
        lda     f:teleport_departure_q2+2*I
        .else
        lda     #.loword(.ident(.sprintf("QC_TELEPORT_FOG_%c", 88+I)))
        .endif
        sta     f:GSU_LIVE_POSE_ADDRESS+2+2*I,x
        .endrepeat
        txa
        clc
        adc     #GSU_GRUNT_POSE_BYTES
        tax
        .endrepeat
@Done:  rts
TeleportFogRows:
        .repeat 22, I
        .word (QC_TELEPORT_FOG_ROW+3*((I*20+16)/64)) << 8
        .endrepeat

QuakeCEpisodeTeleportClock:
        lda     f:hub_teleport_cooldown
        beq     @Done
        dec
        sta     f:hub_teleport_cooldown
        cmp     #QC_HUB_TELEPORT_COOLDOWN-QC_HUB_ARRIVAL_Q6
        bcc     @Done
        beq     :+
        jmp     TeleportDeathTouch
:
        ; Both stock fog thinks choose a sound. The old position lies beyond
        ; audible distance from t6, so only the arriving voice reaches the player.
        jsr     ShotgunRandom
        inc     a:.loword(quakec_sounds)
        jsr     ShotgunRandom
        lda     a:qcg+2
        asl
        asl
        clc
        adc     a:qcg+2
        .repeat 6
        lsr
        .endrepeat
        clc
        adc     #16
        jsl     GameplayPlayTrackLong
@Done:  rts
.endif

; X remains the record offset. Inclusive unsigned interval differences handle
; native signed coordinates without overflowing on a zero-crossing box.
.macro HUB_INSIDE_AXIS axis
        .local Inside
        lda     f:QuakeCHubData+axis*4+2,x
        sec
        sbc     f:QuakeCHubData+axis*4,x
        sta     a:hub_extent
        lda     f:hub_point+axis*2
        sec
        sbc     f:QuakeCHubData+axis*4,x
        cmp     a:hub_extent
        bcc     Inside
        beq     Inside
        clc
        rts
Inside:
.endmacro

QuakeCHubContains:
        RW_assume a16i16
        HUB_INSIDE_AXIS 0
        HUB_INSIDE_AXIS 1
        HUB_INSIDE_AXIS 2
        sec
        rts

.ifdef QC_HUB_WARNING_COUNT
.assert (QC_HUB_WARNING_COUNT = 3 .or QC_HUB_WARNING_COUNT = 7 .or QC_HUB_WARNING_COUNT = 9) && QC_HUB_WARNING_RECORD_BYTES = 16, error, "START centerprint table changed"

; Hub ticks run at the shared 64-unit gameplay clock.
QuakeCHubAdvanceWarning:
        RW_assume a16i16
.ifdef QC_HUB_CLUE_EDICT
        lda     a:.loword(hub_clue_cooldown)
        beq     :+
        dec     a:.loword(hub_clue_cooldown)
:
.endif
        lda     a:.loword(hub_warning_ticks)
        beq     @Idle
        dec     a:.loword(hub_warning_ticks)
        bne     @Idle
        stz     a:.loword(hub_warning_gate)
@Idle:
        .repeat QC_HUB_WARNING_COUNT, gate
        lda     a:.loword(hub_warning_cooldowns)+gate*2
        beq     :+
.ifdef QC_E1M1_HINTS
        bmi     :+                       ; A killed trigger stays gone until restart.
.endif
        dec     a:.loword(hub_warning_cooldowns)+gate*2
:
        .endrepeat
        rts

QuakeCHubTouchWarning:
        RW_assume a16i16
        ldy     #0
        ldx     #QC_HUB_WARNING_OFFSET
.ifdef QC_E1M1_HINTS
        lda     f:quake_skill_active
        cmp     #2
        bcc     @Gate
        ldy     #4                       ; Hard and Nightmare exclude the jump triggers.
        ldx     #QC_HUB_WARNING_OFFSET+2*QC_HUB_WARNING_RECORD_BYTES
.endif
@Gate:
        lda     a:.loword(hub_warning_cooldowns),y
        bne     @Next
        jsr     QuakeCHubContains
        bcc     @Next
        lda     a:hub_sample_yaw
        sec
        sbc     f:QuakeCHubData+12,x
        and     #$00ff                  ; Facing arcs can cross byte yaw zero.
        cmp     f:QuakeCHubData+14,x
        bcc     @Warn
@Next:
        iny
        iny
        txa
        clc
        adc     #QC_HUB_WARNING_RECORD_BYTES
        tax
        cpy     #QC_HUB_WARNING_COUNT*2
        bcc     @Gate
        rts
@Warn:
.ifdef QC_E1M1_HINTS
        lda     #QC_HINT_REPEAT_Q6
        sta     a:.loword(hub_warning_cooldowns),y
        lda     #QC_HUB_WARNING_Q6
.else
        lda     #QC_HUB_WARNING_Q6
        sta     a:.loword(hub_warning_cooldowns),y
.endif
        sta     a:.loword(hub_warning_ticks)
        tya
        lsr
        inc
        sta     a:.loword(hub_warning_gate)
        inc     a:.loword(hub_warning_events)
        inc     a:.loword(quakec_sounds)
        lda     #10                     ; Stock misc/talk.wav, shared SPC slot.
        jmp     GameplayPlaySound
.endif

.ifdef QC_E1M1_HINTS
QuakeCHubDismissHint:
        jsr     QuakeCHubContains
        bcc     @Done
        lda     f:QuakeCHubData+12,x
        tay
        lda     #$ffff
        sta     a:.loword(hub_warning_cooldowns),y
@Done:
        rts
.endif

.ifdef QC_SECRET_COUNT
; Quake's trigger_secret is removed immediately from the touch set. The bit
; records discovery for this level, even if the player stays inside or dies.
QuakeCHubSecrets:
        lda     a:.loword(quakec_found_secrets)
        cmp     #QC_SECRET_COUNT
        beq     @Done
        ldx     #QC_SECRET_OFFSET
@Next:
        lda     f:QuakeCHubData+12,x
        bit     a:.loword(qc_secret_mask)
        bne     @Advance
        jsr     QuakeCHubContains
        bcc     @Advance
        lda     f:QuakeCHubData+12,x
        tsb     a:.loword(qc_secret_mask)
        inc     a:.loword(quakec_found_secrets)
        lda     #QC_HUB_WARNING_Q6
        sta     a:.loword(hub_warning_ticks)
        lda     #QC_SECRET_GATE
        sta     a:.loword(hub_warning_gate)
        inc     a:.loword(hub_warning_events)
        inc     a:.loword(quakec_sounds)
        lda     #GAMEPLAY_AUX_SECRET
        jsl     GameplayPlayAuxSound
@Advance:
        txa
        clc
        adc     #14
        tax
        cpx     #QC_SECRET_OFFSET+14*QC_SECRET_COUNT
        bcc     @Next
@Done:
        rts
.endif

.ifdef QC_HUB_CLUE_EDICT
.assert QC_HUB_CLUE_EDICT = QC_GRUNT && QC_HUB_CLUE_EDICT+QC_ENTITY_STRIDE = QC_EDICT_BYTES, error, "START clue must own the spare edict"
QuakeCHubShootClue:
        RW_assume a16i16
        lda     a:.loword(hub_clue_cooldown)
        bne     @Done
        lda     #QC_HUB_CLUE_REARM_Q6
        sta     a:.loword(hub_clue_cooldown)
        lda     #QC_HUB_WARNING_Q6
        sta     a:.loword(hub_warning_ticks)
        lda     #QC_HUB_CLUE_GATE
        sta     a:.loword(hub_warning_gate)
        inc     a:.loword(hub_warning_events)
        inc     a:.loword(quakec_sounds)
        lda     #GAMEPLAY_AUX_SECRET
        jsl     GameplayPlayAuxSound
@Done:
        rts
.endif

.if .defined(PLAYABLE_REGISTER_WALK_TRACE) .and QC_HUB_ENABLED
        .pushseg
        .segment "BSP_QUAKEC_BYTECODE"
.endif
QuakeCHubData:
.ifdef QC_HUB_SWIM_OFFSET
        .incbin "Data/QuakeBSPHubGameplay.bin", 0, QC_HUB_SWIM_OFFSET
.assert *-QuakeCHubData = QC_HUB_SWIM_OFFSET, error, "Hub prompt tables must precede the pool table"
.elseif .defined(QC_E1M1_HINTS) .and .defined(PLAYABLE_WEAPON_OBJ)
        ; The cartridge draws text with BG2. Only the software-weapon preview
        ; needs the large OAM text arrays that follow the touch records.
        .incbin "Data/QuakeBSPHubGameplay.bin", 0, QC_HUB_WARNING_OAM_TABLE_OFFSET
.else
        .incbin "Data/QuakeBSPHubGameplay.bin"
.assert *-QuakeCHubData = QC_HUB_BYTES, error, "Hub table length differs from its source descriptors"
.endif
.if .defined(PLAYABLE_REGISTER_WALK_TRACE) .and QC_HUB_ENABLED
        .popseg
.endif
.endif
