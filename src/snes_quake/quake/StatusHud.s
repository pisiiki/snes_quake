; The HUD atlas is shared by both textured display formats. The two tilemaps
; select the same graphics relative to the currently displayed BG1 char base.
.include "Data/QuakeBSPStatusHud.i"

HUD_ATLAS_HEAD_VRAM = $9000
HUD_ATLAS_TAIL_VRAM = $C000
HUD_ATLAS_EXTRA_VRAM = $E700
HUD_MAP_A_VRAM = $E000
HUD_MAP_B_VRAM = $E800
HUD_BG1SC_A = bgsc(HUD_MAP_A_VRAM, SC_SIZE_32X32)
HUD_BG1SC_B = bgsc(HUD_MAP_B_VRAM, SC_SIZE_32X32)
HUD_WORLD_SC = bgsc(VRAM_TEXTURE_TILEMAP, SC_SIZE_32X32)
HUD_WORLD_SC_X3 = bgsc(VRAM_FLY3_TILEMAP, SC_SIZE_32X32)
HUD_WINDOW_HDMA = $08
HUD_MODE_HDMA = $10
.if .defined(PLAYABLE_WEAPON_OBJ) || .defined(QC_INTERMISSION_COUNT)
HUD_OBJ_HDMA = $04
.endif
.if .defined(PLAYABLE_WEAPON_OBJ) && .defined(QC_HUB_WARNING_COUNT)
START_WARNING_MAP_VRAM = $B800
HUD_TEXT_SC = bgsc(START_WARNING_MAP_VRAM, SC_SIZE_32X32)
.else
HUD_TEXT_SC = 0
.endif
; X3 scroll writes share the Mode 7 multiplier latch. Channel 0 updates BG1,
; then channel 5 restores the low operand byte from direct page on that line.
.ifdef QC_QUEUED_INPUT
HUD_SCROLL_HDMA = $21
.else
HUD_SCROLL_HDMA = $20
.endif
HUD_SCROLL_X = 1
HUD_SCROLL_Y = $FFFF
HUD_MAP_OFFSET = 25 * 32 * 2
HUD_MOSAIC_X2 = $11
HUD_MOSAIC_X3 = $21
HUD_FACE_SLOT = 12

.assert HUD_ATLAS_HEAD_VRAM+HUD_ATLAS_SPLIT <= $B800, error, "HUD head exceeds its atlas allocation"
.assert HUD_ATLAS_TAIL_VRAM+HUD_ATLAS_TAIL_BYTES <= $D5C0, error, "HUD overlaps weapon OBJ tiles"
.assert HUD_ATLAS_EXTRA_VRAM >= HUD_MAP_A_VRAM+HUD_MAP_OFFSET+HUD_MAP_BYTES, error, "HUD overlaps tilemap A"
.assert HUD_ATLAS_EXTRA_VRAM+HUD_ATLAS_EXTRA_BYTES <= HUD_MAP_B_VRAM+HUD_MAP_OFFSET, error, "HUD overlaps tilemap B"
.assert HUD_MAP_B_VRAM+$0800 <= VRAM_TEXTURE_TILEMAP, error, "HUD overlaps the world tilemap"

.pushseg
.segment "CODE"

StatusHudLoad:
        RW_assume a8i16
        VRAM_memcpy HUD_ATLAS_HEAD_VRAM, HUD_ATLAS, HUD_ATLAS_SPLIT
.if HUD_ATLAS_TAIL_BYTES
        VRAM_memcpy HUD_ATLAS_TAIL_VRAM, (HUD_ATLAS+HUD_ATLAS_SPLIT), HUD_ATLAS_TAIL_BYTES
.endif
.if HUD_ATLAS_EXTRA_BYTES
        VRAM_memcpy HUD_ATLAS_EXTRA_VRAM, (HUD_ATLAS+HUD_ATLAS_SPLIT+HUD_ATLAS_TAIL_BYTES), HUD_ATLAS_EXTRA_BYTES
.endif
        VRAM_memcpy (HUD_MAP_A_VRAM+HUD_MAP_OFFSET), HUD_MAP_A_DATA, HUD_MAP_BYTES
        VRAM_memcpy (HUD_MAP_B_VRAM+HUD_MAP_OFFSET), HUD_MAP_B_DATA, HUD_MAP_BYTES
.ifdef PLAYABLE_WEAPON_OBJ
        jsl     StatusHudObjLoad
.endif
.if .defined(PLAYABLE_WEAPON_OBJ) || .defined(QC_INTERMISSION_COUNT)
        stz     DMAP2
        lda     #$2C
        sta     BBAD2
        lda     #^StatusHudWindowX3
        sta     A1B2
.endif
.ifdef PLAYABLE_WEAPON_OBJ
  .ifdef QC_HUB_WARNING_COUNT
    .ifdef QC_E1M1_HINTS
        jsl     StartWarningLoad
    .else
        jsr     StartWarningLoad
    .endif
  .endif
.endif
        lda     #4
        sta     DMAP4
        lda     #$05
        sta     BBAD4
        lda     #^StatusHudSplitA
        sta     A1B4
.ifdef QC_QUEUED_INPUT
        ldx     #$0D03                  ; Direct HOFS twice, VOFS twice.
        stx     DMAP0
        lda     #^StatusHudScrollX3
        sta     A1B0
        ldx     #.loword(StatusHudScrollX3)
        stx     A1T0L
        ldx     #$1F40                  ; Indirect byte to unused Mode 7 center X.
        stx     DMAP5
        stz     DASB5                   ; Bank 0 mirrors the CPU's direct page.
.else
        lda     #3
        sta     DMAP5
        lda     #$0D
        sta     BBAD5
.endif
        stz     DMAP3
        lda     #$2E
        sta     BBAD3
        lda     #^StatusHudWindowX3
        sta     A1B3
        lda     #^StatusHudScrollX3
        sta     A1B5
        rts

StatusHudInit:
        RW_assume a8i16
        RW      a16
        lda     #$FFFF
        sta     status_hud_health
        sta     status_hud_ammo
.if .defined(QC_NAIL_COUNT) || .defined(QC_CAMPAIGN_ITEMS)
        stz     status_hud_nails
.endif
.if .defined(QC_ARMOR_COUNT) || .defined(QC_CAMPAIGN_ITEMS)
        sta     status_hud_armor
        sta     status_hud_armor_type
        stz     status_hud_armor_column
.ifdef QC_POWERUP_COUNT
        stz     status_hud_face_source
        stz     status_hud_face_hit
.endif
        sta     status_hud_cells+14
.endif
        .repeat 7, slot
          sta   status_hud_cells+2*slot
        .endrepeat
        jsr     StatusHudUpdateValues
        stz     status_hud_changes
        RW      a8
.ifdef PLAYABLE_WEAPON_OBJ
        jsl     StatusHudObjPublish
.endif
        rts

; Run after the world page and palette have been published for this VBlank.
; The first scanline of the next frame uses world registers. At the split the
; PPU reads the 8bpp HUD at 1x. X2 keeps its scroll and reads rows 25–27.
; X3 also switches scroll at the split.
StatusHudVBlank:
        RW_assume a8i16
        lda     HVBJOY
        bpl     @Skip
        lda     presented_format
        beq     @Skip
        lda     quake_restart_pending
        beq     @Display
@Skip:
        rts
@Display:
.ifdef QC_INTERMISSION_COUNT
        lda     f:intermission_phase
        cmp     #2
        bne     :+
        ; BG1 has just 200 valid world scanlines. Channel 2 writes TM at
        ; the split so the old HUD tiles cannot leak into the bottom rows.
        ; The X3 window table has the same 1/0 mask and line counts.
        ldx     #.loword(StatusHudWindowX3)
        stx     A1T2L           ; The table also restores TM for the first line.
        lda     #HUD_OBJ_HDMA
        sta     HDMAEN
        lda     presented_render_scale
        cmp     #3
        bne     @IntermissionX2
        jsr     SetFly3MosaicDisplay
        rts
@IntermissionX2:
        lda     #HUD_WORLD_SC
        sta     BG1SC
        lda     #HUD_MOSAIC_X2
        sta     MOSAIC
        rts
:
.endif
        lda     #3
        sta     BGMODE
        lda     presented_render_scale
        cmp     #3
        beq     @X3
        lda     #HUD_MOSAIC_X2
        sta     MOSAIC
        lda     #HUD_WORLD_SC
        sta     BG1SC
        ldx     #.loword(StatusHudSplitA)
        lda     upload_target
        bne     :+
        ldx     #.loword(StatusHudSplitB)
:
        stx     A1T4L
.ifdef PLAYABLE_WEAPON_OBJ
        lda     weapon_obj_oam_word
        beq     @HudWithoutWeapon
        lda     #$11
        sta     TM
        lda     #HUD_MODE_HDMA
        bra     @Enable
@HudWithoutWeapon:
        lda     #$01
        sta     TM
        ldx     #.loword(StatusHudObjNoWeaponSplit)
        stx     A1T2L
        lda     #HUD_MODE_HDMA | HUD_OBJ_HDMA
.else
        lda     #HUD_MODE_HDMA
.endif
        bra     @Enable
@X3:
        jsr     SetFly3MosaicDisplay
        ldx     #.loword(StatusHudSplitX3A)
        lda     upload_target
        bne     :+
        ldx     #.loword(StatusHudSplitX3B)
:
        stx     A1T4L
        ldx     #.loword(StatusHudWindowX3)
        stx     A1T3L
.ifdef QC_QUEUED_INPUT
        ldx     #.loword(StatusHudRestoreLatchX3)
.else
        ldx     #.loword(StatusHudScrollX3)
.endif
        stx     A1T5L
.ifdef PLAYABLE_WEAPON_OBJ
        lda     weapon_obj_oam_word
        beq     @X3WithoutWeapon
        lda     #$11
        sta     TM
        lda     #HUD_WINDOW_HDMA | HUD_MODE_HDMA | HUD_SCROLL_HDMA
        bra     @Enable
@X3WithoutWeapon:
        lda     #$01
        sta     TM
        ldx     #.loword(StatusHudObjNoWeaponSplit)
        stx     A1T2L
        lda     #HUD_WINDOW_HDMA | HUD_MODE_HDMA | HUD_SCROLL_HDMA | HUD_OBJ_HDMA
.else
        lda     #HUD_WINDOW_HDMA | HUD_MODE_HDMA | HUD_SCROLL_HDMA
.endif
@Enable:
.if .defined(PLAYABLE_WEAPON_OBJ) && .defined(QC_PICKUP_NOTICES)
        jsl     PickupNoticeLayers
        bcs     @NoText
.endif
.if .defined(PLAYABLE_WEAPON_OBJ) && .defined(QC_HUB_WARNING_COUNT)
        ldx     start_warning_scroll
        beq     @NoText           ; No table until the first centerprint.
        pha
        lda     start_warning_oam
        beq     @TextReady
  .ifdef QC_E1M1_HINTS
        jsl     StartWarningArm
  .else
        jsr     StartWarningArm
  .endif
        ldx     #.loword(StatusHudWarningSplit)
        lda     weapon_obj_oam_word
        beq     @WarningBackground
        ldx     #.loword(StatusHudWarningObjSplit)
        lda     #$11
        bra     @WarningLayers
@WarningBackground:
        lda     #1
@WarningLayers:
        sta     TM
        stx     A1T2L
        pla
        ora     #HUD_OBJ_HDMA | START_WARNING_SCROLL_HDMA
        bra     @NoText
@TextReady:
        pla
@NoText:
.endif
        sta     HDMAEN
        RW      a16
.if .defined(QC_NAIL_COUNT) || .defined(QC_CAMPAIGN_ITEMS)
        jsl     NailHudSelected
        cmp     status_hud_nails
        bne     @CheckTime
.endif
.if .defined(QC_ARMOR_COUNT) || .defined(QC_CAMPAIGN_ITEMS)
.ifdef QC_POWERUP_COUNT
        jsl     StatusHudDesiredFace
        cmp     status_hud_face_source
        bne     @CheckTime
.endif
        lda     f:ShotgunPlayer+QC_FIELD_ARMORVALUE
        cmp     status_hud_armor
        bne     @CheckTime
        lda     f:ShotgunPlayer+QC_FIELD_ARMORTYPE
        cmp     status_hud_armor_type
        bne     @CheckTime
.endif
        lda     f:ShotgunPlayer+QC_FIELD_HEALTH
        cmp     status_hud_health
        bne     @CheckTime
.if .defined(QC_NAIL_COUNT) || .defined(QC_CAMPAIGN_ITEMS)
        lda     f:ShotgunPlayer+QC_FIELD_CURRENTAMMO
.else
        lda     f:ShotgunPlayer+QC_FIELD_AMMO_SHELLS
.endif
        cmp     status_hud_ammo
        beq     @Unchanged
@CheckTime:
        ; A coincident final world DMA can consume most of VBlank. Leave
        ; pending values untouched until there is room for all dirty cells.
        RW      a8
        lda     STAT78
        lda     SLHV
        lda     OPVCT
        tax
        lda     OPVCT
        and     #1
        bne     @Done
        txa
        cmp     #250
        bcs     @Done
        RW      a16
        jsr     StatusHudUpdateValues
@Unchanged:
        RW      a8
@Done:
.ifdef PLAYABLE_WEAPON_OBJ
        jsl     StatusHudObjPublish
.endif
        rts

StatusHudUpdateValues:
        RW_assume a16i16
.if .defined(QC_NAIL_COUNT) || .defined(QC_CAMPAIGN_ITEMS)
        jsl     NailHudSelected
        cmp     status_hud_nails
        beq     :+
        sta     status_hud_nails
        jsl     NailHudUpload
        rts                     ; Retain the remaining dirty cells for the next VBlank.
:
.endif
.if .defined(QC_ARMOR_COUNT) || .defined(QC_CAMPAIGN_ITEMS)
        jsr     StatusHudArmor
.endif
.ifdef QC_POWERUP_COUNT
        jsl     StatusHudDesiredFace
        cmp     status_hud_face_source
        beq     :+
        sta     status_hud_face_source
        jsl     PowerupFaceUpload
        lda     #$ffff
        sta     status_hud_health
:
.endif
        lda     f:ShotgunPlayer+QC_FIELD_HEALTH
        cmp     status_hud_health
        beq     @Ammo
        sta     status_hud_health
        jsr     StatusHudInteger
        pha
        ldx     #0
        ldy     #1
        cmp     #26
        bcs     :+
        ldy     #11
:
        jsr     StatusHudNumber
        pla
        ldy     #21
        cmp     #80
        bcs     @Face
        iny
        cmp     #60
        bcs     @Face
        iny
        cmp     #40
        bcs     @Face
        iny
        cmp     #20
        bcs     @Face
        iny
@Face:
.ifdef QC_POWERUP_COUNT
        lda     status_hud_face_source
        beq     :+
        ldy     #21
:
.endif
        tya
        ldx     #HUD_FACE_SLOT
        jsr     StatusHudSetCell
@Ammo:
.if .defined(QC_NAIL_COUNT) || .defined(QC_CAMPAIGN_ITEMS)
        lda     f:ShotgunPlayer+QC_FIELD_CURRENTAMMO
.else
        lda     f:ShotgunPlayer+QC_FIELD_AMMO_SHELLS
.endif
        cmp     status_hud_ammo
        beq     @Done
        sta     status_hud_ammo
        jsr     StatusHudInteger
        ldx     #6
        ldy     #1
        cmp     #11
        bcs     :+
        ldy     #11
:
        jmp     StatusHudNumber
@Done:
        rts

.if .defined(QC_ARMOR_COUNT) || .defined(QC_CAMPAIGN_ITEMS)
StatusHudArmor:
        lda     f:ShotgunPlayer+QC_FIELD_ARMORTYPE
        cmp     status_hud_armor_type
        beq     @Value
        sta     status_hud_armor_type
        ldy     #26             ; original backdrop, green, yellow
        cmp     #0
        beq     :+
        iny
        cmp     #38
        bne     :+
        iny
:       tya
        ldx     #14
        jsr     StatusHudSetCell
@Value:
        lda     f:ShotgunPlayer+QC_FIELD_ARMORVALUE
        cmp     status_hud_armor
        bne     :+
        rts
:
        sta     status_hud_armor
        jsr     StatusHudInteger
        ldx     #0
        ldy     #0
@Hundreds:
        cmp     #100
        bcc     @Tens
        sbc     #100
        inx
        bra     @Hundreds
@Tens:
        cmp     #10
        bcc     @Write
        sbc     #10
        iny
        bra     @Tens
@Write:
        sta     status_hud_armor_digits+4
        sty     status_hud_armor_digits+2
        stx     status_hud_armor_digits
        ldx     #0
@Digit:
        lda     status_hud_armor_digits,x
        bne     @Glyph
        cpx     #4
        beq     @Last
        cpx     #2
        bne     @Background
        lda     status_hud_armor_digits
        bne     @Zero
        bra     @Background
@Last:  lda     status_hud_armor
        beq     @Background
@Zero:  lda     #0
@Glyph: asl
        tay
        tyx
        lda     f:HUD_ARMOR_DIGITS,x
        ldx     status_hud_armor_column
        bra     @Tile
@Background:
        lda     f:HUD_MAP_A_DATA+2*(32+3),x
@Tile:  pha
        txa
        lsr
        clc
        adc     #((HUD_MAP_A_VRAM+HUD_MAP_OFFSET)/2)+32+3
        sta     VMADDL
        pla
        sta     VMDATAL
        pha
        txa
        lsr
        clc
        adc     #((HUD_MAP_B_VRAM+HUD_MAP_OFFSET)/2)+32+3
        sta     VMADDL
        pla
        sec
        sbc     #$0100
        sta     VMDATAL
        inx
        inx
        stx     status_hud_armor_column
        cpx     #6
        bne     @Digit
        stz     status_hud_armor_column
@Done:  rts
.endif

StatusHudInteger:
        RW_assume a16i16
        cmp     #$8000
        bcc     :+
        lda     #0
:
        .repeat 6
          lsr
        .endrepeat
        rts

; A is the unsigned value, Y is the first normal or red digit, X is the
; byte index of its first cell. Leading zeroes show the original backdrop.
StatusHudNumber:
        RW_assume a16i16
        sty     status_hud_digit_base
        ldy     #0
@Hundreds:
        cmp     #100
        bcc     @HundredsDone
        sbc     #100
        iny
        bra     @Hundreds
@HundredsDone:
        sty     status_hud_hundreds
        ldy     #0
@Tens:
        cmp     #10
        bcc     @Digits
        sbc     #10
        iny
        bra     @Tens
@Digits:
        pha
        phy
        lda     status_hud_hundreds
        beq     :+
        clc
        adc     status_hud_digit_base
:
        jsr     StatusHudSetCell
        inx
        inx
        pla
        bne     @TensGlyph
        ldy     status_hud_hundreds
        beq     :+
@TensGlyph:
        clc
        adc     status_hud_digit_base
:
        jsr     StatusHudSetCell
        inx
        inx
        pla
        clc
        adc     status_hud_digit_base
        jmp     StatusHudSetCell

; Change nine tilemap words per changed cell on each map. Tile graphics stay
; resident. Subtract 256 tile IDs for world char base $4000.
StatusHudSetCell:
        RW_assume a16i16
        cmp     status_hud_cells,x
        bne     :+
        rts
:
        sta     status_hud_cells,x
        inc     status_hud_changes
        phx
        asl
        sta     status_hud_variant_x2
        asl
        asl
        asl
        clc
        adc     status_hud_variant_x2
        tay
        lda     StatusHudCellColumns,x
        tax
        stx     status_hud_column
        tyx
        RW      a8
        lda     #$80
        sta     VMAINC
        RW      a16
        .repeat 2, page
          .repeat 3, row
            lda status_hud_column
            clc
            adc #((HUD_MAP_A_VRAM+HUD_MAP_OFFSET)/2)+page*((HUD_MAP_B_VRAM-HUD_MAP_A_VRAM)/2)+row*32
            sta VMADDL
            .repeat 3, column
              lda f:HUD_VARIANT_DATA+2*(row*3+column),x
              .if page
                sec
                sbc #$0100
              .endif
              sta VMDATAL
            .endrepeat
          .endrepeat
        .endrepeat
        plx
.ifdef PLAYABLE_WEAPON_OBJ
        cpx     #12                 ; The sixth numeric cell ends before the face.
        bcs     :+
        lda     status_hud_cells,x
        jsl     StatusHudObjSetDigit
:
.endif
        rts

.segment "RODATA"
.ifdef PLAYABLE_WEAPON_OBJ
StatusHudObjNoWeaponSplit:
        .byte 126, $01, BSP_PLAYABLE_WORLD_HEIGHT-126, $01, 1, $11, 0
  .ifdef QC_HUB_WARNING_COUNT
.ifdef QC_PICKUP_NOTICES
.macro PICKUP_LAYER_TABLE base, center
        .byte 32, base | 2, 46, base, WEAPON_OBJ_CENTERPRINT_LINES*10, center
        .byte BSP_PLAYABLE_WORLD_HEIGHT-78-WEAPON_OBJ_CENTERPRINT_LINES*10, base
        .byte 1, $11, 0
.endmacro
StatusHudPickupLayers:
        PICKUP_LAYER_TABLE $01, $01
StatusHudPickupCenterLayers:
        PICKUP_LAYER_TABLE $01, $03
StatusHudPickupObjLayers:
        PICKUP_LAYER_TABLE $11, $11
StatusHudPickupCenterObjLayers:
        PICKUP_LAYER_TABLE $11, $13
.endif
StatusHudWarningObjSplit:
        .byte 78, $11, WEAPON_OBJ_CENTERPRINT_LINES*10, $13
        .byte BSP_PLAYABLE_WORLD_HEIGHT-78-WEAPON_OBJ_CENTERPRINT_LINES*10, $11, 1, $11, 0
StatusHudWarningSplit:
        .byte 78, $01, WEAPON_OBJ_CENTERPRINT_LINES*10, $03
        .byte BSP_PLAYABLE_WORLD_HEIGHT-78-WEAPON_OBJ_CENTERPRINT_LINES*10, $01, 1, $11, 0
  .endif
.endif
StatusHudCellColumns:
        .word 9, 12, 15, 23, 26, 29, 6
.if .defined(QC_ARMOR_COUNT) || .defined(QC_CAMPAIGN_ITEMS)
        .word 0
.endif

.macro HUD_MODE_TABLE top_mosaic, world_sc, hud_sc
        .byte 126, 3, top_mosaic, world_sc, HUD_TEXT_SC
        .byte BSP_PLAYABLE_WORLD_HEIGHT-126, 3, top_mosaic, world_sc, HUD_TEXT_SC
        .byte 1, 3, 0, hud_sc, HUD_TEXT_SC
        .byte 0
.endmacro
StatusHudSplitA:
        HUD_MODE_TABLE HUD_MOSAIC_X2, HUD_WORLD_SC, HUD_BG1SC_A
StatusHudSplitB:
        HUD_MODE_TABLE HUD_MOSAIC_X2, HUD_WORLD_SC, HUD_BG1SC_B
StatusHudSplitX3A:
        HUD_MODE_TABLE HUD_MOSAIC_X3, HUD_WORLD_SC_X3, HUD_BG1SC_A
StatusHudSplitX3B:
        HUD_MODE_TABLE HUD_MOSAIC_X3, HUD_WORLD_SC_X3, HUD_BG1SC_B

StatusHudScrollX3:
        .byte 126
        .word FLY3_WORLD_HSCROLL, HUD_SCROLL_Y
        .byte BSP_PLAYABLE_WORLD_HEIGHT-126
        .word FLY3_WORLD_HSCROLL, HUD_SCROLL_Y
        .byte 1
        .word HUD_SCROLL_X, HUD_SCROLL_Y
        .byte 0
.ifdef QC_QUEUED_INPUT
; Match each direct scroll transfer, including the first transfer of a frame.
; M7X shares the PPU write latch with M7A and leaves its matrix value alone.
StatusHudRestoreLatchX3:
        .byte 126
        .word w_mul_a
        .byte BSP_PLAYABLE_WORLD_HEIGHT-126
        .word w_mul_a
        .byte 1
        .word w_mul_a
        .byte 0
        .assert ^StatusHudRestoreLatchX3 = ^StatusHudScrollX3, lderror, "HUD HDMA tables must share a bank"
.endif
StatusHudWindowX3:
        .byte 126, 1, BSP_PLAYABLE_WORLD_HEIGHT-126, 1, 1, 0, 0

.segment "LORAM"
status_hud_health:      .res 2
status_hud_ammo:        .res 2
.if .defined(QC_NAIL_COUNT) || .defined(QC_CAMPAIGN_ITEMS)
status_hud_nails:       .res 2
.endif
status_hud_changes:     .res 2
.ifdef QC_POWERUP_COUNT
status_hud_face_source:  .res 2
status_hud_face_hit:     .res 2
.endif
status_hud_cells:       .res 14
.if .defined(QC_ARMOR_COUNT) || .defined(QC_CAMPAIGN_ITEMS)
                        .res 2
status_hud_armor:       .res 2
status_hud_armor_type:  .res 2
status_hud_armor_digits:.res 6
status_hud_armor_column:.res 2
.endif
status_hud_digit_base:  .res 2
status_hud_hundreds:    .res 2
status_hud_variant_x2:  .res 2
status_hud_column:      .res 2
.popseg

.ifdef PLAYABLE_WEAPON_OBJ
.include "quake/StatusHudObj.s"
.endif
