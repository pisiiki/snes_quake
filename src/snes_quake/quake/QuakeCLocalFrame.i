; X is the first local byte, Y the first saved-stack byte. Linked descriptors
; prove the complete local range lies in globals. The caller already checked
; the 256-byte stack limit and skipped empty frames.
.assert PLAYABLE_E1M1_LOCAL_COPY_END = 1, error, "Frame copies require the checked end offset"
.assert QuakeCGlobals + QC_GLOBAL_BYTES <= QCStack || QCStack + 256 <= QuakeCGlobals, lderror, "VM globals and stack overlap"

.macro QC_LOCAL_WORD offset, restore
  .if restore
        lda     a:qcs+offset,y
        sta     a:qcg+offset,x
  .else
        lda     a:qcg+offset,x
        sta     a:qcs+offset,y
  .endif
.endmacro

.macro QC_LOCAL_FRAME label, restore
.proc label
        lda     z:qc_size
        cmp     #16
        beq     Words8
        cmp     #14
        beq     Words7
        cmp     #4
        beq     Words2
        cmp     #10
        beq     Words5
        cmp     #18
        beq     Words9
        cmp     #8
        beq     Words4
Loop:   QC_LOCAL_WORD 0, restore
        inx
        inx
        iny
        iny
        cpy     z:qc_arg
        bne     Loop
        rts
Words9: QC_LOCAL_WORD 16, restore
Words8: QC_LOCAL_WORD 14, restore
Words7: QC_LOCAL_WORD 12, restore
        QC_LOCAL_WORD 10, restore
Words5: QC_LOCAL_WORD 8, restore
Words4: QC_LOCAL_WORD 6, restore
        QC_LOCAL_WORD 4, restore
Words2: QC_LOCAL_WORD 2, restore
        QC_LOCAL_WORD 0, restore
  .if restore
        ; QuakeCInvoke returns X and Y just beyond both copied ranges.
        txa
        clc
        adc     z:qc_size
        tax
  .endif
        ldy     z:qc_arg
        sec                             ; CPY at the original loop exit
        rts
.endproc
.endmacro

QC_LOCAL_FRAME QCSaveLocalFrame, 0
QC_LOCAL_FRAME QCRestoreLocalFrame, 1
.delmacro QC_LOCAL_FRAME
.delmacro QC_LOCAL_WORD
