; Fixed-step flight for the stock dog leap. QuakeC owns launch, touch,
; damage and the animation. This host advances the Q3 velocity at 20 Hz.
DogAdvance:
        lda     a:qce+QC_FIELD_FLAGS,x
        bit     #512
        bne     @Idle
        lda     a:qce+QC_FIELD_TOUCH,x
        beq     @Idle
        lda     a:qce+QC_FIELD_VELOCITY,x
        ora     a:qce+QC_FIELD_VELOCITY+2,x
        ora     a:qce+QC_FIELD_VELOCITY+4,x
        bne     @Flight
@Idle:
        rts
@Flight:
        stx     a:qcg+QC_GLOBAL_SELF
        lda     a:qce+QC_FIELD_VELOCITY+4,x
        sec
        sbc     #40*8
        sta     a:qce+QC_FIELD_VELOCITY+4,x
        .repeat 3, I
        lda     a:qce+QC_FIELD_ORIGIN+2*I,x
        asl
        sta     a:w_from+2*I
        lda     a:qce+QC_FIELD_VELOCITY+2*I,x
        jsr     DogVelocityStep
        clc
        adc     a:w_from+2*I
        sta     a:w_to+2*I
        .endrepeat
        stz     a:dog_landed
        stz     a:dog_hit_player
        jsr     WalkTrace
        bcc     @Position
        lda     a:w_normal+4
        bmi     @Position
        cmp     #WALK_FLOOR_Z
        bcc     @Position
        inc     a:dog_landed
@Position:
        .repeat 3, I
        lda     a:w_result+2*I
        sta     a:gr_move_target+2*I
        inc
        cmp     #$8000
        ror
        sta     a:gr_move_q3+2*I
        .endrepeat
        jsr     GruntClearOfPlayer
        bcc     @Player
        jsr     GruntStoreOrigin
        bra     @Contact
@Player:
        inc     a:dog_hit_player
        stz     a:dog_landed
@Contact:
        ldx     a:gr_tick_actor
        lda     a:dog_landed
        beq     @Touch
        lda     a:qce+QC_FIELD_FLAGS,x
        ora     #512
        sta     a:qce+QC_FIELD_FLAGS,x
@Touch:
        lda     a:dog_landed
        ora     a:dog_hit_player
        beq     @Done
        stz     a:qcg+QC_GLOBAL_OTHER
        lda     a:dog_hit_player
        beq     :+
        lda     #QC_ENTITY_STRIDE
        sta     a:qcg+QC_GLOBAL_OTHER
:
        lda     a:qce+QC_FIELD_TOUCH,x
        ldx     #4096
        stx     z:qc_budget
        jsr     QuakeCInvokeOuter
        ldx     a:gr_tick_actor
        stz     a:qce+QC_FIELD_VELOCITY,x
        stz     a:qce+QC_FIELD_VELOCITY+2,x
        lda     a:dog_landed
        beq     @Done
        stz     a:qce+QC_FIELD_VELOCITY+4,x
@Done:
        rts

; Convert signed Q3 units/sec to Q4 displacement for one 1/20-sec step.
DogVelocityStep:
        phx
        cmp     #$8000
        php
        jsr     QCAbs
        sta     z:qc_tmp
        lda     #0
        ldx     #16
@Bit:
        asl     z:qc_tmp
        rol
        cmp     #10
        bcc     @Next
        sbc     #10
        inc     z:qc_tmp
@Next:
        dex
        bne     @Bit
        lda     z:qc_tmp
        plp
        plx
        bcc     :+
        jmp     QCNegate
:       rts

DogCheckBottom:
        ldx     a:qcg+8
        .repeat 3, I
        lda     a:qce+QC_FIELD_ORIGIN+2*I,x
        asl
        sta     a:gr_move_target+2*I
        .endrepeat
        jsr     GruntCheckBottom
        lda     #0
        bcc     :+
        lda     #64
:       sta     a:qcg+2
        rts
