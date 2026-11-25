; Linked records encode fixed argument destinations. Keep the scalar copies
; ordered so overlapping source and destination vectors retain VM semantics.
.macro QC_STORE_VECTOR_PARM handler, destination
handler:
        ldy     #destination
        bra     QCStoreVectorSource
.endmacro
QC_STORE_VECTOR_PARM QCStoreVectorParm0, 8
QC_STORE_VECTOR_PARM QCStoreVectorParm1, 14
QC_STORE_VECTOR_PARM QCStoreVectorParm2, 20
QC_STORE_VECTOR_PARM QCStoreVectorParm3, 26
QC_STORE_VECTOR_PARM QCStoreVectorParm4, 32
.delmacro QC_STORE_VECTOR_PARM

.ifdef PLAYABLE_E1M1_LINKED_QC_FIELDS
; B is the proven field offset. Read self live and retain the original
; 16-bit wrap when computing the edict address.
.macro QC_SELF_FIELD
        lda     f:QuakeCCode+6,x
        tay
        lda     a:qcg+QC_GLOBAL_SELF
        clc
        adc     f:QuakeCCode+4,x
.endmacro

QCLoadSelf:
        QC_SELF_FIELD
        tax
        lda     a:qce,x
QCStoreSelfResult:
        sta     a:qcg,y
        jmp     QuakeCDispatch

QCLoadSelfVector:
        QC_SELF_FIELD
        tax
        jmp     QCLoadFieldVectorXY

QCAddressSelf:
        QC_SELF_FIELD
        bra     QCStoreSelfResult
.delmacro QC_SELF_FIELD
.endif
