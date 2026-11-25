; Immutable path_corner records have a Q3 origin followed by the next token.
; Only a committed actor move relinks its bounds and touches the corner.
GruntCorners = QuakeCInitGruntFields + QC_PATROL_TABLE
GruntTouchCorner:
        and     #$7fff
        tax
        .repeat 3, I
        ; Stock setsize(-8..8), expanded by one unit in SV_LinkEdict.
        lda     a:qce+QC_FIELD_ABSMIN+2*I,y
        sec
        sbc     f:GruntCorners+2*I,x
        bmi     :+
        cmp     #9*8+1
        bcc     :+
        rts
:       lda     f:GruntCorners+2*I,x
        sec
        sbc     a:qce+QC_FIELD_ABSMAX+2*I,y
        bmi     :+
        cmp     #9*8+1
        bcc     :+
        rts
:
        .endrepeat
        lda     f:GruntCorners+6,x
        sta     a:qce+QC_FIELD_MOVETARGET,y
        sta     a:qce+QC_FIELD_GOALENTITY,y
        and     #$7fff
        tax
        ; This link callback is inside movetogoal. Preserve the VM argument
        ; and return registers used by the ordinary vectoyaw builtin.
        lda     a:qcg+2
        pha
        lda     a:qcg+8
        pha
        lda     a:qcg+10
        pha
        lda     f:GruntCorners,x
        sec
        sbc     a:qce+QC_FIELD_ORIGIN,y
        sta     a:qcg+8
        lda     f:GruntCorners+2,x
        sec
        sbc     a:qce+QC_FIELD_ORIGIN+2,y
        sta     a:qcg+10
        jsr     GruntVectorYaw
        GRUNT_FIELD sta, QC_FIELD_IDEAL_YAW
        pla
        sta     a:qcg+10
        pla
        sta     a:qcg+8
        pla
        sta     a:qcg+2
        rts
