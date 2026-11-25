; Rebuild the four console tile rows only when a pickup arrives or expires.
PickupNoticeMap:
        RW_assume a8i16
        RW      a16
        lda     f:pickup_notice_revision
        cmp     pickup_screen_revision
        RW      a8
        beq     @Unchanged
        jsr     StartWarningDMATime
        bcs     @Unchanged
        RW      a16
        lda     f:pickup_notice_revision
        sta     pickup_screen_revision
        lda     f:pickup_notice_next
        tax
        ldy     #4
        RW      a8
        stz     pickup_screen_rows
        lda     #$80
        sta     VMAINC
        lda     #^PICKUP_ROWS
        sta     A1B7
        RW      a16
        lda     #$1801
        sta     DMAP7
        lda     #PICKUP_MAP_VRAM/2
        sta     VMADDL
@Scan:  lda     f:pickup_notice_rows,x
        beq     @Next
        jsr     @Row
        RW      a8
        inc     pickup_screen_rows
        RW      a16
@Next:  txa
        inc
        inc
        and     #6
        tax
        dey
        bne     @Scan
        lda     #4
        sec
        sbc     pickup_screen_rows
        and     #$ff
        tay
        beq     @Finish
@Blank: lda     #0
        jsr     @Row
        dey
        bne     @Blank
@Finish:
        RW      a8
        lda     pickup_screen_rows
        ora     start_warning_oam
        bne     :+
        stz     CGADSUB
        lda     #RUNTIME_MENU_COLOR_WINDOW_CLOSED
        sta     CGSWSEL
:       sec
        rts
@Unchanged:
        clc
        rts
@Row:   ; Each ROM row has 32 tile words. DMA advances the VRAM destination.
        RW_assume a16i16
        .repeat 6
          asl
        .endrepeat
        clc
        adc     #.loword(PICKUP_ROWS)
        sta     A1T7L
        lda     #64
        sta     DAS7L
        RW      a8
        lda     #$80
        sta     MDMAEN
        RW      a16
        rts

PickupNoticeLayers:
        RW_assume a8i16
        pha
        lda     runtime_menu_open
        bne     @Idle
        lda     pickup_screen_rows
        beq     @Idle
        lda     quake_restart_pending
        bne     @Idle
        jsl     StartWarningArm
        stz     CGSWSEL
        lda     #$ff
        sta     COLDATA
        lda     #CG_BG2_ON
        sta     CGADSUB
        lda     weapon_obj_oam_word
        beq     @Background
        ldx     #.loword(StatusHudPickupObjLayers)
        lda     start_warning_oam
        beq     :+
        ldx     #.loword(StatusHudPickupCenterObjLayers)
:       lda     #$13
        bra     @Arm
@Background:
        ldx     #.loword(StatusHudPickupLayers)
        lda     start_warning_oam
        beq     :+
        ldx     #.loword(StatusHudPickupCenterLayers)
:       lda     #$03
@Arm:   sta     TM
        stx     A1T2L
        pla
        ora     #HUD_OBJ_HDMA | START_WARNING_SCROLL_HDMA
        sec
        rtl
@Idle:  pla
        clc
        rtl

.include "quake/PickupPalette.s"
