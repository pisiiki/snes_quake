; The packed node names a reverse-biased exact threshold for this live pose.
; Preserve the node in X. Only a split needs the full original plane state.
.pushseg
.segment "BSP_CPU_WALK_RUN"
.macro SHOT_MOVING_RANK_SIDE axis
        and     #$00ff
  .if !.defined(PLAYABLE_MAP_ID) .or (axis = 0)
        sty     z:w_limit
  .endif
        tay
        lda     a:point_moving_ranks,y
        cmp     w_biased_to_fast+axis
        bcs     @MovingRankFastFront
        cmp     w_biased_from_fast+axis
        bcc     @MovingRankFastBack
  .ifdef PLAYABLE_MAP_ID
        ldy     #axis
  .endif
  .if axis <> 4
        bra     @MovingRankFastSplit
  .endif
.endmacro
@MovingRankFast:
        cmp     #$c200
        bcc     @MovingRankX
.ifdef PLAYABLE_MAP_ID
        ; Share the visit-budget save for Y and Z in the packed dispatcher.
        sty     z:w_limit
.endif
        cmp     #$c300
        bcs     @MovingRankZ
        SHOT_MOVING_RANK_SIDE 2
@MovingRankX:
        ; The unranked sentinel shares the lower tag range with ranked X.
        cmp     #$c000
        beq     @MovingRankFallbackLong
        SHOT_MOVING_RANK_SIDE 0
@MovingRankZ:
  .ifdef WALK_TRACE_MOVER_TAIL_GUARD
        cmp     #WALK_TRACE_MOVER_TAIL_GUARD
        bne     :+
        jmp     @CertifiedMoverTail
:
  .endif
        SHOT_MOVING_RANK_SIDE 4
@MovingRankFastSplit:
.ifdef PLAYABLE_MAP_ID
        jml     @MovingRankSplit
.else
        ldy     z:w_limit
.endif
@MovingRankFallbackLong:
        jml     @MovingRankFallback
@MovingRankFastFront:
        ldy     z:w_limit
        jml     @FastFront
@MovingRankFastBack:
        ldy     z:w_limit
        jml     @FastBack
.ifdef PLAYABLE_MAP_ID
.segment "BSP_CPU_POINT_RANKED_SPLIT"
@MovingRankSplit:
        ; The rank has already proved the translated threshold crosses the ray.
        ; Y holds the packed rank's axis. Retain the original impact reference.
        sta     z:w_d0
        stx     z:w_node
        lda     f:WalkHullData+6,x
        sta     z:w_plane
        jml     @PackedAxialSplit
.assert * - @MovingRankSplit <= 32, error, "Ranked point split exceeds its bank-local tail"
.endif
.delmacro SHOT_MOVING_RANK_SIDE
.popseg
