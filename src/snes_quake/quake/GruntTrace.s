; Clip point traces against stock edicts' linked bounds after the world
; and pusher trace. Every distance here is in rebased Q3, time in Q12.
GruntTraceActor:
.if QC_GRUNT_COUNT = 0
  .ifdef QC_HUB_CLUE_EDICT
        lda     a:qcg+20                 ; MOVE_NOMONSTERS skips the BBOX.
        bne     @Done
        lda     a:qcg+QC_GLOBAL_SELF
        cmp     #QC_ENTITY_STRIDE
        bne     @Done
        lda     a:qcg+26
        sta     a:gr_trace_passed
        lda     #QC_HUB_CLUE_EDICT
        jsr     GruntTraceCandidate
        lda     a:qcg+QC_GLOBAL_TRACE_ENT
        cmp     #QC_HUB_CLUE_EDICT
        bne     @Done
        jmp     QuakeCHubShootClue
@Done:
  .endif
        rts

.else
        ; MOVE_NOMONSTERS leaves player and grunt out of visibility traces.
        lda     a:qcg+20
        bne     @Done
        lda     a:qcg+26                 ; traceline's passedict.
        sta     a:gr_trace_passed
        lda     #QC_ENTITY_STRIDE
        jsr     GruntTraceCandidate
        lda     #QC_GRUNT
@Scan:
        jsr     GruntTraceCandidate
        lda     a:gr_trace_actor
        clc
        adc     #QC_ENTITY_STRIDE
        cmp     #QC_GRUNT_DROP
        bcc     @Scan
.ifdef QC_EXPLOBOX
        lda     #QC_EXPLOBOX
        jsr     GruntTraceCandidate
.endif
@Done:
        rts

.endif
GruntTraceCandidate:
        sta     a:gr_trace_actor
        cmp     a:gr_trace_passed
        beq     @Done
        tax
        lda     a:qce+QC_FIELD_SOLID,x
        beq     @Done
        stz     a:gr_trace_axis
        stz     a:gr_enter
        stz     a:gr_axis_hit
        lda     z:w_lo
        sta     a:gr_exit
@Axis:
        jsr     GruntClipAxis
        bcc     @Done
        lda     a:gr_trace_axis
        inc
        inc
        sta     a:gr_trace_axis
        cmp     #6
        bcc     @Axis
        lda     a:gr_enter
        cmp     z:w_lo
        bcs     @Done
        sta     z:w_lo
        sta     a:w_safe_t
        stz     a:w_normal
        stz     a:w_normal+2
        stz     a:w_normal+4
        lda     a:gr_axis_hit
        beq     :+
        dec
        tax
        lda     a:gr_trace_normal
        sta     a:w_normal,x
:       jsr     ShotHull::WalkTraceInterpolate
        lda     a:gr_trace_actor
        sta     a:qcg+QC_GLOBAL_TRACE_ENT
@Done:
        rts

GruntClipAxis:
        ldx     a:gr_trace_actor
        ldy     a:gr_trace_axis
        txa
        clc
        adc     a:gr_trace_axis
        tax
        lda     a:qce+QC_FIELD_ORIGIN,x
        clc
        adc     a:qce+QC_FIELD_MINS,x
        eor     #$8000
        sta     a:gr_min
        lda     a:qce+QC_FIELD_ORIGIN,x
        clc
        adc     a:qce+QC_FIELD_MAXS,x
        eor     #$8000
        sta     a:gr_max
        lda     a:w_from,y
        eor     #$8000
        sta     a:gr_start
        lda     a:w_to,y
        eor     #$8000
        sta     a:gr_end
        cmp     a:gr_start
        bcs     @Increasing
        ; Reflect decreasing rays so both paths use the same slab math.
        lda     a:gr_min
        eor     #$ffff
        pha
        lda     a:gr_max
        eor     #$ffff
        sta     a:gr_min
        pla
        sta     a:gr_max
        lda     a:gr_start
        eor     #$ffff
        sta     a:gr_start
        lda     a:gr_end
        eor     #$ffff
        sta     a:gr_end
        lda     #$4000
        bra     @Direction
@Increasing:
        lda     #$c000
@Direction:
        sta     a:gr_normal
        lda     a:gr_start
        cmp     a:gr_max
        bcc     :+
        beq     :+
        clc
        rts
:       lda     a:gr_end
        cmp     a:gr_min
        bcc     @Miss
        sec
        sbc     a:gr_start
        sta     z:w_denominator
        stz     z:w_denominator_high
        stz     z:w_numerator_high
        lda     a:gr_min
        cmp     a:gr_start
        bcc     @Leave
        beq     @Leave
        sec
        sbc     a:gr_start
        sta     z:w_numerator
        jsr     ShotHull::WalkFraction
        cmp     a:gr_enter
        bcc     @Leave
        sta     a:gr_enter
        lda     a:gr_trace_axis
        inc
        sta     a:gr_axis_hit
        lda     a:gr_normal
        sta     a:gr_trace_normal
@Leave:
        lda     a:gr_max
        cmp     a:gr_end
        bcs     @Check
        sec
        sbc     a:gr_start
        sta     z:w_numerator
        stz     z:w_numerator_high
        jsr     ShotHull::WalkFraction
        cmp     a:gr_exit
        bcs     @Check
        sta     a:gr_exit
@Check:
        lda     a:gr_exit
        cmp     a:gr_enter
        rts
@Miss:
        clc
        rts
