; Additive exact sky-phase command. Existing low23 telemetry remains intact.
; Called inside StageSkyCommand's clock-revision retry, in a16/i16 mode.
StageSkyExactPhase:
        RW_assume a16i16
        lda     sky_phase_override_valid
        beq     @Production
        lda     sky_phase_override_float32_valid
        beq     @LegacyOverride
        lda     #GSU_SKY_EXACT_PHASE_BINARY32
        sta     f:GSU_DATA_BASE+GSU_SKY_EXACT_PHASE_FORMAT_OFFSET
        lda     sky_phase_override_float32
        sta     f:GSU_DATA_BASE+GSU_SKY_EXACT_PHASE_OFFSET
        lda     sky_phase_override_float32+2
        sta     f:GSU_DATA_BASE+GSU_SKY_EXACT_PHASE_OFFSET+2
        lda     #0
        sta     f:GSU_DATA_BASE+GSU_SKY_EXACT_PHASE_OFFSET+4
        rts
@LegacyOverride:
        lda     #GSU_SKY_EXACT_PHASE_Q16
        sta     f:GSU_DATA_BASE+GSU_SKY_EXACT_PHASE_FORMAT_OFFSET
        lda     sky_phase_override_q16
        sta     f:GSU_DATA_BASE+GSU_SKY_EXACT_PHASE_OFFSET
        lda     sky_phase_override_q16+2
        and     #$0FFF
        sta     f:GSU_DATA_BASE+GSU_SKY_EXACT_PHASE_OFFSET+2
        lda     #0
        sta     f:GSU_DATA_BASE+GSU_SKY_EXACT_PHASE_OFFSET+4
        rts
@Production:
        lda     render_demo_pose
        cmp     #$FFFF
        beq     @Fly
        asl
        asl
        tax
        lda     #GSU_SKY_EXACT_PHASE_BINARY32
        sta     f:GSU_DATA_BASE+GSU_SKY_EXACT_PHASE_FORMAT_OFFSET
        lda     f:QuakeBSPSkyFloatPhases,x
        sta     f:GSU_DATA_BASE+GSU_SKY_EXACT_PHASE_OFFSET
        lda     f:QuakeBSPSkyFloatPhases+2,x
        sta     f:GSU_DATA_BASE+GSU_SKY_EXACT_PHASE_OFFSET+2
        lda     #0
        sta     f:GSU_DATA_BASE+GSU_SKY_EXACT_PHASE_OFFSET+4
        rts
@Fly:
        lda     #GSU_SKY_EXACT_PHASE_Q24
        sta     f:GSU_DATA_BASE+GSU_SKY_EXACT_PHASE_FORMAT_OFFSET
        ; Low23 phase and residual keep their existing published semantics.
        ; The five-bit epoch supplies only the previously discarded magnitude.
        lda     fly_sky_phase_fraction_q8
        and     #$00FF
        sta     f:GSU_DATA_BASE+GSU_SKY_EXACT_PHASE_OFFSET
        lda     fly_sky_phase_q16
        sta     f:GSU_DATA_BASE+GSU_SKY_EXACT_PHASE_OFFSET+1
        lda     fly_sky_phase_epoch
        lsr
        tax
        lda     fly_sky_phase_q16+2
        and     #$007F
        bcc     @FlyLowEpoch
        ora     #$0080
@FlyLowEpoch:
        sta     f:GSU_DATA_BASE+GSU_SKY_EXACT_PHASE_OFFSET+3
        txa
        sta     f:GSU_DATA_BASE+GSU_SKY_EXACT_PHASE_OFFSET+4
        rts
