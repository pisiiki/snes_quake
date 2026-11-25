; One world face's packed S/T contour is consumed before clipping uses buffer B.
.ifdef PLAYABLE_WORLD_COORDINATE_STREAM
.import WorldCoordinateStreamIndex:far, WorldCoordinateStreamCount:far
.import WorldCoordinateStreamBuffer:far, WorldCoordinateStreamRequest:far
.import WorldCoordinateStreamResume:far, F3_WorldCoordinateStreamResume:far
.import F3_WorldCoordinateStreamBuffer:far
.assert WorldCoordinateStreamBuffer = F3_WorldCoordinateStreamBuffer, lderror, "X2 and X3 coordinate scratch differ"
.assert .bankbyte(WorldCoordinateStreamResume) = $70, lderror, "World coordinate resume must stay in RAM"
.assert WorldCoordinateStreamResume = F3_WorldCoordinateStreamResume, lderror, "X2 and X3 coordinate resume must use the same address"
.assert .bankbyte(WorldCoordinateStreamBuffer) = ^GSU_DATA_BASE, lderror, "World coordinate cache DMA requires bank $71"

.if PLAYABLE_MAP_ID = PLAYABLE_E1M1_MAP_ID
PLAYABLE_COORDINATE_CACHE = 1
; E1M1's ROM contours leave a smaller checked WRAM working set.
WORLD_COORDINATE_CACHE_SLOTS = 256
WORLD_COORDINATE_CACHE_BYTES = WORLD_COORDINATE_CACHE_SLOTS * (4 + 32)
WORLD_COORDINATE_CACHE_BANK = $7E
.segment "CODE"
PlayableCopyCheckedCache7e:
        PLAYABLE_COPY_CHECKED_CACHE $7E
WorldCoordinateCopyCheckedCache = PlayableCopyCheckedCache7e
.elseif .defined(PLAYABLE_COORDINATE_CACHE)
WORLD_COORDINATE_CACHE_BANK = $7F
WorldCoordinateCopyCheckedCache = WorldCopyCheckedCache
.endif

.ifdef PLAYABLE_COORDINATE_CACHE
.segment "LORAM"
WorldCoordinateCacheKey: .res 2
WorldCoordinateCacheSlot: .res 2
WorldCoordinateCacheHits: .res 2

.if WORLD_COORDINATE_CACHE_BANK = $7E
.segment "PLAYABLE_STREAM_CACHE"
.else
.segment "WORLD_LIGHTMAP_CACHE"
.endif
WorldCoordinateCacheTags: .res WORLD_COORDINATE_CACHE_SLOTS * 4
WorldCoordinateCacheData: .res WORLD_COORDINATE_CACHE_SLOTS * 32
WorldCoordinateCacheEnd:
.assert WorldCoordinateCacheEnd-WorldCoordinateCacheTags = WORLD_COORDINATE_CACHE_BYTES, error, "Coordinate cache size changed"
.assert .bankbyte(WorldCoordinateCacheTags) = WORLD_COORDINATE_CACHE_BANK, lderror, "Coordinate cache starts outside its WRAM bank"
.assert .bankbyte(WorldCoordinateCacheEnd-1) = WORLD_COORDINATE_CACHE_BANK, lderror, "Coordinate cache crosses its WRAM bank"
.endif

.segment "RODATA"
WorldCoordinateSizeTable:
        WORLD_COORDINATE_CHUNKS
WorldCoordinateSeekTable:
        WORLD_COORDINATE_SEEKS

.segment "CODE"
WorldCoordinateStreamFill:
        RW_assume a16i16
        lda     f:WorldCoordinateStreamCount
        beq     WorldCoordinateBadRequest
        cmp     #BSP_WORLD_MAX_FACE_VERTICES+1
        bcc     WorldCoordinateValidCount
WorldCoordinateBadRequest:
        RW_forced a8i16
        lda     #8
        jmp     PlayableArchiveFatal
WorldCoordinateValidCount:
        RW_forced a16i16
        asl
        asl
        sta     playable_copy_remaining
.ifdef PLAYABLE_COORDINATE_CACHE
        jsr     WorldCoordinateRestoreCached
        bcc     :+
        rts
:
.endif
        lda     f:WorldCoordinateStreamIndex
        xba
        and     #$00e0
        .repeat 4
        lsr
        .endrepeat
        tax
        cpx     #2*WORLD_COORDINATE_CHUNK_COUNT
        bcs     WorldCoordinateBadRequest
        lda     f:WorldCoordinateStreamIndex
        and     #$1fff
        asl
        asl
        pha
        clc
        adc     playable_copy_remaining
        cmp     f:WorldCoordinateSizeTable,x
        bcc     @Seek
        bne     WorldCoordinateBadRequest
@Seek:
        txa
        asl
        tax
        pla
        asl
        clc
        adc     f:WorldCoordinateSeekTable,x
        sta     playable_archive_seek
        lda     f:WorldCoordinateSeekTable+2,x
        adc     #0
        sta     playable_archive_seek+2
        RW      a8
        lda     playable_archive_busy
        beq     :+
        lda     #5
        jmp     PlayableArchiveFatal
:
        inc     playable_archive_busy
        jsr     PlayableEnsureArchive
        jsr     PlayableSeekArchive
        ldx     #0
@Copy:
        ; DBR is the module bank, which mirrors MSU MMIO. Each contour
        ; vertex is four bytes, so test the bound once per complete S/T.
        .repeat 4
        lda     a:$2001
        sta     f:WorldCoordinateStreamBuffer,x
        eor     a:$2001
        inc                             ; Zero only for complementary bytes.
        bne     @BadPair
        inx
        .endrepeat
        cpx     playable_copy_remaining
        bne     @Copy
        stz     playable_archive_busy
        RW      a16
.ifdef PLAYABLE_COORDINATE_CACHE
        jsr     WorldCoordinateRemember
.endif
        rts
@BadPair:
        RW_forced a8i16
        lda     #3
        jmp     PlayableArchiveFatal

.ifdef PLAYABLE_COORDINATE_CACHE
; The map's boot clears WRAM, so zero is an invalid key. Publish only after
; all MSU pairs pass validation. Both first index and length must match.
WorldCoordinateRestoreCached:
        RW_assume a16i16
        ldx     #$FFFF
        stx     WorldCoordinateCacheSlot
        cmp     #33
        bcs     @Miss
        lda     f:WorldCoordinateStreamIndex
        inc
        sta     WorldCoordinateCacheKey
.if WORLD_COORDINATE_CACHE_SLOTS = 512
        ; Fold the upper seven bits into the low nine without aliasing
        ; slot bit 8 to bit 0 as a widened byte swap would.
        lsr
        xba
        and     #$007F
.else
        xba
.endif
        eor     WorldCoordinateCacheKey
        and     #WORLD_COORDINATE_CACHE_SLOTS-1
        asl
        asl
        tax
        stx     WorldCoordinateCacheSlot
        lda     f:WorldCoordinateCacheTags,x
        cmp     WorldCoordinateCacheKey
        bne     @Miss
        lda     f:WorldCoordinateCacheTags+2,x
        cmp     playable_copy_remaining
        bne     @Miss
        jsr     WorldCoordinateCachePointer
        tax
        lda     playable_copy_remaining
        cmp     #16
        bcc     @Short
        ldy     #.loword(WorldCoordinateStreamBuffer)
        sec
        jsr     WorldCoordinateCopyCheckedCache
        bra     @Hit
@Short:
        ldy     #.loword(WorldCoordinateStreamBuffer)
        dec
        phb
        mvn     #WORLD_COORDINATE_CACHE_BANK, #$71
        plb
@Hit:
        inc     WorldCoordinateCacheHits
        sec
        rts
@Miss:
        clc
        rts

WorldCoordinateRemember:
        RW_assume a16i16
        ldx     WorldCoordinateCacheSlot
        bmi     @Done
        jsr     WorldCoordinateCachePointer
        tay
        lda     playable_copy_remaining
        cmp     #16
        bcc     @Short
        tyx
        ldy     #.loword(WorldCoordinateStreamBuffer)
        clc
        jsr     WorldCoordinateCopyCheckedCache
        bra     @Publish
@Short:
        ldx     #.loword(WorldCoordinateStreamBuffer)
        dec
        phb
        mvn     #$71, #WORLD_COORDINATE_CACHE_BANK
        plb
@Publish:
        ldx     WorldCoordinateCacheSlot
        lda     playable_copy_remaining
        sta     f:WorldCoordinateCacheTags+2,x
        lda     WorldCoordinateCacheKey
        sta     f:WorldCoordinateCacheTags,x
@Done:
        rts

WorldCoordinateCachePointer:
        RW_assume a16i16
        txa
        asl
        asl
        asl
        clc
        adc     #.loword(WorldCoordinateCacheData)
        rts
.endif
.endif
