; The playable centerprint reuses the menu glyphs.
.pushseg
.segment "BSS"
start_warning_oam: .res 1
.ifdef PLAYABLE_WEAPON_OBJ
start_warning_scroll: .res 2
.ifdef QC_PICKUP_NOTICES
pickup_screen_revision: .res 2
pickup_screen_rows: .res 1
.endif
.endif
.segment "CODE"
.ifdef PLAYABLE_WEAPON_OBJ
START_WARNING_TILES_VRAM = $6000
START_WARNING_MAP_BYTES = WEAPON_OBJ_CENTERPRINT_LINES*2*32*2
START_WARNING_SCROLL_HDMA = $02

; The E1M1 boot bank is full. Put its text updater in the space freed
; by sharing the BG2 font instead of keeping a second, sprite-based font map.
.macro CENTERPRINT_ENTRY entry
        .local Body
  .ifdef QC_E1M1_HINTS
        .segment "BSP_QUAKEC"
entry:  jsr     Body
        rtl
Body:
  .else
entry:
  .endif
.endmacro

CENTERPRINT_ENTRY StartWarningLoad
        RW_assume a8i16
        stz     start_warning_oam
.ifdef QC_PICKUP_NOTICES
        .assert PICKUP_MAP_VRAM >= START_WARNING_MAP_VRAM + START_WARNING_MAP_BYTES, error, "console rows overlap center text"
        .assert PICKUP_MAP_VRAM + 4*64 <= PICKUP_FONT_VRAM, error, "console rows overlap their font"
        VRAM_memcpy PICKUP_FONT_VRAM, PICKUP_FONT, PICKUP_FONT_BYTES
        stz     pickup_screen_rows
        RW      a16
        stz     pickup_screen_revision
        lda     f:WEAPON_OBJ_CENTERPRINTS
        clc
        adc     #.loword(WEAPON_OBJ_CENTERPRINTS)+START_WARNING_MAP_BYTES
        sta     start_warning_scroll
        RW      a8
.endif
        lda     #3
        sta     DMAP1
        lda     #.lobyte(BG2HOFS)
        sta     BBAD1
        lda     #^WEAPON_OBJ_CENTERPRINTS
        sta     A1B1
        rts

; Keep BG1 on the currently visible page and set BG2 to the text font.
CENTERPRINT_ENTRY StartWarningArm
        RW_assume a8i16
        lda     upload_target
        beq     @PageB
        lda     #bg12nba(VRAM_TEXTURE_TILES_A, START_WARNING_TILES_VRAM)
        bra     @TileBases
@PageB:
        lda     #bg12nba(VRAM_TEXTURE_TILES_B, START_WARNING_TILES_VRAM)
@TileBases:
        sta     BG12NBA
        ldx     start_warning_scroll
        stx     A1T1L
        rts

; Preserve hardware weapon OAM. Each new message needs one small VRAM DMA.
CENTERPRINT_ENTRY StartWarningVBlank
        RW_assume a8i16
        lda     runtime_menu_open
        beq     @Playing
        stz     start_warning_oam
        clc
        rts
@Playing:
.ifdef QC_PICKUP_NOTICES
        jsr     PickupNoticeMap
        bcc     :+
        rts
:
.endif
        lda     quake_restart_pending
        bne     @Hide
        lda     f:hub_warning_ticks
        beq     @Hide
        lda     f:hub_warning_gate
        cmp     start_warning_oam
        beq     @Done
        jsr     StartWarningDMATime
        bcs     @Done
        lda     f:hub_warning_gate
        sta     start_warning_oam
        RW      a16
        and     #$00ff
        dec
        asl
        tax
        lda     f:WEAPON_OBJ_CENTERPRINTS,x
        clc
        adc     #.loword(WEAPON_OBJ_CENTERPRINTS)
        sta     A1T7L
        clc
        adc     #START_WARNING_MAP_BYTES
        sta     start_warning_scroll
        ldx     #START_WARNING_MAP_VRAM/2
        stx     VMADDL
        ldx     #$1801
        stx     DMAP7
        ldx     #START_WARNING_MAP_BYTES
        stx     DAS7L
        RW      a8
        lda     #^WEAPON_OBJ_CENTERPRINTS
        sta     A1B7
        lda     #$80
        sta     VMAINC
        sta     MDMAEN
        ; Only BG2 is whitened. The world and weapon use the same CGRAM tint.
        stz     CGSWSEL
        lda     #$ff
        sta     COLDATA
        lda     #CG_BG2_ON
        sta     CGADSUB
        sec
        rts
@Hide:
        lda     start_warning_oam
        beq     @Done
        stz     start_warning_oam
.ifdef QC_PICKUP_NOTICES
        lda     pickup_screen_rows
        bne     @Done
.endif
        stz     CGADSUB
        lda     #RUNTIME_MENU_COLOR_WINDOW_CLOSED
        sta     CGSWSEL
@Done:
        clc
        rts
.ifdef QC_PICKUP_NOTICES
.include "quake/PickupDisplay.s"
.endif
.else
StartWarningVBlank:
        RW_assume a8i16
        lda     runtime_menu_open
        beq     @Playing
        stz     start_warning_oam      ; Opening the menu replaces all OAM.
        bra     @Done
@Playing:
        lda     quake_restart_pending
        bne     @Hidden
        lda     f:hub_warning_ticks
        beq     @Hidden
        lda     f:hub_warning_gate
        cmp     start_warning_oam
        beq     @Done
        jsr     StartWarningDMATime
        bcs     @Done
        lda     f:hub_warning_gate
        sta     start_warning_oam
        RW_forced a16i16
        and     #$00ff
        dec
        asl
        tax
        lda     f:QuakeCHubData+QC_HUB_WARNING_OAM_TABLE_OFFSET,x
        clc
        adc     #.loword(QuakeCHubData)
        sta     A1T7L
        ldx     #0
        stx     OAMADDL
        ldx     #$0400
        stx     DMAP7
        ldx     #544
        stx     DAS7L
        RW_forced a8i16
        lda     #^QuakeCHubData
        sta     A1B7
        lda     #$80
        sta     MDMAEN
        lda     #tm(ON, OFF, OFF, OFF, ON)
        sta     TM
        sec
        rts
@Done:
        clc
        rts
@Hidden:
        lda     start_warning_oam
        beq     @Done
        jsr     StartWarningDMATime
        bcs     @Done
        stz     start_warning_oam
        lda     #tm(ON, OFF, OFF, OFF, OFF)
        sta     TM
        sec
        rts
.endif

StartWarningDMATime:
        RW_assume a8i16
        ; Defer a changed overlay if the world/HUD used most of VBlank.
        lda     HVBJOY
        bpl     @Late
        lda     STAT78
        lda     SLHV
        lda     OPVCT
        tax
        lda     OPVCT
        and     #1
        bne     @Late
        txa
        cmp     #249                   ; Room for 544 DMA bytes plus setup.
        rts
@Late:
        sec
        rts
.popseg
