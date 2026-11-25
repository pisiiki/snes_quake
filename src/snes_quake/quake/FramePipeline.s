; Fixed frame pipeline; code generation emits a separate fly3x copy.
.include "Viewport.i"
.include "FrameImage.s"
FrameMain:
        jsr     RenderFrame
RenderFrameComplete:
        ; RenderFrame returns with M=0; keep assembler/runtime width aligned.
        RW_forced a16i16
.ifdef PLAYABLE_E1M1_PREFETCH_GAMEPLAY
        ; A discarded render or a short FX3 job may leave the service due.
        lda     deferred_gameplay_tick
        beq     @GameplayReady
        jsr     ServiceDeferredGameplay
@GameplayReady:
.endif
        lda     runtime_menu_open
        beq     :+
        stz     stage_frame_required
        stz     prefetched_selector_valid
        BSP_SOUND_WAIT_FRAME BSP_RENDER_SCALE
        jmp     MainLoop
:
        lda     stage_frame_required
        bne     CheckRenderedRevision
        lda     control_revision
        cmp     render_camera+12
        beq     @IdleVisible
        ; VBlank may have changed controls after RenderFrame found the prior
        ; identity current. Re-enter the renderer before sleeping so the newly
        ; visible command cannot wait for another interrupt edge.
        jmp     MainLoop
@IdleVisible:
        ; VBlank still advances input and wakes changed commands.
PresentationBoundaryWait:
        BSP_SOUND_WAIT_FRAME BSP_RENDER_SCALE
        jmp     MainLoop
CheckRenderedRevision:
        lda     demo_schedule_revision
        cmp     render_demo_epoch
        beq     @WaitForQueue
        ; A restart epoch may invalidate the rendered frame.
        stz     stage_frame_required
        jmp     MainLoop

@WaitForQueue:
        lda     frame_ready
        beq     @QueueReady
@QueueService:
        lda     frame_ready
        bne     @WaitForQueue
@QueueReady:
        lda     runtime_menu_open
        beq     :+
        stz     stage_frame_required
        BSP_SOUND_WAIT_FRAME BSP_RENDER_SCALE
        jmp     MainLoop
:
@StageFrame:
        ; Snapshot N before StageCommand may publish N+1. Starting the selector
        ; before the safe-window wait keeps NMI/input live while either the
        ; selector or the PPU scanline gate is the longer operation.
        jsr     SnapshotRenderedFrameForStage
        lda     demo_schedule_revision
        cmp     staging_demo_epoch
        beq     :+
        jmp     DiscardStaleFrameBeforeSelector
:
        ; Preserve the flat-render overlap through queue and snapshot work,
        ; then close it before publishing the next selector command.
        BSP_SOUND_FX3_JOB_JOIN BSP_RENDER_SCALE
RendererOutputReady:
.if BSP_RENDER_SCALE = 2
  .ifdef PLAYABLE_WEAPON_OBJ
        nop
  .else
        jsr     BlitStagingWeapon
  .endif
.endif
RendererCompositeReady:
        jsr     TryStartOverlappedSelector
        RW      a8
        lda     temporal_stage_metadata_only
        bne     @StagingGateReady
        jsr     WaitForSafeStagingFrame
@StagingGateReady:
        VBL_off
        RW      a16
        lda     demo_schedule_revision
        cmp     staging_demo_epoch
        beq     :+
        jmp     DiscardStaleStage
:
        RW      a8
        jsr     StageExpandedFrame
        RW_forced a16i16
        lda     producer_slot
        sta     ready_slot
        eor     #$01
        sta     producer_slot
        lda     #$01
        sta     frame_ready
FrameReadyPublished:
        RW_forced a8i16
        lda     RDNMI                   ; Discard any VBlank deferred by DMA.
        VBL_on
        RW_forced a16i16
        jsr     JoinOverlappedSelector
.if BSP_RENDER_SCALE = 2 && !.defined(PLAYABLE_WEAPON_OBJ)
        jsr     RestoreStagingWorld
.endif
        jmp     MainLoop
DiscardStaleFrameBeforeSelector:
        stz     stage_frame_required
        jmp     MainLoop
DiscardStaleStage:
        stz     prefetched_selector_valid
        RW      a8
        lda     RDNMI
        VBL_on
        RW      a16
        jsr     JoinOverlappedSelector
.if BSP_RENDER_SCALE = 2 && !.defined(PLAYABLE_WEAPON_OBJ)
        jsr     RestoreStagingWorld
.endif
        stz     prefetched_selector_valid
        stz     stage_frame_required
        jmp     MainLoop
.include "quake/FrameStaging.s"
StageCommand:
        RW_forced a16i16
StageCommandRetry:
.ifdef QUAKE_MSU_WORLD_KEEP
        lda     #0
        sta     f:GSU_DATA_BASE+MSU_WORLD_KEEP_READY
.endif
        lda     control_revision
        sta     render_camera+12
        lda     demo_schedule_revision
        sta     render_demo_epoch
StageCommandLiveCamera:
        lda     camera_x
        sta     render_camera_q8+0
        lda     camera_y
        sta     render_camera_q8+2
        lda     camera_z
        sta     render_camera_q8+4
        lda     yaw_index
        and     #CAMERA_ANGLE_MASK
        sta     render_camera+0
        lda     pitch_level
        and     #CAMERA_ANGLE_MASK
        sta     render_camera+2
        lda     camera_x
        sec
        sbc     #BSP_WORLD_START_X_Q8
        xba
        and     #$00FF
        sta     render_camera+4
        lda     camera_y
        sec
        sbc     #BSP_WORLD_START_Y_Q8
        xba
        and     #$00FF
        sta     render_camera+6
        lda     camera_z
        sec
        sbc     #BSP_WORLD_START_Z_Q8
        xba
        and     #$00FF
        sta     render_camera+8
StageCommandCameraReady:
.ifdef PLAYABLE_SWITCHED_LIGHTS
        jsl     SwitchedFrameMask
        sta     switched_render_mask
.endif
        ; Resolve into the unpublished snapshot; flight freezes its last seqlock state.
        stz     render_brush_visual_state
        lda     technique
        and     #$00FF
        sta     render_camera+10       ; A16 store also clears overlay flags.
        lda     dynamic_brushes_enabled
        bne     StageCommandResolveBrushState
        lda     mdl_entities_enabled
        and     #BSP_EXTERNAL_BSP_SUPPORTED
        beq     StageCommandBrushStateResolved
StageCommandResolveBrushState:
.if BSP_QUAKEC_GAMEPLAY
        lda     f:quakec_brush_row
        asl
        tax
        lda     f:BSP_BRUSH_ROWSTATE_CPU_ADDRESS,x
        sta     render_brush_visual_state
        bra     StageCommandCompleteFlyBrushState
.else
        lda     brush_visual_state
        sta     render_brush_visual_state
        lda     render_brush_visual_state
        bne     StageCommandCompleteFlyBrushState
StageCommandLoadBrushState:
        ldx     demo_track_pose
        txa
        asl
        tax
        lda     f:BSP_BRUSH_ROWSTATE_CPU_ADDRESS,x
        sta     render_brush_visual_state
.endif
StageCommandCompleteFlyBrushState:
        ; Fill demo-camera omissions while preserving the accepted brush poses.
        lda     render_brush_visual_state
        dec
        asl
        tax
        lda     f:BSP_BRUSH_FLYSTATE_CPU_ADDRESS,x
        sta     render_brush_visual_state
StageCommandBrushStateResolved:
.if BSP_QUAKEC_GAMEPLAY
  .if QC_ENTRANCE_COUNT > 0 .or .defined(QC_EXIT_MOVER_COUNT)
        jsl     QuakeCStageEntranceVisuals
  .endif
.endif
        lda     dynamic_brushes_enabled
        beq     StageCommandAliases
        lda     render_camera+10
        ora     #(BSP_OVERLAY_DYNAMIC_BRUSHES << 8)
        sta     render_camera+10
        lda     render_camera+10
        ora     #(BSP_OVERLAY_FLY_STATICS << 8)
        sta     render_camera+10
StageCommandAliases:
        ; Include entities from the all-leaf initial-pose snapshot.
        lda     mdl_entities_enabled
        beq     StageCommandOverlayReady
.if BSP_EXTERNAL_BSP_SUPPORTED
        lda     render_camera+10
        ora     #(BSP_OVERLAY_EXTERNAL_BSP << 8)
        sta     render_camera+10
.endif
.if .defined(QC_E1M2_GROUP_COUNT) && !BSP_ALIAS_LIVE_POSES
        lda     f:quakec_e1m2_key
        bne     StageCommandOverlayReady
.endif
        lda     render_camera+10
        ora     #(BSP_OVERLAY_ALIAS_ENTITIES << 8)
        sta     render_camera+10
StageCommandOverlayReady:
        lda     #$FFFF
        sta     render_demo_pose
.if BSP_ALIAS_LIVE_POSES
        lda     f:grunt_frame_wram
        tax
        lda     f:GruntFrameRows,x
        and     #$00ff
.else
        ; Quantize camera yaw to the nearest generated 45-degree orbit row.
        lda     render_camera+0
        clc
        adc     #CAMERA_ANGLE_STEPS/16
        lsr
        lsr
        lsr
        lsr
        lsr
        and     #(BSP_ALIAS_FLY_ROW_COUNT - 1)
        clc
        adc     #BSP_ALIAS_FLY_ROW
.endif
        sta     render_camera+14
        stz     render_demo_due_tick
.if BSP_QUAKEC_GAMEPLAY
  .ifdef QC_HEALTH_COUNT
        jsr     QuakeCExternalPickupMask
  .else
        lda     f:QuakeCShellMask       ; Live external brush links, in edict order.
  .endif
.else
        lda     demo_track_pose        ; Flight retains its accepted demo row.
.endif
        sta     f:GSU_COMMAND+14
.ifdef QC_MEGA_COUNT
        lda     pickup_render_high
        sta     f:GSU_DATA_BASE+GSU_PICKUP_MASK_HIGH
.endif
        ; Bind technique, flags, entity pose, and brush replay to one revision.
        jsr     StageSkyCommand
        jsr     StageAliasRotation
        jsr     StageTurbulenceCommand
        lda     control_revision
        cmp     render_camera+12
        beq     :+
        jmp     StageCommandRetry
:
        lda     demo_schedule_revision
        cmp     render_demo_epoch
        beq     :+
        jmp     StageCommandRetry
:
        lda     dynamic_brushes_enabled
        bne     :+
        lda     mdl_entities_enabled
        and     #BSP_EXTERNAL_BSP_SUPPORTED
        beq     StageCommandSnapshotReady
:
        lda     render_brush_visual_state
        sta     brush_visual_state
StageCommandSnapshotReady:
        jsr     EnsureBrushCode
.ifdef PLAYABLE_SWITCHED_LIGHTS
        jsr     SwitchedStageFlat
.endif

        RW      a8
        lda     render_camera+0
        sta     f:GSU_COMMAND+0
        lda     render_camera+2
        sta     f:GSU_COMMAND+1
        lda     render_camera+4
        sta     f:GSU_COMMAND+2
        lda     render_camera+6
        sta     f:GSU_COMMAND+3
        lda     render_camera+8
        sta     f:GSU_COMMAND+4
        lda     render_camera+10
        sta     f:GSU_COMMAND+5
        lda     render_camera+12
        sta     f:GSU_COMMAND+6
        lda     render_camera+13
        sta     f:GSU_COMMAND+7
        lda     render_camera_q8+1      ; Global map-centered signed coordinates.
        sta     f:GSU_COMMAND+8
        lda     render_camera_q8+3
        sta     f:GSU_COMMAND+9
        lda     render_camera_q8+5
        sta     f:GSU_COMMAND+10
        lda     render_camera+11
        sta     f:GSU_COMMAND+11        ; Overlay feature flags.
        RW      a16
        lda     render_brush_visual_state
        sta     f:GSU_COMMAND+12
.if BSP_QUAKEC_GAMEPLAY
        ; Convert rebased physics Q4 (one count per 1/16 Quake unit) to
        ; geometry Q2, rounding down to the map's render camera grid.
        ldx     #4
@StageCameraPosition:
        lda     render_camera_q8,x
        eor     #$8000          ; Bias to unsigned before shifting six bits.
        .repeat 6
        lsr
        .endrepeat
        sec
        sbc     #$0200
  .if BSP_PLAYABLE_CAMERA_POSITION_UNITS = 16
        and     #$FFFC
  .endif
        sta     f:GSU_DATA_BASE+GSU_PLAYABLE_CAMERA_Q2_X,x
        dex
        dex
        bpl     @StageCameraPosition
  .ifdef QC_EXIT_MOVER_COUNT
        jsl     QuakeCWriteExitVisuals
  .elseif QC_ENTRANCE_COUNT > 0
        lda     render_entrance_variants
        sta     f:GSU_DATA_BASE+GSU_ENTRANCE_VARIANTS_OFFSET
        lda     render_entrance_variants+2
        sta     f:GSU_DATA_BASE+GSU_ENTRANCE_VARIANTS_OFFSET+2
  .endif
.endif
        lda     render_camera+14
        sta     f:GSU_DATA_BASE+GSU_ALIAS_RENDER_ROW_OFFSET
        RW_forced a16i16
StageCommandFrozen:
        jmp     StageAliasVisibilityArchive
.include "quake/AliasVisibilityArchive.s"
;-------------------------------------------------------------------------------
RenderFrame:
        RW_forced a16i16
        ; Flat rendering overlaps the S-CPU queue work. Join that prior job
        ; before touching SCMR, SCBR, or the shared command for another frame.
        BSP_SOUND_FX3_JOB_JOIN BSP_RENDER_SCALE
        lda     prefetched_selector_valid
        beq     RenderStageSelectorCommand
        stz     prefetched_selector_valid
        lda     #$0001
        sta     stage_frame_required
        jmp     RenderAfterSelectorCapture
RenderStageSelectorCommand:
        RW      a8
        stz     FX3_SCMR
        jsr     StageCommand
        RW_forced a16i16
        lda     coverage_debug
        sta     render_coverage_mode       ; Bind the mode to this frame job.
.if BSP_RENDER_SCALE = 2 && !BSP_QUAKEC_GAMEPLAY
        jsr     SelectRenderWeapon
.endif
RenderRequired:
        lda     #$0001
        sta     stage_frame_required
        stz     temporal_stage_metadata_only
        ; Reuse a successfully guarded packet while the camera pose is
        ; unchanged instead of repeating the full-world selector/painter pass.
        ; Packet geometry depends on camera pose, not technique, diagnostic
        ; mode or the bookkeeping revision. Keep the
        ; full-Q8 position so every fly-camera movement still invalidates the
        ; selector even before it crosses a packed whole-unit boundary.
        REQUIRE_ACTIVE_PACKET_CAMERA_MATCH RenderRunSelector
        bra     RenderReusePacket
RenderReusePacket:
        RW_forced a8i16
        jmp     RenderSelectorComplete

RenderRunSelector:
.if .defined(PLAYABLE_RESIDENT_WORLD) && (BSP_RENDER_SCALE = 2)
        RW_forced a16i16
        lda     #0
        sta     f:GSU_DATA_BASE+GSU_RESIDENT_WORLD_STATUS
.endif
        ; StageCommand deliberately returns in 16-bit accumulator mode.
        ; Force the runtime mode back to 8-bit before the immediate below;
        ; relying on assembler width tracking across JSR would misdecode it.
        RW_forced a16i16
        inc     gsu_job_counter
        RW_forced a8i16
        FX3_JOB_START FX3_SCMR_128X128_4BPP_ROM, .loword(GSU_SelectVisibility), set
.ifdef PLAYABLE_VISIBILITY_STREAM
        jsr     VisibilityStreamJoinSelector
.else
        BSP_SOUND_FX3_JOB_JOIN BSP_RENDER_SCALE
.endif
        stz     FX3_SCMR
        jsr     CaptureSelectorTelemetry
RenderAfterSelectorCapture:
        ; A restart may have invalidated the selector's frozen command.
        RW_forced a16i16
        lda     demo_schedule_revision
        cmp     render_demo_epoch
        beq     RenderSelectorComplete
RenderDiscardSelector:
        stz     stage_frame_required
        rts
RenderSelectorComplete:
        RW_forced a16i16
        lda     runtime_menu_open
        beq     :+
        stz     stage_frame_required
        rts
:
        jmp     RenderStartRenderer
.include "quake/RendererDispatch.s"
.include "quake/TextureColormapModes.s"
.include "VideoInit.s"
