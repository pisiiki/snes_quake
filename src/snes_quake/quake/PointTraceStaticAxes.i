.assert .defined(WALK_TRACE_EXIT_GUARD) .and !WALK_CHECK_AXIAL_OWNER, error, "Point axis ranges require packed E1M1 movers"
        cpx     #WALK_TRACE_STATIC_Z_END
        bcs     @ReadTraceTag
        WALK_STATIC_AXIAL 4, @FastFront, @FastBack, @FastSplit, 0
@ReadTraceTag:
.if WALK_POINT_AXES
        ; The remaining static axes need no plane tag load.
        cpx     #::PLAYABLE_SHOT_HULL_STATIC_Y_END
        bcs     @PointCold
        cpx     #::PLAYABLE_SHOT_HULL_STATIC_X_END
        bcs     @FastY
        WALK_STATIC_AXIAL 0, @FastFront, @FastBack, @FastSplit, 0
@PointCold:
        lda     f:WalkHullData,x
        bpl     @SpillNode
.else
        lda     f:WalkHullData,x
        bpl     @LowTag
        cmp     #$A000
        bcc     @FastY
.endif
