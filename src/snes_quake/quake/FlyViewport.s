; Frame-level selection only. The running frame owns its private pipeline and
; its queued presentation callback even if a menu change arrives during work.

InitFlyViewport:
        RW_assume a16i16
        lda     #.loword(FrameMain)
        sta     frame_pipeline_entry
        lda     #2
        sta     active_render_scale
        sta     presented_render_scale
.ifndef PLAYABLE_MAP_ID
        lda     #RUNTIME_MENU_PLAYBACK_FLY
        sta     fly_playback_mode
.endif
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
.ifndef PLAYABLE_WEAPON_OBJ
        jsr     BlitStagingWeapon
.endif
        jsr     StageExpandedFrame
.ifndef PLAYABLE_WEAPON_OBJ
        jsr     RestoreStagingWorld
.endif
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

; X3 samples every third screen pixel from the same planar tile pool as X2.
; Three copies of a tile and the 3*x mod 8 swizzle expose all eight pixels.
.if BSP_QUAKEC_GAMEPLAY
FLY3_WORLD_HSCROLL = 3
.else
FLY3_WORLD_HSCROLL = 0
.endif

F3_UploadPresentDirect:
        RW_forced a8i16
        jsr     SetFly3MosaicDisplay
        lda     upload_target
        beq     @PageA
        lda     #bg12nba(VRAM_TEXTURE_TILES_B, 0)
        sta     BG12NBA
        jmp     UploadPresented
@PageA:
        lda     #bg12nba(VRAM_TEXTURE_TILES_A, 0)
        sta     BG12NBA
        jmp     UploadPresented

SetFly3MosaicDisplay:
        RW_assume a8i16
        lda     #3
        sta     presented_render_scale
        lda     #$21
        sta     MOSAIC
        lda     #bgsc(VRAM_FLY3_TILEMAP, SC_SIZE_32X32)
        sta     BG1SC
.if BSP_QUAKEC_GAMEPLAY
        lda     #FLY3_WORLD_HSCROLL
        sta     BG1HOFS
.else
        stz     BG1HOFS
.endif
        stz     BG1HOFS
        lda     #$FF
        sta     BG1VOFS
        sta     BG1VOFS
        ; The 85 source columns occupy 255 screen columns.
        lda     #$03
        sta     W12SEL
        stz     WH0
        lda     #254
        sta     WH1
        lda     #1
        sta     TMW
        rts

.segment "FLY_VIEWPORT_DATA"
Fly3Reciprocal:
  .repeat GSU_RECIPROCAL_RAM_ENTRIES, depth
    .if depth < 4
        .word 0
    .else
        .word (16384 + depth / 2) / depth
    .endif
  .endrepeat
Fly3CoordinateMap:
  .repeat 128, coordinate
        .byte (coordinate & $F8) | ((coordinate * 3) & 7)
  .endrepeat
Fly3Tilemap:
  .repeat 32, row
    .repeat 32, column
      .if BSP_QUAKEC_GAMEPLAY
        ; At sample 3*x+3, H flip selects the swizzled column 84-x.
        ; The first partial source tile occupies map columns 0 and 1.
        .word $4000 | ((row / 3) * 16 + 10 - (column + 1) / 3)
      .else
        .word (row / 3) * 16 + column / 3
      .endif
    .endrepeat
  .endrepeat
.assert * - Fly3Tilemap = $0800, error, "X3 mosaic tilemap must be 32x32"
.segment "CODE"
