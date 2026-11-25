; X holds the node and Y holds the remaining visits. The packed threshold
; is already reverse-biased, so same-side nodes need no plane-table lookup.
.if !.defined(POINT_SHOT)
.macro WALK_STATIC_AXIAL axis, front, back, split, check_owner
  .if check_owner
        bit     #6                    ; Entrance owner needs live translation.
        bne     @SpillNode
  .endif
        lda     f:WalkHullData+6,x
  .if WALK_POINT_AXES .and ((axis = 0) .or (axis = 2))
        cmp     w_biased_to_fast+axis      ; Unsigned maximum endpoint.
        bcs     front
        cmp     w_biased_from_fast+axis    ; Unsigned minimum endpoint.
        bcc     back
  .else
        cmp     w_biased_from_fast+axis    ; Unsigned minimum endpoint.
        bcc     back
        cmp     w_biased_to_fast+axis      ; Unsigned maximum endpoint.
        bcs     front
  .endif
        sty     z:w_limit
        ldy     #axis
  .if .defined(WALK_TRACE_MOVER_TAIL_GUARD) .and (axis = 4)
        jmp     split                 ; The Q3 mover dispatch widens the Z path.
  .else
        bra     split
  .endif
.endmacro
.endif

        ldx     #4
@Bias:
.if WALK_REGISTER_TRACE
        ; Sort once per sweep. A split still uses the original endpoints.
        lda     a:w_from,x
        eor     #$7fff
        sta     a:w_biased_from,x
  .ifdef PLAYABLE_E1M1_TRACE_LAYOUT
        sta     z:w_biased_from_dp,x
  .endif
        lda     a:w_to,x
        eor     #$7fff
        cmp     a:w_biased_from,x
        bcs     :+
        ldy     a:w_biased_from,x
        sta     a:w_biased_from,x
  .ifdef PLAYABLE_E1M1_TRACE_LAYOUT
        sta     z:w_biased_from_dp,x
  .endif
        tya
:       sta     a:w_biased_to,x
  .ifdef PLAYABLE_E1M1_TRACE_LAYOUT
        sta     z:w_biased_to_dp,x
    .if WALK_CACHE_AXIAL_SPLIT
        ; The sort carry is set when the start is the lower biased endpoint.
        ror     a:w_axial_front,x
    .endif
  .endif
.if WALK_CACHE_AXIAL_SPLIT .or (.defined(WALK_TRACE_EXIT_GUARD) .and WALK_TRACE_OBLIQUE_BOUND)
        ; Reverse bias preserves the unsigned gap between signed endpoints.
        sec
        sbc     w_biased_from_fast,x
  .if WALK_CACHE_AXIAL_SPLIT
        sta     a:w_axial_span,x
  .endif
.endif
.if .defined(WALK_TRACE_EXIT_GUARD) .and WALK_TRACE_OBLIQUE_BOUND
        cmp     z:w_oblique_negative_bound
        bcc     @BiasNext
        sta     z:w_oblique_negative_bound
@BiasNext:
.endif
.else
        lda     a:w_from,x
        eor     #$8000
        sta     a:w_biased_from,x
        lda     a:w_to,x
        eor     #$8000
        sta     a:w_biased_to,x
.endif
        dex
        dex
        bpl     @Bias
.if .defined(WALK_TRACE_EXIT_GUARD) .and WALK_TRACE_OBLIQUE_BOUND
        lda     z:w_oblique_negative_bound
        cmp     #$5553                 ; 3*M+7 fits a word through $5552.
        bcs     @DisableObliqueBound    ; Also excludes signed delta wrapping.
        asl
        clc
        adc     z:w_oblique_negative_bound
        adc     #7                     ; First sum has no carry by the guard.
        .repeat 3
        lsr
        .endrepeat
        sta     z:w_oblique_front_bound
        eor     #$ffff                 ; Negative biased threshold for CMP.
        clc
        adc     #$8001
        bra     @SaveObliqueBound
@DisableObliqueBound:
        lda     #$8000                 ; Neither comparison can qualify.
        sta     z:w_oblique_front_bound
        lda     #0
@SaveObliqueBound:
        sta     z:w_oblique_negative_bound
.endif
