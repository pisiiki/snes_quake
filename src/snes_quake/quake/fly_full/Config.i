; One admitted configuration for the dedicated fly renderer. The command is
; immutable by this boundary; live UI state must not participate in dispatch.
BSP_FLY_FUSED_OVERLAYS = BSP_OVERLAY_DYNAMIC_BRUSHES | BSP_OVERLAY_ALIAS_ENTITIES | BSP_OVERLAY_FLY_STATICS | BSP_OVERLAY_EXTERNAL_BSP
BSP_FLY_FUSED_COMMAND = BSP_TECHNIQUE_TEXTURED_LIGHTMAP | (BSP_FLY_FUSED_OVERLAYS << 8)
BSP_FLY_FUSED_SUPPORTED = BSP_SKY_ENABLED && BSP_TURBULENCE_ENABLED && BSP_EXTERNAL_BSP_SUPPORTED

.assert BSP_FLY_FUSED_COMMAND = $2704, error, "Fly fused command ABI changed; update profiler binding"
