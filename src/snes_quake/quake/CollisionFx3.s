; DB is bank $7F. The caller has exclusive use of the stopped FX3.
; Gameplay entry and the textured renderer join leave PBR at $70.
.import CollisionFx3PlaneDistanceGSU:far
.macro FX3_PLANE_INPUTS
        lda     z:w_cache_coord_a
        sta     f:FX3_R1
        lda     z:w_cache_coord_b
        sta     f:FX3_R2
        lda     z:w_coeff_a
        sta     f:FX3_R6
        lda     z:w_coeff_b
        sta     f:FX3_R7
        lda     z:w_dist
        sta     f:FX3_R8
        lda     z:w_dist_high
        sta     f:FX3_R9
.endmacro

.macro FX3_PLANE_JOB wait_label
        lda     #.loword(CollisionFx3PlaneDistanceGSU)
        sta     f:FX3_R15
wait_label:
        lda     f:FX3_R15
        bne     wait_label
        lda     f:FX3_R4
        sta     z:w_eval
        lda     f:FX3_R0
        sta     z:w_eval_high
.endmacro

WalkPlaneDistanceFx3:
        FX3_PLANE_INPUTS
        RW      a8
        lda     #(.bankbyte(CollisionFx3PlaneDistanceGSU) & $7f)
        sta     f:FX3_PBR
        lda     #FX3_SCMR_128X128_8BPP_ROM
        sta     f:FX3_SCMR
        RW      a16
        FX3_PLANE_JOB @Wait
        RW      a8
        lda     #0
        sta     f:FX3_SCMR
        lda     #$70
        sta     f:FX3_PBR
        RW      a16
        rts

.pushseg
.segment "BSP_QUAKEC"
; The painter has released the GSU. Claim any due live tap before handing
; the completed frame to staging and the next normal gameplay service.
ServiceBakedFrameGameplay:
        RW_assume a16i16
        lda     f:render_camera+10
        and     #$00FF
        cmp     #RUNTIME_MENU_TECHNIQUE_FACE_COLORS
        bne     @Done
        lda     f:runtime_menu_open
        bne     @Done
        lda     f:quakec_last_tick
        cmp     f:QC_INPUT_TICK
        beq     @Done
.ifdef PLAYABLE_E1M1_PREFETCH_GAMEPLAY
        inc
        beq     @Immediate              ; The deferred input token needs a nonzero tick.
        ldx     a:qc_sample_weapon
        bne     @Immediate              ; Retain the weapon selection before staging.
        jml     GameplayCaptureDeferredLiveInput
@Immediate:
.endif
        jml     ServiceExclusiveBakedGameplay
.ifdef PLAYABLE_E1M1_PREFETCH_GAMEPLAY
        .res    2, $EA
.else
        .res    14, $EA
.endif
@Done:
        rtl
.popseg

.pushseg
.segment "CODE"
; This entry owns the stopped FX3 for the entire gameplay callback.
; No renderer refill runs until the service returns and restores the bank.
ServiceExclusiveBakedGameplay:
        lda     #$8000
        sta     f:qc_fx3_plane_foreground_wram
        RW      a8
        lda     #(.bankbyte(CollisionFx3PlaneDistanceGSU) & $7f)
        sta     f:FX3_PBR
        lda     #FX3_SCMR_128X128_8BPP_ROM
        sta     f:FX3_SCMR
        RW      a16
        jsl     QuakeCService
        RW      a8
        lda     #0
        sta     f:FX3_SCMR
        lda     #$70
        sta     f:FX3_PBR
        RW      a16
        lda     #0
        sta     f:qc_fx3_plane_foreground_wram
        rtl

WalkPlaneDistanceBaked:
        FX3_PLANE_INPUTS
        FX3_PLANE_JOB @Wait
        rtl
.popseg
