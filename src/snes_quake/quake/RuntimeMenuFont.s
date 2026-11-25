; Menu glyphs are SNES 4bpp OBJ tiles.
.macro RUNTIME_MENU_GLYPH row0, row1, row2, row3, row4, row5, row6, row7
        .byte   $00, row0, $00, row1, $00, row2, $00, row3
        .byte   $00, row4, $00, row5, $00, row6, $00, row7
        .byte   row0, row0, row1, row1, row2, row2, row3, row3
        .byte   row4, row4, row5, row5, row6, row6, row7, row7
.endmacro

.if .defined(PLAYABLE_MAP_ID) .or .defined(PLAYABLE_MENU_FONT_PLACEMENT)
.pushseg
.segment "BSP_CPU_MENU_FONT"
.endif
RuntimeMenuFont:
        RUNTIME_MENU_GLYPH $00, $00, $00, $00, $00, $00, $00, $00 ; space
        RUNTIME_MENU_GLYPH $10, $10, $10, $10, $10, $00, $10, $00 ; !
        RUNTIME_MENU_GLYPH $28, $28, $28, $00, $00, $00, $00, $00 ; "
        RUNTIME_MENU_GLYPH $28, $7C, $28, $28, $7C, $28, $00, $00 ; #
        RUNTIME_MENU_GLYPH $10, $3C, $50, $38, $14, $78, $10, $00 ; $
        RUNTIME_MENU_GLYPH $64, $68, $10, $20, $2C, $4C, $00, $00 ; %
        RUNTIME_MENU_GLYPH $30, $48, $50, $20, $54, $48, $34, $00 ; &
        RUNTIME_MENU_GLYPH $10, $10, $20, $00, $00, $00, $00, $00 ; '
        RUNTIME_MENU_GLYPH $08, $10, $20, $20, $20, $10, $08, $00 ; (
        RUNTIME_MENU_GLYPH $20, $10, $08, $08, $08, $10, $20, $00 ; )
        RUNTIME_MENU_GLYPH $00, $54, $38, $7C, $38, $54, $00, $00 ; *
        RUNTIME_MENU_GLYPH $00, $10, $10, $7C, $10, $10, $00, $00 ; +
        RUNTIME_MENU_GLYPH $00, $00, $00, $00, $00, $10, $10, $20 ; ,
        RUNTIME_MENU_GLYPH $00, $00, $00, $7C, $00, $00, $00, $00 ; -
        RUNTIME_MENU_GLYPH $00, $00, $00, $00, $00, $00, $10, $00 ; .
        RUNTIME_MENU_GLYPH $04, $08, $10, $20, $40, $00, $00, $00 ; /
        RUNTIME_MENU_GLYPH $38, $44, $4C, $54, $64, $44, $38, $00 ; 0
        RUNTIME_MENU_GLYPH $10, $30, $10, $10, $10, $10, $38, $00 ; 1
        RUNTIME_MENU_GLYPH $38, $44, $04, $08, $10, $20, $7C, $00 ; 2
        RUNTIME_MENU_GLYPH $78, $04, $04, $38, $04, $04, $78, $00 ; 3
        RUNTIME_MENU_GLYPH $08, $18, $28, $48, $7C, $08, $08, $00 ; 4
        RUNTIME_MENU_GLYPH $7C, $40, $40, $78, $04, $04, $78, $00 ; 5
        RUNTIME_MENU_GLYPH $38, $40, $40, $78, $44, $44, $38, $00 ; 6
        RUNTIME_MENU_GLYPH $7C, $04, $08, $10, $20, $20, $20, $00 ; 7
        RUNTIME_MENU_GLYPH $38, $44, $44, $38, $44, $44, $38, $00 ; 8
        RUNTIME_MENU_GLYPH $38, $44, $44, $3C, $04, $04, $38, $00 ; 9
        RUNTIME_MENU_GLYPH $00, $10, $00, $00, $10, $00, $00, $00 ; :
        RUNTIME_MENU_GLYPH $00, $10, $00, $00, $10, $10, $20, $00 ; ;
        RUNTIME_MENU_GLYPH $08, $10, $20, $40, $20, $10, $08, $00 ; <
        RUNTIME_MENU_GLYPH $00, $00, $7C, $00, $7C, $00, $00, $00 ; =
        RUNTIME_MENU_GLYPH $40, $20, $10, $08, $10, $20, $40, $00 ; >
        RUNTIME_MENU_GLYPH $38, $44, $04, $08, $10, $00, $10, $00 ; ?
        RUNTIME_MENU_GLYPH $38, $44, $5C, $54, $5C, $40, $38, $00 ; @
        RUNTIME_MENU_GLYPH $38, $44, $44, $7C, $44, $44, $44, $00 ; A
        RUNTIME_MENU_GLYPH $78, $44, $44, $78, $44, $44, $78, $00 ; B
        RUNTIME_MENU_GLYPH $38, $44, $40, $40, $40, $44, $38, $00 ; C
        RUNTIME_MENU_GLYPH $78, $44, $44, $44, $44, $44, $78, $00 ; D
        RUNTIME_MENU_GLYPH $7C, $40, $40, $78, $40, $40, $7C, $00 ; E
        RUNTIME_MENU_GLYPH $7C, $40, $40, $78, $40, $40, $40, $00 ; F
        RUNTIME_MENU_GLYPH $38, $44, $40, $5C, $44, $44, $38, $00 ; G
        RUNTIME_MENU_GLYPH $44, $44, $44, $7C, $44, $44, $44, $00 ; H
        RUNTIME_MENU_GLYPH $38, $10, $10, $10, $10, $10, $38, $00 ; I
        RUNTIME_MENU_GLYPH $1C, $08, $08, $08, $08, $48, $30, $00 ; J
        RUNTIME_MENU_GLYPH $44, $48, $50, $60, $50, $48, $44, $00 ; K
        RUNTIME_MENU_GLYPH $40, $40, $40, $40, $40, $40, $7C, $00 ; L
        RUNTIME_MENU_GLYPH $44, $6C, $54, $54, $44, $44, $44, $00 ; M
        RUNTIME_MENU_GLYPH $44, $64, $54, $4C, $44, $44, $44, $00 ; N
        RUNTIME_MENU_GLYPH $38, $44, $44, $44, $44, $44, $38, $00 ; O
        RUNTIME_MENU_GLYPH $78, $44, $44, $78, $40, $40, $40, $00 ; P
        RUNTIME_MENU_GLYPH $38, $44, $44, $44, $54, $48, $34, $00 ; Q
        RUNTIME_MENU_GLYPH $78, $44, $44, $78, $50, $48, $44, $00 ; R
        RUNTIME_MENU_GLYPH $3C, $40, $40, $38, $04, $04, $78, $00 ; S
        RUNTIME_MENU_GLYPH $7C, $10, $10, $10, $10, $10, $10, $00 ; T
        RUNTIME_MENU_GLYPH $44, $44, $44, $44, $44, $44, $38, $00 ; U
        RUNTIME_MENU_GLYPH $44, $44, $44, $44, $44, $28, $10, $00 ; V
        RUNTIME_MENU_GLYPH $44, $44, $44, $54, $54, $54, $28, $00 ; W
        RUNTIME_MENU_GLYPH $44, $44, $28, $10, $28, $44, $44, $00 ; X
        RUNTIME_MENU_GLYPH $44, $44, $28, $10, $10, $10, $10, $00 ; Y
        RUNTIME_MENU_GLYPH $7C, $04, $08, $10, $20, $40, $7C, $00 ; Z
RuntimeMenuFontEnd:
.assert ^RuntimeMenuFont = ^(RuntimeMenuFontEnd - 1), lderror, "Menu font crosses a DMA source bank"
.assert RuntimeMenuFontEnd - RuntimeMenuFont = RUNTIME_MENU_FONT_BYTES, error, "Runtime-menu font size changed"
.assert VRAM_RUNTIME_MENU_TILES+RUNTIME_MENU_FONT_BYTES <= VRAM_TILES_B, error, "Runtime-menu font exceeds shared sprite VRAM"

.if .defined(PLAYABLE_MAP_ID) .or .defined(PLAYABLE_MENU_FONT_PLACEMENT)
; The playable highlight uses OBJ palette 7 colors 8 (red) and 12 (gold).
.macro RUNTIME_MENU_PLAYABLE_GLYPHS emit
        emit $00, $00, $00, $00, $00, $00, $00, $00 ; space
        emit $00, $00, $00, $7C, $00, $00, $00, $00 ; -
        emit $10, $30, $10, $10, $10, $10, $38, $00 ; 1
        emit $38, $44, $04, $08, $10, $20, $7C, $00 ; 2
        emit $78, $04, $04, $38, $04, $04, $78, $00 ; 3
        emit $08, $18, $28, $48, $7C, $08, $08, $00 ; 4
        emit $38, $44, $44, $7C, $44, $44, $44, $00 ; A
        emit $78, $44, $44, $78, $44, $44, $78, $00 ; B
        emit $38, $44, $40, $40, $40, $44, $38, $00 ; C
        emit $78, $44, $44, $44, $44, $44, $78, $00 ; D
        emit $7C, $40, $40, $78, $40, $40, $7C, $00 ; E
        emit $7C, $40, $40, $78, $40, $40, $40, $00 ; F
        emit $38, $44, $40, $5C, $44, $44, $38, $00 ; G
        emit $44, $44, $44, $7C, $44, $44, $44, $00 ; H
        emit $38, $10, $10, $10, $10, $10, $38, $00 ; I
        emit $44, $48, $50, $60, $50, $48, $44, $00 ; K
        emit $40, $40, $40, $40, $40, $40, $7C, $00 ; L
        emit $44, $6C, $54, $54, $44, $44, $44, $00 ; M
        emit $44, $64, $54, $4C, $44, $44, $44, $00 ; N
        emit $38, $44, $44, $44, $44, $44, $38, $00 ; O
        emit $78, $44, $44, $78, $40, $40, $40, $00 ; P
        emit $78, $44, $44, $78, $50, $48, $44, $00 ; R
        emit $3C, $40, $40, $38, $04, $04, $78, $00 ; S
        emit $7C, $10, $10, $10, $10, $10, $10, $00 ; T
        emit $44, $44, $44, $44, $44, $44, $38, $00 ; U
        emit $44, $44, $44, $44, $44, $28, $10, $00 ; V
        emit $44, $44, $44, $54, $54, $54, $28, $00 ; W
        emit $44, $44, $28, $10, $28, $44, $44, $00 ; X
        emit $44, $44, $28, $10, $10, $10, $10, $00 ; Y
.endmacro
.macro RUNTIME_MENU_GLYPH_HIGHLIGHT row0, row1, row2, row3, row4, row5, row6, row7
        .res    16, $00
        .byte   row0, $FF, row1, $FF, row2, $FF, row3, $FF
        .byte   row4, $FF, row5, $FF, row6, $FF, row7, $FF
.endmacro
RuntimeMenuHighlightFont:
        RUNTIME_MENU_PLAYABLE_GLYPHS RUNTIME_MENU_GLYPH_HIGHLIGHT
RuntimeMenuHighlightFontEnd:
RuntimeMenuHighlightFontBytes = RuntimeMenuHighlightFontEnd - RuntimeMenuHighlightFont
.assert ^RuntimeMenuHighlightFont = ^(RuntimeMenuHighlightFontEnd - 1), lderror, "Highlight font crosses a DMA source bank"
RuntimeMenuHighlightGlyphs:
.repeat RUNTIME_MENU_FONT_TILE_COUNT, ascii_index
  .if .defined(.ident(.sprintf("RuntimeMenuHighlightChar%d", RUNTIME_MENU_ASCII_FIRST + ascii_index)))
        .byte   .ident(.sprintf("RuntimeMenuHighlightChar%d", RUNTIME_MENU_ASCII_FIRST + ascii_index))
  .else
        .byte   .lobyte(RUNTIME_MENU_HIGHLIGHT_TILE_BASE)
  .endif
.endrepeat
.popseg
.endif
.ifdef PLAYABLE_MAP_ID
.assert VRAM_RUNTIME_MENU_HIGHLIGHT + RuntimeMenuHighlightFontBytes <= VRAM_RUNTIME_MENU_TILES, error, "Highlighted menu font overlaps normal font"
.endif
