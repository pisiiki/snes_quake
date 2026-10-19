; Source projection is immutable for a rendered image and travels in its camera
; flags. The ordinary X3 and fly paths retain their existing focal length.
.if BSP_RENDER_SCALE = 3
.segment "LORAM"
warp_projection_installed: .res 2
.segment "CODE"
EnsureWarpOverscanProjection:
        RW_assume a16i16
        lda     render_camera+10
        and     #(BSP_OVERLAY_WARP_OVERSCAN << 8)
        cmp     warp_projection_installed
.if BSP_WARP_SOURCE_FOCAL < BSP_VIEW_CENTER_X
        bne     :+
        rts
:
        sta     warp_projection_installed
        cmp     #0                     ; CMP above tested the previous mode.
        bne     :+
        jmp     @Normal
:
.else
        beq     @Ready
        sta     warp_projection_installed
.if BSP_WARP_SOURCE_FOCAL < 64
        cmp     #0                     ; STA does not set the zero flag.
.endif
        beq     @Normal
.endif
        BSP_STATIC_COPY GSU_RECIPROCAL, Fly3WarpReciprocal, GSU_RECIPROCAL_RAM_BYTES
        BSP_STATIC_COPY ConvexProjectScale, WarpFocalPatch, BSP_WARP_FOCAL_PATCH_BYTES
.if BSP_WARP_SOURCE_FOCAL < BSP_VIEW_CENTER_X
        BSP_STATIC_COPY PacketClipRightScale, WarpClipAxisScalePatch, 2
        BSP_STATIC_COPY PacketClipUpScale, WarpClipAxisScalePatch, 2
        BSP_STATIC_COPY SharedClipRightScale, WarpClipAxisScalePatch, 2
        BSP_STATIC_COPY SharedClipUpScale, WarpClipAxisScalePatch, 2
        BSP_STATIC_COPY ConvexClipAxisScale, WarpClipAxisScalePatch, 2
        BSP_STATIC_COPY AliasClipDepthScale, WarpClipDepthScalePatch, 2
        BSP_STATIC_COPY ConvexProjectClampScale, WarpProjectClampScalePatch, 1
        BSP_STATIC_COPY ConvexProjectClampLimit, WarpProjectWideClampPatch, 3
.endif
.if BSP_WARP_SOURCE_FOCAL < BSP_VIEW_CENTER_X
        jmp     @Invalidate
.else
        bra     @Invalidate
.endif
@Normal:
        BSP_STATIC_COPY GSU_RECIPROCAL, Fly3Reciprocal, GSU_RECIPROCAL_RAM_BYTES
        BSP_STATIC_COPY ConvexProjectScale, BSP_CPU_CODE_ADDRESS(__GSUCODE_LOAD__+ConvexProjectScale-__GSUCODE_RUN__), BSP_WARP_FOCAL_PATCH_BYTES
.if BSP_WARP_SOURCE_FOCAL < BSP_VIEW_CENTER_X
        BSP_STATIC_COPY PacketClipRightScale, WarpClipNoScalePatch, 2
        BSP_STATIC_COPY PacketClipUpScale, WarpClipNoScalePatch, 2
        BSP_STATIC_COPY SharedClipRightScale, WarpClipNoScalePatch, 2
        BSP_STATIC_COPY SharedClipUpScale, WarpClipNoScalePatch, 2
        BSP_STATIC_COPY ConvexClipAxisScale, WarpClipNoScalePatch, 2
        BSP_STATIC_COPY AliasClipDepthScale, WarpClipNoScalePatch, 2
        BSP_STATIC_COPY ConvexProjectClampScale, WarpClipNoScalePatch, 1
        BSP_STATIC_COPY ConvexProjectClampLimit, WarpProjectNormalClampPatch, 3
.endif
@Invalidate:
        RW_forced a16i16
        stz     active_packet_guard_status
        lda     #0
        sta     f:GSU_DATA_BASE+GSU_TELEMETRY_PACKET_REVISION
@Ready:
        rts
.endif
