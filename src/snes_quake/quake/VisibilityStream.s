; The selector's STOP owns the existing bank-$71 face bitset exclusively.
.ifdef PLAYABLE_VISIBILITY_STREAM
.import VisibilityStreamResume:far
.assert .bankbyte(VisibilityStreamResume) = $70, lderror, "Visibility continuation must stay in GSU RAM"
.assert VISIBILITY_STREAM_ROW_COUNT = BSP_WORLD_VIS_LEAF_COUNT + 1, error, "Visibility stream leaf count changed"
.assert VISIBILITY_STREAM_ROW_BYTES = BSP_WORLD_FACE_BITSET_BYTES, error, "Visibility stream width changed"

.segment "LORAM"
VisibilityStreamMetadata: .res 4
VisibilityStreamUploads: .res 2

.segment "CODE"
VisibilityStreamJoinSelector:
        php
        RW_forced a16i16
        pha
        phy
        phb
        phk
        plb
@Wait:
.ifdef PLAYABLE_SELECTOR_COOP
        lda     active_render_scale
        cmp     #2
        bne     @PlainWait
@Queued:
        ldx     FX3_R15
        beq     @Ready
        lda     f:QC_INPUT_TICK
        cmp     f:quakec_last_tick
        beq     @Queued
.if .defined(PLAYABLE_E1M1_PREFETCH_GAMEPLAY_CODE) && .defined(PLAYABLE_MAP_ID)
        jsl     ServiceOrDeferSelectorGameplay
        bcs     @PlainWait
.else
        ; The selector owns its scratch until STOP.
        jsl     QuakeCService
.endif
        bra     @Queued
@PlainWait:
.endif
        FX3_JOB_JOIN
.ifdef PLAYABLE_SELECTOR_COOP
@Ready:
.endif
        lda     f:GSU_DATA_BASE+GSU_TELEMETRY_MAGIC
        cmp     #VISIBILITY_STREAM_REQUEST
        bne     @Done
        jsr     VisibilityStreamFill
        ldx     #.loword(VisibilityStreamResume)
        stx     FX3_R15
        bra     @Wait
@Done:
        plb
        ply
        pla
        plp
        rts

VisibilityStreamFill:
        RW_assume a16i16
        lda     f:GSU_DATA_BASE+GSU_TELEMETRY_LEAF
        cmp     #VISIBILITY_STREAM_ROW_COUNT
        bcc     :+
        RW      a8
        lda     #9
        jmp     PlayableArchiveFatal
:
        RW_forced a16i16
        stz     playable_archive_seek+2
        .repeat VISIBILITY_STREAM_SHIFT
        asl
        rol     playable_archive_seek+2
        .endrepeat
        clc
        adc     #.loword(VISIBILITY_STREAM_SEEK)
        sta     playable_archive_seek
        lda     playable_archive_seek+2
        adc     #.hiword(VISIBILITY_STREAM_SEEK)
        sta     playable_archive_seek+2
        RW_forced a8i16
        lda     playable_archive_busy
        beq     :+
        lda     #5
        jmp     PlayableArchiveFatal
:
        inc     playable_archive_busy
        jsr     PlayableEnsureArchive
        jsr     PlayableSeekArchive
        ldx     #0
@Metadata:
        lda     f:$002001
        sta     a:VisibilityStreamMetadata,x
        eor     f:$002001
        cmp     #$FF
        bne     VisibilityStreamBadPair
        inx
        cpx     #4
        bne     @Metadata
        ldx     #0
        ; DBR mirrors MSU MMIO. Check each byte pair and test the row
        ; bound once per group, followed by the exact tail.
.macro COPY_VISIBILITY_PAIR
        lda     a:$2001
        sta     f:GSU_WORLD_VISIBILITY,x
        eor     a:$2001
        inc
        bne     VisibilityStreamBadPair
        inx
.endmacro
        .if VISIBILITY_STREAM_ROW_BYTES >= 4
@Group:
          .repeat 4
        COPY_VISIBILITY_PAIR
          .endrepeat
        cpx     #(VISIBILITY_STREAM_ROW_BYTES & $FFFC)
        bne     @Group
        .endif
        .repeat VISIBILITY_STREAM_ROW_BYTES .mod 4
        COPY_VISIBILITY_PAIR
        .endrepeat
        stz     playable_archive_busy
        RW_forced a16i16
        lda     VisibilityStreamMetadata
        sta     f:GSU_DATA_BASE+GSU_TELEMETRY_ENCODED_BYTES
        lda     VisibilityStreamMetadata+2
        sta     f:GSU_DATA_BASE+GSU_TELEMETRY_FACE_COUNT
        inc     VisibilityStreamUploads
        rts

VisibilityStreamBadPair:
        RW_forced a8i16
        lda     #3
        jmp     PlayableArchiveFatal

.if .defined(PLAYABLE_E1M1_PREFETCH_GAMEPLAY_CODE) && .defined(PLAYABLE_MAP_ID)
.pushseg
.segment "BSP_CPU_WALK_RESUME"
; Let the painter service the due step and retain any pending live tap.
; The frame pipeline services the step if it discards the command.
ServiceOrDeferSelectorGameplay:
        RW_assume a16i16
        lda     f:quakec_last_tick
        inc
        beq     @Service
        cmp     deferred_gameplay_tick
        beq     @Deferred
        lda     video_active
        beq     @Service
        lda     deferred_gameplay_tick
        ora     render_coverage_mode
        ora     runtime_menu_open
        ora     runtime_menu_release_gate
        ora     quake_restart_pending
        ora     playable_switch_pending
        ora     qc_sample_weapon
        ora     f:quakec_fault
.ifdef QC_INTERMISSION_COUNT
        ora     f:intermission_phase
.endif
.ifdef QC_HEALTH_COUNT
        ora     pickup_pixels_dirty
.endif
.ifdef PLAYABLE_WEAPON_OBJ
        ora     weapon_obj_menu_pending
        ora     f:axe_selected
.endif
        bne     @Service
.if .defined(PLAYABLE_WEAPON_OBJ) && (.defined(QC_NAIL_COUNT) || .defined(QC_CAMPAIGN_ITEMS))
        lda     f:ShotgunPlayer+QC_FIELD_WEAPON
        cmp     #64
        bne     @Service
.endif
        lda     demo_schedule_revision
        cmp     render_demo_epoch
        bne     @Service
        lda     render_camera+10
        dec
        and     #$00fe
        cmp     #(RUNTIME_MENU_TECHNIQUE_FACE_COLORS-1)
        bne     @Service
        lda     f:quakec_last_tick
        inc
        cmp     deferred_live_input_tick
        beq     @Record
        ldx     deferred_live_input_tick
        bne     @Service
        jsl     GameplayCaptureDeferredLiveInput
@Record:
        sta     deferred_gameplay_tick
@Deferred:
        sec
        rtl
@Service:
        jsl     QuakeCService
        clc
        rtl
.popseg
.endif
.endif
