; Transition-only lookup selection for the retained lightmapped renderers.

TEXTURE_COLORMAP_TEXTURED_LIGHTMAP    = 1
TEXTURE_COLORMAP_UNTEXTURED_LIGHTMAP  = 4

; Seed one byte, then deliberately use an overlapping forward MVN to replicate
; it across the remaining 255 bytes in the row. X enters as row*256 and is
; reconstructed after MVN so no scratch RAM is needed.
.macro BSP_COLLAPSE_COLORMAP_ROWS row_table, row_count
        .local Row
        RW_forced a16i16
        ldx     #$0000
Row:
        txa
        xba
        and     #$00FF
        tax
        RW      a8
        lda     f:row_table,x
        pha
        RW      a16
        txa
        and     #$00FF
        xba
        clc
        adc     #.loword(GSU_TEXTURE_COLORMAP)
        tax
        tay
        iny
        RW      a8
        pla
        sta     f:GSU_DATA_BASE,x
        RW      a16
        lda     #$00FE                 ; Copy 255 bytes after the seed.
        phb
        mvn     #^(GSU_DATA_BASE), #^(GSU_DATA_BASE)
        plb
        txa
        sec
        sbc     #.loword(GSU_TEXTURE_COLORMAP)-1
        tax
        cpx     #row_count * 256
        bcc     Row
.endmacro

; Technique 4 uses the natural 64-row table and technique 7 collapses those
; rows to a neutral ramp. Technique 2 ignores this RAM.
SyncTextureColormap:
        RW_assume a16i16
        ; The final-index cache is valid only when both texture and lightmap
        ; output are requested. Publish this once while the GSU is idle so the
        ; established per-face gate remains unchanged in cost.
        lda     render_camera+10
        and     #$00FF
        cmp     #BSP_TECHNIQUE_TEXTURED_LIGHTMAP
        beq     @ComposedAllowed
        lda     #$0000
        bra     @ComposedPublish
@ComposedAllowed:
        lda     #$0001
@ComposedPublish:
        sta     f:GSU_DATA_BASE+GSU_TEXTURE_COMPOSED_ALLOWED_OFFSET
        lda     render_camera+10
        and     #$00FF
        cmp     #$0002
        bcc     SyncTextureColormapDispatch
        jsr     SyncTextureDivideQ12Mirror
SyncTextureColormapDispatch:
        lda     render_camera+10
        and     #$00FF
.if .defined(PLAYABLE_FLAT_MONOTONE_RASTER) && .defined(PLAYABLE_PAIRED_WORLD_CODE) && (BSP_RENDER_SCALE = 2)
        cmp     #$0003
        beq     SyncFlatMonotoneOverlay
        lda     flat_monotone_resident
        beq     @ReloadTechnique
        jsr     InstallPairedWorldOverlay
@ReloadTechnique:
        lda     render_camera+10
        and     #$00FF
.endif
        cmp     #$0004
        bne     :+
        jmp     SyncTextureColormapTexturedLightmap
:
        cmp     #$0007
        bne     :+
        jmp     SyncTextureColormapUntexturedLightmap
:
        rts

.if .defined(PLAYABLE_FLAT_MONOTONE_RASTER) && .defined(PLAYABLE_PAIRED_WORLD_CODE) && (BSP_RENDER_SCALE = 2)
; The reciprocal mirror can reinstall the paired image. Select the Flat
; owner after the mirror fence while the GSU is still stopped.
SyncFlatMonotoneOverlay:
        lda     flat_monotone_resident
        beq     @Install
        rts
@Install:
        BSP_STATIC_COPY __GSU_FLAT_MONOTONE_CODE_RUN__, BSP_CPU_CODE_ADDRESS(__GSU_FLAT_MONOTONE_CODE_LOAD__), __GSU_FLAT_MONOTONE_CODE_SIZE__
        lda     #$0001
        sta     flat_monotone_resident
        jmp     InvalidateFlatBrushCodeCache
.endif

; Flat renderers phase-overlay the bank-$70 hot reciprocal mirror and overwrite
; the hidden texture rows that host the cold clear helper. Rebuild the mirror,
; its reserved turbulence-sampler tail, and the texture helper only on the
; transition back to a textured technique; steady frames just test the validity
; word while the GSU is idle.
SyncTextureDivideQ12Mirror:
        lda     texture_phase_overlay_valid
        bne     SyncTextureDivideQ12MirrorDone
        BSP_STATIC_COPY GSU_DIVIDE_Q12_HOT_MIRROR, QuakeBSPDivideQ12Reciprocal, GSU_DIVIDE_Q12_HOT_MIRROR_BYTES
.if .defined(QUAKE_MSU_CACHE) .and (BSP_RENDER_SCALE = 2)
        jsr     MsuCacheResetArena
.endif
        BSP_STATIC_COPY __GSU_TURBULENCE_HOT_CODE_RUN__, BSP_CPU_CODE_ADDRESS(__GSU_TURBULENCE_HOT_CODE_LOAD__), __GSU_TURBULENCE_HOT_CODE_SIZE__
        BSP_STATIC_COPY __GSU_TEXTURE_TAIL_CODE_RUN__, BSP_CPU_CODE_ADDRESS(__GSU_TEXTURE_TAIL_CODE_LOAD__), __GSU_TEXTURE_TAIL_CODE_SIZE__
.ifdef PLAYABLE_MAP_ID
        BSP_STATIC_COPY __GSU_FACE_COLOR_CODE_RUN__, BSP_CPU_CODE_ADDRESS(__GSU_FACE_COLOR_CODE_LOAD__), __GSU_FACE_COLOR_CODE_SIZE__
.endif
.if .defined(PLAYABLE_PAIRED_WORLD_CODE) && (BSP_RENDER_SCALE = 2)
        jsr     InstallPairedWorldOverlay
.endif
        lda     #$0001
        sta     texture_phase_overlay_valid
SyncTextureDivideQ12MirrorDone:
        rts

SyncTextureColormapTexturedLightmap:
        lda     texture_colormap_mode
.ifdef PLAYABLE_TEXTURELESS_WHITE
        cmp     #TEXTURE_COLORMAP_UNTEXTURED_LIGHTMAP
        bne     :+
        jsr     RestoreTexturedLightmapMapper
        bra     SyncTextureColormapNaturalRows
:
.endif
        cmp     #TEXTURE_COLORMAP_TEXTURED_LIGHTMAP
.ifdef PLAYABLE_SPRITE_STREAM
        bne     @Full
        lda     SpriteStreamColormapDirty
        beq     SyncTextureColormapTexturedLightmapDone
        ; Restore the checked natural rows saved at map boot.
        ; DMA6 reads the WRAM port and writes the idle FX3 RAM window.
        RW      a8
        ldx     #.loword(SpriteStreamColormapShadow)
        stx     WMADDL
        lda     #(^SpriteStreamColormapShadow & 1)
        sta     WMADDH
        ldx     #.loword(GSU_TEXTURE_COLORMAP)
        stx     A1T6L
        lda     #^GSU_TEXTURE_COLORMAP
        sta     A1B6
        lda     #$80
        sta     DMAP6
        sta     BBAD6
        ldx     #SPRITE_STREAM_CACHE_BYTES
        stx     DAS6L
        lda     #$40
        sta     MDMAEN
        RW      a16
        stz     SpriteStreamColormapDirty
        rts
@Full:
.else
        beq     SyncTextureColormapTexturedLightmapDone
.endif
.ifdef PLAYABLE_TEXTURELESS_WHITE
SyncTextureColormapNaturalRows:
.endif
        BSP_STATIC_COPY GSU_TEXTURE_COLORMAP, QuakeBSPLightmapColormap, GSU_LIGHTMAP_COLORMAP_BYTES
.ifdef PLAYABLE_SPRITE_STREAM
        stz     SpriteStreamColormapDirty
.endif
        lda     #TEXTURE_COLORMAP_TEXTURED_LIGHTMAP
        sta     texture_colormap_mode
SyncTextureColormapTexturedLightmapDone:
        rts

SyncTextureColormapUntexturedLightmap:
.ifdef PLAYABLE_TEXTURELESS_WHITE
        ; Scale and brush overlay installs can restore individual sites.
        ; Refresh their same-size mapper while the GSU is idle.
        jsr     InstallTexturelessLightmapMapper
        lda     texture_colormap_mode
        cmp     #TEXTURE_COLORMAP_UNTEXTURED_LIGHTMAP
        beq     SyncTextureColormapUntexturedLightmapDone
        BSP_STATIC_COPY GSU_DATA_BASE+GSU_TEXTURELESS_ROWS_OFFSET, QuakeBSPUntexturedLightmapRows, GSU_TEXTURELESS_ROWS_BYTES
        lda     #TEXTURE_COLORMAP_UNTEXTURED_LIGHTMAP
        sta     texture_colormap_mode
.else
        lda     texture_colormap_mode
        cmp     #TEXTURE_COLORMAP_UNTEXTURED_LIGHTMAP
.ifdef PLAYABLE_SPRITE_STREAM
        beq     :+
        jmp     SyncTextureColormapUntexturedLightmapFull
:       lda     SpriteStreamColormapDirty
        bne     :+
        rts
:       BSP_COLLAPSE_COLORMAP_ROWS QuakeBSPUntexturedLightmapRows, SPRITE_STREAM_CACHE_BYTES / 256
        stz     SpriteStreamColormapDirty
        rts
SyncTextureColormapUntexturedLightmapFull:
.else
        beq     SyncTextureColormapUntexturedLightmapDone
.endif
        BSP_COLLAPSE_COLORMAP_ROWS QuakeBSPUntexturedLightmapRows, 64
.ifdef PLAYABLE_SPRITE_STREAM
        stz     SpriteStreamColormapDirty
.endif
        lda     #TEXTURE_COLORMAP_UNTEXTURED_LIGHTMAP
        sta     texture_colormap_mode
.endif
SyncTextureColormapUntexturedLightmapDone:
        rts
