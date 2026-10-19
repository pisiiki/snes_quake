; Estimate arrival latency L and replacement interval D independently, then
; render at now + L + ceil(D/2). Units are canonical 30 Hz playback poses.
DEMO_RENDER_LOOKAHEAD_POSES = 1       ; Initial guess, then publication calibrates it.
DEMO_RENDER_LOOKAHEAD_MAX = 64
DEMO_RENDER_LOOKAHEAD_TOLERANCE = 1
.assert BSP_DEMO_PRECISE_TRACK_POSE_COUNT * 10 <= $10000, error, "Demo camera record offsets exceed X16"

.segment "CODE"
StagePredictedDemoCamera:
        RW_assume a16i16
        stz     render_demo_prediction_lead
        stz     render_demo_prediction_bias
        lda     render_demo_epoch
        cmp     demo_prediction_epoch
        beq     @EpochReady
        sta     demo_prediction_epoch
        lda     #DEMO_RENDER_LOOKAHEAD_POSES
        sta     demo_prediction_lead
        sta     demo_prediction_interval
        stz     demo_prediction_error
        stz     demo_prediction_samples
        stz     demo_prediction_interval_error
        stz     demo_prediction_interval_samples
        stz     demo_prediction_interval_valid
@EpochReady:
.if BSP_SOUND_ENABLED
        ; Sound restarts/seeks from the first presented image of its epoch or
        ; lap. Publish that actual camera before predicting further images.
        lda     demo_schedule
        beq     @Predict
        lda     demo_playback_rate_shift
        bne     @Predict
        lda     sound_cpu_state
        cmp     #SOUND_CPU_STATE_PLAYING
        bne     @ActualCamera
        lda     sound_demo_epoch
        cmp     render_demo_epoch
        bne     @ActualCamera
        lda     sound_demo_loop
        cmp     demo_loop_counter
        beq     @Predict
@ActualCamera:
        clc
        rts
@Predict:
.endif
        lda     demo_prediction_interval
        inc                             ; Half poses round upward: ceil(D/2).
        lsr
        sta     render_demo_prediction_bias
        clc
        adc     demo_prediction_lead
        sta     render_demo_prediction_lead
        clc
        adc     render_demo_pose
        cmp     #BSP_DEMO_PRECISE_TRACK_POSE_COUNT
        bcc     @PoseReady
        lda     #BSP_DEMO_PRECISE_TRACK_POSE_COUNT-1
@PoseReady:
        sta     render_demo_pose
        sta     render_camera+14
        asl
        tax
        lda     f:QuakeBSPDemoPreciseTiming,x
        sta     render_demo_due_tick
        ; X is the two-byte pose offset; each camera record has ten bytes.
        txa
        asl
        adc     render_demo_pose       ; 4*pose ASL cannot carry for an X16 record.
        asl
        tax
  .repeat 3, Axis
        lda     f:QuakeBSPDemoPreciseTrack+Axis*2,x
        sec
    .if Axis = 0
        sbc     #.loword(BSP_WORLD_ORIGIN_X * 8)
    .elseif Axis = 1
        sbc     #.loword(BSP_WORLD_ORIGIN_Y * 8)
    .else
        sbc     #.loword(BSP_WORLD_ORIGIN_Z * 8)
    .endif
        asl
        sta     render_camera_q8+Axis*2
        sec
    .if Axis = 0
        sbc     #BSP_WORLD_START_X_Q8
    .elseif Axis = 1
        sbc     #BSP_WORLD_START_Y_Q8
    .else
        sbc     #BSP_WORLD_START_Z_Q8
    .endif
        xba
        and     #$00FF
        sta     render_camera+4+Axis*2
  .endrepeat
        lda     f:QuakeBSPDemoPreciseTrack+6,x
        clc
        adc     #$0400
        xba
        and     #$00F8
        sta     render_camera
        lda     #0
        sec
        sbc     f:QuakeBSPDemoPreciseTrack+8,x
        clc
        adc     #$0400
        xba
        and     #$00F8
        sta     render_camera+2
        sec                             ; The caller skips the live-camera copy.
        rts

; Called only for a newly mapped X3 image, after all visible PPU writes.
; Metadata-only commits never enter this callback. Keep the guard as well so
; every accepted observation explicitly belongs to immutable new pixels.
CalibrateDemoRenderPrediction:
        RW_assume a16i16
        lda     demo_mode
        beq     @Inactive
        lda     fly_warp_enabled
        beq     @Inactive
        lda     runtime_menu_open
        bne     @Inactive
        lda     upload_slot
        asl
        tax
        lda     slot_metadata_only,x
        bne     @Ignored                ; Same pixels: preserve the D anchor.
        lda     demo_schedule_revision
        cmp     demo_prediction_epoch
        bne     @Inactive
        cmp     slot_demo_epoch,x
        bne     @Inactive
        lda     slot_demo_pose,x
        ; A clamped endpoint supplies no useful latency feedback. A frame
        ; crossing a lap below is excluded too, without unsigned wrap ages.
        cmp     #BSP_DEMO_PRECISE_TRACK_POSE_COUNT-1
        bcs     @Inactive
.if BSP_SOUND_ENABLED
        lda     demo_schedule
        beq     @Clock
        lda     demo_playback_rate_shift
        bne     @Clock
        lda     sound_cpu_state
        cmp     #SOUND_CPU_STATE_PLAYING
        bne     @Inactive
        lda     sound_demo_epoch
        cmp     demo_schedule_revision
        bne     @Inactive
        lda     sound_demo_loop
        cmp     demo_loop_counter
        bne     @Inactive
.endif
        bra     @Clock
@Inactive:
        stz     demo_prediction_interval_valid
@Ignored:
        jmp     DemoPredictionFeedbackDone
@Clock:
        lda     demo_track_pose
        ldy     demo_schedule
        bne     @Error
        ldy     demo_warp_clock_valid
        beq     @Inactive
        ; Ordered 3 Hz's render cursor omits poses; its independent 30 Hz
        ; camera is the actual wall clock used to judge image arrival.
        lda     demo_warp_clock_pose
@Error:
        sta     demo_prediction_arrival_pose
        sec
        sbc     slot_demo_pose,x
        ; Reject cross-lap ages before removing this image's midpoint bias.
        cmp     #BSP_DEMO_PRECISE_TRACK_POSE_COUNT/2
        bcc     @Unbias
        cmp     #.loword(-(BSP_DEMO_PRECISE_TRACK_POSE_COUNT/2))
        bcc     @Inactive
@Unbias:
        pha                             ; D feedback must not change L's error.
        jsr     CalibrateDemoDisplayInterval
        pla
        clc
        adc     slot_demo_prediction_bias,x
        bmi     @Early
        sta     demo_prediction_error
        inc     demo_prediction_samples
        cmp     #DEMO_RENDER_LOOKAHEAD_TOLERANCE+1
        bcc     DemoPredictionFeedbackDone
        lda     demo_prediction_lead
        cmp     #DEMO_RENDER_LOOKAHEAD_MAX
        bcs     DemoPredictionFeedbackDone
        inc     demo_prediction_lead
        bra     DemoPredictionFeedbackDone
@Early:
        sta     demo_prediction_error
        inc     demo_prediction_samples
        cmp     #.loword(-DEMO_RENDER_LOOKAHEAD_TOLERANCE)
        bcs     DemoPredictionFeedbackDone
        lda     demo_prediction_lead
        beq     DemoPredictionFeedbackDone
        dec     demo_prediction_lead
DemoPredictionFeedbackDone:
        rts

; Consecutive actual new-image arrivals measure how long pixels stay visible.
; Repeated warps and metadata-only publications never advance this anchor.
; Preserve X: it identifies the immutable slot used by arrival feedback.
CalibrateDemoDisplayInterval:
        RW_assume a16i16
        lda     demo_prediction_interval_valid
        beq     @Anchor
        lda     demo_loop_counter
        cmp     demo_prediction_interval_loop
        bne     @Anchor                 ; Never subtract clocks across a lap.
        lda     demo_prediction_arrival_pose
        sec
        sbc     demo_prediction_interval_pose
        bmi     @Anchor                 ; A backward clock is not a lifetime.
        cmp     #DEMO_RENDER_LOOKAHEAD_MAX+1
        bcc     @Error
        lda     #DEMO_RENDER_LOOKAHEAD_MAX
@Error:
        inc     demo_prediction_interval_samples ; Before SBC owns the sign flags.
        sec
        sbc     demo_prediction_interval
        sta     demo_prediction_interval_error
        bmi     @Shorter
        cmp     #DEMO_RENDER_LOOKAHEAD_TOLERANCE+1
        bcc     @Anchor
        lda     demo_prediction_interval
        cmp     #DEMO_RENDER_LOOKAHEAD_MAX
        bcs     @Anchor
        inc     demo_prediction_interval
        bra     @Anchor
@Shorter:
        cmp     #.loword(-DEMO_RENDER_LOOKAHEAD_TOLERANCE)
        bcs     @Anchor
        lda     demo_prediction_interval
        beq     @Anchor
        dec     demo_prediction_interval
@Anchor:
        lda     demo_prediction_arrival_pose
        sta     demo_prediction_interval_pose
        lda     demo_loop_counter
        sta     demo_prediction_interval_loop
        lda     #1
        sta     demo_prediction_interval_valid
        rts

.pushseg
.segment "LORAM"
demo_prediction_lead:       .res 2 ; Unbiased first-presentation latency, 0..64.
demo_prediction_epoch:      .res 2
demo_prediction_error:      .res 2 ; Signed arrival error with image bias removed.
demo_prediction_samples:    .res 2 ; Only accepted new-image observations.
render_demo_prediction_lead: .res 2 ; Applied L + ceil(D/2), 0..96 before clamp.
render_demo_prediction_bias: .res 2 ; Extra half-period owned by this render.
staging_demo_prediction_bias: .res 2
slot_demo_prediction_bias:  .res 4 ; Immutable per-image feedback correction.
demo_prediction_interval:   .res 2 ; Independent new-image interval D, 0..64.
demo_prediction_interval_error: .res 2
demo_prediction_interval_samples: .res 2
demo_prediction_interval_pose: .res 2 ; Previous accepted arrival's real clock.
demo_prediction_interval_loop: .res 2
demo_prediction_interval_valid: .res 2
demo_prediction_arrival_pose: .res 2 ; Scratch actual clock shared by L and D.
.popseg
