.segment "HDMA_WARP_CODE"
.macro HDMA_MUL lhs, rhs, destination
        lda     lhs
        ldx     rhs
        jsr     HdmaMultiplyQ12
        sta     destination
.endmacro

HdmaCameraTerms:
        lda     hdma_rotation_valid
        beq     HdmaNewRotation
        lda     hdma_build_precise
        cmp     hdma_rotation_precise
        bne     HdmaNewRotation
        .repeat 2, angle
          lda   hdma_source_camera+6+angle*2
          cmp   hdma_rotation_key+angle*2
          bne   HdmaNewRotation
          lda   hdma_target_camera+6+angle*2
          cmp   hdma_rotation_key+4+angle*2
          bne   HdmaNewRotation
        .endrepeat
HdmaReuseRotation:
        ; Matrix, source basis, angular steps and cofactors are immutable
        ; between preparations. Only the five running accumulators need reset.
        .repeat 10, word
          lda   hdma_rotation_accum+word*2
          sta   z:hdma_accum-hdma_work+word*2
        .endrepeat
        lda     hdma_rotation_fault
        sta     z:hdma_fault-hdma_work
        jmp     HdmaCameraTranslation
HdmaNewRotation:
        ; Inverse of the actual Q6 render basis, not its transpose.
        lda     hdma_source_camera+6
        xba
        and     #255
        asl
        tax
        lda     f:HdmaDualSine,x
        sta     z:hdma_sy-hdma_work
        lda     f:HdmaDualSine+128,x
        sta     z:hdma_cy-hdma_work
        lda     hdma_source_camera+8
        xba
        and     #255
        asl
        tax
        lda     f:HdmaDualSine,x
        sta     z:hdma_sp-hdma_work
        lda     f:HdmaDualSine+128,x
        sta     z:hdma_cp-hdma_work
        lda     hdma_target_camera+6
        jsr     HdmaTargetSin
        sta     z:hdma_ts-hdma_work
        lda     hdma_target_camera+6
        clc
        adc     #16384
        jsr     HdmaTargetSin
        sta     z:hdma_tc-hdma_work
        lda     hdma_target_camera+8
        jsr     HdmaTargetSin
        sta     z:hdma_ps-hdma_work
        lda     hdma_target_camera+8
        clc
        adc     #16384
        jsr     HdmaTargetSin
        sta     z:hdma_pc-hdma_work

        HDMA_MUL z:hdma_sy-hdma_work, z:hdma_ts-hdma_work, z:hdma_q-hdma_work
        HDMA_MUL z:hdma_cy-hdma_work, z:hdma_tc-hdma_work, z:hdma_r-hdma_work
        clc
        adc     z:hdma_q-hdma_work
        sta     z:hdma_q-hdma_work
        sta     z:hdma_matrix-hdma_work+0
        HDMA_MUL z:hdma_sy-hdma_work, z:hdma_tc-hdma_work, z:hdma_r-hdma_work
        HDMA_MUL z:hdma_cy-hdma_work, z:hdma_ts-hdma_work, z:hdma_partial-hdma_work
        sec
        sbc     z:hdma_r-hdma_work
        sta     z:hdma_r-hdma_work
        HDMA_MUL z:hdma_ps-hdma_work, z:hdma_q-hdma_work, z:hdma_pq-hdma_work
        HDMA_MUL z:hdma_pc-hdma_work, z:hdma_q-hdma_work, z:hdma_cq-hdma_work
        HDMA_MUL z:hdma_ps-hdma_work, z:hdma_r-hdma_work, z:hdma_matrix-hdma_work+2
        neg
        sta     z:hdma_matrix-hdma_work+2
        HDMA_MUL z:hdma_pc-hdma_work, z:hdma_r-hdma_work, z:hdma_matrix-hdma_work+4
        HDMA_MUL z:hdma_sp-hdma_work, z:hdma_r-hdma_work, z:hdma_matrix-hdma_work+6
        HDMA_MUL z:hdma_cp-hdma_work, z:hdma_r-hdma_work, z:hdma_matrix-hdma_work+12
        neg
        sta     z:hdma_matrix-hdma_work+12
        HDMA_MUL z:hdma_sp-hdma_work, z:hdma_pq-hdma_work, z:hdma_matrix-hdma_work+8
        HDMA_MUL z:hdma_cp-hdma_work, z:hdma_pc-hdma_work, z:hdma_partial-hdma_work
        clc
        adc     z:hdma_matrix-hdma_work+8
        sta     z:hdma_matrix-hdma_work+8
        HDMA_MUL z:hdma_sp-hdma_work, z:hdma_cq-hdma_work, z:hdma_matrix-hdma_work+10
        HDMA_MUL z:hdma_cp-hdma_work, z:hdma_ps-hdma_work, z:hdma_partial-hdma_work
        sec
        sbc     z:hdma_matrix-hdma_work+10
        sta     z:hdma_matrix-hdma_work+10
        HDMA_MUL z:hdma_cp-hdma_work, z:hdma_pq-hdma_work, z:hdma_matrix-hdma_work+14
        HDMA_MUL z:hdma_sp-hdma_work, z:hdma_pc-hdma_work, z:hdma_partial-hdma_work
        sec
        sbc     z:hdma_matrix-hdma_work+14
        sta     z:hdma_matrix-hdma_work+14
        HDMA_MUL z:hdma_cp-hdma_work, z:hdma_cq-hdma_work, z:hdma_matrix-hdma_work+16
        HDMA_MUL z:hdma_sp-hdma_work, z:hdma_ps-hdma_work, z:hdma_partial-hdma_work
        clc
        adc     z:hdma_matrix-hdma_work+16
        sta     z:hdma_matrix-hdma_work+16

        jsr     HdmaPrepareRotation
        .repeat 10, word
          lda   z:hdma_accum-hdma_work+word*2
          sta   hdma_rotation_accum+word*2
        .endrepeat
        .repeat 2, angle
          lda   hdma_source_camera+6+angle*2
          sta   hdma_rotation_key+angle*2
          lda   hdma_target_camera+6+angle*2
          sta   hdma_rotation_key+4+angle*2
        .endrepeat
        lda     z:hdma_fault-hdma_work
        sta     hdma_rotation_fault
        lda     hdma_build_precise
        sta     hdma_rotation_precise
        lda     #1
        sta     hdma_rotation_valid
HdmaCameraTranslation:
        .repeat 3, axis
          lda   hdma_target_camera+axis*2
          sec
          sbc   hdma_source_camera+axis*2
          sta   z:hdma_ray-hdma_work+axis*2
        .endrepeat
        HDMA_MUL z:hdma_cy-hdma_work, z:hdma_ray-hdma_work, z:hdma_horizontal-hdma_work
        HDMA_MUL z:hdma_sy-hdma_work, z:hdma_ray-hdma_work+2, z:hdma_partial-hdma_work
        clc
        adc     z:hdma_horizontal-hdma_work
        sta     z:hdma_horizontal-hdma_work
        HDMA_MUL z:hdma_sy-hdma_work, z:hdma_ray-hdma_work, z:hdma_translation-hdma_work
        HDMA_MUL z:hdma_cy-hdma_work, z:hdma_ray-hdma_work+2, z:hdma_partial-hdma_work
        sec
        sbc     z:hdma_translation-hdma_work
        sta     z:hdma_translation-hdma_work
        HDMA_MUL z:hdma_sp-hdma_work, z:hdma_horizontal-hdma_work, z:hdma_translation-hdma_work+2
        HDMA_MUL z:hdma_cp-hdma_work, z:hdma_ray-hdma_work+4, z:hdma_partial-hdma_work
        sec
        sbc     z:hdma_translation-hdma_work+2
        sta     z:hdma_translation-hdma_work+2
        HDMA_MUL z:hdma_cp-hdma_work, z:hdma_horizontal-hdma_work, z:hdma_translation-hdma_work+4
        HDMA_MUL z:hdma_sp-hdma_work, z:hdma_ray-hdma_work+4, z:hdma_partial-hdma_work
        clc
        adc     z:hdma_translation-hdma_work+4
        sta     z:hdma_translation-hdma_work+4
        rts
