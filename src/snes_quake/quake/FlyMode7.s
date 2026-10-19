; FLY3X: two 110-pattern chunky pages in Mode 7's high VRAM byte lane.
; The entire low lane is blank except one active 11x10 rectangle at origin.
; Page flips change its 110 tile numbers; an unfinished page is never mapped.
.macro MODE7_VRAM_COPY word_address, source, count, port
        ldx     #word_address
        stx     VMADDL
        lda     #$80
        sta     VMAINC
        stz     DMAP7
        lda     #port
        sta     BBAD7
        ldx     #.loword(source)
        stx     A1T7L
        lda     #^(source)
        sta     A1B7
        ldx     #count
        stx     DAS7L
        lda     #$80
        sta     MDMAEN
.endmacro

InitializeFlyMode7Frame:
        RW_forced a16i16
        phx                             ; The selected renderer entry is in X.
        inc     gsu_job_counter
        RW_forced a8i16
        FX3_JOB_START FX3_SCMR_128X128_8BPP_ROM, .loword(Mode7ClearSource), set
        BSP_SOUND_FX3_JOB_JOIN 3
        stz     FX3_SCMR
        plx
        rts

PackFlyMode7Frame:
        RW_forced a16i16
        inc     gsu_job_counter
        ; Preserve opaque black while palette zero exposes the OBJ underlay.
        ldx     #48                    ; Natural palette's duplicate black.
        lda     render_camera+10
        and     #$00FF
        cmp     #BSP_TECHNIQUE_UNTEXTURED_LIGHTMAP
        bne     :+
        ldx     #64                    ; Unused black after the gray ramp.
:
        stx     FX3_R4
        RW_forced a8i16
        FX3_JOB_RUN FX3_SCMR_128X128_8BPP_ROM, .loword(Mode7PackFrame), set
PackFlyMode7FrameDone:
        stz     FX3_SCMR
        rts

InitFlyMode7Map:
        RW_forced a8i16
        ; Low-byte transfers advance after $2118, high-byte after $2119.
        ; This helper's low-lane copy therefore sets VMAIN to zero explicitly.
        stz     VMAINC
        ldx     #0
        stx     VMADDL
        lda     #$08                    ; Fixed-source fill of all 128x128 cells.
        sta     DMAP7
        lda     #$18
        sta     BBAD7
        ldx     #.loword(FlyMode7MapBlank)
        stx     A1T7L
        lda     #^FlyMode7MapBlank
        sta     A1B7
        ldx     #128*128
        stx     DAS7L
        lda     #$80
        sta     MDMAEN
        MODE7_VRAM_COPY 220*64, FlyMode7Blank, 64, $19
        ; The old $7800 OBJ font overlaps the full Mode 7 low lane. Its
        ; Mode 7 copy lives above all map/pattern bytes, with the same indices.
        VRAM_memcpy $B800, RuntimeMenuFont, RUNTIME_MENU_FONT_BYTES
        jsr     InitWarpBackground
        lda     #0
        jsr     SelectFlyMode7MapPage
        rts

SelectFlyMode7MapPage:
        RW_assume a8i16
        stz     VMAINC
        ldx     #.loword(FlyMode7ActiveMaps)
        cmp     #0
        beq     :+
        ldx     #.loword(FlyMode7ActiveMaps+110)
:
        stx     A1T7L
        lda     #^FlyMode7ActiveMaps
        sta     A1B7
        stz     DMAP7
        lda     #$18
        sta     BBAD7
        .repeat 10, row
          ldx   #row*128
          stx   VMADDL
          ldx   #11
          stx   DAS7L
          lda   #$80
          sta   MDMAEN
        .endrepeat
        rts

RestorePlanarMenuFont:
        RW_forced a16i16
        lda     upload_chunk
        bne     @Done
        lda     presented_format
        cmp     #BSP_UPLOAD_FORMAT_MODE7
        bne     @Done
        RW      a8
        VRAM_memcpy VRAM_RUNTIME_MENU_TILES, RuntimeMenuFont, RUNTIME_MENU_FONT_BYTES
        lda     #objsel(VRAM_RUNTIME_MENU_OBJ_BASE, OBJ_8x8_16x16, 0)
        sta     OBJSEL
@Done:
        RW_forced a16i16
        rts

InitFlyMode7Frame:
        RW_forced a8i16
        jsr     InitFlyMode7Map
        MODE7_VRAM_COPY 0, StagedFrame0, GSU_MODE7_FRAME_BYTES, $19
        MODE7_VRAM_COPY GSU_MODE7_FRAME_BYTES, StagedFrame0, GSU_MODE7_FRAME_BYTES, $19
        RW      a16
        .repeat 2, angle
          lda   staging_camera+angle*2
          sta   presented_warp_yaw+angle*2
        .endrepeat
        .repeat 3, position
          lda   slot_warp_x+position*4 ; Startup pixels and reference own slot 0.
          sta   presented_warp_x+position*2
        .endrepeat
        lda     staging_demo_epoch
        sta     presented_warp_epoch
        RW      a8
        rts

UploadFlyMode7Chunk:
        RW_forced a16i16
        lda     upload_chunk
        bne     @MapReady
        lda     presented_format
        cmp     #BSP_UPLOAD_FORMAT_MODE7
        beq     @MapReady
        ; The format transition is forced blank until this page completes.
        jsr     InitFlyMode7Map
        RW_forced a16i16
@MapReady:
        lda     upload_chunk
        cmp     #2
        bne     @Transfer
        lda     fly_warp_enabled
        beq     @CheckPublishTime
        lda     runtime_menu_open
        bne     @CheckPublishTime
        lda     hdma_ready
        beq     @HoldImage
        jsr     HdmaMetadataIndex
        jsr     LoadUploadFlyWarpReference
        ldx     hdma_metadata_offset
        jsr     HdmaReferenceMatches
        bcs     @CheckPublishTime
@HoldImage:
        jmp     UploadFrameReturn
@CheckPublishTime:
        ; Both transfers are complete. Publish in a separate VBlank, so
        ; palette/map/table/reference changes fit even with live HDMA.
        jsr     LatchHdmaBuildLine
        cmp     #248
        bcc     @Publish
        jsr     LoadPresentedFlyWarpReference
        jsr     CalculateFlyMode7Warp
        jsr     WriteFlyMode7Warp
        jmp     UploadFrameReturn
@Publish:
        jsr     PrepareFlyMode7UploadWarp
        RW      a8
        jmp     UploadPresentTexture
@Transfer:
        RW_forced a16i16
.if BSP_SOUND_ENABLED
        ; The setup half of a live warp already interleaves SPC packets.
        ; Move this bulk video transfer to the lighter half of the pair.
        ; X2/plain X3 and silent playback retain their original DMA cadence.
        lda     fly_warp_enabled
        beq     @TransferNow
        lda     hdma_deadline_armed
        beq     @TransferNow           ; First image must bootstrap the worker.
        lda     hdma_deadline_phase
        bne     @TransferNow
        lda     sound_cpu_state
        cmp     #SOUND_CPU_STATE_PLAYING
        bne     @TransferNow
        jsr     QuakeSoundCompatible
        bcc     @TransferNow
        jmp     UploadFrameReturn
@TransferNow:
.endif
        ; A delayed NMI plus the moving backdrop can leave too little VBlank
        ; for the usual half-page. Limit this transfer to 160 bytes per whole
        ; remaining line before 259: 1,280 DMA clocks leave refresh margin,
        ; and lines 259..261 cover setup/return and sprite pre-render at 0.
        ; Format transitions deliberately stay blank and may use full chunks.
        lda     SFX_inidisp
        and     #$0080
        bne     @FullBudget
        jsr     LatchHdmaBuildLine
        cmp     #225
        bcc     @DeferTransfer         ; Also reject wrap into active display.
        cmp     #259
        bcc     :+
@DeferTransfer:
        jmp     UploadFrameReturn
:
        lda     #259
        sec
        sbc     hdma_line_latch
        sta     DAS7L                 ; Scratch until the final count is ready.
        asl
        asl
        clc
        adc     DAS7L
        .repeat 5
          asl                         ; Remaining lines * 5 * 32 bytes.
        .endrepeat
        cmp     #BSP_MODE7_UPLOAD_CHUNK_BYTES
        bcc     @BudgetReady
@FullBudget:
        lda     #BSP_MODE7_UPLOAD_CHUNK_BYTES
@BudgetReady:
        tay
        clc
        adc     upload_offset
        cmp     #GSU_MODE7_FRAME_BYTES+1
        bcc     @CountReady
        lda     #GSU_MODE7_FRAME_BYTES
        sec
        sbc     upload_offset
        tay
@CountReady:
        lda     upload_offset
        ldx     upload_slot
        beq     @SlotZero
        clc
        adc     #.loword(StagedFrame1)
        bra     @SourceReady
@SlotZero:
        clc
        adc     #.loword(StagedFrame0)
@SourceReady:
        sta     A1T7L
        lda     upload_offset
        ldx     upload_target
        beq     @DestinationReady
        clc
        adc     #GSU_MODE7_FRAME_BYTES
@DestinationReady:
        sta     VMADDL
        sty     DAS7L
        RW      a8
        lda     #^StagedFrame0
        sta     A1B7
        lda     #$80
        sta     VMAINC
        stz     DMAP7
        lda     #$19
        sta     BBAD7
        lda     #$80
        sta     MDMAEN
        RW      a16
        inc     vram_chunk_counter
        tya
        clc
        adc     upload_offset
        sta     upload_offset
        ; 0 is unstarted, 1 is a partial page, 2 is complete and eligible for
        ; the existing next-VBlank map/table publication handshake.
        ldx     #1
        cmp     #GSU_MODE7_FRAME_BYTES
        bne     :+
        inx
:
        stx     upload_chunk
        jmp     UploadFrameReturn

F3_UploadPresentDirect:
        RW_forced a8i16
        lda     upload_target
        jsr     SelectFlyMode7MapPage
        jsr     WriteFlyMode7Warp
        RW_forced a8i16
        jsr     SetFlyMode7Flags
        ; All visible VRAM/palette/register changes are complete. Publish
        ; brightness before bookkeeping so the first active line is intact.
        lda     #inidisp(ON, DISP_BRIGHTNESS_MAX)
        sta     INIDISP
        lda     demo_mode
        beq     :+
        lda     fly_warp_enabled
        beq     :+
        RW_forced a16i16
        jsr     CalibrateDemoRenderPrediction
        RW_forced a8i16
:
        jmp     UploadPresented

; A8 records page 0/1. Negative A plus horizontal mirroring cancels the
; reversal and supplies an exact +85/256 sampling phase, without mosaic:
; source X = floor(85*(screenX+1)/256) = floor(X/3), independent of page.
; SNES visible scanline Y starts at 1 and supplies the same vertical phase.
; The equivalence holds across the 255x222 viewport; padding is source zero.
SetFlyMode7Display:
        RW_forced a8i16
        sta     fly_warp_page
        stz     fly_warp_page+1
        lda     fly_warp_reference_overscan+1
        beq     :+
        jmp     SetFlyMode7OverscanDisplay
:
        lda     #85
        pha
        sta     M7X
        stz     M7X
        pla
        sta     BG1HOFS
        stz     BG1HOFS
        stz     M7Y
        stz     M7Y
        stz     BG1VOFS
        stz     BG1VOFS
        lda     #$AB                    ; -85 in signed 8.8 format.
        sta     M7A
        lda     #$FF
        sta     M7A
        stz     M7B
        stz     M7B
        stz     M7C
        stz     M7C
        lda     #85
        sta     M7D
        stz     M7D
SetFlyMode7Flags:
        RW_assume a8i16
        lda     #$81                    ; Transparent outside map, H mirror.
        sta     M7SEL
        stz     MOSAIC
        stz     TMW
        lda     #7
        sta     BGMODE
        lda     #objsel($8000, OBJ_8x8_64x64, 0)
        sta     OBJSEL
        lda     #3
        sta     presented_render_scale
        jmp     RefreshWarpBackground

; Fallback still crops the retained wide source when HDMA is disabled or stale.
; Coefficients and pivot derive from the same focal constant as the renderer.
SetFlyMode7OverscanDisplay:
        RW_assume a8i16
        lda     #(85-((85-43)*(64-BSP_WARP_SOURCE_FOCAL)+32)/64)
        sta     M7X
        stz     M7X
        sta     BG1HOFS
        stz     BG1HOFS
        lda     #(37*(64-BSP_WARP_SOURCE_FOCAL)+63)/64
        sta     M7Y
        stz     M7Y
        dec
        sta     BG1VOFS
        stz     BG1VOFS
        lda     #.lobyte(-(85*BSP_WARP_SOURCE_FOCAL+32)/64)
        sta     M7A
        lda     #$FF
        sta     M7A
        stz     M7B
        stz     M7B
        stz     M7C
        stz     M7C
        lda     #(85*BSP_WARP_SOURCE_FOCAL+32)/64
        sta     M7D
        stz     M7D
        jmp     SetFlyMode7Flags

.segment "FLY_VIEWPORT_DATA"
FlyMode7MapBlank:
        .byte 220
FlyMode7ActiveMaps:
        .repeat 220, tile
          .byte tile
        .endrepeat
FlyMode7Blank:
        .res 64, 0
.segment "CODE"
