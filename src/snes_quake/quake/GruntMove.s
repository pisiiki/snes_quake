; Engine movement for the stock grunt's QuakeC walkmove and movetogoal.
; Navigation distances are Q6. Collision sweeps reuse the player's Q4 hull 1.
GRUNT_STEP = 18*16
GRUNT_NO_DIRECTION = $ffff

; Keep grounded riders attached to the stock secret lift as its
; collision pose changes. Translations are Q4, while edicts use Q3.
GruntRideLift:
.if .defined(QC_BASIC_GAMEPLAY)
        rts

.else
        lda     f:quakec_door_pose
        cmp     a:qc_pose
        bne     :+
        rts
:       asl
        tax
        lda     f:QCDoorTranslations,x
        cmp     #$8000
        ror
        sta     a:gr_lift_delta
        clc
        adc     #.loword((QC_DOOR_MAX_Z-BSP_WORLD_ORIGIN_Z+22)*8)
        sta     a:gr_lift_top
        lda     a:qc_pose
        asl
        tax
        lda     f:QCDoorTranslations,x
        cmp     #$8000
        ror
        sec
        sbc     a:gr_lift_delta
        sta     a:gr_lift_delta
        ldx     #QC_GRUNT
@Rider:
        lda     a:qce+QC_FIELD_ORIGIN+4,x
        sec
        sbc     a:gr_lift_top
        inc
        cmp     #3
        bcs     @Next
        lda     a:qce+QC_FIELD_ORIGIN,x
        sec
        sbc     #.loword((QC_DOOR_MIN_X-BSP_WORLD_ORIGIN_X)*8)
        cmp     #(QC_DOOR_MAX_X-QC_DOOR_MIN_X)*8
        bcs     @Next
        lda     a:qce+QC_FIELD_ORIGIN+2,x
        sec
        sbc     #.loword((QC_DOOR_MIN_Y-BSP_WORLD_ORIGIN_Y)*8)
        cmp     #(QC_DOOR_MAX_Y-QC_DOOR_MIN_Y)*8
        bcs     @Next
        lda     a:qce+QC_FIELD_ORIGIN+4,x
        clc
        adc     a:gr_lift_delta
        sta     a:qce+QC_FIELD_ORIGIN+4,x
        lda     a:qce+QC_FIELD_ABSMIN+4,x
        clc
        adc     a:gr_lift_delta
        sta     a:qce+QC_FIELD_ABSMIN+4,x
        lda     a:qce+QC_FIELD_ABSMAX+4,x
        clc
        adc     a:gr_lift_delta
        sta     a:qce+QC_FIELD_ABSMAX+4,x
@Next:  txa
        clc
        adc     #QC_ENTITY_STRIDE
        tax
        cmp     #QC_GRUNT_DROP
        bcc     @Rider
        rts

.endif
GruntWalkMove:
        lda     a:qcg+14
        sta     a:gr_move_distance
        lda     a:qcg+8
        jsr     GruntTryMove
        lda     #0
        bcc     :+
        lda     #64
:       sta     a:qcg+2
        rts

GruntMoveToGoal:
        GRUNT_FIELD lda, QC_FIELD_GOALENTITY
.ifdef QC_PATROL_TOKEN
        bpl     :+
        sta     a:gr_goal_actor
        and     #$7fff
        tax
        lda     a:qcg+8
        sta     a:gr_move_distance
        lda     f:GruntCorners,x
        sec
        GRUNT_FIELD sbc, QC_FIELD_ORIGIN
        sta     a:gr_goal_x
        lda     f:GruntCorners+2,x
        sec
        GRUNT_FIELD sbc, QC_FIELD_ORIGIN+2
        sta     a:gr_goal_y
        bra     @Pursue
:
.endif
        beq     @NoGoal
        cmp     #QC_GRUNT_DROP
        bcc     :+
@NoGoal:
        rts
:       sta     a:gr_goal_actor
        tax
        lda     a:qcg+8
        sta     a:gr_move_distance
        lsr
        lsr
        lsr
        clc
        adc     #34*8                  ; Two 16-unit radii and link padding.
        sta     a:gr_close_xy
        lda     a:qce+QC_FIELD_ORIGIN,x
        sec
        GRUNT_FIELD sbc, QC_FIELD_ORIGIN
        sta     a:gr_goal_x
        jsr     QCAbs
        cmp     a:gr_close_xy
        bcc     :+
        bne     @Pursue
:       lda     a:qce+QC_FIELD_ORIGIN+2,x
        sec
        GRUNT_FIELD sbc, QC_FIELD_ORIGIN+2
        jsr     QCAbs
        cmp     a:gr_close_xy
        bcc     :+
        bne     @Pursue
:       lda     a:qce+QC_FIELD_ORIGIN+4,x
        sec
        GRUNT_FIELD sbc, QC_FIELD_ORIGIN+4
        bpl     @Above
        jsr     QCNegate
        cpx     #QC_ENTITY_STRIDE
        bne     @Above
        sec
        sbc     #24*8                  ; Player max Z 32 + grunt min Z 24.
        bra     @CheckZ
@Above:
        sec
        sbc     #32*8                  ; Grunt max Z 40 + player min Z 24.
@CheckZ:
        bmi     @Close
        cmp     a:gr_close_xy
        bcc     @Close
        beq     @Close
@Pursue:
        GRUNT_FIELD lda, QC_FIELD_IDEAL_YAW
        jsr     GruntAngleIndex
        .repeat 5
        lsr
        .endrepeat
        sta     a:gr_old_direction
        eor     #4
        sta     a:gr_reverse
        jsr     GruntMoveRandom
        and     #3
        cmp     #1
        beq     @Reroute
        GRUNT_FIELD lda, QC_FIELD_IDEAL_YAW
        jsr     GruntStepDirection
        bcc     @Reroute
@Close: rts
@Reroute:
        jmp     GruntNewChaseDirection

; Try the target diagonal and preferred axes, continue the old heading, then
; scan the other octants. The turnaround is the final choice.
GruntNewChaseDirection:
        ldx     a:gr_goal_actor
.ifdef QC_PATROL_TOKEN
        bmi     @PatrolGoal
.endif
        lda     a:qce+QC_FIELD_ORIGIN+2,x
        sec
        GRUNT_FIELD sbc, QC_FIELD_ORIGIN+2
        sta     a:gr_goal_y
@PatrolGoal:
        lda     a:gr_goal_x
        jsr     GruntChaseAxis
        sta     a:gr_nav_x
        lda     a:gr_goal_y
        jsr     GruntChaseAxis
        bmi     :+
        clc
        adc     #2
:       sta     a:gr_nav_y
        ora     a:gr_nav_x
        bmi     @AxisOrder
        lda     a:gr_nav_x
        beq     @East
        lda     a:gr_nav_y
        inc                             ; NW 3, or SW 5.
        and     #7
        cmp     #7
        bne     @TryDiagonal
        lda     #5
        bra     @TryDiagonal
@East:
        lda     a:gr_nav_y
        dec                             ; NE 1, or SE 7.
        cmp     #5
        bne     @TryDiagonal
        lda     #7
@TryDiagonal:
        jsr     GruntTryOctant
        bcc     @AxisOrder
        rts
@AxisOrder:
        jsr     GruntMoveRandom
        lsr
        bcs     @Swap
        lda     a:gr_goal_y
        jsr     QCAbs
        sta     a:gr_nav_abs_y
        lda     a:gr_goal_x
        jsr     QCAbs
        cmp     a:gr_nav_abs_y
        bcs     @Axes
@Swap:
        ldx     a:gr_nav_x
        lda     a:gr_nav_y
        stx     a:gr_nav_y
        sta     a:gr_nav_x
@Axes:
        lda     a:gr_nav_x
        jsr     GruntTryOctant
        bcs     @Done
        lda     a:gr_nav_y
        jsr     GruntTryOctant
        bcs     @Done
        lda     a:gr_old_direction
        jsr     GruntTryOctant
        bcs     @Done
        jsr     GruntMoveRandom
        and     #1
        beq     @ScanUp
        lda     #7
        sta     a:gr_nav_scan
@Down:
        lda     a:gr_nav_scan
        jsr     GruntTryOctant
        bcs     @Done
        dec     a:gr_nav_scan
        bpl     @Down
        bra     @Reverse
@ScanUp:
        stz     a:gr_nav_scan
@Up:
        lda     a:gr_nav_scan
        jsr     GruntTryOctant
        bcs     @Done
        inc     a:gr_nav_scan
        lda     a:gr_nav_scan
        cmp     #8
        bcc     @Up
@Reverse:
        lda     a:gr_reverse
        jsr     GruntOctantYaw
        jsr     GruntStepDirection
        bcs     @Done
        lda     a:gr_old_direction
        jsr     GruntOctantYaw
        GRUNT_FIELD sta, QC_FIELD_IDEAL_YAW
@Done:  rts

GruntChaseAxis:
        bmi     @Negative
        cmp     #10*8+1
        bcc     @None
        lda     #0
        rts
@Negative:
        cmp     #.loword(-10*8)
        bcs     @None
        lda     #4
        rts
@None:  lda     #GRUNT_NO_DIRECTION
        rts

GruntTryOctant:
        cmp     #GRUNT_NO_DIRECTION
        beq     @Skip
        cmp     a:gr_reverse
        beq     @Skip
        jsr     GruntOctantYaw
        bra     GruntStepDirection
@Skip:  clc
        rts

GruntOctantYaw:
        asl
        tax
        lda     f:GruntChaseHeadings,x
        rts

.ifdef PLAYABLE_E1M1_STATEMENT_BATCH
        .pushseg
        .segment "RODATA"
.endif
GruntChaseHeadings:
        .word 0, 45*64, 90*64, 135*64, 180*64, 225*64, 270*64, 315*64
.ifdef PLAYABLE_E1M1_STATEMENT_BATCH
        .popseg
.endif

GruntMoveRandom:
        lda     a:gr_nav_random
        bne     :+
        lda     f:QC_RNG_TICK
        ora     #1
:       lsr
        bcc     :+
        eor     #$b400
:       sta     a:gr_nav_random
        xba
        rts

GruntStepDirection:
        GRUNT_FIELD sta, QC_FIELD_IDEAL_YAW
        jsr     GruntChangeYaw
        GRUNT_FIELD lda, QC_FIELD_ANGLES+2
        sec
        GRUNT_FIELD sbc, QC_FIELD_IDEAL_YAW
        bpl     :+
        clc
        adc     #360*64
:       cmp     #45*64+1
        bcc     @Step
        cmp     #315*64
        bcs     @Step
        ; Test the route while turning, but commit only once facing it.
        lda     #1
        bra     @Try
@Step:  lda     #0
@Try:   sta     a:gr_turn_only
        GRUNT_FIELD lda, QC_FIELD_IDEAL_YAW
        jsr     GruntSweepMove
        rts

GruntTryMove:
        stz     a:gr_turn_only
GruntSweepMove:
        pha
        GRUNT_FIELD lda, QC_FIELD_FLAGS
        bit     #512                    ; FL_ONGROUND
        bne     :+
        pla
        clc
        rts
:       pla
        ; Stock callers may pass yaw minus 90 or yaw plus 180. The
        ; positive range can cross the 16-bit sign bit, up to 540 degrees.
        cmp     #540*64
        bcc     :+
        adc     #360*64-1
:
        cmp     #360*64
        bcc     :+
        sbc     #360*64
:       jsr     GruntAngleIndex
        sta     a:gr_move_angle
        ldy     a:qcg+QC_GLOBAL_SELF
        .repeat 3, I
        lda     a:qce+QC_FIELD_ORIGIN+2*I,y
        asl
        sta     a:gr_move_base+2*I
        sta     a:w_from+2*I
        .endrepeat
        ldx     a:gr_move_angle
        lda     f:CameraAngleCos,x
        jsr     GruntMoveComponent
        clc
        adc     a:w_from
        and     #$fffe
        sta     a:gr_move_target
        ldx     a:gr_move_angle
        lda     f:CameraAngleSin,x
        jsr     GruntMoveComponent
        clc
        adc     a:w_from+2
        and     #$fffe
        sta     a:gr_move_target+2
        lda     a:gr_move_base+4
        sta     a:w_from+4
        jsr     GruntSweepAcross
        bcc     @Drop
        ; Rise at the old XY before sweeping across a step. A low ceiling
        ; limits the rise; the across sweep still must be entirely clear.
        lda     a:gr_move_base
        sta     a:w_to
        lda     a:gr_move_base+2
        sta     a:w_to+2
        lda     a:gr_move_base+4
        clc
        adc     #GRUNT_STEP
        sta     a:w_to+4
        jsr     WalkTrace
        lda     a:w_result+4
        cmp     a:gr_move_base+4
        beq     @Blocked
        sta     a:w_from+4
        jsr     GruntSweepAcross
        bcs     @Blocked
@Drop:
        lda     a:gr_move_target
        sta     a:w_from
        lda     a:gr_move_target+2
        sta     a:w_from+2
        lda     a:gr_move_base+4
        sec
        sbc     #GRUNT_STEP
        sta     a:w_to+4
        jsr     WalkTrace
        bcc     @Unsupported
        lda     a:w_normal+4
        bmi     @Unsupported
        cmp     #WALK_FLOOR_Z
        bcc     @Unsupported
        lda     a:w_result+4
        sta     a:gr_move_target+4
        jsr     GruntClearOfPlayer
        bcc     @Blocked
        jsr     GruntCheckBottom
        bcc     @Unsupported
        jsr     GruntClearOfActors
        bcc     @Blocked
        lda     a:gr_turn_only
        bne     @Accepted
        jsr     GruntCommitMove
@Accepted:
        sec
        rts
@Unsupported:
        inc     a:grunt_unsupported_moves
@Blocked:
        inc     a:grunt_blocked_moves
        clc
        rts

GruntMoveComponent:
        jsr     ShotgunSignedByte
        ldx     a:gr_move_distance
        stx     z:qc_rhs
        jsr     QCMulRound
        clc
        adc     #2
        cmp     #$8000
        ror
        cmp     #$8000
        ror
        rts

GruntSweepAcross:
        lda     a:gr_move_target
        sta     a:w_to
        lda     a:gr_move_target+2
        sta     a:w_to+2
        lda     a:w_from+4
        sta     a:w_to+4
        jmp     WalkTrace

GruntClearOfPlayer:
        lda     a:shot_player+QC_FIELD_SOLID
        beq     @Clear
.ifdef QC_DOG_FIRST
        ldy     a:qcg+QC_GLOBAL_SELF
.endif
        ldx     #2
@Axis:
        lda     a:shot_player+QC_FIELD_ORIGIN,x
        asl
        sec
        sbc     a:gr_move_target,x
        jsr     QCAbs
.ifdef QC_DOG_FIRST
        cpy     #QC_DOG_FIRST
        bcc     :+
        cmp     #48*16
        bra     :++
:
.endif
        cmp     #32*16
:
        bcs     @Clear
        dex
        dex
        bpl     @Axis
        lda     a:shot_player+QC_FIELD_ORIGIN+4
        asl
        sec
        sbc     a:gr_move_target+4
        bmi     @Below
        cmp     #64*16
        rts
@Below:
        jsr     QCNegate
        cmp     #56*16
        rts
@Clear: sec
        rts

GruntClearOfActors:
.if QC_GRUNT_COUNT = 0
        sec
        rts

.else
        ldx     #QC_GRUNT
@Check:
        cpx     a:qcg+QC_GLOBAL_SELF
        beq     @Next
        lda     a:qce+QC_FIELD_SOLID,x
        beq     @Next
        .repeat 3, I
        lda     a:qce+QC_FIELD_ORIGIN+2*I,x
        sec
        sbc     a:gr_move_q3+2*I
.ifdef PLAYABLE_E1M1_ACTOR_BOUNDS
        ; Bias the strict signed interval into one unsigned comparison.
        clc
        adc     #((32+32*(I=2))*8-1)
        cmp     #((32+32*(I=2))*16-1)
.else
        jsr     QCAbs
        cmp     #((32+32*(I=2))*8)
.endif
        bcs     @Next
        .endrepeat
        clc
        rts
@Next:  txa
        clc
        adc     #QC_ENTITY_STRIDE
        tax
        cmp     #QC_GRUNT_DROP
        bcc     @Check
        sec
        rts

.endif
; Check the stock center and footprint corners against the point BSP.
; All corners must find ground within 18 units below the center's support.
GruntCheckBottom:
        ldx     #4
@Convert:
        lda     a:gr_move_target,x
        inc
        cmp     #$8000
        ror
        sta     a:gr_move_q3,x
        dex
        dex
        bpl     @Convert
        lda     a:gr_move_q3+4
        sec
        sbc     #24*8
        sta     a:gr_foot_z
.ifdef PLAYABLE_E1M1_FOOTING
        stz     a:gr_foot_index
        jsl     ShotSupportCertificate
        bcc     @Foot
        rts
.else
        ldx     #0
        stx     a:gr_foot_index
.endif
@Foot:
        ldx     a:gr_foot_index
        lda     f:GruntFootOffsets,x
.ifdef QC_DOG_FIRST
        ldy     a:qcg+QC_GLOBAL_SELF
        cpy     #QC_DOG_FIRST
        bcc     :+
        asl
:
.endif
        clc
        adc     a:gr_move_q3
        sta     a:w_from
        sta     a:w_to
        lda     f:GruntFootOffsets+2,x
.ifdef QC_DOG_FIRST
        cpy     #QC_DOG_FIRST
        bcc     :+
        asl
:
.endif
        clc
        adc     a:gr_move_q3+2
        sta     a:w_from+2
        sta     a:w_to+2
        lda     a:gr_foot_z
        sta     a:w_from+4
        sec
        sbc     #36*8
        sta     a:w_to+4
        jsr     ShotHull::WalkTrace
        bcc     @Unsupported
        lda     a:gr_foot_index
        bne     @Corner
        lda     a:w_result+4
        sec
        sbc     #18*8
        sta     a:gr_min_support
        bra     @Next
@Corner:
        lda     a:w_result+4
        sec
        sbc     a:gr_min_support
        bmi     @Unsupported
@Next:
        lda     a:gr_foot_index
        clc
        adc     #4
        sta     a:gr_foot_index
        cmp     #20
        bcc     @Foot
        sec
        rts
@Unsupported:
        clc
        rts

GruntFootOffsets:
        .word 0, 0, .loword(-128), .loword(-128), .loword(-128), 128
        .word 128, .loword(-128), 128, 128

GruntCommitMove:
        inc     a:grunt_moves
        lda     a:qcg+QC_GLOBAL_SELF
        jsr     GruntCounterIndex
        inc     a:gr_actor_moves,x
        lda     a:gr_move_target+4
        sec
        sbc     a:gr_move_base+4
        cmp     #16
        bcc     :+
        bmi     :+
        inc     a:grunt_steps_up
:
GruntStoreOrigin:
        ldy     a:qcg+QC_GLOBAL_SELF
        .repeat 3, I
        lda     a:gr_move_q3+2*I
        sta     a:qce+QC_FIELD_ORIGIN+2*I,y
        clc
        adc     a:qce+QC_FIELD_MINS+2*I,y
        sec
        sbc     #8
        sta     a:qce+QC_FIELD_ABSMIN+2*I,y
        lda     a:gr_move_q3+2*I
        clc
        adc     a:qce+QC_FIELD_MAXS+2*I,y
        clc
        adc     #8
        sta     a:qce+QC_FIELD_ABSMAX+2*I,y
        .endrepeat
.ifdef QC_PATROL_TOKEN
        lda     a:qce+QC_FIELD_ENEMY,y
        bne     @Done
        lda     a:qce+QC_FIELD_MOVETARGET,y
        bpl     @Done
        jmp     GruntTouchCorner
@Done:
.endif
        rts

.ifdef QC_PATROL_TOKEN
.include "quake/GruntPatrol.s"
.endif
