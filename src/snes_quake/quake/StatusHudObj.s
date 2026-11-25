; Exact opaque glyph pixels which can share one OBJ palette per cell.
; Each of the six digits owns two small OAM records. The asset packer checks
; the two-record ceiling and keeps this tail above every weapon template.
HUD_OBJ_RECORDS_PER_DIGIT = 2
HUD_OBJ_TAIL_BYTES = HUD_OBJ_COUNT*4
HUD_OBJ_OAM_WORD = HUD_OBJ_FIRST*2
.assert HUD_OBJ_COUNT = 6*HUD_OBJ_RECORDS_PER_DIGIT, error, "HUD OAM record count changed"
.assert (HUD_OBJ_FIRST & 3) = 0, error, "Align HUD OAM to the high-table group"
.assert HUD_OBJ_FIRST + 6*HUD_OBJ_RECORDS_PER_DIGIT <= 128, error, "HUD OAM tail exceeds OAM"

.pushseg
.segment "LORAM"
status_hud_obj_replay:   .res 2
status_hud_obj_blanked:  .res 2

.segment "EXRAM"
status_hud_obj_image:    .res HUD_OBJ_TAIL_BYTES

.segment "BSP_CPU_STATUS_HUD_OBJ"

; The two OBJ high-table bits are zero in both full gameplay OAM templates.
; Menu mode has no HUD and also initializes the upper table to zero.
StatusHudObjLoad:
        RW_assume a8i16
        VRAM_memcpy HUD_OBJ_VRAM, HUD_OBJ_TILES, HUD_OBJ_BYTES
        RW      a16
        stz     status_hud_obj_blanked
        RW      a8
        rtl

; A16 glyph ID, X16 digit cell offset 0,2,...,10. Preserve X. The caller has
; published this digit's BG tilemap to both pages in the same VBlank.
StatusHudObjSetDigit:
        RW_assume a16i16
        phx
        pha
        txa
        asl
        asl
        tay
        pla
        asl
        asl
        asl
        pha
        lda     f:StatusHudObjPositions,x
        plx
        pha
        phb
        pea     $7f7f
        plb
        plb
        .repeat HUD_OBJ_RECORDS_PER_DIGIT, record
          lda   f:HUD_OBJ_GLYPHS+record*4,x
          clc
          adc   2,s             ; Digit origin beneath the saved data bank.
          sta   a:.loword(status_hud_obj_image+record*4),y
          lda   f:HUD_OBJ_GLYPHS+record*4+2,x
          sta   a:.loword(status_hud_obj_image+record*4+2),y
        .endrepeat
        plb
        pla
        lda     #1
        sta     status_hud_obj_replay
        plx
        rtl

; Run after the frame owner and the dirty BG tilemap updates. If the latter
; were deferred, replay the cached tail for the still-visible BG digits.
StatusHudObjPublish:
        RW_assume a8i16
        lda     weapon_obj_oam_word
        ora     weapon_obj_oam_word+1
        bne     @Replay
        lda     status_hud_obj_blanked
        bne     @Replay
        ; WeaponObjHide changes TM only. Clear stale weapon/menu sprites once
        ; when X3 or the software weapon takes ownership, without changing the
        ; shared WRAM menu shadow. $F0 makes every small sprite off-screen.
        ldx     #0
        stx     OAMADDL
        ldx     #$0408
        stx     DMAP7
        ldx     #.loword(StatusHudObjOffscreen)
        stx     A1T7L
        ldx     #512
        stx     DAS7L
        lda     #^StatusHudObjOffscreen
        sta     A1B7
        lda     #$80
        sta     MDMAEN
        lda     #objsel($8000, OBJ_8x8_16x16, $2000)
        sta     OBJSEL
        lda     #1
        sta     status_hud_obj_blanked
        sta     status_hud_obj_replay
@Replay:
        lda     status_hud_obj_replay
        beq     @Done
        ldx     #HUD_OBJ_OAM_WORD
        stx     OAMADDL
        ldx     #$0400
        stx     DMAP7
        ldx     #.loword(status_hud_obj_image)
        stx     A1T7L
        ldx     #HUD_OBJ_TAIL_BYTES
        stx     DAS7L
        lda     #^status_hud_obj_image
        sta     A1B7
        lda     #$80
        sta     MDMAEN
        stz     status_hud_obj_replay
@Done:
        rtl

StatusHudObjOffscreen:
        .byte $F0
; BG1 scroll X=1 shifts the HUD one screen pixel left. The sides never wrap
; here because the numeric cells are inside the 256-pixel viewport.
StatusHudObjPositions:
        .repeat 6, slot
          .word (BSP_PLAYABLE_WORLD_HEIGHT << 8) | ((9+slot*3+(slot/3)*5)*8-HUD_SCROLL_X)
        .endrepeat
.popseg
