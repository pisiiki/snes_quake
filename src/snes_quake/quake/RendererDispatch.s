; CPU-side renderer selection and phase-overlay lifetime management.

.ifdef PLAYABLE_MAP_ID
  .if ((PLAYABLE_MAP_ID = PLAYABLE_E1M1_MAP_ID) || (PLAYABLE_MAP_ID = PLAYABLE_E1M2_MAP_ID) || (PLAYABLE_MAP_ID = PLAYABLE_E1M3_MAP_ID) || (PLAYABLE_MAP_ID = PLAYABLE_E1M4_MAP_ID)) && BSP_QUAKEC_GAMEPLAY && (BSP_RENDER_SCALE = 2)
PLAYABLE_LIGHTMAPPED_T4 = 1
  .endif
.endif

RenderStartRenderer:
SelectorStageRendererBegin:
        RW_forced a16i16
.if .defined(PLAYABLE_WEAPON_OBJ) && BSP_RENDER_SCALE = 2
        lda     video_active
        beq     :+
        jsr     WeaponObjPrepareWorld
:
.endif
.ifdef QC_HEALTH_COUNT
        jsr     QuakeCClearCollectedHealthPixels
.endif
        inc     gsu_job_counter
        lda     render_coverage_mode
        beq     RenderProductionRenderer
        dec                             ; Diagnostic modes 1/2 select phases 0/1.
        sta     FX3_R0
        ldx     #.loword(GSU_CoverageCode)
        jmp     RenderRendererReady
RenderProductionRenderer:
.include "fly_full/Dispatch.s"
        lda     render_camera+10
        and     #$00FF
        cmp     #BSP_TECHNIQUE_TEXTURED_LIGHTMAP
        bne     @GeneralTextureCode
        lda     technique4_specialized_path
        beq     @GeneralTextureCode
.if !((BSP_START_LARGE_PACKET && BSP_QUAKEC_GAMEPLAY && (BSP_RENDER_SCALE = 2)) || .defined(PLAYABLE_LIGHTMAPPED_T4))
        ; Other free-flight configurations retain the general renderer.
        lda     render_demo_pose
        cmp     #$FFFF
        beq     @GeneralTextureCode
.endif
        jsr     EnsureTechnique4RendererCode
.if BSP_RENDER_SCALE = 2
  .ifdef PLAYABLE_WEAPON_OBJ
        lda     #.loword(WeaponCullCoveredFace)
  .elseif .defined(PLAYABLE_LIGHTMAPPED_T4)
        lda     #.loword(WorldLightmapRasterTarget)
  .else
        ; Demo draws may omit pixels covered by the weapon that this job
        ; actually stages. Fly keeps the complete world before composition.
        lda     render_weapon_frame
        and     #$00FF
        beq     @DemoWorldUnmasked
        lda     #.loword(WeaponCullCoveredFace)
        bra     @SetDemoRasterCall
@DemoWorldUnmasked:
        lda     #.loword(WorldLightmapRasterTarget)
@SetDemoRasterCall:
  .endif
        sta     f:WorldLightmapRasterCall+2
.endif
        jsr     SyncTextureColormap
        lda     render_camera+10
        cmp     #$0100
        bcc     @Technique4WorldRenderer
        ldx     #.loword(GSU_T4_BrushTextureLightmapCode)
        jmp     RenderTextureRenderer
@Technique4WorldRenderer:
        ldx     #.loword(GSU_T4_TextureLightmapCode)
        jmp     RenderTextureRenderer
@GeneralTextureCode:
.if .defined(PLAYABLE_FLAT_BRUSH_CODE) && (BSP_RENDER_SCALE = 2)
        lda     render_camera+10
        cmp     #$0100
        bcc     @GeneralCodeReady
        and     #$00FF
        cmp     #RUNTIME_MENU_TECHNIQUE_FACE_COLORS
        bne     @GeneralCodeReady
        jsr     EnsureFlatBrushCode
        jsr     SyncTextureColormap
        ldx     #.loword(GSU_BrushTextureCode)
        jmp     RenderTextureRenderer
@GeneralCodeReady:
.endif
        jsr     EnsureGeneralTextureRendererCode
        jsr     SyncTextureColormap
        lda     render_camera+10
.if BSP_RENDER_SCALE = 3
        and     #$7FFF
.endif
        cmp     #$0100
        bcc     @WorldOnlyRenderer
        and     #$00FF
        cmp     #RUNTIME_MENU_TECHNIQUE_TEXTURED_NONE
        beq     @BrushAlbedoRenderer
.ifdef PLAYABLE_MAP_ID
        cmp     #RUNTIME_MENU_TECHNIQUE_FACE_COLORS
        beq     @BrushAlbedoRenderer
.endif
@BrushLightmapRenderer:
        ldx     #.loword(GSU_BrushTextureLightmapCode)
        bra     RenderTextureRenderer
@BrushAlbedoRenderer:
        ldx     #.loword(GSU_BrushTextureCode)
        bra     RenderTextureRenderer
@WorldOnlyRenderer:
        cmp     #RUNTIME_MENU_TECHNIQUE_TEXTURED_NONE
        beq     @WorldAlbedoRenderer
.ifdef PLAYABLE_MAP_ID
        cmp     #RUNTIME_MENU_TECHNIQUE_FACE_COLORS
        beq     @WorldAlbedoRenderer
.endif
        ldx     #.loword(GSU_TextureLightmapCode)
        bra     RenderTextureRenderer
@WorldAlbedoRenderer:
        ldx     #.loword(GSU_TextureCode)
RenderTextureRenderer:
.if .defined(QUAKE_MSU_CACHE) .and (BSP_RENDER_SCALE = 2)
        phx
        jsr     MsuCacheUpdate
MsuCacheUpdateDone:
        plx
.endif
 .if .defined(PLAYABLE_SPRITE_STREAM) .or .defined(PLAYABLE_WORLD_COORDINATE_STREAM)
        jsr     SpriteStreamPrepareRenderer
 .endif
.if .defined(PLAYABLE_RESIDENT_WORLD) && (BSP_RENDER_SCALE = 2)
        jsr     PrepareResidentWorldCommand
.endif
        RW_forced a8i16
.if .defined(PLAYABLE_MAP_ID) && BSP_QUAKEC_GAMEPLAY && (BSP_RENDER_SCALE = 3)
        ; Stream resumes enter their saved GSU PC without clearing a partially drawn world.
        lda     render_camera+10
        cmp     #BSP_TECHNIQUE_TEXTURED_LIGHTMAP
        bne     :+
        stx     FX3_R9
        ldx     #.loword(ClearFreshX3World)
:
.endif
        stz     FX3_SCBR
        FX3_JOB_START FX3_SCMR_128X128_8BPP_ROM, x, set
.if .defined(PLAYABLE_SPRITE_STREAM) .or .defined(PLAYABLE_WORLD_LIGHTMAP_STREAM) .or .defined(PLAYABLE_WORLD_COORDINATE_STREAM)
        jsr     SpriteStreamJoinRenderer
.elseif BSP_QUAKEC_GAMEPLAY && (BSP_RENDER_SCALE = 2)
        jsr     QuakeCJoinRenderer
.else
        BSP_SOUND_FX3_JOB_JOIN BSP_RENDER_SCALE
.endif
        stz     FX3_SCMR
        RW_forced a16i16
.if .defined(PLAYABLE_RESIDENT_WORLD) && (BSP_RENDER_SCALE = 2)
        jsl     FinishResidentWorldCommand
.endif
        inc     render_counter
.if .defined(PLAYABLE_FX3_PLANE_DISTANCE) && (BSP_RENDER_SCALE = 2)
        jsl     ServiceBakedFrameGameplay
.endif
        rts

.if .defined(PLAYABLE_RESIDENT_WORLD) && (BSP_RENDER_SCALE = 2)
.include "quake/BrushResidentWorld.s"
.endif

.if BSP_QUAKEC_GAMEPLAY && (BSP_RENDER_SCALE = 2)
QuakeCJoinRenderer:
        php
        RW_forced a16i16
        pha
        phy
@Wait:
        ldx     FX3_R15
        beq     @Done
.ifdef QC_QUEUED_INPUT
        ; Avoid entering the long-call wrapper on idle polls. The wrapper
        ; still rechecks R15 and the admitted tick before it starts a step.
        lda     f:QC_INPUT_TICK
        cmp     f:quakec_last_tick
        beq     @Wait
.endif
        jsl     QuakeCServiceFX3
        bra     @Wait
@Done:
        ply
        pla
        plp
        rts
.endif

EnsureBrushCode:
        RW_assume a16i16
        lda     brush_code_valid
        bne     @Ready
        BSP_STATIC_COPY __GSU_BRUSH_CODE_RUN__, BSP_CPU_CODE_ADDRESS(__GSU_BRUSH_CODE_LOAD__), __GSU_BRUSH_CODE_SIZE__
        lda     #$0001
        sta     brush_code_valid
        ; Reloading the general overlay also restores every sparse T4 brush window.
.if .defined(PLAYABLE_FLAT_BRUSH_CODE) && (BSP_RENDER_SCALE = 2)
        lda     texture_renderer_code_variant
        cmp     #FLAT_BRUSH_CODE_VARIANT
        bne     :+
  .if .defined(PLAYABLE_FLAT_COMPONENT_PROJECTOR) || .defined(PLAYABLE_FLAT_BRUSH_DEPTH)
        ; Restore the projection operands and monotone row cache site.
        jsr     RestoreFlatBrushCode
  .else
        jsr     InvalidateFlatBrushCodeCache
  .endif
:
.endif
        stz     texture_renderer_code_variant
@Ready:
        rts

; Fly tracing is not part of the ordered/demo boot image. Install it only at
; the user-visible mode transition, before any fly render can start.
EnsureFlyAliasCode:
        RW_assume a16i16
        BSP_STATIC_COPY __GSU_ALIAS_FLY_CODE_RUN__, BSP_CPU_CODE_ADDRESS(__GSU_ALIAS_FLY_CODE_LOAD__), __GSU_ALIAS_FLY_CODE_SIZE__
        rts

EnsureTechnique4RendererCode:
        RW_assume a16i16
        lda     texture_renderer_code_variant
        beq     @Install
.if .defined(PLAYABLE_FLAT_BRUSH_CODE) && (BSP_RENDER_SCALE = 2)
        cmp     #$0001
        beq     @Ready
        cmp     #$0002
        beq     @BrushPVS
        jsr     RestoreFlatBrushCode
        bra     @Install
@BrushPVS:
.else
        cmp     #$0002
        bne     @Ready
.endif
        jsr     RestoreBrushPVSCode
        lda     #$0001
        sta     texture_renderer_code_variant
@Ready:
        rts
@Install:
        ; The shared projection CACHE also covers this retired T2 raster
        ; prefix. Patch only the ordinary component calls; aliases and the
        ; runtime focal scale keep their original public implementations.
        BSP_STATIC_COPY __GSU_T4_PROJECTION_CODE_RUN__, BSP_CPU_CODE_ADDRESS(__GSU_T4_PROJECTION_CODE_LOAD__), __GSU_T4_PROJECTION_CODE_SIZE__
        lda     #.loword(T4ConvexProjectComponentCached)
        sta     f:TextureShadeProjectRightCall+2
        sta     f:TextureShadeProjectUpCall+2
        BSP_STATIC_COPY __GSU_T4_REPLAY_BOUNDS_CODE_RUN__, BSP_CPU_CODE_ADDRESS(__GSU_T4_REPLAY_BOUNDS_CODE_LOAD__), __GSU_T4_REPLAY_BOUNDS_CODE_SIZE__
        BSP_STATIC_COPY __GSU_T4_REPLAY_BOUNDS_MATH_CODE_RUN__, BSP_CPU_CODE_ADDRESS(__GSU_T4_REPLAY_BOUNDS_MATH_CODE_LOAD__), __GSU_T4_REPLAY_BOUNDS_MATH_CODE_SIZE__
        BSP_STATIC_COPY __GSU_T4_REPLAY_BOUNDS_LOAD_PATCH_RUN__, BSP_CPU_CODE_ADDRESS(__GSU_T4_REPLAY_BOUNDS_LOAD_PATCH_LOAD__), __GSU_T4_REPLAY_BOUNDS_LOAD_PATCH_SIZE__
        lda     #.loword(T4PrepareReplayBounds)
        sta     f:TextureEndpointBatchMathCall+2
        lda     #.loword(T4TextureEndpointLoadRow)
        sta     f:TextureEndpointLoadRowCall+2
        lda     #.loword(T4PrepareEndpointDepth)
        sta     f:BrushArbiterDepthMathCall+2
        lda     #.loword(T4TextureEndpointDepthBatch)
        sta     f:BrushArbiterDepthBatchCall+1
        BSP_STATIC_COPY __GSU_T4_RASTER_CODE_RUN__, BSP_CPU_CODE_ADDRESS(__GSU_T4_RASTER_CODE_LOAD__), __GSU_T4_RASTER_CODE_SIZE__
        BSP_STATIC_COPY __GSU_T4_EDGE_PATCH_RUN__, BSP_CPU_CODE_ADDRESS(__GSU_T4_EDGE_PATCH_LOAD__), __GSU_T4_EDGE_PATCH_SIZE__
        BSP_STATIC_COPY __GSU_T4_EDGE_DEPTH_CODE_RUN__, BSP_CPU_CODE_ADDRESS(__GSU_T4_EDGE_DEPTH_CODE_LOAD__), __GSU_T4_EDGE_DEPTH_CODE_SIZE__
        BSP_STATIC_COPY __GSU_T4_STAGE_CODE_RUN__, BSP_CPU_CODE_ADDRESS(__GSU_T4_STAGE_CODE_LOAD__), __GSU_T4_STAGE_CODE_SIZE__
        BSP_STATIC_COPY __GSU_T4_EDGE_OUTPUT_CODE_RUN__, BSP_CPU_CODE_ADDRESS(__GSU_T4_EDGE_OUTPUT_CODE_LOAD__), __GSU_T4_EDGE_OUTPUT_CODE_SIZE__
        BSP_STATIC_COPY __GSU_T4_FACE_DISPATCH_PATCH_RUN__, BSP_CPU_CODE_ADDRESS(__GSU_T4_FACE_DISPATCH_PATCH_LOAD__), __GSU_T4_FACE_DISPATCH_PATCH_SIZE__
        BSP_STATIC_COPY __GSU_T4_BLOCK_SELECT_CODE_RUN__, BSP_CPU_CODE_ADDRESS(__GSU_T4_BLOCK_SELECT_CODE_LOAD__), __GSU_T4_BLOCK_SELECT_CODE_SIZE__
        BSP_STATIC_COPY __GSU_T4_SAMPLE_WRAP_CODE_RUN__, BSP_CPU_CODE_ADDRESS(__GSU_T4_SAMPLE_WRAP_CODE_LOAD__), __GSU_T4_SAMPLE_WRAP_CODE_SIZE__
        BSP_STATIC_COPY __GSU_T4_SAMPLE_CODE_RUN__, BSP_CPU_CODE_ADDRESS(__GSU_T4_SAMPLE_CODE_LOAD__), __GSU_T4_SAMPLE_CODE_SIZE__
        BSP_STATIC_COPY __GSU_T4_SAMPLE_SELECT_PATCH_RUN__, BSP_CPU_CODE_ADDRESS(__GSU_T4_SAMPLE_SELECT_PATCH_LOAD__), __GSU_T4_SAMPLE_SELECT_PATCH_SIZE__
        BSP_STATIC_COPY __GSU_T4_SAMPLE_AUX_CODE_RUN__, BSP_CPU_CODE_ADDRESS(__GSU_T4_SAMPLE_AUX_CODE_LOAD__), __GSU_T4_SAMPLE_AUX_CODE_SIZE__
        BSP_STATIC_COPY __GSU_T4_BRUSH_FRAGMENT_PATCH_RUN__, BSP_CPU_CODE_ADDRESS(__GSU_T4_BRUSH_FRAGMENT_PATCH_LOAD__), __GSU_T4_BRUSH_FRAGMENT_PATCH_SIZE__
        BSP_STATIC_COPY __GSU_T4_BRUSH_WORLD_PATCH_RUN__, BSP_CPU_CODE_ADDRESS(__GSU_T4_BRUSH_WORLD_PATCH_LOAD__), __GSU_T4_BRUSH_WORLD_PATCH_SIZE__
        BSP_STATIC_COPY __GSU_T4_BRUSH_SAMPLE_PATCH_RUN__, BSP_CPU_CODE_ADDRESS(__GSU_T4_BRUSH_SAMPLE_PATCH_LOAD__), __GSU_T4_BRUSH_SAMPLE_PATCH_SIZE__
        BSP_STATIC_COPY __GSU_T4_BRUSH_RASTER_PATCH_RUN__, BSP_CPU_CODE_ADDRESS(__GSU_T4_BRUSH_RASTER_PATCH_LOAD__), __GSU_T4_BRUSH_RASTER_PATCH_SIZE__
        BSP_STATIC_COPY __GSU_T4_BRUSH_MODE_PATCH_RUN__, BSP_CPU_CODE_ADDRESS(__GSU_T4_BRUSH_MODE_PATCH_LOAD__), __GSU_T4_BRUSH_MODE_PATCH_SIZE__
        BSP_STATIC_COPY __GSU_T4_BRUSH_PREP_PATCH_RUN__, BSP_CPU_CODE_ADDRESS(__GSU_T4_BRUSH_PREP_PATCH_LOAD__), __GSU_T4_BRUSH_PREP_PATCH_SIZE__
        BSP_STATIC_COPY __GSU_T4_BRUSH_ROW_PATCH_RUN__, BSP_CPU_CODE_ADDRESS(__GSU_T4_BRUSH_ROW_PATCH_LOAD__), __GSU_T4_BRUSH_ROW_PATCH_SIZE__
        BSP_STATIC_COPY __GSU_T4_BRUSH_MATERIAL_PATCH_RUN__, BSP_CPU_CODE_ADDRESS(__GSU_T4_BRUSH_MATERIAL_PATCH_LOAD__), __GSU_T4_BRUSH_MATERIAL_PATCH_SIZE__
        BSP_STATIC_COPY __GSU_T4_BRUSH_FORWARD_PATCH_RUN__, BSP_CPU_CODE_ADDRESS(__GSU_T4_BRUSH_FORWARD_PATCH_LOAD__), __GSU_T4_BRUSH_FORWARD_PATCH_SIZE__
        BSP_STATIC_COPY __GSU_T4_BRUSH_REVERSE_PATCH_RUN__, BSP_CPU_CODE_ADDRESS(__GSU_T4_BRUSH_REVERSE_PATCH_LOAD__), __GSU_T4_BRUSH_REVERSE_PATCH_SIZE__
        BSP_STATIC_COPY __GSU_T4_BRUSH_SPAN_PATCH_RUN__, BSP_CPU_CODE_ADDRESS(__GSU_T4_BRUSH_SPAN_PATCH_LOAD__), __GSU_T4_BRUSH_SPAN_PATCH_SIZE__
        BSP_STATIC_COPY __GSU_T4_BRUSH_BLOCK_PATCH_RUN__, BSP_CPU_CODE_ADDRESS(__GSU_T4_BRUSH_BLOCK_PATCH_LOAD__), __GSU_T4_BRUSH_BLOCK_PATCH_SIZE__
        BSP_STATIC_COPY __GSU_T4_BRUSH_FINAL_PATCH_RUN__, BSP_CPU_CODE_ADDRESS(__GSU_T4_BRUSH_FINAL_PATCH_LOAD__), __GSU_T4_BRUSH_FINAL_PATCH_SIZE__
        BSP_STATIC_COPY __GSU_T4_BRUSH_FALLBACK_PATCH_RUN__, BSP_CPU_CODE_ADDRESS(__GSU_T4_BRUSH_FALLBACK_PATCH_LOAD__), __GSU_T4_BRUSH_FALLBACK_PATCH_SIZE__
        lda     #$0001
        sta     texture_renderer_code_variant
        rts

EnsureGeneralTextureRendererCode:
        RW_assume a16i16
        lda     texture_renderer_code_variant
.if .defined(PLAYABLE_FLAT_BRUSH_CODE) && (BSP_RENDER_SCALE = 2)
        beq     @VerifyGeneral
        cmp     #FLAT_BRUSH_CODE_VARIANT
        bne     @Restore
        jmp     RestoreFlatBrushCode
@VerifyGeneral:
.else
        bne     @Restore
.endif
        ; A brush reload can clear the variant while the mixed slot remains.
        lda     f:GSU_RENDER_BASE+GSU_T4_SAMPLE_CODE_OFFSET
        cmp     #$A13D
        beq     @Restore
        ; The AUX world hook survives a brush reload that clears the variant,
        ; even when both mutable slots currently contain their default roles.
        lda     f:TextureEndpointBatchMathCall+2
        cmp     #.loword(T4PrepareReplayBounds)
        beq     @Restore
        ; A variant reset can also leave the world loader resident.
        lda     f:GSU_RENDER_BASE+.loword(T4TextureEndpointDepthBatch)
        cmp     #$AA3D
        beq     @Restore
        rts
@Restore:
        jsr     RestoreBrushPVSCode
        lda     #.loword(ConvexProjectComponent)
        sta     f:TextureShadeProjectRightCall+2
        sta     f:TextureShadeProjectUpCall+2
        BSP_STATIC_COPY __GSU_T4_PROJECTION_CODE_RUN__, BSP_CPU_CODE_ADDRESS(__GSUCODE_LOAD__)+(__GSU_T4_PROJECTION_CODE_RUN__-__GSUCODE_RUN__), __GSU_T4_PROJECTION_CODE_SIZE__
        lda     #.loword(TextureEndpointBatchMath)
        sta     f:TextureEndpointBatchMathCall+2
        sta     f:BrushArbiterDepthMathCall+2
        lda     #.loword(TextureEndpointLoadRow)
        sta     f:TextureEndpointLoadRowCall+2
        lda     #.loword(TextureEndpointDepthBatch)
        sta     f:BrushArbiterDepthBatchCall+1
        BSP_STATIC_COPY __GSU_T4_REPLAY_BOUNDS_LOAD_PATCH_RUN__, BSP_CPU_CODE_ADDRESS(__GSU_AUX_CODE_LOAD__)+(__GSU_T4_REPLAY_BOUNDS_LOAD_PATCH_RUN__-__GSU_AUX_CODE_RUN__), __GSU_T4_REPLAY_BOUNDS_LOAD_PATCH_SIZE__
        BSP_STATIC_COPY __GSU_T4_REPLAY_BOUNDS_MATH_CODE_RUN__, BSP_CPU_CODE_ADDRESS(__GSU_AUX_CODE_LOAD__)+(__GSU_T4_REPLAY_BOUNDS_MATH_CODE_RUN__-__GSU_AUX_CODE_RUN__), __GSU_T4_REPLAY_BOUNDS_MATH_CODE_SIZE__
        BSP_STATIC_COPY __GSU_T4_REPLAY_BOUNDS_CODE_RUN__, BSP_CPU_CODE_ADDRESS(__GSUCODE_LOAD__)+(__GSU_T4_REPLAY_BOUNDS_CODE_RUN__-__GSUCODE_RUN__), __GSU_T4_REPLAY_BOUNDS_CODE_SIZE__
.if BSP_RENDER_SCALE = 2
        lda     #.loword(WorldLightmapRasterTarget)
        sta     f:WorldLightmapRasterCall+2
.endif
        BSP_STATIC_COPY __GSU_T4_RASTER_CODE_RUN__, BSP_CPU_CODE_ADDRESS(__GSUCODE_LOAD__)+(__GSU_T4_RASTER_CODE_RUN__-__GSUCODE_RUN__), __GSU_T4_RASTER_CODE_SIZE__
        BSP_STATIC_COPY __GSU_T4_EDGE_PATCH_RUN__, BSP_CPU_CODE_ADDRESS(__GSUCODE_LOAD__)+(__GSU_T4_EDGE_PATCH_RUN__-__GSUCODE_RUN__), __GSU_T4_EDGE_PATCH_SIZE__
        BSP_STATIC_COPY __GSU_T4_EDGE_DEPTH_CODE_RUN__, BSP_CPU_CODE_ADDRESS(__GSUCODE_LOAD__)+(__GSU_T4_EDGE_DEPTH_CODE_RUN__-__GSUCODE_RUN__), __GSU_T4_EDGE_DEPTH_CODE_SIZE__
        BSP_STATIC_COPY __GSU_T4_STAGE_CODE_RUN__, BSP_CPU_CODE_ADDRESS(__GSUCODE_LOAD__)+(__GSU_T4_STAGE_CODE_RUN__-__GSUCODE_RUN__), __GSU_T4_STAGE_CODE_SIZE__
        BSP_STATIC_COPY __GSU_T4_EDGE_OUTPUT_CODE_RUN__, BSP_CPU_CODE_ADDRESS(__GSUCODE_LOAD__)+(__GSU_T4_EDGE_OUTPUT_CODE_RUN__-__GSUCODE_RUN__), __GSU_T4_EDGE_OUTPUT_CODE_SIZE__
        BSP_STATIC_COPY __GSU_T4_FACE_DISPATCH_PATCH_RUN__, BSP_CPU_CODE_ADDRESS(__GSUCODE_LOAD__)+(__GSU_T4_FACE_DISPATCH_PATCH_RUN__-__GSUCODE_RUN__), __GSU_T4_FACE_DISPATCH_PATCH_SIZE__
        BSP_STATIC_COPY __GSU_T4_BLOCK_SELECT_CODE_RUN__, BSP_CPU_CODE_ADDRESS(__GSUCODE_LOAD__)+(__GSU_T4_BLOCK_SELECT_CODE_RUN__-__GSUCODE_RUN__), __GSU_T4_BLOCK_SELECT_CODE_SIZE__
        BSP_STATIC_COPY __GSU_T4_SAMPLE_WRAP_CODE_RUN__, BSP_CPU_CODE_ADDRESS(__GSUCODE_LOAD__)+(__GSU_T4_SAMPLE_WRAP_CODE_RUN__-__GSUCODE_RUN__), __GSU_T4_SAMPLE_WRAP_CODE_SIZE__
        BSP_STATIC_COPY __GSU_T4_SAMPLE_CODE_RUN__, BSP_CPU_CODE_ADDRESS(__GSUCODE_LOAD__)+(__GSU_T4_SAMPLE_CODE_RUN__-__GSUCODE_RUN__), __GSU_T4_SAMPLE_CODE_SIZE__
        BSP_STATIC_COPY __GSU_T4_SAMPLE_SELECT_PATCH_RUN__, BSP_CPU_CODE_ADDRESS(__GSUCODE_LOAD__)+(__GSU_T4_SAMPLE_SELECT_PATCH_RUN__-__GSUCODE_RUN__), __GSU_T4_SAMPLE_SELECT_PATCH_SIZE__
        BSP_STATIC_COPY __GSU_T4_SAMPLE_AUX_CODE_RUN__, BSP_CPU_CODE_ADDRESS(__GSUCODE_LOAD__)+(__GSU_T4_SAMPLE_AUX_CODE_RUN__-__GSUCODE_RUN__), __GSU_T4_SAMPLE_AUX_CODE_SIZE__
        BSP_STATIC_COPY __GSU_T4_BRUSH_FRAGMENT_PATCH_RUN__, BSP_CPU_CODE_ADDRESS(__GSU_BRUSH_CODE_LOAD__)+(__GSU_T4_BRUSH_FRAGMENT_PATCH_RUN__-__GSU_BRUSH_CODE_RUN__), __GSU_T4_BRUSH_FRAGMENT_PATCH_SIZE__
        BSP_STATIC_COPY __GSU_T4_BRUSH_WORLD_PATCH_RUN__, BSP_CPU_CODE_ADDRESS(__GSU_BRUSH_CODE_LOAD__)+(__GSU_T4_BRUSH_WORLD_PATCH_RUN__-__GSU_BRUSH_CODE_RUN__), __GSU_T4_BRUSH_WORLD_PATCH_SIZE__
        BSP_STATIC_COPY __GSU_T4_BRUSH_SAMPLE_PATCH_RUN__, BSP_CPU_CODE_ADDRESS(__GSU_BRUSH_CODE_LOAD__)+(__GSU_T4_BRUSH_SAMPLE_PATCH_RUN__-__GSU_BRUSH_CODE_RUN__), __GSU_T4_BRUSH_SAMPLE_PATCH_SIZE__
        BSP_STATIC_COPY __GSU_T4_BRUSH_RASTER_PATCH_RUN__, BSP_CPU_CODE_ADDRESS(__GSU_BRUSH_CODE_LOAD__)+(__GSU_T4_BRUSH_RASTER_PATCH_RUN__-__GSU_BRUSH_CODE_RUN__), __GSU_T4_BRUSH_RASTER_PATCH_SIZE__
        BSP_STATIC_COPY __GSU_T4_BRUSH_MODE_PATCH_RUN__, BSP_CPU_CODE_ADDRESS(__GSU_BRUSH_CODE_LOAD__)+(__GSU_T4_BRUSH_MODE_PATCH_RUN__-__GSU_BRUSH_CODE_RUN__), __GSU_T4_BRUSH_MODE_PATCH_SIZE__
        BSP_STATIC_COPY __GSU_T4_BRUSH_PREP_PATCH_RUN__, BSP_CPU_CODE_ADDRESS(__GSU_BRUSH_CODE_LOAD__)+(__GSU_T4_BRUSH_PREP_PATCH_RUN__-__GSU_BRUSH_CODE_RUN__), __GSU_T4_BRUSH_PREP_PATCH_SIZE__
        BSP_STATIC_COPY __GSU_T4_BRUSH_ROW_PATCH_RUN__, BSP_CPU_CODE_ADDRESS(__GSU_BRUSH_CODE_LOAD__)+(__GSU_T4_BRUSH_ROW_PATCH_RUN__-__GSU_BRUSH_CODE_RUN__), __GSU_T4_BRUSH_ROW_PATCH_SIZE__
        BSP_STATIC_COPY __GSU_T4_BRUSH_MATERIAL_PATCH_RUN__, BSP_CPU_CODE_ADDRESS(__GSU_BRUSH_CODE_LOAD__)+(__GSU_T4_BRUSH_MATERIAL_PATCH_RUN__-__GSU_BRUSH_CODE_RUN__), __GSU_T4_BRUSH_MATERIAL_PATCH_SIZE__
        BSP_STATIC_COPY __GSU_T4_BRUSH_FORWARD_PATCH_RUN__, BSP_CPU_CODE_ADDRESS(__GSU_BRUSH_CODE_LOAD__)+(__GSU_T4_BRUSH_FORWARD_PATCH_RUN__-__GSU_BRUSH_CODE_RUN__), __GSU_T4_BRUSH_FORWARD_PATCH_SIZE__
        BSP_STATIC_COPY __GSU_T4_BRUSH_REVERSE_PATCH_RUN__, BSP_CPU_CODE_ADDRESS(__GSU_BRUSH_CODE_LOAD__)+(__GSU_T4_BRUSH_REVERSE_PATCH_RUN__-__GSU_BRUSH_CODE_RUN__), __GSU_T4_BRUSH_REVERSE_PATCH_SIZE__
        BSP_STATIC_COPY __GSU_T4_BRUSH_SPAN_PATCH_RUN__, BSP_CPU_CODE_ADDRESS(__GSU_BRUSH_CODE_LOAD__)+(__GSU_T4_BRUSH_SPAN_PATCH_RUN__-__GSU_BRUSH_CODE_RUN__), __GSU_T4_BRUSH_SPAN_PATCH_SIZE__
        BSP_STATIC_COPY __GSU_T4_BRUSH_BLOCK_PATCH_RUN__, BSP_CPU_CODE_ADDRESS(__GSU_BRUSH_CODE_LOAD__)+(__GSU_T4_BRUSH_BLOCK_PATCH_RUN__-__GSU_BRUSH_CODE_RUN__), __GSU_T4_BRUSH_BLOCK_PATCH_SIZE__
        BSP_STATIC_COPY __GSU_T4_BRUSH_FINAL_PATCH_RUN__, BSP_CPU_CODE_ADDRESS(__GSU_BRUSH_CODE_LOAD__)+(__GSU_T4_BRUSH_FINAL_PATCH_RUN__-__GSU_BRUSH_CODE_RUN__), __GSU_T4_BRUSH_FINAL_PATCH_SIZE__
        BSP_STATIC_COPY __GSU_T4_BRUSH_FALLBACK_PATCH_RUN__, BSP_CPU_CODE_ADDRESS(__GSU_BRUSH_CODE_LOAD__)+(__GSU_T4_BRUSH_FALLBACK_PATCH_RUN__-__GSU_BRUSH_CODE_RUN__), __GSU_T4_BRUSH_FALLBACK_PATCH_SIZE__
        stz     texture_renderer_code_variant
        rts

.include "fly_full/BrushPVS.s"
.if .defined(PLAYABLE_FLAT_BRUSH_CODE) && (BSP_RENDER_SCALE = 2)
.include "FlatBrushCode.s"
.endif
RenderFlatRenderer:
        RW_forced a8i16
        lda     #GSU_LOGICAL_SCBR
        sta     FX3_SCBR
        RW_forced a16i16
        ldx     #.loword(GSU_Code)
RenderRendererReady:
.if .defined(PLAYABLE_RESIDENT_WORLD) && (BSP_RENDER_SCALE = 2)
        lda     #0
        sta     f:GSU_DATA_BASE+GSU_RESIDENT_WORLD_STATUS
.endif
        ; Flat output owns both the phase-overlaid Q12 mirror and the hidden
        ; texture-row helper. Restore them on the next textured transition.
        stz     texture_phase_overlay_valid
 .ifdef PLAYABLE_SPRITE_STREAM
        jsr     SpriteStreamPrepareRenderer
 .endif
        RW_forced a8i16
        FX3_JOB_START FX3_SCMR_128X128_4BPP_ROM, x, set
.ifdef PLAYABLE_SPRITE_STREAM
        ; Flat output also needs the refill fence before later frame staging.
        jsr     SpriteStreamJoinRenderer
.endif
        RW_forced a16i16
        inc     render_counter
        rts
