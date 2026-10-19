; Direct source-pose lookup on the S-CPU avoids GSU dictionary and projection
; dispatch. The resulting ROM address survives selector scratch reuse.
StageAliasVisibilityArchive:
        RW_assume a16i16
.assert BSP_ALIAS_ARCHIVE_VERSION = 3, error, "Unsupported alias archive version"
.if ((BSP_RENDER_SCALE = 2) && ((BSP_VIEW_WIDTH <> 128) || (BSP_VIEW_HEIGHT <> 112) || (BSP_VIEW_CENTER_X <> 64) || (BSP_VIEW_CENTER_Y <> 56))) || ((BSP_RENDER_SCALE = 3) && ((BSP_VIEW_WIDTH <> 85) || (BSP_VIEW_HEIGHT <> 74) || (BSP_VIEW_CENTER_X <> 43) || (BSP_VIEW_CENTER_Y <> 37)))
        lda     #$FFFF
        sta     f:GSU_DATA_BASE+GSU_ALIAS_ARCHIVE_ADDRESS_OFFSET
        rts
.else
        lda     render_camera+14
        cmp     #BSP_ALIAS_VISIBILITY_SOURCE_ROW_COUNT
        bcs     @Live
        asl
        tax
        lda     render_camera+10
        and     #$00FF
        cmp     #BSP_TECHNIQUE_TEXTURED_LIGHTMAP
        bne     @Live
        lda     render_camera+10
        bit     #(BSP_OVERLAY_FLY_STATICS << 8)
        bne     @Live
        ; Brush visual states are interned, not source-pose numbers.
        and     #((BSP_OVERLAY_DYNAMIC_BRUSHES | BSP_OVERLAY_EXTERNAL_BSP) << 8)
        beq     @StateReady
        lda     f:BSP_BRUSH_ROWSTATE_CPU_ADDRESS,x
        cmp     render_brush_visual_state
        bne     @Live
@StateReady:
.if BSP_RENDER_SCALE = 3
        lda     render_camera+10
        bit     #(BSP_OVERLAY_WARP_OVERSCAN << 8)
        beq     @Unity
.if BSP_WARP_SOURCE_FOCAL <> BSP_ALIAS_ARCHIVE_WARP_FOCAL
        ; An independently built focal remains correct until its masks are
        ; regenerated; it must not consume the configured archive's stream.
        bra     @Live
.else
        and     #(BSP_OVERLAY_DYNAMIC_BRUSHES << 8)
        beq     @WarpDisabled
        lda     f:QuakeBSPAliasVisibilityX3WarpEnabled,x
        bra     @Publish
@WarpDisabled:
        lda     f:QuakeBSPAliasVisibilityX3WarpDisabled,x
        bra     @Publish
.endif
@Unity:
        and     #(BSP_OVERLAY_DYNAMIC_BRUSHES << 8)
        beq     @UnityDisabled
        lda     f:QuakeBSPAliasVisibilityX3UnityEnabled,x
        bra     @Publish
@UnityDisabled:
        lda     f:QuakeBSPAliasVisibilityX3UnityDisabled,x
.else
        lda     render_camera+10
        and     #(BSP_OVERLAY_DYNAMIC_BRUSHES << 8)
        beq     @Disabled
        lda     f:QuakeBSPAliasVisibilityX2Enabled,x
        bra     @Publish
@Disabled:
        lda     f:QuakeBSPAliasVisibilityX2Disabled,x
.endif
        bra     @Publish
@Live:
        lda     #$FFFF
@Publish:
        sta     f:GSU_DATA_BASE+GSU_ALIAS_ARCHIVE_ADDRESS_OFFSET
        rts
.endif
