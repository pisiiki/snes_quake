; Only a normal soldier death can create a backpack. A converted actor reuses
; that edict tail for its persistent head and three independent temporary edicts.
GIB_RECORDS = 400
GIB_BYTES = 28
GIB_ROW = 2
GIB_ORIGIN = 4
GIB_VELOCITY = 10
GIB_ANGLES = 16
GIB_SPIN = 22
.assert GIB_RECORDS+4*GIB_BYTES = QC_ENTITY_STRIDE, error, "Gib records must fit the stock edict stride"
.assert GIB_RECORDS+GIB_ROW = PACK_LIFE, error, "Head marker must disambiguate the backpack union"

GibSetSize:
        ; The original setsize args are Q6 vectors. Edict hull extents use Q3.
        .repeat 3, I
        lda     a:qcg+14+2*I
        .repeat 3
        cmp     #$8000
        ror
        .endrepeat
        sta     a:qce+QC_FIELD_MINS+2*I,x
        lda     a:qcg+20+2*I
        .repeat 3
        cmp     #$8000
        ror
        .endrepeat
        sta     a:qce+QC_FIELD_MAXS+2*I,x
        sec
        sbc     a:qce+QC_FIELD_MINS+2*I,x
        sta     a:qce+QC_FIELD_SIZE+2*I,x
        .endrepeat
        rts

GibModelIds:
        .repeat 5, I
        .word   .ident(.sprintf("QC_GIB_MODEL_%d", I))
        .endrepeat

; Called only at the original DONE of ThrowHead or ThrowGib, after all stock
; RNG, velocity and nextthink assignments. Shared spawn scratch is safe again
; only after the complete individual fragment has been copied.
GibCapture:
        lda     a:qcg+QC_GLOBAL_SELF
        clc
        adc     #GIB_RECORDS
        tax
        ldy     z:qc_b
        beq     @Piece
        ldy     a:qcg+QC_GLOBAL_SELF
        inc     a:gib_actor_count
        lda     #$ffff
        bra     @Life
@Piece:
        .repeat 3, I
        txa
        clc
        adc     #GIB_BYTES
        tax
        lda     a:qce,x
        beq     @Found
        .endrepeat
        jmp     QuakeCTrap
@Found:
        ldy     #QC_GRUNT_DROP
        lda     a:qce+QC_FIELD_NEXTTHINK,y
        sec
        sbc     a:qcg+QC_GLOBAL_TIME
@Life:
        sta     a:qce,x
        stx     a:gib_cursor
        lda     a:qce+QC_FIELD_MODEL,y
        ldx     #0
@Model:
        cmp     f:GibModelIds,x
        beq     @Located
        inx
        inx
        cpx     #10
        bcc     @Model
        jmp     QuakeCTrap
@Located:
        txa
        lsr
        clc
        adc     #QC_GIB_FIRST_ROW
        ldx     z:qc_b
        beq     :+
        ora     #$8000
:       ldx     a:gib_cursor
        sta     a:qce+GIB_ROW,x
        .repeat 3, I
        lda     a:qce+QC_FIELD_ORIGIN+2*I,y
        sta     a:qce+GIB_ORIGIN+2*I,x
        lda     a:qce+QC_FIELD_VELOCITY+2*I,y
        sta     a:qce+GIB_VELOCITY+2*I,x
        lda     a:qce+QC_FIELD_AVELOCITY+2*I,y
        sta     a:qce+GIB_SPIN+2*I,x
        lda     z:qc_b
        beq     :+
        lda     a:qce+QC_FIELD_ANGLES+2*I,y
:       sta     a:qce+GIB_ANGLES+2*I,x
        .endrepeat
        rts

GibAdvance:
        txa
        clc
        adc     #GIB_RECORDS
        tax
        lda     #4
        sta     a:gib_remaining
@Next:
        stx     a:gib_cursor
        lda     a:qce,x
        beq     @Skip
        cmp     #$ffff
        beq     @Live
        sec
.ifdef QC_QUEUED_INPUT
        sbc     a:qc_elapsed_units
.else
        sbc     #1
.endif
        bcs     :+
        lda     #0
:       sta     a:qce,x
        beq     @Skip
@Live:
        jsr     GibToss
@Skip:
        lda     a:gib_cursor
        clc
        adc     #GIB_BYTES
        tax
        dec     a:gib_remaining
        bne     @Next
        rts

GibToss:
        lda     a:qce+GIB_VELOCITY,x
        ora     a:qce+GIB_VELOCITY+2,x
        ora     a:qce+GIB_VELOCITY+4,x
        bne     :+
        rts
:
        ; Clip to Quake's sv_maxvelocity before gravity. Integrate angles
        ; from Q3 degrees/sec to Q6 degrees in the same 50-ms service.
        ldy     #0
@Axis:
        lda     a:qce+GIB_VELOCITY,x
        bmi     @Negative
        cmp     #2000*8
        bcc     @Clamped
        lda     #2000*8
        bra     @Clamped
@Negative:
        cmp     #.loword(-2000*8)
        bcs     @Clamped
        lda     #.loword(-2000*8)
@Clamped:
        cpy     #4
        bne     :+
        sec
        sbc     #40*8
:       sta     a:qce+GIB_VELOCITY,x
        jsr     DogVelocityStep
        sta     a:w_temp
        lda     a:qce+GIB_ORIGIN,x
        pha
        lda     a:gib_remaining
        cmp     #4
        pla
        bcc     @Point
        cpy     #4
        bne     :+
        clc
        adc     #24*8
:       asl
        bra     @From
@Point: pha
        ; DogVelocityStep gave Q4 displacement. Signed divide by two,
        ; truncating toward zero, gives the point hull Q3 displacement.
        lda     a:w_temp
        bpl     :+
        inc
:       cmp     #$8000
        ror
        sta     a:w_temp
        pla
@From:  sta     a:w_from,y
        clc
        adc     a:w_temp
        sta     a:w_to,y
        lda     a:qce+GIB_SPIN,x
        asl
        asl
        jsr     DogVelocityStep
        clc
        adc     a:qce+GIB_ANGLES,x
        bpl     :+
        clc
        adc     #360*64
:       cmp     #360*64
        bcc     :+
        sbc     #360*64
:       sta     a:qce+GIB_ANGLES,x
        inx
        inx
        iny
        iny
        cpy     #6
        bcs     :+
        jmp     @Axis
:       lda     a:gib_remaining
        cmp     #4
        bne     @PointTrace
        jsr     WalkTrace
        bra     @TraceResult
@PointTrace:
        jsr     ShotHull::WalkTrace
@TraceResult:
        php
        ldx     a:gib_cursor
        ldy     #0
@Position:
        lda     a:gib_remaining
        cmp     #4
        lda     a:w_result,y
        bcc     @Store
        inc
        cmp     #$8000
        ror
        cpy     #4
        bne     @Store
        sec
        sbc     #24*8
@Store: sta     a:qce+GIB_ORIGIN,x
        inx
        inx
        iny
        iny
        cpy     #6
        bcc     @Position
        plp
        bcc     @Sync
        jsr     GibBounce
@Sync:
        lda     a:gib_remaining
        cmp     #4
        bne     @Done
        ldx     a:gib_cursor
        ldy     a:gr_tick_actor
        .repeat 3, I
        lda     a:qce+GIB_ORIGIN+2*I,x
        sta     a:qce+QC_FIELD_ORIGIN+2*I,y
        lda     a:qce+GIB_VELOCITY+2*I,x
        sta     a:qce+QC_FIELD_VELOCITY+2*I,y
        lda     a:qce+GIB_ANGLES+2*I,x
        sta     a:qce+QC_FIELD_ANGLES+2*I,y
        lda     a:qce+GIB_SPIN+2*I,x
        sta     a:qce+QC_FIELD_AVELOCITY+2*I,y
        .endrepeat
@Done:  rts

GibBounce:
        stz     a:w_dot
        stz     a:w_dot_high
        ldy     #0
@Dot:   tya
        clc
        adc     a:gib_cursor
        tax
        lda     a:qce+GIB_VELOCITY,x
        ldx     a:w_normal,y
        phy
        jsr     WalkMultiply
        ply
        lda     a:w_dot
        clc
        adc     z:w_mul_low
        sta     a:w_dot
        lda     a:w_dot_high
        adc     z:w_mul_high
        sta     a:w_dot_high
        iny
        iny
        cpy     #6
        bcc     @Dot
        lda     a:w_dot
        sta     z:w_mul_low
        lda     a:w_dot_high
        sta     z:w_mul_high
        jsr     WalkProductQ14
        sta     a:w_progress
        cmp     #$8000
        ror
        clc
        adc     a:w_progress
        sta     a:w_progress
        ldy     #0
@Clip:  lda     a:w_normal,y
        ldx     a:w_progress
        phy
        jsr     WalkMultiply
        ply
        jsr     WalkProductQ14
        sta     a:w_temp
        tya
        clc
        adc     a:gib_cursor
        tax
        lda     a:qce+GIB_VELOCITY,x
        sec
        sbc     a:w_temp
        sta     a:qce+GIB_VELOCITY,x
        iny
        iny
        cpy     #6
        bcc     @Clip
        lda     a:w_normal+4
        bmi     @Done
        cmp     #WALK_FLOOR_Z
        bcc     @Done
        ldx     a:gib_cursor
        lda     a:qce+GIB_VELOCITY+4,x
        bmi     @Stop
        cmp     #60*8
        bcs     @Done
@Stop:
        lda     a:gib_remaining
        cmp     #4
        bne     :+
        ldy     a:gr_tick_actor
        lda     a:qce+QC_FIELD_FLAGS,y
        ora     #512                    ; FL_ONGROUND on the converted edict.
        sta     a:qce+QC_FIELD_FLAGS,y
:       .repeat 3, I
        stz     a:qce+GIB_VELOCITY+2*I,x
        stz     a:qce+GIB_SPIN+2*I,x
        .endrepeat
@Done:  rts

; Append current fragments in stable actor/spawn order after the packs.
; All ten Easy actors together can occupy at most 30 of these 34 slots.
GibStage:
        lda     a:gib_actor_count
        bne     :+
        rts
:       lda     #QC_GRUNT
        sta     a:gib_cursor
@Actor:
        ldy     a:gib_cursor
        lda     a:qce+GIB_RECORDS+GIB_ROW,y
        bmi     :+
        jmp     @NextActor
:       tya
        clc
        adc     #(GIB_RECORDS+GIB_BYTES)
        tay
        lda     #3
        sta     a:gib_remaining
@Piece:
        lda     a:qce,y
        bne     :+
        jmp     @Next
:       cpx     #(GSU_ALIAS_LIVE_COUNT*GSU_GRUNT_POSE_BYTES)
        bcc     :+
        rts
:
        phx
        lda     a:qce+GIB_ANGLES+2,y
        jsr     GruntAngleIndex
        plx
        sta     a:gr_trial
        lda     a:qce+GIB_ROW,y
        xba
        ora     a:gr_trial
        sta     f:GSU_LIVE_POSE_ADDRESS,x
        .repeat 3, I
        lda     a:qce+GIB_ORIGIN+2*I,y
          .if I = 2
        sec
        sbc     #22*8
          .endif
        clc
        adc     #16
          .repeat 5
        cmp     #$8000
        ror
          .endrepeat
        sta     f:GSU_LIVE_POSE_ADDRESS+2+2*I,x
        .endrepeat
        txa
        clc
        adc     #GSU_GRUNT_POSE_BYTES
        tax
@Next:
        tya
        clc
        adc     #GIB_BYTES
        tay
        dec     a:gib_remaining
        beq     @NextActor
        jmp     @Piece
@NextActor:
        lda     a:gib_cursor
        clc
        adc     #QC_ENTITY_STRIDE
        sta     a:gib_cursor
        cmp     #QC_GRUNT_DROP
        bcs     @Done
        jmp     @Actor
@Done:  rts
