; Fixed frame pipeline; code generation emits a separate fly3x copy.
.include "Viewport.i"
.include "FrameImage.s"
.include "WarpOverscan.s"
FrameMain:
        jsr     RenderFrame
RenderFrameComplete:
        ; RenderFrame returns with M=0; keep assembler/runtime width aligned.
        RW_forced a16i16
        ; Cache warm-up needs the GSU-overlap service inside RenderFrame, but
        ; the held ordered pose must not become another presentation.
        BSP_SOUND_HOLD_DEMO DiscardHeldOrderedFrame
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
        ; VBlank still advances input/demo time and wakes changed commands.
PresentationBoundaryWait:
        BSP_SOUND_WAIT_FRAME BSP_RENDER_SCALE
        jmp     MainLoop
CheckRenderedRevision:
        lda     demo_schedule_revision
        cmp     render_demo_epoch
        bne     @DiscardRenderedFrame
        lda     demo_mode
        beq     @WaitForQueue
        lda     demo_schedule
        bne     @WaitForQueue
        lda     fly_playback_mode
        cmp     #RUNTIME_MENU_PLAYBACK_FLY3X
        bne     @OrderedRevision
        lda     fly_warp_enabled
        bne     @WaitForQueue          ; Independent camera clock may pass this job.
@OrderedRevision:
        lda     control_revision
        cmp     render_camera+12
        beq     @WaitForQueue
@DiscardRenderedFrame:
        ; Only step playback may discard ordinary camera revisions.
        stz     stage_frame_required
        jmp     MainLoop

@WaitForQueue:
  .if BSP_SOUND_ENABLED
        lda     sound_cpu_state
        cmp     #SOUND_CPU_STATE_PLAYING
        bne     @QueueService
  .endif
        lda     frame_ready
        beq     @QueueReady
@QueueService:
.if BSP_RENDER_SCALE = 3
        jsr     ServiceHdmaWarp
.endif
  .if BSP_SOUND_ENABLED
        ; Fast GSU jobs can finish before the previous upload drains. Keep
        ; the SPC ring fed while presentation owns the producer queue.
        jsr     QuakeSoundServiceMain
  .endif
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
        jsr     AdvanceDemoAfterStage
        ; Preserve the flat-render overlap through queue and snapshot work,
        ; then close it before publishing the next selector command.
        BSP_SOUND_FX3_JOB_JOIN BSP_RENDER_SCALE
RendererOutputReady:
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
        stz     prefetched_selector_valid
        stz     stage_frame_required
        jmp     MainLoop
.include "quake/FrameStaging.s"
StageCommand:
        RW_forced a16i16
StageCommandRetry:
        stz     render_demo_prediction_bias
        lda     control_revision
        sta     render_camera+12
        lda     demo_schedule_revision
        sta     render_demo_epoch
        lda     fly_warp_strafe
        sta     render_warp_strafe
        lda     fly_warp_forward
        sta     render_warp_forward
.if BSP_RENDER_SCALE = 3
        lda     demo_mode
        beq     StageCommandLiveCamera
        lda     fly_warp_enabled
        beq     StageCommandLiveCamera
        lda     demo_track_pose
        sta     render_demo_pose
        sta     render_camera+14
        lda     demo_pose_due_tick
        sta     render_demo_due_tick
        jsr     StagePredictedDemoCamera
        bcs     StageCommandCameraReady
.endif
StageCommandLiveCamera:
.if BSP_RENDER_SCALE = 3
        stz     demo_prediction_interval_valid ; Do not span Fly/plain/audio holds.
.endif
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
        lda     brush_visual_state
        sta     render_brush_visual_state
        lda     demo_mode
        bne     StageCommandLoadBrushState
        lda     render_brush_visual_state
        bne     StageCommandCompleteFlyBrushState
StageCommandLoadBrushState:
        ldx     demo_track_pose
.if BSP_RENDER_SCALE = 3
        ; Flight retains its last actual demo row.
        lda     demo_mode
        beq     @BrushRowReady
        lda     fly_warp_enabled
        beq     @BrushRowReady
        ldx     render_demo_pose
@BrushRowReady:
.endif
        txa
        asl
        tax
        lda     f:BSP_BRUSH_ROWSTATE_CPU_ADDRESS,x
        sta     render_brush_visual_state
StageCommandCompleteFlyBrushState:
        ; Fill demo-camera omissions while preserving the accepted brush poses.
        lda     demo_mode
        bne     StageCommandBrushStateResolved
        lda     render_brush_visual_state
        dec
        asl
        tax
        lda     f:BSP_BRUSH_FLYSTATE_CPU_ADDRESS,x
        sta     render_brush_visual_state
StageCommandBrushStateResolved:
        lda     dynamic_brushes_enabled
        beq     StageCommandAliases
        lda     render_camera+10
        ora     #(BSP_OVERLAY_DYNAMIC_BRUSHES << 8)
        sta     render_camera+10
        lda     demo_mode
        bne     StageCommandAliases
        lda     render_camera+10
        ora     #(BSP_OVERLAY_FLY_STATICS << 8)
        sta     render_camera+10
StageCommandAliases:
        ; Demo uses sampled entity rows; flight uses the all-leaf initial-pose snapshot.
        lda     mdl_entities_enabled
        beq     StageCommandOverlayReady
        lda     render_camera+10
        ora     #(BSP_OVERLAY_EXTERNAL_BSP << 8)
        sta     render_camera+10
        lda     render_camera+10
        ora     #(BSP_OVERLAY_ALIAS_ENTITIES << 8)
        sta     render_camera+10
StageCommandOverlayReady:
.if BSP_RENDER_SCALE = 3 .and BSP_WARP_SOURCE_FOCAL < 64
        lda     demo_mode
        beq     :+
        lda     fly_warp_enabled
        beq     :+
        lda     render_camera+10
        ora     #(BSP_OVERLAY_WARP_OVERSCAN << 8)
        sta     render_camera+10
:
.endif
        lda     demo_mode
        beq     @ManualDemoMetadata
.if BSP_RENDER_SCALE = 3
        lda     fly_warp_enabled
        bne     @PredictedMetadataReady
.endif
        lda     demo_track_pose
        sta     render_demo_pose
        sta     render_camera+14
        lda     demo_pose_due_tick
        sta     render_demo_due_tick
@PredictedMetadataReady:
        lda     render_demo_pose
        sta     f:GSU_COMMAND+14        ; Frozen demo row for brush lifecycle.
        bra     @DemoMetadataReady
@ManualDemoMetadata:
        lda     #$FFFF
        sta     render_demo_pose
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
        sta     render_camera+14
        stz     render_demo_due_tick
        lda     demo_track_pose
        sta     f:GSU_COMMAND+14        ; Flight retains its accepted demo row.
@DemoMetadataReady:
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
.if BSP_RENDER_SCALE = 3
.if BSP_WARP_SOURCE_FOCAL >= BSP_VIEW_CENTER_X
        jsr     EnsureWarpOverscanProjection
.endif
.endif
        jsr     EnsureBrushCode
.if (BSP_RENDER_SCALE = 3) && (BSP_WARP_SOURCE_FOCAL < BSP_VIEW_CENTER_X)
        ; The brush overlay contains packet-vertex outcodes. Install its
        ; focal patches only after a possible base-image restoration.
        jsr     EnsureWarpOverscanProjection
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
        lda     render_camera+14
        sta     f:GSU_DATA_BASE+GSU_ALIAS_RENDER_ROW_OFFSET
        RW_forced a16i16
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
        jsr     ClassifyScheduledFrameReuse
        beq     RenderRequired
        cmp     #$0002
        bne     RenderIdleReady
        inc     texture_input_reuse_counter
        sta     temporal_stage_metadata_only
        lda     #$0001
        sta     stage_frame_required

RenderIdleReady:
        RW_forced a16i16
        rts

RenderRequired:
        lda     #$0001
        sta     stage_frame_required
        stz     temporal_stage_metadata_only
        ; Reuse a successfully guarded packet while the camera pose is
        ; unchanged instead of repeating the full-world selector/painter pass.
        ; Packet geometry depends on camera pose, not technique, diagnostic
        ; mode, demo/manual source, or the bookkeeping revision. Keep the
        ; full-Q8 position so every fly-camera movement still invalidates the
        ; selector even before it crosses a packed whole-unit boundary.
        REQUIRE_ACTIVE_PACKET_CAMERA_MATCH RenderRunSelector
        bra     RenderReusePacket
RenderReusePacket:
        RW_forced a8i16
        jmp     RenderSelectorComplete

RenderRunSelector:
        ; StageCommand deliberately returns in 16-bit accumulator mode.
        ; Force the runtime mode back to 8-bit before the immediate below;
        ; relying on assembler width tracking across JSR would misdecode it.
        RW_forced a16i16
        inc     gsu_job_counter
        RW_forced a8i16
        FX3_JOB_START FX3_SCMR_128X128_4BPP_ROM, .loword(GSU_SelectVisibility), set
        BSP_SOUND_FX3_JOB_JOIN BSP_RENDER_SCALE
        stz     FX3_SCMR
        jsr     CaptureSelectorTelemetry
RenderAfterSelectorCapture:
        ; NMI exclusively advances the replay cursor and its candidate scratch.
        ; Calling UpdateRealtimeDemo here allowed an NMI to publish a due pose
        ; midway through this call, then the resumed foreground consumed the
        ; next pose using the old due tick. NMI already services every video tick.
        RW_forced a16i16
        lda     demo_schedule_revision
        cmp     render_demo_epoch
        bne     RenderDiscardSelector
        lda     demo_mode
        beq     RenderSelectorComplete
        lda     demo_schedule
        bne     RenderSelectorComplete
        lda     fly_playback_mode
        cmp     #RUNTIME_MENU_PLAYBACK_FLY3X
        bne     @OrderedRevision
        lda     fly_warp_enabled
        bne     RenderSelectorComplete
@OrderedRevision:
        lda     control_revision
        cmp     render_camera+12
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
