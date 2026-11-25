; Dedicated 8bpp palette for the retained textureless lightmap mode.
;
; A strict BGR555 gray diagonal contains only 32 colors. This ramp walks
; individual channel increments while keeping the channels within one code,
; yielding 64 distinct monotonic colors that remain visually neutral.

QuakeBSPUntexturedPalette:
.ifdef PLAYABLE_TEXTURELESS_WHITE
        .incbin "../Data/QuakeBSPPlayableTextureless.bin", 0, 512
.else
        .word   $0000, $0001, $0421, $0422, $0842, $0843, $0C63, $0C64
        .word   $1084, $1085, $14A5, $14A6, $18C6, $18C7, $1CE7, $1CE8
        .word   $2108, $2109, $2529, $252A, $294A, $294B, $296B, $2D6C
        .word   $2D8C, $318D, $31AD, $35AE, $35CE, $39CF, $39EF, $3DF0
        .word   $3E10, $4211, $4231, $4632, $4652, $4A53, $4A73, $4E74
        .word   $4E94, $5295, $52B5, $56B5, $56D6, $5AD6, $5AF7, $5EF7
        .word   $5F18, $6318, $6339, $6739, $675A, $6B5A, $6B7B, $6F7B
        .word   $6F9C, $739C, $73BD, $77BD, $77DE, $7BDE, $7BFF, $7FFF
        .res    (239 - 64) * 2, 0
        .word   $7C1F                  ; Palette index 239 diagnoses holes.
        .incbin "../Data/QuakeBSPTexturePalette.bin", 480, 32
.endif
QuakeBSPUntexturedPaletteEnd:
.assert QuakeBSPUntexturedPaletteEnd - QuakeBSPUntexturedPalette = 512, error, "Textureless palette must contain 256 colors"

QuakeBSPUntexturedLightmapRows:
.ifdef PLAYABLE_TEXTURELESS_WHITE
        .incbin "../Data/QuakeBSPPlayableTextureless.bin", 512, 64
.else
        .byte   63, 62, 61, 60, 59, 58, 57, 56
        .byte   55, 54, 53, 52, 51, 50, 49, 48
        .byte   47, 46, 45, 44, 43, 42, 41, 40
        .byte   39, 38, 37, 36, 35, 34, 33, 32
        .byte   31, 30, 29, 28, 27, 26, 25, 24
        .byte   23, 22, 21, 20, 19, 18, 17, 16
        .byte   15, 14, 13, 12, 11, 10, 9, 8
        .byte   7, 6, 5, 4, 3, 2, 1, 0
.endif
QuakeBSPUntexturedLightmapRowsEnd:
.assert QuakeBSPUntexturedLightmapRowsEnd - QuakeBSPUntexturedLightmapRows = 64, error, "Textureless LightMap row table changed"

.ifdef PLAYABLE_TEXTURELESS_WHITE
.import TextureLightmapSampleReady:far, F3_TextureLightmapSampleReady:far
.import BrushArbiterLightmapPalette:far, F3_BrushArbiterLightmapPalette:far
.import BrushCachedMap:far, F3_BrushCachedMap:far
.assert TextureLightmapSampleReady = F3_TextureLightmapSampleReady, lderror, "World lightmap mapper changed across scales"
.assert BrushArbiterLightmapPalette = F3_BrushArbiterLightmapPalette, lderror, "Brush lightmap mapper changed across scales"
.assert BrushCachedMap = F3_BrushCachedMap, lderror, "Cached brush lightmap mapper changed across scales"

.pushseg
.segment "CODE"
InstallTexturelessLightmapMapper:
        RW_assume a16i16
        ; IWT R0, #table-$C0 / ADD R4 / ALT1 / LDW (R0).
        lda     #(.lobyte(GSU_TEXTURELESS_MAPPER_BASE) << 8) | $F0
        ldx     #$5400 | .hibyte(GSU_TEXTURELESS_MAPPER_BASE)
        ldy     #$403D
        bra     WriteLightmapMapper
RestoreTexturedLightmapMapper:
        RW_assume a16i16
        ; WITH R4 / SWAP / WITH R4 / ADD R12 / ALT1 / LDW (R4).
        lda     #$4D24
        ldx     #$5C24
        ldy     #$443D
WriteLightmapMapper:
        .repeat 3, word
          .if word = 1
            txa
          .elseif word = 2
            tya
          .endif
          sta   f:TextureLightmapSampleReady + word * 2
          sta   f:BrushArbiterLightmapPalette + word * 2
          sta   f:BrushCachedMap + word * 2
        .endrepeat
        ; The patch targets may still have valid instruction cache lines.
        RW      a8
        lda     #$70
        sta     FX3_PBR
        RW      a16
        rts
.popseg
.endif
