; Transition-only lookup selection for 8bpp renderers. None/LightMap
; textureless modes collapse colormap rows; Distance instead swaps in its
; dedicated full-range depth-to-index LUT.

TEXTURE_COLORMAP_TEXTURED_DISTANCE    = 0
TEXTURE_COLORMAP_TEXTURED_LIGHTMAP    = 1
TEXTURE_COLORMAP_UNTEXTURED_NONE      = 2
TEXTURE_COLORMAP_UNTEXTURED_DISTANCE  = 3
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

; Technique 3 uses 55 compact depth rows; technique 4 uses 64 natural
; lightmap rows. Complete tables are copied or collapsed only when the selected
; table changes. Techniques 0..2 ignore this RAM.
SyncTextureColormap:
        RW_assume a16i16
        lda     render_camera+10
        and     #$00FF
        cmp     #$0002
        bcc     SyncTextureColormapDispatch
        jsr     SyncTextureDivideQ12Mirror
SyncTextureColormapDispatch:
        lda     render_camera+10
        and     #$00FF
        cmp     #$0004
        bne     :+
        jmp     SyncTextureColormapTexturedLightmap
:
        cmp     #$0003
        beq     SyncTextureColormapTexturedDistance
        cmp     #$0005
        bne     :+
        jmp     SyncTextureColormapUntexturedNone
:
        cmp     #$0006
        bne     :+
        jmp     SyncTextureColormapUntexturedDistance
:
        cmp     #$0007
        bne     :+
        jmp     SyncTextureColormapUntexturedLightmap
:
        rts

; Flat renderers phase-overlay the bank-$70 hot reciprocal mirror. Rebuild it
; only on the transition back to a textured technique; steady frames just test
; the validity word while the GSU is idle.
SyncTextureDivideQ12Mirror:
        lda     texture_divide_q12_mirror_valid
        bne     SyncTextureDivideQ12MirrorDone
        BSP_STATIC_COPY GSU_DIVIDE_Q12_HOT_MIRROR, QuakeBSPDivideQ12Reciprocal, GSU_DIVIDE_Q12_HOT_MIRROR_BYTES
        lda     #$0001
        sta     texture_divide_q12_mirror_valid
SyncTextureDivideQ12MirrorDone:
        rts

SyncTextureColormapTexturedDistance:
        lda     texture_colormap_mode
        cmp     #TEXTURE_COLORMAP_TEXTURED_DISTANCE
        beq     SyncTextureColormapTexturedDistanceDone
        BSP_STATIC_COPY GSU_TEXTURE_DEPTH_SHADE, QuakeBSPTextureDepthShade, GSU_TEXTURE_DEPTH_SHADE_BYTES
        BSP_STATIC_COPY GSU_TEXTURE_COLORMAP, QuakeBSPTextureColormap, GSU_TEXTURE_COLORMAP_BYTES
        lda     #TEXTURE_COLORMAP_TEXTURED_DISTANCE
        sta     texture_colormap_mode
SyncTextureColormapTexturedDistanceDone:
        rts

SyncTextureColormapTexturedLightmap:
        lda     texture_colormap_mode
        cmp     #TEXTURE_COLORMAP_TEXTURED_LIGHTMAP
        beq     SyncTextureColormapTexturedLightmapDone
        BSP_STATIC_COPY GSU_TEXTURE_COLORMAP, QuakeBSPLightmapColormap, GSU_LIGHTMAP_COLORMAP_BYTES
        lda     #TEXTURE_COLORMAP_TEXTURED_LIGHTMAP
        sta     texture_colormap_mode
SyncTextureColormapTexturedLightmapDone:
        rts

SyncTextureColormapUntexturedNone:
        lda     texture_colormap_mode
        cmp     #TEXTURE_COLORMAP_UNTEXTURED_NONE
        beq     SyncTextureColormapUntexturedNoneDone
        BSP_STATIC_COPY GSU_TEXTURE_DEPTH_SHADE, QuakeBSPTextureDepthShade, GSU_TEXTURE_DEPTH_SHADE_BYTES
        BSP_COLLAPSE_COLORMAP_ROWS QuakeBSPUntexturedNoneRows, 55
        lda     #TEXTURE_COLORMAP_UNTEXTURED_NONE
        sta     texture_colormap_mode
SyncTextureColormapUntexturedNoneDone:
        rts

SyncTextureColormapUntexturedDistance:
        lda     texture_colormap_mode
        cmp     #TEXTURE_COLORMAP_UNTEXTURED_DISTANCE
        beq     SyncTextureColormapUntexturedDistanceDone
        BSP_STATIC_COPY GSU_TEXTURE_DEPTH_SHADE, QuakeBSPUntexturedDistanceDepthShade, GSU_TEXTURE_DEPTH_SHADE_BYTES
        lda     #TEXTURE_COLORMAP_UNTEXTURED_DISTANCE
        sta     texture_colormap_mode
SyncTextureColormapUntexturedDistanceDone:
        rts

SyncTextureColormapUntexturedLightmap:
        lda     texture_colormap_mode
        cmp     #TEXTURE_COLORMAP_UNTEXTURED_LIGHTMAP
        beq     SyncTextureColormapUntexturedLightmapDone
        BSP_COLLAPSE_COLORMAP_ROWS QuakeBSPUntexturedLightmapRows, 64
        lda     #TEXTURE_COLORMAP_UNTEXTURED_LIGHTMAP
        sta     texture_colormap_mode
SyncTextureColormapUntexturedLightmapDone:
        rts
