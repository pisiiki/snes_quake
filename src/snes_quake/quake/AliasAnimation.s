; Quake EF_ROTATE: one 100-degree/second clock, independent of render speed.
.segment "CODE"
InitAliasClock:
        RW_assume a16i16
        stz     fly_alias_phase_q32
        stz     fly_alias_phase_q32+2
        stz     render_alias_yaw_q8
        rts

UpdateFlyAliasClock:
        RW_forced a16i16
        lda     runtime_menu_open
        bne     @Return
        lda     demo_mode
        bne     @Return
        lda     fly_alias_phase_q32
        clc
        adc     #(BSP_ALIAS_ROTATION_STEP_Q32 & $FFFF)
        sta     fly_alias_phase_q32
        lda     fly_alias_phase_q32+2
        adc     #(BSP_ALIAS_ROTATION_STEP_Q32 >> 16)
        sta     fly_alias_phase_q32+2
@Return:
        rts

; Match the demo frame selected by the existing sky/turbulence transition.
SeedFlyAliasClockFromDemo:
        RW_assume a16i16
        lda     frame_ready
        beq     @NoReady
        ldx     #0
        lda     ready_slot
        beq     :+
        ldx     #2
:
        lda     slot_demo_pose,x
        bra     @Pose
@NoReady:
        lda     upload_active
        beq     @Presented
        ldx     #0
        lda     upload_slot
        beq     :+
        ldx     #2
:
        lda     slot_demo_pose,x
        bra     @Pose
@Presented:
        lda     presented_demo_pose
@Pose:
        cmp     #BSP_ALIAS_FLY_ROW
        bcs     @Return
        asl
        tax
        stz     fly_alias_phase_q32
        stz     fly_alias_phase_q32+2
        lda     f:BSP_ALIAS_ROTATION_PHASES_CPU_ADDRESS,x
        sta     fly_alias_phase_q32+2
@Return:
        rts

; One 16-bit load snapshots the NMI-owned phase coherently. Round to 1/256
; turn and publish the two signed Q6 basis bytes once for the entire GSU job.
StageAliasRotation:
        RW_assume a16i16
        lda     fly_alias_phase_q32+2
        clc
        adc     #$0080
        xba
        and     #$00FF
        sta     render_alias_yaw_q8
        asl
        tax
        lda     f:BSP_ALIAS_ROTATION_BASES_CPU_ADDRESS,x
        sta     f:GSU_DATA_BASE+GSU_ALIAS_ROTATION_OFFSET
        rts

.segment "BSS"
fly_alias_phase_q32: .res 4
render_alias_yaw_q8: .res 2
