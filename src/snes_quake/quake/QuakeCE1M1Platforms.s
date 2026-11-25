; X is the platform word index (0 or 2). The powered lift and its button
; remain in the ordinary QuakeC VM. Both func_plats start at their low stop.
QCPlatformsTick:
        ldx     #0
        jsr     QCPlatformTick
        ldx     #2
QCPlatformTick:
        stx     a:qc_plat_slot
        lda     a:qc_plat_phase,x
        cmp     #1
        beq     @Move
        cmp     #3
        beq     @Move
        lda     a:qce+QC_ENTITY_STRIDE+QC_FIELD_HEALTH
        beq     @NoTouch
        bmi     @NoTouch
        txa
        beq     :+
        ldx     #6*12
        bra     @Touch
:       ldx     #5*12
@Touch: jsr     QCExitTouches
        ldx     a:qc_plat_slot
        bcc     @NoTouch
        lda     a:qc_plat_phase,x
        bne     @Occupied
        inc     a:qc_plat_phase,x
        stz     a:qc_exit_ages+16,x
        lda     #GAMEPLAY_PLAT_MOVE
        jsl     GameplayPlaySoundLong
        bra     @Move
@Occupied:
        lda     f:QCPlatformOccupiedWait,x
        sta     a:qc_plat_wait,x
@NoTouch:
        lda     a:qc_plat_phase,x
        beq     @Return
        dec     a:qc_plat_wait,x
        bne     @Return
        inc     a:qc_plat_phase,x
        stz     a:qc_exit_ages+16,x
        lda     #GAMEPLAY_PLAT_MOVE
        jsl     GameplayPlaySoundLong
@Return:
        rts
@Move:
        lda     a:qc_exit_ages+16,x
        inc
        cmp     f:QCExitDurations+16,x
        bne     @Step
        lda     a:qc_plat_phase,x
        cmp     #1
        beq     @TopStop
        lda     f:QCPlatformBottom,x
        bra     @Candidate
@TopStop:
        lda     #0
        bra     @Candidate
@Step:  ; At 150 units/sec each Q6 tick advances exactly 75 Q5 units.
        sta     a:qc_plat_next
        asl
        sta     a:qc_plat_delta
        asl
        asl
        clc
        adc     a:qc_plat_delta
        adc     a:qc_plat_next
        sta     a:qc_plat_delta
        lda     a:qc_plat_next
        .repeat 6
        asl
        .endrepeat
        clc
        adc     a:qc_plat_delta
        lsr
        bcc     :+
        inc
        and     #$fffe                  ; Q4 nearest, halfway to even.
:       ldy     a:qc_plat_phase,x
        cpy     #1
        bne     @Lower
        clc
        adc     f:QCPlatformBottom,x
        bra     @Candidate
@Lower: eor     #$ffff
        inc
@Candidate:
        ldx     a:qc_plat_slot
        sta     a:qc_plat_next
        sec
        sbc     f:quakec_platform_q4,x
        sta     a:qc_plat_delta
        jsr     QCPlatformCarry
        ldx     a:qc_plat_slot
        bcc     @Commit
        ; Stock plat_crush deals one point and heads for the opposite stop.
        lda     #64
.ifdef QC_ARMOR_COUNT
        jsl     ArmorEnvironmentDamage
.endif
        eor     #$ffff
        sec
        adc     a:qce+QC_ENTITY_STRIDE+QC_FIELD_HEALTH
        sta     a:qce+QC_ENTITY_STRIDE+QC_FIELD_HEALTH
        lda     #4
        sta     a:grunt_damage_flash
        ldx     a:qc_plat_slot
        lda     a:qc_plat_phase,x
        eor     #2
        sta     a:qc_plat_phase,x
        lda     f:QCExitDurations+16,x
        sec
        sbc     a:qc_exit_ages+16,x
        cmp     f:QCExitDurations+16,x
        bcc     :+
        dec
:       sta     a:qc_exit_ages+16,x
        lda     #GAMEPLAY_PLAT_MOVE
        jsl     GameplayPlaySoundLong
        rts
@Commit:
        lda     a:qc_plat_next
        sta     f:quakec_platform_q4,x
.ifdef PLAYABLE_E1M1_WALK_RESUME_BYTES
        jsl     MarkTraceResultCacheDirty
.endif
        sec
        sbc     f:QCPlatformBottom,x
        clc
        adc     #32
        .repeat 6
        lsr
        .endrepeat
        sta     a:qc_exit_poses+16,x     ; One rendered Q2 step per four Quake units.
        inc     a:qc_exit_updated
        inc     a:qc_exit_ages+16,x
        lda     a:qc_exit_ages+16,x
        cmp     f:QCExitDurations+16,x
        bne     @Moving
        lda     a:qc_plat_phase,x
        cmp     #1
        bne     @Bottom
        inc     a:qc_plat_phase,x
        bra     @AtStop
@Bottom:
        stz     a:qc_plat_phase,x
@AtStop:
        lda     f:QCPlatformWait,x
        sta     a:qc_plat_wait,x
        lda     #GAMEPLAY_PLAT_STOP
        jsl     GameplayPlaySoundLong
@Moving:
        rts

QCPlatformCarry:
        lda     a:qce+QC_ENTITY_STRIDE+QC_FIELD_HEALTH
        beq     @Skip
        bpl     @Bounds
@Skip:  clc
        rts
@Bounds:
        txa
        asl
        asl
        tax
.repeat 2,I
        lda     a:qc_exit_eye+I*2
        sec
        sbc     f:QCPlatformRider0+I*4,x
        cmp     f:QCPlatformRider0+I*4+2,x
        bcs     @Skip
.endrepeat
        stz     a:qc_plat_supported
        ldx     #4
@From:  lda     a:qc_exit_eye,x
        sta     a:w_from,x
        dex
        dex
        bpl     @From
        jsr     QCPlatformInvalidateImpacts
        ldx     a:qc_plat_slot
        lda     a:w_grounded
        beq     @Contact
        lda     a:qc_exit_eye+4
        sec
        sbc     f:quakec_platform_q4,x
        sec
        sbc     f:QCPlatformFloor,x
        clc
        adc     #4
        cmp     #9
        bcs     @Contact
        inc     a:qc_plat_supported
        lda     #.loword(-5)
        bra     @Trace
@Contact:
        ; Sweep the body backwards relative to the previous brush position.
        ; A hit identifies airborne and underside contacts via the same hull.
        lda     a:qc_plat_delta
        eor     #$ffff
        inc
@Trace:
        jsr     WalkTraceVertical
        bcc     @NoRider
        lda     a:w_enter
        and     #$e006
        cmp     #$a006
        bne     @NoRider
        lda     a:w_enter
        and     #$1ff8
        sec
        sbc     #WALK_EXIT_PLANE_FIRST
        bcc     @NoRider
        lsr
        lsr
        lsr
        tax
        lda     f:WalkHullData+WALK_TRACE_PLANES+WALK_EXIT_PLANE_TABLE,x
        and     #$ff
        lsr
        and     #$fffe
        sec
        sbc     #QC_E1M1_PLATFORM_FIRST*2
        cmp     a:qc_plat_slot
        beq     @Carry
@NoRider:
        clc
        rts
@Carry: lda     a:qc_plat_delta
        bpl     @Sweep
        lda     a:qc_plat_supported
        beq     @Sweep
        ldx     a:qc_plat_slot
        lda     a:qc_plat_next
        sta     f:quakec_platform_q4,x
.ifdef PLAYABLE_E1M1_WALK_RESUME_BYTES
        jsl     MarkTraceResultCacheDirty
.endif
        jsr     QCPlatformInvalidateImpacts
@Sweep: lda     a:qc_plat_delta
        jsr     WalkTraceVertical
        bcc     @Publish
        ldx     a:qc_plat_slot
        cpx     #4
        bne     @Rollback
        ; If a ledge clips the push, test the actual endpoint against the
        ; final hydraulic hull. A rider can step off onto the world floor.
        lda     a:qc_plat_next
        sta     f:quakec_platform_q4,x
.ifdef PLAYABLE_E1M1_WALK_RESUME_BYTES
        jsl     MarkTraceResultCacheDirty
.endif
        jsr     QCPlatformInvalidateImpacts
        ldx     #4
@Clipped:
        lda     a:w_result,x
        sta     a:w_from,x
        sta     a:w_to,x
        dex
        dex
        bpl     @Clipped
        jsr     WalkTrace
        bcc     @Publish
@Rollback:
        lda     a:qc_plat_next
        sec
        sbc     a:qc_plat_delta
        ldx     a:qc_plat_slot
        sta     f:quakec_platform_q4,x
.ifdef PLAYABLE_E1M1_WALK_RESUME_BYTES
        jsl     MarkTraceResultCacheDirty
.endif
        jsr     QCPlatformInvalidateImpacts
        sec
        rts
@Publish:
QCPlatformPublish:
        stz     a:w_pending
        ldx     #4
@Axis:  lda     a:w_to,x
        sta     a:w_pending_xyz,x
        sta     a:w_from,x
        dex
        dex
        bpl     @Axis
        lda     #1
        sta     a:w_pending
        clc
        rts

QCDoorContainsPlayerLong:
        jsr     QCDoorContainsPlayer
        rtl
QCDoorPushTrace:
        jsr     WalkTraceVertical
        rtl
QCDoorPublishRider:
        jsr     QCPlatformPublish
        rtl

        .pushseg
        .segment "BSP_CPU_LIFT_COLLISION"

; The button-operated lift tests the candidate box before committing its pose.
; A body met by its upper face should move with the deck if the world allows it.
QCDoorCarryPlayer:
@Check: lda     f:video_tick
        sta     a:qc_collision_tick
        lda     a:qc_pose
        jsl     QCDoorContainsPlayerLong
        php
        lda     f:video_tick
        cmp     a:qc_collision_tick
        beq     @Stable
        plp
        bra     @Check
@Stable:
        plp
        bcs     @Contact
        rtl
@Contact:
        lda     a:w_pending
        beq     @Live
        ldx     #4
@Pending:
        lda     a:w_pending_xyz,x
        sta     a:w_from,x
        dex
        dex
        bpl     @Pending
        bra     @Eye
@Live:  lda     f:camera_x
        sta     a:w_from
        lda     f:camera_y
        sta     a:w_from+2
        lda     f:camera_z
        sta     a:w_from+4
@Eye:   lda     f:quakec_door_pose
        asl
        tax
        lda     f:QCDoorTranslations,x
        clc
        adc     #.loword((QC_DOOR_MAX_Z + QC_EYE_HEIGHT - BSP_WORLD_ORIGIN_Z)*16)
        sta     a:qc_plat_delta
        lda     a:w_from+4
        sec
        sbc     a:qc_plat_delta
        bmi     @Blocked
        lda     a:qc_pose
        asl
        tax
        lda     f:QCDoorTranslations,x
        clc
        adc     #.loword((QC_DOOR_MAX_Z + QC_EYE_HEIGHT - BSP_WORLD_ORIGIN_Z)*16)
        sta     a:qc_plat_next
        sec
        sbc     a:qc_plat_delta
        jsl     QCDoorPushTrace
        lda     a:w_result+4
        sec
        sbc     a:qc_plat_next
        bmi     @Blocked
        lda     a:w_result+4
        sta     a:w_to+4
        stz     a:w_support_valid
        jml     QCDoorPublishRider
@Blocked:
        sec
        rtl
        .popseg

QCPlatformInvalidateImpacts:
.ifdef WALK_IMPACT_CACHE_BYTES
.repeat WALK_IMPACT_CACHE_BYTES / WALK_IMPACT_CACHE_STRIDE, slot
        stz     a:w_impact_cache+slot*WALK_IMPACT_CACHE_STRIDE+26
.endrepeat
.endif
        rts
