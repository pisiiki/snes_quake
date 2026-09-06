; Immutable frame staging and the one-selector lookahead used to overlap the
; completed frame's WRAM DMA with disjoint bank-$71 selector work.

; The static-world packet owns projection and painter state for one complete
; camera pose. Keep the normal and overlapped selectors on the same predicate:
; yaw/pitch plus the packed position bytes consumed by the GSU, with committed
; guard/error authority. Low position bytes are presentation metadata only.
.macro REQUIRE_ACTIVE_PACKET_CAMERA_MATCH stale
        lda     active_packet_guard_status
        cmp     #GSU_PACKET_GUARD_VALUE
        bne     stale
        lda     active_packet_error
        bne     stale
        lda     active_packet_camera+0
        cmp     render_camera+0
        bne     stale
        lda     active_packet_camera+2
        cmp     render_camera+2
        bne     stale
        lda     active_packet_camera_q8+0
        eor     render_camera_q8+0
        and     #$FF00
        bne     stale
        lda     active_packet_camera_q8+2
        eor     render_camera_q8+2
        and     #$FF00
        bne     stale
        lda     active_packet_camera_q8+4
        eor     render_camera_q8+4
        and     #$FF00
        bne     stale
.endmacro

;-------------------------------------------------------------------------------
; Freeze every field consumed after StageCommand is allowed to publish the next
; command. The render_* identity remains owned by the next selector/renderer.
SnapshotRenderedFrameForStage:
        RW_forced a16i16
        lda     render_camera+0
        sta     staging_camera+0
        lda     render_camera+2
        sta     staging_camera+2
        lda     render_camera+4
        sta     staging_camera+4
        lda     render_camera+6
        sta     staging_camera+6
        lda     render_camera+8
        sta     staging_camera+8
        lda     render_camera+10
        sta     staging_camera+10
        lda     render_camera+12
        sta     staging_camera+12
        lda     render_camera+14
        sta     staging_camera+14
        lda     render_camera_q8+0
        sta     staging_camera_q8+0
        lda     render_camera_q8+2
        sta     staging_camera_q8+2
        lda     render_camera_q8+4
        sta     staging_camera_q8+4
        lda     render_brush_visual_state
        sta     staging_brush_visual_state
        lda     render_coverage_mode
        sta     staging_coverage_mode
        lda     render_demo_pose
        sta     staging_demo_pose
        lda     render_demo_due_tick
        sta     staging_demo_due_tick
        lda     render_demo_epoch
        sta     staging_demo_epoch
        lda     render_sky_phase_q16+0
        sta     staging_sky_phase_q16+0
        lda     render_sky_phase_q16+2
        sta     staging_sky_phase_q16+2
        lda     render_turbulence_phase_q16+0
        sta     staging_turbulence_phase_q16+0
        lda     render_turbulence_phase_q16+2
        sta     staging_turbulence_phase_q16+2
        jsr     SnapshotRenderedSkyState
        rts

;-------------------------------------------------------------------------------
; The texture DMA must begin early enough to finish before VBlank. The selector
; starts first while NMI remains enabled; this final gate certifies the actual
; DMA boundary without suppressing an input/presentation tick.
WaitForSafeStagingFrame:
        RW_forced a8i16
        lda     STAT78                  ; Reset OPVCT's low/high read toggle.
        lda     SLHV                    ; Latch and consume the full V counter.
        lda     OPVCT
        sta     staging_scanline
        lda     OPVCT
        and     #$01
        sta     staging_scanline+1
        RW      a16
        lda     staging_camera+10
        and     #$00FF
        cmp     #$0002
        bcc     @FlatLimit
        lda     staging_scanline
        cmp     #BSP_STAGING_TEXTURE_LIMIT
        bcc     @Safe
        bra     @Wait
@FlatLimit:
        lda     staging_scanline
        cmp     #BSP_STAGING_FLAT_LIMIT
        bcc     @Safe
@Wait:
        RW      a8
        lda     HVBJOY
        bmi     @WaitForActive
@WaitForVBlank:
        lda     HVBJOY
        bpl     @WaitForVBlank
@WaitForActive:
        lda     HVBJOY
        bmi     @WaitForActive
@Safe:
        RW_forced a8i16
        rts

;-------------------------------------------------------------------------------
; Publish frame N+1's command and start only its selector. Packet reuse skips
; the job; the normal RenderFrame path handles the cheap technique-only work.
TryStartOverlappedSelector:
        RW_forced a16i16
        stz     overlap_selector_active
        stz     prefetched_selector_valid
        jsr     StageCommand
        lda     coverage_debug
        sta     render_coverage_mode
        REQUIRE_ACTIVE_PACKET_CAMERA_MATCH @StartSelector
        rts
@StartSelector:
SelectorStageOverlapBegin:
        inc     gsu_job_counter
        RW      a8
        FX3_JOB_START FX3_SCMR_128X128_4BPP_ROM, .loword(GSU_SelectVisibility), set
        RW      a16
        lda     #$0001
        sta     overlap_selector_active
        rts

;-------------------------------------------------------------------------------
; Finish the selector only after the staging DMA and metadata publication. The
; subsequent renderer is therefore structurally unable to overwrite frame N.
JoinOverlappedSelector:
        RW_forced a16i16
        lda     overlap_selector_active
        beq     JoinOverlappedSelectorReturn
        RW      a8
        FX3_JOB_JOIN
        stz     FX3_SCMR
        RW      a16
        stz     overlap_selector_active
        jsr     CaptureSelectorTelemetry
        lda     runtime_menu_open
        bne     JoinOverlappedSelectorDiscard
        lda     #$0001
        sta     prefetched_selector_valid
SelectorStageJoinDone:
JoinOverlappedSelectorReturn:
        rts
JoinOverlappedSelectorDiscard:
        stz     prefetched_selector_valid
        stz     stage_frame_required
        bra     JoinOverlappedSelectorReturn

;-------------------------------------------------------------------------------
; Copy completed output into one of two WRAM producer slots, then associate the
; exact snapshotted camera and scheduler identity with that immutable slot.
StageExpandedFrame:
        RW_forced a16i16
        lda     temporal_stage_metadata_only
        beq     :+
TemporalMetadataOnlyStaging:
        jmp     SelectorStageMetadataOnly
:
        RW_forced a8i16
        stz     MDMAEN
        lda     producer_slot
        beq     @SlotZero
        ldx     #.loword(StagedFrame1)
        bra     @DestinationReady
@SlotZero:
        ldx     #.loword(StagedFrame0)
@DestinationReady:
        stx     WMADDL
        stz     WMADDH
        ldx     #.loword(GSU_OUTPUT)
        stx     A1T6L
        lda     #^GSU_OUTPUT
        sta     A1B6
        ldx     #GSU_OUTPUT_BYTES
        lda     staging_camera+10
        cmp     #$02
        bcc     @TransferSizeReady
        ldx     #GSU_TEXTURE_VISIBLE_BYTES
@TransferSizeReady:
        stx     DAS6L
        stz     DMAP6
        lda     #$80
        sta     BBAD6
SelectorStageDmaBegin:
        lda     #%01000000
        sta     MDMAEN

        RW      a16
SelectorStageDmaDone:
        RW_forced a16i16
        inc     staging_dma_counter
SelectorStageMetadataOnly:
        ldx     #0
        lda     producer_slot
        beq     @CameraSlotReady
        ldx     #CAMERA_COMMAND_BYTES
@CameraSlotReady:
        lda     staging_camera+0
        sta     slot_camera+0,x
        lda     staging_camera+2
        sta     slot_camera+2,x
        lda     staging_camera+4
        sta     slot_camera+4,x
        lda     staging_camera+6
        sta     slot_camera+6,x
        lda     staging_camera+8
        sta     slot_camera+8,x
        lda     staging_camera+10
        sta     slot_camera+10,x
        lda     staging_camera+12
        sta     slot_camera+12,x
        lda     staging_camera+14
        sta     slot_camera+14,x

        ldx     #0
        lda     producer_slot
        beq     @BrushStateSlotReady
        ldx     #2
@BrushStateSlotReady:
        lda     staging_brush_visual_state
        sta     slot_brush_visual_state,x

        ldx     #0
        lda     producer_slot
        beq     @CoverageSlotReady
        ldx     #2
@CoverageSlotReady:
        lda     staging_coverage_mode
        sta     slot_coverage_mode,x

        ldx     #0
        lda     producer_slot
        beq     @ReuseSlotReady
        ldx     #2
@ReuseSlotReady:
        lda     temporal_stage_metadata_only
        sta     slot_metadata_only,x

        ldx     #0
        lda     producer_slot
        beq     @DemoSlotReady
        ldx     #2
@DemoSlotReady:
        lda     staging_demo_pose
        sta     slot_demo_pose,x
        lda     staging_demo_due_tick
        sta     slot_demo_due_tick,x
        lda     staging_demo_epoch
        sta     slot_demo_epoch,x

        ldx     #0
        lda     producer_slot
        beq     @SkyPhaseSlotReady
        ldx     #4
@SkyPhaseSlotReady:
        lda     staging_sky_phase_q16+0
        sta     slot_sky_phase_q16+0,x
        lda     staging_sky_phase_q16+2
        sta     slot_sky_phase_q16+2,x

        ldx     #0
        lda     producer_slot
        beq     @TurbulencePhaseSlotReady
        ldx     #4
@TurbulencePhaseSlotReady:
        lda     staging_turbulence_phase_q16+0
        sta     slot_turbulence_phase_q16+0,x
        lda     staging_turbulence_phase_q16+2
        sta     slot_turbulence_phase_q16+2,x

        ldx     #0
        lda     producer_slot
        beq     @SkyPresentSlotReady
        ldx     #2
@SkyPresentSlotReady:
        lda     staging_sky_present
        sta     slot_sky_present,x

        ; Publish identity only after the exact pixels and metadata are in an
        ; immutable producer slot.
        lda     staging_camera+0
        sta     scheduled_frame_camera+0
        lda     staging_camera+2
        sta     scheduled_frame_camera+2
        lda     staging_camera+4
        sta     scheduled_frame_camera+4
        lda     staging_camera+6
        sta     scheduled_frame_camera+6
        lda     staging_camera+8
        sta     scheduled_frame_camera+8
        lda     staging_camera+10
        sta     scheduled_frame_camera+10
        lda     staging_camera+12
        sta     scheduled_frame_camera+12
        lda     staging_camera+14
        sta     scheduled_frame_camera+14
        lda     staging_brush_visual_state
        sta     scheduled_frame_brush_visual_state
        lda     staging_camera_q8+0
        sta     scheduled_frame_camera_q8+0
        lda     staging_camera_q8+2
        sta     scheduled_frame_camera_q8+2
        lda     staging_camera_q8+4
        sta     scheduled_frame_camera_q8+4
        lda     staging_coverage_mode
        sta     scheduled_frame_coverage_mode
        lda     #$0001
        sta     scheduled_frame_valid
        stz     temporal_stage_metadata_only
        stz     stage_frame_required
        RW_forced a16i16
        rts

SelectorStageTransferDone = SelectorStageDmaDone
