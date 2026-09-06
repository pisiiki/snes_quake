; S-CPU staging and phase-overlay lifetime for the Quake sky compositor.

.assert ^__GSU_SKY_ROM_CODE_RUN__ = $82, lderror, "Sky compositor must remain in GSU ROM bank $02"
.assert BSP_SKY_PHASE_RECORD_BYTES = 3, error, "Sky phase staging requires packed LE24 records"
.assert BSP_SKY_PHASE_POSE_COUNT = BSP_DEMO_PRECISE_TRACK_POSE_COUNT, error, "Sky phase count must match the precise demo track"
.assert BSP_SKY_FLY_PHASE_Q16 = 0, error, "Fly sky initial phase must remain zero"
.assert BSP_SKY_FLY_CLOCK_FRACTION_BITS = 8, error, "Fly sky residual must remain Q8"
.assert BSP_SKY_PHASE_GSU_ROM_BANK = $03, error, "Sky phase debug identity moved from GSU ROM bank $03"
.assert BSP_SKY_PHASE_GSU_ROM_ADDRESS >= $8000, error, "Sky phase table escaped GSU ROM bank $03"
.assert BSP_SKY_PHASE_GSU_ROM_END_ADDRESS <= $10000, error, "Sky phase table crosses GSU ROM bank $03"

.segment "CODE"
InitSkyClock:
        RW_assume a16i16
        stz     sky_phase_override_q16
        stz     sky_phase_override_q16+2
        stz     sky_phase_override_valid
        stz     fly_sky_phase_q16
        stz     fly_sky_phase_q16+2
        stz     fly_sky_phase_fraction_q8
        stz     fly_sky_clock_revision
        stz     render_sky_phase_q16
        stz     render_sky_phase_q16+2
        stz     render_sky_present
        stz     staging_sky_phase_q16
        stz     staging_sky_phase_q16+2
        stz     staging_sky_present
        stz     slot_sky_phase_q16+0
        stz     slot_sky_phase_q16+2
        stz     slot_sky_phase_q16+4
        stz     slot_sky_phase_q16+6
        stz     slot_sky_present+0
        stz     slot_sky_present+2
        stz     presented_sky_phase_q16
        stz     presented_sky_phase_q16+2
        stz     presented_sky_present
        rts

; Fly time advances from unpaused NTSC VBlank, never from render completion.
; The generated Q8 residual schedule is within one part per million of the
; released eight-texel-per-second clock while remaining integer-exact.
UpdateFlySkyClock:
        RW_forced a16i16
        lda     runtime_menu_open
        bne     @Return
        lda     demo_mode
        bne     @Return
        lda     fly_sky_phase_fraction_q8
        clc
        adc     #BSP_SKY_FLY_CLOCK_FRACTION_STEP_Q8
        cmp     #$0100
        bcc     @BaseStep
        and     #$00FF
        sta     fly_sky_phase_fraction_q8
        lda     #BSP_SKY_FLY_CLOCK_PHASE_STEP_Q16+1
        bra     @AddPhase
@BaseStep:
        sta     fly_sky_phase_fraction_q8
        lda     #BSP_SKY_FLY_CLOCK_PHASE_STEP_Q16
@AddPhase:
        clc
        adc     fly_sky_phase_q16
        sta     fly_sky_phase_q16
        lda     fly_sky_phase_q16+2
        adc     #0
        and     #$007F
        sta     fly_sky_phase_q16+2
        inc     fly_sky_clock_revision
@Return:
        rts

; Preserve the canonical phase of the last demo frame that will become
; visible when the public runtime menu transitions to fly.  A ready frame is
; newer than an active upload, and both are newer than presented state.
SeedFlySkyClockFromDemo:
        RW_assume a16i16
        lda     frame_ready
        beq     @NoReadyFrame
        ldx     #0
        lda     ready_slot
        beq     :+
        ldx     #2
:
        lda     slot_demo_pose,x
        bra     @SeedPoseReady
@NoReadyFrame:
        lda     upload_active
        beq     @UsePresentedPose
        ldx     #0
        lda     upload_slot
        beq     :+
        ldx     #2
:
        lda     slot_demo_pose,x
        bra     @SeedPoseReady
@UsePresentedPose:
        lda     presented_demo_pose
@SeedPoseReady:
        cmp     #BSP_SKY_PHASE_POSE_COUNT
        bcs     @PresentedPhaseFallback
        sta     fly_sky_phase_fraction_q8
        asl
        clc
        adc     fly_sky_phase_fraction_q8
        tax
        RW      a8
        lda     f:QuakeBSPSkyPhases+0,x
        sta     fly_sky_phase_q16+0
        lda     f:QuakeBSPSkyPhases+1,x
        sta     fly_sky_phase_q16+1
        lda     f:QuakeBSPSkyPhases+2,x
        sta     fly_sky_phase_q16+2
        stz     fly_sky_phase_q16+3
        RW      a16
        bra     @Ready
@PresentedPhaseFallback:
        lda     presented_sky_phase_q16+0
        sta     fly_sky_phase_q16+0
        lda     presented_sky_phase_q16+2
        and     #$007F
        sta     fly_sky_phase_q16+2
@Ready:
        stz     fly_sky_phase_fraction_q8
        rts

StageSkyCommand:
        RW_assume a16i16
@Retry:
        lda     fly_sky_clock_revision
        pha
        lda     #0
        sta     f:GSU_DATA_BASE+GSU_SKY_PRESENT_OFFSET
        sta     f:GSU_DATA_BASE+GSU_SKY_PHASE_OFFSET
        sta     f:GSU_DATA_BASE+GSU_TURBULENCE_PRESENT_OFFSET
        sta     f:GSU_DATA_BASE+GSU_BRUSH_RASTER_RETURN_OFFSET
        sta     render_sky_phase_q16
        sta     render_sky_phase_q16+2
        sta     render_sky_present
        RW      a8
        sta     f:GSU_DATA_BASE+GSU_SKY_PHASE_OFFSET+2
        sta     f:GSU_DATA_BASE+GSU_SKY_FLAGS_OFFSET
        RW      a16
        lda     render_camera+10
        and     #$00FF
        cmp     #$0002
        bcc     @Ready
        cmp     #$0005
        bcs     @Ready
.if BSP_SKY_ENABLED
        RW      a8
        lda     #BSP_SKY_FLAG_ENABLED
        sta     f:GSU_DATA_BASE+GSU_SKY_FLAGS_OFFSET
        RW      a16
        ; Validation-only debugger seam. Production leaves valid at its
        ; zero-initialized default and follows the canonical fly/table path.
        lda     sky_phase_override_valid
        beq     @UseProductionPhase
        lda     sky_phase_override_q16
        sta     render_sky_phase_q16+0
        lda     sky_phase_override_q16+2
        and     #$007F
        sta     render_sky_phase_q16+2
        bra     @Publish
@UseProductionPhase:
        lda     render_demo_pose
        cmp     #$FFFF
        beq     @FlyPhase
        asl
        clc
        adc     render_demo_pose
        tax
        RW      a8
        lda     f:QuakeBSPSkyPhases+0,x
        sta     render_sky_phase_q16+0
        lda     f:QuakeBSPSkyPhases+1,x
        sta     render_sky_phase_q16+1
        lda     f:QuakeBSPSkyPhases+2,x
        sta     render_sky_phase_q16+2
        RW      a16
        bra     @Publish
@FlyPhase:
        lda     fly_sky_phase_q16+0
        sta     render_sky_phase_q16+0
        lda     fly_sky_phase_q16+2
        and     #$007F
        sta     render_sky_phase_q16+2
@Publish:
        lda     render_sky_phase_q16+0
        sta     f:GSU_DATA_BASE+GSU_SKY_PHASE_OFFSET+0
        RW      a8
        lda     render_sky_phase_q16+2
        sta     f:GSU_DATA_BASE+GSU_SKY_PHASE_OFFSET+2
        RW      a16
.endif
@Ready:
        pla
        cmp     fly_sky_clock_revision
        beq     :+
        jmp     @Retry
:
        rts

SnapshotRenderedSkyState:
        RW_forced a16i16
        lda     temporal_stage_metadata_only
        beq     @Capture
        ; A metadata-only texture presentation retains the exact prior pixels.
        ; Carry their special-surface evidence forward instead of observing
        ; StageCommand's intentionally cleared GSU flags.
        lda     staging_sky_present
        sta     render_sky_present
        lda     staging_turbulence_present
        sta     render_turbulence_present
        rts
@Capture:
        RW_forced a8i16
        lda     f:GSU_DATA_BASE+GSU_SKY_FLAGS_OFFSET
        and     #BSP_SKY_FLAG_PRESENTED
        beq     :+
        lda     #1
:
        sta     render_sky_present
        stz     render_sky_present+1
        sta     staging_sky_present
        stz     staging_sky_present+1
        RW      a16
        lda     f:GSU_DATA_BASE+GSU_TURBULENCE_PRESENT_OFFSET
        beq     :+
        lda     #1
:
        sta     render_turbulence_present
        sta     staging_turbulence_present
        rts

PresentSkyStateFromSlot:
        RW_assume a16i16
        ldx     #0
        lda     upload_slot
        beq     :+
        ldx     #4
:
        lda     slot_sky_phase_q16+0,x
        sta     presented_sky_phase_q16+0
        lda     slot_sky_phase_q16+2,x
        sta     presented_sky_phase_q16+2
        ldx     #0
        lda     upload_slot
        beq     :+
        ldx     #2
:
        lda     slot_sky_present,x
        sta     presented_sky_present
        rts

.segment "LORAM"
fly_sky_phase_q16: .res 4
fly_sky_phase_fraction_q8: .res 2
fly_sky_clock_revision: .res 2
render_sky_phase_q16: .res 4
render_sky_present: .res 2
staging_sky_phase_q16: .res 4
staging_sky_present: .res 2
slot_sky_phase_q16: .res 8
slot_sky_present: .res 4
presented_sky_phase_q16: .res 4
presented_sky_present: .res 2

.segment "CODE"
