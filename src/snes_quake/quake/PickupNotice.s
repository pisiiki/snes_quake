; Four console-notify rows in the stock three-second client window.
; Called with DBR=$7f from accepted E1M1 touches. Preserve the scanner's X.
NOTICE_SHELLS   = 1
NOTICE_NAILS    = 2
NOTICE_NAILGUN  = 3
NOTICE_ARMOR    = 4
NOTICE_HEALTH15 = 5
NOTICE_HEALTH25 = 6
NOTICE_MEGA     = 7
NOTICE_QUAD     = 8
NOTICE_SUIT     = 9
NOTICE_BACKPACK = 10
NOTICE_SSG      = 11

PickupNotify:
        RW_assume a16i16
        phx
        jsr     @AddRow
        cmp     #NOTICE_SSG
        bne     :+
        lda     #NOTICE_SSG+1
        jsr     @AddRow
:       lda     #30
        sta     a:.loword(pickup_bonus_ticks)
        inc     a:.loword(pickup_notice_revision)
.ifdef PICKUP_BLEND
        lda     #1
        sta     a:.loword(pickup_peak_pending)
.endif
        plx
        rtl
@AddRow:
        pha
        ldx     a:.loword(pickup_notice_next)
        ; Install the new lifetime first. An intervening NMI must not expire
        ; the previous message after its slot has been given a new ID.
        lda     #180
        sta     a:.loword(pickup_notice_life),x
        lda     1,s
        sta     a:.loword(pickup_notice_rows),x
        txa
        inc
        inc
        and     #6
        sta     a:.loword(pickup_notice_next)
        pla
        rts

; Video-time expiration also runs while the player is in the menu.
PickupNotifyVideo:
        RW_assume a16i16
        lda     f:pickup_bonus_ticks
        beq     :+
        dec
        sta     f:pickup_bonus_ticks
:       ldx     #6
@Age:   lda     f:pickup_notice_life,x
        beq     @Next
        dec
        sta     f:pickup_notice_life,x
        bne     @Next
        sta     f:pickup_notice_rows,x
        lda     f:pickup_notice_revision
        inc
        sta     f:pickup_notice_revision
@Next:  dex
        dex
        bpl     @Age
        rtl
