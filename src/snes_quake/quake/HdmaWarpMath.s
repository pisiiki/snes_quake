; Bank-local math. D points at hdma_work, DB remains the CPU's I/O bank.
.segment "HDMA_WARP_CODE"

; Signed A * X -> 32-bit hdma_product. Hardware 8x8 products never touch
; the live PPU's Mode 7 multiplier. Each read has >=8 CPU cycles of latency.
HdmaMultiply:
        sta     z:hdma_mul_a-hdma_work
        stx     z:hdma_mul_b-hdma_work
        lda     hdma_nmi_counter
        sta     z:hdma_math_interrupt-hdma_work
        lda     z:hdma_mul_a-hdma_work
        RW      a8
        sta     WRMPYA
        lda     z:hdma_mul_b-hdma_work
        sta     WRMPYB
        stz     z:hdma_product+2-hdma_work
        stz     z:hdma_product+3-hdma_work
        RW      a16
        lda     RDMPYL
        sta     z:hdma_product-hdma_work
        RW      a8
        lda     z:hdma_mul_a+1-hdma_work
        sta     WRMPYA
        lda     z:hdma_mul_b-hdma_work
        sta     WRMPYB
        RW      a16
        nop
        nop
        nop
        lda     RDMPYL
        clc
        adc     z:hdma_product+1-hdma_work
        sta     z:hdma_product+1-hdma_work
        RW      a8
        lda     #0
        adc     #0
        sta     z:hdma_product+3-hdma_work
        lda     z:hdma_mul_a-hdma_work
        sta     WRMPYA
        lda     z:hdma_mul_b+1-hdma_work
        sta     WRMPYB
        RW      a16
        nop
        nop
        nop
        lda     RDMPYL
        clc
        adc     z:hdma_product+1-hdma_work
        sta     z:hdma_product+1-hdma_work
        RW      a8
        lda     z:hdma_product+3-hdma_work
        adc     #0
        sta     z:hdma_product+3-hdma_work
        lda     z:hdma_mul_a+1-hdma_work
        sta     WRMPYA
        lda     z:hdma_mul_b+1-hdma_work
        sta     WRMPYB
        RW      a16
        nop
        nop
        nop
        lda     RDMPYL
        clc
        adc     z:hdma_product+2-hdma_work
        ldx     z:hdma_mul_a-hdma_work
        bpl     :+
        sec
        sbc     z:hdma_mul_b-hdma_work
:
        ldx     z:hdma_mul_b-hdma_work
        bpl     :+
        sec
        sbc     z:hdma_mul_a-hdma_work
:
        sta     z:hdma_product+2-hdma_work
        lda     hdma_nmi_counter
        cmp     z:hdma_math_interrupt-hdma_work
        beq     :+
        lda     z:hdma_mul_a-hdma_work
        ldx     z:hdma_mul_b-hdma_work
        jmp     HdmaMultiply
:
        rts

HdmaMultiplyQ12:
        jsr     HdmaQuarterProduct
        bcs     @Slow
        bit     z:hdma_mul_sign-hdma_work
        bpl     @Positive
        clc
        adc     #3
        lsr
        lsr
        neg
        rts
@Positive:
        lsr
        lsr
        rts
@Slow:
        jsr     HdmaMultiply
        lda     z:hdma_product+2-hdma_work
        clc
        adc     #$0800
        cmp     #$1000
        bcc     :+
        inc     z:hdma_fault-hdma_work
:
        lda     z:hdma_product+2-hdma_work
        asl
        asl
        asl
        asl
        and     #$F000
        sta     z:hdma_partial-hdma_work
        lda     z:hdma_product+1-hdma_work
        lsr
        lsr
        lsr
        lsr
        ora     z:hdma_partial-hdma_work
        rts

HdmaMultiplyQ10:
        jsr     HdmaQuarterProduct
        bcs     @Slow
        cmp     #$8000
        bcc     :+
        bne     @Overflow
        bit     z:hdma_mul_sign-hdma_work
        bmi     :+                    ; -32768 is representable.
@Overflow:
        inc     z:hdma_fault-hdma_work
:
        bit     z:hdma_mul_sign-hdma_work
        bpl     :+
        neg
:
        rts
@Slow:
        jsr     HdmaMultiply
        lda     z:hdma_product+2-hdma_work
        clc
        adc     #$0200
        cmp     #$0400
        bcc     :+
        inc     z:hdma_fault-hdma_work
:
        lda     z:hdma_product+2-hdma_work
        .repeat 6
          asl
        .endrepeat
        and     #$C000
        sta     z:hdma_partial-hdma_work
        lda     z:hdma_product+1-hdma_work
        lsr
        lsr
        ora     z:hdma_partial-hdma_work
        rts

; Two ROM reads replace four MMIO products in the common bounded domain.
; floor((a+b)^2/4096)-floor((a-b)^2/4096) differs from a*b/1024 by <1.
; Carry set returns the original A/X for the full 32-bit fallback.
HdmaQuarterProduct:
        sta     z:hdma_mul_a-hdma_work
        stx     z:hdma_mul_b-hdma_work
        txa
        eor     z:hdma_mul_a-hdma_work
        sta     z:hdma_mul_sign-hdma_work
        txa
        bpl     :+
        neg
:
        sta     z:hdma_product+2-hdma_work
        lda     z:hdma_mul_a-hdma_work
        bpl     :+
        neg
:
        sta     z:hdma_product-hdma_work
        clc
        adc     z:hdma_product+2-hdma_work
        bcs     @Slow
        cmp     #16384
        bcs     @Slow
        asl
        tax
        lda     f:HdmaQuarterSquare,x
        sta     z:hdma_partial-hdma_work
        lda     z:hdma_product-hdma_work
        sec
        sbc     z:hdma_product+2-hdma_work
        bpl     :+
        neg
:
        asl
        tax
        lda     z:hdma_partial-hdma_work
        sec
        sbc     f:HdmaQuarterSquare,x
        clc
        rts
@Slow:
        lda     z:hdma_mul_a-hdma_work
        ldx     z:hdma_mul_b-hdma_work
        sec
        rts

; Q12 derivative -> Mode 7 8.8 / three. Nearest, ties away from zero.
HdmaSlope:
        sta     z:hdma_div_input-hdma_work
        lda     hdma_nmi_counter
        sta     z:hdma_math_interrupt-hdma_work
        lda     z:hdma_div_input-hdma_work
        sta     z:hdma_partial-hdma_work
        bpl     :+
        neg
:
        clc
        adc     #24
        sta     WRDIVL
        RW      a8
        lda     #48
        sta     WRDIVB
        RW      a16
        .repeat 7
          nop
        .endrepeat
        lda     RDDIVL
        pha
        lda     hdma_nmi_counter
        cmp     z:hdma_math_interrupt-hdma_work
        beq     :+
        pla
        lda     z:hdma_div_input-hdma_work
        jmp     HdmaSlope
:
        pla
        bit     z:hdma_partial-hdma_work
        bpl     :+
        neg
:
        rts

; Nearest 1/4096-turn lookup, no interpolation between camera records.
HdmaSin:
        clc
        adc     #8
        .repeat 4
          lsr
        .endrepeat
        sta     z:hdma_angle-hdma_work
        and     #1023
        sta     z:hdma_partial-hdma_work
        lda     z:hdma_angle-hdma_work
        and     #$0400
        beq     @Forward
        lda     #1024
        sec
        sbc     z:hdma_partial-hdma_work
        bra     @Lookup
@Forward:
        lda     z:hdma_angle-hdma_work
        and     #1023
@Lookup:
        asl
        tax
        lda     f:HdmaSine,x
        ldx     z:hdma_angle-hdma_work
        pha
        txa
        and     #$0800
        beq     :+
        pla
        neg
        rts
:
        pla
        rts

HdmaTargetSin:
        ldx     hdma_build_precise
        bne     HdmaSin
        xba
        and     #255
        tax
        RW      a8
        lda     f:CameraAngleSin,x
        RW      a16
        and     #255
        cmp     #128
        bcc     :+
        ora     #$FF00
:
        .repeat 6
          asl
        .endrepeat
        rts
