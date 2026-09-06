; CPU-side renderer selection and phase-overlay lifetime management.

RenderStartRenderer:
SelectorStageRendererBegin:
        RW_forced a16i16
        inc     gsu_job_counter
        lda     render_coverage_mode
        beq     RenderProductionRenderer
        dec                             ; Diagnostic modes 1/2 select phases 0/1.
        sta     FX3_R0
        ldx     #.loword(GSU_CoverageCode)
        jmp     RenderRendererReady
RenderProductionRenderer:
        lda     render_camera+10
        and     #$00FF
        cmp     #BSP_TECHNIQUE_TEXTURED_LIGHTMAP
        bne     @GeneralTextureCode
        lda     technique4_specialized_path
        beq     @GeneralTextureCode
        ; The specialized code is qualified for generated demo snapshots. A
        ; free-flight command uses arbitrary camera geometry and must retain
        ; the general dynamic renderer until that broader domain is qualified.
        lda     render_demo_pose
        cmp     #$FFFF
        beq     @GeneralTextureCode
        jsr     EnsureTechnique4RendererCode
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
        jsr     EnsureGeneralTextureRendererCode
        jsr     SyncTextureColormap
        lda     render_camera+10
        cmp     #$0100
        bcc     @WorldOnlyRenderer
        and     #$00FF
        cmp     #RUNTIME_MENU_TECHNIQUE_TEXTURED_NONE
        beq     @BrushAlbedoRenderer
@BrushLightmapRenderer:
        ldx     #.loword(GSU_BrushTextureLightmapCode)
        bra     RenderTextureRenderer
@BrushAlbedoRenderer:
        ldx     #.loword(GSU_BrushTextureCode)
        bra     RenderTextureRenderer
@WorldOnlyRenderer:
        cmp     #RUNTIME_MENU_TECHNIQUE_TEXTURED_NONE
        beq     @WorldAlbedoRenderer
        ldx     #.loword(GSU_TextureLightmapCode)
        bra     RenderTextureRenderer
@WorldAlbedoRenderer:
        ldx     #.loword(GSU_TextureCode)
RenderTextureRenderer:
        RW_forced a8i16
        stz     FX3_SCBR
        FX3_JOB_START FX3_SCMR_128X128_8BPP_ROM, x, set
        BSP_SOUND_FX3_JOB_JOIN
        stz     FX3_SCMR
        RW_forced a16i16
        inc     render_counter
        rts

EnsureBrushCode:
        RW_assume a16i16
        lda     brush_code_valid
        bne     @Ready
        BSP_STATIC_COPY __GSU_BRUSH_CODE_RUN__, __GSU_BRUSH_CODE_LOAD__, __GSU_BRUSH_CODE_SIZE__
        lda     #$0001
        sta     brush_code_valid
        ; Reloading ROM63 also restores every sparse T4 brush window.
        stz     texture_renderer_code_variant
@Ready:
        rts

; Fly tracing is not part of the ordered/demo boot image. Install it only at
; the user-visible mode transition, before any fly render can start.
EnsureFlyAliasCode:
        RW_assume a16i16
        BSP_STATIC_COPY __GSU_ALIAS_FLY_CODE_RUN__, __GSU_ALIAS_FLY_CODE_LOAD__, __GSU_ALIAS_FLY_CODE_SIZE__
        rts

EnsureTechnique4RendererCode:
        RW_assume a16i16
        lda     texture_renderer_code_variant
        beq     @Install
        rts
@Install:
        BSP_STATIC_COPY __GSU_T4_RASTER_CODE_RUN__, __GSU_T4_RASTER_CODE_LOAD__+BSP_SOUND_CPU_MIRROR_DELTA, __GSU_T4_RASTER_CODE_SIZE__
        BSP_STATIC_COPY __GSU_T4_EDGE_PATCH_RUN__, __GSU_T4_EDGE_PATCH_LOAD__+BSP_SOUND_CPU_MIRROR_DELTA, __GSU_T4_EDGE_PATCH_SIZE__
        BSP_STATIC_COPY __GSU_T4_EDGE_DEPTH_CODE_RUN__, __GSU_T4_EDGE_DEPTH_CODE_LOAD__+BSP_SOUND_CPU_MIRROR_DELTA, __GSU_T4_EDGE_DEPTH_CODE_SIZE__
        BSP_STATIC_COPY __GSU_T4_STAGE_CODE_RUN__, __GSU_T4_STAGE_CODE_LOAD__+BSP_SOUND_CPU_MIRROR_DELTA, __GSU_T4_STAGE_CODE_SIZE__
        BSP_STATIC_COPY __GSU_T4_EDGE_OUTPUT_CODE_RUN__, __GSU_T4_EDGE_OUTPUT_CODE_LOAD__+BSP_SOUND_CPU_MIRROR_DELTA, __GSU_T4_EDGE_OUTPUT_CODE_SIZE__
        BSP_STATIC_COPY __GSU_T4_FACE_DISPATCH_PATCH_RUN__, __GSU_T4_FACE_DISPATCH_PATCH_LOAD__+BSP_SOUND_CPU_MIRROR_DELTA, __GSU_T4_FACE_DISPATCH_PATCH_SIZE__
        BSP_STATIC_COPY __GSU_T4_BLOCK_SELECT_CODE_RUN__, __GSU_T4_BLOCK_SELECT_CODE_LOAD__+BSP_SOUND_CPU_MIRROR_DELTA, __GSU_T4_BLOCK_SELECT_CODE_SIZE__
        BSP_STATIC_COPY __GSU_T4_SAMPLE_WRAP_CODE_RUN__, __GSU_T4_SAMPLE_WRAP_CODE_LOAD__+BSP_SOUND_CPU_MIRROR_DELTA, __GSU_T4_SAMPLE_WRAP_CODE_SIZE__
        BSP_STATIC_COPY __GSU_T4_SAMPLE_CODE_RUN__, __GSU_T4_SAMPLE_CODE_LOAD__+BSP_SOUND_CPU_MIRROR_DELTA, __GSU_T4_SAMPLE_CODE_SIZE__
        BSP_STATIC_COPY __GSU_T4_SAMPLE_SELECT_PATCH_RUN__, __GSU_T4_SAMPLE_SELECT_PATCH_LOAD__+BSP_SOUND_CPU_MIRROR_DELTA, __GSU_T4_SAMPLE_SELECT_PATCH_SIZE__
        BSP_STATIC_COPY __GSU_T4_SAMPLE_AUX_CODE_RUN__, __GSU_T4_SAMPLE_AUX_CODE_LOAD__+BSP_SOUND_CPU_MIRROR_DELTA, __GSU_T4_SAMPLE_AUX_CODE_SIZE__
        BSP_STATIC_COPY __GSU_T4_BRUSH_FRAGMENT_PATCH_RUN__, __GSU_T4_BRUSH_FRAGMENT_PATCH_LOAD__+BSP_SOUND_CPU_MIRROR_DELTA, __GSU_T4_BRUSH_FRAGMENT_PATCH_SIZE__
        BSP_STATIC_COPY __GSU_T4_BRUSH_WORLD_PATCH_RUN__, __GSU_T4_BRUSH_WORLD_PATCH_LOAD__+BSP_SOUND_CPU_MIRROR_DELTA, __GSU_T4_BRUSH_WORLD_PATCH_SIZE__
        BSP_STATIC_COPY __GSU_T4_BRUSH_SAMPLE_PATCH_RUN__, __GSU_T4_BRUSH_SAMPLE_PATCH_LOAD__+BSP_SOUND_CPU_MIRROR_DELTA, __GSU_T4_BRUSH_SAMPLE_PATCH_SIZE__
        BSP_STATIC_COPY __GSU_T4_BRUSH_RASTER_PATCH_RUN__, __GSU_T4_BRUSH_RASTER_PATCH_LOAD__+BSP_SOUND_CPU_MIRROR_DELTA, __GSU_T4_BRUSH_RASTER_PATCH_SIZE__
        BSP_STATIC_COPY __GSU_T4_BRUSH_MODE_PATCH_RUN__, __GSU_T4_BRUSH_MODE_PATCH_LOAD__+BSP_SOUND_CPU_MIRROR_DELTA, __GSU_T4_BRUSH_MODE_PATCH_SIZE__
        BSP_STATIC_COPY __GSU_T4_BRUSH_PREP_PATCH_RUN__, __GSU_T4_BRUSH_PREP_PATCH_LOAD__+BSP_SOUND_CPU_MIRROR_DELTA, __GSU_T4_BRUSH_PREP_PATCH_SIZE__
        BSP_STATIC_COPY __GSU_T4_BRUSH_ROW_PATCH_RUN__, __GSU_T4_BRUSH_ROW_PATCH_LOAD__+BSP_SOUND_CPU_MIRROR_DELTA, __GSU_T4_BRUSH_ROW_PATCH_SIZE__
        BSP_STATIC_COPY __GSU_T4_BRUSH_MATERIAL_PATCH_RUN__, __GSU_T4_BRUSH_MATERIAL_PATCH_LOAD__+BSP_SOUND_CPU_MIRROR_DELTA, __GSU_T4_BRUSH_MATERIAL_PATCH_SIZE__
        BSP_STATIC_COPY __GSU_T4_BRUSH_FORWARD_PATCH_RUN__, __GSU_T4_BRUSH_FORWARD_PATCH_LOAD__+BSP_SOUND_CPU_MIRROR_DELTA, __GSU_T4_BRUSH_FORWARD_PATCH_SIZE__
        BSP_STATIC_COPY __GSU_T4_BRUSH_REVERSE_PATCH_RUN__, __GSU_T4_BRUSH_REVERSE_PATCH_LOAD__+BSP_SOUND_CPU_MIRROR_DELTA, __GSU_T4_BRUSH_REVERSE_PATCH_SIZE__
        BSP_STATIC_COPY __GSU_T4_BRUSH_SPAN_PATCH_RUN__, __GSU_T4_BRUSH_SPAN_PATCH_LOAD__+BSP_SOUND_CPU_MIRROR_DELTA, __GSU_T4_BRUSH_SPAN_PATCH_SIZE__
        BSP_STATIC_COPY __GSU_T4_BRUSH_BLOCK_PATCH_RUN__, __GSU_T4_BRUSH_BLOCK_PATCH_LOAD__+BSP_SOUND_CPU_MIRROR_DELTA, __GSU_T4_BRUSH_BLOCK_PATCH_SIZE__
        BSP_STATIC_COPY __GSU_T4_BRUSH_FINAL_PATCH_RUN__, __GSU_T4_BRUSH_FINAL_PATCH_LOAD__+BSP_SOUND_CPU_MIRROR_DELTA, __GSU_T4_BRUSH_FINAL_PATCH_SIZE__
        BSP_STATIC_COPY __GSU_T4_BRUSH_FALLBACK_PATCH_RUN__, __GSU_T4_BRUSH_FALLBACK_PATCH_LOAD__+BSP_SOUND_CPU_MIRROR_DELTA, __GSU_T4_BRUSH_FALLBACK_PATCH_SIZE__
        lda     #$0001
        sta     texture_renderer_code_variant
        rts

EnsureGeneralTextureRendererCode:
        RW_assume a16i16
        lda     texture_renderer_code_variant
        bne     @Restore
        rts
@Restore:
        BSP_STATIC_COPY __GSU_T4_RASTER_CODE_RUN__, __GSUCODE_LOAD__+BSP_SOUND_CPU_MIRROR_DELTA+(__GSU_T4_RASTER_CODE_RUN__-__GSUCODE_RUN__), __GSU_T4_RASTER_CODE_SIZE__
        BSP_STATIC_COPY __GSU_T4_EDGE_PATCH_RUN__, __GSUCODE_LOAD__+BSP_SOUND_CPU_MIRROR_DELTA+(__GSU_T4_EDGE_PATCH_RUN__-__GSUCODE_RUN__), __GSU_T4_EDGE_PATCH_SIZE__
        BSP_STATIC_COPY __GSU_T4_EDGE_DEPTH_CODE_RUN__, __GSUCODE_LOAD__+BSP_SOUND_CPU_MIRROR_DELTA+(__GSU_T4_EDGE_DEPTH_CODE_RUN__-__GSUCODE_RUN__), __GSU_T4_EDGE_DEPTH_CODE_SIZE__
        BSP_STATIC_COPY __GSU_T4_STAGE_CODE_RUN__, __GSUCODE_LOAD__+BSP_SOUND_CPU_MIRROR_DELTA+(__GSU_T4_STAGE_CODE_RUN__-__GSUCODE_RUN__), __GSU_T4_STAGE_CODE_SIZE__
        BSP_STATIC_COPY __GSU_T4_EDGE_OUTPUT_CODE_RUN__, __GSUCODE_LOAD__+BSP_SOUND_CPU_MIRROR_DELTA+(__GSU_T4_EDGE_OUTPUT_CODE_RUN__-__GSUCODE_RUN__), __GSU_T4_EDGE_OUTPUT_CODE_SIZE__
        BSP_STATIC_COPY __GSU_T4_FACE_DISPATCH_PATCH_RUN__, __GSUCODE_LOAD__+BSP_SOUND_CPU_MIRROR_DELTA+(__GSU_T4_FACE_DISPATCH_PATCH_RUN__-__GSUCODE_RUN__), __GSU_T4_FACE_DISPATCH_PATCH_SIZE__
        BSP_STATIC_COPY __GSU_T4_BLOCK_SELECT_CODE_RUN__, __GSUCODE_LOAD__+BSP_SOUND_CPU_MIRROR_DELTA+(__GSU_T4_BLOCK_SELECT_CODE_RUN__-__GSUCODE_RUN__), __GSU_T4_BLOCK_SELECT_CODE_SIZE__
        BSP_STATIC_COPY __GSU_T4_SAMPLE_WRAP_CODE_RUN__, __GSUCODE_LOAD__+BSP_SOUND_CPU_MIRROR_DELTA+(__GSU_T4_SAMPLE_WRAP_CODE_RUN__-__GSUCODE_RUN__), __GSU_T4_SAMPLE_WRAP_CODE_SIZE__
        BSP_STATIC_COPY __GSU_T4_SAMPLE_CODE_RUN__, __GSUCODE_LOAD__+BSP_SOUND_CPU_MIRROR_DELTA+(__GSU_T4_SAMPLE_CODE_RUN__-__GSUCODE_RUN__), __GSU_T4_SAMPLE_CODE_SIZE__
        BSP_STATIC_COPY __GSU_T4_SAMPLE_SELECT_PATCH_RUN__, __GSUCODE_LOAD__+BSP_SOUND_CPU_MIRROR_DELTA+(__GSU_T4_SAMPLE_SELECT_PATCH_RUN__-__GSUCODE_RUN__), __GSU_T4_SAMPLE_SELECT_PATCH_SIZE__
        BSP_STATIC_COPY __GSU_T4_SAMPLE_AUX_CODE_RUN__, __GSUCODE_LOAD__+BSP_SOUND_CPU_MIRROR_DELTA+(__GSU_T4_SAMPLE_AUX_CODE_RUN__-__GSUCODE_RUN__), __GSU_T4_SAMPLE_AUX_CODE_SIZE__
        BSP_STATIC_COPY __GSU_T4_BRUSH_FRAGMENT_PATCH_RUN__, __GSU_BRUSH_CODE_LOAD__+(__GSU_T4_BRUSH_FRAGMENT_PATCH_RUN__-__GSU_BRUSH_CODE_RUN__), __GSU_T4_BRUSH_FRAGMENT_PATCH_SIZE__
        BSP_STATIC_COPY __GSU_T4_BRUSH_WORLD_PATCH_RUN__, __GSU_BRUSH_CODE_LOAD__+(__GSU_T4_BRUSH_WORLD_PATCH_RUN__-__GSU_BRUSH_CODE_RUN__), __GSU_T4_BRUSH_WORLD_PATCH_SIZE__
        BSP_STATIC_COPY __GSU_T4_BRUSH_SAMPLE_PATCH_RUN__, __GSU_BRUSH_CODE_LOAD__+(__GSU_T4_BRUSH_SAMPLE_PATCH_RUN__-__GSU_BRUSH_CODE_RUN__), __GSU_T4_BRUSH_SAMPLE_PATCH_SIZE__
        BSP_STATIC_COPY __GSU_T4_BRUSH_RASTER_PATCH_RUN__, __GSU_BRUSH_CODE_LOAD__+(__GSU_T4_BRUSH_RASTER_PATCH_RUN__-__GSU_BRUSH_CODE_RUN__), __GSU_T4_BRUSH_RASTER_PATCH_SIZE__
        BSP_STATIC_COPY __GSU_T4_BRUSH_MODE_PATCH_RUN__, __GSU_BRUSH_CODE_LOAD__+(__GSU_T4_BRUSH_MODE_PATCH_RUN__-__GSU_BRUSH_CODE_RUN__), __GSU_T4_BRUSH_MODE_PATCH_SIZE__
        BSP_STATIC_COPY __GSU_T4_BRUSH_PREP_PATCH_RUN__, __GSU_BRUSH_CODE_LOAD__+(__GSU_T4_BRUSH_PREP_PATCH_RUN__-__GSU_BRUSH_CODE_RUN__), __GSU_T4_BRUSH_PREP_PATCH_SIZE__
        BSP_STATIC_COPY __GSU_T4_BRUSH_ROW_PATCH_RUN__, __GSU_BRUSH_CODE_LOAD__+(__GSU_T4_BRUSH_ROW_PATCH_RUN__-__GSU_BRUSH_CODE_RUN__), __GSU_T4_BRUSH_ROW_PATCH_SIZE__
        BSP_STATIC_COPY __GSU_T4_BRUSH_MATERIAL_PATCH_RUN__, __GSU_BRUSH_CODE_LOAD__+(__GSU_T4_BRUSH_MATERIAL_PATCH_RUN__-__GSU_BRUSH_CODE_RUN__), __GSU_T4_BRUSH_MATERIAL_PATCH_SIZE__
        BSP_STATIC_COPY __GSU_T4_BRUSH_FORWARD_PATCH_RUN__, __GSU_BRUSH_CODE_LOAD__+(__GSU_T4_BRUSH_FORWARD_PATCH_RUN__-__GSU_BRUSH_CODE_RUN__), __GSU_T4_BRUSH_FORWARD_PATCH_SIZE__
        BSP_STATIC_COPY __GSU_T4_BRUSH_REVERSE_PATCH_RUN__, __GSU_BRUSH_CODE_LOAD__+(__GSU_T4_BRUSH_REVERSE_PATCH_RUN__-__GSU_BRUSH_CODE_RUN__), __GSU_T4_BRUSH_REVERSE_PATCH_SIZE__
        BSP_STATIC_COPY __GSU_T4_BRUSH_SPAN_PATCH_RUN__, __GSU_BRUSH_CODE_LOAD__+(__GSU_T4_BRUSH_SPAN_PATCH_RUN__-__GSU_BRUSH_CODE_RUN__), __GSU_T4_BRUSH_SPAN_PATCH_SIZE__
        BSP_STATIC_COPY __GSU_T4_BRUSH_BLOCK_PATCH_RUN__, __GSU_BRUSH_CODE_LOAD__+(__GSU_T4_BRUSH_BLOCK_PATCH_RUN__-__GSU_BRUSH_CODE_RUN__), __GSU_T4_BRUSH_BLOCK_PATCH_SIZE__
        BSP_STATIC_COPY __GSU_T4_BRUSH_FINAL_PATCH_RUN__, __GSU_BRUSH_CODE_LOAD__+(__GSU_T4_BRUSH_FINAL_PATCH_RUN__-__GSU_BRUSH_CODE_RUN__), __GSU_T4_BRUSH_FINAL_PATCH_SIZE__
        BSP_STATIC_COPY __GSU_T4_BRUSH_FALLBACK_PATCH_RUN__, __GSU_BRUSH_CODE_LOAD__+(__GSU_T4_BRUSH_FALLBACK_PATCH_RUN__-__GSU_BRUSH_CODE_RUN__), __GSU_T4_BRUSH_FALLBACK_PATCH_SIZE__
        stz     texture_renderer_code_variant
        rts

RenderFlatRenderer:
        RW_forced a8i16
        lda     #GSU_LOGICAL_SCBR
        sta     FX3_SCBR
        RW_forced a16i16
        ldx     #.loword(GSU_Code)
RenderRendererReady:
        ; Flat output owns both the phase-overlaid Q12 mirror and the hidden
        ; texture-row helper. Restore them on the next textured transition.
        stz     texture_phase_overlay_valid
.if BSP_SOUND_ENABLED
        RW_forced a16i16
        jsr     QuakeSoundServiceMain
.endif
        RW_forced a8i16
        FX3_JOB_START FX3_SCMR_128X128_4BPP_ROM, x, set
        RW_forced a16i16
        inc     render_counter
        rts
