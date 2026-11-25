.if .defined(PLAYABLE_E1M1_WALK_RESUME_BYTES) .and !.defined(POINT_SHOT)
        jsl     WalkTraceQ4Cached
        rts
WalkTraceQ4UncachedFar:
        jsr     WalkTraceUncached
        rtl
WalkTraceUncached:
.endif
