; Install only the color and texture-coordinate replacements used by Flat.
.ifdef PLAYABLE_FLAT_BRUSH_DEPTH
.import FlatBrushAnchorSite, BrushArbiterSpanCompose, FlatBrushAdvanceSite
.import FlatBrushAnchorPatch, FlatBrushComposePatch, FlatBrushAdvancePatch, FlatBrushPatchEnd
  .if .defined(PLAYABLE_SWITCHED_LIGHTS) && (PLAYABLE_MAP_ID = PLAYABLE_E1M1_MAP_ID)
.define FLAT_BRUSH_SPAN_LOAD FlatBrushAnchorPatch
.define FLAT_BRUSH_SPAN_RUN FlatBrushAnchorPatch
  .elseif PLAYABLE_MAP_ID = PLAYABLE_E1M1_MAP_ID
.define FLAT_BRUSH_SPAN_LOAD __GSU_FACE_COLOR_CODE_LOAD__
.define FLAT_BRUSH_SPAN_RUN __GSU_FACE_COLOR_CODE_RUN__
  .else
.define FLAT_BRUSH_SPAN_LOAD __GSUCODE_LOAD__
.define FLAT_BRUSH_SPAN_RUN __GSUCODE_RUN__
  .endif
.endif
.ifdef PLAYABLE_FLAT_BRUSH_FRAGMENT
.import BrushComputeFragmentCoordinates, FlatBrushFragmentPatch, FlatBrushFragmentPatchEnd
  .if .defined(PLAYABLE_MAP_ID) && .defined(PLAYABLE_BRUSH_FRAGMENT_AFFINE) && (BSP_RENDER_SCALE = 2)
.import BrushPrepareFragmentAffine, FlatBrushSkipAffinePatch, FlatBrushSkipAffinePatchEnd
  .endif
  .ifdef PLAYABLE_FLAT_BRUSH_FRAGMENT_SELECTOR
.define FLAT_BRUSH_FRAGMENT_LOAD __GSUCODE_LOAD__
.define FLAT_BRUSH_FRAGMENT_RUN __GSUCODE_RUN__
  .else
.define FLAT_BRUSH_FRAGMENT_LOAD __GSU_AUX_CODE_LOAD__
.define FLAT_BRUSH_FRAGMENT_RUN __GSU_AUX_CODE_RUN__
  .endif
.endif
.ifdef PLAYABLE_FLAT_BRUSH_PROJECTIVE_EDGE
.import FlatBrushForwardProjectiveEdge, FlatBrushReverseProjectiveEdge
.import TextureIntersectActiveEdgeProjective
.import FlatBrushForwardEdgeTarget, FlatBrushReverseEdgeTarget
.endif
.ifdef PLAYABLE_FLAT_COMPONENT_PROJECTOR
.import FlatProjectComponent
.endif
.ifdef PLAYABLE_FLAT_BRUSH_DEPTH
.import FlatMonotoneCacheSite
.endif

.if .defined(PLAYABLE_FLAT_BRUSH_MATERIAL) && (BSP_RENDER_SCALE = 2)
.import BakedReturn, BrushLoadFaceMaterial, BrushArbiterPrepareMaterials
.import FlatBrushCollectMaterialTarget, FlatBrushPrepareMaterialsTarget
.import FlyBrushBuildDepthView, BrushBuildFragmentView, FlatBrushCollectViewTarget
.import FlatBrushStoreFaceSite, BrushArbiterCandidateSpanPresent
.import FlatBrushStoreFacePatch, FlatBrushCandidateMaterialPatch, FlatBrushMaterialPatchEnd
.endif

.ifdef PLAYABLE_FLAT_MONOTONE_RASTER
.import TextureRasterPolygon, FlatMonotoneDispatch, FlatMonotoneDispatchEnd
  .if PLAYABLE_MAP_ID <> PLAYABLE_E1M1_MAP_ID
.import FlatMixedWorldFaceTarget, FlatMixedWorldFace, BrushTryRenderComposedWorldFace
  .endif
.endif

.macro PATCH_FLAT_COMPONENT_PROJECTOR restore
  .ifdef PLAYABLE_FLAT_COMPONENT_PROJECTOR
    .ifblank restore
        lda     #.loword(FlatProjectComponent)
    .else
        lda     #.loword(ConvexProjectComponent)
    .endif
        sta     f:TextureShadeProjectRightCall+2
        sta     f:TextureShadeProjectUpCall+2
  .if .defined(PLAYABLE_FLAT_MONOTONE_RASTER) && (BSP_RENDER_SCALE = 2)
    .if PLAYABLE_MAP_ID = PLAYABLE_E1M1_MAP_ID
        .import TextureShadePrepareDepthCall, TexturePrepareDivideQ12, FlatPrepareProjectionDivide
      .ifblank restore
        lda     #.loword(FlatPrepareProjectionDivide)
      .else
        lda     #.loword(TexturePrepareDivideQ12)
      .endif
        sta     f:TextureShadePrepareDepthCall+2
    .endif
  .endif
  .endif
.endmacro

.macro COPY_FLAT_BRUSH_PATCH site, patch, next, load, run, restore
  .ifblank restore
        BSP_STATIC_COPY site, BSP_CPU_CODE_ADDRESS(load)+(patch-run), next-patch
  .else
        BSP_STATIC_COPY site, BSP_CPU_CODE_ADDRESS(__GSU_BRUSH_CODE_LOAD__)+(site-__GSU_BRUSH_CODE_RUN__), next-patch
  .endif
.endmacro

.macro COPY_FLAT_BRUSH_PATCHES restore
  .ifdef PLAYABLE_FLAT_BRUSH_DEPTH
        COPY_FLAT_BRUSH_PATCH FlatBrushAnchorSite, FlatBrushAnchorPatch, FlatBrushComposePatch, FLAT_BRUSH_SPAN_LOAD, FLAT_BRUSH_SPAN_RUN, restore
        COPY_FLAT_BRUSH_PATCH BrushArbiterSpanCompose, FlatBrushComposePatch, FlatBrushAdvancePatch, FLAT_BRUSH_SPAN_LOAD, FLAT_BRUSH_SPAN_RUN, restore
        COPY_FLAT_BRUSH_PATCH FlatBrushAdvanceSite, FlatBrushAdvancePatch, FlatBrushPatchEnd, FLAT_BRUSH_SPAN_LOAD, FLAT_BRUSH_SPAN_RUN, restore
  .endif
  .ifdef PLAYABLE_FLAT_BRUSH_FRAGMENT
        COPY_FLAT_BRUSH_PATCH BrushComputeFragmentCoordinates, FlatBrushFragmentPatch, FlatBrushFragmentPatchEnd, FLAT_BRUSH_FRAGMENT_LOAD, FLAT_BRUSH_FRAGMENT_RUN, restore
    .if .defined(PLAYABLE_MAP_ID) && .defined(PLAYABLE_BRUSH_FRAGMENT_AFFINE) && (BSP_RENDER_SCALE = 2)
        COPY_FLAT_BRUSH_PATCH BrushPrepareFragmentAffine, FlatBrushSkipAffinePatch, FlatBrushSkipAffinePatchEnd, FLAT_BRUSH_FRAGMENT_LOAD, FLAT_BRUSH_FRAGMENT_RUN, restore
    .endif
  .endif
  .ifdef PLAYABLE_FLAT_BRUSH_PROJECTIVE_EDGE
    .ifblank restore
        lda     #.loword(FlatBrushForwardProjectiveEdge)
        sta     f:FlatBrushForwardEdgeTarget
        lda     #.loword(FlatBrushReverseProjectiveEdge)
    .else
        lda     #.loword(TextureIntersectActiveEdgeProjective)
        sta     f:FlatBrushForwardEdgeTarget
    .endif
        sta     f:FlatBrushReverseEdgeTarget
  .endif
  .ifndef PLAYABLE_FLAT_MONOTONE_RASTER
        PATCH_FLAT_COMPONENT_PROJECTOR restore
  .endif
  .ifdef PLAYABLE_FLAT_BRUSH_DEPTH
        RW      a8
    .ifblank restore
        lda     #$02                    ; Super FX CACHE, one byte.
    .else
        lda     #$01                    ; Restore the original NOP.
    .endif
        sta     f:FlatMonotoneCacheSite
        RW      a16
  .endif
  .if .defined(PLAYABLE_FLAT_BRUSH_MATERIAL) && (BSP_RENDER_SCALE = 2)
    .ifblank restore
        lda     #.loword(BakedReturn)
        sta     f:FlatBrushCollectMaterialTarget
    .else
        lda     #.loword(BrushLoadFaceMaterial)
        sta     f:FlatBrushCollectMaterialTarget
        lda     #.loword(BrushArbiterPrepareMaterials)
    .endif
        sta     f:FlatBrushPrepareMaterialsTarget
    .ifblank restore
        lda     #.loword(FlyBrushBuildDepthView)
    .else
        lda     #.loword(BrushBuildFragmentView)
    .endif
        sta     f:FlatBrushCollectViewTarget
        COPY_FLAT_BRUSH_PATCH FlatBrushStoreFaceSite, FlatBrushStoreFacePatch, FlatBrushCandidateMaterialPatch, __GSUCODE_LOAD__, __GSUCODE_RUN__, restore
        COPY_FLAT_BRUSH_PATCH BrushArbiterCandidateSpanPresent, FlatBrushCandidateMaterialPatch, FlatBrushMaterialPatchEnd, __GSUCODE_LOAD__, __GSUCODE_RUN__, restore
  .endif
  .ifdef PLAYABLE_FLAT_MONOTONE_RASTER
    .ifblank restore
        jsl     InstallFlatWorldRaster
        BSP_STATIC_COPY TextureRasterPolygon, BSP_CPU_CODE_ADDRESS(__GSU_FLAT_MONOTONE_CODE_LOAD__)+(FlatMonotoneDispatch-__GSU_FLAT_MONOTONE_CODE_RUN__), FlatMonotoneDispatchEnd-FlatMonotoneDispatch
    .else
        jsl     RestoreFullWorldRaster
        BSP_STATIC_COPY TextureRasterPolygon, BSP_CPU_CODE_ADDRESS(__GSUCODE_LOAD__)+(TextureRasterPolygon-__GSUCODE_RUN__), FlatMonotoneDispatchEnd-FlatMonotoneDispatch
    .endif
  .endif
.endmacro

EnsureFlatBrushCode:
        RW_assume a16i16
        lda     texture_renderer_code_variant
        cmp     #FLAT_BRUSH_CODE_VARIANT
        bne     @Install
        rts
@Install:
        jsr     EnsureGeneralTextureRendererCode
        COPY_FLAT_BRUSH_PATCHES
        lda     #FLAT_BRUSH_CODE_VARIANT
        sta     texture_renderer_code_variant
        jmp     InvalidateFlatBrushCodeCache

RestoreFlatBrushCode:
        RW_assume a16i16
        COPY_FLAT_BRUSH_PATCHES restore
        stz     texture_renderer_code_variant
InvalidateFlatBrushCodeCache:
.ifdef PLAYABLE_RESIDENT_WORLD
        ; Identical geometry has different opaque pixels in Full and Flat.
        lda     #0
        sta     f:GSU_DATA_BASE+GSU_RESIDENT_WORLD_STATUS
.endif
        RW      a8
        lda     #$70
        sta     FX3_PBR
        RW      a16
        rts

.ifdef PLAYABLE_FLAT_MONOTONE_RASTER
.pushseg
.segment "BSP_QUAKEC"
InstallFlatWorldRaster:
        RW_assume a16i16
  .if PLAYABLE_MAP_ID <> PLAYABLE_E1M1_MAP_ID
        lda     #.loword(FlatMixedWorldFace)
        sta     f:FlatMixedWorldFaceTarget
  .endif
        PATCH_FLAT_COMPONENT_PROJECTOR
        rtl
RestoreFullWorldRaster:
        RW_assume a16i16
  .if PLAYABLE_MAP_ID <> PLAYABLE_E1M1_MAP_ID
        lda     #.loword(BrushTryRenderComposedWorldFace)
        sta     f:FlatMixedWorldFaceTarget
  .endif
        PATCH_FLAT_COMPONENT_PROJECTOR restore
        rtl
.popseg
.endif
