; Playable scanout is planar at both scales, leaving the PPU multiplier
; available. The standalone path retains the S-CPU multiplication routine.
.if .defined(PLAYABLE_WALK_HULL_EXIT_GUARD) || .defined(PLAYABLE_FAST_WALK_PPU_MUL)
WALK_PPU_SIGNED_DIGITS = 1
.endif
.if .defined(PLAYABLE_E1M1_TRACE_LAYOUT) .and .defined(PLAYABLE_MAP_ID)
; The signed-digit paths also produce exact zero products. Limit the
; specialized entry to the relocated link so the sizing layout is stable.
WALK_PPU_ZERO_DIGITS = 1
.endif
WalkMultiply:
.ifdef QC_QUEUED_INPUT
        sta     z:w_mul_a
  .ifndef WALK_PPU_SIGNED_DIGITS
        stx     z:w_mul_b
  .endif
  .ifndef WALK_PPU_ZERO_DIGITS
        cmp     #0
        beq     @Zero
        cpx     #0
        bne     @Latch
@Zero:
        stz     z:w_mul_low
        stz     z:w_mul_high
        rts
    .if .defined(PLAYABLE_LARGE_DISTANCE_CACHE) || .defined(PLAYABLE_FAST_WALK_PPU_MUL)
@RetryLatch:
        RW_forced a16i16
        lda     z:w_mul_a
    .endif
  .endif
@Latch:
        RW      a8
@LatchByte:
  .if .defined(PLAYABLE_LARGE_DISTANCE_CACHE) || .defined(PLAYABLE_FAST_WALK_PPU_MUL)
        ; A holds the multiplicand. Retry the two stores if VBlank
        ; writes the shared BG1 scroll latch between them.
        stz     z:w_ppu_latch_nmi
        sta     f:M7A
        xba
        sta     f:M7A
        lda     z:w_ppu_latch_nmi
        bne     @RetryLatch
  .else
        ; Compare the low video tick across the bounded M7A write pair.
        lda     f:video_tick
        sta     z:w_mul_nmi
        lda     z:w_mul_a
        sta     f:M7A
        lda     z:w_mul_a+1
        sta     f:M7A
        lda     f:video_tick
        cmp     z:w_mul_nmi
        bne     @LatchByte
  .endif

  .ifdef WALK_PPU_SIGNED_DIGITS
        txa
        beq     @ZeroLowDigit
  .else
        lda     z:w_mul_b
  .endif
        sta     f:M7B
        RW      a16
        lda     f:MPYL
        sta     z:w_mul_low
  .ifdef WALK_PPU_SIGNED_DIGITS
        ; The preceding word load already retained the middle byte.
        RW      a8
        lda     f:MPYH
        sta     z:w_mul_high
  .else
        lda     f:MPYM
        sta     z:w_mul_low+1
        RW      a8
  .endif
        bpl     :+
        lda     #$ff
        bra     @ExtendLow
:       lda     #0
@ExtendLow:
        sta     z:w_mul_high+1
        RW      a16
  .ifdef WALK_PPU_SIGNED_DIGITS
        txa
  .else
        lda     z:w_mul_b
  .endif
        clc
        adc     #128
  .ifdef WALK_PPU_SIGNED_DIGITS
        ; The carry from rounding can only occur for a signed-byte factor.
        ; BIT retains both carry and the overflow needed for +128 high.
        bit     #$ff00
        beq     @DoneByte
        bvs     @HighOverflow
@AddHighDigit:
        xba
  .else
        cmp     #256
        bcc     @Done16
  .endif
        RW      a8
  .ifndef WALK_PPU_SIGNED_DIGITS
        lda     z:w_mul_b+1
  .endif
        sta     f:M7B
        RW      a16
        lda     f:MPYL
  .ifndef WALK_PPU_SIGNED_DIGITS
        clc
  .endif
        adc     z:w_mul_low+1
        sta     z:w_mul_low+1
        RW      a8
        lda     f:MPYH
        adc     z:w_mul_high+1
        sta     z:w_mul_high+1

  .ifndef WALK_PPU_SIGNED_DIGITS
        ; A negative low digit represents B.low - 256. Add A to the
        ; upper three-byte lane to restore the unsigned low digit.
        lda     z:w_mul_b
        bpl     @Done8
        RW      a16
        lda     z:w_mul_a
        clc
        adc     z:w_mul_low+1
        sta     z:w_mul_low+1
        RW      a8
        lda     z:w_mul_a+1
        bpl     :+
        lda     #$ff
        bra     @ExtendCorrection
:       lda     #0
@ExtendCorrection:
        adc     z:w_mul_high+1
        sta     z:w_mul_high+1
@Done8:
  .endif
        RW      a16
@Done16:
        rts
  .ifdef WALK_PPU_ZERO_DIGITS
@RetryLatch:
        RW_forced a16i16
        lda     z:w_mul_a
        bra     @Latch
  .endif
  .ifdef WALK_PPU_SIGNED_DIGITS
@DoneByte:
        ; Preserve all flags from the original signed-byte return.
        cmp     #256
        rts
@HighOverflow:
        ; The high digit +128 was sent as -128. Add A * 65536.
        jsr     @AddHighDigit
        lda     z:w_mul_high
        clc
        adc     z:w_mul_a
        sta     z:w_mul_high
        rts
@ZeroLowDigit:
        ; B is its signed high byte times 256. Shift the one product by a byte.
        RW_assume a8
        RW      a16
        txa
        xba
        RW      a8
        sta     f:M7B
        RW      a16
        lda     f:MPYL
        sta     z:w_mul_low+1
        RW      a8
        stz     z:w_mul_low
        lda     f:MPYH
        sta     z:w_mul_high+1
        RW      a16
    .ifdef WALK_PPU_ZERO_DIGITS
        sec                            ; Preserve carry from the former CPX.
    .endif
        rts
  .endif
.else
        ; The VBlank handler also uses the S-CPU multiplier.
        sta     z:w_mul_a
        stx     z:w_mul_b
        cmp     #0
        bne     :+
        jmp     @Zero
:
        cpx     #0
        bne     @Retry
        jmp     @Zero
@Retry:
        lda     f:video_tick
        sta     z:w_mul_nmi
        RW      a8
        lda     z:w_mul_a
        sta     f:WRMPYA
        lda     z:w_mul_b
        sta     f:WRMPYB
        stz     z:w_mul_high
        stz     z:w_mul_high+1
        RW      a16
        lda     f:RDMPYL
        sta     z:w_mul_low
        RW      a8
        lda     z:w_mul_a+1
        sta     f:WRMPYA
        lda     z:w_mul_b
        sta     f:WRMPYB
        RW      a16
        nop
        nop
        nop
        lda     f:RDMPYL
        clc
        adc     z:w_mul_low+1
        sta     z:w_mul_low+1
        RW      a8
        lda     #0
        adc     #0
        sta     z:w_mul_high+1
        lda     z:w_mul_a
        sta     f:WRMPYA
        lda     z:w_mul_b+1
        sta     f:WRMPYB
        RW      a16
        nop
        nop
        nop
        lda     f:RDMPYL
        clc
        adc     z:w_mul_low+1
        sta     z:w_mul_low+1
        RW      a8
        lda     z:w_mul_high+1
        adc     #0
        sta     z:w_mul_high+1
        lda     z:w_mul_a+1
        sta     f:WRMPYA
        lda     z:w_mul_b+1
        sta     f:WRMPYB
        RW      a16
        nop
        nop
        nop
        lda     f:RDMPYL
        clc
        adc     z:w_mul_high
        ldx     z:w_mul_a
        bpl     :+
        sec
        sbc     z:w_mul_b
:       ldx     z:w_mul_b
        bpl     :+
        sec
        sbc     z:w_mul_a
:       sta     z:w_mul_high
        lda     f:video_tick
        cmp     z:w_mul_nmi
        beq     @Done
        jmp     @Retry
@Zero:
        stz     z:w_mul_low
        stz     z:w_mul_high
@Done:
        rts
.endif

.assert w_mul_high = w_mul_low + 2, error, "Walk product bytes must be contiguous"

.ifdef QC_QUEUED_INPUT
; For n < d < 256, divide n*4096 in one or two hardware operations.
; The two-operation case takes eight quotient bits first, then four
; more from the exact remainder. NMI may use the same result registers.
WalkFractionByte:
@Retry:
        lda     f:video_tick
        sta     z:w_mul_nmi
        lda     z:w_numerator
        cmp     #16
        bcc     @SingleDigit
        xba
        jsr     WalkDivideByte
        .repeat 4
        asl
        .endrepeat
        sta     z:w_fraction
        lda     f:RDMPYL
        bra     @FinalDigit
@SingleDigit:
        xba
@FinalDigit:
        .repeat 4
        asl
        .endrepeat
        jsr     WalkDivideByte
        ora     z:w_fraction
        tax
        lda     f:video_tick
        cmp     z:w_mul_nmi
        bne     @Retry
        txa
        rts

WalkDivideByte:
        WALK_DIVIDE_WORD_BY_BYTE w_denominator
        rts
.endif

WalkProductQ12:
.ifdef QC_QUEUED_INPUT
        lda     z:w_mul_high
        .repeat 2
        asl     z:w_mul_low
        rol
        .endrepeat
        bra     WalkProductLastTwo
WalkProductQ14:
        lda     z:w_mul_high
WalkProductLastTwo:
        .repeat 2
        asl     z:w_mul_low
        rol
        .endrepeat
        sta     z:w_mul_high
        rts
.else
        asl     z:w_mul_low
        rol     z:w_mul_high
        asl     z:w_mul_low
        rol     z:w_mul_high
WalkProductQ14:
        asl     z:w_mul_low
        rol     z:w_mul_high
        asl     z:w_mul_low
        rol     z:w_mul_high
        lda     z:w_mul_high
        rts
.endif

; Multiply a signed word in X by a fixed collision coefficient.
; Return the low word in A and high word in w_eval_high. X/Y are scratch.
.ifdef PLAYABLE_LARGE_DISTANCE_CACHE
.macro WALK_PRODUCT_TABLES coefficient, low_table, high_table
.pushseg
.segment "BSP_QUAKEC_BYTECODE"
low_table:
  .repeat 256, I
        .dword coefficient * I
  .endrepeat
high_table:
  .repeat 256, I
    .if I < 128
        .dword (coefficient * I) << 8
    .else
        .dword ((coefficient * (I - 256)) << 8) & $ffffffff
    .endif
  .endrepeat
.popseg
.endmacro
.macro WALK_PRODUCT_FIXED low_table, high_table
        txa
        tay
        and     #$00ff
        asl
        asl
        tax
        lda     f:low_table,x
        sta     z:w_eval
        lda     f:low_table+2,x
        sta     z:w_eval_high
        tya
        xba
        and     #$00ff
        asl
        asl
        tax
        lda     f:high_table,x
        clc
        adc     z:w_eval
        sta     z:w_eval
        lda     f:high_table+2,x
        adc     z:w_eval_high
        sta     z:w_eval_high
        lda     z:w_eval
        rts
.endmacro
WALK_PRODUCT_TABLES 11585, WalkProduct11585Low, WalkProduct11585High
WALK_PRODUCT_TABLES 7327, WalkProduct7327Low, WalkProduct7327High
WalkProduct11585Signed:
        WALK_PRODUCT_FIXED WalkProduct11585Low, WalkProduct11585High
WalkProduct7327Signed:
        WALK_PRODUCT_FIXED WalkProduct7327Low, WalkProduct7327High
.delmacro WALK_PRODUCT_TABLES
.delmacro WALK_PRODUCT_FIXED
.endif
