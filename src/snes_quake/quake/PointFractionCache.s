.macro POINT_FRACTION_WORD operation, table
  .ifdef PLAYABLE_KNIGHT_POINT_FRACTIONS
        operation f:table,x
  .else
        operation a:table,x
  .endif
.endmacro

.macro POINT_FRACTION_VALUE operation, table
  .ifdef PLAYABLE_SPLIT_POINT_FRACTIONS
        operation f:table,x
  .else
        POINT_FRACTION_WORD operation, table
  .endif
.endmacro

; General callers already proved the small-divider bounds. Packed axial
; callers supply 0 <= numerator <= denominator with a nonzero word divisor.
WalkFractionSmallCached:
.if .defined(PLAYABLE_E1M1_TRACE_LAYOUT) .and .defined(PLAYABLE_MAP_ID)
        ; Only the low byte of the folded key reaches the slot mask.
        .assert POINT_FRACTION_CACHE_SLOTS <= 256, error, "Folded fraction key exceeds one byte"
        lda     z:w_numerator
        eor     z:w_numerator+1
        eor     z:w_denominator
.else
        lda     z:w_numerator
        xba
        eor     z:w_denominator
        eor     z:w_numerator
.endif
        and     #(POINT_FRACTION_CACHE_SLOTS-1)
        asl
        tax
        POINT_FRACTION_WORD lda, point_fraction_denominators
        cmp     z:w_denominator
        bne     @Miss
        POINT_FRACTION_VALUE lda, point_fraction_numerators
        cmp     z:w_numerator
        bne     @Miss
        POINT_FRACTION_VALUE lda, point_fraction_quotients
.if .defined(PLAYABLE_E1M1_TRACE_LAYOUT) .and .defined(PLAYABLE_MAP_ID)
@Return:
        ldx     #0
        bit     #$ffff                ; Restore Z for the nonnegative Q12 result.
        clc
        rts
.else
        sta     z:w_fraction
        bra     @Return
.endif
@Miss:
.if WALK_PACKED_POINT_CACHE
        ; Only the ordinary narrow divider publishes cache entries. Classify
        ; a new packed key once its exact lookup misses.
        lda     z:w_numerator
        beq     @Zero
        cmp     z:w_denominator
        bcs     @One
        lda     z:w_denominator
        cmp     #256
        bcc     @Byte
  .ifdef WALK_TRACE_FOOT_FRACTION
        cmp     #36*8
        beq     @Foot
  .endif
        cmp     #$8001
        bcs     @Wide
.endif
        phx
.if .defined(PLAYABLE_E1M1_TRACE_LAYOUT) .and .defined(PLAYABLE_MAP_ID)
        ; For d = 256*D, Q12 is floor((n*16)/D). Keep both cache keys intact.
        lda     z:w_denominator
        and     #$00ff
        bne     @Software
        lda     z:w_numerator
        cmp     #$1000
        bcs     @Software
        jsl     PointFractionAlignedDivide
        bra     @Publish
@Software:
  .if WALK_PACKED_POINT_CACHE
        stz     z:w_fraction
  .endif
.endif
        lda     z:w_numerator
        WALK_FRACTION_SMALL_DIGITS @SmallDigit
@Publish:
        plx
        lda     z:w_denominator
        POINT_FRACTION_WORD sta, point_fraction_denominators
        lda     z:w_numerator
        POINT_FRACTION_VALUE sta, point_fraction_numerators
        lda     z:w_fraction
        POINT_FRACTION_VALUE sta, point_fraction_quotients
.if .defined(PLAYABLE_E1M1_TRACE_LAYOUT) .and .defined(PLAYABLE_MAP_ID)
        bra     @Return
.else
@Return:
        ldx     #0
        lda     z:w_fraction
        clc
        rts
.endif

.if WALK_PACKED_POINT_CACHE
@Zero:
        rts
@One:
        lda     #WALK_T_ONE
        rts
@Byte:
        stz     z:w_fraction
        jmp     WalkFractionByte
  .ifdef WALK_TRACE_FOOT_FRACTION
@Foot:
        lda     z:w_numerator
        asl
        tax
        lda     f:::ShotHullData+WALK_TRACE_FOOT_FRACTION,x
        rts
  .endif
@Wide:
        stz     z:w_denominator_high
        stz     z:w_numerator_high
        sec
        jmp     WalkFractionWithWidth
.endif

.if .defined(PLAYABLE_E1M1_TRACE_LAYOUT) .and .defined(PLAYABLE_MAP_ID)
.pushseg
.segment "BSP_CPU_POINT_ALIGNED_DIVIDE"
PointFractionAlignedDivide:
        RW_assume a16i16
@Retry:
        lda     f:video_tick
        sta     z:w_mul_nmi
        lda     z:w_numerator
        .repeat 4
        asl
        .endrepeat
        WALK_DIVIDE_WORD_BY_BYTE w_denominator+1
        sta     z:w_fraction
        ; NMI may use the same arithmetic registers as the existing divider.
        lda     f:video_tick
        cmp     z:w_mul_nmi
        bne     @Retry
        rtl
.assert * - PointFractionAlignedDivide <= 48, error, "Aligned point divide exceeds its CPU tail"
.popseg
.endif

.delmacro POINT_FRACTION_WORD
