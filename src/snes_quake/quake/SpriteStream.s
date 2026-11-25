; Mandatory playable QBA pixel refill. Source baselines and demos omit this.
.ifdef PLAYABLE_COORDINATE_COOP
  .ifdef PLAYABLE_SPRITE_STREAM
    .if PLAYABLE_MAP_ID = PLAYABLE_E1M1_MAP_ID
PLAYABLE_SPRITE_STREAM_COOP = 1
    .endif
  .endif
.pushseg
  .ifdef PLAYABLE_LARGE_DISTANCE_CACHE
PLAYABLE_COORDINATE_YIELD_DP = 1
.zeropage
  .else
.segment "LORAM"
  .endif
SpriteStreamCoordinateYield: .res 2
.segment "CODE"
; Called at a stopped FX3 job during cooperative gameplay with DB=$7F.
; Service a pending renderer refill and resume at its saved PC.
SpriteStreamYieldCoordinate:
  .ifdef PLAYABLE_WORLD_COORDINATE_STREAM
        RW_assume a16i16
        php
        phx
        phy
        phb
        phk
        plb
    .ifdef PLAYABLE_LIGHTMAP_COOP
        lda     f:WorldLightmapStreamBank
        and     #$FFC0
        cmp     #WORLD_LIGHTMAP_REQUEST_TAG
        bne     @TryCoordinate
      .ifdef PLAYABLE_LIGHTMAP_HIT_COOP
        jsr     WorldLightmapTryCached
        bcc     @Disable
      .else
        ; Both hits and checked archive refills resume the same renderer job.
        jsr     WorldLightmapStreamFill
      .endif
        lda     #.loword(WorldLightmapStreamResume)
        bra     @Resume
@TryCoordinate:
    .endif
        jsr     SpriteStreamCoordinateResume
    .ifdef PLAYABLE_SPRITE_STREAM_COOP
        bcs     @Resume
      .ifdef PLAYABLE_SWITCHED_LIGHTS
        ; The renderer owns a frozen mask while gameplay services its inputs.
        lda     f:SwitchedGridRequest
        cmp     #$4000
        bne     :+
        jsr     SwitchedGridFillForScale
        bra     @Resume
:
      .endif
        ; Contour and alias requests share the mailbox. A contour wins first.
        jsr     SpriteStreamResumeRequest
    .endif
        bcc     @Disable
@Resume:
        tax
        stx     FX3_R15
        bra     @Done
@Disable:
    .ifdef PLAYABLE_COORDINATE_YIELD_DP
        stz     z:SpriteStreamCoordinateYield
    .else
        stz     SpriteStreamCoordinateYield
    .endif
@Done:
        plb
        ply
        plx
        plp
  .else
        ; The sizing link has the same simulation call sites and no archive.
    .ifdef PLAYABLE_COORDINATE_YIELD_DP
        stz     z:SpriteStreamCoordinateYield
    .else
        lda     #0
        sta     f:SpriteStreamCoordinateYield
    .endif
  .endif
        rtl
.popseg
.endif

.ifdef PLAYABLE_SPRITE_STREAM
.ifndef SPRITE_STREAM_BANK_COUNT
.include "Data/QuakeBSPPlayableSpriteStream.i"
.endif
.import SpriteStreamRequestBank:far, SpriteStreamRequestAddress:far
.import SpriteStreamRequestBytes:far, SpriteStreamRequestReady:far
.import SpriteStreamCacheBank:far, SpriteStreamCacheAddress:far, SpriteStreamCacheBytes:far
.import SpriteStreamRequestResume:far
.import AliasSpriteStreamResume:far, F3_AliasSpriteStreamResume:far
.assert SPRITE_STREAM_CACHE_OFFSET = $C000, error, "Alias cache must overlay the completed opaque colormap phase"
.assert SPRITE_STREAM_CACHE_BYTES = $0600, error, "Alias cache capacity changed"
.assert SPRITE_STREAM_BANK_RECORD_BYTES = 4, error, "Sprite stream table must contain paired MSU seek dwords"
.assert .bankbyte(AliasSpriteStreamResume) = $70, lderror, "Alias resume must execute in retained RAM bank70"
.assert .bankbyte(F3_AliasSpriteStreamResume) = $70, lderror, "F3 alias resume must execute in retained RAM bank70"

.segment "LORAM"
SpriteStreamColormapDirty: .res 2
SpriteStreamCopyBytes: .res 2
SpriteStreamCopyValue: .res 1
SpriteStreamUploads: .res 2
.if PLAYABLE_MAP_ID = PLAYABLE_E1M1_MAP_ID
PLAYABLE_SPRITE_WRAM_CACHE = 1
PLAYABLE_E1M1_WIDE_Q3 = 1
SPRITE_WRAM_SLOTS = 27
SPRITE_WRAM_SLOT_BYTES = $0300
SpriteStreamWramNext: .res 2
SpriteStreamWramHits: .res 2
; Retain the linked low WRAM layout while reclaiming one raster slot in $7E.
SpriteStreamWramTags: .res 28 * 8
.assert * <= $002000, lderror, "Sprite cache tags must fit in low WRAM"
.segment "PLAYABLE_STREAM_CACHE"
SpriteStreamWramData: .res SPRITE_WRAM_SLOTS * SPRITE_WRAM_SLOT_BYTES
.assert .bankbyte(SpriteStreamWramData) = $7E && .bankbyte(*-1) = $7E, lderror, "Sprite cache data must fit in bank $7E"
.endif

.segment "RODATA"
SpriteStreamBankTable:
        .incbin "Data/QuakeBSPPlayableSpriteStream.bin"
.assert *-SpriteStreamBankTable = SPRITE_STREAM_BANK_COUNT*SPRITE_STREAM_BANK_RECORD_BYTES, error, "Sprite stream table length changed"
.endif ; PLAYABLE_SPRITE_STREAM

.if .defined(PLAYABLE_SPRITE_STREAM) .or .defined(PLAYABLE_WORLD_COORDINATE_STREAM)
.segment "CODE"
.ifdef PLAYABLE_RESIDENT_WORLD_SNAPSHOT
.include "quake/BrushResidentWorldSnapshot.s"
.endif
; Call after all selector/coarse jobs, immediately before each actual draw.
; The selector may reuse these phase words; no prior-job cache tag survives.
; Preserve X because it holds the renderer entry at both launch sites.
SpriteStreamPrepareRenderer:
        php
        RW_forced a16i16
        pha
        lda     #0
.ifdef PLAYABLE_SPRITE_STREAM
        sta     f:SpriteStreamRequestBank
        sta     f:SpriteStreamRequestReady
        sta     f:SpriteStreamCacheBytes
        lda     #$FFFF
        sta     f:SpriteStreamCacheBank
.else
        sta     f:WorldCoordinateStreamRequest
.endif
        pla
        plp
        rts
.endif

.if .defined(PLAYABLE_SPRITE_STREAM) .or .defined(PLAYABLE_WORLD_LIGHTMAP_STREAM) .or .defined(PLAYABLE_WORLD_COORDINATE_STREAM)
; The ordinary join may return for an internal sprite refill STOP. Do not
; clear SCMR, pack a frame, increment render counters or publish any slot until
; the shader finally stops with RequestBank=0. CPU writes no live GSU register
; except R15, preserving the halted register file/PBR/CBR/RAMBR and PLOT state.
SpriteStreamJoinRenderer:
        php
        RW_forced a16i16
        pha
        phy
        phb
        phk
        plb
.ifdef PLAYABLE_MAP_ID
        lda     video_active
        bne     @Wait
        ; The PPU is forced blank during startup. Fill its independent HUD
        ; pages while FX3 renders the first world frame.
        RW      a8
        jsr     StatusHudLoad
        RW      a16
.endif
@Wait:
        jsr     QuakeCJoinRenderer
        RW_forced a16i16
.ifdef PLAYABLE_WORLD_COORDINATE_STREAM
@CheckRequests:
.endif
.ifdef PLAYABLE_SWITCHED_LIGHTS
        lda     f:SwitchedGridRequest
        cmp     #$4000
        bne     :+
        jsr     SwitchedGridFillForScale
        tax
        ; A running grid job can yield again at a gameplay boundary.
        ; Recheck queued input instead of polling with the archive seek's Y.
@ResumeSwitchedGrid:
        stx     FX3_R15
        bra     @Wait
:
.endif
.ifdef PLAYABLE_WORLD_LIGHTMAP_STREAM
  .ifdef PLAYABLE_RESIDENT_WORLD_SNAPSHOT
        jsl     ServiceBrushResidentWorldSnapshot
        bcs     @JoinAgain
  .else
        lda     f:WorldLightmapStreamBank
  .endif
        and     #$FFC0
        cmp     #WORLD_LIGHTMAP_REQUEST_TAG
        bne     @TrySprite
        jsr     WorldLightmapStreamFill
        ldx     #.loword(WorldLightmapStreamResume)
  .ifdef PLAYABLE_COORDINATE_YIELD_DP
        ldy     #3840
  .endif
        bra     @StartJob
@TrySprite:
.endif
.ifdef PLAYABLE_WORLD_COORDINATE_STREAM
  .ifdef PLAYABLE_COORDINATE_COOP
        jsr     SpriteStreamCoordinateResume
        bcc     @Sprite
    .ifdef PLAYABLE_COORDINATE_YIELD_DP
        tax
@ContourWaitBudget:
        ldy     #12288
        bra     @StartJob
    .else
        bra     @Resume
    .endif
  .else
        lda     f:WorldCoordinateStreamRequest
        cmp     #WORLD_COORDINATE_REQUEST_TAG
        bne     @Sprite
        jsr     WorldCoordinateStreamFill
        ldx     #.loword(WorldCoordinateStreamResume)
        bra     @StartJob
  .endif
@Sprite:
.endif
.ifdef PLAYABLE_SPRITE_STREAM
        jsr     SpriteStreamResumeRequest
        bcc     @Done
        bra     @Resume
.else
        bra     @Done
.endif
@Resume:
        tax
.ifdef PLAYABLE_COORDINATE_YIELD_DP
@SpriteWaitBudget:
        ldy     #12288
.endif
@StartJob:
        stx     FX3_R15
.ifdef PLAYABLE_WORLD_COORDINATE_STREAM
        lda     active_render_scale
        cmp     #2
        bne     @JoinAgain
        ; Give short contour runs a chance to reach their next refill
        ; before entering a full gameplay step. Longer raster runs still
        ; overlap the usual queued simulation.
  .ifdef PLAYABLE_COORDINATE_COOP
        ; Gameplay can now finish the refill, so give it the CPU sooner.
    .if PLAYABLE_MAP_ID = PLAYABLE_E1M1_MAP_ID
      .ifndef PLAYABLE_COORDINATE_YIELD_DP
        ldy     #3840
      .endif
    .else
        ldy     #320
    .endif
  .else
        ldy     #640
  .endif
  .ifdef PLAYABLE_E1M1_DUE_REFILL_WAIT
        ; Let a resumed job chain short refills, then give an already-due
        ; gameplay step the existing cooperative renderer join.
        lda     render_camera+10
        and     #$00FF
        cmp     #BSP_TECHNIQUE_TEXTURED_LIGHTMAP
        bne     @TryFlatDue
@CheckDue:
        lda     f:QC_INPUT_TICK
        cmp     f:quakec_last_tick
        beq     @PollRefill
        ldy     #PLAYABLE_E1M1_DUE_REFILL_WAIT
  .endif
@PollRefill:
        ldx     FX3_R15
        bne     :+
        jmp     @CheckRequests
:
        dey
        bne     @PollRefill
@JoinAgain:
        jmp     @Wait
  .ifdef PLAYABLE_E1M1_DUE_REFILL_WAIT
@TryFlatDue:
        cmp     #RUNTIME_MENU_TECHNIQUE_FACE_COLORS
        beq     @CheckDue
        bra     @PollRefill
  .endif
.else
        bra     @Wait
.endif
@Done:
        plb
        ply
        pla
        plp
        rts

.ifdef PLAYABLE_SWITCHED_LIGHTS
; Both the ordinary join and an in-service yield resume the active image.
SwitchedGridFillForScale:
        jsr     SwitchedGridFill
        ldx     active_render_scale
        cpx     #3
        bne     :+
        .assert F3_SwitchedGridResident-SwitchedGridResident = F3_SwitchedGridResume-SwitchedGridResume, lderror, "Switched-grid continuations need equal scale offsets"
        clc
        adc     #.loword(F3_SwitchedGridResume-SwitchedGridResume)
:       rts
.endif

.if .defined(PLAYABLE_WORLD_COORDINATE_STREAM) .and .defined(PLAYABLE_COORDINATE_COOP)
; Return the original resume address in A and C set after a checked fill.
SpriteStreamCoordinateResume:
        lda     f:WorldCoordinateStreamRequest
        cmp     #WORLD_COORDINATE_REQUEST_TAG
        bne     @NoRequest
        jsr     WorldCoordinateStreamFill
        lda     #.loword(WorldCoordinateStreamResume)
        sec
        rts
@NoRequest:
        clc
        rts
.endif
.endif

.ifdef PLAYABLE_SPRITE_STREAM
; Return the checked stopped alias continuation in A with carry set.
SpriteStreamResumeRequest:
        lda     render_coverage_mode
        bne     @NoRequest             ; Diagnostic jobs never sample QBA pixels.
        lda     f:SpriteStreamRequestBank
        beq     @NoRequest
        jsr     SpriteStreamFillRequest
        lda     f:SpriteStreamRequestResume
        cmp     #.loword(AliasSpriteStreamResume)
        beq     @Resume
        cmp     #.loword(F3_AliasSpriteStreamResume)
        beq     @Resume
        jmp     SpriteStreamInvalidRequest
@Resume:
        sec
        rts
@NoRequest:
        clc
        rts

; A committed request names a raw offset in one virtual 32KiB QBA pixel bank.
; All descriptors remain immutable; only the selected exact sprite is loaded.
; No CPU facing/animation calculation and no conventional ROM fallback exist.
.if PLAYABLE_MAP_ID = PLAYABLE_E1M1_MAP_ID
.macro SPRITE_STREAM_COPY_CHECKED_BYTE bad_pair, absolute_store
        lda     z:$01                   ; Direct page is temporarily at $2000.
  .if absolute_store
        sta     a:SPRITE_STREAM_CACHE_OFFSET,x
  .else
        sta     f:GSU_DATA_BASE+SPRITE_STREAM_CACHE_OFFSET,x
  .endif
        ; With carry set, only a complementary byte gives zero and carry set.
        adc     z:$01
        bne     bad_pair
        inx
.endmacro
.endif
SpriteStreamFillRequest:
        RW_forced a16i16
        phb
        phk
        plb
        lda     f:SpriteStreamRequestReady
        beq     :+
        jmp     SpriteStreamInvalidRequest
:
        lda     f:SpriteStreamRequestBank
        sec
        sbc     #$0080
        bne     :+
        jmp     SpriteStreamInvalidRequest
:
        cmp     #SPRITE_STREAM_BANK_COUNT
        bcc     :+
        jmp     SpriteStreamInvalidRequest
:
        asl
        asl
        tax
        lda     f:SpriteStreamRequestBytes
        bne     :+
        jmp     SpriteStreamInvalidRequest
:
        cmp     #SPRITE_STREAM_CACHE_BYTES+1
        bcc     :+
        jmp     SpriteStreamInvalidRequest
:
        sta     SpriteStreamCopyBytes
        lda     f:SpriteStreamRequestAddress
        bpl     :+
        jmp     SpriteStreamInvalidRequest
:
        clc
        adc     SpriteStreamCopyBytes
        cmp     #$8001
        bcc     :+
        jmp     SpriteStreamInvalidRequest
:
        lda     f:SpriteStreamRequestAddress
        asl                             ; The archive stores byte/complement pairs.
        clc
        adc     f:SpriteStreamBankTable,x
        sta     playable_archive_seek
        lda     f:SpriteStreamBankTable+2,x
        adc     #0
        sta     playable_archive_seek+2
.ifdef PLAYABLE_SPRITE_WRAM_CACHE
        jsr     SpriteStreamRestoreWram
        bcc     :+
        jmp     @Upload
:
.endif
        RW_forced a8i16
        lda     playable_archive_busy
        beq     :+
        lda     #5
        jmp     PlayableArchiveFatal
:
        inc     playable_archive_busy
        jsr     PlayableEnsureArchive
        jsr     PlayableSeekArchive
        ldx     #0
.if PLAYABLE_MAP_ID = PLAYABLE_E1M1_MAP_ID
        phy
        phd
        pea     $2000
        pld
        cld
        RW_forced a16i16
        lda     a:SpriteStreamCopyBytes
        lsr
        lsr
        lsr
        tay
        RW_forced a8i16
        beq     @Tail
        ; The grouped copy only accesses MSU-1 through DP and FX3 RAM
        ; through DBR. Restore DBR before reading the tail's WRAM limit.
        phb
        lda     #^GSU_DATA_BASE
        pha
        plb
        sec
@EightBytes:
        .repeat 8
        SPRITE_STREAM_COPY_CHECKED_BYTE @BadBulkPair, 1
        .endrepeat
        dey
        bne     @EightBytes
        plb
@Tail:
        cpx     a:SpriteStreamCopyBytes
        beq     @CopyDone
@TailByte:
        sec
        SPRITE_STREAM_COPY_CHECKED_BYTE @BadPair, 0
        cpx     a:SpriteStreamCopyBytes
        bne     @TailByte
        bra     @CopyDone
@BadBulkPair:
        plb
@BadPair:
        ; Keep the partially copied slot unavailable on a corrupt pair.
        pld
        lda     #3
        jmp     PlayableArchiveFatal
@CopyDone:
        pld
        ply
.else
        RW_forced a8i16
@Byte:
        lda     f:$002001
        ; GSU is halted and Ready remains zero until every pair validates.
        ; A corrupt pair aborts before the partial slot can be consumed.
        sta     f:$710000+SPRITE_STREAM_CACHE_OFFSET,x
        eor     f:$002001
        cmp     #$FF
        beq     :+
        lda     #3
        jmp     PlayableArchiveFatal
:
        inx
        cpx     SpriteStreamCopyBytes
        bne     @Byte
.endif
        stz     playable_archive_busy
        RW_forced a16i16
.ifdef PLAYABLE_SPRITE_WRAM_CACHE
        jsr     SpriteStreamRememberWram
@Upload:
.endif
        lda     #1
        sta     SpriteStreamColormapDirty
        lda     SpriteStreamUploads
        inc
        sta     SpriteStreamUploads
        lda     f:SpriteStreamRequestBytes
        sta     f:SpriteStreamCacheBytes
        lda     f:SpriteStreamRequestAddress
        sta     f:SpriteStreamCacheAddress
        lda     f:SpriteStreamRequestBank
        sta     f:SpriteStreamCacheBank
        lda     #1
        sta     f:SpriteStreamRequestReady ; Reply commit after every pixel/key.
SpriteStreamFillComplete:
        plb
        rts

.ifdef PLAYABLE_SPRITE_WRAM_CACHE
; The seek and size identify immutable checked bytes in the bound archive.
; All lengths start at zero and each FIFO slot commits its size last.
SpriteStreamRestoreWram:
        RW_assume a16i16
        lda     SpriteStreamCopyBytes
        cmp     #SPRITE_WRAM_SLOT_BYTES+1
        bcs     @Miss
        ldx     #0
@Find:
        lda     f:SpriteStreamWramTags,x
        cmp     SpriteStreamCopyBytes
        bne     @Next
        lda     f:SpriteStreamWramTags+2,x
        cmp     playable_archive_seek
        bne     @Next
        lda     f:SpriteStreamWramTags+4,x
        cmp     playable_archive_seek+2
        beq     @Hit
@Next:
        txa
        clc
        adc     #8
        tax
        cpx     #SPRITE_WRAM_SLOTS*8
        bcc     @Find
@Miss:
        clc
        rts
@Hit:
        jsr     SpriteStreamWramAddress
        lda     SpriteStreamCopyBytes
        ldy     #SPRITE_STREAM_CACHE_OFFSET
        sec
        jsr     PlayableCopyCheckedCache7e
        inc     SpriteStreamWramHits
        sec
        rts

SpriteStreamRememberWram:
        ; Oversize requests still use the full checked FX3 upload slot.
        lda     SpriteStreamCopyBytes
        cmp     #SPRITE_WRAM_SLOT_BYTES+1
        bcs     @Done
        ldx     SpriteStreamWramNext
        jsr     SpriteStreamWramAddress
        lda     SpriteStreamCopyBytes
        ldy     #SPRITE_STREAM_CACHE_OFFSET
        clc
        jsr     PlayableCopyCheckedCache7e
        ldx     SpriteStreamWramNext
        lda     playable_archive_seek
        sta     f:SpriteStreamWramTags+2,x
        lda     playable_archive_seek+2
        sta     f:SpriteStreamWramTags+4,x
        lda     SpriteStreamCopyBytes
        sta     f:SpriteStreamWramTags,x
        txa
        clc
        adc     #8
        cmp     #SPRITE_WRAM_SLOTS*8
        bcc     :+
        lda     #0
:
        sta     SpriteStreamWramNext
@Done:
        rts

SpriteStreamWramAddress:
        ; X is the eight-byte tag offset. Multiply it by 96 to obtain
        ; the matching 768-byte raster offset without a ROM table.
        .assert SPRITE_WRAM_SLOT_BYTES = 8 * 3 * 32, error, "Sprite raster stride changed"
        .assert SPRITE_WRAM_SLOTS * SPRITE_WRAM_SLOT_BYTES <= $8000, error, "Sprite raster offset carries"
        phx
        txa
        asl
        adc     1,s
        .repeat 5
        asl
        .endrepeat
        adc     #.loword(SpriteStreamWramData)
        tax
        pla
        rts
.endif

SpriteStreamInvalidRequest:
        RW_forced a8i16
        lda     #8                      ; Bad virtual key/bounds/resume/reply.
        jmp     PlayableArchiveFatal
.endif
