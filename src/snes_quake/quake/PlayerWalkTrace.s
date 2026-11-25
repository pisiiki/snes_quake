; Sweep a Q4 eye point through the packed player hull. The packer rebases
; original body-space planes and chains the two moving brush hulls after
; world EMPTY leaves. Far intervals use a bounded WRAM stack.
WALK_T_ONE = 4096
WALK_NO_PLANE = $ffff
WALK_PLANE_OFFSET = $1ff8
.ifdef POINT_SHOT
WALK_TRACE_EXTENDED_PLANES = .defined(SHOT_HULL_EXTENDED_PLANES)
.else
WALK_TRACE_EXTENDED_PLANES = .defined(WALK_HULL_EXTENDED_PLANES)
.endif
.if .defined(QC_EXIT_MOVER_COUNT) .and !.defined(QC_E1M2_GROUP_COUNT)
  .ifdef POINT_SHOT
WALK_TRACE_EXIT_PLANE_FIRST = SHOT_EXIT_PLANE_FIRST
WALK_TRACE_EXIT_PLANE_TABLE = SHOT_EXIT_PLANE_TABLE
  .else
WALK_TRACE_EXIT_PLANE_FIRST = WALK_EXIT_PLANE_FIRST
WALK_TRACE_EXIT_PLANE_TABLE = WALK_EXIT_PLANE_TABLE
  .endif
.endif
.if WALK_TRACE_EXTENDED_PLANES
        .assert .defined(QC_BASIC_GAMEPLAY), error, "Extended planes require bit 1 to be free of moving-hull ownership"
.endif
.if !.definedmacro(WALK_LOAD_PLANE_OFFSET)
.macro WALK_LOAD_PLANE_OFFSET extended
        lda     z:w_plane
  .if extended
        bit     #2
        beq     :+
        and     #WALK_PLANE_OFFSET
        ora     #$2000
        bra     :++
:
        and     #WALK_PLANE_OFFSET
:
  .else
        and     #WALK_PLANE_OFFSET
  .endif
        tax
.endmacro
.endif
.if !.definedmacro(WALK_LOAD_PLANE_DISTANCE)
.macro WALK_LOAD_PLANE_DISTANCE
        lda     f:WalkHullData+WALK_TRACE_PLANES+4,x
        sta     z:w_dist
        lda     f:WalkHullData+WALK_TRACE_PLANES+6,x
        sta     z:w_dist_high
.endmacro
.endif
.if !.definedmacro(WALK_DIVIDE_WORD_BY_BYTE)
.macro WALK_DIVIDE_WORD_BY_BYTE divisor
        sta     f:WRDIVL
        RW      a8
        lda     z:divisor
        sta     f:WRDIVB
        RW      a16
        .repeat 7                    ; At least 16 CPU cycles including REP.
        nop
        .endrepeat
        lda     f:RDDIVL
.endmacro
.endif
.if !.definedmacro(WALK_FRACTION_SMALL_DIGITS)
.macro WALK_FRACTION_SMALL_DIGITS digit
  .ifdef QC_QUEUED_INPUT
        ldx     #3
digit:
        .repeat 4
  .else
        ldx     #12
digit:
  .endif
        asl
        cmp     z:w_denominator
        bcc     :+
        sbc     z:w_denominator
:       rol     z:w_fraction
  .ifdef QC_QUEUED_INPUT
        .endrepeat
  .endif
        dex
        bne     digit
.endmacro
.endif
.if .defined(POINT_SHOT) .or .defined(QC_BASIC_GAMEPLAY)
WALK_MAX_NODES_PER_TRACE = 4096
.else
WALK_MAX_NODES_PER_TRACE = 512
.endif

.if .defined(POINT_SHOT)
WALK_REGISTER_TRACE = .defined(PLAYABLE_SHOT_HULL_BYTES)
.else
WALK_REGISTER_TRACE = .defined(PLAYABLE_REGISTER_WALK_TRACE)
.endif

.if .defined(POINT_SHOT)
WALK_TRACE_OBLIQUE_BOUND = .defined(PLAYABLE_POINT_OBLIQUE_BOUND)
.else
WALK_TRACE_OBLIQUE_BOUND = .defined(PLAYABLE_WALK_HULL_OBLIQUE_BOUND)
.endif

.if .defined(PLAYABLE_E1M1_WALK_RESUME_BYTES) .and (!.defined(POINT_SHOT))
        .include "quake/WalkTraceResume.s"
.endif

.if WALK_REGISTER_TRACE
  .if .defined(POINT_SHOT)
WALK_TRACE_ROOT = PLAYABLE_SHOT_HULL_ROOT
WALK_TRACE_PLANES = PLAYABLE_SHOT_HULL_PLANES
WALK_TRACE_THIRD = PLAYABLE_SHOT_HULL_THIRD
    .ifdef PLAYABLE_SHOT_HULL_EXIT_GUARD
WALK_TRACE_EXIT_GUARD = PLAYABLE_SHOT_HULL_EXIT_GUARD
WALK_TRACE_EXIT_BOUNDS = PLAYABLE_SHOT_HULL_EXIT_BOUNDS
WALK_TRACE_EXIT_BUCKET_MASK = $FC00
WALK_TRACE_FOOT_FRACTION = PLAYABLE_SHOT_HULL_FOOT_FRACTION
      .ifdef ::PLAYABLE_SHOT_HULL_MOVER_TAIL_GUARD
WALK_TRACE_MOVER_TAIL_GUARD = ::PLAYABLE_SHOT_HULL_MOVER_TAIL_GUARD
      .endif
      .ifdef ::PLAYABLE_SHOT_HULL_STATIC_Z_END
WALK_TRACE_STATIC_Z_END = ::PLAYABLE_SHOT_HULL_STATIC_Z_END
      .endif
      .ifdef ::PLAYABLE_SHOT_HULL_SECRET_BOUNDS
WALK_TRACE_SECRET_BOUNDS = ::PLAYABLE_SHOT_HULL_SECRET_BOUNDS
WALK_TRACE_SECRET_FIRST = ::PLAYABLE_SHOT_HULL_SECRET_FIRST_DEBT
WALK_TRACE_SECRET_MORE = ::PLAYABLE_SHOT_HULL_SECRET_MORE_DEBT
WALK_TRACE_SECRET_STACK = ::PLAYABLE_SHOT_HULL_SECRET_STACK_ENTRIES
      .endif
    .endif
  .else
WALK_TRACE_ROOT = PLAYABLE_WALK_HULL_ROOT
WALK_TRACE_PLANES = PLAYABLE_WALK_HULL_PLANES
WALK_TRACE_THIRD = PLAYABLE_WALK_HULL_THIRD
    .ifdef PLAYABLE_WALK_HULL_AXIS_X_END
WALK_TRACE_AXIS_X_END = PLAYABLE_WALK_HULL_AXIS_X_END
    .endif
    .ifdef PLAYABLE_WALK_HULL_EXIT_GUARD
WALK_TRACE_EXIT_GUARD = PLAYABLE_WALK_HULL_EXIT_GUARD
WALK_TRACE_EXIT_BOUNDS = PLAYABLE_WALK_HULL_EXIT_BOUNDS
WALK_TRACE_EXIT_BUCKET_MASK = $F800
      .if .defined(PLAYABLE_MAP_ID) .and .defined(PLAYABLE_SHOT_HULL_FOOT_FRACTION)
WALK_TRACE_FOOT_FRACTION = PLAYABLE_SHOT_HULL_FOOT_FRACTION
      .endif
      .ifdef PLAYABLE_WALK_HULL_SECRET_BOUNDS
WALK_TRACE_SECRET_BOUNDS = PLAYABLE_WALK_HULL_SECRET_BOUNDS
WALK_TRACE_SECRET_FIRST = PLAYABLE_WALK_HULL_SECRET_FIRST_DEBT
WALK_TRACE_SECRET_MORE = PLAYABLE_WALK_HULL_SECRET_MORE_DEBT
WALK_TRACE_SECRET_STACK = PLAYABLE_WALK_HULL_SECRET_STACK_ENTRIES
      .endif
    .endif
  .endif
WALK_NODE_BYTES = 8
; The packed exit hull routes owned axial nodes through its cold decoder.
  .if .defined(QC_BASIC_GAMEPLAY) .or .defined(WALK_TRACE_EXIT_GUARD)
WALK_CHECK_AXIAL_OWNER = 0
  .else
WALK_CHECK_AXIAL_OWNER = 1
  .endif
.else
WALK_TRACE_ROOT = WALK_HULL_ROOT
WALK_TRACE_PLANES = WALK_HULL_PLANES
WALK_NODE_BYTES = 6
  .if .defined(QC_BASIC_GAMEPLAY)
    .ifdef POINT_SHOT
WALK_TRACE_THIRD = SHOT_HULL_THIRD_COEFFICIENTS
    .else
WALK_TRACE_THIRD = WALK_HULL_THIRD_COEFFICIENTS
    .endif
  .endif
.endif

WALK_DIRECT_AXIAL_SPLIT = .defined(WALK_TRACE_EXIT_GUARD) .or .defined(POINT_SHOT)
WALK_CACHE_AXIAL_SPLIT = .defined(POINT_SHOT) .and .defined(PLAYABLE_E1M1_TRACE_LAYOUT)
WALK_PACKED_POINT_CACHE = WALK_CACHE_AXIAL_SPLIT .and .defined(PLAYABLE_MAP_ID) .and (.defined(PLAYABLE_LARGE_DISTANCE_CACHE) .or .defined(PLAYABLE_KNIGHT_POINT_FRACTIONS))
WALK_POINT_AXES = .defined(POINT_SHOT) .and .defined(::PLAYABLE_SHOT_HULL_STATIC_Y_END)
.ifdef POINT_SHOT
WALK_FAST_EXIT_AXIAL = .defined(PLAYABLE_E1M1_MOVING_PLANE_ADD) .and .defined(PLAYABLE_SHOT_HULL_LIVE_EXIT_AXIAL)
  .if WALK_FAST_EXIT_AXIAL
    .assert PLAYABLE_SHOT_HULL_LIVE_EXIT_AXIAL = 2*QC_SECRET_DOOR_COUNT, error, "Unexpected number of live secret axes"
  .endif
.else
WALK_FAST_EXIT_AXIAL = .defined(PLAYABLE_E1M1_MOVING_PLANE_ADD) .and .defined(PLAYABLE_WALK_HULL_LIVE_EXIT_AXIAL)
  .if WALK_FAST_EXIT_AXIAL
    .assert PLAYABLE_WALK_HULL_LIVE_EXIT_AXIAL = 2*QC_SECRET_DOOR_COUNT, error, "Unexpected number of live secret axes"
  .endif
.endif
; Exit hulls index the sparse axis table with the encoded tag bits.
.ifdef WALK_TRACE_EXIT_GUARD
WALK_TAG_STEP = $20
.else
WALK_TAG_STEP = 2
.endif

; w_from, w_to, w_result are consecutive XYZ vectors. All run-time plane and
; trace scratch is in DB=$7f. The result is in w_result, with carry on impact.
WalkTrace:
        QC_YIELD_COORDINATE_STREAM
        .include "quake/WalkTraceCacheEntry.i"
.if .defined(POINT_SHOT) .and .defined(PLAYABLE_POINT_SIGHT_CACHE)
.assert !.defined(PLAYABLE_LARGE_DISTANCE_CACHE), error, "Sight cache expects the uncached point trace entry"
WalkSightTraceBody:
.endif
.if .defined(POINT_SHOT) .and .defined(PLAYABLE_LARGE_DISTANCE_CACHE)
        jmp     WalkPointTraceCached
WalkTraceUncached:
.endif
.if .defined(WALK_IMPACT_CACHE_BYTES) .and !.defined(POINT_SHOT)
        ; The basic map hull has no moving planes. Preserve exactly the
        ; caller-visible outputs of a repeated segment. Clear paths do not
        ; evict repeated gravity, wall and slide impacts from this FIFO.
        ldx     #0
@FindImpact:
        lda     a:w_impact_cache+26,x
        beq     @Uncached
        .repeat 6, word
          lda   a:w_from+2*word
          cmp   a:w_impact_cache+2*word,x
          bne   @NextImpact
        .endrepeat
        .repeat 6, word
          lda   a:w_impact_cache+12+2*word,x
          sta   a:w_result+2*word
        .endrepeat
        lda     a:w_impact_cache+24,x
        sta     a:w_enter
        inc     a:w_impacts
        cmp     #WALK_NO_PLANE
        bne     :+
        inc     a:w_startsolid
:       sec
        rts
@NextImpact:
        txa
        clc
        adc     #WALK_IMPACT_CACHE_STRIDE
        tax
        cpx     #WALK_IMPACT_CACHE_BYTES
        bcc     @FindImpact
@Uncached:
        lda     a:w_trace_fault
        pha
        jsr     WalkTraceUncached
        bcc     @ClearReturn
        pla
        cmp     a:w_trace_fault
        bne     @ImpactReturn
        ldx     a:w_impact_cache_next
        .repeat 12, word
          lda   a:w_from+2*word
          sta   a:w_impact_cache+2*word,x
        .endrepeat
        lda     a:w_enter
        sta     a:w_impact_cache+24,x
        lda     #1
        sta     a:w_impact_cache+26,x
        txa
        clc
        adc     #WALK_IMPACT_CACHE_STRIDE
        cmp     #WALK_IMPACT_CACHE_BYTES
        bcc     :+
        lda     #0
:       sta     a:w_impact_cache_next
@ImpactReturn:
        sec
        rts
@ClearReturn:
        pla
        clc
        rts

.assert w_to = w_from + 6, error, "impact cache requires contiguous trace endpoints"
.assert w_result = w_to + 6, error, "impact cache requires contiguous trace results"
.assert w_normal = w_result + 6, error, "impact cache requires contiguous trace normals"
.assert WALK_IMPACT_CACHE_STRIDE >= 28, error, "impact cache record exceeds its stride"
.assert w_impact_cache + WALK_IMPACT_CACHE_BYTES <= $10000, lderror, "impact cache crosses WRAM bank"
WalkTraceUncached:
.endif
.ifdef WALK_TRACE_SECRET_BOUNDS
        stz     a:w_secret_tail_state
@TraceInit:
.endif
.if !.defined(QC_BASIC_GAMEPLAY)
        stz     a:w_entrance_probe_owner
.endif
.if .defined(WALK_TRACE_EXIT_GUARD) .and WALK_TRACE_OBLIQUE_BOUND
        stz     z:w_oblique_negative_bound
.endif
.include "quake/PlayerWalkTraceBias.i"
        stz     z:w_sp
        stz     z:w_lo
        lda     #WALK_T_ONE
        sta     z:w_hi
.if !WALK_REGISTER_TRACE
        lda     #WALK_HULL_ROOT
.if .defined(WALK_EXPLOBOX_ROOT) .and !.defined(POINT_SHOT)
        ldx     a:qce+QC_EXPLOBOX+QC_FIELD_SOLID
        beq     :+
        lda     #WALK_EXPLOBOX_ROOT
:
.endif
        sta     z:w_node
.endif
        lda     #WALK_NO_PLANE
        sta     a:w_enter
.if WALK_REGISTER_TRACE
        ldy     #WALK_MAX_NODES_PER_TRACE
        lda     #WALK_TRACE_ROOT
  .if .defined(WALK_EXPLOBOX_ROOT) .and !.defined(POINT_SHOT)
        ldx     a:qce+QC_EXPLOBOX+QC_FIELD_SOLID
        beq     :+
    .ifdef PLAYABLE_E1M1_WALK_RESUME_BYTES
        jsl     WalkResumePrefix
    .elseif .defined(WALK_TRACE_AXIS_X_END)
        lda     #PLAYABLE_WALK_HULL_EXPLOBOX_ROOT
    .else
        lda     #WALK_EXPLOBOX_ROOT/6*WALK_NODE_BYTES
    .endif
:
  .endif
  .if .defined(POINT_SHOT) .and .defined(PLAYABLE_SHOT_RESUME_BYTES)
    .ifdef PLAYABLE_E1M1_POINT_OBLIQUE
        jsl     ::ShotResumeVertical
    .else
        jsr     ShotResumeVertical
    .endif
  .endif
.else
        lda     #WALK_MAX_NODES_PER_TRACE
        sta     z:w_limit
.endif
.ifdef PLAYABLE_E1M1_TRACE_LAYOUT
        .assert WALK_REGISTER_TRACE, error, "E1M1 trace layout requires a register traversal"
        bra     @Visit
@Leaf:
.else
@Visit:
  .if WALK_REGISTER_TRACE
        dey
        beq     @VisitFault
        tax
        bpl     @Node
  .endif
.endif
.if WALK_REGISTER_TRACE
  .if .defined(POINT_SHOT)
        cmp     #$ffff
        beq     @Empty
        stx     z:w_node               ; Weapon callbacks distinguish mover hits.
  .else
        cmp     #$fffe
        bne     @Empty
  .endif
.else
        dec     z:w_limit
        bne     :+
        jmp     WalkTraceFault
:
        ldx     z:w_node
        bpl     @Node
.if .defined(POINT_SHOT)
        cpx     #$ffff
        beq     @Empty
.else
        cpx     #$fffe
        bne     @Empty
.endif
.endif
        jmp     WalkTraceImpact
.if WALK_REGISTER_TRACE
@VisitFault:
  .ifdef WALK_TRACE_SECRET_BOUNDS
    .ifdef WALK_TRACE_MOVER_TAIL_GUARD
        jml     @TraceFaultCheck
    .else
        jmp     @TraceFaultCheck
    .endif
  .else
        jmp     WalkTraceFault
  .endif
.endif
@Empty:
        lda     z:w_sp
        bne     @Pop
        ldx     #4
@Clear:
        lda     a:w_to,x
        sta     a:w_result,x
        stz     a:w_normal,x
        dex
        dex
        bpl     @Clear
        clc
        rts
@Pop:
.if WALK_REGISTER_TRACE
        sty     z:w_limit
.endif
        sec
        sbc     #8
        sta     z:w_sp
        tay
.if !WALK_REGISTER_TRACE
        lda     a:w_stack,y
        sta     z:w_node
.endif
        lda     a:w_stack+2,y
        sta     z:w_lo
        lda     a:w_stack+4,y
        sta     z:w_hi
        lda     a:w_stack+6,y
        sta     a:w_enter
.if WALK_REGISTER_TRACE
        lda     a:w_stack,y
        ldy     z:w_limit
.endif
.ifdef PLAYABLE_E1M1_TRACE_LAYOUT
  .ifdef POINT_SHOT
        bra     @Visit
@FastFront:
        lda     f:WalkHullData+2,x
  .endif
@Visit:
        dey
        beq     @VisitFault
        tax
        bmi     @Leaf
.else
        bra     @Visit
.endif
@Node:
.if WALK_REGISTER_TRACE
  .if .defined(WALK_TRACE_AXIS_X_END) .and !.defined(POINT_SHOT)
.assert .defined(WALK_TRACE_EXIT_GUARD) .and !WALK_CHECK_AXIAL_OWNER, error, "Static axis ranges require packed E1M1 exit movers"
        .include "quake/WalkTraceStaticAxes.i"
  .else
  .ifdef WALK_TRACE_STATIC_Z_END
        .include "quake/PointTraceStaticAxes.i"
  .else
        lda     f:WalkHullData,x
        bpl     @LowTag
        cmp     #$A000
        bcc     @FastY
        cmp     #$C000
  .endif
  .ifdef WALK_TRACE_EXIT_GUARD
    .ifndef WALK_TRACE_STATIC_Z_END
        bcc     :+
    .endif
        cmp     #WALK_TRACE_EXIT_GUARD
        beq     @ExitTail
    .if .defined(POINT_SHOT) .and .defined(PLAYABLE_POINT_MOVING_RANK)
        jml     @MovingRankFast
@MovingRankFallback:
    .elseif .defined(WALK_TRACE_MOVER_TAIL_GUARD)
        cmp     #WALK_TRACE_MOVER_TAIL_GUARD
        bne     :+
        jml     @CertifiedMoverTail
:
    .endif
        lda     f:WalkHullData+6,x     ; Original moving axial plane reference.
    .if !WALK_CHECK_AXIAL_OWNER
        ; The packed sentinel already classified this as a moving axis.
        sty     z:w_limit
        stx     z:w_node
        sta     z:w_plane
        jmp     @Moving
    .else
        bra     @SpillNode
    .endif
    .ifndef WALK_TRACE_STATIC_Z_END
:
    .endif
  .else
    .ifdef QC_E1M2_GROUP_COUNT
        bcc     :+
        cmp     #$E000
        bne     @SpillNode
        lda     f:WalkHullData+6,x
        sty     z:w_limit
        stx     z:w_node
        sta     z:w_plane
        jmp     @Moving
:
    .else
        bcs     @SpillNode
    .endif
  .endif
  .ifndef WALK_TRACE_STATIC_Z_END
        WALK_STATIC_AXIAL 4, @FastFront, @FastBack, @FastSplit, WALK_CHECK_AXIAL_OWNER
  .endif
  .if WALK_POINT_AXES = 0
@LowTag:
        cmp     #$6000
        bcc     @SpillNode
        WALK_STATIC_AXIAL 0, @FastFront, @FastBack, @FastSplit, WALK_CHECK_AXIAL_OWNER
  .endif
@FastY:
        WALK_STATIC_AXIAL 2, @FastFront, @FastBack, @FastSplit, WALK_CHECK_AXIAL_OWNER
  .endif
@SpillNode:
        sty     z:w_limit
        stx     z:w_node
        sta     z:w_plane
  .if .defined(WALK_TRACE_EXIT_GUARD) .and !WALK_CHECK_AXIAL_OWNER
        ; Only the low-tag oblique test reaches this spill.
        jmp     @Oblique
  .else
    .if .defined(QC_BASIC_GAMEPLAY)
        cmp     #$E000
    .else
        cmp     #$6000                 ; All spilled E1M1 axial nodes move.
    .endif
        bcs     :+
        jmp     @Oblique
:       jmp     @Moving
  .endif
.if !(.defined(PLAYABLE_E1M1_TRACE_LAYOUT) .and .defined(POINT_SHOT))
@FastFront:
        lda     f:WalkHullData+2,x
        jmp     @Visit
.endif
@FastBack:
        lda     f:WalkHullData+4,x
        jmp     @Visit
  .ifdef WALK_TRACE_EXIT_GUARD
@ExitTail:
        ; The smaller reverse-biased endpoint represents the higher Y.
        ; Skip the whole tail without adding a split or an entering plane.
        iny                            ; This synthetic node does not consume a visit.
        lda     f:WalkHullData+6,x
        cmp     w_biased_from_fast+2
    .ifdef WALK_TRACE_SECRET_BOUNDS
        bcc     @ExitMoversMiss
    .else
        bcc     @FastBack
    .endif
    .ifdef POINT_SHOT
        jsr     ::ShotHull::WalkExitBucketPossible
    .else
        jsr     WalkExitBucketPossible
    .endif
    .ifdef WALK_TRACE_SECRET_BOUNDS
        bcc     @ExitMoversMiss
      .if .defined(PLAYABLE_E1M1_TRACE_LAYOUT) .and .defined(POINT_SHOT)
        jmp     @FastFront
      .else
        bra     @FastFront
      .endif
@ExitMoversMiss:
      .ifdef WALK_TRACE_MOVER_TAIL_GUARD
        jml     @TrySecretTail
      .else
        jmp     @TrySecretTail
      .endif
    .else
        bcc     @FastBack
      .if .defined(PLAYABLE_E1M1_TRACE_LAYOUT) .and .defined(POINT_SHOT)
        jmp     @FastFront
      .else
        bra     @FastFront
      .endif
    .endif
  .endif
@FastSplit:
  .if WALK_DIRECT_AXIAL_SPLIT
        sta     z:w_d0
        stx     z:w_node
        lda     f:WalkHullData,x
        sta     z:w_plane
@PackedAxialSplit:
        ; For reversed endpoint bounds min <= plane < max, the split
        ; denominator is max-min. Only the original start picks the side.
    .if WALK_CACHE_AXIAL_SPLIT
        lda     a:w_axial_span,y
    .else
        lda     a:w_biased_to,y
        sec
        sbc     a:w_biased_from,y
    .endif
        sta     z:w_denominator
  .ifndef POINT_SHOT
        bmi     @WideAxialSplit
        stz     z:w_denominator_high
        stz     z:w_numerator_high
  .else
    .ifndef PLAYABLE_E1M1_TRACE_LAYOUT
        QC_YIELD_COORDINATE_STREAM
    .endif
  .endif
    .if WALK_CACHE_AXIAL_SPLIT
        lda     a:w_axial_front,y
        bpl     @PackedNearBack
    .else
        lda     a:w_from,y
        eor     #$7fff
        cmp     a:w_biased_from,y
        bne     @PackedNearBack
    .endif
        lda     z:w_d0
        sec
        sbc     a:w_biased_from,y
        POINT_TRACE_PACKED_BOUNDS 2, 4
        lda     f:WalkHullData+2,x
        sta     z:w_near
        lda     f:WalkHullData+4,x
        bra     @PackedFar
@PackedNearBack:
        lda     a:w_biased_to,y
        sec
        sbc     z:w_d0
        POINT_TRACE_PACKED_BOUNDS 4, 2
        inc     z:w_plane
        lda     f:WalkHullData+4,x
        sta     z:w_near
        lda     f:WalkHullData+2,x
@PackedFar:
        sta     z:w_far
        POINT_TRACE_FINISH_PACKED @DividePrepared, @ClassifyFraction
  .ifndef POINT_SHOT
@WideAxialSplit:
        ; Preserve the legacy signed-distance saturation for wide sweeps.
        sty     z:w_axis_a
        lda     z:w_d0
        eor     #$7fff
        sta     z:w_dist
        jsr     WalkAxialDistances
        jmp     @Split
  .endif
  .else
        sty     z:w_axis_a
        eor     #$7fff
        sta     z:w_dist
        stx     z:w_node
        lda     f:WalkHullData,x
        sta     z:w_plane
        jsr     WalkAxialDistances
        jmp     @Split
  .endif
.else
        lda     f:WalkHullData,x
        sta     z:w_plane
.ifdef QC_E1M2_GROUP_COUNT
  .ifdef QC_E1M3_GOLD_KEY
        and     #$e000
        cmp     #$6000
        bcs     :+
        jmp     @Oblique
:       lda     z:w_plane
  .endif
        bit     #4
        bne     @Moving
.endif
        and     #$e000
        cmp     #$6000
        bcc     @Oblique
        cmp     #$c000
.if .defined(QC_BASIC_GAMEPLAY)
        beq     @Oblique
.endif
        bcs     @Moving
 .if !.defined(QC_BASIC_GAMEPLAY)
        ; Entrance axial planes retain their normal tag, with owner bits in
        ; the reserved low reference bits. They need the translated loader.
        lda     z:w_plane
        and     #6
        beq     :+
        jmp     @Moving
:       lda     z:w_plane
        and     #$e000
.endif
        ; Static axial tags are X=$6000, Y=$8000, Z=$a000. Compare
        ; biased coordinates directly and read just the chosen child.
        ldy     #0
        cmp     #$8000
        bcc     @StaticAxial
        ldy     #2
        cmp     #$a000
        bcc     @StaticAxial
        ldy     #4
@StaticAxial:
        WALK_LOAD_PLANE_OFFSET WALK_TRACE_EXTENDED_PLANES
        lda     f:WalkHullData+WALK_HULL_PLANES+4,x
        eor     #$8000
.if .defined(WALK_IMPACT_CACHE_BYTES) .and !.defined(POINT_SHOT)
        ; Hold the biased threshold minus one in A. Carry from CMP then
        ; means strictly behind the plane, including for equal endpoints.
        beq     @Front
        dec
        cmp     a:w_biased_from,y
        bcs     @AxialBack
        cmp     a:w_biased_to,y
        bcc     @Front
        bra     @AxialSplit
@AxialBack:
        cmp     a:w_biased_to,y
        bcs     @Back
@AxialSplit:
        sty     z:w_axis_a
        inc
        eor     #$8000
        sta     z:w_dist
.else
        sta     z:w_dist
        lda     a:w_biased_from,y
        cmp     z:w_dist
        bcc     @AxialBack
        lda     a:w_biased_to,y
        cmp     z:w_dist
        bcs     @Front
        bra     @AxialSplit
@AxialBack:
        lda     a:w_biased_to,y
        cmp     z:w_dist
        bcc     @Back
@AxialSplit:
        sty     z:w_axis_a
.if .defined(POINT_SHOT)
        ; The point path calls WalkPlaneDistance, which reads w_tag.
        ; The previous node may have left an oblique tag and coefficients.
        lda     #3 * WALK_TAG_STEP
        sta     z:w_tag
.endif
        lda     z:w_dist
        eor     #$8000
        sta     z:w_dist
.endif
.if .defined(POINT_SHOT)
        ldx     #0
        cmp     #$8000
        bcc     :+
        dex
:       stx     z:w_dist_high
.endif
        jsr     WalkAxialDistances
        bra     @Split
.endif
  .if .defined(POINT_SHOT) .and .defined(PLAYABLE_POINT_MOVING_RANK)
.include "quake/PointTraceMovingRankDispatch.i"
  .endif
@Moving:
.if WALK_REGISTER_TRACE .and (.defined(WALK_TRACE_EXIT_GUARD) .or (.defined(POINT_SHOT) .and .defined(QC_E1M2_Q4_BYTES)))
  .if .defined(POINT_SHOT) .and .defined(PLAYABLE_LARGE_DISTANCE_CACHE)
        ; These translated axial thresholds are valid until a mover changes.
        lda     z:w_plane
    .ifndef PLAYABLE_E1M1_MOVING_PLANE_ADD
        asl
    .endif
        ; E1M1 plane records already have the eight-byte cache slot stride.
        and     #(POINT_MOVING_CACHE_BYTES-8)
        tax
        lda     a:point_moving_cache,x
        cmp     z:w_plane
        bne     @MovingMiss
        ldy     a:point_moving_cache+2,x
        lda     a:point_moving_cache+4,x
        bra     @MovingRank
@MovingMiss:
        phx
    .if WALK_FAST_EXIT_AXIAL
        jsr     WalkLoadMovingAxial
    .else
        jsr     WalkLoadPlane
    .endif
        plx
        lda     z:w_plane
        sta     a:point_moving_cache,x
        ldy     z:w_axis_a
        tya
        sta     a:point_moving_cache+2,x
        lda     z:w_dist
        eor     #$7fff
        sta     a:point_moving_cache+4,x
@MovingRank:
  .elseif .defined(POINT_SHOT) .and .defined(QC_E1M2_Q4_BYTES)
        jsr     WalkE1M2MovingThreshold  ; Every authored pose fits a signed word.
        eor     #$7fff
  .elseif .defined(QC_E1M2_TRANSLATION_CACHE)
        jsr     WalkLoadE1M2MovingAxial
        lda     z:w_dist
        eor     #$7fff
  .else
    .if WALK_FAST_EXIT_AXIAL
        jsr     WalkLoadMovingAxial
    .else
        jsr     WalkLoadPlane
    .endif
        ldy     z:w_axis_a
        lda     z:w_dist
        eor     #$7fff
  .endif
        ; The packer bounds translated axial planes to signed words.
        ; Classify against the sorted endpoints before evaluating a split.
        cmp     a:w_biased_from,y
        bcs     :+
        jmp     @Back
:       cmp     a:w_biased_to,y
        bcc     :+
        jmp     @Front
:       sta     z:w_d0
        ldx     z:w_node
        jmp     @PackedAxialSplit
.else
  .ifdef QC_E1M2_TRANSLATION_CACHE
        jsr     WalkE1M2MovingSide
        bcc     :+
        beq     @Front
        bra     @Back
:
  .else
        jsr     WalkLoadPlane
  .endif
        jsr     WalkAxialDistances
        bra     @Classify
.endif
@Oblique:
.if .defined(POINT_SHOT) .and .defined(PLAYABLE_E1M1_POINT_OBLIQUE)
  .ifdef PLAYABLE_SHOT_HULL_INLINE_BOUNDS
        .assert WALK_REGISTER_TRACE .and .defined(WALK_TRACE_EXIT_GUARD), error, "Inline point bounds require the register traversal"
  .endif
        jsl     ::ShotObliqueSafeSide
        bcc     :+
        bmi     @Back
        bra     @Front
:
.endif
        jsr     WalkLoadPlane
.if .defined(PLAYABLE_LARGE_DISTANCE_CACHE) .and !.defined(QC_BASIC_GAMEPLAY)
        jsr     WalkStartObliqueDistance
.else
        ldy     #0
        jsr     WalkPlaneDistance
.endif
.if .defined(WALK_TRACE_EXIT_GUARD) .and WALK_TRACE_OBLIQUE_BOUND
        ; The packer proves |ca|+|cb| <= $6000, so the raw dot product
        ; changes by at most $6000*M. The high word alone can prove a side.
        lda     z:w_eval_high
        bmi     @ObliqueNegative
        cmp     z:w_oblique_front_bound
        bcs     @Front
        bra     @ObliqueExact
@ObliqueNegative:
        eor     #$8000
        cmp     z:w_oblique_negative_bound
        bcc     @Back
@ObliqueExact:
.endif
        lda     z:w_eval
        sta     z:w_d0
        lda     z:w_eval_high
        sta     z:w_d0_high
        jsr     WalkObliqueEndDistance
@Classify:
        lda     z:w_eval_high
        eor     z:w_d0_high
        bmi     @Split
        lda     z:w_d0_high
        bmi     @Back
@Front:
        ldx     z:w_node
        lda     f:WalkHullData+2,x
        bra     @Child
@Back:
        ldx     z:w_node
        lda     f:WalkHullData+4,x
@Child:
.if WALK_REGISTER_TRACE
        ldy     z:w_limit
.else
        sta     z:w_node
.endif
        jmp     @Visit
@Split:
.ifdef POINT_SHOT
        QC_YIELD_COORDINATE_STREAM
.endif
        ldx     z:w_node
        lda     f:WalkHullData+2,x
        sta     a:w_front
        lda     f:WalkHullData+4,x
        sta     a:w_back
        ; The absolute distances sum to the denominator. Keep full precision
        ; through the divide, including distances smaller than one Q4 unit.
        lda     z:w_eval
        sta     z:w_d1
        lda     z:w_eval_high
        sta     z:w_d1_high
        lda     z:w_d0_high
        bmi     @NearBack
        lda     a:w_front
        sta     z:w_near
        lda     a:w_back
        sta     z:w_far
        lda     #0
        sec
        sbc     z:w_d1
        sta     z:w_d1
        lda     #0
        sbc     z:w_d1_high
        sta     z:w_d1_high
        bra     @Divide
@NearBack:
        lda     a:w_back
        sta     z:w_near
        lda     a:w_front
        sta     z:w_far
        inc     z:w_plane              ; Low bit orients the impact normal.
        lda     #0
        sec
        sbc     z:w_d0
        sta     z:w_d0
        lda     #0
        sbc     z:w_d0_high
        sta     z:w_d0_high
@Divide:
        lda     z:w_d0
        sta     z:w_numerator
        clc
        adc     z:w_d1
        sta     z:w_denominator
        lda     z:w_d0_high
        sta     z:w_numerator_high
        adc     z:w_d1_high
        sta     z:w_denominator_high
.if WALK_REGISTER_TRACE .and WALK_DIRECT_AXIAL_SPLIT
  .if WALK_CACHE_AXIAL_SPLIT
        clc
  .endif
@DividePrepared:
.endif
        jsr     WalkFractionWithWidth
@ClassifyFraction:
        sta     z:w_mid
        cmp     z:w_lo
        bcc     @Far
        beq     @FarBoundary
        cmp     z:w_hi
        bcc     @Push
        beq     @Push                  ; Check contact at the exact endpoint.
        lda     z:w_near
        jmp     @Child
@FarBoundary:
        lda     z:w_plane
        sta     a:w_enter
@Far:
        lda     z:w_far
        jmp     @Child
@Push:
        lda     z:w_sp
        cmp     #WALK_HULL_STACK_ENTRIES*8
        bcc     :+
.ifdef WALK_TRACE_SECRET_BOUNDS
  .ifdef WALK_TRACE_MOVER_TAIL_GUARD
        jml     @TraceFaultCheck
  .else
        jmp     @TraceFaultCheck
  .endif
.else
        jmp     WalkTraceFault
.endif
:       tay
        lda     z:w_far
        sta     a:w_stack,y
        lda     z:w_mid
        sta     a:w_stack+2,y
        lda     z:w_hi
        sta     a:w_stack+4,y
        lda     z:w_plane
        sta     a:w_stack+6,y
        tya
        clc
        adc     #8
        sta     z:w_sp
        lda     z:w_mid
        sta     z:w_hi
        lda     z:w_near
        jmp     @Child

.include "quake/WalkTraceMoverTail.i"

WalkTraceFault:
.if .defined(POINT_SHOT)
        inc     a:.loword(shotgun_trace_fault)
        ldx     #$fffe
        stx     z:w_node
.else
        inc     a:w_trace_fault
.endif
        lda     #WALK_NO_PLANE
        sta     a:w_enter
        stz     z:w_lo
        bra     WalkTraceImpact

WalkTraceImpact:
.if !.defined(POINT_SHOT)
        inc     a:w_impacts
.endif
        stz     a:w_normal
        stz     a:w_normal+2
        stz     a:w_normal+4
        lda     a:w_enter
        cmp     #WALK_NO_PLANE
        bne     @Normal
.if !.defined(POINT_SHOT)
        inc     a:w_startsolid
.endif
        stz     a:w_safe_t
        jmp     WalkTraceInterpolate
@Normal:
        sta     z:w_plane
        jsr     WalkLoadPlane
        ldx     z:w_axis_a
        lda     z:w_tag
        cmp     #3 * WALK_TAG_STEP
.if .defined(QC_BASIC_GAMEPLAY)
        cmp     #6 * WALK_TAG_STEP
        beq     @ThreeAxisNormal
        cmp     #3 * WALK_TAG_STEP
.endif
        bcc     @Oblique
        lda     #$4000
        sta     a:w_normal,x
        bra     @Orient
@Oblique:
        lda     z:w_coeff_a
        sta     a:w_normal,x
        ldx     z:w_axis_b
        lda     z:w_coeff_b
        sta     a:w_normal,x
.if .defined(QC_BASIC_GAMEPLAY)
        bra     @Orient
@ThreeAxisNormal:
        lda     z:w_coeff_a
        sta     a:w_normal
        lda     z:w_coeff_b
        sta     a:w_normal+2
        lda     a:w_coeff_c
        sta     a:w_normal+4
.endif
@Orient:
        lda     a:w_enter
        and     #1
        beq     @Skin
        ldx     #4
@Negate:
        lda     #0
        sec
        sbc     a:w_normal,x
        sta     a:w_normal,x
        dex
        dex
        bpl     @Negate
@Skin:
.if .defined(POINT_SHOT)
        lda     z:w_lo
        sta     a:w_safe_t
.else
        ; Leave two Q4 units of skin along the dominant move axis. Start and
        ; end are bounded before this path, so the differences fit a word.
        stz     z:w_denominator
        stz     z:w_denominator_high
        ldx     #4
@Dominant:
        lda     a:w_to,x
        sec
        sbc     a:w_from,x
        bpl     :+
        eor     #$ffff
        inc
:       cmp     z:w_denominator
        bcc     :+
        sta     z:w_denominator
:       dex
        dex
        bpl     @Dominant
        lda     #2
        sta     z:w_numerator
        stz     z:w_numerator_high
        cmp     z:w_denominator
        bcs     @AtStart
        jsr     WalkFraction
        sta     a:w_temp
        lda     z:w_lo
        sec
        sbc     a:w_temp
        bcs     @Verify
@AtStart:
        lda     #0
@Verify:
        sta     a:w_safe_t
        lda     #7
        sta     a:w_fallback_count
@Check:
        lda     a:w_safe_t
        beq     WalkTraceInterpolate
        jsr     WalkTraceInterpolate
        jsr     WalkPointSolid
        bcc     @Done
        lsr     a:w_safe_t
        dec     a:w_fallback_count
        bne     @Check
        stz     a:w_safe_t
        jsr     WalkTraceInterpolate
@Done:
        sec
        rts
.endif

WalkTraceInterpolate:
        lda     a:w_safe_t
        bne     @Interpolate
        ldx     #4
@Copy:
        lda     a:w_from,x
        sta     a:w_result,x
        dex
        dex
        bpl     @Copy
        sec
        rts
@Interpolate:
        ldy     #4
@Axis:
        lda     a:w_to,y
        sec
        sbc     a:w_from,y
.ifdef QC_QUEUED_INPUT
        beq     @SameAxis
        ; The short signed delta usually fits one PPU product.
        tax
        lda     a:w_safe_t
.else
        ldx     a:w_safe_t
.endif
        jsr     WalkMultiply
        jsr     WalkProductQ12
        clc
        adc     a:w_from,y
.ifdef QC_QUEUED_INPUT
        bra     @StoreAxis
@SameAxis:
        lda     a:w_from,y
@StoreAxis:
.endif
        sta     a:w_result,y
        dey
        dey
        bpl     @Axis
        sec
        rts

.include "quake/WalkTraceBounds.i"

; Tag indices 0..2 identify the two nonzero axes of an oblique plane.
; Indices 3..5 are static axial planes, 6 translates door Z and 7 button X.
.ifndef WALK_TRACE_EXIT_GUARD
WalkAxisA:
        .word   0, 0, 2, 0, 2, 4, 4, 0
WalkAxisB:
        .word   2, 4, 4
.endif

.if WALK_FAST_EXIT_AXIAL
.assert .defined(WALK_TRACE_EXIT_GUARD) .and !WALK_CHECK_AXIAL_OWNER, error, "Fast exit loader requires preclassified moving axial nodes"
WalkLoadMovingAxial:
        lda     z:w_plane
        and     #6
        cmp     #6
        beq     @InlineExit
        jmp     WalkLoadPlane
@InlineExit:
        WALK_LOAD_PLANE_OFFSET 0
        lda     f:WalkHullData+WALK_TRACE_PLANES+4,x
        sta     z:w_dist
        lda     f:WalkHullData+WALK_TRACE_PLANES+2,x
        sta     z:w_axis_a
        lda     f:WalkHullData+WALK_TRACE_PLANES,x
        tax
        lda     a:.loword(qc_sd_offsets),x
  .ifdef POINT_SHOT
        cmp     #$8000
        ror
  .endif
        ; Translated axial thresholds fit a signed word.
        clc
        adc     z:w_dist
        sta     z:w_dist
        rts
.endif

WalkLoadPlane:
.if .defined(QC_BASIC_GAMEPLAY)
        lda     z:w_plane
        and     #$e000
        cmp     #$c000
        bne     :+
        jmp     WalkLoadThreeAxisPlane
:
.endif
.ifdef WALK_TRACE_EXIT_GUARD
        ; Only bits from the high byte of the reference survive the mask.
        .assert .loword(w_plane) <= $FD, lderror, "Plane tag load crosses direct page"
        lda     z:w_plane+1
.else
        lda     z:w_plane
        xba
.endif
        and     #$00e0
.ifndef WALK_TRACE_EXIT_GUARD
        lsr
        lsr
        lsr
        lsr
.endif
        tax
        stx     z:w_tag
.ifdef WALK_TRACE_EXIT_GUARD
        lda     f:::WalkAxesByTag,x
.else
        lda     f:WalkAxisA,x
.endif
        sta     z:w_axis_a
        cpx     #3 * WALK_TAG_STEP
.ifdef WALK_TRACE_EXIT_GUARD
        bcs     @Axial
.else
        bcs     :+
.endif
.ifdef WALK_TRACE_EXIT_GUARD
        lda     f:::WalkAxesByTag+2,x
.else
        lda     f:WalkAxisB,x
.endif
        sta     z:w_axis_b
:       WALK_LOAD_PLANE_OFFSET WALK_TRACE_EXTENDED_PLANES
.ifndef WALK_TRACE_EXIT_GUARD
        lda     z:w_tag
        cmp     #3 * WALK_TAG_STEP
        bcs     @Distance
.endif
        lda     f:WalkHullData+WALK_TRACE_PLANES,x
        sta     z:w_coeff_a
        lda     f:WalkHullData+WALK_TRACE_PLANES+2,x
        sta     z:w_coeff_b
.ifdef WALK_TRACE_EXIT_GUARD
        ; A two-axis tag has no legacy door or button translation. The
        ; shared tail still translates its entrance or exit mover owner.
        WALK_LOAD_PLANE_DISTANCE
        bra     @Done
@Axial:
        WALK_LOAD_PLANE_OFFSET WALK_TRACE_EXTENDED_PLANES
.endif
@Distance:
        WALK_LOAD_PLANE_DISTANCE
        lda     z:w_tag
        cmp     #6 * WALK_TAG_STEP
        bcc     @Done
        beq     @Door
        lda     f:quakec_button_pose
        asl
        tax
        lda     f:QCButtonTranslations,x
        bra     @Translate
@Door:
        lda     f:quakec_door_pose
        asl
        tax
        lda     f:QCDoorTranslations,x
@Translate:
.if .defined(POINT_SHOT)
        cmp     #$8000
        ror
.endif
        ldx     #0
        cmp     #$8000
        bcc     :+
        dex
:       clc
        adc     z:w_dist
        sta     z:w_dist
        txa
        adc     z:w_dist_high
        sta     z:w_dist_high
@Done:
.ifdef QC_E1M2_GROUP_COUNT
        lda     z:w_plane
        bit     #4
        beq     :+
        jmp     WalkE1M2AxialDistance
:
.endif
.if !.defined(QC_BASIC_GAMEPLAY)
        lda     z:w_plane
        and     #6
        beq     :+
        jmp     WalkEntrancePlaneDistance
:
.endif
        rts

.ifdef QC_E1M2_GROUP_COUNT
.include "quake/PlayerWalkE1M2.s"
.endif
.if !.defined(QC_BASIC_GAMEPLAY)
; Move the plane's signed32 distance, not the signed16 query coordinate.
; This keeps far-domain coordinates valid and handles original YZ bevels.
WalkEntrancePlaneDistance:
.ifdef QC_EXIT_MOVER_COUNT
        cmp     #6
        bne     :+
        jmp     @ExitMover
:
.endif
        cmp     a:w_entrance_probe_owner
        bne     @Live
        lda     a:w_entrance_probe_pose
        asl
        tax
        lda     z:w_plane
        and     #6
        cmp     #2
        beq     @ProbeFirst
        lda     f:QCEntrance1Translations,x
        bra     @Delta
@ProbeFirst:
        lda     f:QCEntrance0Translations,x
        bra     @Delta
@Live:
        cmp     #2
        beq     @First
        lda     f:quakec_entrance_pose+2
        asl
        tax
        lda     f:QCEntrance1Translations,x
        bra     @Delta
@First:
        lda     f:quakec_entrance_pose
        asl
        tax
        lda     f:QCEntrance0Translations,x
@Delta:
.if .defined(POINT_SHOT)
        cmp     #$8000
        ror
.endif
.ifdef PLAYABLE_E1M1_MOVING_PLANE_ADD
        beq     @TranslationDone
.endif
        ldy     z:w_tag
        cpy     #4 * WALK_TAG_STEP
        beq     @AxialY
        cpy     #0
        beq     @SecondCoefficient
        cpy     #2 * WALK_TAG_STEP
        beq     @FirstCoefficient
        rts
@SecondCoefficient:
        ldx     z:w_coeff_b
        bra     @Product
@FirstCoefficient:
        ldx     z:w_coeff_a
@Product:
        jsr     WalkMultiply
        lda     z:w_mul_low
.ifndef PLAYABLE_E1M1_MOVING_PLANE_ADD
        bra     @Add
@AxialY:
        ldx     #0
        cmp     #$8000
        bcc     :+
        dex
:       stx     z:w_mul_high
.endif
@Add:
        clc
        adc     z:w_dist
        sta     z:w_dist
        lda     z:w_mul_high
        adc     z:w_dist_high
        sta     z:w_dist_high
        rts
.ifdef PLAYABLE_E1M1_MOVING_PLANE_ADD
@AxialY:
        ; Positive deltas only change the high word on carry. Negative
        ; deltas sign-extend and only change it when the low add borrows.
        cmp     #$8000
        bcs     @NegativeDelta
        adc     z:w_dist
        sta     z:w_dist
        bcc     @TranslationDone
        inc     z:w_dist_high
        rts
@NegativeDelta:
        clc
        adc     z:w_dist
        sta     z:w_dist
        bcs     @TranslationDone
        dec     z:w_dist_high
@TranslationDone:
        rts
.endif
.ifdef QC_EXIT_MOVER_COUNT
@ExitMover:
        ; X is the packed plane byte offset. Each selector names one
        ; mover and either its axial translation or the affected bevel coefficient.
        txa
        sec
        sbc     #WALK_TRACE_EXIT_PLANE_FIRST
        lsr
        lsr
        lsr
        tax
        lda     f:WalkHullData+WALK_TRACE_PLANES+WALK_TRACE_EXIT_PLANE_TABLE,x
        and     #$00ff
  .ifdef QC_SECRET_DOOR_COUNT
        cmp     #128
        bcc     @OrdinaryExit
        sbc     #128
        asl
        tax
        lda     f:qc_sd_offsets,x
    .ifdef POINT_SHOT
        cmp     #$8000
        ror
    .endif
    .ifdef PLAYABLE_E1M1_MOVING_PLANE_ADD
        beq     @TranslationDone
    .endif
        jmp     @AxialY
@OrdinaryExit:
  .endif
        tay
        lsr
        and     #$fffe
        tax
  .ifdef QC_E1M1_PLATFORM_FIRST
        lda     f:qc_exit_active_q4,x
    .ifdef POINT_SHOT
        cmp     #$8000
        ror
    .endif
  .else
        lda     f:QuakeCExitPoses,x
        asl
        sta     z:w_mul_low
        tya
        and     #$fffc
        asl
        clc
        adc     z:w_mul_low
        tax
  .ifdef POINT_SHOT
        lda     f:QCExitPositionsQ3,x
  .else
        lda     f:QCExitPositionsQ4,x
  .endif
  .endif
.ifdef PLAYABLE_E1M1_MOVING_PLANE_ADD
        ; The table or platform already supplied the active displacement.
        ; A zero pose index can still have a nonzero translation.
        bne     :+
        rts
:
.endif
        pha
        tya
        and     #3
        beq     @ExitAxial
        cmp     #1
        beq     @ExitFirst
        ldx     z:w_coeff_b
        bra     @ExitProduct
@ExitFirst:
        ldx     z:w_coeff_a
@ExitProduct:
        pla
        jmp     @Product
@ExitAxial:
        pla
        jmp     @AxialY
.endif
.endif

.if .defined(POINT_SHOT) .and .defined(PLAYABLE_LARGE_DISTANCE_CACHE)
.include "quake/PointTraceCache.s"
.elseif .defined(POINT_SHOT) .and .defined(PLAYABLE_KNIGHT_POINT_FRACTIONS)
.include "quake/PointFractionCache.s"
.endif

; A straddling axial plane is at most one step away, so its two
; distances fit signed words. When they are farther away only the sign
; matters. Correct that sign on signed subtraction overflow.
WalkAxialDistances:
.if .defined(POINT_SHOT)
  .ifdef PLAYABLE_LARGE_DISTANCE_CACHE
        ; Point traces can span the whole signed coordinate range. Keep
        ; both signed high words rather than using the short walk test.
        ldy     z:w_axis_a
        ldx     #0
        lda     a:w_from,y
        bpl     :+
        dex
:       sec
        sbc     z:w_dist
        sta     z:w_d0
        txa
        sbc     z:w_dist_high
        sta     z:w_d0_high
        ldx     #0
        lda     a:w_to,y
        bpl     :+
        dex
:       sec
        sbc     z:w_dist
        sta     z:w_eval
        txa
        sbc     z:w_dist_high
        sta     z:w_eval_high
        rts
  .else
        ldy     #0
        jsr     WalkPlaneDistance
        lda     z:w_eval
        sta     z:w_d0
        lda     z:w_eval_high
        sta     z:w_d0_high
        ldy     #6
        jmp     WalkPlaneDistance
  .endif
.else
        ldy     z:w_axis_a
        lda     a:w_from,y
        sec
        sbc     z:w_dist
        bvc     :+
        eor     #$8000
:       sta     z:w_d0
        ldx     #0
        cmp     #$8000
        bcc     :+
        dex
:       stx     z:w_d0_high
        lda     a:w_to,y
        sec
        sbc     z:w_dist
        bvc     :+
        eor     #$8000
:       sta     z:w_eval
        ldx     #0
        cmp     #$8000
        bcc     :+
        dex
:       stx     z:w_eval_high
        rts
.endif

; d(end) = d(start) + n·(end-start), reusing the exact 32-bit dot product.
; Most traces hold one or both of the plane's two axes constant.
WalkObliqueEndDistance:
.if .defined(QC_BASIC_GAMEPLAY)
        lda     z:w_tag
        cmp     #6 * WALK_TAG_STEP
        bne     :+
        ldy     #6
        jmp     WalkThreeAxisEndDistance
:
.endif
        ldy     z:w_axis_a
        lda     a:w_to,y
        sec
        sbc     a:w_from,y
        beq     @Second
.ifdef QC_QUEUED_INPUT
        tax
        lda     z:w_coeff_a
.else
        ldx     z:w_coeff_a
.endif
        jsr     WalkMultiply
        jsr     WalkAccumulateDistance
@Second:
        ldy     z:w_axis_b
        lda     a:w_to,y
        sec
        sbc     a:w_from,y
        beq     WalkDistanceDone
.ifdef QC_QUEUED_INPUT
        tax
        lda     z:w_coeff_b
.else
        ldx     z:w_coeff_b
.endif
        jsr     WalkMultiply
WalkAccumulateDistance:
        lda     z:w_eval
        clc
        adc     z:w_mul_low
        sta     z:w_eval
        lda     z:w_eval_high
        adc     z:w_mul_high
        sta     z:w_eval_high
WalkDistanceDone:
        rts

.if .defined(PLAYABLE_LARGE_DISTANCE_CACHE) .and !.defined(QC_BASIC_GAMEPLAY)
; The trace already classified a two-axis plane at the start endpoint.
WalkStartObliqueDistance:
        ldy     z:w_axis_a
        lda     a:w_from,y
        sta     z:w_cache_coord_a
        ldy     z:w_axis_b
        lda     a:w_from,y
        bra     WalkObliqueDistanceCoordB
.endif

WalkPlaneDistance:
.if .defined(QC_BASIC_GAMEPLAY)
        lda     z:w_tag
        cmp     #6 * WALK_TAG_STEP
        bne     :+
        jmp     WalkThreeAxisDistance
:
.endif
        sty     z:w_endpoint
        tya
        clc
        adc     z:w_axis_a
        tay
        lda     a:w_from,y
        ldx     z:w_tag
        cpx     #3 * WALK_TAG_STEP
        bcc     @Oblique
        ldx     #0
        cmp     #$8000
        bcc     :+
        dex
:       sec
        sbc     z:w_dist
        sta     z:w_eval
        txa
        sbc     z:w_dist_high
        sta     z:w_eval_high
        rts
@Oblique:
        ; Oblique planes are immutable. Reuse the exact 32-bit result
        ; when both coordinates that contribute to the dot product match.
        sta     z:w_cache_coord_a
        lda     z:w_endpoint
        clc
        adc     z:w_axis_b
        tay
        lda     a:w_from,y
.if .defined(PLAYABLE_LARGE_DISTANCE_CACHE) .and !.defined(QC_BASIC_GAMEPLAY)
WalkObliqueDistanceCoordB:
.endif
        sta     z:w_cache_coord_b
.if .defined(QC_E1M3_GOLD_KEY)
        lda     z:w_plane
        bit     #4
        bne     @ComputeDistance
.elseif !.defined(QC_BASIC_GAMEPLAY)
        lda     z:w_plane
        and     #6
        bne     @ComputeDistance
.endif
.if .defined(POINT_SHOT) .and .defined(PLAYABLE_LARGE_DISTANCE_CACHE)
        ; Sight and footing traces can share a plane without sharing
        ; the start point. Keep the full comparisons at the selected row.
        lda     z:w_cache_coord_a
        asl
        eor     z:w_cache_coord_b
        xba
        eor     z:w_cache_coord_a
        eor     z:w_plane
.elseif .defined(PLAYABLE_LARGE_DISTANCE_CACHE)
        ; Player sweeps often revisit a plane from several support points.
        lda     z:w_cache_coord_a
        xba
        eor     z:w_cache_coord_b
        eor     z:w_plane
.else
        lda     z:w_plane
.endif
.if .defined(POINT_SHOT) && .defined(QC_DOG_FIRST)
        and     #POINT_DISTANCE_CACHE_MASK
.elseif .defined(QC_INTERMISSION_COUNT) && .defined(PLAYABLE_LARGE_DISTANCE_CACHE)
        and     a:.loword(intermission_walk_cache_mask)
.else
        and     #WALK_DISTANCE_CACHE_MASK
.endif
        asl
        tax
        lda     z:w_plane
        ora     #1                      ; A zeroed key is always invalid.
        cmp     a:w_distance_cache,x
        bne     @Miss
        lda     z:w_cache_coord_a
        cmp     a:w_distance_cache+2,x
        bne     @Miss
        lda     z:w_cache_coord_b
        cmp     a:w_distance_cache+4,x
        bne     @Miss
        lda     a:w_distance_cache+6,x
        sta     z:w_eval
        lda     a:w_distance_cache+8,x
        sta     z:w_eval_high
        rts
@Miss:
        stx     z:w_cache_slot
@ComputeDistance:
.ifdef PLAYABLE_FX3_PLANE_DISTANCE
        ; The baked painter has joined every refill. Its exclusive grant
        ; remains valid because the bridge waits for STOP on every call.
        lda     a:qc_fx3_plane_foreground
        beq     @CpuDistance
        bmi     @RunBakedDistance
        lda     f:FX3_R15
        bne     @CpuDistance
@RunFx3Distance:
        jsr     ::WalkPlaneDistanceFx3
  .ifdef PLAYABLE_LARGE_DISTANCE_CACHE
        jmp     @StoreDistance
  .else
        bra     @StoreDistance
  .endif
@RunBakedDistance:
        jsl     ::WalkPlaneDistanceBaked
  .ifdef PLAYABLE_LARGE_DISTANCE_CACHE
        jmp     @StoreDistance
  .else
        bra     @StoreDistance
  .endif
@CpuDistance:
.endif
.ifdef PLAYABLE_LARGE_DISTANCE_CACHE
        ; Stock 45-degree planes share one coefficient across both axes.
        ; Combine signed coordinates first when the sum fits a word.
        lda     z:w_coeff_a
        cmp     #11585
        bne     @TryRatioPair
        lda     z:w_plane
        bit     #6
        beq     :+
        jmp     @ProductPair           ; Keep translated planes on the ordinary path.
:
        lda     z:w_coeff_b
        cmp     #11585
        beq     @PairSum
        cmp     #.loword(-11585)
        beq     :+
        jmp     @ProductPair
:       lda     z:w_cache_coord_a
        sec
        sbc     z:w_cache_coord_b
        bra     @PairCombined
@PairSum:
        lda     z:w_cache_coord_a
        clc
        adc     z:w_cache_coord_b
@PairCombined:
        bvc     :+
        jmp     @ProductPair           ; Full signed inputs remain supported.
:
        tax
        QC_YIELD_COORDINATE_STREAM     ; X holds the combined coordinate.
        jsr     ::WalkProduct11585Signed
        jmp     @SubtractDistance
@TryRatioPair:
        ; The stock 2:1 bevels have a common factor of 7327. Only take
        ; this path when the doubled coordinate and final word both fit.
        cmp     #14654
        beq     @RatioDoubleA
        lda     z:w_coeff_b
        cmp     #14654
        bne     @ProductPair
        lda     z:w_coeff_a
        cmp     #7327
        beq     @RatioDoubleBAdd
        cmp     #.loword(-7327)
        bne     @ProductPair
        lda     z:w_cache_coord_b
        clc
        adc     z:w_cache_coord_b
        bvs     @ProductPair
        sec
        sbc     z:w_cache_coord_a
        bra     @RatioCombined
@RatioDoubleBAdd:
        lda     z:w_cache_coord_b
        clc
        adc     z:w_cache_coord_b
        bvs     @ProductPair
        clc
        adc     z:w_cache_coord_a
        bra     @RatioCombined
@RatioDoubleA:
        lda     z:w_coeff_b
        cmp     #7327
        beq     @RatioDoubleAAdd
        cmp     #.loword(-7327)
        bne     @ProductPair
        lda     z:w_cache_coord_a
        clc
        adc     z:w_cache_coord_a
        bvs     @ProductPair
        sec
        sbc     z:w_cache_coord_b
        bra     @RatioCombined
@RatioDoubleAAdd:
        lda     z:w_cache_coord_a
        clc
        adc     z:w_cache_coord_a
        bvs     @ProductPair
        clc
        adc     z:w_cache_coord_b
@RatioCombined:
        bvs     @ProductPair
        tay
        lda     z:w_plane
        bit     #6
        bne     @ProductPair
        tyx
        QC_YIELD_COORDINATE_STREAM
        jsr     ::WalkProduct7327Signed
        bra     @SubtractDistance
@ProductPair:
.endif
        lda     z:w_cache_coord_a
        ldx     z:w_coeff_a
        jsr     WalkMultiply
        lda     z:w_mul_low
        sta     z:w_eval
        lda     z:w_mul_high
        sta     z:w_eval_high
.ifdef PLAYABLE_LARGE_DISTANCE_CACHE
        ; The first product is saved and the next multiply reloads its latch.
        QC_YIELD_COORDINATE_STREAM
.endif
        lda     z:w_cache_coord_b
        ldx     z:w_coeff_b
        jsr     WalkMultiply
        lda     z:w_eval
        clc
        adc     z:w_mul_low
        sta     z:w_eval
        lda     z:w_eval_high
        adc     z:w_mul_high
        sta     z:w_eval_high
        lda     z:w_eval
.ifdef PLAYABLE_LARGE_DISTANCE_CACHE
@SubtractDistance:
.endif
        sec
        sbc     z:w_dist
        sta     z:w_eval
        lda     z:w_eval_high
        sbc     z:w_dist_high
        sta     z:w_eval_high
.ifdef PLAYABLE_FX3_PLANE_DISTANCE
@StoreDistance:
.endif
.if .defined(QC_E1M3_GOLD_KEY)
        lda     z:w_plane
        bit     #4
        beq     :+
        rts
:
.elseif !.defined(QC_BASIC_GAMEPLAY)
        lda     z:w_plane
        and     #6
        beq     :+
        rts
:
.endif
        ; Keep the exact lookup slot across the synchronous multiply.
        ldx     z:w_cache_slot
        clc                             ; The old index ASL always cleared carry.
        lda     z:w_plane
        ora     #1
        sta     a:w_distance_cache,x
        lda     z:w_cache_coord_a
        sta     a:w_distance_cache+2,x
        lda     z:w_cache_coord_b
        sta     a:w_distance_cache+4,x
        lda     z:w_eval
        sta     a:w_distance_cache+6,x
        lda     z:w_eval_high
        sta     a:w_distance_cache+8,x
        rts

; Unsigned 32-bit ratio with an inclusive 1.0, returned in Q12.
WalkFraction:
.if WALK_CACHE_AXIAL_SPLIT
        clc
.endif
WalkFractionWithWidth:
        POINT_TRACE_WORD_FRACTION @WordSize
.if .defined(POINT_SHOT) .and .defined(PLAYABLE_E1M1_TRACE_LAYOUT) .and .defined(PLAYABLE_MAP_ID)
        ; The low compare supplies the borrow for the unsigned high word.
        lda     z:w_numerator
        cmp     z:w_denominator
        lda     z:w_numerator_high
        sbc     z:w_denominator_high
        bcc     @Begin
.else
        lda     z:w_numerator_high
        cmp     z:w_denominator_high
        bcc     @Begin
        bne     @One
        lda     z:w_numerator
        cmp     z:w_denominator
        bcc     @Begin
@One:
.endif
        lda     #WALK_T_ONE
        rts
@Begin:
.if WALK_REGISTER_TRACE .or (.defined(WALK_IMPACT_CACHE_BYTES) .and !.defined(POINT_SHOT)) .or (.defined(QC_QUEUED_INPUT) .and .defined(POINT_SHOT))
        ; With a small denominator the doubled remainder cannot overflow a
        ; word. Keep it in A and shift the compare carry into the Q12 result.
        lda     z:w_denominator_high
.if .defined(POINT_SHOT) .and .defined(PLAYABLE_E1M1_WIDE_Q3)
        bne     @WideCached
.else
        bne     @Wide
.endif
@WordSize:
        lda     z:w_denominator
        cmp     #$8001
        bcs     @Wide
.ifdef QC_QUEUED_INPUT
        cmp     #256
        bcs     @SoftwareSmall
        lda     z:w_numerator
        beq     @SmallDone
        jmp     WalkFractionByte
@SoftwareSmall:
  .ifdef WALK_TRACE_FOOT_FRACTION
        cmp     #36*8
        beq     @FootFraction
  .endif
.endif
        lda     z:w_numerator
        beq     @SmallDone
.if .defined(POINT_SHOT) .and (.defined(PLAYABLE_LARGE_DISTANCE_CACHE) .or .defined(PLAYABLE_KNIGHT_POINT_FRACTIONS))
        jmp     WalkFractionSmallCached
.else
        WALK_FRACTION_SMALL_DIGITS @SmallDigit
        lda     z:w_fraction
.endif
@SmallDone:
        rts
  .ifdef WALK_TRACE_FOOT_FRACTION
@FootFraction:
        ; The exact table serves both the Q3 footing and Q4 step sweeps.
        lda     z:w_numerator
        asl
        tax
        lda     f:::ShotHullData+WALK_TRACE_FOOT_FRACTION,x
        rts
  .endif
.if .defined(POINT_SHOT) .and .defined(PLAYABLE_E1M1_WIDE_Q3)
@WideCached:
        jsl     ::PointWideFractionLookup
        bcs     @WideHit
        jsr     @Wide
        jsl     ::PointWideFractionPublish
        rts
@WideHit:
        ldx     #0
        lda     z:w_fraction
        clc
        rts
.endif
@Wide:
.endif
.ifdef QC_QUEUED_INPUT
        ; Keep the high remainder in A and append each quotient bit from
        ; carry. The split consumes only the returned Q12 value.
        phy
        ldx     #12
        lda     z:w_numerator_high
@Digit:
        asl     z:w_numerator
        rol
        bcs     @Subtract
        cmp     z:w_denominator_high
        bcc     @Next
        bne     @Subtract
        tay
        lda     z:w_numerator
        cmp     z:w_denominator
        tya
        bcc     @Next
@Subtract:
        tay
        lda     z:w_numerator
        sec
        sbc     z:w_denominator
        sta     z:w_numerator
        tya
        sbc     z:w_denominator_high
        sec
@Next:
        rol     z:w_fraction
        dex
        bne     @Digit
        sta     z:w_numerator_high
        ply
        lda     z:w_fraction
        rts
.else
        ldx     #12
@Digit:
        asl     z:w_fraction
        asl     z:w_numerator
        rol     z:w_numerator_high
        bcs     @Subtract
        lda     z:w_numerator_high
        cmp     z:w_denominator_high
        bcc     @Next
        bne     @Subtract
        lda     z:w_numerator
        cmp     z:w_denominator
        bcc     @Next
@Subtract:
        lda     z:w_numerator
        sec
        sbc     z:w_denominator
        sta     z:w_numerator
        lda     z:w_numerator_high
        sbc     z:w_denominator_high
        sta     z:w_numerator_high
        inc     z:w_fraction
@Next:
        dex
        bne     @Digit
        lda     z:w_fraction
        rts
.endif

.if .defined(QC_BASIC_GAMEPLAY)
.include "quake/PlayerWalkThreeAxes.s"
.endif
