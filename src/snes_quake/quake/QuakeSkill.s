; The menu selects a skill for the next level load. Its selection lives
; outside QuakeCRamBegin..QuakeCRamEnd so reinitialization preserves it.

; A neutral fire sample must occur after death before a new press can respawn.
; UpdateCameraControls has already combined the pad and mouse inputs.
TryQuakeRespawn:
        RW_assume a16i16
        lda     QC_INPUT_BUTTONS
        and     #JOY_L
        bne     @Pressed
        lda     #1
        sta     f:quake_respawn_armed
        clc
        rts
@Pressed:
        lda     f:quake_respawn_armed
        beq     @WaitRelease
        lda     #1
.ifdef QC_QUEUED_INPUT
        sta     qc_respawn_release
.else
        sta     runtime_menu_release_gate
.endif
        RW      a8
        lda     #0
        sta     f:shotgun_flash
        sta     f:grunt_damage_flash_wram
.ifndef QC_QUEUED_INPUT
        jsr     ShotgunClearFlashColor
.endif
        RW      a16
        jsr     QueueQuakeRestart
        sec
        rts
@WaitRelease:
        clc
        rts

QueueQuakeRestart:
        RW_assume a16i16
        ; Finish the gameplay reload in MainLoop, outside VBlank and FX3.
        lda     #1
        sta     quake_restart_pending
        inc     demo_schedule_revision
.ifndef QC_QUEUED_INPUT
        RecenterFlyCameraPose
.endif
        rts

RestartQuakeLevel:
        RW_assume a16i16
        lda     upload_active
        ora     frame_ready
        and     #$ff
        beq     @Reload
        wai
        rts
@Reload:
.ifdef QC_QUEUED_INPUT
        lda     f:quakec_last_tick
        pha
        RW      a8
        lda     SFX_nmitimen
        and     #$7F
        sta     NMITIMEN
        RW      a16
        RecenterFlyCameraPose
        RW      a8
        lda     SFX_nmitimen
        sta     NMITIMEN
        RW      a16
.endif
        ; The SPC is already running. Preserve the S-CPU's end of its
        ; sound handshake while QuakeCInit clears gameplay WRAM.
        RW      a8
        lda     f:shotgun_sound_token
        pha
        RW      a16
        jsl     QuakeCInit
        RW      a8
        pla
        sta     f:shotgun_sound_token
.ifndef QC_BASIC_GAMEPLAY
        lda     #GAMEPLAY_AUX_LIFT_OFF
        jsl     GameplayPlayAuxSound
.endif
        RW      a16
.ifdef QC_QUEUED_INPUT
        pla
        sta     f:quakec_last_tick
.else
        lda     video_tick
        sta     f:quakec_last_tick
.endif
        stz     prefetched_selector_valid
        jsr     InvalidateDynamicBrushRenderState
        stz     quake_restart_pending
RestartQuakeLevelEnd:
        rts

.ifdef PLAYABLE_MAP_ID
QUAKE_SKILL_VALUE_BYTES = RUNTIME_MENU_SKILL_VALUE_BYTES
.else
QUAKE_SKILL_VALUE_COLUMN = 6
QUAKE_SKILL_VALUE_BYTES = RUNTIME_MENU_SKILL_COLUMNS - QUAKE_SKILL_VALUE_COLUMN
.endif

PatchQuakeSkillOAM:
        RW_forced a16i16
        lda     quake_skill_selected
        and     #3
        .repeat 4
        asl
        .endrepeat
        clc
        adc     #(QuakeSkillLabels - RuntimeMenuToggleValues)
        tax
.ifdef PLAYABLE_MAP_ID
        ldy     #RUNTIME_MENU_SKILL_VALUE_OAM + 2
.else
        ldy     #RUNTIME_MENU_SKILL_OAM + (QUAKE_SKILL_VALUE_COLUMN * RUNTIME_MENU_ENTRY_BYTES) + 2
.endif
        RW      a8
        lda     #QUAKE_SKILL_VALUE_BYTES
        jmp     WriteRuntimeMenuValue
