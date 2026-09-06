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
        cmp     #$0004
        bne     :+
        jmp     SyncTextureColormapTexturedLightmap
:
        cmp     #$0007
        bne     :+
        jmp     SyncTextureColormapUntexturedLightmap
:
        rts

; Flat renderers phase-overlay the bank-$70 hot reciprocal mirror and overwrite
; the hidden texture rows that host the cold clear helper. Rebuild the mirror,
; its reserved turbulence-sampler tail, and the texture helper only on the
; transition back to a textured technique; steady frames just test the validity
; word while the GSU is idle.
SyncTextureDivideQ12Mirror:
        lda     texture_phase_overlay_valid
        bne     SyncTextureDivideQ12MirrorDone
        BSP_STATIC_COPY GSU_DIVIDE_Q12_HOT_MIRROR, QuakeBSPDivideQ12Reciprocal, GSU_DIVIDE_Q12_HOT_MIRROR_BYTES
        BSP_STATIC_COPY __GSU_TURBULENCE_HOT_CODE_RUN__, __GSU_TURBULENCE_HOT_CODE_LOAD__, __GSU_TURBULENCE_HOT_CODE_SIZE__
        BSP_STATIC_COPY __GSU_TEXTURE_TAIL_CODE_RUN__, __GSU_TEXTURE_TAIL_CODE_LOAD__, __GSU_TEXTURE_TAIL_CODE_SIZE__
        lda     #$0001
        sta     texture_phase_overlay_valid
SyncTextureDivideQ12MirrorDone:
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

SyncTextureColormapUntexturedLightmap:
        lda     texture_colormap_mode
        cmp     #TEXTURE_COLORMAP_UNTEXTURED_LIGHTMAP
        beq     SyncTextureColormapUntexturedLightmapDone
        BSP_COLLAPSE_COLORMAP_ROWS QuakeBSPUntexturedLightmapRows, 64
        lda     #TEXTURE_COLORMAP_UNTEXTURED_LIGHTMAP
        sta     texture_colormap_mode
SyncTextureColormapUntexturedLightmapDone:
        rts
