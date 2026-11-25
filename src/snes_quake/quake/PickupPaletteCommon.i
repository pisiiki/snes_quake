; Shared foreground palette staging and the 256-color component translation.
.pushseg
.segment "EXRAM"
PickupPalettePixels: .res 512
pickup_palette_build: .res 2
pickup_palette_phase: .res 2
pickup_palette_rg: .res 2
.popseg

.macro PICKUP_COLOR_LOOP Tables, Stride
        .local Color
        ldx     #0
Color: phx
        lda     a:$0000,y
        pha
        and     #31
        ora     f:pickup_palette_phase
        tax
        lda     f:Tables,x
        and     #31
        sta     f:pickup_palette_rg
        lda     1,s
        .repeat 5
          lsr
        .endrepeat
        and     #31
        ora     f:pickup_palette_phase
        tax
        lda     f:Tables+Stride,x
        and     #31
        .repeat 5
          asl
        .endrepeat
        ora     f:pickup_palette_rg
        sta     f:pickup_palette_rg
        pla
        xba
        lsr
        lsr
        and     #31
        ora     f:pickup_palette_phase
        tax
        lda     f:Tables+2*Stride,x
        and     #31
        xba
        asl
        asl
        ora     f:pickup_palette_rg
        plx
        sta     f:PickupPalettePixels,x
        iny
        iny
        inx
        inx
        cpx     #512
        bne     Color
.endmacro

