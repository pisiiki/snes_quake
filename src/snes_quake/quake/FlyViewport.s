; Frame-level selection only. The running frame owns its private pipeline and
; its queued presentation callback even if a menu change arrives during work.

InitFlyViewport:
        RW_assume a16i16
        lda     #.loword(FrameMain)
        sta     frame_pipeline_entry
        lda     #2
        sta     active_render_scale
        sta     presented_render_scale
        lda     #RUNTIME_MENU_PLAYBACK_FLY
        sta     fly_playback_mode
        lda     #1
        sta     fly_warp_enabled
        ; Install the small deferred tracing overlay once before NMI starts.
        jsr     EnsureFlyAliasCode
        rts

RequestFlyViewport:
        RW_assume a16i16
        lda     runtime_menu_draft_scale
        bne     @Three
        lda     #RUNTIME_MENU_PLAYBACK_FLY
        cmp     fly_playback_mode
        beq     @Done
        sta     fly_playback_mode
        lda     #.loword(InstallFramePipeline)
        bra     @Publish
@Three:
        lda     #RUNTIME_MENU_PLAYBACK_FLY3X
        cmp     fly_playback_mode
        beq     @Done
        sta     fly_playback_mode
        lda     #.loword(F3_InstallFramePipeline)
@Publish:
        sta     frame_pipeline_entry
        ; A resolution change invalidates image identity, not demo time.
        inc     control_revision
        jsr     InvalidateScheduledFrameIdentity
@Done:
        rts

BootRenderViewport:
        RW_forced a16i16
        lda     fly_playback_mode
        cmp     #RUNTIME_MENU_PLAYBACK_FLY3X
        beq     BootRenderViewportThree
        jsr     RenderFrame
        FX3_JOB_JOIN
StartupRendererOutputReady:
        jsr     SnapshotRenderedFrameForStage
        jsr     StageExpandedFrame
        jmp     InitVideo
BootRenderViewportThree:
        jsr     F3_LoadFramePipelineImage
        jsr     F3_RenderFrame
        FX3_JOB_JOIN
        jsr     F3_SnapshotRenderedFrameForStage
        jsr     F3_StageExpandedFrame
        jsr     F3_InitVideo
        RW_forced a16i16
        lda     #.loword(F3_FrameMain)
        sta     frame_pipeline_entry
        RW_forced a8i16
        rts

.include "quake/FlyMode7.s"
.include "quake/WarpBackground.s"
.include "quake/FlyMode7Warp.s"
.include "quake/DemoMode7Warp.s"
.include "quake/HdmaWarp.s"

.segment "FLY_VIEWPORT_DATA"
Fly3Reciprocal:
  .repeat GSU_RECIPROCAL_RAM_ENTRIES, depth
    .if depth < 4
        .word 0
    .else
        .word (16384 + depth / 2) / depth
    .endif
  .endrepeat
Fly3WarpReciprocal:
  .repeat GSU_RECIPROCAL_RAM_ENTRIES, depth
    .if depth < 4
        .word 0
    .else
        .word (BSP_WARP_SOURCE_FOCAL * 256 + depth / 2) / depth
    .endif
  .endrepeat
Fly3CoordinateMap:
  .repeat 128, coordinate
        .byte (coordinate & $F8) | ((coordinate * 3) & 7)
  .endrepeat
.segment "CODE"
