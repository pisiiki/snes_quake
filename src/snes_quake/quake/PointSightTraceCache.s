; Cache each monster's sight trace through world geometry. The caller still
; publishes the QuakeC trace globals. Moving collision planes clear the cache.
WalkSightTrace:
        lda     a:qcg+20
        cmp     #64                     ; MOVE_NOMONSTERS in QuakeC Q6.
        bne     @Uncached
        lda     a:qcg+QC_GLOBAL_SELF
        sec
        sbc     #QC_GRUNT
        cmp     #(QC_GRUNT_COUNT*QC_ENTITY_STRIDE)
        bcs     @Uncached
        bit     #(QC_ENTITY_STRIDE-1)
        beq     @Lookup
@Uncached:
        jmp     WalkTrace
@Lookup:
        .repeat 4
        lsr
        .endrepeat
        tax
        QC_YIELD_COORDINATE_STREAM
        lda     f:SightTraceCache,x
        beq     @Miss
        .repeat 6, word
        lda     a:w_from+2*word
        cmp     f:SightTraceCache+2+2*word,x
        bne     @Miss
        .endrepeat
        .repeat 6, word
        lda     f:SightTraceCache+14+2*word,x
        sta     a:w_result+2*word
        .endrepeat
        lda     f:SightTraceCache+26,x
        sta     z:w_lo
        lda     f:SightTraceCache+28,x
        sta     z:w_node
        lda     f:SightTraceCache,x
        cmp     #2                      ; 1 = clear, 2 = impact.
        rts
@Miss:
        phx
        lda     a:.loword(shotgun_trace_fault)
        pha
        jsr     WalkSightTraceBody
        lda     #1
        adc     #0
        tay
        pla
        plx
        cmp     a:.loword(shotgun_trace_fault)
        bne     @Return
        .repeat 6, word
        lda     a:w_from+2*word
        sta     f:SightTraceCache+2+2*word,x
        lda     a:w_result+2*word
        sta     f:SightTraceCache+14+2*word,x
        .endrepeat
        lda     z:w_lo
        sta     f:SightTraceCache+26,x
        lda     z:w_node
        sta     f:SightTraceCache+28,x
        tya
        sta     f:SightTraceCache,x
@Return:
        cpy     #2
        rts

; The table lives outside the ordinary QuakeC RAM clear. Invalidate the
; status word for each row on map initialization and when a mover changes.
WalkSightCacheInvalidate:
        ldx     #(QC_GRUNT_COUNT-1)*SIGHT_TRACE_ROW_BYTES
@Clear:
        lda     #0
        sta     f:SightTraceCache,x
        txa
        sec
        sbc     #SIGHT_TRACE_ROW_BYTES
        tax
        bpl     @Clear
        rts

.assert (QC_ENTITY_STRIDE = 512) && (SIGHT_TRACE_ROW_BYTES = 32), error, "Sight cache index assumes 512-byte entities and 32-byte rows"
.assert w_to = w_from+6, error, "Sight cache requires contiguous endpoints"
.assert w_normal = w_result+6, error, "Sight cache requires contiguous outputs"
