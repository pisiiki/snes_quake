.ifdef PLAYABLE_E1M1_PREFETCH_GAMEPLAY_CODE
.pushseg
.segment "LORAM"
deferred_gameplay_tick: .res 2
deferred_live_input_tick: .res 2
.popseg
  .ifdef PLAYABLE_MAP_ID
    .assert PLAYABLE_MAP_ID = PLAYABLE_E1M1_MAP_ID, error, "Prefetched gameplay is scoped to E1M1"
PLAYABLE_E1M1_PREFETCH_GAMEPLAY = 1
  .endif
.endif

MainLoop:
        RW_forced a16i16
.ifdef PLAYABLE_MAP_ID
        lda     playable_switch_pending
        beq     :+
        jsr     PlayableServiceSwitch
        bra     MainLoop
:
.endif
.if BSP_QUAKEC_GAMEPLAY
        lda     quake_restart_pending
        beq     :+
        jsr     RestartQuakeLevel
        bra     MainLoop
:
.ifdef PLAYABLE_E1M1_PREFETCH_GAMEPLAY
        ; The completed selector already owns a frozen command. Give the
        ; textured renderer join a chance to service the next queued input.
        lda     prefetched_selector_valid
        beq     @ServiceGameplay
        jsr     DeferPrefetchedGameplay
        bcs     @AfterGameplay
@ServiceGameplay:
.endif
.ifdef PLAYABLE_FX3_PLANE_DISTANCE
        ; The renderer and selector joins can stop with live FX3 state.
        ; Only this foreground service can start an independent math job.
        lda     #1
        sta     f:qc_fx3_plane_foreground_wram
.endif
        jsl     QuakeCService
.ifdef PLAYABLE_FX3_PLANE_DISTANCE
        lda     #0
        sta     f:qc_fx3_plane_foreground_wram
.endif
.ifdef PLAYABLE_E1M1_PREFETCH_GAMEPLAY
@AfterGameplay:
.endif
.endif
