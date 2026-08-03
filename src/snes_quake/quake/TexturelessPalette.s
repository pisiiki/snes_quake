; Dedicated 8bpp palette for the three textureless render modes.
;
; A strict BGR555 gray diagonal contains only 32 colors. This ramp walks
; individual channel increments while keeping the channels within one code,
; yielding 64 distinct monotonic colors that remain visually neutral.

QuakeBSPUntexturedPalette:
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
QuakeBSPUntexturedPaletteEnd:
.assert QuakeBSPUntexturedPaletteEnd - QuakeBSPUntexturedPalette = 512, error, "Textureless palette must contain 256 colors"

; Technique 6 owns all 256 palette entries. A strict gray diagonal has only
; 32 BGR555 words, so this deterministic ramp advances the least perceptually
; significant blue/red channels between gray anchors. Every word is distinct,
; integer luminance increases strictly, and channel spread never exceeds two.
.macro BSP_DISTANCE_COLOR base, red, green, blue
        .word   ((base + red) | ((base + green) << 5) | ((base + blue) << 10))
.endmacro

QuakeBSPUntexturedDistancePalette:
  .repeat 8, base
        BSP_DISTANCE_COLOR base, 0, 0, 0
        BSP_DISTANCE_COLOR base, 0, 0, 1
        BSP_DISTANCE_COLOR base, 0, 0, 2
        BSP_DISTANCE_COLOR base, 1, 0, 0
        BSP_DISTANCE_COLOR base, 1, 0, 1
        BSP_DISTANCE_COLOR base, 2, 0, 1
        BSP_DISTANCE_COLOR base, 0, 1, 0
        BSP_DISTANCE_COLOR base, 0, 1, 1
        BSP_DISTANCE_COLOR base, 1, 1, 0
  .endrepeat
  .repeat 22, offset
        BSP_DISTANCE_COLOR offset + 8, 0, 0, 0
        BSP_DISTANCE_COLOR offset + 8, 0, 0, 1
        BSP_DISTANCE_COLOR offset + 8, 0, 0, 2
        BSP_DISTANCE_COLOR offset + 8, 1, 0, 0
        BSP_DISTANCE_COLOR offset + 8, 1, 0, 1
        BSP_DISTANCE_COLOR offset + 8, 2, 0, 1
        BSP_DISTANCE_COLOR offset + 8, 0, 1, 0
        BSP_DISTANCE_COLOR offset + 8, 1, 1, 0
  .endrepeat
        BSP_DISTANCE_COLOR 30, 0, 0, 0
        BSP_DISTANCE_COLOR 30, 0, 0, 1
        BSP_DISTANCE_COLOR 30, 1, 0, 0
        BSP_DISTANCE_COLOR 30, 1, 0, 1
        BSP_DISTANCE_COLOR 30, 0, 1, 0
        BSP_DISTANCE_COLOR 30, 0, 1, 1
        BSP_DISTANCE_COLOR 30, 1, 1, 0
        BSP_DISTANCE_COLOR 31, 0, 0, 0
QuakeBSPUntexturedDistancePaletteEnd:
.assert QuakeBSPUntexturedDistancePaletteEnd - QuakeBSPUntexturedDistancePalette = 512, error, "Distance palette must contain 256 colors"

; Half-world-unit Q6 depth buckets map near=8 to white and far=99 to
; black. The GSU clamps its five-bit-shifted depth before indexing this table.
QuakeBSPUntexturedDistanceDepthShade:
  .repeat 256, bucket
    .if bucket <= 16
        .byte   255
    .elseif bucket >= 198
        .byte   0
    .else
        .byte   255 - (((bucket - 16) * 255 + 91) / 182)
    .endif
  .endrepeat
QuakeBSPUntexturedDistanceDepthShadeEnd:
.assert QuakeBSPUntexturedDistanceDepthShadeEnd - QuakeBSPUntexturedDistanceDepthShade = 256, error, "Distance-depth LUT must contain 256 entries"

; These are complete output-index rows for the lookup-table collapse performed
; only when a textureless renderer is selected. The existing GSU span kernels
; remain byte-for-byte unchanged.
QuakeBSPUntexturedNoneRows:
        .res    55, 63
QuakeBSPUntexturedNoneRowsEnd:
.assert QuakeBSPUntexturedNoneRowsEnd - QuakeBSPUntexturedNoneRows = 55, error, "Textureless None row table changed"

QuakeBSPUntexturedLightmapRows:
        .byte   63, 62, 61, 60, 59, 58, 57, 56
        .byte   55, 54, 53, 52, 51, 50, 49, 48
        .byte   47, 46, 45, 44, 43, 42, 41, 40
        .byte   39, 38, 37, 36, 35, 34, 33, 32
        .byte   31, 30, 29, 28, 27, 26, 25, 24
        .byte   23, 22, 21, 20, 19, 18, 17, 16
        .byte   15, 14, 13, 12, 11, 10, 9, 8
        .byte   7, 6, 5, 4, 3, 2, 1, 0
QuakeBSPUntexturedLightmapRowsEnd:
.assert QuakeBSPUntexturedLightmapRowsEnd - QuakeBSPUntexturedLightmapRows = 64, error, "Textureless LightMap row table changed"
