; Basic levels use tag6 for a full normal; authored movers are static.
WalkLoadThreeAxisPlane:
        lda     #6 * WALK_TAG_STEP
        sta     z:w_tag
        stz     z:w_axis_a
        lda     #2
        sta     z:w_axis_b
        WALK_LOAD_PLANE_OFFSET WALK_TRACE_EXTENDED_PLANES
        lda     f:WalkHullData+WALK_TRACE_PLANES,x
        sta     z:w_coeff_a
        lda     f:WalkHullData+WALK_TRACE_PLANES+2,x
        sta     z:w_coeff_b
        lda     f:WalkHullData+WALK_TRACE_PLANES+4,x
        sta     z:w_dist
        lda     f:WalkHullData+WALK_TRACE_PLANES+6,x
        sta     z:w_dist_high
        txa
        lsr
        lsr
        tax
.if .defined(PLAYABLE_WALK_HULL_SPLIT_THIRD) .and !.defined(POINT_SHOT)
        lda     f:WalkHullThirdData,x
.else
        lda     f:WalkHullData+WALK_TRACE_THIRD,x
.endif
        sta     a:w_coeff_c
        rts

.ifndef PLAYABLE_WALK_THREE_AXIS_DELTA
WalkThreeAxisEndDistance = WalkThreeAxisDistance
.endif

; Direct exact dot product. Y chooses w_from(0) or w_to(6). It bypasses
; the legacy two-coordinate cache so a Z-only move cannot reuse stale data.
WalkThreeAxisDistance:
        sty     z:w_endpoint
.ifdef PLAYABLE_WALK_FOLD_XY
        ; Equal signed coefficients share one product as long as x +/- y
        ; fits its signed input word. Y still names the original endpoint.
        ldx     z:w_coeff_a
        cpx     z:w_coeff_b
        beq     @Sum
        txa
        eor     #$ffff
        inc
        cmp     z:w_coeff_b
        bne     @Unfolded
        lda     a:w_from,y
        sec
        sbc     a:w_from+2,y
        bvs     @Unfolded
        bra     @Folded
@Sum:
        lda     a:w_from,y
        clc
        adc     a:w_from+2,y
        bvs     @Unfolded
@Folded:
        jsr     WalkMultiply
        lda     z:w_mul_low
        sta     z:w_eval
        lda     z:w_mul_high
        sta     z:w_eval_high
        bra     @LastAxis
@Unfolded:
.endif
        lda     a:w_from,y
        ldx     z:w_coeff_a
        jsr     WalkMultiply
        lda     z:w_mul_low
        sta     z:w_eval
        lda     z:w_mul_high
        sta     z:w_eval_high
        lda     z:w_endpoint
        inc
        inc
        tay
        lda     a:w_from,y
        ldx     z:w_coeff_b
        jsr     WalkMultiply
        jsr     WalkAccumulateDistance
@LastAxis:
        lda     z:w_endpoint
        clc
        adc     #4
        tay
        lda     a:w_from,y
        ldx     a:w_coeff_c
        jsr     WalkMultiply
        jsr     WalkAccumulateDistance
        lda     z:w_eval
        sec
        sbc     z:w_dist
        sta     z:w_eval
        lda     z:w_eval_high
        sbc     z:w_dist_high
        sta     z:w_eval_high
        rts

.ifdef PLAYABLE_WALK_THREE_AXIS_DELTA
; Enter with d(start) in w_eval. Add each exact signed delta product.
; Overflow on any axis restarts the full evaluation and overwrites w_eval.
WalkThreeAxisEndDistance:
        lda     a:w_to
        sec
        sbc     a:w_from
        bvs     @Full
        beq     @Y
        ldx     z:w_coeff_a
        jsr     WalkMultiply
        jsr     WalkAccumulateDistance
@Y:
        lda     a:w_to+2
        sec
        sbc     a:w_from+2
        bvs     @Full
        beq     @Z
        ldx     z:w_coeff_b
        jsr     WalkMultiply
        jsr     WalkAccumulateDistance
@Z:
        lda     a:w_to+4
        sec
        sbc     a:w_from+4
        bvs     @Full
        beq     @Done
        ldx     a:w_coeff_c
        jsr     WalkMultiply
        jmp     WalkAccumulateDistance
@Done:
        rts
@Full:
        ldy     #6
        jmp     WalkThreeAxisDistance
.endif
