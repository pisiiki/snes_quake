; E1M3 collision uses continuous Q4 translation. Render variants sample the
; same animation at four points, independent of physical rider movement.
QCE1M3InitMovers:
        ldx     #QC_EXIT_MOVER_COUNT*2-2
@Initialize:
        lda     f:QCE1M3MoverOffsetIndex,x
        tay
        phx
        tyx
        lda     f:QCE1M3MoverOffsetQ4,x
        plx
        sta     a:qc_e1m3_mover_offsets,x
        lda     f:QCE1M3MoverSecondaryIndex,x
        bmi     :+
        phx
        tax
        lda     f:QCE1M3MoverOffsetQ4,x
        plx
        sta     a:qc_e1m3_mover_offsets+QC_EXIT_MOVER_COUNT*2,x
:
        dex
        dex
        bpl     @Initialize
        rts

; X is the mover word index. A is Q6 time since its activation.
; Carry is set if a rider would be pushed into solid geometry.
QCE1M3UpdateMover:
        sta     a:qc_e1m3_move_age
        lda     f:QCE1M3MoverReturnAt,x
        beq     @Clamp
        cmp     a:qc_e1m3_move_age
        bcs     @Clamp
        clc
        adc     f:QCE1M3MoverDuration,x
        sec
        sbc     a:qc_e1m3_move_age
        bpl     @UseAge
        lda     #0
@UseAge:
        sta     a:qc_e1m3_move_age
@Clamp:
        lda     a:qc_e1m3_move_age
        cmp     f:QCE1M3MoverDuration,x
        bcc     :+
        lda     f:QCE1M3MoverDuration,x
:       sta     a:qc_e1m3_move_age
        asl
        clc
        adc     f:QCE1M3MoverOffsetIndex,x
        stx     a:qc_e1m3_move_slot
        tax
        lda     f:QCE1M3MoverOffsetQ4,x
        sta     a:qc_e1m3_move_next
        ldx     a:qc_e1m3_move_slot
        sec
        sbc     a:qc_e1m3_mover_offsets,x
        beq     @Ready
        sta     a:qc_e1m3_move_delta
        lda     f:QCE1M3RiderFloor,x
        beq     @Commit
        jsr     QCE1M3Carry
        ldx     a:qc_e1m3_move_slot
        bcs     @Blocked
@Commit:
        lda     a:qc_e1m3_move_next
        sta     a:qc_e1m3_mover_offsets,x
        inc     a:qc_exit_updated
@Ready:
        lda     f:QCE1M3MoverSecondaryIndex,x
        bmi     @Age
        phx
        clc
        adc     a:qc_e1m3_move_age
        adc     a:qc_e1m3_move_age
        tax
        lda     f:QCE1M3MoverOffsetQ4,x
        plx
        cmp     a:qc_e1m3_mover_offsets+QC_EXIT_MOVER_COUNT*2,x
        beq     @Age
        sta     a:qc_e1m3_mover_offsets+QC_EXIT_MOVER_COUNT*2,x
        inc     a:qc_exit_updated
@Age:
        lda     a:qc_e1m3_move_age
        clc
@Blocked:
        rts

QCE1M3Carry:
        lda     a:w_grounded
        beq     @Outside
        lda     a:qce+QC_ENTITY_STRIDE+QC_FIELD_HEALTH
        beq     @Outside
        bmi     @Outside
        ; Shotgun point traces share the walk scratch in Q3. Reload the
        ; actual Q4 pose before testing standing support or carrying it.
        phx
        ldx     #4
        lda     a:w_pending
        beq     @ReadCamera
@ReadPending:
        lda     a:w_pending_xyz,x
        sta     a:w_from,x
        dex
        dex
        bpl     @ReadPending
        bra     @Bounds
@ReadCamera:
        lda     f:camera_x,x
        sta     a:w_from,x
        dex
        dex
        bpl     @ReadCamera
@Bounds:
        plx
        lda     a:w_from
        eor     #$8000
        cmp     f:QCE1M3RiderMinX,x
        bcc     @Outside
        cmp     f:QCE1M3RiderMaxX,x
        bcs     @Outside
        lda     a:w_from+2
        eor     #$8000
        cmp     f:QCE1M3RiderMinY,x
        bcc     @Outside
        cmp     f:QCE1M3RiderMaxY,x
        bcc     @Probe
@Outside:
        clc
        rts
@Probe:
        jsr     QCE1M3InvalidateImpacts
        lda     #.loword(-5)
        jsr     WalkTraceVertical
        bcc     @Outside
        lda     a:w_enter
        sta     z:w_plane
        and     #$e004
        cmp     #$a004
        bne     @Outside
        WALK_LOAD_PLANE_OFFSET WALK_TRACE_EXTENDED_PLANES
        lda     f:WalkHullData+WALK_TRACE_PLANES,x
        dec
        asl
        cmp     a:qc_e1m3_move_slot
        bne     @Outside
        ; Sweep against the lower of the two platform positions.
        lda     a:qc_e1m3_move_delta
        bpl     @Sweep
        ldx     a:qc_e1m3_move_slot
        lda     a:qc_e1m3_move_next
        sta     a:qc_e1m3_mover_offsets,x
        jsr     QCE1M3InvalidateImpacts
@Sweep:
        lda     a:qc_e1m3_move_delta
        jsr     WalkTraceVertical
        bcc     @Publish
        lda     a:qc_e1m3_move_delta
        bpl     @Blocked
        ldx     a:qc_e1m3_move_slot
        lda     a:qc_e1m3_move_next
        sec
        sbc     a:qc_e1m3_move_delta
        sta     a:qc_e1m3_mover_offsets,x
        jsr     QCE1M3InvalidateImpacts
@Blocked:
        sec
        rts
@Publish:
        stz     a:w_pending
        ldx     #4
@Axis:
        lda     a:w_to,x
        sta     a:w_from,x
        sta     a:w_pending_xyz,x
        dex
        dex
        bpl     @Axis
        lda     #1
        sta     a:w_pending
        clc
        rts

QCE1M3InvalidateImpacts:
.ifdef WALK_IMPACT_CACHE_BYTES
.repeat WALK_IMPACT_CACHE_BYTES / WALK_IMPACT_CACHE_STRIDE, slot
        stz     a:w_impact_cache+slot*WALK_IMPACT_CACHE_STRIDE+26
.endrepeat
.endif
        rts

; Stock targeted plat starts raised. Either t82 trigger sends it down once.
; The generated platform trigger raises it again from the bottom.
QCE1M3PlatformTick:
        lda     a:qc_e1m3_platform_phase
        bne     @Running
        lda     a:qce+QC_ENTITY_STRIDE+QC_FIELD_HEALTH
        beq     :+
        bpl     :++
:       rts
:
        ldx     #(QCE1M3PlatformUseAbove-QCE1M2GroupBounds)
        jsr     QCE1M2Touches
        bcs     :+
        ldx     #(QCE1M3PlatformUseBelow-QCE1M2GroupBounds)
        jsr     QCE1M2Touches
        bcs     :+
        rts
:       lda     a:qc_e1m2_group_bit
        tsb     a:.loword(quakec_exit_targets)
        inc     a:qc_e1m3_platform_phase
        bra     @Down
@Running:
        cmp     #1
        beq     @Down
        cmp     #3
        beq     @Up
        bcc     @Bottom
        dec     a:qc_e1m3_platform_wait
        bne     @Done
        lda     #1
        sta     a:qc_e1m3_platform_phase
@Down:
        lda     a:qc_e1m3_platform_age
        inc
        sta     a:qc_e1m3_platform_age
        cmp     f:QCE1M3MoverDuration+QC_E1M3_PLATFORM*2
        bcc     @Move
        inc     a:qc_e1m3_platform_phase
        bra     @Move
@Bottom:
        lda     a:qce+QC_ENTITY_STRIDE+QC_FIELD_HEALTH
        beq     @Done
        bmi     @Done
        ldx     #(QCE1M3PlatformCenterTouch-QCE1M2GroupBounds)
        jsr     QCE1M2Touches
        bcc     @Done
        inc     a:qc_e1m3_platform_phase
@Up:
        lda     a:qc_e1m3_platform_age
        dec
        sta     a:qc_e1m3_platform_age
        bne     @Move
        inc     a:qc_e1m3_platform_phase
        ldy     #3*64
        sty     a:qc_e1m3_platform_wait
@Move:
        ldx     #QC_E1M3_PLATFORM*2
        jsr     QCE1M3UpdateMover
        bcs     @Done
        ldy     #0
        QC_AXIAL_MOVER_POSE
        tya
        cmp     a:qc_exit_poses,x
        beq     @Done
        sta     a:qc_exit_poses,x
        inc     a:qc_exit_updated
@Done:
        rts
