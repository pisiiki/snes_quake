; Keep the first 64 exact walk-distance rows for active monster and gib
; traces. The rest can hold both results overlays until the next map.
.ifdef PLAYABLE_LARGE_DISTANCE_CACHE
INTER_CACHE = $7F0000 + w_distance_cache
INTER_CACHE_HALF = WALK_DISTANCE_CACHE_BYTES/2
INTER_THINKER_CACHE = 1024
.ifdef PLAYABLE_MAP_ID
INTER_SEEK_VAR = playable_archive_seek
.else
INTER_SEEK_VAR = intermission_packet      ; Never accessed by the standalone size probe.
.endif
INTER_PACKET_COUNT = 171               ; One background plus seventeen positions x ten digits.
.ifndef INTERMISSION_SEEK
INTERMISSION_SEEK = 0                  ; Standalone source size probe.
.endif

.pushseg
.segment "BSP_CPU_WALK_RUN"
IntermissionPrepare:
        ldy     #0
        lda     f:intermission_seconds
        ldx     #0
@Minute:cmp     #60
        bcc     @MinuteReady
        sbc     #60
        inx
        bra     @Minute
@MinuteReady:
        pha
        txa
        jsr     IntermissionThree
        pla
        ldx     #0
@Second:cmp     #10
        bcc     @SecondsReady
        sbc     #10
        inx
        bra     @Second
@SecondsReady:
        stx     a:.loword(intermission_digits)+6
        sta     a:.loword(intermission_digits)+8
        ldy     #10
        lda     f:quakec_found_secrets
        jsr     IntermissionThree
        lda     #QC_SECRET_COUNT
        jsr     IntermissionThree
        lda     f:intermission_kills
        jsr     IntermissionThree
        lda     f:intermission_monsters
        jsr     IntermissionThree
        stz     a:.loword(intermission_stream_base)
        lda     #(INTER_THINKER_CACHE/2)-8
        sta     f:intermission_walk_cache_mask
        lda     #INTER_THINKER_CACHE
        sta     a:.loword(intermission_cache_end)
        jsr     IntermissionFormat
        lda     #INTER_PACKET_COUNT
        sta     a:.loword(intermission_stream_base)
        lda     #INTER_CACHE_HALF
        sta     a:.loword(intermission_cache_end)
        jsr     IntermissionFormat
        rtl

; Original three-place Sbar numbers are right-aligned and discard excess leading digits.
IntermissionThree:
        cmp     #1000
        bcc     @Hundreds
        sbc     #1000
        bra     IntermissionThree
@Hundreds:
        ldx     #$ffff
        cmp     #100
        bcc     @StoreHundreds
        ldx     #0
@Hundred:inx
        sbc     #100
        cmp     #100
        bcs     @Hundred
@StoreHundreds:
        pha
        txa
        sta     a:.loword(intermission_digits),y
        iny
        iny
        pla
        cpx     #0
        bpl     @PadTens
        cmp     #10
        bcc     @StoreTens
@PadTens:
        ldx     #0
        cmp     #10
        bcc     @StoreTens
@Ten:   inx
        sbc     #10
        cmp     #10
        bcs     @Ten
@StoreTens:
        pha
        txa
        sta     a:.loword(intermission_digits),y
        iny
        iny
        pla
        sta     a:.loword(intermission_digits),y
        iny
        iny
        rts

IntermissionFormat:
        lda     a:.loword(intermission_stream_base)
        jsr     IntermissionCachePacket
        lda     a:.loword(intermission_stream_base)
        inc
        sta     a:.loword(intermission_packet)
        ldy     #0
@Digit: lda     a:.loword(intermission_digits),y
        bmi     @Next
        clc
        adc     a:.loword(intermission_packet)
        phy
        jsr     IntermissionCachePacket
        ply
@Next:  lda     a:.loword(intermission_packet)
        clc
        adc     #10
        sta     a:.loword(intermission_packet)
        iny
        iny
        cpy     #34
        bcc     @Digit
        ldx     a:.loword(intermission_cache_end)
        lda     #$ffff
        sta     f:INTER_CACHE,x
        rts

IntermissionCachePacket:
        ; Directory entries hold 32-bit logical offsets into the paired MSU stream.
        asl
        asl
        jsr     IntermissionSeekOffset
        jsr     IntermissionReadWord
        pha
        jsr     IntermissionReadWord
        beq     :+
        jmp     IntermissionBad
:       pla
        jsr     IntermissionSeekOffset
        jsr     IntermissionReadWord
        beq     @Done
        tay
        ldx     a:.loword(intermission_cache_end)
@Record:RW      a8
        .repeat 11
        jsr     IntermissionReadByte
        sta     f:INTER_CACHE,x
        inx
        .endrepeat
        RW      a16
        dey
        bne     @Record
        stx     a:.loword(intermission_cache_end)
@Done:  rts

IntermissionSeekOffset:
        asl
        pha
        lda     #.hiword(INTERMISSION_SEEK)
        adc     #0
        sta     f:INTER_SEEK_VAR+2
        pla
        clc
        adc     #.loword(INTERMISSION_SEEK)
        sta     f:INTER_SEEK_VAR
        bcc     :+
        lda     f:INTER_SEEK_VAR+2
        inc
        sta     f:INTER_SEEK_VAR+2
:       jsl     IntermissionSeekLong
        rts

IntermissionReadWord:
        RW      a8
        jsr     IntermissionReadByte
        pha
        jsr     IntermissionReadByte
        xba
        pla
        RW      a16
        rts

IntermissionReadByte:
        RW_assume a8i16
        lda     f:$002001
        sta     a:.loword(intermission_byte)
        eor     f:$002001
        cmp     #$ff
        bne     IntermissionBad
        lda     a:.loword(intermission_byte)
        rts
IntermissionBad:
        RW_forced a8i16
        lda     #8
.ifdef PLAYABLE_MAP_ID
        jml     PlayableArchiveFatal
.else
        stp
        .res    3,$ea
.endif

; Composite the original palette indices on the completed producer slot. The
; immutable GSU world and both distance caches used during gameplay are separate.
IntermissionStage:
        RW_assume a16i16
        phb
        pea     $7f7f
        plb
        plb
        ldy     #INTER_THINKER_CACHE
        cmp     #3
        bne     :+
        ldy     #INTER_CACHE_HALF
:       lda     f:producer_slot
        beq     :+
        lda     #.loword(StagedFrame1)
        bra     :++
:       lda     #.loword(StagedFrame0)
:       sta     a:.loword(intermission_slot)
@Cell:  lda     a:w_distance_cache,y
        bpl     :+
        plb
        rtl
:       clc
        adc     a:.loword(intermission_slot)
        tax
        iny
        iny
        RW      a8
        lda     a:w_distance_cache,y
        eor     #$ff
        sta     a:.loword(intermission_byte)
        iny
        .repeat 8,I
        lda     f:$7E0000+((I/2)*16)+(I .mod 2),x
        and     a:.loword(intermission_byte)
        ora     a:w_distance_cache,y
        sta     f:$7E0000+((I/2)*16)+(I .mod 2),x
        iny
        .endrepeat
        RW      a16
        jmp     @Cell

.pushseg
.segment "CODE"
IntermissionSeekLong:
        phb
        phk
        plb
        RW      a8
.ifdef PLAYABLE_MAP_ID
        jsr     PlayableEnsureArchive
        jsr     PlayableSeekArchive
.else
        .res    6,$ea
.endif
        RW      a16
        plb
        rtl
.popseg
.popseg
.endif
