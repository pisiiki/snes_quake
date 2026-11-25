; Static OAM positions and labels are built once before display is enabled.
; Glyph tiles use transparent color zero around each character.
BuildRuntimeMenuOAM:
        RW_forced a8i16
        OAM_init RuntimeMenuOAM, 0, $F0, 0
        stz     RuntimeMenuBuildRow
.ifdef PLAYABLE_MAP_ID
        stz     RuntimeMenuBuildY+1
        ldx     #RUNTIME_MENU_HIGHLIGHT_OAM
        lda     #RUNTIME_MENU_HIGHLIGHT_X
@InitStrip:
        sta     a:RuntimeMenuOAM,x
        pha
        lda     #RUNTIME_MENU_OBJ_ATTR
        sta     a:RuntimeMenuOAM+3,x
        pla
  .repeat 4
        inx
  .endrepeat
        clc
        adc     #8
        cmp     #RUNTIME_MENU_HIGHLIGHT_X + RUNTIME_MENU_HIGHLIGHT_COLUMNS * 8
        bne     @InitStrip
.endif
        ldx     #$0000
        ldy     #$0000
@Row:
        lda     RuntimeMenuBuildRow
        asl
        asl
        asl
        clc
        adc     #RUNTIME_MENU_Y
        sta     RuntimeMenuBuildY
.ifdef PLAYABLE_MAP_ID
        lda     RuntimeMenuBuildRow
        cmp     #RUNTIME_MENU_ROW_RESTART
        bne     :+
        lda     #RUNTIME_MENU_Y + RUNTIME_MENU_ROW_RESTART * 8 + RUNTIME_MENU_RESTART_GAP_PIXELS
        sta     RuntimeMenuBuildY
:
.else
        lda     #RUNTIME_MENU_X
        sta     RuntimeMenuBuildX
.endif
        phx
        ldx     RuntimeMenuBuildRow
.ifdef PLAYABLE_MAP_ID
        lda     f:RuntimeMenuRowX,x
        sta     RuntimeMenuBuildX
.endif
        lda     f:RuntimeMenuRowWidths,x
        plx
        sta     RuntimeMenuBuildColumns
@Column:
        lda     RuntimeMenuBuildX
        sta     a:RuntimeMenuOAM+0,y
        lda     RuntimeMenuBuildY
        sta     a:RuntimeMenuOAM+1,y
        lda     f:RuntimeMenuText,x
.ifndef PLAYABLE_MAP_ID
        sec
        sbc     #RUNTIME_MENU_ASCII_FIRST
        clc
        adc     #.lobyte(RUNTIME_MENU_TILE_BASE)
.endif
        sta     a:RuntimeMenuOAM+2,y
        lda     #RUNTIME_MENU_OBJ_ATTR
        sta     a:RuntimeMenuOAM+3,y
        inx
        iny
        iny
        iny
        iny
        lda     RuntimeMenuBuildX
        clc
        adc     #$08
        sta     RuntimeMenuBuildX
        dec     RuntimeMenuBuildColumns
        bne     @Column
        inc     RuntimeMenuBuildRow
        lda     RuntimeMenuBuildRow
        cmp     #RUNTIME_MENU_ROW_COUNT
        bne     @Row
        jsr     PatchRuntimeMenuOAM
        RW_forced a8i16
        rts

RefreshRuntimeMenuOAM:
        RW_forced a8i16
        jsr     PatchRuntimeMenuOAM
.ifdef PLAYABLE_MAP_ID
        jsr     PatchRuntimeMenuHighlight
.endif
        OAM_memcpy RuntimeMenuOAM
        RW_forced a16i16
        rts

PatchRuntimeMenuOAM:
        RW_forced a8i16
.ifndef PLAYABLE_MAP_ID
        ldx     #0
@ClearCursor:
        RW      a16
        lda     f:RuntimeMenuCursorOffsets,x
        tay
        RW      a8
        lda     #RUNTIME_MENU_TILE_SPACE
        sta     a:RuntimeMenuOAM,y
        inx
        inx
        cpx     #RUNTIME_MENU_ROW_COUNT*2
        bcc     @ClearCursor
        RW      a16
        lda     runtime_menu_selection
        cmp     #RUNTIME_MENU_ROW_COUNT
        bcc     :+
        lda     #RUNTIME_MENU_FIRST_ROW
:       asl
        tax
        lda     f:RuntimeMenuCursorOffsets,x
        tax
        RW      a8
        lda     #RUNTIME_MENU_TILE_CURSOR
        sta     a:RuntimeMenuOAM,x
.endif

        RW      a16
.ifdef PLAYABLE_MAP_ID
        lda     runtime_menu_draft_map
        asl
        asl
        asl
        sec
        sbc     runtime_menu_draft_map
        clc
        adc     #(PlayableModuleMapValues - RuntimeMenuToggleValues)
        tax
.else
        ldx     #(RuntimeMenuPlaybackValues - RuntimeMenuToggleValues)
.endif
  .ifdef PLAYABLE_MAP_ID
        ldy     #RUNTIME_MENU_PLAYBACK_VALUE_OAM + 2
  .else
        ldy     #RUNTIME_MENU_PLAYBACK_OAM + (RUNTIME_MENU_PLAYBACK_VALUE_COLUMN * RUNTIME_MENU_ENTRY_BYTES) + 2
  .endif
        RW      a8
        lda     #RUNTIME_MENU_PLAYBACK_VALUE_BYTES
        jsr     WriteRuntimeMenuValue

.ifdef PLAYABLE_MAP_ID
        RW      a16
        jsr     RuntimeMenuRenderIndex
        txa
        asl
        asl
        asl
        clc
        adc     #(RuntimeMenuRenderValues - RuntimeMenuToggleValues)
        tax
        ldy     #RUNTIME_MENU_RENDER_VALUE_OAM + 2
        RW      a8
        lda     #RUNTIME_MENU_RENDER_VALUE_BYTES
        jsr     WriteRuntimeMenuValue
.else
        RW      a16
        lda     runtime_menu_draft_textures
        cmp     #RUNTIME_MENU_TEXTURES_COUNT
        bcc     :+
        lda     #RUNTIME_MENU_TEXTURES_OFF
:
        asl
        asl
        asl
        clc
        adc     #(RuntimeMenuTextureValues - RuntimeMenuToggleValues)
        tax
        ldy     #RUNTIME_MENU_TEXTURES_OAM + (RUNTIME_MENU_VALUE_COLUMN * RUNTIME_MENU_ENTRY_BYTES) + 2
        RW      a8
        lda     #RUNTIME_MENU_VALUE_BYTES
        jsr     WriteRuntimeMenuValue

        RW      a16
        lda     runtime_menu_draft_lighting
        and     #$0007
        asl
        asl
        asl
        clc
        adc     #(RuntimeMenuLightingValues - RuntimeMenuToggleValues)
        tax
        ldy     #RUNTIME_MENU_LIGHTING_OAM + (RUNTIME_MENU_VALUE_COLUMN * RUNTIME_MENU_ENTRY_BYTES) + 2
        RW      a8
        lda     #RUNTIME_MENU_VALUE_BYTES
        jsr     WriteRuntimeMenuValue

.endif
        RW      a16
        lda     runtime_menu_draft_brushes
        and     #$0001
        asl
        asl
        asl
        tax
  .ifdef PLAYABLE_MAP_ID
        ldy     #RUNTIME_MENU_BRUSHES_VALUE_OAM + 2
  .else
        ldy     #RUNTIME_MENU_BRUSHES_OAM + (RUNTIME_MENU_VALUE_COLUMN * RUNTIME_MENU_ENTRY_BYTES) + 2
  .endif
        RW      a8
        lda     #RUNTIME_MENU_VALUE_BYTES
        jsr     WriteRuntimeMenuValue

        RW      a16
        lda     runtime_menu_draft_entities
        and     #$0001
        asl
        asl
        asl
        tax
  .ifdef PLAYABLE_MAP_ID
        ldy     #RUNTIME_MENU_ENTITIES_VALUE_OAM + 2
  .else
        ldy     #RUNTIME_MENU_ENTITIES_OAM + (RUNTIME_MENU_VALUE_COLUMN * RUNTIME_MENU_ENTRY_BYTES) + 2
  .endif
        RW      a8
        lda     #RUNTIME_MENU_VALUE_BYTES
        jsr     WriteRuntimeMenuValue

@PatchDone:
        jsr     PatchRuntimeMenuScaleOAM
.if BSP_QUAKEC_GAMEPLAY
        jsr     PatchQuakeSkillOAM
.endif
.ifdef PLAYABLE_MAP_ID
        jsr     PatchAlwaysRunOAM
.endif
        RW_forced a8i16
        rts

.ifdef PLAYABLE_MAP_ID
; Give the highlighted row its own contiguous sprite strip. Hide the
; normal copy so both together cannot exceed the per-scanline OBJ limit.
PatchRuntimeMenuHighlight:
        RW_assume a8i16
        lda     RuntimeMenuBuildY+1
        beq     @Select
        ldx     RuntimeMenuBuildRow
        ldy     RuntimeMenuBuildX
        lda     RuntimeMenuBuildY
@RestoreGlyph:
        sta     a:RuntimeMenuOAM+1,x
  .repeat 4
        inx
  .endrepeat
        dey
        bne     @RestoreGlyph
@Select:
        lda     #1
        sta     RuntimeMenuBuildY+1
        ldx     runtime_menu_selection
        lda     f:RuntimeMenuRowWidths,x
        sta     RuntimeMenuBuildX
        RW      a16
        txa
        asl     a
        tax
        lda     f:RuntimeMenuRowOffsets,x
        tay
        RW      a8
        sty     RuntimeMenuBuildRow
        lda     a:RuntimeMenuOAM+1,y
        sta     RuntimeMenuBuildY
        ldx     #RUNTIME_MENU_HIGHLIGHT_OAM
@Background:
        lda     RuntimeMenuBuildY
        sta     a:RuntimeMenuOAM+1,x
        lda     #.lobyte(RUNTIME_MENU_HIGHLIGHT_TILE_BASE)
        sta     a:RuntimeMenuOAM+2,x
  .repeat 4
        inx
  .endrepeat
        cpx     #RUNTIME_MENU_HIGHLIGHT_OAM + RUNTIME_MENU_HIGHLIGHT_COLUMNS * 4
        bne     @Background

        lda     a:RuntimeMenuOAM,y
        sec
        sbc     #RUNTIME_MENU_HIGHLIGHT_X
        lsr     a
        clc
        adc     #RUNTIME_MENU_HIGHLIGHT_OAM & $FF
        sta     RuntimeMenuBuildColumns
        lda     #(RUNTIME_MENU_HIGHLIGHT_OAM >> 8)
        adc     #0
        sta     RuntimeMenuBuildColumns+1
        ldx     RuntimeMenuBuildColumns
        lda     RuntimeMenuBuildX
        sta     RuntimeMenuBuildColumns
@HighlightGlyph:
        RW      a16
        lda     a:RuntimeMenuOAM+2,y
        and     #$003F                  ; Normal atlas starts at tile low $C0.
        phx
        tax
        RW      a8
        lda     f:RuntimeMenuHighlightGlyphs,x
        plx
        sta     a:RuntimeMenuOAM+2,x
        lda     #$F0
        sta     a:RuntimeMenuOAM+1,y
  .repeat 4
        inx
        iny
  .endrepeat
        dec     RuntimeMenuBuildColumns
        bne     @HighlightGlyph
        rts

PatchAlwaysRunOAM:
        RW_forced a16i16
        ldx     #8                      ; RuntimeMenuToggleValues: OFF, ON.
        lda     runtime_walk
        beq     :+
        ldx     #0
:       ldy     #RUNTIME_MENU_ALWAYS_RUN_VALUE_OAM + 2
        RW      a8
        lda     #3
        jmp     WriteRuntimeMenuValue

RuntimeMenuToggleAlwaysRun:
        RW_assume a16i16
        lda     runtime_walk
        eor     #QC_INPUT_WALK
        sta     runtime_walk
        jmp     RefreshRuntimeMenuOAM
.endif

; A is the character count, X the offset into the shared text, and Y
; the OAM tile byte for the first glyph. All callers already use A8/I16.
WriteRuntimeMenuValue:
        RW_assume a8i16
        sta     RuntimeMenuBuildColumns
@Glyph:
        lda     f:RuntimeMenuToggleValues,x
.ifndef PLAYABLE_MAP_ID
        sec
        sbc     #RUNTIME_MENU_ASCII_FIRST
        clc
        adc     #RUNTIME_MENU_TILE_SPACE
.endif
        sta     a:RuntimeMenuOAM,y
        inx
        iny
        iny
        iny
        iny
        dec     RuntimeMenuBuildColumns
        bne     @Glyph
        rts

.pushseg
.segment "RODATA"
.ifdef PLAYABLE_MAP_ID

; Keep normal tile numbers so START centerprints can share the font.
.define RUNTIME_MENU_GLYPH_CHARS " -1234ABCDEFGHIKLMNOPRSTUVWXY"
.repeat .strlen(RUNTIME_MENU_GLYPH_CHARS), glyph_index
.ident(.sprintf("RuntimeMenuHighlightChar%d", .strat(RUNTIME_MENU_GLYPH_CHARS, glyph_index))) = .lobyte(RUNTIME_MENU_HIGHLIGHT_TILE_BASE) + glyph_index
.endrepeat
.assert .strlen(RUNTIME_MENU_GLYPH_CHARS) * 32 = RuntimeMenuHighlightFontBytes, error, "Highlight glyph table must match the font"
.assert (RUNTIME_MENU_TILE_SPACE & $3F) = 0, error, "Highlight lookup requires aligned normal glyph indices"
.endif

.macro RuntimeMenuGlyphText value
.ifdef PLAYABLE_MAP_ID
  .repeat .strlen(value), text_index
        .assert .defined(.ident(.sprintf("RuntimeMenuHighlightChar%d", .strat(value, text_index)))), error, "Menu text has no highlight glyph"
        .byte   .lobyte(RUNTIME_MENU_TILE_BASE) + .strat(value, text_index) - RUNTIME_MENU_ASCII_FIRST
  .endrepeat
.else
        .byte   value
.endif
.endmacro

.ifdef PLAYABLE_MAP_ID
; End each description at the common gutter without spending OAM on
; left padding. Each pair has one blank character cell between columns.
.macro RuntimeMenuPair row, value, label, count, x_position
row:
        RuntimeMenuGlyphText " "
        RuntimeMenuGlyphText label
x_position = RUNTIME_MENU_GAP_X - (* - row) * 8
.assert x_position >= RUNTIME_MENU_HIGHLIGHT_X, error, "Menu row begins before the highlight strip"
.assert RUNTIME_MENU_GAP_X + (RUNTIME_MENU_GAP_COLUMNS + count) * 8 <= RUNTIME_MENU_HIGHLIGHT_X + RUNTIME_MENU_HIGHLIGHT_COLUMNS * 8, error, "Menu row extends past the highlight strip"
        .res    RUNTIME_MENU_GAP_COLUMNS, RUNTIME_MENU_TILE_SPACE
value = (* - RuntimeMenuText) * RUNTIME_MENU_ENTRY_BYTES
        .res    count, RUNTIME_MENU_TILE_SPACE
.endmacro
RuntimeMenuText:
PlayableMenuLevelFirst:
RuntimeMenuPair RuntimeMenuTextPlayback, RUNTIME_MENU_PLAYBACK_VALUE_OAM, "LEVEL", RUNTIME_MENU_PLAYBACK_VALUE_BYTES, RuntimeMenuLevelX
RuntimeMenuPair RuntimeMenuTextRender, RUNTIME_MENU_RENDER_VALUE_OAM, "RENDER", RUNTIME_MENU_RENDER_VALUE_BYTES, RuntimeMenuRenderX
RuntimeMenuPair RuntimeMenuTextBrushes, RUNTIME_MENU_BRUSHES_VALUE_OAM, "D-BRSH", RUNTIME_MENU_VALUE_BYTES, RuntimeMenuBrushesX
RuntimeMenuPair RuntimeMenuTextEntities, RUNTIME_MENU_ENTITIES_VALUE_OAM, "ENTITY", RUNTIME_MENU_VALUE_BYTES, RuntimeMenuEntitiesX
RuntimeMenuPair RuntimeMenuTextScale, RUNTIME_MENU_SCALE_VALUE_OAM, "SCALE", 2, RuntimeMenuScaleX
RuntimeMenuPair RuntimeMenuTextSkill, RUNTIME_MENU_SKILL_VALUE_OAM, "SKILL", RUNTIME_MENU_SKILL_VALUE_BYTES, RuntimeMenuSkillX
RuntimeMenuPair RuntimeMenuTextAlwaysRun, RUNTIME_MENU_ALWAYS_RUN_VALUE_OAM, "ALWAYS RUN", RUNTIME_MENU_VALUE_BYTES, RuntimeMenuRunX
RuntimeMenuTextRestart:
        RuntimeMenuGlyphText " RESTART"
.else
RuntimeMenuText:
        RuntimeMenuGlyphText " RESUME       "
RuntimeMenuTextPlayback:
        RuntimeMenuGlyphText " PB           "
RuntimeMenuTextTextures:
        RuntimeMenuGlyphText " TEXTURE      "
RuntimeMenuTextLighting:
        RuntimeMenuGlyphText " LIGHT        "
RuntimeMenuTextBrushes:
        RuntimeMenuGlyphText " D-BRSH       "
RuntimeMenuTextEntities:
        RuntimeMenuGlyphText " ENTITY       "
RuntimeMenuTextScale:
        RuntimeMenuGlyphText " SCALE        "
RuntimeMenuTextRestart:
        RuntimeMenuGlyphText " RESTART      "
.if BSP_QUAKEC_GAMEPLAY
RuntimeMenuTextSkill:
        RuntimeMenuGlyphText " SKILL          "
.endif
.endif
RuntimeMenuTextEnd:

.macro RuntimeMenuWidth first, last
        .assert last - first <= 32, error, "Runtime-menu row exceeds the per-scanline OBJ limit"
        .byte   last - first
.endmacro
RuntimeMenuRowWidths:
.ifdef PLAYABLE_MAP_ID
        RuntimeMenuWidth RuntimeMenuTextPlayback, RuntimeMenuTextRender
        RuntimeMenuWidth RuntimeMenuTextRender, RuntimeMenuTextBrushes
        RuntimeMenuWidth RuntimeMenuTextBrushes, RuntimeMenuTextEntities
        RuntimeMenuWidth RuntimeMenuTextEntities, RuntimeMenuTextScale
        RuntimeMenuWidth RuntimeMenuTextScale, RuntimeMenuTextSkill
        RuntimeMenuWidth RuntimeMenuTextSkill, RuntimeMenuTextAlwaysRun
        RuntimeMenuWidth RuntimeMenuTextAlwaysRun, RuntimeMenuTextRestart
        RuntimeMenuWidth RuntimeMenuTextRestart, RuntimeMenuTextEnd
.else
        RuntimeMenuWidth RuntimeMenuText, RuntimeMenuTextPlayback
        RuntimeMenuWidth RuntimeMenuTextPlayback, RuntimeMenuTextTextures
        RuntimeMenuWidth RuntimeMenuTextTextures, RuntimeMenuTextLighting
        RuntimeMenuWidth RuntimeMenuTextLighting, RuntimeMenuTextBrushes
        RuntimeMenuWidth RuntimeMenuTextBrushes, RuntimeMenuTextEntities
        RuntimeMenuWidth RuntimeMenuTextEntities, RuntimeMenuTextScale
        RuntimeMenuWidth RuntimeMenuTextScale, RuntimeMenuTextRestart
  .if BSP_QUAKEC_GAMEPLAY
        RuntimeMenuWidth RuntimeMenuTextRestart, RuntimeMenuTextSkill
        RuntimeMenuWidth RuntimeMenuTextSkill, RuntimeMenuTextEnd
  .else
        RuntimeMenuWidth RuntimeMenuTextRestart, RuntimeMenuTextEnd
  .endif
.endif
.assert * - RuntimeMenuRowWidths = RUNTIME_MENU_ROW_COUNT, error, "Runtime-menu row widths changed"

.ifdef PLAYABLE_MAP_ID
RuntimeMenuRowX:
        .byte   RuntimeMenuLevelX, RuntimeMenuRenderX, RuntimeMenuBrushesX, RuntimeMenuEntitiesX
        .byte   RuntimeMenuScaleX, RuntimeMenuSkillX, RuntimeMenuRunX, 96
.assert * - RuntimeMenuRowX = RUNTIME_MENU_ROW_COUNT, error, "Runtime-menu row origins changed"

RuntimeMenuRowOffsets:
        .word   RUNTIME_MENU_PLAYBACK_OAM, (RuntimeMenuTextRender - RuntimeMenuText) * RUNTIME_MENU_ENTRY_BYTES
        .word   RUNTIME_MENU_BRUSHES_OAM, RUNTIME_MENU_ENTITIES_OAM, RUNTIME_MENU_SCALE_OAM
        .word   RUNTIME_MENU_SKILL_OAM, RUNTIME_MENU_ALWAYS_RUN_OAM
        .word   (RuntimeMenuTextRestart - RuntimeMenuText) * RUNTIME_MENU_ENTRY_BYTES
.assert * - RuntimeMenuRowOffsets = RUNTIME_MENU_ROW_COUNT*2, error, "Runtime-menu row offsets changed"
.else
RuntimeMenuCursorOffsets:
        .word   2, RUNTIME_MENU_PLAYBACK_OAM+2, RUNTIME_MENU_TEXTURES_OAM+2
        .word   RUNTIME_MENU_LIGHTING_OAM+2, RUNTIME_MENU_BRUSHES_OAM+2
        .word   RUNTIME_MENU_ENTITIES_OAM+2, RUNTIME_MENU_SCALE_OAM+2
        .word   (RuntimeMenuTextRestart - RuntimeMenuText) * RUNTIME_MENU_ENTRY_BYTES + 2
  .if BSP_QUAKEC_GAMEPLAY
        .word   RUNTIME_MENU_SKILL_OAM+2
  .endif
.assert * - RuntimeMenuCursorOffsets = RUNTIME_MENU_ROW_COUNT*2, error, "Runtime-menu cursor count changed"
.endif

RuntimeMenuToggleValues:
        RuntimeMenuGlyphText "OFF     "
        RuntimeMenuGlyphText "ON      "
RuntimeMenuToggleValuesEnd:
.assert RuntimeMenuToggleValuesEnd - RuntimeMenuToggleValues = 2 * 8, error, "Runtime-menu toggle values must stay fixed-width"

.ifdef PLAYABLE_MAP_ID
RuntimeMenuRenderValues:
        RuntimeMenuGlyphText "FULL            "
        RuntimeMenuGlyphText "FLAT            "
        RuntimeMenuGlyphText "TEXTURES        "
        RuntimeMenuGlyphText "LIGHTMAPS       "
.assert * - RuntimeMenuRenderValues = 4 * 16, error, "Render values must retain 16-byte indexing"
.else
RuntimeMenuTextureValues:
        RuntimeMenuGlyphText "OFF     "
        RuntimeMenuGlyphText "ON      "
RuntimeMenuTextureValuesEnd:
.assert RuntimeMenuTextureValuesEnd - RuntimeMenuTextureValues = RUNTIME_MENU_TEXTURES_COUNT * 8, error, "Runtime-menu texture values must stay fixed-width"

RuntimeMenuLightingValues:
        RuntimeMenuGlyphText "NONE    "
        RuntimeMenuGlyphText "L-MAP   "
RuntimeMenuLightingValuesEnd:
.assert RuntimeMenuLightingValuesEnd - RuntimeMenuLightingValues = 2 * 8, error, "Runtime-menu lighting values must stay fixed-width"

.endif
RuntimeMenuScaleValues:
        RuntimeMenuGlyphText "X2      "
        RuntimeMenuGlyphText "X3      "
RuntimeMenuScaleValuesEnd:
.assert RuntimeMenuScaleValuesEnd - RuntimeMenuScaleValues = RUNTIME_MENU_SCALE_COUNT * 8, error, "Scale values must retain eight-byte indexing"
.if BSP_QUAKEC_GAMEPLAY
QuakeSkillLabels:
.ifdef PLAYABLE_MAP_ID
        RuntimeMenuGlyphText "EASY            "
        RuntimeMenuGlyphText "NORMAL          "
        RuntimeMenuGlyphText "HARD            "
        RuntimeMenuGlyphText "NIGHTMARE       "
.else
        RuntimeMenuGlyphText " EASY           "
        RuntimeMenuGlyphText " NORMAL         "
        RuntimeMenuGlyphText " HARD           "
        RuntimeMenuGlyphText " NIGHTMARE      "
.endif
.assert * - QuakeSkillLabels = 4*16, error, "Quake skill labels must use a 16-byte stride"

.endif

.ifdef PLAYABLE_MAP_ID
PlayableModuleMapValues:
        RuntimeMenuGlyphText "E1M1   "
        RuntimeMenuGlyphText "E1M3   "
.if PLAYABLE_MAP_COUNT > PLAYABLE_START_MAP_ID
        RuntimeMenuGlyphText "START  "
.endif
.if PLAYABLE_MAP_COUNT > PLAYABLE_E1M2_MAP_ID
        RuntimeMenuGlyphText "E1M2   "
.endif
.if PLAYABLE_MAP_COUNT > PLAYABLE_E1M4_MAP_ID
        RuntimeMenuGlyphText "E1M4   "
.endif
.assert *-PlayableModuleMapValues = PLAYABLE_MAP_COUNT*7, error, "Playable menu label count changed"

.else
RuntimeMenuPlaybackValues:
        .byte   "FLY       "

.endif
.popseg
