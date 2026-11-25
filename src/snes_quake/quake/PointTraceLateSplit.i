.macro POINT_TRACE_LATE_NEAR child
.ifdef POINT_SHOT
        ; A is the numerator. If 2*n >= d and hi < 1/2,
        ; the near child is the only child the interval can reach.
        ldy     z:w_hi
        cpy     #(WALK_T_ONE/2)
        bcs     :+++
        asl
        bcs     :+
        cmp     z:w_denominator
.ifdef PLAYABLE_E1M1_TRACE_LAYOUT
        bcs     :+
        ; Likewise, 4*n >= d places the split beyond any hi under 1/4.
        cpy     #(WALK_T_ONE/4)
        bcs     :++
        asl
        bcs     :+
        cmp     z:w_denominator
        bcs     :+
        lsr                             ; Recover 2*n after a failed quarter test.
        bra     :++
.else
        bcc     :++
.endif
:       lda     f:WalkHullData+child,x
        jmp     @Child
:       lsr                             ; ASL had no carry, so recover n.
:
.endif
.endmacro

.macro POINT_TRACE_PACKED_BOUNDS near_child, far_child
.if .defined(POINT_SHOT) .and .defined(PLAYABLE_E1M1_TRACE_LAYOUT) .and .defined(PLAYABLE_MAP_ID)
        ; For hi below a quarter, the half proof is redundant. If the
        ; quarter proof fails, lo <= hi rules out both far-child proofs.
        ldy     z:w_hi
        cpy     #(WALK_T_ONE/4)
        bcs     :++
        asl
        bcs     :+
        asl
        bcs     :+
        cmp     z:w_denominator
        bcs     :+
        lsr
        lsr
        sta     z:w_numerator
        bra     :+++++
:       lda     f:WalkHullData+near_child,x
        jmp     @Child
:       cpy     #(WALK_T_ONE/2)
        bcs     :+
        asl
        bcs     :--
        cmp     z:w_denominator
        bcs     :--
        lsr
:       sta     z:w_numerator
        ; For lo >= 1/k and k*n < d, the Q12 midpoint is strictly below lo.
        ; Leave equality to the divider so it can update the entry plane.
        ldy     z:w_lo
        cpy     #(WALK_T_ONE/4)
        bcc     :++
        asl
        bcs     :++
        cpy     #(WALK_T_ONE/2)
        bcs     :+
        asl
        bcs     :++
:       cmp     z:w_denominator
        bcs     :+
        lda     f:WalkHullData+far_child,x
        jmp     @Child
:
.else
        POINT_TRACE_LATE_NEAR near_child
        sta     z:w_numerator
.endif
.endmacro

.macro POINT_TRACE_FINISH_PACKED prepared, classify
.if .defined(POINT_SHOT) .and .defined(PLAYABLE_E1M1_TRACE_LAYOUT)
        QC_YIELD_COORDINATE_STREAM
.endif
.if WALK_PACKED_POINT_CACHE
        ; Both packed endpoints are words. The exact key is sufficient on
        ; a hit, independently of which trace or plane filled the cache.
        jsr     WalkFractionSmallCached
        jmp     classify
.else
  .ifdef POINT_SHOT
        stz     z:w_denominator_high
        stz     z:w_numerator_high
  .endif
  .if WALK_CACHE_AXIAL_SPLIT
        sec
  .endif
        jmp     prepared
.endif
.endmacro

.macro POINT_TRACE_WORD_FRACTION word_size
        stz     z:w_fraction
.if WALK_CACHE_AXIAL_SPLIT
        ; Carry denotes a packed axial split with zero high words.
        bcc     :+
        lda     z:w_numerator
        cmp     z:w_denominator
        bcc     word_size
:
.endif
.endmacro
