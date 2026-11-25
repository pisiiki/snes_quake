; Freeze translation-only entrance geometry independently of the lift/button.
QuakeCStageEntranceVisuals:
        RW_assume a16i16
.ifdef QC_SECRET_DOOR_COUNT
        lda     f:qc_sd_revision
        sta     f:render_secret_revision
        ldx     #2*(QC_MOVING_DOOR_POSES-1)
@SecretPose:
        lda     f:qc_sd_pose,x
        sta     f:render_secret_poses,x
        dex
        dex
        bpl     @SecretPose
.endif
.ifdef QC_EXIT_MOVER_COUNT
        lda     f:quakec_exit_pose_word
        sta     f:render_exit_pose_word
  .if QC_EXIT_MOVER_COUNT > 8
        lda     f:quakec_exit_pose_word_high
        sta     f:render_exit_pose_word_high
  .endif
.endif
.if QC_ENTRANCE_COUNT > 0
        lda     f:quakec_entrance_pose
        cmp     #QC_ENTRANCE_STEPS+1
        bcs     @Invalid
        asl
        tax
        lda     f:QuakeCEntrance0LocalVariants,x
        sta     f:render_entrance_variants
        lda     f:quakec_entrance_pose+2
        cmp     #QC_ENTRANCE_STEPS+1
        bcs     @Invalid
        asl
        tax
        lda     f:QuakeCEntrance1LocalVariants,x
        sta     f:render_entrance_variants+2
        rtl
@Invalid:
        lda     #$8351
        sta     f:quakec_fault
        lda     #0
        sta     f:render_entrance_variants
        sta     f:render_entrance_variants+2
        rtl
.else
        rtl
.endif

.ifdef QC_EXIT_MOVER_COUNT
; One byte per inline model fits the command gap after grunt poses.
; A zero slot inherits the packed replay's local variant.
QuakeCWriteExitVisuals:
        RW_assume a16i16
  .ifdef PLAYABLE_PACKET_VIEW_REUSE
        ; Token and link caches retain resolved geometry between jobs.
        ; A different mover pose invalidates those caches, even if the
        ; camera and selector packet are unchanged.
        lda     f:render_exit_pose_word
        cmp     f:uploaded_exit_pose_word
        bne     @Changed
    .ifdef QC_SECRET_DOOR_COUNT
        lda     f:render_secret_revision
        cmp     f:uploaded_secret_revision
        bne     @Changed
    .endif
    .if QC_EXIT_MOVER_COUNT > 8
        lda     f:render_exit_pose_word_high
        cmp     f:uploaded_exit_pose_word_high
        bne     @Changed
    .endif
    .ifdef exit_variant_shadow
        lda     f:exit_variant_shadow_valid
        beq     @ClearTable
        ; The renderer always receives the complete table, even when the
        ; previous job or scale installation reused its cartridge RAM.
        phb
        ldx     #.loword(exit_variant_shadow)
        ldy     #GSU_ENTRANCE_VARIANTS_OFFSET
        lda     #GSU_ENTRANCE_VARIANTS_BYTES-1
        mvn     #^exit_variant_shadow, #^GSU_DATA_BASE
        plb
        rtl
    .else
        bra     @ClearTable
    .endif
@Changed:
        lda     #0
        sta     f:GSU_DATA_BASE+GSU_BRUSH_MERGE_CACHE_COUNT
    .if .defined(PLAYABLE_RESIDENT_WORLD) && (BSP_RENDER_SCALE = 2) && BSP_ALIAS_LIVE_POSES
        sta     f:GSU_DATA_BASE+GSU_RESIDENT_WORLD_STATUS
    .endif
        lda     f:render_exit_pose_word
        sta     f:uploaded_exit_pose_word
    .ifdef QC_SECRET_DOOR_COUNT
        lda     f:render_secret_revision
        sta     f:uploaded_secret_revision
    .endif
    .if QC_EXIT_MOVER_COUNT > 8
        lda     f:render_exit_pose_word_high
        sta     f:uploaded_exit_pose_word_high
    .endif
@ClearTable:
  .endif
        ldx     #GSU_ENTRANCE_VARIANTS_BYTES-2
        lda     #0
@Clear:
        sta     f:GSU_DATA_BASE+GSU_ENTRANCE_VARIANTS_OFFSET,x
        dex
        dex
        bpl     @Clear
  .if QC_ENTRANCE_COUNT > 0
        RW_forced a8i16
        lda     f:render_entrance_variants
        inc
        sta     f:GSU_DATA_BASE+GSU_ENTRANCE_VARIANTS_OFFSET+1
        lda     f:render_entrance_variants+2
        inc
        sta     f:GSU_DATA_BASE+GSU_ENTRANCE_VARIANTS_OFFSET+2
        RW_forced a16i16
  .endif
        ldy     #0
.ifndef QC_E1M3_GOLD_KEY
        lda     f:render_exit_pose_word
.endif
@Mover:
.ifdef QC_E1M3_GOLD_KEY
        tyx
        lda     f:QCE1M3VisualShift,x
        cmp     #16
        bcc     @Low
        sbc     #16
        tax
        lda     f:render_exit_pose_word_high
        bra     @Shift
@Low:
        tax
        lda     f:render_exit_pose_word
@Shift:
        cpx     #0
        beq     @Variant
:       lsr
        dex
        bne     :-
@Variant:
.else
        pha
.endif
        and     #3
        asl
        sta     f:render_exit_pose_index
        tya
        asl
        asl
        ora     f:render_exit_pose_index
        tax
        lda     f:QCExitLocalVariants,x
        pha
        tyx
        lda     f:QCExitVariantOffsets,x
        tax
        pla
        RW_forced a8i16
        sta     f:GSU_DATA_BASE+GSU_ENTRANCE_VARIANTS_OFFSET,x
        RW_forced a16i16
  .ifndef QC_E1M3_GOLD_KEY
        pla
        lsr
        lsr
  .endif
        iny
        iny
  .if .defined(QC_E1M1_PLATFORM_FIRST)
        cpy     #QC_E1M1_PLATFORM_FIRST*2
        bcc     @Mover
        lda     f:render_exit_pose_word_high
        sta     f:GSU_DATA_BASE+GSU_PLATFORM_HEIGHTS
        and     #$00ff
        tax
        RW_forced a8i16
        lda     f:QCPlatform7LocalVariants,x
        sta     f:GSU_DATA_BASE+GSU_ENTRANCE_VARIANTS_OFFSET+7
        RW_forced a16i16
        lda     f:render_exit_pose_word_high
        xba
        and     #$00ff
        tax
        RW_forced a8i16
        lda     f:QCPlatform22LocalVariants,x
        sta     f:GSU_DATA_BASE+GSU_ENTRANCE_VARIANTS_OFFSET+22
        RW_forced a16i16
  .else
  .if QC_EXIT_MOVER_COUNT > 8 && !.defined(QC_E1M3_GOLD_KEY)
        cpy     #8*2
        bne     :+
        lda     f:render_exit_pose_word_high
:
  .endif
        cpy     #QC_EXIT_MOVER_COUNT*2
        bcc     @Mover
  .endif
  .ifdef QC_SECRET_DOOR_COUNT
        ldy     #0
@SecretDoor:
        tyx
        lda     f:render_secret_poses,x
        clc
        adc     f:QCSecretDoorVariantBases,x
        tax
        lda     f:QCSecretDoorVariants,x
        pha
        tyx
        lda     f:QCSecretModels,x
        tax
        pla
        RW_forced a8i16
        sta     f:GSU_DATA_BASE+GSU_ENTRANCE_VARIANTS_OFFSET,x
        RW_forced a16i16
        iny
        iny
        cpy     #2*QC_MOVING_DOOR_POSES
        bcc     @SecretDoor
  .endif
  .ifdef exit_variant_shadow
        ; Retain every byte of the ordinary expansion, including unused slots.
        phb
        ldx     #GSU_ENTRANCE_VARIANTS_OFFSET
        ldy     #.loword(exit_variant_shadow)
        lda     #GSU_ENTRANCE_VARIANTS_BYTES-1
        mvn     #^GSU_DATA_BASE, #^exit_variant_shadow
        plb
        lda     #1
        sta     f:exit_variant_shadow_valid
  .endif
        rtl
.endif
.include "Data/QuakeBSPEntranceVisuals.i"
