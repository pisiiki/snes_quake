; Quake composes view contents, damage, bonus and powerup in 8-bit RGB,
; quantizing only the final color to SNES BGR555. Build 96 channel values
; once per new key and reuse them for every color in the physical CGRAM image.
; Palette preparation runs between complete foreground simulation transactions.
; The hull traversal stack is idle here and the NMI reads only the published CGRAM image.
WaterPaletteChannels = WalkTraceStack + 0
water_palette_channel = WalkTraceStack + 97
water_palette_index = WalkTraceStack + 99
water_palette_fluid = WalkTraceStack + 101
water_palette_bonus = WalkTraceStack + 103
water_palette_gold = WalkTraceStack + 105
water_palette_power = WalkTraceStack + 107
water_palette_power_dest = WalkTraceStack + 109
water_palette_flash = WalkTraceStack + 111
water_palette_value = WalkTraceStack + 113
water_palette_difference = WalkTraceStack + 115
water_palette_nmi = WalkTraceStack + 117
.assert SHOT_HULL_STACK_ENTRIES * 8 >= 119 .or WALK_HULL_STACK_ENTRIES * 8 >= 119, error, "Water palette scratch exceeds the traversal stack"

.pushseg
.segment "BSP_CPU_LANDING"
WaterBuildPalette:
        RW_assume a16i16
        phb
        phx
        phy
        sta     f:pickup_palette_build
        lda     #0
        sta     f:pickup_palette_ready
        sta     f:pickup_palette_phase
        sta     f:water_palette_channel
        sta     f:water_palette_index
        lda     f:pickup_palette_build
        xba
        and     #31
        tax
        lda     f:WaterPaletteBonus,x
        and     #$ff
        sta     f:water_palette_bonus
        lda     f:pickup_palette_build
        bit     #$40
        beq     :+
        lda     #96
        bra     :++
:       lda     #0
:       sta     f:water_palette_fluid

@Channel:
        lda     f:water_palette_channel
        tax
        lda     f:WaterPaletteGold,x
        sta     f:water_palette_gold
        lda     f:pickup_palette_build
        and     #$1c
        cmp     #4                     ; Weapon OBJ damage effect.
        bne     :+
        lda     f:WaterPaletteDamage,x
        bra     @Flash
:       cmp     #8                     ; Weapon OBJ muzzle effect.
        bne     :+
        lda     f:WaterPaletteMuzzle,x
        bra     @Flash
:       lda     #0
@Flash: sta     f:water_palette_flash
        lda     f:pickup_palette_build
        bit     #$4000
        bne     @Quad
        bit     #$8000
        bne     @Suit
        lda     #0
        bra     @Power
@Quad:  lda     #30
        cpx     #4
        bra     @Power
@Suit:  lda     #20
        cpx     #2
@Power: sta     f:water_palette_power
        beq     :+
        lda     #0
        bra     @Destination
:       lda     #255
@Destination:
        sta     f:water_palette_power_dest
@Component:
        lda     f:water_palette_index
        clc
        adc     f:water_palette_fluid
        tax
        lda     f:WaterPaletteContents,x
        and     #$ff
        clc
        adc     f:water_palette_flash
        cmp     #249
        bcc     :+
        lda     #248
:       pha
        lda     f:water_palette_gold
        tax
        lda     f:water_palette_bonus
        tay
        pla
        jsr     WaterPaletteShift
        pha
        lda     f:water_palette_power_dest
        tax
        lda     f:water_palette_power
        tay
        pla
        jsr     WaterPaletteShift
        lsr
        lsr
        lsr
        pha
        lda     f:water_palette_index
        tax
        inc
        sta     f:water_palette_index
        pla
        RW      a8
        sta     f:WaterPaletteChannels,x
        RW      a16
        inx
        txa
        and     #31
        bne     @Component
        lda     f:water_palette_channel
        inc
        inc
        sta     f:water_palette_channel
        cmp     #6
        bcs     :+
        jmp     @Channel
:       lda     f:pickup_palette_build
        and     #3
        asl
        asl
        tax
        lda     f:WaterSceneSources,x
        tay
        RW      a8
        lda     f:WaterSceneSources+2,x
        pha
        plb
        RW      a16
        PICKUP_COLOR_LOOP WaterPaletteChannels, 32
        lda     f:pickup_palette_build
        sta     f:pickup_palette_ready
        ply
        plx
        plb
        rtl

; A is the source, X the target, and Y the 8-bit strength. A negative
; difference's unsigned low byte contributes one extra strength to the high byte.
WaterPaletteShift:
        cpy     #0
        beq     @Done
        sta     f:water_palette_value
        txa
        sec
        sbc     f:water_palette_value
        sta     f:water_palette_difference
@Retry:
        lda     f:video_tick
        sta     f:water_palette_nmi
        RW      a8
        lda     f:water_palette_difference
        sta     f:WRMPYA
        tya
        sta     f:WRMPYB
        RW      a16
        nop
        nop
        nop
        lda     f:RDMPYL
        xba
        and     #$ff
        pha
        lda     f:video_tick
        cmp     f:water_palette_nmi
        beq     :+
        pla
        bra     @Retry
:       lda     f:water_palette_difference
        bpl     :+
        tya
        eor     #$ffff
        inc
        clc
        adc     1,s
        sta     1,s
:       pla
        clc
        adc     f:water_palette_value
@Done:  rts

WaterSceneSources:
        .dword BSP_CPU_CODE_ADDRESS(QuakeBSPTexturePalette), QuakeBSPUntexturedPalette
        .dword BSP_CPU_CODE_ADDRESS(QuakeBSPFlashPalette)
WaterPaletteGold:   .word 215, 186, 69
WaterPaletteDamage: .word 80, 0, 0
WaterPaletteMuzzle: .word 64, 32, 0
WaterPaletteBonus:
        .repeat 31, Tick
        .byte 50*Tick/30
        .endrepeat
WaterPaletteContents:
        .macro WATER_CHANNEL Dest, Strength
        .repeat 32, Value
        .byte (Value * 8 * (256 - Strength) + Dest * Strength) / 256
        .endrepeat
        .endmacro
        WATER_CHANNEL 130, 128
        WATER_CHANNEL 80, 128
        WATER_CHANNEL 50, 128
        WATER_CHANNEL 0, 150
        WATER_CHANNEL 25, 150
        WATER_CHANNEL 5, 150
        .byte 0
.popseg
