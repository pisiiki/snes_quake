; S-CPU clock and command staging for Quake turbulent special surfaces.

.assert BSP_TURBULENCE_ENABLED = 1, error, "Turbulence renderer requires generated assets"
.assert BSP_TURBULENCE_CYCLE = 128, error, "Turbulence phase mask requires 128 entries"
.assert BSP_TURBULENCE_PHASE_RECORD_BYTES = 3, error, "Turbulence staging requires packed LE24 Q16 phases"
.assert BSP_TURBULENCE_PHASE_POSE_COUNT = BSP_DEMO_PRECISE_TRACK_POSE_COUNT, error, "Turbulence phase count must match the precise demo track"
.assert BSP_TURBULENCE_FLY_CLOCK_FRACTION_BITS = 8, error, "Fly turbulence residual must remain Q8"
.assert BSP_TURBULENCE_PHASE_GSU_ROM_BANK = $03, error, "Turbulence phase identity moved from GSU ROM bank $03"
.assert BSP_TURBULENCE_PHASE_GSU_ROM_ADDRESS >= $8000, error, "Turbulence phase table escaped GSU ROM bank $03"
.assert BSP_TURBULENCE_PHASE_GSU_ROM_END_ADDRESS <= $10000, error, "Turbulence phase table crosses GSU ROM bank $03"

.segment "CODE"
InitTurbulenceClock:
        RW_assume a16i16
        stz     fly_turbulence_phase_q16
        stz     fly_turbulence_phase_q16+2
        stz     fly_turbulence_phase_fraction_q8
        stz     fly_turbulence_clock_revision
        stz     render_turbulence_phase_q16
        stz     render_turbulence_phase_q16+2
        stz     render_turbulence_present
        stz     staging_turbulence_phase_q16
        stz     staging_turbulence_phase_q16+2
        stz     staging_turbulence_present
        stz     slot_turbulence_phase_q16+0
        stz     slot_turbulence_phase_q16+2
        stz     slot_turbulence_phase_q16+4
        stz     slot_turbulence_phase_q16+6
        stz     presented_turbulence_phase_q16
        stz     presented_turbulence_phase_q16+2
        rts

; Advance the fly clock from unpaused NTSC VBlank. The generated residual
; schedule tracks Quake's 20-Hz phase without tying animation to render FPS.
UpdateFlyTurbulenceClock:
        RW_forced a16i16
        lda     runtime_menu_open
        bne     @Return
        lda     demo_mode
        bne     @Return
        lda     fly_turbulence_phase_fraction_q8
        clc
        adc     #BSP_TURBULENCE_FLY_CLOCK_FRACTION_STEP_Q8
        cmp     #$0100
        bcc     @BaseStep
        and     #$00FF
        sta     fly_turbulence_phase_fraction_q8
        lda     #BSP_TURBULENCE_FLY_CLOCK_PHASE_STEP_Q16+1
        bra     @AddPhase
@BaseStep:
        sta     fly_turbulence_phase_fraction_q8
        lda     #BSP_TURBULENCE_FLY_CLOCK_PHASE_STEP_Q16
@AddPhase:
        clc
        adc     fly_turbulence_phase_q16
        sta     fly_turbulence_phase_q16
        lda     fly_turbulence_phase_q16+2
        adc     #0
        and     #$007F
        sta     fly_turbulence_phase_q16+2
        inc     fly_turbulence_clock_revision
@Return:
        rts

; Seed fly mode from the newest frame that can become visible. The Q16 value
; comes from renderer server time, preserving the fractional phase at the
; demo/fly boundary instead of restarting or using wall-clock render cadence.
SeedFlyTurbulenceClockFromDemo:
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
        cmp     #BSP_TURBULENCE_PHASE_POSE_COUNT
        bcs     @RenderedPhaseFallback
        sta     fly_turbulence_phase_fraction_q8
        asl
        clc
        adc     fly_turbulence_phase_fraction_q8
        tax
        RW      a8
        lda     f:QuakeBSPTurbulencePhases+0,x
        sta     fly_turbulence_phase_q16+0
        lda     f:QuakeBSPTurbulencePhases+1,x
        sta     fly_turbulence_phase_q16+1
        lda     f:QuakeBSPTurbulencePhases+2,x
        sta     fly_turbulence_phase_q16+2
        stz     fly_turbulence_phase_q16+3
        RW      a16
        bra     @Ready
@RenderedPhaseFallback:
        lda     presented_turbulence_phase_q16+0
        sta     fly_turbulence_phase_q16+0
        lda     presented_turbulence_phase_q16+2
        and     #$007F
        sta     fly_turbulence_phase_q16+2
@Ready:
        stz     fly_turbulence_phase_fraction_q8
SeedFlyTurbulenceClockFromDemoDone:
        rts

; Publish one coherent integer phase after the owning render command is
; sampled. Demo phases originate in renderer server time; fly phases originate
; in the independent VBlank clock above. Revision retry closes an NMI race.
StageTurbulenceCommand:
        RW_assume a16i16
@Retry:
        lda     fly_turbulence_clock_revision
        pha
        lda     #GSU_TURBULENCE_TABLE_OFFSET
        sta     f:GSU_DATA_BASE+GSU_TURBULENCE_TABLE_BASE_OFFSET
        stz     render_turbulence_phase_q16
        stz     render_turbulence_phase_q16+2
        lda     render_camera+10
        and     #$00FF
        cmp     #$0002
        bcc     @Ready
        cmp     #$0005
        bcs     @Ready
        lda     render_demo_pose
        cmp     #$FFFF
        beq     @FlyPhase
        asl
        clc
        adc     render_demo_pose
        tax
        RW      a8
        lda     f:QuakeBSPTurbulencePhases+0,x
        sta     render_turbulence_phase_q16+0
        lda     f:QuakeBSPTurbulencePhases+1,x
        sta     render_turbulence_phase_q16+1
        lda     f:QuakeBSPTurbulencePhases+2,x
        sta     render_turbulence_phase_q16+2
        stz     render_turbulence_phase_q16+3
        RW      a16
        bra     @Publish
@FlyPhase:
        lda     fly_turbulence_phase_q16+0
        sta     render_turbulence_phase_q16+0
        lda     fly_turbulence_phase_q16+2
        and     #$007F
        sta     render_turbulence_phase_q16+2
@Publish:
        lda     render_turbulence_phase_q16+2
        and     #$007F
        clc
        adc     #GSU_TURBULENCE_TABLE_OFFSET
        sta     f:GSU_DATA_BASE+GSU_TURBULENCE_TABLE_BASE_OFFSET
@Ready:
        pla
        cmp     fly_turbulence_clock_revision
        beq     :+
        jmp     @Retry
:
        rts

PresentTurbulenceStateFromSlot:
        RW_assume a16i16
        ldx     #0
        lda     upload_slot
        beq     :+
        ldx     #4
:
        lda     slot_turbulence_phase_q16+0,x
        sta     presented_turbulence_phase_q16+0
        lda     slot_turbulence_phase_q16+2,x
        sta     presented_turbulence_phase_q16+2
        rts

.segment "LORAM"
fly_turbulence_phase_q16: .res 4
fly_turbulence_phase_fraction_q8: .res 2
fly_turbulence_clock_revision: .res 2
render_turbulence_phase_q16: .res 4
render_turbulence_present: .res 2
staging_turbulence_phase_q16: .res 4
staging_turbulence_present: .res 2
slot_turbulence_phase_q16: .res 8
presented_turbulence_phase_q16: .res 4

.segment "CODE"
