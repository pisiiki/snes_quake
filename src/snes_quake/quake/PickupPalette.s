; Foreground prepares the new CGRAM image while the FX3 can keep drawing.
; NMI reads the staging buffer only after the complete palette has been published.
PickupPaletteSources:
        ; Low two bits select the scene. Quad/Suit apply after the bonus shift.
        .macro PICKUP_BASE_PALETTES
          .dword BSP_CPU_CODE_ADDRESS(QuakeBSPTexturePalette), QuakeBSPUntexturedPalette
          .dword BSP_CPU_CODE_ADDRESS(QuakeBSPFlashPalette), 0
        .endmacro
        PICKUP_BASE_PALETTES
        .dword WEAPON_OBJ_TINTS, WEAPON_OBJ_TINTS+1024, WEAPON_OBJ_TINTS+2048, 0
        .dword WEAPON_OBJ_TINTS+512, WEAPON_OBJ_TINTS+1536, WEAPON_OBJ_TINTS+2560, 0
        PICKUP_BASE_PALETTES
        PICKUP_BASE_PALETTES

; Prepare the peak at the accepted touch, including the newly granted artifact.
PickupPalettePeak:
        RW_assume a16i16
        lda     f:weapon_obj_tint_effect
        and     #$1c
        cmp     #WEAPON_OBJ_DAMAGE_TINT
        beq     @Scene
        cmp     #WEAPON_OBJ_SHOT_TINT
        beq     @Scene
        lda     f:QuakeCItemsHigh
        bit     #QC_POWERUP_0_ITEM_HIGH
        beq     :+
        lda     #WEAPON_OBJ_QUAD_TINT
        bra     @Scene
:       bit     #QC_POWERUP_1_ITEM_HIGH
        beq     :+
        lda     #WEAPON_OBJ_SUIT_TINT
        bra     @Scene
:       lda     #0
@Scene: ora     f:presented_palette_mode
        and     #$1f
        ora     #30 << 8
.ifdef QC_LIQUID_ROOT
        jsr     PickupWaterPaletteKey
.endif
        cmp     f:pickup_palette_ready
        bne     PickupBuildPalette
        rtl

PickupBuildPalette:
        RW_assume a16i16
.ifdef QC_LIQUID_ROOT
        bit     #$60
        beq     :+
        jml     WaterBuildPalette
:
.endif
        phb
        phx
        phy
        sta     f:pickup_palette_build
        lda     #0
        sta     f:pickup_palette_ready
        lda     f:pickup_palette_build
        xba
        and     #$ff
        dec
        .repeat 5
          asl
        .endrepeat
        sta     f:pickup_palette_phase
        lda     f:pickup_palette_build
        and     #$1c
        cmp     #WEAPON_OBJ_QUAD_TINT
        bcc     @Source
        cmp     #WEAPON_OBJ_SUIT_TINT
        beq     @Suit
        lda     #30*32
        bra     @Artifact
@Suit:  lda     #60*32
@Artifact:
        clc
        adc     f:pickup_palette_phase
        sta     f:pickup_palette_phase
@Source:
        lda     f:pickup_palette_build
        and     #$1f
        asl
        asl
        tax
        lda     f:PickupPaletteSources,x
        tay
        RW      a8
        lda     f:PickupPaletteSources+2,x
        pha
        plb
        RW      a16
.ifdef PICKUP_BLEND_PACKED
        jsl     PickupBuildDryColors
.else
        PICKUP_COLOR_LOOP PICKUP_BLEND, 90*32
.endif
        lda     f:pickup_palette_build
        sta     f:pickup_palette_ready
        ply
        plx
        plb
        rtl

.ifdef PICKUP_BLEND_PACKED
.include "quake/PickupDryColors.s"
.endif

; Use at most one 512-byte transfer. A busy upload can postpone a palette
; until the following field without touching the renderer or its MSU cursor.
PickupPalettePublish:
        RW_assume a8i16
        lda     runtime_menu_open
        ora     quake_restart_pending
        bne     @Clear
        lda     f:pickup_bonus_ticks
.ifdef QC_LIQUID_ROOT
        bne     :+
        lda     f:walk_eye_palette
        beq     @Clear
        lda     #0
:
.else
        beq     @Clear
.endif
        xba
        lda     weapon_obj_tint_effect
        ora     presented_palette_mode
        RW      a16
.ifdef QC_LIQUID_ROOT
        jsr     PickupWaterPaletteKey
.endif
        sta     f:pickup_palette_wanted
        ; The foreground may finish between two fields. Accept its most
        ; recent complete fade step only when its scene and active effect match.
        lda     f:pickup_palette_ready
        beq     @Pending
        eor     f:pickup_palette_wanted
        and     #$c0ff
        bne     @Pending
        lda     f:pickup_palette_ready
        cmp     f:pickup_palette_shown
        beq     @Handled
        RW      a8
        jsr     StartWarningDMATime
        RW      a16
        bcs     @Pending
        lda     f:pickup_palette_ready
        sta     f:pickup_palette_shown
        RW      a8
        sta     weapon_obj_palette_key
        CGRAM_memcpy 0, PickupPalettePixels, 512
        sec
        rtl
@Pending:
        RW_assume a16i16
        lda     f:pickup_palette_shown
        beq     @Normal
        eor     f:pickup_palette_wanted
        and     #$c0ff
        beq     @Handled
        bra     @Restore
@Clear: RW_forced a16i16
        lda     #0
        sta     f:pickup_palette_wanted
        lda     f:pickup_palette_shown
        beq     @Normal
@Restore:
        lda     #0
        sta     f:pickup_palette_shown
        RW      a8
        lda     #$ff
        sta     weapon_obj_palette_key
@Normal:
        RW_forced a8i16
        clc
        rtl
@Handled:
        RW_forced a8i16
        sec
        rtl

.ifdef QC_LIQUID_ROOT
; Held artifacts continue to shift the underwater palette during a damage or muzzle flash.
PickupWaterPaletteKey:
        RW_assume a16i16
        .assert WEAPON_OBJ_DAMAGE_TINT = 4 .and WEAPON_OBJ_SHOT_TINT = 8, error, "Water palette effect keys changed"
        ora     f:walk_eye_palette
        bit     #$60
        beq     @Done
        pha
        lda     f:QuakeCItemsHigh
        bit     #QC_POWERUP_0_ITEM_HIGH
        beq     :+
        pla
        ora     #$4000
        rts
:       bit     #QC_POWERUP_1_ITEM_HIGH
        beq     :+
        pla
        ora     #$8000
        rts
:       pla
@Done:  rts

.endif
