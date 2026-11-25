; Authored touch groups advance in the same Q6 time as stock pushers.
.macro QC_AXIAL_MOVER_POSE
        cmp     f:QCE1M2MoverThreshold1,x
        bcc     :+
        iny
        cmp     f:QCE1M2MoverThreshold2,x
        bcc     :+
        iny
        cmp     f:QCE1M2MoverThreshold3,x
        bcc     :+
        iny
:
.endmacro

.ifdef QC_E1M2_SNAPSHOT_EYE
.pushseg
.segment "CODE"
QCE1M2SampleEye:
.else
QuakeCE1M2Tick:
.endif
        ldx     #4
        lda     f:walk_pending
        beq     @Camera
@Pending:
        lda     f:WalkPendingXYZ,x
        sta     a:qc_exit_eye,x
        dex
        dex
        bpl     @Pending
.ifdef QC_E1M2_SNAPSHOT_EYE
        rtl
.else
        bra     @Key
.endif
@Camera:
        lda     f:camera_x,x
        sta     a:qc_exit_eye,x
        dex
        dex
        bpl     @Camera
.ifdef QC_E1M2_SNAPSHOT_EYE
        rtl
.popseg
QuakeCE1M2Tick:
.endif
@Key:
        lda     f:quakec_e1m2_key
        bne     @Groups
        lda     a:qce+QC_ENTITY_STRIDE+QC_FIELD_HEALTH
        beq     @Groups
        bmi     @Groups
        ldx     #(QCE1M2KeyBounds-QCE1M2GroupBounds)
        jsr     QCE1M2Touches
        bcc     @Groups
        inc     a:.loword(quakec_e1m2_key)
@Groups:
        stz     a:qc_exit_updated
        lda     #1
        sta     a:qc_e1m2_group_bit
        ldx     #0
@Group:
        stx     a:qc_e1m2_group_index
        lda     f:QCE1M2GroupWait,x
        bpl     @CheckTouch
        lda     a:.loword(quakec_exit_targets)
        bit     a:qc_e1m2_group_bit
        bne     @TargetActive
@CheckTouch:
        lda     a:qce+QC_ENTITY_STRIDE+QC_FIELD_HEALTH
        beq     @Advance
        bmi     @Advance
        cpx     #QC_E1M2_SILVER_GROUP*2
        bne     @Bounds
        lda     f:quakec_e1m2_key
        cmp     #1
        bne     @Advance
@Bounds:
.ifdef QC_E1M3_GOLD_KEY
        cpx     #QC_E1M3_SHOT_GROUP*2
        bne     :+
        lda     a:qc_e1m3_stair_button_hit
        beq     @Advance
        bra     @Trigger
:
.endif
        lda     f:QCE1M2GroupBoundsOffsets,x
        tax
        jsr     QCE1M2Touches
        ldx     a:qc_e1m2_group_index
        bcc     @Advance
.ifdef QC_E1M3_GOLD_KEY
@Trigger:
.endif
        lda     a:.loword(quakec_exit_targets)
        ora     a:qc_e1m2_group_bit
        sta     a:.loword(quakec_exit_targets)
        lda     f:QCE1M2GroupWait,x
        sta     a:.loword(qc_e1m2_group_wait),x
        cpx     #QC_E1M2_SILVER_GROUP*2
        bne     @Advance
        inc     a:.loword(quakec_e1m2_key)
@Advance:
        lda     a:.loword(quakec_exit_targets)
        bit     a:qc_e1m2_group_bit
        beq     @Close
@TargetActive:
        lda     a:.loword(qc_e1m2_group_age),x
        cmp     f:QCE1M2GroupDuration,x
        bcc     @Open
        lda     a:.loword(qc_e1m2_group_wait),x
        beq     @Next
        bmi     @Next
        dec     a:.loword(qc_e1m2_group_wait),x
        bne     @Next
        lda     a:qc_e1m2_group_bit
        trb     a:.loword(quakec_exit_targets)
        bra     @Next
@Open:
        inc     a:.loword(qc_e1m2_group_age),x
        bra     @Update
@Close:
        lda     a:.loword(qc_e1m2_group_age),x
        beq     @Next
        dec     a:.loword(qc_e1m2_group_age),x
@Update:
        lda     a:.loword(qc_e1m2_group_age),x
        sta     a:qc_exit_age
        lda     f:QCE1M2GroupFirst,x
        clc
        adc     f:QCE1M2GroupCount,x
        asl
        sta     a:qc_e1m2_mover_end
        lda     f:QCE1M2GroupFirst,x
        asl
        tax
@Mover:
        ldy     #0
        lda     a:qc_exit_age
        sec
        sbc     f:QCE1M2MoverDelay,x
        bcc     @Store
.ifdef QC_E1M3_GOLD_KEY
        jsr     QCE1M3UpdateMover
        bcs     @NextMover
        ldy     #0
.endif
        QC_AXIAL_MOVER_POSE
@Store:
        tya
        cmp     a:qc_exit_poses,x
        beq     @NextMover
        sta     a:qc_exit_poses,x
.ifdef QC_E1M2_TRANSLATION_CACHE
        jsr     QCE1M2StoreMoverOffset
.endif
        inc     a:qc_exit_updated
@NextMover:
        inx
        inx
        cpx     a:qc_e1m2_mover_end
        bcc     @Mover
@Next:
        asl     a:qc_e1m2_group_bit
        ldx     a:qc_e1m2_group_index
        inx
        inx
        cpx     #QC_E1M2_GROUP_COUNT*2
        bcs     :+
        jmp     @Group
:
.ifdef QC_E1M3_GOLD_KEY
        jsr     QCE1M3PlatformTick
.endif
        lda     a:qc_exit_updated
        beq     @Done
.ifdef PLAYABLE_POINT_SIGHT_CACHE
        jsr     ShotHull::WalkSightCacheInvalidate
.endif
        stz     a:w_support_valid
.ifdef WALK_IMPACT_CACHE_BYTES
.repeat WALK_IMPACT_CACHE_BYTES / WALK_IMPACT_CACHE_STRIDE, slot
        stz     a:w_impact_cache+slot*WALK_IMPACT_CACHE_STRIDE+26
.endrepeat
.endif
.repeat 2, part
        lda     #0
.repeat 8, I
        asl
        asl
  .ifdef QC_E1M3_GOLD_KEY
        ora     a:qc_exit_poses+.ident(.sprintf("QC_E1M3_PACKED_MOVER_%d", part*8+7-I))*2
  .else
        ora     a:qc_exit_poses+(part*8+7-I)*2
  .endif
.endrepeat
        sta     a:.loword(quakec_exit_pose_word)+part*2
.endrepeat
@Done:  rts

.ifdef QC_E1M2_TRANSLATION_CACHE
; X is the mover word index and Y its sampled pose. Keep both
; quantizations exactly as authored, including nonzero pose-zero offsets.
QCE1M2StoreMoverOffset:
        phy
        tya
        asl
        sta     z:qc_tmp
        txa
        txy
        asl
        asl
        ora     z:qc_tmp
        tax
        lda     f:QCE1M2MoverPositionsQ4,x
        sta     a:qc_e1m2_mover_q4,y
        lda     f:QCE1M2MoverPositionsQ3,x
        sta     a:qc_e1m2_mover_q3,y
  .ifdef QC_E1M2_Q4_BYTES
        jsr     QCE1M2StoreMoverThresholds
  .endif
        tyx
        ply
        rts
.endif

.ifdef QC_E1M2_Q4_BYTES
.pushseg
.segment "BSP_QUAKEC_BYTECODE"
QCE1M2MoverWalkPlanes:
        .incbin "Data/PlayableE1M2MoverWalk.bin"
        .assert * - QCE1M2MoverWalkPlanes = QC_EXIT_MOVER_COUNT * 8, error, "Invalid E1M2 walk plane table size"
QCE1M2MoverShotPlanes:
        .incbin "Data/PlayableE1M2MoverShot.bin"
        .assert * - QCE1M2MoverShotPlanes = QC_EXIT_MOVER_COUNT * 8, error, "Invalid E1M2 shot plane table size"
.popseg

; Each hull contributes two cache indices and two base thresholds per mover.
.macro QC_CACHE_MOVER_PLANES source, delta, dest
        lda     a:delta,y
        sta     z:qc_tmp
  .repeat 2, plane
        lda     f:source+plane*4,x
        tay
        lda     f:source+plane*4+2,x
        clc
        adc     z:qc_tmp
        sta     a:dest,y
  .endrepeat
.endmacro

QCE1M2StoreMoverThresholds:
        phy
        tya
        asl
        asl
        tax
        QC_CACHE_MOVER_PLANES QCE1M2MoverWalkPlanes, qc_e1m2_mover_q4, qc_e1m2_threshold_q4
        ply
        phy
        QC_CACHE_MOVER_PLANES QCE1M2MoverShotPlanes, qc_e1m2_mover_q3, qc_e1m2_threshold_q3
        ply
        rts
.endif

QCE1M2Touches:
.repeat 3, I
        lda     a:qc_exit_eye+I*2
        eor     #$8000
        cmp     f:QCE1M2GroupBounds+I*4,x
        bcc     @Outside
        cmp     f:QCE1M2GroupBounds+I*4+2,x
        bcc     :+
        bne     @Outside
:
.endrepeat
        sec
        rts
@Outside:
        clc
        rts

.include "Data/QuakeBSPE1M2Machinery.i"
.assert QCE1M2GroupWait-QCE1M2GroupBounds = QC_E1M2_GROUP_COUNT*12, error, "E1M2 touch-box stride changed"
QCE1M2GroupBoundsOffsets:
.repeat QC_E1M2_GROUP_COUNT, group
        .word   group*12
.endrepeat
