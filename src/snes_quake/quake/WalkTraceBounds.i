; Point occupancy and whole-ray collision bounds.
.if !.defined(POINT_SHOT)
.if !.defined(QC_BASIC_GAMEPLAY)
; Foreground only. A=candidate pose, X=entrance leaf byte offset (0 or2).
; Copy the effective player eye and query only that original model's hull.
; Does not mutate published poses. Clobbers A/X/Y and common walk scratch.
WalkEntranceContainsPlayer:
        stz     a:w_entrance_probe_owner
        cmp     #QC_ENTRANCE_STEPS+1
        bcc     :+
        clc
        rts
:       sta     a:w_entrance_probe_pose
        cpx     #0
        beq     @First
        cpx     #2
        beq     @Second
        clc
        rts
@First:
        lda     #2
        sta     a:w_entrance_probe_owner
  .ifdef WALK_TRACE_AXIS_X_END
        lda     #PLAYABLE_WALK_HULL_ENTRANCE_0_NODE_BEGIN
  .else
        lda     #WALK_ENTRANCE_0_NODE_BEGIN/6*WALK_NODE_BYTES
  .endif
        sta     z:w_lo
  .ifdef WALK_TRACE_AXIS_X_END
        lda     #PLAYABLE_WALK_HULL_ENTRANCE_0_NODE_END
  .else
        lda     #WALK_ENTRANCE_0_NODE_END/6*WALK_NODE_BYTES
  .endif
        sta     z:w_hi
  .ifdef WALK_TRACE_AXIS_X_END
        lda     #PLAYABLE_WALK_HULL_ENTRANCE_0_ROOT
  .else
        lda     #WALK_ENTRANCE_0_ROOT/6*WALK_NODE_BYTES
  .endif
        bra     @CopyPoint
@Second:
        lda     #4
        sta     a:w_entrance_probe_owner
  .ifdef WALK_TRACE_AXIS_X_END
        lda     #PLAYABLE_WALK_HULL_ENTRANCE_1_NODE_BEGIN
  .else
        lda     #WALK_ENTRANCE_1_NODE_BEGIN/6*WALK_NODE_BYTES
  .endif
        sta     z:w_lo
  .ifdef WALK_TRACE_AXIS_X_END
        lda     #PLAYABLE_WALK_HULL_ENTRANCE_1_NODE_END
  .else
        lda     #WALK_ENTRANCE_1_NODE_END/6*WALK_NODE_BYTES
  .endif
        sta     z:w_hi
  .ifdef WALK_TRACE_AXIS_X_END
        lda     #PLAYABLE_WALK_HULL_ENTRANCE_1_ROOT
  .else
        lda     #WALK_ENTRANCE_1_ROOT/6*WALK_NODE_BYTES
  .endif
@CopyPoint:
        sta     z:w_node
        lda     #WALK_MAX_NODES_PER_TRACE
        sta     z:w_limit
        ldx     #4
        lda     a:w_pending
        beq     @Live
@Pending:
        lda     a:w_pending_xyz,x
        sta     a:w_result,x
        dex
        dex
        bpl     @Pending
        bra     @Query
@Live:
        lda     f:camera_x,x
        sta     a:w_result,x
        dex
        dex
        bpl     @Live
@Query:
        ldx     z:w_node
        jmp     WalkPointSolidVisit
.endif
WalkPointSolid:
.if !.defined(QC_BASIC_GAMEPLAY)
        stz     a:w_entrance_probe_owner
.endif
        ldx     #WALK_TRACE_ROOT
.if .defined(WALK_EXPLOBOX_ROOT) .and !.defined(POINT_SHOT)
        lda     a:qce+QC_EXPLOBOX+QC_FIELD_SOLID
        beq     :+
  .ifdef WALK_TRACE_AXIS_X_END
        ldx     #PLAYABLE_WALK_HULL_EXPLOBOX_ROOT
  .else
        ldx     #WALK_EXPLOBOX_ROOT/6*WALK_NODE_BYTES
  .endif
:
.endif
WalkPointSolidVisit:
        txa
        bpl     :+
        jmp     WalkPointSolidTerminal
:
.if !.defined(QC_BASIC_GAMEPLAY)
        lda     a:w_entrance_probe_owner
        beq     @Unbounded
        dec     z:w_limit
        bne     :+
        jmp     WalkPointSolidInside
:       txa
        cmp     z:w_lo
        bcs     :+
        jmp     WalkPointSolidOutside
:       cmp     z:w_hi
        bcc     @Unbounded
        jmp     WalkPointSolidOutside
@Unbounded:
.endif
        lda     f:WalkHullData,x
.if WALK_REGISTER_TRACE
  .if WALK_CHECK_AXIAL_OWNER
        bit     #6
        bne     @LoadPlane
  .endif
        cmp     #$6000
        bcc     @LoadPlane
        cmp     #$c000
  .ifdef WALK_TRACE_EXIT_GUARD
        bcc     :+
        cmp     #WALK_TRACE_EXIT_GUARD
        beq     @ExitTail
        lda     f:WalkHullData+6,x
        bra     @LoadPlane
:
  .else
    .ifdef QC_E1M2_GROUP_COUNT
        bcc     :+
        cmp     #$e000
        bne     @LoadPlane
        lda     f:WalkHullData+6,x
        bra     @LoadPlane
:
    .else
        bcs     @LoadPlane
    .endif
  .endif
        ldy     #0
        cmp     #$8000
        bcc     @StaticAxial
        ldy     #2
        cmp     #$a000
        bcc     @StaticAxial
        ldy     #4
@StaticAxial:
        ; The packed threshold uses reverse signed order. Equality belongs
        ; to the front child, as it does in the full plane evaluator.
        lda     a:w_result,y
        eor     #$7fff
        cmp     f:WalkHullData+6,x
        bcc     @Front
        beq     @Front
        bra     @Back
  .ifdef WALK_TRACE_EXIT_GUARD
@ExitTail:
        ldy     #2
        bra     @StaticAxial
  .endif
@LoadPlane:
.endif
        stx     z:w_node
        sta     z:w_plane
        jsr     WalkLoadPlane
        ldy     #12
        jsr     WalkPlaneDistance
        ldx     z:w_node
        lda     z:w_eval_high
        bmi     @Back
.if WALK_REGISTER_TRACE
@Front:
.endif
        lda     f:WalkHullData+2,x
        tax
        jmp     WalkPointSolidVisit
@Back:
        lda     f:WalkHullData+4,x
        tax
        jmp     WalkPointSolidVisit
WalkPointSolidTerminal:
        cmp     #$fffe
        bne     WalkPointSolidOutside
WalkPointSolidInside:
.if !.defined(QC_BASIC_GAMEPLAY)
        stz     a:w_entrance_probe_owner
.endif
        sec
        rts
WalkPointSolidOutside:
.if !.defined(QC_BASIC_GAMEPLAY)
        stz     a:w_entrance_probe_owner
.endif
        clc
        rts
.endif

.ifdef WALK_TRACE_EXIT_GUARD
; A trace within one Y band can miss every exit hull on X alone. Crossing
; bands keeps the original traversal. Keep X and Y for the caller.
.macro WALK_X_BUCKET_POSSIBLE bounds, mask, shifts
        .local Possible, Inside, Outside
        lda     a:w_from+2
        eor     a:w_to+2
        and     #mask
        bne     Possible
        phx
        lda     a:w_from+2
        xba
        and     #(mask >> 8)
        .repeat shifts
        lsr
        .endrepeat
        tax
        lda     f:WalkHullData+bounds,x
        cmp     w_biased_from_fast
        bcc     Outside
        lda     f:WalkHullData+bounds+2,x
        cmp     w_biased_to_fast
        beq     Inside
        bcs     Outside
Inside:
        plx
Possible:
        sec
        rts
Outside:
        plx
        clc
        rts
.endmacro

WalkExitBucketPossible:
  .ifdef POINT_SHOT
        WALK_X_BUCKET_POSSIBLE WALK_TRACE_EXIT_BOUNDS, WALK_TRACE_EXIT_BUCKET_MASK, 0
  .else
        WALK_X_BUCKET_POSSIBLE WALK_TRACE_EXIT_BOUNDS, WALK_TRACE_EXIT_BUCKET_MASK, 1
  .endif

  .ifdef WALK_TRACE_SECRET_BOUNDS
WalkSecretBucketPossible:
    .ifdef POINT_SHOT
        WALK_X_BUCKET_POSSIBLE WALK_TRACE_SECRET_BOUNDS, $F800, 1
    .else
        WALK_X_BUCKET_POSSIBLE WALK_TRACE_SECRET_BOUNDS, $F000, 2
    .endif
  .endif
.delmacro WALK_X_BUCKET_POSSIBLE
.endif
