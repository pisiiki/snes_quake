; The foreground owns this scratch until the next simulation transaction.
PickupDryRed = WalkTraceStack
PickupDryGreen = PickupDryRed + 64
PickupDryBlue = PickupDryGreen + 64
PickupDryMask = PickupDryBlue + 64
.assert SHOT_HULL_STACK_ENTRIES * 8 >= 196 .or WALK_HULL_STACK_ENTRIES * 8 >= 196, error, "Pickup channels exceed trace scratch"

.macro PICKUP_EXPAND_CHANNEL source, destination, shift
        .local color
        lda     f:source+1,x
        sta     a:.loword(PickupDryMask)
        lda     f:source+3,x
        sta     a:.loword(PickupDryMask)+2
        lda     f:source,x
        and     #31
        .repeat shift
        asl
        .endrepeat
        ldy     #0
color:  sta     a:.loword(destination),y
        lsr     a:.loword(PickupDryMask)+2
        ror     a:.loword(PickupDryMask)
        bcc     :+
        adc     #((1 << shift) - 1)    ; Carry includes the unit increment.
:       iny
        iny
        cpy     #64
        bne     color
.endmacro

.pushseg
.segment "BSP_CPU_PICKUP_PALETTE"
PickupBuildDryColors:
        RW_assume a16i16
        phb
        phy
        pea     $7f7f
        plb
        plb
        lda     f:pickup_palette_phase
        .repeat 5
        lsr
        .endrepeat
        pha
        asl
        asl
        clc
        adc     1,s
        plx
        tax
        PICKUP_EXPAND_CHANNEL PICKUP_BLEND, PickupDryRed, 0
        PICKUP_EXPAND_CHANNEL PICKUP_BLEND+90*5, PickupDryGreen, 5
        PICKUP_EXPAND_CHANNEL PICKUP_BLEND+2*90*5, PickupDryBlue, 10
.if .defined(PLAYABLE_E1M1_TRACE_LAYOUT) && .defined(PLAYABLE_MAP_ID)
        ; Palette work runs between gameplay transactions, as does the
        ; trace-stack channel scratch above. Keep DB on the output bank.
        .assert w_mul_b = w_mul_a+2, error, "Palette source pointer needs three consecutive bytes"
        ply
        sty     z:w_mul_a
        RW      a8
        lda     1,s                     ; Source bank saved by PHB.
        sta     z:w_mul_b
        RW      a16
        ldy     #0
@Color:
        lda     [w_mul_a],y
        sta     z:w_mul_low
        and     #31
        asl
        tax
        lda     a:.loword(PickupDryRed),x
        sta     z:w_mul_high
        lda     z:w_mul_low
        .repeat 4
        lsr
        .endrepeat
        and     #62
        tax
        lda     a:.loword(PickupDryGreen),x
        ora     z:w_mul_high
        sta     z:w_mul_high
        lda     z:w_mul_low
        xba
        lsr
        and     #62
        tax
        lda     a:.loword(PickupDryBlue),x
        ora     z:w_mul_high
        sta     a:.loword(PickupPalettePixels),y
        iny
        iny
        cpy     #512
        bne     @Color
        plb
.else
        ply
        plb

        ldx     #0
@Color:
        phx
        lda     a:$0000,y
        and     #31
        asl
        tax
        lda     f:PickupDryRed,x
        sta     f:pickup_palette_rg
        lda     a:$0000,y
        .repeat 4
        lsr
        .endrepeat
        and     #62
        tax
        lda     f:PickupDryGreen,x
        ora     f:pickup_palette_rg
        sta     f:pickup_palette_rg
        lda     a:$0000,y
        xba
        lsr
        and     #62
        tax
        lda     f:PickupDryBlue,x
        ora     f:pickup_palette_rg
        plx
        sta     f:PickupPalettePixels,x
        iny
        iny
        inx
        inx
        cpx     #512
        bne     @Color
.endif
        rtl
.popseg
.delmacro PICKUP_EXPAND_CHANNEL
