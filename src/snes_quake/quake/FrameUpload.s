; Drain one chunk each VBlank; present only after the complete page is resident.
UploadFrameChunk:
        RW_forced a16i16
        lda     upload_offset
.ifdef PLAYABLE_WEAPON_OBJ
        ; Retry a completed page without issuing another world or OBJ DMA.
        cmp     #BSP_PLAYABLE_X2_STAGE_BYTES
        beq     @AlreadyStaged
        ldx     upload_chunk
        cpx     #BSP_TEXTURE_UPLOAD_CHUNKS
        bne     :+
@AlreadyStaged:
        jmp     UploadFrameComplete
:
.endif
        lsr
        tay
        lda     upload_format
        bne     @TextureDestination
        lda     upload_target
        beq     @DestinationA
        tya
        clc
        adc     #VRAM_TILES_B >> 1
        tay
        bra     UploadChunkDestinationReady
@DestinationA:
        tya
        clc
        adc     #VRAM_TILES_A >> 1
        tay
        bra     UploadChunkDestinationReady
@TextureDestination:
        lda     upload_target
        beq     @TextureDestinationA
        tya
        clc
        adc     #VRAM_TEXTURE_TILES_B >> 1
        tay
        bra     UploadChunkDestinationReady
@TextureDestinationA:
        tya
        clc
        adc     #VRAM_TEXTURE_TILES_A >> 1
        tay
UploadChunkDestinationReady:
        lda     upload_offset
        ldx     upload_slot
        beq     @SourceSlot0
        clc
        adc     #.loword(StagedFrame1)
        tax
        bra     @SourceReady
@SourceSlot0:
        clc
        adc     #.loword(StagedFrame0)
        tax
@SourceReady:
        stx     A1T7L
.ifdef PLAYABLE_MAP_ID
.ifdef PLAYABLE_WEAPON_OBJ
        lda     weapon_obj_short_upload
        beq     @RegularChunk
        ; Larger transfers cannot be the last one. Leave room on that
        ; VBlank for palette, OAM, page publication and the HUD.
        lda     #BSP_PLAYABLE_X2_STAGE_BYTES
        sec
        sbc     upload_offset
        cmp     #(BSP_PLAYABLE_X2_STAGE_BYTES / BSP_TEXTURE_UPLOAD_CHUNKS)+1
        bcc     @LastObjChunk
  .ifdef QC_HUB_WARNING_COUNT
        ; A large transfer can leave too little VBlank for BG2 and OBJ
        ; HDMA setup on the next scanout. Keep the current upload offset
        ; and finish this page with the regular chunk budget.
        pha
        RW      a8
        lda     start_warning_oam
        RW      a16
        beq     :+
        pla
        bra     @SmallObjChunk
:
        pla
  .endif
        cmp     #3841
        bcc     @GuardLastObjChunk
        cmp     #4737
        bcc     @SmallObjChunk
        ldx     #4736
        lda     #233                    ; No palette or OAM on an intermediate chunk.
        bra     @GuardObjChunk
@GuardLastObjChunk:
        tax
        lda     #232                    ; Reserve the additional final-VBlank work.
@GuardObjChunk:
        RW      a8
        pha
        lda     STAT78
        lda     SLHV
        lda     OPVCT
        pha
        lda     OPVCT
        and     #1
        bne     @ObjChunkHighLine
        pla
        cmp     1,s
        bcc     @ObjChunkInTime
        bra     @SlowObjChunk
@ObjChunkHighLine:
        pla
@SlowObjChunk:
        pla
        RW      a16
@SmallObjChunk:
        ldx     #BSP_PLAYABLE_X2_STAGE_BYTES / BSP_TEXTURE_UPLOAD_CHUNKS
        bra     @ChunkBytesReady
@ObjChunkInTime:
        pla
        RW_forced a16i16
        bra     @ChunkBytesReady
@LastObjChunk:
        tax
        bra     @ChunkBytesReady
@RegularChunk:
.endif
        lda     upload_format
        ldx     #BSP_PLAYABLE_X2_STAGE_BYTES / BSP_TEXTURE_UPLOAD_CHUNKS
        cmp     #BSP_UPLOAD_FORMAT_TEXTURE_X3
        bne     @ChunkBytesReady
        ldx     #BSP_PLAYABLE_X3_STAGE_BYTES / BSP_TEXTURE_UPLOAD_CHUNKS
.else
        ldx     #BSP_UPLOAD_CHUNK_BYTES
        lda     upload_format
        beq     @ChunkBytesReady
        ldx     #BSP_TEXTURE_UPLOAD_CHUNK_BYTES
        lda     upload_chunk
        cmp     #BSP_TEXTURE_UPLOAD_CHUNKS-1
        bne     @ChunkBytesReady
        ldx     #BSP_TEXTURE_UPLOAD_LAST_CHUNK_BYTES
        bra     @ChunkBytesReady
.endif
@ChunkBytesReady:
.ifdef QC_E1M2_DEFER_UPLOAD
        ; A page can defer one intermediate X2 Flat chunk for each of
        ; an active gameplay step and a due input latch. Keep the old
        ; page visible and leave the upload cursor intact.
        lda     upload_defer_budget
        beq     @Transfer
        lda     upload_format
        cmp     #BSP_UPLOAD_FORMAT_TEXTURE
        bne     @Transfer
        txa
        clc
        adc     upload_offset
        cmp     #BSP_PLAYABLE_X2_STAGE_BYTES
        bcs     @Transfer
        lda     upload_defer_budget
        bit     #E1M2_DEFER_ACTIVE
        beq     @CheckLatch
        lda     f:QCE1M2SimulationActive
        bne     @DeferActive
@CheckLatch:
        lda     upload_defer_budget
        bit     #E1M2_DEFER_LATCH
        beq     @Transfer
        lda     qc_input_divider
        cmp     #QC_INPUT_VBLANKS - 1
        bcc     @Transfer
        lda     qc_input_replay
        bne     @ReplayLatch
        lda     qc_input_tick
        cmp     f:quakec_last_tick
        bne     @Transfer
        bra     @DeferLatch
@ReplayLatch:
        lda     qc_input_tail
        clc
        adc     #QC_INPUT_RECORD_SIZE
        and     #QC_INPUT_QUEUE_MASK
        cmp     qc_input_head
        beq     @Transfer
@DeferLatch:
        lda     #E1M2_DEFER_LATCH
        bra     @Defer
@DeferActive:
        lda     #E1M2_DEFER_ACTIVE
@Defer:
        trb     upload_defer_budget
        jmp     UploadFrameReturn
@Transfer:
.endif
        RW      a8
        stz     MDMAEN
        sty     VMADDL
        lda     #$80                    ; Word writes; advance after $2119.
        sta     VMAINC
        lda     #^StagedFrame0
        sta     A1B7
        stx     DAS7L
        lda     #$01                    ; Alternate $2118/$2119 for tile bytes.
        sta     DMAP7
        lda     #$18
        sta     BBAD7
        lda     #%10000000
        sta     MDMAEN
        RW      a16
        inc     vram_chunk_counter
        txa
        clc
        adc     upload_offset
        sta     upload_offset
.ifdef PLAYABLE_WEAPON_OBJ
        lda     weapon_obj_short_upload
        bne     :+
        RW      a8
        jsr     WeaponObjUploadChunk
        RW      a16
:
        RW_forced a16i16
.endif
        inc     upload_chunk
.ifdef PLAYABLE_MAP_ID
        lda     #BSP_TEXTURE_UPLOAD_CHUNKS
.ifdef PLAYABLE_WEAPON_OBJ
        ldx     weapon_obj_short_upload
        beq     :+
        lda     upload_offset
        cmp     #BSP_PLAYABLE_X2_STAGE_BYTES
        beq     UploadFrameComplete
        jmp     UploadFrameReturn
:
.endif
.else
        lda     upload_format
        beq     @FlatUploadChunks
        lda     #BSP_TEXTURE_UPLOAD_CHUNKS
        bra     @UploadChunksReady
@FlatUploadChunks:
        lda     #BSP_UPLOAD_CHUNKS
@UploadChunksReady:
.endif
        cmp     upload_chunk
        beq     UploadFrameComplete
        jmp     UploadFrameReturn
UploadFrameComplete:
        RW      a8
.ifdef PLAYABLE_WEAPON_OBJ
        lda     upload_format
        beq     @SelectFormat
        jsr     WeaponObjPageCanPublish
        bcc     @SelectFormat
        ; Keep the old world page and its HUD split together until the
        ; resident page, weapon and palette can all be published in VBlank.
        jmp     UploadFrameReturn
@SelectFormat:
.endif
        lda     upload_format
        beq     @PresentFlat
        jmp     UploadPresentTexture
@PresentFlat:
        jmp     UploadPresentFlat
UploadPresentTexture:
        lda     presented_format
        cmp     upload_format
        bne     UploadLoadTexturePalette
        lda     upload_palette_mode
        cmp     presented_palette_mode
        bne     :+
        jmp     UploadTexturePaletteReady
:
UploadLoadTexturePalette:
 .ifndef PLAYABLE_WEAPON_OBJ
        jsr     ApplyUploadTexturePalette
 .endif
UploadTexturePaletteReady:
.if BSP_QUAKEC_GAMEPLAY
        ; The mirrored mosaic reads the odd source pixel of each pair.
        lda     #1
        sta     BG1HOFS
.else
        stz     BG1HOFS
.endif
        stz     BG1HOFS
        lda     #bgmode(BG_MODE_3, BG3_PRIO_NORMAL, BG_SIZE_8X8, BG_SIZE_8X8, BG_SIZE_8X8, BG_SIZE_8X8)
        sta     BGMODE                 ; Mode 3 gives BG1 all eight bitplanes.
        RW      a16
        lda     upload_slot
        asl
        tax
        RW      a8
        jmp     (slot_present_direct,x)
UploadPresentDirect:
        RW_forced a16i16
        RW_forced a8i16
        stz     TMW
        lda     #2
        sta     presented_render_scale
        lda     #$11                    ; Mosaic size 2, BG1 enabled.
        sta     MOSAIC
        lda     #bgsc(VRAM_TEXTURE_TILEMAP, SC_SIZE_32X32)
        sta     BG1SC
        ; Align mosaic pairs to source rows (0,1), (2,3), ... . With the
        ; mirrored tile quads this makes the GSU row swizzle present in
        ; ascending logical order instead of reversing every eight-row tile.
        lda     #$FF
        sta     BG1VOFS
        sta     BG1VOFS
        lda     upload_target
        beq     UploadPresentDirectA
        lda     #bg12nba(VRAM_TEXTURE_TILES_B, 0)
        sta     BG12NBA
        bra     UploadPresented
UploadPresentDirectA:
        lda     #bg12nba(VRAM_TEXTURE_TILES_A, 0)
        sta     BG12NBA
        bra     UploadPresented
UploadPresentFlat:
        lda     presented_format
        beq     UploadFlatPaletteReady
        CGRAM_memcpy 0, BSP_CPU_CODE_ADDRESS(QuakeBSPPalette), 32
UploadFlatPaletteReady:
        stz     TMW
        stz     BG1HOFS
        stz     BG1HOFS
        lda     #bgmode(BG_MODE_1, BG3_PRIO_NORMAL, BG_SIZE_8X8, BG_SIZE_8X8, BG_SIZE_8X8, BG_SIZE_8X8)
        sta     BGMODE
        stz     MOSAIC
        lda     #bgsc(VRAM_TILEMAP, SC_SIZE_32X32)
        sta     BG1SC
        lda     #$FF
        sta     BG1VOFS
        sta     BG1VOFS
        lda     upload_target
        beq     UploadPresentFlatA
        lda     #bg12nba(VRAM_TILES_B, 0)
        sta     BG12NBA
        bra     UploadPresented
UploadPresentFlatA:
        lda     #bg12nba(VRAM_TILES_A, 0)
        sta     BG12NBA
UploadPresented:
        lda     upload_metadata_only
        bne     UploadPresentedMetadata
        lda     upload_format
        sta     presented_format
        lda     upload_target
        eor     #$01
        sta     upload_target
        lda     #inidisp(ON, DISP_BRIGHTNESS_MAX)
        sta     SFX_inidisp

        RW      a16
        inc     page_flip_counter
        bra     UploadPresentedState
UploadPresentedMetadata:
        stz     upload_metadata_only
        ; This entry is called from the A8 NMI dispatcher. Force the physical
        ; REP here: assembler state also reaches this merge from the A16 pixel
        ; path and a state-only RW would elide it, truncating slot-1 metadata.
        RW_forced a16i16
        inc     metadata_present_counter
UploadPresentedState:
        jsr     PublishUploadSlotState
.ifdef PLAYABLE_WEAPON_OBJ
        jsr     WeaponObjPresent
.endif
        inc     present_counter
        ; Idle is the final commit word: when it becomes observable, the
        ; visible page, slot identity, metadata, and counters already agree.
        stz     upload_active
UploadFrameReturn:
        RW_forced a8i16
        rts

PublishUploadSlotState:
        RW_assume a16i16
        lda     upload_palette_mode
        sta     presented_palette_mode
        ldx     #0
        lda     upload_slot
        beq     @PresentedCameraReady
        ldx     #CAMERA_COMMAND_BYTES
@PresentedCameraReady:
        lda     slot_camera+0,x
        sta     presented_camera+0
        lda     slot_camera+2,x
        sta     presented_camera+2
        lda     slot_camera+4,x
        sta     presented_camera+4
        lda     slot_camera+6,x
        sta     presented_camera+6
        lda     slot_camera+8,x
        sta     presented_camera+8
        lda     slot_camera+10,x
        sta     presented_camera+10
        lda     slot_camera+12,x
        sta     presented_camera+12
        lda     slot_camera+14,x
        sta     presented_camera+14

        lda     upload_slot
        asl
        tax
        lda     slot_brush_visual_state,x
        sta     presented_brush_visual_state
.if BSP_QUAKEC_GAMEPLAY
  .ifdef QC_EXIT_MOVER_COUNT
        lda     slot_exit_pose_word,x
        sta     presented_exit_pose_word
    .if QC_EXIT_MOVER_COUNT > 8
        lda     slot_exit_pose_word_high,x
        sta     presented_exit_pose_word_high
    .endif
  .endif
  .if QC_ENTRANCE_COUNT > 0
        txa
        asl
        tax
        lda     slot_entrance_variants,x
        sta     presented_entrance_variants
        lda     slot_entrance_variants+2,x
        sta     presented_entrance_variants+2
        txa
        lsr
        tax
  .endif
.endif

@PresentedCoverageReady:
        lda     slot_coverage_mode,x
        sta     presented_coverage_mode

.ifdef PLAYABLE_WEAPON_OBJ
        lda     weapon_obj_slot_mask,x
        sta     weapon_obj_presented_mask
.endif
        lda     slot_weapon_frame,x
        sta     presented_weapon_frame
        lda     slot_demo_pose,x
        sta     presented_demo_pose
        cmp     #$FFFF
        beq     @WeaponIdleReady
        lda     presented_render_scale
        cmp     #2
        bne     @WeaponIdleReady
        lda     slot_weapon_frame,x
        and     #$00FF
        beq     @WeaponIdleReady
        phx
        tax
        lda     f:QuakeBSPWeaponIdleFrames,x
        and     #$00FF
        sta     weapon_idle_frame
        plx
@WeaponIdleReady:
        lda     slot_demo_due_tick,x
        sta     presented_demo_due_tick
        lda     slot_demo_epoch,x
        sta     presented_demo_epoch
        jsr     PresentSkyStateFromSlot       ; X: word offset -> Q16 offset.
        jsr     PresentTurbulenceStateFromSlot ; Reuse that immutable slot offset.
        rts
