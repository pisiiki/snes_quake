; Composed E1M1 marks each collision-pose store. The source-size and
; legacy layouts still compare the four ordinary entrance pose words.
.ifdef PLAYABLE_E1M1_WALK_RESUME_BYTES
        stz     a:qc_exit_collision_dirty
.else
        stz     a:w_entrance_probe_owner
.ifdef QC_EXIT_MOVER_COUNT
        lda     a:qc_exit_collision_dirty
        beq     :+
        stz     a:qc_exit_collision_dirty
        bra     @Invalidate
:
.endif
        lda     f:quakec_door_pose
        cmp     a:point_trace_cache_door
        bne     @Invalidate
        lda     f:quakec_button_pose
        cmp     a:point_trace_cache_button
        bne     @Invalidate
        lda     f:quakec_entrance_pose
        cmp     a:point_trace_cache_entrance0
        bne     @Invalidate
        lda     f:quakec_entrance_pose+2
        cmp     a:point_trace_cache_entrance1
        beq     @Ready
@Invalidate:
.endif
.ifdef PLAYABLE_POINT_MOVING_RANK
        jsl     ::ShotRefreshMovingRanks
.endif
.ifndef PLAYABLE_E1M1_WALK_RESUME_BYTES
        lda     f:quakec_door_pose
        sta     a:point_trace_cache_door
        lda     f:quakec_button_pose
        sta     a:point_trace_cache_button
        lda     f:quakec_entrance_pose
        sta     a:point_trace_cache_entrance0
        lda     f:quakec_entrance_pose+2
        sta     a:point_trace_cache_entrance1
.endif
        ldx     #POINT_TRACE_CACHE_BYTES-32
@Clear:
        stz     a:point_trace_cache,x
        txa
        sec
        sbc     #32
        tax
        bpl     @Clear
        ldx     #POINT_MOVING_CACHE_BYTES-8
@ClearMoving:
        stz     a:point_moving_cache,x
        txa
        sec
        sbc     #8
        tax
        bpl     @ClearMoving
.ifndef PLAYABLE_E1M1_WALK_RESUME_BYTES
@Ready:
.endif
