; A point split with a nonzero denominator high word can reuse an exact
; quotient. Both full operands must match before the division is bypassed.
POINT_WIDE_FRACTION_SLOTS = 64
.pushseg
.segment "PLAYABLE_STREAM_CACHE"
PointWideFractionDenHigh: .res 2 * POINT_WIDE_FRACTION_SLOTS
PointWideFractionDenLow:  .res 2 * POINT_WIDE_FRACTION_SLOTS
PointWideFractionNumHigh: .res 2 * POINT_WIDE_FRACTION_SLOTS
PointWideFractionNumLow:  .res 2 * POINT_WIDE_FRACTION_SLOTS
PointWideFractionValue:   .res 2 * POINT_WIDE_FRACTION_SLOTS
.assert PointWideFractionDenHigh = SpriteStreamWramData + SPRITE_WRAM_SLOTS * SPRITE_WRAM_SLOT_BYTES, lderror, "Wide fractions must follow sprite raster storage"
.assert * - PointWideFractionDenHigh <= SPRITE_WRAM_SLOT_BYTES, error, "Wide fractions exceed one sprite slot"
.assert .bankbyte(PointWideFractionDenHigh) = $7E && .bankbyte(*-1) = $7E, lderror, "Wide fractions must fit in bank $7E"

.segment "BSP_CPU_POINT_WIDE_CACHE"
; A is the nonzero denominator high word. Endpoint evaluation has finished,
; so the distance-cache index can hold this slot until the quotient returns.
PointWideFractionLookup:
        RW_assume a16i16
        eor     z:w_denominator
        eor     z:w_numerator_high
        eor     z:w_numerator
        and     #(POINT_WIDE_FRACTION_SLOTS-1)
        asl
        tax
        stx     z:w_cache_slot
        lda     f:PointWideFractionDenHigh,x
        cmp     z:w_denominator_high
        bne     @Miss
        lda     f:PointWideFractionDenLow,x
        cmp     z:w_denominator
        bne     @Miss
        lda     f:PointWideFractionNumHigh,x
        cmp     z:w_numerator_high
        bne     @Miss
        lda     f:PointWideFractionNumLow,x
        cmp     z:w_numerator
        bne     @Miss
        lda     f:PointWideFractionValue,x
        sta     z:w_fraction
        sec
        rtl
@Miss:
        lda     #0
        sta     f:PointWideFractionDenHigh,x
        lda     z:w_denominator
        sta     f:PointWideFractionDenLow,x
        lda     z:w_numerator_high
        sta     f:PointWideFractionNumHigh,x
        lda     z:w_numerator
        sta     f:PointWideFractionNumLow,x
        clc
        rtl

PointWideFractionPublish:
        RW_assume a16i16
        ldx     z:w_cache_slot
        sta     f:PointWideFractionValue,x
        lda     z:w_denominator_high
        sta     f:PointWideFractionDenHigh,x
        ldx     #0
        lda     z:w_fraction
        clc
        rtl

PointWideFractionInit:
        RW_assume a16i16
        pha
        phx
        lda     #0
        ldx     #2*(POINT_WIDE_FRACTION_SLOTS-1)
:       sta     f:PointWideFractionDenHigh,x
        dex
        dex
        bpl     :-
        plx
        pla
        rtl
.assert * - PointWideFractionLookup <= $80, error, "Wide fraction code exceeds the CPU tail"
.popseg
