; Included at RenderProductionRenderer. All-feature fly is selected once per
; job, independently of the demo-only technique4_specialized_path switch.
.if BSP_FLY_FUSED_SUPPORTED
        lda     render_demo_pose
        cmp     #$FFFF
        bne     @OtherFlyConfiguration
        lda     render_camera+10
        cmp     #BSP_FLY_FUSED_COMMAND
        bne     @OtherFlyConfiguration
        ; The admitted command fixes textures, lightmaps and all overlays.
        ; Reuse the fixed-lightmap kernels through our own realtime fly entry.
        jsr     EnsureFlyBrushPVSCode
        jsr     SyncTextureColormap
        ldx     #.loword(GSU_FlyTextureLightmapCode)
        jmp     RenderTextureRenderer
@OtherFlyConfiguration:
.endif
