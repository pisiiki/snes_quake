; The E1M1 point and walk hulls share the existing 32-byte result rows.
; Negative tags mark Q4 rows. Bit 14 selects the live explobox root.
.pushseg
.segment "BSP_CPU_WALK_RESUME"
.assert .defined(WALK_EXPLOBOX_ROOT), error, "Q4 cache key needs the explobox selector"
.assert !.defined(WALK_IMPACT_CACHE_BYTES), error, "Q4 cache replaces the basic impact path"

WalkTraceQ4Cached:
        RW_assume a16i16
        .include "quake/TraceResultCacheCheck.i"
        lda     a:w_from+2
        lsr
        lsr
        clc
        adc     a:w_from
        eor     a:w_from+4
        adc     a:w_to+4
        eor     a:w_to
        and     #((POINT_TRACE_CACHE_BYTES / 32 - 1) * 8)
        asl
        asl
        tax
        lda     a:point_trace_cache,x
        bpl     @NoMatch
        bit     #$4000
        beq     @OpenRoot
        lda     a:qce+QC_EXPLOBOX+QC_FIELD_SOLID
        bne     @Compare
        bra     @NoMatch
@OpenRoot:
        lda     a:qce+QC_EXPLOBOX+QC_FIELD_SOLID
        beq     @Compare
@NoMatch:
        jmp     @Miss
@Compare:
.repeat 6,I
        lda     a:w_from+2*I
        cmp     a:point_trace_cache+2+2*I,x
        bne     @Miss
.endrepeat
.repeat 6,I
        lda     a:point_trace_cache+14+2*I,x
        sta     a:w_result+2*I
.endrepeat
        lda     a:point_trace_cache+26,x
        sta     z:w_lo
        lda     a:point_trace_cache+28,x
        sta     a:w_enter
        lda     a:point_trace_cache,x
        and     #3
        cmp     #2
        bcc     @Clear
        inc     a:w_impacts
        lda     a:w_enter
        cmp     #WALK_NO_PLANE
        bne     :+
        inc     a:w_startsolid
:       sec
@Clear: rtl
@Miss:
        phx
        lda     a:w_trace_fault
        pha
        jsl     WalkTraceQ4UncachedFar
        lda     #1
        adc     #0
        tay
        pla
        plx
        cmp     a:w_trace_fault
        bne     @Return
.repeat 6,I
        lda     a:w_from+2*I
        sta     a:point_trace_cache+2+2*I,x
        lda     a:w_result+2*I
        sta     a:point_trace_cache+14+2*I,x
.endrepeat
        lda     z:w_lo
        sta     a:point_trace_cache+26,x
        lda     a:w_enter
        sta     a:point_trace_cache+28,x
        lda     a:qce+QC_EXPLOBOX+QC_FIELD_SOLID
        beq     @OpenTag
        tya
        ora     #$C000
        bra     @Publish
@OpenTag:
        tya
        ora     #$8000
@Publish:
        sta     a:point_trace_cache,x
@Return:
        cpy     #2
        rtl

InvalidateTraceResultCache:
        .include "quake/TraceResultCacheValidate.i"
        rtl

MarkTraceResultCacheDirty:
        php
        pha
        lda     #1
        sta     a:qc_exit_collision_dirty
        pla
        plp
        rtl
.popseg
