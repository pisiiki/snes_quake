; The renderer waits for checked MSU samples in its existing 512-byte cache.
; Caller owns the renderer wait, and the GSU is stopped in RAM $70.
; Copy A bytes between WRAM at X and stopped FX3 RAM at $71:Y.
; Carry set restores to FX3. Carry clear retains newly checked bytes in WRAM.
.macro PLAYABLE_COPY_CHECKED_CACHE wram_bank
        RW_assume a16i16
        sta     DAS6L
        stx     WMADDL
        sty     A1T6L
        lda     #$8000
        bcc     :+
        ora     #$0080
:
        sta     DMAP6
        RW      a8
        lda     #(wram_bank - $7E)
        sta     WMADDH
        lda     #^GSU_DATA_BASE
        sta     A1B6
        lda     #$40
        sta     MDMAEN
        RW      a16
        rts
.endmacro

.ifdef PLAYABLE_WORLD_LIGHTMAP_STREAM
.import WorldLightmapStreamBank:far, WorldLightmapStreamAddress:far
.import WorldLightmapStreamWidth:far, WorldLightmapStreamHeight:far
.import WorldLightmapStreamResume:far, F3_WorldLightmapStreamResume:far
.import F3_WorldLightmapStreamBank:far, F3_WorldLightmapStreamAddress:far
.import F3_WorldLightmapStreamWidth:far, F3_WorldLightmapStreamHeight:far
.assert .bankbyte(WorldLightmapStreamResume) = $70, lderror, "World lightmap resume must stay in RAM"
.assert WorldLightmapStreamResume = F3_WorldLightmapStreamResume, lderror, "X2 and X3 lightmap resume must use the same address"
.assert WorldLightmapStreamBank = F3_WorldLightmapStreamBank, lderror, "Renderer world lightmap bank differs"
.assert WorldLightmapStreamAddress = F3_WorldLightmapStreamAddress, lderror, "Renderer world lightmap address differs"
.assert WorldLightmapStreamWidth = F3_WorldLightmapStreamWidth, lderror, "Renderer world lightmap width differs"
.assert WorldLightmapStreamHeight = F3_WorldLightmapStreamHeight, lderror, "Renderer world lightmap height differs"

.segment "LORAM"
WorldLightmapCount: .res 2
WorldLightmapGroupEnd: .res 2
WorldLightmapSource: .res 2
WorldLightmapWidth: .res 2
WorldLightmapA: .res 1
WorldLightmapB: .res 1
WorldLightmapC: .res 1
WorldLightmapPart: .res 1
WorldLightmapUploads: .res 2

.if .defined(PLAYABLE_WORLD_COORDINATE_STREAM) && (PLAYABLE_MAP_ID <> PLAYABLE_START_MAP_ID)
PLAYABLE_COORDINATE_CACHE = 1
.if (PLAYABLE_MAP_ID = PLAYABLE_E1M2_MAP_ID) .or (PLAYABLE_MAP_ID = PLAYABLE_E1M4_MAP_ID)
; These maps' lightmap working sets leave room for more contour entries.
WORLD_COORDINATE_CACHE_SLOTS = 512
.else
WORLD_COORDINATE_CACHE_SLOTS = 256
.endif
WORLD_COORDINATE_CACHE_BYTES = WORLD_COORDINATE_CACHE_SLOTS * (4 + 32)
.else
WORLD_COORDINATE_CACHE_BYTES = 0
.endif
.ifdef QC_KNIGHT_ROSTER
; In bank $7F the roster, expanded VM scratch and alias colormap shadow
; share the streamed lightmap arena.
WORLD_KNIGHT_RAM_BYTES = QC_GRUNT_COUNT*QC_ENTITY_STRIDE + SPRITE_STREAM_CACHE_BYTES + $0180
.else
WORLD_KNIGHT_RAM_BYTES = 0
.endif
.if PLAYABLE_MAP_ID = PLAYABLE_E1M1_MAP_ID
; Keep the stock mover and monster state beside the streamed cache.
WORLD_LIGHTMAP_CACHE_BYTES = $6200
.elseif PLAYABLE_MAP_ID = PLAYABLE_START_MAP_ID
WORLD_LIGHTMAP_CACHE_BYTES = $B000
.elseif PLAYABLE_MAP_ID = PLAYABLE_E1M3_MAP_ID
; Leave room in bank $7F for the shared axe callback globals.
WORLD_LIGHTMAP_CACHE_BYTES = $9F80 - WORLD_COORDINATE_CACHE_BYTES
.elseif PLAYABLE_MAP_ID = PLAYABLE_E1M4_MAP_ID
WORLD_LIGHTMAP_CACHE_BYTES = $9000 - WORLD_COORDINATE_CACHE_BYTES - WORLD_KNIGHT_RAM_BYTES
.else
WORLD_LIGHTMAP_CACHE_BYTES = $A000 - WORLD_COORDINATE_CACHE_BYTES - WORLD_KNIGHT_RAM_BYTES
.endif
WORLD_LIGHTMAP_INDEX_BYTES = 2 * BSP_WORLD_FACE_COUNT
WorldLightmapCacheKey: .res 2
WorldLightmapCacheUsed: .res 2
WorldLightmapCacheHits: .res 2
WorldLightmapCacheResets: .res 2
.ifdef PLAYABLE_LIGHTMAP_REGIONS
WORLD_LIGHTMAP_REGION_BYTES = WORLD_LIGHTMAP_CACHE_BYTES / 2
.assert WORLD_LIGHTMAP_REGION_BYTES >= GSU_LIGHTMAP_CACHE_BYTES + 4, error, "Region cannot hold the largest grid"
WorldLightmapActiveRegion: .res 2
WorldLightmapRegionHead: .res 4
.endif

.segment "WORLD_LIGHTMAP_CACHE"
WorldLightmapCacheIndex: .res WORLD_LIGHTMAP_INDEX_BYTES
WorldLightmapCacheData: .res WORLD_LIGHTMAP_CACHE_BYTES
WorldLightmapCacheEnd:
.assert .bankbyte(WorldLightmapCacheIndex) = $7F, lderror, "World lightmap index must be in WRAM"
.assert .loword(WorldLightmapCacheData) <> 0, lderror, "World lightmap index uses zero for missing entries"
.assert .bankbyte(WorldLightmapCacheEnd-1) = $7F, lderror, "World lightmap cache exceeds WRAM bank"

.segment "RODATA"
WorldLightmapSizeTable:
        WORLD_LIGHTMAP_CHUNK_SIZES
WorldLightmapSeekTable:
        WORLD_LIGHTMAP_CHUNK_SEEKS
.ifdef PLAYABLE_LIGHTMAP_REGIONS
WorldLightmapRegionBase:
        .word   0, WORLD_LIGHTMAP_REGION_BYTES
WorldLightmapRegionLimit:
        .word   WORLD_LIGHTMAP_REGION_BYTES + 1, WORLD_LIGHTMAP_CACHE_BYTES + 1
.endif

.segment "CODE"
; DBR is the current module bank, which mirrors MSU MMIO. In A8/I16 the
; low byte transfers through Y intact; this also avoids a WRAM scratch round
; trip. No continuation can run until every requested pair has passed.
.macro WORLD_LIGHTMAP_READ_PAIR
        lda     a:$2001
        tay
        eor     a:$2001
        cmp     #$ff
        beq     :+
        jmp     WorldLightmapBadPair
:
        tya
.endmacro

.macro WORLD_LIGHTMAP_DECODE_GROUP tail, done
        WORLD_LIGHTMAP_READ_PAIR
        sta     WorldLightmapA
        and     #$3f
        ora     #$c0
        sta     f:GSU_DATA_BASE+GSU_LIGHTMAP_CACHE_OFFSET,x
        inx
        .if tail
        cpx     WorldLightmapCount
        beq     done
        .endif
        WORLD_LIGHTMAP_READ_PAIR
        sta     WorldLightmapB
        and     #$0f
        asl
        asl
        sta     WorldLightmapPart
        lda     WorldLightmapA
        ; The carry entering these three rotates is shifted above bit 1.
        rol
        rol
        rol
        and     #3
        ora     WorldLightmapPart
        ora     #$c0
        sta     f:GSU_DATA_BASE+GSU_LIGHTMAP_CACHE_OFFSET,x
        inx
        .if tail
        cpx     WorldLightmapCount
        beq     done
        .endif
        WORLD_LIGHTMAP_READ_PAIR
        sta     WorldLightmapC
        and     #3
        .repeat 4
        asl
        .endrepeat
        sta     WorldLightmapPart
        lda     WorldLightmapB
        .repeat 4
        lsr
        .endrepeat
        ora     WorldLightmapPart
        ora     #$c0
        sta     f:GSU_DATA_BASE+GSU_LIGHTMAP_CACHE_OFFSET,x
        inx
        .if !tail
        lda     WorldLightmapC
        lsr
        lsr
        ora     #$c0
        sta     f:GSU_DATA_BASE+GSU_LIGHTMAP_CACHE_OFFSET,x
        inx
        .endif
.endmacro

.macro WORLD_LIGHTMAP_LOOKUP miss
        lda     f:GSU_DATA_BASE+GSU_RENDER_SOURCE_INDEX_OFFSET
        cmp     #BSP_WORLD_FACE_COUNT
        bcs     WorldLightmapBadRequest
        asl
        tax
        lda     f:WorldLightmapCacheIndex,x
        beq     miss
.endmacro

; The world directory is immutable for the lifetime of the map. The stopped
; shader's source-face index identifies its grid, independently of packet order.
; BootVector clears WRAM on every module load. A live restart of the same map
; can reuse checked bytes from that same archive.
WorldLightmapStreamFill:
        RW_assume a16i16
        WORLD_LIGHTMAP_LOOKUP WorldLightmapRestoreMiss
WorldLightmapRestoreHit:
        tax
        lda     f:$7F0000,x             ; Entry header is the decoded byte count.
        inx
        inx
        ldy     #GSU_LIGHTMAP_CACHE_OFFSET
.if PLAYABLE_MAP_ID <> PLAYABLE_START_MAP_ID
        cmp     #16
        bcc     @Short
        sec
        jsr     WorldCopyCheckedCache
        bra     @Hit
@Short:
.endif
        dec
        phb
        mvn     #$7F, #$71
        plb
.if PLAYABLE_MAP_ID <> PLAYABLE_START_MAP_ID
@Hit:
.endif
        inc     WorldLightmapCacheHits
        rts

.if .defined(PLAYABLE_COORDINATE_COOP) && ((PLAYABLE_MAP_ID = PLAYABLE_E1M2_MAP_ID) .or (PLAYABLE_MAP_ID = PLAYABLE_E1M3_MAP_ID) .or (PLAYABLE_MAP_ID = PLAYABLE_E1M4_MAP_ID))
PLAYABLE_LIGHTMAP_COOP = 1
.endif
.if .defined(PLAYABLE_LIGHTMAP_COOP) && (PLAYABLE_MAP_ID = PLAYABLE_E1M4_MAP_ID)
PLAYABLE_LIGHTMAP_HIT_COOP = 1
; Gameplay can refill a cache hit without starting a synchronous archive read.
; Leave the stopped request for the normal join if the decoded grid is absent.
WorldLightmapTryCached:
        RW_assume a16i16
        WORLD_LIGHTMAP_LOOKUP @Miss
        jsr     WorldLightmapRestoreHit
        sec
        rts
@Miss:
        clc
        rts
.endif

WorldLightmapBadRequest:
        RW_forced a8i16
        lda     #10
        jmp     PlayableArchiveFatal

WorldLightmapRestoreMiss:
        RW_assume a16i16
        stx     WorldLightmapCacheKey
        lda     f:WorldLightmapStreamBank
        sec
        sbc     #WORLD_LIGHTMAP_REQUEST_TAG + WORLD_LIGHTMAP_FIRST_BANK
        cmp     #WORLD_LIGHTMAP_CHUNK_COUNT
        bcs     WorldLightmapBadRequest
        asl
        tay                             ; Two-byte chunk-size table index.
        lda     f:WorldLightmapStreamAddress
        bpl     WorldLightmapBadRequest
        and     #$7fff
        sta     WorldLightmapSource
        lda     f:WorldLightmapStreamWidth
        beq     WorldLightmapBadRequest
        cmp     #$0100
        bcs     WorldLightmapBadRequest
        sta     WorldLightmapWidth
        lda     f:WorldLightmapStreamHeight
        beq     WorldLightmapBadRequest
        cmp     #$0100
        bcs     WorldLightmapBadRequest
        tax
        lda     #0
        clc
@Multiply:
        adc     WorldLightmapWidth      ; Width and height at most 255, no carry.
        dex
        bne     @Multiply
        cmp     #GSU_LIGHTMAP_CACHE_BYTES + 1
        bcs     WorldLightmapBadRequest
        sta     WorldLightmapCount
        asl
        clc
        adc     WorldLightmapCount
        adc     #3
        lsr
        lsr
        ; A = ceil(6 * sample_count / 8).
        clc
        adc     WorldLightmapSource
        tyx
        cmp     f:WorldLightmapSizeTable,x
        bcc     @Bounded
        bne     WorldLightmapBadRequest
@Bounded:
        txa
        asl
        tax                             ; Four-byte paired-seek table index.
        lda     WorldLightmapSource
        asl
        clc
        adc     f:WorldLightmapSeekTable,x
        sta     playable_archive_seek
        lda     f:WorldLightmapSeekTable+2,x
        adc     #0
        sta     playable_archive_seek+2
        lda     WorldLightmapCount
        and     #$fffc
        sta     WorldLightmapGroupEnd
        RW_forced a8i16
        lda     playable_archive_busy
        beq     :+
        lda     #5
        jmp     PlayableArchiveFatal
:
        inc     playable_archive_busy
        jsr     PlayableEnsureArchive
        jsr     PlayableSeekArchive
WorldLightmapReadByte:                 ; First checked pair, for archive probes.
        ldx     #0
        cpx     WorldLightmapGroupEnd
        bne     @Group
        jmp     @Tail
@Group:
        WORLD_LIGHTMAP_DECODE_GROUP 0, @Done
        cpx     WorldLightmapGroupEnd
        beq     @Tail
        jmp     @Group
@Tail:
        cpx     WorldLightmapCount
        bne     :+
        jmp     @Done
:
        WORLD_LIGHTMAP_DECODE_GROUP 1, @Done
@Done:
        stz     playable_archive_busy
        RW_forced a16i16
        inc     WorldLightmapUploads
        jsr     WorldLightmapRemember
        rts

WorldLightmapBadPair:
        RW_assume a8i16
        lda     #3
        jmp     PlayableArchiveFatal

.if PLAYABLE_MAP_ID <> PLAYABLE_START_MAP_ID
WorldCopyCheckedCache:
        PLAYABLE_COPY_CHECKED_CACHE $7F
.endif

; Publish the index entry only after the checked grid has been copied in full.
; Every entry begins with its decoded byte count. In region mode the
; face index follows the sample bytes, leaving the hit path unchanged.
WorldLightmapRemember:
        RW_assume a16i16
        lda     WorldLightmapCacheUsed
        clc
        adc     WorldLightmapCount
.ifdef PLAYABLE_LIGHTMAP_REGIONS
        adc     #4
        ldx     WorldLightmapActiveRegion
        cmp     f:WorldLightmapRegionLimit,x
        bcc     @Append

        ; The other region stays readable until it is selected for reuse.
        lda     WorldLightmapCacheUsed
        sta     WorldLightmapRegionHead,x
        txa
        eor     #2
        tax
        stx     WorldLightmapActiveRegion
        lda     WorldLightmapRegionHead,x
        clc
        adc     #.loword(WorldLightmapCacheData)
        sta     WorldLightmapSource
        lda     f:WorldLightmapRegionBase,x
        sta     WorldLightmapCacheUsed
        clc
        adc     #.loword(WorldLightmapCacheData)
        tax
@PurgeRegion:
        cpx     WorldLightmapSource
        bcs     @RegionReady
        txa
        clc
        adc     f:$7F0000,x              ; Skip decoded byte count and samples.
        adc     #2
        tax
        txy
        lda     f:$7F0000,x              ; Doubled face index stored at the end.
        tax
        lda     #0
        sta     f:WorldLightmapCacheIndex,x
        tyx
        inx
        inx
        bra     @PurgeRegion
@RegionReady:
.else
        adc     #2
        cmp     #WORLD_LIGHTMAP_CACHE_BYTES + 1
        bcc     @Append
        lda     #0
        sta     f:WorldLightmapCacheIndex
        lda     #WORLD_LIGHTMAP_INDEX_BYTES - 2
        ldx     #.loword(WorldLightmapCacheIndex)
        ldy     #.loword(WorldLightmapCacheIndex) + 1
        phb
        mvn     #$7F, #$7F
        plb
        stz     WorldLightmapCacheUsed
.endif
        inc     WorldLightmapCacheResets
@Append:
        ldx     WorldLightmapCacheUsed
        lda     WorldLightmapCount
        sta     f:WorldLightmapCacheData,x
        txa
        clc
        adc     #.loword(WorldLightmapCacheData)
        pha
        tay
        iny
        iny
        lda     WorldLightmapCount
.if PLAYABLE_MAP_ID <> PLAYABLE_START_MAP_ID
        cmp     #16
        bcc     @CopyShort
        tyx
        ldy     #GSU_LIGHTMAP_CACHE_OFFSET
        clc
        jsr     WorldCopyCheckedCache
        lda     WorldLightmapCacheUsed
        clc
        adc     WorldLightmapCount
        adc     #2
        bra     @Copied
@CopyShort:
.endif
        ldx     #GSU_LIGHTMAP_CACHE_OFFSET
        dec
        phb
        mvn     #$71, #$7F
        plb
        tya
        sec
        sbc     #.loword(WorldLightmapCacheData)
@Copied:
.ifdef PLAYABLE_LIGHTMAP_REGIONS
        tax
        lda     WorldLightmapCacheKey
        sta     f:WorldLightmapCacheData,x
        inx
        inx
        stx     WorldLightmapCacheUsed
.else
        sta     WorldLightmapCacheUsed
.endif
        pla
        ldx     WorldLightmapCacheKey
        sta     f:WorldLightmapCacheIndex,x
        rts
.endif
