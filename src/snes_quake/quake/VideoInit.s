; Present the already-rendered startup frame in its native format. In
; particular, a textured boot must not depend on a later queue presentation to
; replace a temporary 4bpp display while ordered playback is held for sound.
InitVideo:
        RW_forced a8i16
.if .defined(PLAYABLE_MAP_ID) && .defined(PLAYABLE_WEAPON_OBJ)
        jsl     BuildPlayableTextureTilemap
.else
        VRAM_memcpy VRAM_TEXTURE_TILEMAP, BSP_CPU_CODE_ADDRESS(QuakeBSPTextureTilemap), $0800
.endif
        stz     TMW
.ifndef PLAYABLE_MAP_ID
        lda     technique
        cmp     #$02
        bcc     @InitFlatFrame
        jmp     @InitTextureFrame
@InitFlatFrame:
        VRAM_memcpy VRAM_TILEMAP, BSP_CPU_CODE_ADDRESS(QuakeBSPTilemap), $0800
        CGRAM_memcpy 0, BSP_CPU_CODE_ADDRESS(QuakeBSPPalette), 32
        VRAM_memcpy VRAM_TILES_A, StagedFrame0, GSU_OUTPUT_BYTES
        VRAM_memcpy VRAM_TILES_B, StagedFrame0, GSU_OUTPUT_BYTES
        stz     presented_format
        jmp     @InitFrameReady
.endif
@InitTextureFrame:
        lda     technique
        cmp     #BSP_TECHNIQUE_UNTEXTURED_LIGHTMAP
        bne     @InitNaturalTexturePalette
        lda     #$01
        sta     upload_palette_mode
        bra     @InitTexturePaletteReady
@InitNaturalTexturePalette:
        RW      a16
        jsr     SelectUploadWeaponPalette
        RW      a8
@InitTexturePaletteReady:
        jsr     ApplyUploadTexturePalette
        VRAM_memcpy VRAM_TEXTURE_TILES_A, StagedFrame0, BSP_VIEW_STAGE_BYTES
        VRAM_memcpy VRAM_TEXTURE_TILES_B, StagedFrame0, BSP_VIEW_STAGE_BYTES
.if BSP_RENDER_SCALE = 3
        VRAM_memcpy VRAM_FLY3_TILEMAP, BSP_CPU_CODE_ADDRESS(Fly3Tilemap), $0800
        lda     #BSP_UPLOAD_FORMAT_TEXTURE_X3
.else
        lda     #BSP_UPLOAD_FORMAT_TEXTURE
.endif
        sta     presented_format
        jmp     @InitFrameReady
@InitFrameReady:
.ifdef PLAYABLE_WEAPON_OBJ
  .ifdef QC_E1M1_HINTS
        jsl     WeaponObjBoot
  .else
        jsr     WeaponObjBoot
  .endif
.endif
        VRAM_memcpy VRAM_RUNTIME_MENU_TILES, RuntimeMenuFont, RUNTIME_MENU_FONT_BYTES
.ifdef PLAYABLE_MAP_ID
        VRAM_memcpy VRAM_RUNTIME_MENU_HIGHLIGHT, RuntimeMenuHighlightFont, RuntimeMenuHighlightFontBytes
.endif
        ; OBJ palette 7 shares the texture-palette tail. Flat presentation
        ; deliberately leaves the tail untouched.
        lda     technique
        cmp     #$02
        bcs     @InitMenuPaletteReady
        CGRAM_memcpy 240, RuntimeMenuPalette, 32
@InitMenuPaletteReady:
        jsr     BuildRuntimeMenuOAM
        OAM_memcpy RuntimeMenuOAM
        lda     #objsel(VRAM_RUNTIME_MENU_OBJ_BASE, OBJ_8x8_16x16, 0)
        sta     OBJSEL

.ifndef PLAYABLE_MAP_ID
        lda     technique
        cmp     #$02
        bcs     @InitTextureDisplay
@InitFlatDisplay:
        lda     #bgmode(BG_MODE_1, BG3_PRIO_NORMAL, BG_SIZE_8X8, BG_SIZE_8X8, BG_SIZE_8X8, BG_SIZE_8X8)
        sta     BGMODE
        stz     MOSAIC
        lda     #bgsc(VRAM_TILEMAP, SC_SIZE_32X32)
        sta     BG1SC
        lda     #bg12nba(VRAM_TILES_A, 0)
        sta     BG12NBA
        bra     @InitDisplayReady
.endif
@InitTextureDisplay:
        lda     #bgmode(BG_MODE_3, BG3_PRIO_NORMAL, BG_SIZE_8X8, BG_SIZE_8X8, BG_SIZE_8X8, BG_SIZE_8X8)
        sta     BGMODE
.if BSP_RENDER_SCALE = 3
        lda     #bg12nba(VRAM_TEXTURE_TILES_A, 0)
        sta     BG12NBA
        jsr     SetFly3MosaicDisplay
        lda     #tm(ON, OFF, OFF, OFF, OFF)
        sta     TM
.ifdef PLAYABLE_WEAPON_OBJ
        jsr     WeaponObjBootPresent
.endif
        rts
.else
        lda     #((BSP_RENDER_SCALE-1) << 4) | 1
        sta     MOSAIC
        lda     #bgsc(VRAM_TEXTURE_TILEMAP, SC_SIZE_32X32)
        sta     BG1SC
        lda     #BSP_RENDER_SCALE
        sta     presented_render_scale
        lda     #bg12nba(VRAM_TEXTURE_TILES_A, 0)
        sta     BG12NBA
.if BSP_QUAKEC_GAMEPLAY
        lda     #1
        sta     BG1HOFS
        bra     @InitHorizontalReady
.else
        bra     @InitDisplayReady
.endif
.endif
@InitDisplayReady:
        stz     BG1HOFS
@InitHorizontalReady:
        stz     BG1HOFS
        ; The SNES BG line origin samples one row ahead. Scroll by -1 so the
        ; software-duplicated rows land on physical (0,1), (2,3), ... pairs.
        lda     #$FF
        sta     BG1VOFS
        sta     BG1VOFS
        lda     #tm(ON, OFF, OFF, OFF, OFF)
        sta     TM
.if .defined(PLAYABLE_WEAPON_OBJ) && (BSP_RENDER_SCALE = 2)
        jsr     WeaponObjBootPresent
.endif
        rts

; A8, under forced blank or at final presentation. Never change the palette
; during a partial VRAM upload while the previous image remains visible.
ApplyUploadTexturePalette:
        RW_assume a8i16
        lda     upload_palette_mode
LoadTexturePalette:
        cmp     #$02
        beq     @Flash
        cmp     #$00
        beq     @Natural
        CGRAM_memcpy 0, QuakeBSPUntexturedPalette, BSP_TEXTURE_PALETTE_UPLOAD_BYTES
        rts
@Flash:
        CGRAM_memcpy 0, BSP_CPU_CODE_ADDRESS(QuakeBSPFlashPalette), BSP_TEXTURE_PALETTE_UPLOAD_BYTES
        rts
@Natural:
        CGRAM_memcpy 0, BSP_CPU_CODE_ADDRESS(QuakeBSPTexturePalette), BSP_TEXTURE_PALETTE_UPLOAD_BYTES
        rts

