DiscardHeldOrderedFrame:
        RW_assume a16i16
        stz     stage_frame_required
        jmp     MainLoop

; Step playback advances the generated configured-rate stride after a frame is
; staged. This retains deterministic 2 Hz source-time coverage while
; benchmarking the complete changed-command render path as quickly as the
; renderer permits.
AdvanceDemoAfterStage:
        RW_assume a16i16
        BSP_SOUND_HOLD_DEMO AdvanceDemoReturn
        lda     demo_mode
        beq     AdvanceDemoReturn
        lda     staging_demo_epoch
        cmp     demo_schedule_revision
        bne     AdvanceDemoReturn
        lda     demo_schedule
        bne     AdvanceDemoReturn
        jsr     LoadNextDemoPose
        inc     demo_source_due_counter
AdvanceDemoReturn:
        stz     boot_ordered_source_pose
        rts
