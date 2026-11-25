; The authored support table bounds every vertical point ray from an entire
; footprint cell, including the full range of each moving plane.
.assert PLAYABLE_SHOT_SUPPORT_MAX_VISITS < 4096, error, "Certified footing exceeds the trace visit budget"
.assert PLAYABLE_SHOT_SUPPORT_MAX_STACK <= SHOT_HULL_STACK_ENTRIES, error, "Certified footing exceeds the trace stack"
.assert PLAYABLE_SHOT_SUPPORT_DIRECTORY_BYTES = 4*PLAYABLE_SHOT_SUPPORT_HEIGHTS+2, error, "Footing row directory size changed"

; The fallback trace owns these scratch words only after this lookup returns.
support_x = w_lo
support_y = w_hi
support_end = w_sp

.macro FOOTING_CELL minimum, span, outside
        sec
        sbc     #minimum
        cmp     #span
        bcc     :+
        jmp     outside
:
        asl
        xba
        and     #$00ff
.endmacro

; Carry set means the center and corners pass the ordinary support test.
; Carry clear leaves the caller's existing five probes to decide support.
.pushseg
.segment "BSP_CPU_FOOTING_LOOKUP"
ShotSupportCertificate:
        lda     a:gr_foot_z
        FOOTING_CELL PLAYABLE_SHOT_SUPPORT_MIN_Z, PLAYABLE_SHOT_SUPPORT_SPAN_Z, @Trace
        ldx     a:qcg+QC_GLOBAL_SELF
        cpx     #QC_DOG_FIRST
        bcc     :+
        clc
        adc     #PLAYABLE_SHOT_SUPPORT_HEIGHTS
:
        asl
        tax
        lda     f:ShotSupportDirectory+2,x
        sta     z:support_end
        lda     f:ShotSupportDirectory,x
        cmp     z:support_end
        beq     @Trace
        tay
        lda     a:gr_move_q3
        FOOTING_CELL PLAYABLE_SHOT_SUPPORT_MIN_X, PLAYABLE_SHOT_SUPPORT_SPAN_X, @Trace
        sta     z:support_x
        lda     a:gr_move_q3+2
        FOOTING_CELL PLAYABLE_SHOT_SUPPORT_MIN_Y, PLAYABLE_SHOT_SUPPORT_SPAN_Y, @Trace
        sta     z:support_y
        tyx
@Rectangle:
        lda     f:ShotSupportRectangles,x
        and     #$00ff
        cmp     z:support_x
        beq     :+
        bcs     @Trace                  ; Left edges are sorted within a bucket.
:
        lda     f:ShotSupportRectangles,x
        xba
        and     #$00ff
        cmp     z:support_x
        bcc     @Next
        lda     f:ShotSupportRectangles+2,x
        and     #$00ff
        cmp     z:support_y
        beq     :+
        bcs     @Next
:
        lda     f:ShotSupportRectangles+2,x
        xba
        and     #$00ff
        cmp     z:support_y
        bcc     @Next
@Certified:
        QC_YIELD_COORDINATE_STREAM
        sec
        rtl
@Next:
        .repeat 4
        inx
        .endrepeat
        cpx     z:support_end
        bcc     @Rectangle
@Trace:
        clc
        rtl
.delmacro FOOTING_CELL

.assert *-ShotSupportCertificate <= 176, error, "Footing lookup exceeds its CPU reservation"
ShotSupportDirectory:
        .incbin "Data/PlayableShotSupport.bin", 0, PLAYABLE_SHOT_SUPPORT_DIRECTORY_BYTES
.assert *-ShotSupportDirectory = PLAYABLE_SHOT_SUPPORT_DIRECTORY_BYTES, error, "Footing directory length changed"
.popseg

; Both lookups use far reads, so rectangles can remain in the interpreter bank.
ShotSupportRectangles:
        .incbin "Data/PlayableShotSupport.bin", PLAYABLE_SHOT_SUPPORT_DIRECTORY_BYTES
.assert *-ShotSupportRectangles = PLAYABLE_SHOT_SUPPORT_BYTES - PLAYABLE_SHOT_SUPPORT_DIRECTORY_BYTES, error, "Footing rectangle length changed"
