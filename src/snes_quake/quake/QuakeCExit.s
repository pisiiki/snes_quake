; The linked pair times out after leaving its stock touch bounds. The bridge
; switch and three counter switches latch and fire when they reach the stop.
.assert QC_EXIT_MOVER_COUNT = 10 .and QC_EXIT_POSE_COUNT = 4, error, "Unexpected E1M1 exit mover roster"
QuakeCExitTick:
        lda     f:walk_pending
        bne     @Pending
        lda     f:camera_y
        bra     @YReady
@Pending:
        lda     f:WalkPendingXYZ+2
@YReady:
        sta     a:qc_exit_eye+2
        lda     a:qc_exit_started
        bne     @Eye
        lda     a:qc_exit_eye+2
        eor     #$8000
        cmp     #.loword(QC_EXIT_FIRST_Y ^ $8000)
        bcs     :+
        rts
:       inc     a:qc_exit_started
@Eye:
        lda     f:walk_pending
        bne     @PendingEye
        lda     f:camera_x
        sta     a:qc_exit_eye
        lda     f:camera_z
        bra     @EyeReady
@PendingEye:
        lda     f:WalkPendingXYZ
        sta     a:qc_exit_eye
        lda     f:WalkPendingXYZ+4
@EyeReady:
        sta     a:qc_exit_eye+4
        lda     a:qc_exit_wait
        beq     :+
        dec     a:qc_exit_wait
:       lda     a:qce+QC_ENTITY_STRIDE+QC_FIELD_HEALTH
        beq     @DoorTarget
        bmi     @DoorTarget
        ldx     #0
        jsr     QCExitTouches
        bcc     :+
        lda     #QC_EXIT_DOOR_WAIT
        sta     a:qc_exit_wait
:
.repeat 4, I
        lda     a:.loword(quakec_exit_targets)
        bit     #(1 << (I+3))
        bne     :+
        ldx     #(I+1)*12
        jsr     QCExitTouches
        bcc     :+
        lda     a:.loword(quakec_exit_targets)
        ora     #(1 << (I+3))
        sta     a:.loword(quakec_exit_targets)
:
.endrepeat
@DoorTarget:
        lda     a:qc_exit_wait
        beq     @CloseDoors
        lda     a:.loword(quakec_exit_targets)
        ora     #3
        bra     @DoorReady
@CloseDoors:
        lda     a:.loword(quakec_exit_targets)
        and     #$FFFC
@DoorReady:
        sta     a:.loword(quakec_exit_targets)
        lda     a:qc_exit_ages+6
        cmp     f:QCExitDurations+6
        bcc     @CheckCounter
        lda     a:.loword(quakec_exit_targets)
        ora     #4
        sta     a:.loword(quakec_exit_targets)
@CheckCounter:
.repeat 3, I
        lda     a:qc_exit_ages+(I+4)*2
        cmp     f:QCExitDurations+(I+4)*2
        bcc     @MotionStart
.endrepeat
        lda     a:.loword(quakec_exit_targets)
        ora     #128
        sta     a:.loword(quakec_exit_targets)
@MotionStart:
        stz     a:qc_exit_updated
        ldx     #0
@Motion:
        lda     a:.loword(quakec_exit_targets)
        and     f:QCExitBits,x
        beq     @Backward
        lda     a:qc_exit_ages,x
        cmp     f:QCExitDurations,x
        bcs     @Next
        inc     a:qc_exit_ages,x
        bra     @Pose
@Backward:
        lda     a:qc_exit_ages,x
        beq     @Next
        dec     a:qc_exit_ages,x
@Pose:
        lda     a:qc_exit_ages,x
        sta     a:qc_exit_age
        phx
        txa
        asl
        asl
        tax
        ldy     #0
.repeat 3, I
        lda     a:qc_exit_age
        cmp     f:QCExitPoseThresholds+I*2,x
        bcc     @Store
        iny
.endrepeat
@Store:
        plx
        tya
        cmp     a:qc_exit_poses,x
        beq     @Next
        sta     a:qc_exit_poses,x
        jsr     QCExitStoreActive
        inc     a:qc_exit_updated
@Next:
        inx
        inx
        cpx     #QC_E1M1_PLATFORM_FIRST*2
        bcc     @Motion
        jsr     QCPlatformsTick
        lda     a:qc_exit_updated
        beq     @Done
        sta     a:qc_exit_collision_dirty
        stz     a:w_support_valid
        lda     a:qc_exit_poses+18
        xba
        ora     a:qc_exit_poses+16
        sta     f:quakec_exit_pose_word_high
        ldx     #(QC_E1M1_PLATFORM_FIRST-1)*2
        lda     #0
@Pack:
        asl
        asl
        ora     a:qc_exit_poses,x
        dex
        dex
        bpl     @Pack
        sta     a:.loword(quakec_exit_pose_word)
@Done:  rts

QCExitInitActive:
        ldx     #(QC_E1M1_PLATFORM_FIRST-1)*2
@Load:
        lda     #0
        jsr     QCExitStoreActive
        dex
        dex
        bpl     @Load
        rts

; A is the authored pose; X is the mover's word index and is preserved.
QCExitStoreActive:
        asl
        sta     a:qc_displacement
        phx
        txa
        asl
        asl
        clc
        adc     a:qc_displacement
        tax
        lda     f:QCExitPositionsQ4,x
        plx
        sta     a:.loword(qc_exit_active_q4),x
.ifdef PLAYABLE_E1M1_WALK_RESUME_BYTES
        jsl     MarkTraceResultCacheDirty
.endif
        rts

QCExitTouches:
.repeat 3, I
        lda     a:qc_exit_eye+I*2
        sec
        sbc     f:QCExitTouchBoxes+I*4,x
        cmp     f:QCExitTouchBoxes+I*4+2,x
        bcs     @Outside
.endrepeat
        sec
        rts
@Outside:
        clc
        rts

.include "quake/QuakeCE1M1Platforms.s"
.ifdef QC_SECRET_DOOR_COUNT
.include "quake/QuakeCSecretDoors.s"
.include "quake/QuakeCOrdinaryDoors.s"
.endif
.include "Data/QuakeBSPExitMovers.i"
