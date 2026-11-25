.ifdef QC_E1M2_TRANSLATION_CACHE
; E1M2 mover planes are axial. Use the original reference kept in the
; packed node to load the translated threshold directly.
WalkLoadE1M2MovingAxial:
        jsr     WalkE1M2MovingThreshold
        bvs     WalkE1M2MovingDistanceWide
        bra     WalkE1M2StoreMovingDistance

; The playable cache stores proved signed thresholds. The standalone
; path adds the cached delta on demand, with a wide fallback on overflow.
WalkE1M2MovingThreshold:
        .assert .loword(w_plane) <= $FD, lderror, "Plane tag load crosses direct page"
        lda     z:w_plane+1
        and     #$00e0
.ifdef WALK_TRACE_EXIT_GUARD
        tax
        lda     f:::WalkAxesByTag,x
.else
        lsr
        lsr
        lsr
        lsr
        tax
        lda     f:WalkAxisA,x
.endif
        stx     z:w_tag
        sta     z:w_axis_a
.ifdef QC_E1M2_Q4_BYTES
        tay
        lda     z:w_plane
        and     #WALK_PLANE_OFFSET
        lsr
        lsr
        tax
  .ifdef POINT_SHOT
        lda     a:qc_e1m2_threshold_q3-QC_E1M2_Q3_FIRST,x
  .else
        lda     a:qc_e1m2_threshold_q4-QC_E1M2_Q4_FIRST,x
  .endif
        clv
.else
        WALK_LOAD_PLANE_OFFSET WALK_TRACE_EXTENDED_PLANES
        lda     f:WalkHullData+WALK_TRACE_PLANES,x
        dec
        asl
        tay
.ifdef POINT_SHOT
        lda     a:qc_e1m2_mover_q3,y
.else
        lda     a:qc_e1m2_mover_q4,y
.endif
        ldy     z:w_axis_a
        clc
        adc     f:WalkHullData+WALK_TRACE_PLANES+4,x
.endif
        rts

WalkE1M2MovingDistanceWide:
        WALK_LOAD_PLANE_DISTANCE
        jmp     WalkE1M2AxialDistance

WalkE1M2StoreMovingDistance:
        sta     z:w_dist
        ldx     #0
        cmp     #$8000
        bcc     :+
        dex
:       stx     z:w_dist_high
        rts

; Pairs on the same side can follow the child without two full distances.
; Carry clear leaves the translated plane ready for the exact split path.
WalkE1M2MovingSide:
        jsr     WalkE1M2MovingThreshold
        bvs     @Wide
        sta     z:w_dist
.if WALK_REGISTER_TRACE
        eor     #$7fff
        cmp     a:w_biased_from,y
        bcc     @Back
        cmp     a:w_biased_to,y
        bcc     @Split
.else
        eor     #$8000
        beq     @Front
        dec                            ; An endpoint on the plane is front.
        cmp     a:w_biased_from,y
        bcs     @BehindFrom
        cmp     a:w_biased_to,y
        bcs     @Split
.endif
@Front:
        lda     #0
        sec
        rts
.if !WALK_REGISTER_TRACE
@BehindFrom:
        cmp     a:w_biased_to,y
        bcc     @Split
.endif
@Back:
        lda     #1
        sec
        rts
@Split:
        lda     z:w_dist
        jsr     WalkE1M2StoreMovingDistance
        clc
        rts
@Wide:
        jsr     WalkE1M2MovingDistanceWide
        clc
        rts
.endif

; X is the plane byte offset. Its first word names the mover, one based.
WalkE1M2AxialDistance:
.ifdef QC_E1M3_GOLD_KEY
        lda     z:w_tag
        cmp     #3*WALK_TAG_STEP
        bcc     WalkE1M3BevelDistance
.endif
        lda     f:WalkHullData+WALK_TRACE_PLANES,x
        dec
        asl
.ifdef QC_E1M3_GOLD_KEY
        tax
        lda     a:qc_e1m3_mover_offsets,x
  .ifdef POINT_SHOT
        cmp     #$8000
        ror
  .endif
.else
        tax
.ifdef POINT_SHOT
        lda     a:qc_e1m2_mover_q3,x
.else
        lda     a:qc_e1m2_mover_q4,x
.endif
.endif
        ldx     #0
        cmp     #$8000
        bcc     :+
        dex
:       clc
        adc     z:w_dist
        sta     z:w_dist
        txa
        adc     z:w_dist_high
        sta     z:w_dist_high
        rts

.ifdef QC_E1M3_GOLD_KEY
WalkE1M3BevelDistance:
  .ifdef POINT_SHOT
        .define MOVING_BEVEL_PREFIX "SHOT"
        LOCAL_MOVING_BEVEL_COUNT = ::SHOT_MOVING_BEVEL_COUNT
  .else
        .define MOVING_BEVEL_PREFIX "WALK"
        LOCAL_MOVING_BEVEL_COUNT = WALK_MOVING_BEVEL_COUNT
  .endif
  .repeat LOCAL_MOVING_BEVEL_COUNT, index
        cpx     #::.ident(.sprintf("%s_MOVING_BEVEL_%d_OFFSET", MOVING_BEVEL_PREFIX, index))
        bne     :+
        lda     a:qc_e1m3_mover_offsets+2*::.ident(.sprintf("%s_MOVING_BEVEL_%d_MOVER", MOVING_BEVEL_PREFIX, index))
    .ifdef POINT_SHOT
        cmp     #$8000
        ror
    .endif
        ldx     #.loword(::.ident(.sprintf("%s_MOVING_BEVEL_%d_COEFFICIENT", MOVING_BEVEL_PREFIX, index)))
        jsr     WalkMultiply
        clc
        lda     z:w_mul_low
        adc     z:w_dist
        sta     z:w_dist
        lda     z:w_mul_high
        adc     z:w_dist_high
        sta     z:w_dist_high
        rts
:
  .endrepeat
        rts
  .undefine MOVING_BEVEL_PREFIX
.endif
