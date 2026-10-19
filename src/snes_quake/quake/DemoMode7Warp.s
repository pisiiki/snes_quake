; The image keeps its rendered camera; this independent view follows the
; recorded track between renders. It never changes the renderer/source clock.
.macro DEMO_WARP_ASR Count
  .repeat Count
        cmp     #$8000
        ror
  .endrepeat
.endmacro

UpdateDemoWarpCamera:
        RW_assume a16i16
        BSP_SOUND_HOLD_DEMO DemoWarpCameraReturn
        ; Use the schedule's exact recorded pose, including its fine angles.
        ; No intermediate camera positions or angles are synthesized.
        lda     demo_track_pose
        ldx     demo_schedule
        bne     :+
        ldx     demo_warp_clock_valid
        beq     :+
        lda     demo_warp_clock_pose
:
        sta     demo_warp_pose
        asl
        sta     demo_warp_offset
        asl
        asl
        clc
        adc     demo_warp_offset
        tax
  .repeat 4, Component
        lda     f:QuakeBSPDemoPreciseTrack+Component*2,x
        sta     demo_warp_camera+Component*2
  .endrepeat
        lda     #0
        sec
        sbc     f:QuakeBSPDemoPreciseTrack+8,x
        sta     demo_warp_camera+8
        lda     demo_schedule_revision
        sta     demo_warp_epoch
        lda     video_tick
        sta     demo_warp_sample_tick
DemoWarpCameraReturn:
        rts

FinishDemoWarpCamera:
        RW_assume a16i16
        jsr     UpdateDemoWarpCamera
        jmp     FinishHdmaWarpCamera

; Ordered X3 WARP samples the canonical 30 Hz sequence on a video clock.
; Rendering receives only each configured stride; a slow render may coalesce
; commands but cannot stop the camera. Ordinary ordered X2/X3 is unchanged.
UpdateWarpOrderedDemo:
        ; This clock is owned exclusively by NMI. Foreground selector joins
        ; call UpdateRealtimeDemo, which leaves ordered playback untouched.
        RW_forced a16i16
        BSP_SOUND_HOLD_DEMO WarpOrderedDemoReturn
        lda     demo_schedule
        beq     :+
        RW      a8
        rts
:
        RW_assume a16i16
        lda     fly_playback_mode
        cmp     #RUNTIME_MENU_PLAYBACK_FLY3X
        bne     @Ordinary
        lda     fly_warp_enabled
        bne     @Warp
@Ordinary:
        stz     demo_warp_clock_valid
        RW      a8
        rts
@Warp:
        RW_assume a16i16
        lda     demo_warp_clock_valid
        beq     @First
        lda     demo_warp_clock_epoch
        cmp     demo_schedule_revision
        bne     @First
        lda     video_tick
        cmp     demo_warp_clock_tick
        beq     WarpOrderedDemoReturn
        sta     demo_warp_clock_tick
        bra     @Tick
@First:
        lda     #1
        sta     demo_warp_clock_valid
        lda     demo_schedule_revision
        sta     demo_warp_clock_epoch
        lda     video_tick
        sta     demo_warp_clock_tick
        lda     demo_track_pose
        sta     demo_warp_clock_pose
        stz     demo_warp_clock_phase
        stz     demo_warp_render_phase
        bra     WarpOrderedDemoReturn
@Tick:
        lda     demo_warp_clock_phase
        eor     #1
        sta     demo_warp_clock_phase
        bne     WarpOrderedDemoReturn
        inc     demo_warp_clock_pose
        lda     demo_warp_clock_pose
        cmp     #BSP_DEMO_PRECISE_TRACK_POSE_COUNT
        bcc     @RenderStride
        stz     demo_warp_clock_pose
        inc     demo_loop_counter
        bra     @RenderPose
@RenderStride:
        inc     demo_warp_render_phase
        lda     demo_warp_render_phase
        cmp     demo_ordered_pose_stride
        bcc     WarpOrderedDemoReturn
@RenderPose:
        stz     demo_warp_render_phase
        lda     demo_warp_clock_pose
        sta     demo_track_pose
        asl
        tax
        lda     f:QuakeBSPDemoPreciseTiming,x
        sta     demo_pose_due_tick
        txa
        sta     demo_warp_offset
        asl
        asl
        clc
        adc     demo_warp_offset
        tax
        jsr     LoadDemoPoseRecord
        inc     demo_pose_counter
        inc     demo_source_due_counter
        inc     control_revision
WarpOrderedDemoReturn:
        RW      a8
        rts
