; The stock linked pair has independent Q6 pusher state and shared touch use.
; Collision and rendering publish the same sixteen-interval pose per leaf.
QuakeCWalkSupportPose:
.if QC_ENTRANCE_COUNT > 0
        lda     f:quakec_entrance_pose+2
        .repeat 4
        asl
        .endrepeat
        clc
        adc     f:quakec_entrance_pose+2
        adc     f:quakec_entrance_pose
        sta     z:qc_tmp
        asl
        clc
        adc     z:qc_tmp
        sta     z:qc_tmp
        .repeat 4
        asl
        .endrepeat
        clc
        adc     z:qc_tmp
        adc     f:quakec_brush_row
        rts
.else
        lda     f:quakec_brush_row
        rts
.endif

QuakeCEntranceTick:
.if QC_ENTRANCE_COUNT > 0
@CheckTouch:
        lda     f:video_tick
        sta     a:qc_collision_tick
        jsr     QCEntranceTouchesPlayer
        php
        lda     f:video_tick
        cmp     a:qc_collision_tick
        beq     @TouchStable
        plp
        bra     @CheckTouch
@TouchStable:
        plp
        bcc     @Pushers
        ldx     #QC_ENTRANCE_TRIGGER
        ldy     #QC_ENTITY_STRIDE
        lda     a:qce+QC_ENTRANCE_TRIGGER+QC_FIELD_TOUCH
        jsr     QuakeCEvent
@Pushers:
        stz     a:qc_entrance_index
        ldx     #QC_ENTRANCE_0
        jsr     QCAdvanceEntrance
        lda     #2
        sta     a:qc_entrance_index
        ldx     #QC_ENTRANCE_1
        jsr     QCAdvanceEntrance
.endif
        rts

.if QC_ENTRANCE_COUNT > 0
.assert QC_ENTRANCE_COUNT = 2, error, "Entrance requires its linked pair"
.assert QC_ENTRANCE_STEPS = 16, error, "Entrance support key expects seventeen poses"
.assert QC_ENTRANCE_0_DIRECTION = -1, error, "First entrance leaf must move toward negative Y"
.assert QC_ENTRANCE_1_DIRECTION = 1, error, "Second entrance leaf must move toward positive Y"
.assert QC_ENTRANCE_0_MOVE = 2 .and QC_ENTRANCE_1_MOVE = 2, error, "Entrance pushers must translate on Y"
.assert QC_DOOR_STEPS = 16 .and QC_BUTTON_STEPS = 2, error, "Entrance support key expects fifty-one base rows"

.macro QC_ENTRANCE_INSIDE value, axis, exit
        lda     f:value
        sec
        sbc     #.loword(.ident(.concat("QC_ENTRANCE_TRIGGER_", axis, "_MIN")))
        cmp     #(.ident(.concat("QC_ENTRANCE_TRIGGER_", axis, "_MAX")) - .ident(.concat("QC_ENTRANCE_TRIGGER_", axis, "_MIN")) + 1)
        bcs     exit
.endmacro

QCEntranceTouchesPlayer:
        lda     a:w_pending
        beq     @Live
        QC_ENTRANCE_INSIDE WalkPendingXYZ, "X", @Outside
        QC_ENTRANCE_INSIDE WalkPendingXYZ+2, "Y", @Outside
        QC_ENTRANCE_INSIDE WalkPendingXYZ+4, "Z", @Outside
        sec
        rts
@Live:
        QC_ENTRANCE_INSIDE camera_x, "X", @Outside
        QC_ENTRANCE_INSIDE camera_y, "Y", @Outside
        QC_ENTRANCE_INSIDE camera_z, "Z", @Outside
        sec
        rts
@Outside:
        clc
        rts

QCAdvanceEntrance:
        lda     a:qce+QC_FIELD_NEXTTHINK,x
        bne     :+
        rts
:       bpl     :+
        rts
:       dec     a:qce+QC_FIELD_NEXTTHINK,x
        stx     a:qc_entity
        txa
        clc
        adc     #2
        tax
        stx     a:qc_axis
        lda     a:qce+QC_FIELD_VELOCITY,x
        bne     :+
        jmp     @Think
:       sta     a:qc_displacement
        ldx     a:qc_entity
        clc
        adc     a:qce+QC_PUSHER_FRACTION,x
        pha
        and     #$3f
        sta     a:qc_fraction
        pla
        .repeat 6
        cmp     #$8000
        ror
        .endrepeat
        ldx     a:qc_axis
        clc
        adc     a:qce+QC_FIELD_ORIGIN,x
        sta     a:qc_candidate
        ldy     a:qc_entity
        lda     a:qce+QC_FIELD_NEXTTHINK,y
        bne     :+
        lda     a:qce+QC_FIELD_FINALDEST,x
        sta     a:qc_candidate
:       jsr     QCEntranceQuantizePose
        ldx     a:qc_entrance_index
        lda     a:qc_pose
        cmp     f:quakec_entrance_pose,x
        beq     @Commit
@CheckPlayer:
        lda     f:video_tick
        sta     a:qc_collision_tick
        lda     a:qc_pose
        ldx     a:qc_entrance_index
        jsr     WalkEntranceContainsPlayer
        bcc     @NoNewOverlap
        ldx     a:qc_entrance_index
        lda     f:quakec_entrance_pose,x
        jsr     WalkEntranceContainsPlayer
        bcs     @NoNewOverlap
        sec
        bra     @PlayerChecked
@NoNewOverlap:
        clc
@PlayerChecked:
        php
        lda     f:video_tick
        cmp     a:qc_collision_tick
        beq     @PlayerStable
        plp
        bra     @CheckPlayer
@PlayerStable:
        plp
        bcs     @Blocked
        ldx     a:qc_entrance_index
        lda     a:qc_pose
        sta     f:quakec_entrance_pose,x
.ifdef PLAYABLE_E1M1_WALK_RESUME_BYTES
        jsl     MarkTraceResultCacheDirty
.endif
@Commit:
        ldx     a:qc_axis
        lda     a:qc_candidate
        sta     a:qce+QC_FIELD_ORIGIN,x
        ldx     a:qc_entity
        lda     a:qc_fraction
        sta     a:qce+QC_PUSHER_FRACTION,x
@Think:
        ldx     a:qc_entity
        lda     a:qce+QC_FIELD_NEXTTHINK,x
        bne     @Done
        ldy     #0
        lda     a:qce+QC_FIELD_THINK,x
        jmp     QuakeCEvent
@Blocked:
        ldx     a:qc_entity
        inc     a:qce+QC_FIELD_NEXTTHINK,x
        inc     a:.loword(quakec_door_blocks)
        ldy     #QC_ENTITY_STRIDE
        lda     a:qce+QC_FIELD_BLOCKED,x
        jmp     QuakeCEvent
@Done:
        rts

QCEntranceQuantizePose:
        lda     #QC_ENTRANCE_0_TRAVEL / QC_ENTRANCE_STEPS
        ldx     a:qc_entrance_index
        beq     :+
        lda     #QC_ENTRANCE_1_TRAVEL / QC_ENTRANCE_STEPS
:       sta     a:qc_interval
        lda     a:qc_candidate
        cpx     #0
        bne     @Positive
        cmp     #0
        bpl     @Zero
        jsr     QCNegate
        bra     @BucketStart
@Positive:
        cmp     #0
        bmi     @Zero
@BucketStart:
        pha
        lda     a:qc_interval
        lsr
        clc
        adc     1,s
        plx
        ldx     #0
@Bucket:
        cmp     a:qc_interval
        bcc     @Pose
        sbc     a:qc_interval
        inx
        cpx     #QC_ENTRANCE_STEPS
        bcc     @Bucket
@Pose:
        stx     a:qc_pose
        rts
@Zero:
        stz     a:qc_pose
        rts

QCEntrance0Translations:
        .repeat QC_ENTRANCE_STEPS+1, I
        .word .loword(-I * QC_ENTRANCE_0_TRAVEL / (QC_ENTRANCE_STEPS * 4))
        .endrepeat
QCEntrance1Translations:
        .repeat QC_ENTRANCE_STEPS+1, I
        .word .loword(I * QC_ENTRANCE_1_TRAVEL / (QC_ENTRANCE_STEPS * 4))
        .endrepeat
.endif
