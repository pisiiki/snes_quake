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
        stz     texture_renderer_code_variant
        stz     texture_phase_overlay_valid
        jsr     SyncTextureDivideQ12Mirror
.if BSP_RENDER_SCALE = 2
        BSP_STATIC_COPY GSU_RECIPROCAL, QuakeBSPReciprocal, GSU_RECIPROCAL_RAM_BYTES
        BSP_STATIC_COPY GSU_TEXTURE_COORD_MAP, QuakeBSPTextureCoordinateMap, GSU_TEXTURE_COORD_MAP_BYTES
.else
        BSP_STATIC_COPY GSU_RECIPROCAL, Fly3Reciprocal, GSU_RECIPROCAL_RAM_BYTES
        stz     warp_projection_installed
        BSP_STATIC_COPY GSU_TEXTURE_COORD_MAP, Fly3CoordinateMap, GSU_TEXTURE_COORD_MAP_BYTES
.endif
        ; Only the visible 14 KiB are pixels. The $3800..$3fff tail is code.
        lda     #0
        sta     f:GSU_OUTPUT
        BSP_STATIC_COPY GSU_OUTPUT+1, GSU_OUTPUT, GSU_TEXTURE_VISIBLE_BYTES-1
.if BSP_RENDER_SCALE = 3
        ; Rows 96+ are outside this fixed 74-row renderer. Install only after
        ; the transition clear; 2x reclaims this range as framebuffer pixels.
        BSP_STATIC_COPY __MODE7_PACK_CODE_RUN__, __MODE7_PACK_CODE_LOAD__, __MODE7_PACK_CODE_SIZE__
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
        lda     #$FFFF
        sta     f:GSU_DATA_BASE+GSU_BRUSH_PVS_LEAF_OFFSET
        lda     #BSP_RENDER_SCALE
        sta     active_render_scale
        jsr     InvalidateScheduledFrameIdentity
        rts
