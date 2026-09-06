; Present the already-rendered startup frame in its native format. In
; particular, a textured boot must not depend on a later queue presentation to
; replace a temporary 4bpp display while ordered playback is held for sound.
InitVideo:
        RW_forced a8i16
        VRAM_memcpy VRAM_TEXTURE_TILEMAP, QuakeBSPTextureTilemap, $0800
        VRAM_memcpy VRAM_TILEMAP, QuakeBSPTilemap, $0800
        lda     technique
        cmp     #$02
        bcc     @InitFlatFrame
        jmp     @InitTextureFrame
@InitFlatFrame:
        CGRAM_memcpy 0, QuakeBSPPalette, 32
        VRAM_memcpy VRAM_TILES_A, StagedFrame0, GSU_OUTPUT_BYTES
        VRAM_memcpy VRAM_TILES_B, StagedFrame0, GSU_OUTPUT_BYTES
        stz     presented_format
        jmp     @InitFrameReady
@InitTextureFrame:
        lda     technique
        cmp     #BSP_TECHNIQUE_UNTEXTURED_LIGHTMAP
        bne     @InitNaturalTexturePalette
        CGRAM_memcpy 0, QuakeBSPUntexturedPalette, 512
        lda     #$01
        jmp     @InitTexturePaletteReady
@InitNaturalTexturePalette:
        CGRAM_memcpy 0, QuakeBSPTexturePalette, 512
        lda     #$00
@InitTexturePaletteReady:
        sta     presented_palette_mode
        VRAM_memcpy VRAM_TEXTURE_TILES_A, StagedFrame0, GSU_TEXTURE_VISIBLE_BYTES
        VRAM_memcpy VRAM_TEXTURE_TILES_B, StagedFrame0, GSU_TEXTURE_VISIBLE_BYTES
        lda     #BSP_UPLOAD_FORMAT_TEXTURE
        sta     presented_format
        jmp     @InitFrameReady
@InitFrameReady:
        VRAM_memcpy VRAM_RUNTIME_MENU_TILES, RuntimeMenuFont, RUNTIME_MENU_FONT_BYTES
        ; OBJ palette 7 shares the texture-palette tail. Flat presentation
        ; deliberately leaves the tail untouched.
        CGRAM_memcpy 240, RuntimeMenuPalette, 32
        jsr     BuildRuntimeMenuOAM
        OAM_memcpy RuntimeMenuOAM
        lda     #objsel(VRAM_RUNTIME_MENU_OBJ_BASE, OBJ_8x8_16x16, 0)
        sta     OBJSEL

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
@InitTextureDisplay:
        lda     #bgmode(BG_MODE_3, BG3_PRIO_NORMAL, BG_SIZE_8X8, BG_SIZE_8X8, BG_SIZE_8X8, BG_SIZE_8X8)
        sta     BGMODE
        lda     #$11
        sta     MOSAIC
        lda     #bgsc(VRAM_TEXTURE_TILEMAP, SC_SIZE_32X32)
        sta     BG1SC
        lda     #bg12nba(VRAM_TEXTURE_TILES_A, 0)
        sta     BG12NBA
        bra     @InitDisplayReady
@InitDisplayReady:
        stz     BG1HOFS
        stz     BG1HOFS
        ; The SNES BG line origin samples one row ahead. Scroll by -1 so the
        ; software-duplicated rows land on physical (0,1), (2,3), ... pairs.
        lda     #$FF
        sta     BG1VOFS
        sta     BG1VOFS
        lda     #tm(ON, OFF, OFF, OFF, OFF)
        sta     TM
        rts
