; This file is copied with the frame pipeline. Each entry installs only its
; own fixed image; menu application schedules it without touching busy GSU RAM.
InstallFramePipeline:
        RW_forced a16i16
        lda     #.loword(FrameMain)
        sta     frame_pipeline_entry
        BSP_SOUND_FX3_JOB_JOIN BSP_RENDER_SCALE
        jsr     LoadFramePipelineImage
        jmp     FrameMain

LoadFramePipelineImage:
        RW_forced a8i16
        stz     FX3_SCMR
        BSP_STATIC_COPY __GSUCODE_RUN__, BSP_CPU_CODE_ADDRESS(__GSUCODE_LOAD__), __GSUCODE_SIZE__
        BSP_STATIC_COPY __GSU_AUX_CODE_RUN__, BSP_CPU_CODE_ADDRESS(__GSU_AUX_CODE_LOAD__), __GSU_AUX_CODE_SIZE__
        BSP_STATIC_COPY __GSU_BRUSH_CODE_RUN__, BSP_CPU_CODE_ADDRESS(__GSU_BRUSH_CODE_LOAD__), __GSU_BRUSH_CODE_SIZE__
        RW_forced a16i16
        jsr     EnsureFlyAliasCode
        RW_forced a16i16
.ifdef PLAYABLE_FLAT_BRUSH_CODE
        lda     texture_renderer_code_variant
        cmp     #FLAT_BRUSH_CODE_VARIANT
        bne     :+
        ; The scale image overwrote code that can still be cached at A6A7.
.if .defined(PLAYABLE_RESIDENT_WORLD) && (BSP_RENDER_SCALE = 2)
        jsr     InvalidateFlatBrushCodeCache
.else
        RW      a8
        lda     #$70
        sta     FX3_PBR
        RW      a16
.endif
:
.endif
        stz     texture_renderer_code_variant
        stz     texture_phase_overlay_valid
        jsr     SyncTextureDivideQ12Mirror
.if BSP_RENDER_SCALE = 2
        BSP_STATIC_COPY GSU_RECIPROCAL, QuakeBSPReciprocal, GSU_RECIPROCAL_RAM_BYTES
        BSP_STATIC_COPY GSU_TEXTURE_COORD_MAP, QuakeBSPTextureCoordinateMap, GSU_TEXTURE_COORD_MAP_BYTES
.else
        BSP_STATIC_COPY GSU_RECIPROCAL, Fly3Reciprocal, GSU_RECIPROCAL_RAM_BYTES
        BSP_STATIC_COPY GSU_TEXTURE_COORD_MAP, Fly3CoordinateMap, GSU_TEXTURE_COORD_MAP_BYTES
.endif
        ; Clear the tile rows that back the active viewport.
.ifdef QC_HEALTH_COUNT
        jsr     QuakeCClearVisibleOutput
.else
        lda     #0
        sta     f:GSU_OUTPUT
        BSP_STATIC_COPY GSU_OUTPUT+1, GSU_OUTPUT, BSP_VIEW_STAGE_BYTES-1
.endif
        RW_forced a16i16
        lda     #1
        sta     brush_code_valid
        stz     active_packet_guard_status
        stz     active_packet_revision
        stz     prefetched_selector_valid
        stz     overlap_selector_active
        lda     #0
        sta     f:GSU_TELEMETRY+28
.if .defined(PLAYABLE_RESIDENT_WORLD) && (BSP_RENDER_SCALE = 2)
        sta     f:GSU_DATA_BASE+GSU_RESIDENT_WORLD_STATUS
.endif
.ifdef PLAYABLE_PACKET_VIEW_REUSE
        sta     f:GSU_DATA_BASE+GSU_PACKET_VIEW_CACHE_VALID_OFFSET
        sta     f:GSU_DATA_BASE+GSU_BRUSH_MERGE_CACHE_COUNT
.endif
.ifdef PLAYABLE_PACKET_SCREEN_REUSE
        sta     f:GSU_DATA_BASE+GSU_PACKET_SCREEN_READY
.endif
        lda     #$FFFF
        sta     f:GSU_DATA_BASE+GSU_BRUSH_PVS_LEAF_OFFSET
        lda     #BSP_RENDER_SCALE
        sta     active_render_scale
        jsr     InvalidateScheduledFrameIdentity
        rts
