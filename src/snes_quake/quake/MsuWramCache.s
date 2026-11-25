; Immutable pre-lit pages in CPU WRAM. FX3 samples only the uploaded L1 copy.
; FIFO replacement is bounded; a failed refill never publishes its old key.
.segment "LORAM"
msu_l2_next: .res 2
msu_l2_slot: .res 2
msu_l2_payload: .res 2
msu_l2_hit: .res 2
msu_l2_hits: .res 2
msu_l2_misses: .res 2

.segment "EXRAM"
MsuL2Payload:
        .res MSU_L2_SLOT_COUNT * MSU_SURFACE_SLOT_BYTES
MsuL2Tags:
        .res MSU_L2_SLOT_COUNT * 2
MsuL2Descriptors:
        .res MSU_L2_SLOT_COUNT * MSU_L2_ENTRY_BYTES
MsuL2End:
.assert MsuL2Payload = $7F0000, lderror, "MSU backing cache must start at reclaimed collision WRAM"
.assert MsuL2End <= $7F0000 + BSP_COLLISION_PAYLOAD_BYTES, lderror, "MSU backing cache exceeds reclaimed collision RAM"

.segment "CODE"
MsuL2Initialize:
        RW_forced a16i16
        stz     msu_l2_next
        lda     #$FFFF
        ldx     #MSU_L2_SLOT_COUNT * 2 - 2
@Clear:
        sta     f:MsuL2Tags,x
        dex
        dex
        bpl     @Clear
        rts

; C clear: a complete WRAM page hit, with the descriptor restored.
MsuL2Find:
        RW_forced a16i16
        stz     msu_l2_hit
        ldx     #0
@Find:
        lda     f:MsuL2Tags,x
        cmp     msu_face
        beq     @Hit
        inx
        inx
        cpx     #MSU_L2_SLOT_COUNT * 2
        bcc     @Find
        inc     msu_l2_misses
        sec
        rts
@Hit:
        lda     f:MsuL2Addresses,x
        sta     msu_l2_payload
        txa
        asl     a
        asl     a
        asl     a
        tax
        ldy     #0
@Copy:
        lda     f:MsuL2Descriptors,x
        sta     msu_entry,y
        inx
        inx
        iny
        iny
        cpy     #MSU_L2_ENTRY_BYTES
        bcc     @Copy
        inc     msu_l2_hit
        inc     msu_l2_hits
        clc
        rts

; On hit, no MSU access. On miss, validate into bank $7F before publishing.
MsuL2Load:
        RW_forced a16i16
        lda     msu_l2_hit
        beq     @Miss
        clc
        rts
@Miss:
        lda     msu_entry
        sta     msu_seek
        lda     msu_entry+2
        sta     msu_seek+2
        jsr     MsuCacheSeek
        bcc     :+
        rts
:
        ldx     msu_l2_next
        stx     msu_l2_slot
        lda     #$FFFF
        sta     f:MsuL2Tags,x
        lda     f:MsuL2Addresses,x
        sta     msu_l2_payload
        tay
        RW      a8
        sty     WMADDL
        lda     #1
        sta     WMADDH
        ldx     msu_entry+12
        stx     DAS6L
        ldx     #.loword(MSU_READ)
        stx     A1T6L
        stz     A1B6
        lda     #$80
        sta     BBAD6
        lda     #$08
        sta     DMAP6
        lda     #$40
        sta     MDMAEN
        lda     f:MSU_READ
        cmp     #$A5
        bne     @Fail
        lda     f:MSU_READ
        cmp     #$5A
        bne     @Fail
        RW      a16
        lda     msu_l2_slot
        asl     a
        asl     a
        asl     a
        tax
        ldy     #0
@Copy:
        lda     msu_entry,y
        sta     f:MsuL2Descriptors,x
        inx
        inx
        iny
        iny
        cpy     #MSU_L2_ENTRY_BYTES
        bcc     @Copy
        ldx     msu_l2_slot
        lda     msu_face
        sta     f:MsuL2Tags,x
        inx
        inx
        cpx     #MSU_L2_SLOT_COUNT * 2
        bcc     :+
        ldx     #0
:
        stx     msu_l2_next
        clc
        rts
@Fail:
        RW_forced a16i16
        sec
        rts

MsuL2Addresses:
        .repeat MSU_L2_SLOT_COUNT, I
        .word .loword(MsuL2Payload) + I * MSU_SURFACE_SLOT_BYTES
        .endrepeat
