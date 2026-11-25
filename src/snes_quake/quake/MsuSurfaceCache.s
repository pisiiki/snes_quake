; CPU producer for the opt-in X2 MSU-1 experiment. Only idle FX3 jobs can
; replace a page. The last sixteen painter IDs are the nearest requests.
.ifdef QUAKE_MSU_CACHE
MSU_HINT_OFFSET = MSU_SURFACE_DIRECTORY + BSP_WORLD_FACE_COUNT * 64
.else
MSU_HINT_OFFSET = 8 + BSP_WORLD_FACE_COUNT * 64
.endif
MSU_HINT_BYTES = (BSP_WORLD_FACE_COUNT + 7) / 8

.segment "LORAM"
.ifdef QUAKE_MSU_CACHE
msu_state:          .res 2       ; pending, absent, available, available with hints
msu_packet:         .res 2
msu_scan_limit:     .res 2
msu_scan_position:  .res 2
msu_slot:           .res 2
msu_face:           .res 2
.endif
msu_seek:           .res 4
.ifdef QUAKE_MSU_CACHE
msu_entry:          .res 16
msu_payload_address: .res 2
msu_cache_uploads:  .res 2
msu_cache_bytes:    .res 4
msu_eligible:       .res MSU_HINT_BYTES + 1  ; final byte allows a word read
.endif

.segment "CODE"
.ifdef QUAKE_MSU_CACHE
.import __GSU_MSU_CODE_RUN__, __GSU_MSU_CODE_LOAD__, __GSU_MSU_CODE_SIZE__
.import __BSP_COMPOSED_DIRECTORY_LOAD__

; The flat framebuffer and F3 images can overwrite bank $70. Restore the
; code and invalidate all slots whenever the reciprocal mirror is installed.
MsuCacheResetArena:
        RW_forced a16i16
        BSP_STATIC_COPY __GSU_MSU_CODE_RUN__, BSP_CPU_CODE_ADDRESS(__GSU_MSU_CODE_LOAD__), __GSU_MSU_CODE_SIZE__
        RW_forced a16i16
        lda     #$FFFF
        sta     msu_packet
        .repeat MSU_SURFACE_SLOT_COUNT, I
        sta     f:MSU_SURFACE_TAGS + I * MSU_SURFACE_TAG_BYTES
        .endrepeat
        lda     #0
        sta     f:$710000 + MSU_SURFACE_READY
        ldx     #$FE
@ClearIndex:
        sta     f:MSU_SURFACE_INDEX_CPU,x
        dex
        dex
        bpl     @ClearIndex
        rts

MsuCacheUpdate:
        RW_forced a16i16
        lda     render_camera+10
        and     #$00FF
        cmp     #BSP_TECHNIQUE_TEXTURED_LIGHTMAP
        bne     @Done
        lda     active_packet_guard_status
        cmp     #$A55A
        bne     @Done
        lda     active_packet_error
        bne     @Done
        lda     active_packet_revision
        cmp     msu_packet
        beq     @Done
        sta     msu_packet
        lda     msu_state
        bne     :+
        jsr     MsuCacheProbe
:
        cmp     #2
        bcc     @Done
        lda     active_packet_face_count
        beq     @Done
        cmp     #GSU_PACKET_FACE_CAPACITY + 1
        bcs     @Done
        asl     a
        sta     msu_scan_limit
        sec
        sbc     #32
        bcs     :+
        lda     #0
:
        sta     msu_scan_position
        jsr     MsuCacheChooseSlot
        bcc     @ScanStart
@Done:
        rts
@ScanStart:
        ldx     msu_scan_limit
@Scan:
        dex
        dex
        lda     f:GSU_DATA_BASE + GSU_SOURCE_FACE_IDS_OFFSET,x
        cmp     #BSP_WORLD_FACE_COUNT
        bcs     @Next
        stx     msu_scan_limit
        sta     msu_face
        lda     msu_state
        cmp     #3
        bne     @Candidate
        lda     msu_face
        and     #7
        tax
        lda     f:MsuHintMasks,x
        and     #$00FF
        tay
        lda     msu_face
        lsr     a
        lsr     a
        lsr     a
        tax
        tya
        and     msu_eligible,x
        beq     @Resume
@Candidate:
        lda     msu_face
        asl     a
        tax
        ; Prefer already-baked ROM surfaces. Spend the streaming budget on
        ; faces that otherwise need runtime texture/lightmap composition.
        lda     f:__BSP_COMPOSED_DIRECTORY_LOAD__,x
        cmp     #$FFFF
        bne     @Resume
        lda     msu_face
        .repeat MSU_SURFACE_SLOT_COUNT, I
        cmp     f:MSU_SURFACE_TAGS + I * MSU_SURFACE_TAG_BYTES
        beq     @Resume
        .endrepeat
        jsr     MsuCacheReadFace
        bcs     @Resume
        jmp     MsuCacheLoadPage        ; attempt at most one payload per packet
@Resume:
        ldx     msu_scan_limit
@Next:
        cpx     msu_scan_position
        bne     @Scan
        rts

; Fill every available slot before evicting a face outside the shortlist.
MsuCacheChooseSlot:
        ldx     #0
        .repeat MSU_SURFACE_SLOT_COUNT, I
        lda     f:MSU_SURFACE_TAGS + I * MSU_SURFACE_TAG_BYTES
        bpl     :+
        ldx     #I * MSU_SURFACE_TAG_BYTES
        bra     @Empty
:
        .endrepeat
@Slot:
        stx     msu_slot
        lda     f:MSU_SURFACE_TAGS,x
        ldx     msu_scan_position
@Check:
        cmp     f:GSU_DATA_BASE + GSU_SOURCE_FACE_IDS_OFFSET,x
        beq     @Pinned
        inx
        inx
        cpx     msu_scan_limit
        bne     @Check
@Found:
        clc
        rts
@Pinned:
        lda     msu_slot
        clc
        adc     #MSU_SURFACE_TAG_BYTES
        tax
        cpx     #MSU_SURFACE_SLOT_COUNT * MSU_SURFACE_TAG_BYTES
        bcc     @Slot
        sec
        rts
@Empty:
        stx     msu_slot
        clc
        rts

MsuCacheProbe:
        lda     #1
        sta     msu_state
        RW      a8
        ldx     #0
@ID:
        lda     f:MSU_ID,x
        cmp     f:MsuDeviceID,x
        bne     @Done
        inx
        cpx     #6
        bne     @ID
        RW      a16
        stz     msu_seek
        stz     msu_seek+2
        jsr     MsuCacheSeek
        bcs     @Done16
        RW      a8
        ldx     #0
@Header:
        lda     f:MSU_READ
        cmp     f:MsuSurfaceHeader,x
        bne     @Done
        inx
        cpx     #6
        bne     @Header
        lda     f:MSU_READ
        cmp     #5
        bne     @Done
        lda     f:MSU_READ
        bne     @Done
        ldx     #0
@Binding:
        lda     f:MSU_READ
        cmp     f:MsuSurfaceBinding,x
        bne     @Done
        inx
        cpx     #32
        bne     @Binding
        RW      a16
        jsr     MsuCacheReadHints
        lda     msu_state
        cmp     #3
        bne     @Done16
        jsr     MsuL2Initialize
        bra     @Done16
@Done:
@Done16:
        RW_forced a16i16
        lda     msu_state
        rts

; A bound v5 sidecar must also match the compiled page size and valid hints.
MsuCacheReadHints:
        lda     #.loword(MSU_HINT_OFFSET)
        sta     msu_seek
        lda     #(MSU_HINT_OFFSET >> 16)
        sta     msu_seek+2
        jsr     MsuCacheSeek
        bcs     @Done16
        RW      a8
        lda     f:MSU_READ
        cmp     #<MSU_SURFACE_SLOT_BYTES
        bne     @Done
        lda     f:MSU_READ
        cmp     #>MSU_SURFACE_SLOT_BYTES
        bne     @Done
        ldy     #msu_eligible
        ldx     #MSU_HINT_BYTES
        jsr     MsuCacheStage
        lda     f:MSU_READ
        cmp     #$A5
        bne     @Done
        lda     f:MSU_READ
        cmp     #$5A
        bne     @Done
        RW      a16
        lda     #3
        sta     msu_state
@Done:
@Done16:
        RW_forced a16i16
        rts

; Each face has four directory entries. The reference uses full resolution
; for every face. An oversized mip 0 is a ROM fallback, never a lower mip.
MsuCacheReadFace:
        jsr     MsuL2Find
        bcs     :+
        rts
:
        lda     msu_face
        sta     msu_seek
        stz     msu_seek+2
        .repeat 6
        asl     msu_seek
        rol     msu_seek+2
        .endrepeat
        lda     msu_seek
        clc
        adc     #MSU_SURFACE_DIRECTORY
        sta     msu_seek
        bcc     :+
        inc     msu_seek+2
:
        jsr     MsuCacheSeek
        bcs     @Fail
        RW      a8
        ldx     #0
@ReadEntry:
        lda     f:MSU_READ
        sta     msu_entry,x
        inx
        cpx     #16
        bne     @ReadEntry
        RW      a16
        lda     msu_entry+4             ; width
        beq     @Fail
        cmp     #MSU_SURFACE_SLOT_BYTES+1
        bcs     @Fail
        lda     msu_entry+14            ; high word of byte count
        bne     @Fail
        lda     msu_entry+12
        beq     @Fail
        cmp     #MSU_SURFACE_SLOT_BYTES+1
        rts                             ; C clear iff the page fits
@Fail:
        sec
        rts

MsuCacheLoadPage:
        jsr     MsuL2Load
        bcc     :+
        rts
:
        lda     msu_slot
        lsr     a
        lsr     a                       ; tag byte offset -> word table index
        tax
        lda     f:MsuSlotAddress,x
        sta     msu_payload_address

        jsr     MsuCacheClearIndex
        ldx     msu_slot
        lda     #$FFFF
        sta     f:MSU_SURFACE_TAGS,x

        ; Copy B $2180 to incrementing A $70:slot. Rewind WMADD first.
        RW      a8
        ldx     msu_l2_payload
        stx     WMADDL
        lda     #1
        sta     WMADDH
        ldx     msu_payload_address
        stx     A1T6L
        lda     #$70
        sta     A1B6
        lda     #$80
        sta     DMAP6
        sta     BBAD6
        ldx     msu_entry+12
        stx     DAS6L
        lda     #$40
        sta     MDMAEN

        RW      a16
        ldx     msu_slot
        lda     msu_entry+4
        sta     f:MSU_SURFACE_TAGS+2,x
        lda     msu_payload_address
        clc
        adc     msu_entry+8             ; precomputed signed coordinate bias
        sta     f:MSU_SURFACE_TAGS+4,x
        lda     #0                      ; reserved, currently mip 0 only
        sta     f:MSU_SURFACE_TAGS+6,x
        lda     msu_face
        sta     f:MSU_SURFACE_TAGS,x     ; commit tag last
        jsr     MsuCachePublishIndex
        lda     #1
        sta     f:$710000 + MSU_SURFACE_READY
        inc     msu_cache_uploads
        lda     msu_cache_bytes
        clc
        adc     msu_entry+12
        sta     msu_cache_bytes
        bcc     :+
        inc     msu_cache_bytes+2
:
        clc
        rts

.include "quake/MsuWramCache.s"
.endif
; A8, X=nonzero byte count, Y=low-WRAM destination.
MsuCacheStage:
        RW_forced a8i16
        sty     WMADDL
        stz     WMADDH
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
        rts

.ifdef QUAKE_MSU_CACHE
; Clear just the buckets named by the old tags, then publish the complete
; new index. Collisions use an exact tag scan instead of dropping either page.
MsuCacheClearIndex:
        RW_assume a16i16
        .repeat MSU_SURFACE_SLOT_COUNT, I
        lda     f:MSU_SURFACE_TAGS + I * MSU_SURFACE_TAG_BYTES
        and     #$00FF
        tax
        RW      a8
        lda     #0
        sta     f:MSU_SURFACE_INDEX_CPU,x
        RW      a16
        .endrepeat
        rts

MsuCachePublishIndex:
        RW_assume a16i16
        ldy     #0
@Slot:
        tyx
        lda     f:MSU_SURFACE_TAGS,x
        bmi     @Next
        and     #$00FF
        tax
        RW      a8
        lda     f:MSU_SURFACE_INDEX_CPU,x
        beq     @Empty
        lda     #MSU_SURFACE_COLLISION
        bra     @Store
@Empty:
        tya
        inc     a
@Store:
        sta     f:MSU_SURFACE_INDEX_CPU,x
        RW      a16
@Next:
        tya
        clc
        adc     #MSU_SURFACE_TAG_BYTES
        tay
        cpy     #MSU_SURFACE_SLOT_COUNT * MSU_SURFACE_TAG_BYTES
        bcc     @Slot
        rts
.endif

MsuCacheSeek:
        RW_forced a8i16
        lda     msu_seek
        sta     f:MSU_STATUS
        lda     msu_seek+1
        sta     f:MSU_STATUS+1
        lda     msu_seek+2
        sta     f:MSU_STATUS+2
        lda     msu_seek+3
        sta     f:MSU_STATUS+3
        ldx     #$0800
@Busy:
        lda     f:MSU_STATUS
        bpl     @Ready
        dex
        bne     @Busy
        RW      a16
        sec
        rts
@Ready:
        RW_forced a8i16
        RW      a16
        clc
        rts

.ifdef QUAKE_MSU_CACHE
MsuDeviceID: .byte "S-MSU1"
MsuSurfaceHeader: .byte "QMSU"
        .word BSP_WORLD_FACE_COUNT
MsuHintMasks: .byte $01, $02, $04, $08, $10, $20, $40, $80, $00
MsuSlotAddress:
        .repeat MSU_SURFACE_SLOT_COUNT, I
        .word MSU_SURFACE_SLOT_BASE + I * MSU_SURFACE_SLOT_BYTES
        .endrepeat
MsuSurfaceBinding:
        .incbin .sprintf("Data/MsuSurfaceBinding-%d.bin", MSU_SURFACE_SLOT_BYTES)
.assert * - MsuSurfaceBinding = 32, error, "Bound MSU surface identity must be exactly 32 bytes"
.endif
