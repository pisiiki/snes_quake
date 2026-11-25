.ifdef WALK_TRACE_SECRET_BOUNDS
.assert WALK_HULL_STACK_ENTRIES > WALK_TRACE_SECRET_STACK, error, "Secret tail exceeds trace stack capacity"
  .ifdef WALK_TRACE_MOVER_TAIL_GUARD
        .assert ::PLAYABLE_SHOT_TAIL_STACK_ENTRIES < WALK_HULL_STACK_ENTRIES, error, "Point mover tail exceeds trace stack"
        .assert ::PLAYABLE_SHOT_TAIL_FIRST_DEBT < WALK_MAX_NODES_PER_TRACE, error, "Point mover tail exceeds visit budget"
; Keep the existing bucket reader in the VM bank. Its carry result and the
; resident trace continuations cross banks through long calls and jumps.
@SecretBucketFar:
        jsr     ::ShotHull::WalkSecretBucketPossible
        rtl
.pushseg
.segment "BSP_CPU_WALK_RUN"
; The generated cell admits only vertical rays whose entire mover tail is
; empty. Keep the current outer interval and stack intact. The normal EMPTY
; path restores the next world interval exactly as the original tail does.
@CertifiedMoverTail:
        iny                            ; The new guard itself is synthetic.
        lda     a:w_secret_tail_state
        bmi     @MoverTailFallback
        bit     #2
        beq     @MoverTailFallback
        lda     z:w_sp
        cmp     #(WALK_HULL_STACK_ENTRIES-::PLAYABLE_SHOT_TAIL_STACK_ENTRIES)*8+1
        bcs     @MoverTailFallback
        lda     a:w_secret_tail_state
        bit     #4
        bne     @MoverTailRepeat
        ora     #4
        sta     a:w_secret_tail_state
        tya
        sec
        sbc     #::PLAYABLE_SHOT_TAIL_FIRST_DEBT
        bra     @MoverTailCharge
@MoverTailRepeat:
        tya
        sec
        sbc     #::PLAYABLE_SHOT_TAIL_MORE_DEBT
@MoverTailCharge:
        bcc     @TailRetry
        beq     @TailRetry
        tay
        QC_YIELD_COORDINATE_STREAM
        lda     #$FFFF
        jml     @Visit
@MoverTailFallback:
        jml     @FastFront               ; The front pointer names the original first node.
  .endif

@TrySecretTail:
        lda     a:w_secret_tail_state
        bmi     @SecretTailUnproven
        lda     z:w_sp
        cmp     #(WALK_HULL_STACK_ENTRIES-WALK_TRACE_SECRET_STACK)*8+1
        bcs     @SecretTailUnproven
  .ifdef WALK_TRACE_MOVER_TAIL_GUARD
        jsl     @SecretBucketFar
  .elseif .defined(POINT_SHOT)
        jsr     ::ShotHull::WalkSecretBucketPossible
  .else
        jsr     WalkSecretBucketPossible
  .endif
        bcs     @SecretTailUnproven

        ; Reserve visits for omitted work and retain one ordinary EMPTY visit.
  .ifdef WALK_TRACE_MOVER_TAIL_GUARD
        lda     a:w_secret_tail_state
        bit     #1
        bne     @SecretTailRepeat
        ora     #1
        sta     a:w_secret_tail_state
        tya
        sec
        sbc     #WALK_TRACE_SECRET_FIRST
        bra     @SecretTailCharge
@SecretTailRepeat:
        tya
        sec
  .else
        tya
        sec
        ldx     a:w_secret_tail_state
        bne     @SecretTailRepeat
        inc     a:w_secret_tail_state
        sbc     #WALK_TRACE_SECRET_FIRST
        bra     @SecretTailCharge
@SecretTailRepeat:
  .endif
        sbc     #WALK_TRACE_SECRET_MORE
@SecretTailCharge:
        bcc     @TailRetry
        beq     @TailRetry
        tay
        lda     #$FFFF
  .ifdef WALK_TRACE_MOVER_TAIL_GUARD
        jml     @Visit
@SecretTailUnproven:
        jml     @FastBack
  .else
        jmp     @Visit
@SecretTailUnproven:
        jmp     @FastBack
  .endif

@TraceFaultCheck:
        lda     a:w_secret_tail_state
  .ifdef WALK_TRACE_MOVER_TAIL_GUARD
        bmi     @MoverTailFault
        bit     #5
        beq     @MoverTailFault
  .else
        cmp     #1
        bne     WalkTraceFault
  .endif
@TailRetry:
        ; A conservative charge can reach the cap early. Retry once before
        ; publishing the hit or consuming any fault counter.
        lda     #$FFFF
        sta     a:w_secret_tail_state
  .ifdef WALK_TRACE_MOVER_TAIL_GUARD
        jml     @TraceInit
@MoverTailFault:
        jml     WalkTraceFault
.popseg
  .else
        jmp     @TraceInit
  .endif
.endif
