; The CPU only touches the resident state on either side of the GSU job.
; The mixed walker advances command 1 to 2 when it actually owns the draw.
PrepareResidentWorldCommand:
        RW_assume a16i16
        lda     #0
.if !BSP_ALIAS_LIVE_POSES
        sta     f:GSU_DATA_BASE+GSU_RESIDENT_WORLD_COMMAND
.endif
        cpx     #.loword(GSU_T4_BrushTextureLightmapCode)
        bne     @CheckFlat
@Eligible:
.if BSP_ALIAS_LIVE_POSES
        inc
@Publish:
        sta     f:GSU_DATA_BASE+GSU_RESIDENT_WORLD_COMMAND
        rts
.else
        lda     f:GSU_DATA_BASE+WEAPON_OBJ_CORE_FLAG
        cmp     f:GSU_DATA_BASE+GSU_RESIDENT_WORLD_MASK
        beq     @Arm
        sta     f:GSU_DATA_BASE+GSU_RESIDENT_WORLD_MASK
        lda     #0
        sta     f:GSU_DATA_BASE+GSU_RESIDENT_WORLD_STATUS
@Arm:
        lda     #1
        sta     f:GSU_DATA_BASE+GSU_RESIDENT_WORLD_COMMAND
        rts
.endif
@CheckFlat:
        jsl     CheckFlatResidentWorld
        bcs     @Eligible
.if BSP_ALIAS_LIVE_POSES
        bra     @Publish
.else
        rts
.endif

.pushseg
.segment "BSP_QUAKEC"
; Only the Flat brush entry installs this variant. Textures uses the same
; GSU entry after restoring the general overlay. Return A=0 in both cases.
CheckFlatResidentWorld:
        RW_assume a16i16
        lda     texture_renderer_code_variant
        eor     #FLAT_BRUSH_CODE_VARIANT
        beq     @Flat
        lda     #0
        sta     f:GSU_DATA_BASE+GSU_RESIDENT_WORLD_STATUS
        clc
        rtl
@Flat:
        sec
        rtl

FinishResidentWorldCommand:
        RW_assume a16i16
        lda     f:GSU_DATA_BASE+GSU_RESIDENT_WORLD_COMMAND
        cmp     #2
        bne     @Invalidate
        lda     f:GSU_TELEMETRY
        cmp     #$B529
        bne     @Invalidate
        lda     f:GSU_DATA_BASE+GSU_TURBULENCE_PRESENT_OFFSET
        bne     @Invalidate
        lda     f:GSU_DATA_BASE+GSU_SKY_FLAGS_OFFSET
        bit     #BSP_SKY_FLAG_PRESENTED
        bne     @Invalidate
        rtl
@Invalidate:
        lda     #0
        sta     f:GSU_DATA_BASE+GSU_RESIDENT_WORLD_STATUS
        rtl
.popseg
