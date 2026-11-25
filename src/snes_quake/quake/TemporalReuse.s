; Bind the producer's reuse kind to the NMI consumer before releasing frame_ready.
LoadUploadReuseState:
        RW_forced a16i16
        ldx     #$0000
        lda     upload_slot
        beq     @SlotReady
        ldx     #$0002
@SlotReady:
        lda     slot_metadata_only,x
        sta     upload_metadata_only
        RW_forced a8i16
        rts

; Metadata-only work must execute the existing global completion marker once.
TryCommitMetadataUpload:
        RW_assume a8i16
        lda     upload_metadata_only
        beq     @Pixels
        lda     upload_palette_mode
        cmp     presented_palette_mode
        beq     @PaletteReady
.ifndef PLAYABLE_WEAPON_OBJ
        jsr     ApplyUploadTexturePalette
.endif
@PaletteReady:
        jsr     UploadPresented
        sec
        rts
@Pixels:
        clc
        rts

InvalidateScheduledFrameIdentity:
        RW_assume a16i16
        stz     scheduled_frame_valid
        rts

InvalidateScheduledFrameHistory:
        RW_assume a16i16
        jsr     InvalidateScheduledFrameIdentity
        rts

InitTemporalReuse:
        RW_assume a16i16
        jsr     InvalidateScheduledFrameHistory
        stz     temporal_stage_metadata_only
        stz     upload_metadata_only
        stz     slot_metadata_only+0
        stz     slot_metadata_only+2
        stz     texture_input_reuse_counter
        stz     metadata_present_counter
        rts
