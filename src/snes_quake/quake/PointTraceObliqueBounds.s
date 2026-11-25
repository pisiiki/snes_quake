; The register traversal has sorted reverse-biased endpoints. Use the
; extreme over the whole original segment, which also bounds any split.
; Carry set and N=0/1 means proven Front/Back. The caller has saved the
; node and visit count and reloads its registers for either outcome.
ShotObliqueSafeSide:
.ifdef PLAYABLE_SHOT_HULL_INLINE_BOUNDS
        ; X is the inline point node. Zero has no conservative bounds row.
        lda     f:ShotHullData+6,x
        beq     @Unknown
        bpl     :+
        jml     ShotObliqueDiagonalSide
:
.else
        lda     z:w_plane
        bit     #7
        bne     @Unknown
        and     #$1ff8
        lsr
        lsr
        cmp     #PLAYABLE_SHOT_OBLIQUE_DIRECTORY_BYTES
        bcs     @Unknown
        tax
        lda     f:ShotObliqueDirectory,x
        beq     @Unknown
.endif
        tay                            ; Keep the directory entry across the lookup.
        and     #$003e
        tax
        lda     a:w_biased_from,x
        xba
        and     #$00f8
        lsr
        lsr
        sta     z:w_cache_coord_a
        tya
        and     #$ffc0
        ora     z:w_cache_coord_a
        tax
        tya
        lsr
        bcs     @CheckBack
        lda     w_biased_to_fast           ; Reverse-biased minimum signed X.
        cmp     f:ShotObliqueBounds,x
        bcs     @Unknown
        rep     #$80
        sec
        rtl
@CheckBack:
        lda     w_biased_from_fast         ; Maximum signed X in forward bias.
        eor     #$ffff
        cmp     f:ShotObliqueBounds,x
        bcs     @Unknown
        sep     #$80
        sec
        rtl
@Unknown:
        clc
        rtl

.ifdef PLAYABLE_SHOT_HULL_INLINE_BOUNDS
.pushseg
.segment "BSP_CPU_WALK_RUN"
; Positive equal coefficients reduce the XY plane to x+y or x-y against
; ceil(distance/coefficient). Fall back if either original delta would wrap,
; or if an intermediate or the interval straddle needs the exact divider.
ShotObliqueDiagonalSide:
        RW_assume a16i16
        tax
        lda     a:w_axial_span
        ora     a:w_axial_span+2
        bmi     @Unknown
        txa
        and     #$3fff
        sec
        sbc     #$2000
        sta     z:w_cache_coord_a
        txa
        bit     #$4000
        bne     @Difference
        lda     a:w_from
        clc
        adc     a:w_from+2
        bvs     @Unknown
        sec
        sbc     z:w_cache_coord_a
        bvs     @Unknown
        sta     z:w_cache_coord_b
        lda     a:w_to
        clc
        adc     a:w_to+2
        bra     @CheckEnd
@Difference:
        lda     a:w_from
        sec
        sbc     a:w_from+2
        bvs     @Unknown
        sec
        sbc     z:w_cache_coord_a
        bvs     @Unknown
        sta     z:w_cache_coord_b
        lda     a:w_to
        sec
        sbc     a:w_to+2
@CheckEnd:
        bvs     @Unknown
        sec
        sbc     z:w_cache_coord_a
        bvs     @Unknown
        eor     z:w_cache_coord_b
        bmi     @Unknown
        eor     z:w_cache_coord_b
        sec
        rtl
@Unknown:
        clc
        rtl
.popseg
.endif

.ifndef PLAYABLE_SHOT_HULL_INLINE_BOUNDS
ShotObliqueDirectory:
        .incbin "Data/PlayableShotObliqueBounds.bin", 0, PLAYABLE_SHOT_OBLIQUE_DIRECTORY_BYTES
.endif
ShotObliqueBounds:
        .incbin "Data/PlayableShotObliqueBounds.bin", PLAYABLE_SHOT_OBLIQUE_DIRECTORY_BYTES
        .assert *-ShotObliqueBounds = PLAYABLE_SHOT_OBLIQUE_BYTES - PLAYABLE_SHOT_OBLIQUE_DIRECTORY_BYTES, error, "Point oblique bound layout changed"
