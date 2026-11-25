; The two point-hull callers consume carry, the hit leaf and fraction,
; and the output position and normal. Actor clipping still runs afterward.
; World planes are immutable. Drop all entries if any translated hull moves.
WalkPointTraceCached:
.ifdef PLAYABLE_E1M1_WALK_RESUME_BYTES
        .include "quake/TraceResultCacheCheck.i"
.else
        .include "quake/TraceResultCacheValidate.i"
.endif
        ; Keep the four +/-128 Q3 foot offsets in distinct rows for a
        ; shared height. Compare all six endpoint words on every hit.
        lda     a:w_from+2
        lsr
        lsr
        clc
        adc     a:w_from
        eor     a:w_from+4
        eor     a:w_to+4
        and     #((POINT_TRACE_CACHE_BYTES / 32 - 1) * 8)
        asl
        asl
        tax
        lda     a:point_trace_cache,x
        beq     @Miss
.ifdef PLAYABLE_E1M1_WALK_RESUME_BYTES
        bmi     @Miss                  ; Q4 rows carry a separate type bit.
.endif
        .repeat 6, I
        lda     a:w_from+2*I
        cmp     a:point_trace_cache+2+2*I,x
        bne     @Miss
        .endrepeat
        .repeat 6, I
        lda     a:point_trace_cache+14+2*I,x
        sta     a:w_result+2*I
        .endrepeat
        lda     a:point_trace_cache+26,x
        sta     z:w_lo
        lda     a:point_trace_cache+28,x
        sta     z:w_node
        lda     a:point_trace_cache,x
        cmp     #2                      ; 1 = clear, 2 = impact.
        rts
@Miss:
        phx
        lda     a:.loword(shotgun_trace_fault)
        pha
        jsr     WalkTraceUncached
        lda     #1
        adc     #0
        tay
        pla
        plx
        cmp     a:.loword(shotgun_trace_fault)
        bne     @Return                 ; Fault counters must still advance.
        tya
        sta     a:point_trace_cache,x
        .repeat 6, I
        lda     a:w_from+2*I
        sta     a:point_trace_cache+2+2*I,x
        lda     a:w_result+2*I
        sta     a:point_trace_cache+14+2*I,x
        .endrepeat
        lda     z:w_lo
        sta     a:point_trace_cache+26,x
        lda     z:w_node
        sta     a:point_trace_cache+28,x
@Return:
        cpy     #2
        rts

.include "quake/PointFractionCache.s"

.ifdef PLAYABLE_SHOT_RESUME_BYTES
.assert PLAYABLE_SHOT_RESUME_VISITS = WALK_MAX_NODES_PER_TRACE, error, "Point-hull resume visit limit changed"
  .ifndef PLAYABLE_E1M1_POINT_OBLIQUE
        .include "quake/PointTraceVerticalResume.s"
  .endif
.endif

.assert w_to = w_from + 6, error, "Point cache requires contiguous trace endpoints"
.assert w_normal = w_result + 6, error, "Point cache requires contiguous trace outputs"
