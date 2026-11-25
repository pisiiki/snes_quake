        ; The node address already identifies static thresholds and the cold range.
        cpx     #WALK_TRACE_AXIS_X_END
        bcs     @UpperAxes
        cpx     #PLAYABLE_WALK_HULL_AXIS_COLD_END
        bcs     @FastX
        lda     f:WalkHullData,x
        bpl     @SpillNode
        cmp     #WALK_TRACE_EXIT_GUARD
        beq     @ExitTail
        lda     f:WalkHullData+6,x
        sty     z:w_limit
        stx     z:w_node
        sta     z:w_plane
        jmp     @Moving
@FastX:
        WALK_STATIC_AXIAL 0, @FastFront, @FastBack, @FastSplit, 0
@UpperAxes:
        cpx     #PLAYABLE_WALK_HULL_AXIS_Z_END
        bcs     @FastY
        WALK_STATIC_AXIAL 4, @FastFront, @FastBack, @FastSplit, 0
@FastY:
        WALK_STATIC_AXIAL 2, @FastFront, @FastBack, @FastSplit, 0
