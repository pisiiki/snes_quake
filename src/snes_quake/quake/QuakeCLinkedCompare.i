; A linked comparison whose result is the following IFNOT's input. The
; branch record itself stays intact for jumps or function entries to it.
QCIfNotEqual:
        jsr     QCCompare
        beq     QCIfNotTrue
        bra     QCIfNotFalse
QCIfNotNotEqual:
        jsr     QCCompare
        bne     QCIfNotTrue
        bra     QCIfNotFalse
QCIfNotNot:
        QC_LOAD_A_X 1
        lda     a:qcg,x
        beq     QCIfNotTrue
        bra     QCIfNotFalse
QCIfNotAnd:
        jsr     QCOperands
        beq     QCIfNotFalse
        lda     a:qcg,y
        bne     QCIfNotTrue
        bra     QCIfNotFalse
QCIfNotOr:
        jsr     QCOperands
        ora     a:qcg,y
        bne     QCIfNotTrue
        bra     QCIfNotFalse

; Signed subtraction supplies Z for equality and N xor V for less-than.
QCIfNotSubtract:
        jsr     QCOperands
        sec
        sbc     a:qcg,y
        rts
QCIfNotLessEqual:
        jsr     QCIfNotSubtract
        beq     QCIfNotTrue
        bra     QCIfNotSignedLess
QCIfNotGreater:
        jsr     QCIfNotSubtract
        beq     QCIfNotFalse
        bra     QCIfNotSignedGreaterEqual
QCIfNotLess:
        jsr     QCIfNotSubtract
QCIfNotSignedLess:
        bvs     QCIfNotNonnegative
QCIfNotNegative:
        bmi     QCIfNotTrue
        bra     QCIfNotFalse
QCIfNotGreaterEqual:
        jsr     QCIfNotSubtract
QCIfNotSignedGreaterEqual:
        bvs     QCIfNotNegative
QCIfNotNonnegative:
        bpl     QCIfNotTrue
QCIfNotFalse:
        ldy     z:qc_c
        lda     #0
        sta     a:qcg,y
        ldx     z:qc_pc
        lda     f:QuakeCCode+4,x       ; IFNOT's checked branch target
        bra     QCIfNotFinish
QCIfNotTrue:
        ldy     z:qc_c
        lda     #64
        sta     a:qcg,y
        lda     z:qc_pc
        clc
        adc     #8                     ; IFNOT falls through
QCIfNotFinish:
        ; The comparison has committed. Exhaustion here reports the unchanged
        ; IFNOT PC and charges exactly the preceding comparison.
        dec     z:qc_budget
        bne     :+
        jmp     QCNoOpcode
:       sta     z:qc_pc
        jmp     QuakeCDispatch
