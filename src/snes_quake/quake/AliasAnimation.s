; Quake EF_ROTATE: one 100-degree/second clock, independent of render speed.
.segment "CODE"
InitAliasClock:
        RW_assume a16i16
        stz     fly_alias_phase_q32
        stz     fly_alias_phase_q32+2
        stz     render_alias_yaw_q8
        rts

UpdateFlyAliasClock:
        RW_assume a16i16
.ifndef PLAYABLE_MAP_ID
        lda     runtime_menu_open
        bne     @Return
.endif
        lda     fly_alias_phase_q32
        clc
        adc     #(BSP_ALIAS_ROTATION_STEP_Q32 & $FFFF)
        sta     fly_alias_phase_q32
        lda     fly_alias_phase_q32+2
        adc     #(BSP_ALIAS_ROTATION_STEP_Q32 >> 16)
        sta     fly_alias_phase_q32+2
@Return:
        rts

; One 16-bit load snapshots the NMI-owned phase coherently. Round to 1/256
; turn and publish the two signed Q6 basis bytes once for the entire GSU job.
StageAliasRotation:
        RW_assume a16i16
.if BSP_QUAKEC_GAMEPLAY
        jsl     GruntStageRoster
        rts
.else
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
.endif

.segment "BSS"
fly_alias_phase_q32: .res 4
render_alias_yaw_q8: .res 2
