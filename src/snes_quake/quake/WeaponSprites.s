; X2 weapon pixels are already on the logical framebuffer grid.
WEAPON_CODE_ROM_BANK = ^WeaponBlitX2 & $7F

.import WeaponBlitX2, WeaponBlitShiftedX2, WeaponRestoreX2
.assert ^WeaponBlitShiftedX2 = ^WeaponBlitX2, lderror, "Shifted weapon code must share the weapon FX3 ROM bank"
.assert BSP_WEAPON_MAX_ROWS <= WEAPON_UNDO_MAX_ROWS, error, "Weapon sprite exceeds FX3 undo scratch"

.segment "CODE"

; Freeze frame ID (low byte) and signed bob (high byte) before temporal reuse.
SelectRenderWeapon:
        RW_assume a16i16
        stz     render_weapon_frame
.ifdef QC_INTERMISSION_COUNT
        lda     f:intermission_phase
        cmp     #2
        bne     :+
        jmp     @Done
:
.endif
        lda     render_coverage_mode
        beq     :+
        jmp     @Done
:
        lda     render_camera+10
        and     #$00FF
        cmp     #2
        bcs     :+
        rts
:       cmp     #BSP_TECHNIQUE_UNTEXTURED_LIGHTMAP
        bne     :+
        rts
:
        ldx     render_demo_pose
        cpx     #$FFFF
        beq     @Fly
        cpx     #BSP_WEAPON_POSE_COUNT
        bcc     :+
        rts
:
        txa
        asl
        tax
        lda     f:QuakeBSPWeaponPoses,x
        bra     @Selected
@Fly:
.if BSP_QUAKEC_GAMEPLAY
.ifdef QC_QUEUED_INPUT
  .ifdef PLAYABLE_WEAPON_OBJ
        lda     weapon_obj_frozen
        bne     @Shotgun
  .endif
        lda     f:axe_selected
        beq     @Shotgun
        lda     f:shot_clock_wram
        cmp     #BSP_WEAPON_AXE_TICKS
        bcc     :+
        lda     #BSP_WEAPON_AXE_IDLE
        bra     @Selected
:       tax
        lda     f:QuakeBSPWeaponAxeFrames,x
        and     #$00FF
        bra     @Selected
@Shotgun:
  .if .defined(QC_NAIL_COUNT) || .defined(QC_CAMPAIGN_ITEMS)
        lda     f:ShotgunPlayer+QC_FIELD_WEAPON
        cmp     #4*64
        bne     :+
        lda     f:nail_frame
        clc
        adc     #BSP_WEAPON_NAIL_IDLE
        bra     @Selected
:
  .endif
.endif
        lda     f:shotgun_shots
        bne     @Shot
        lda     #1                      ; The first descriptor is the idle MDL frame.
        bra     @Selected
@Shot:
        ; A slow world frame can outlast the stock muzzle pose. Show it
        ; once in the first composite after each shot, then follow time.
        cmp     f:shotgun_view_shot
        beq     @Age
        sta     f:shotgun_view_shot
        lda     #2                      ; Stock firing pose 1.
        bra     @Selected
@Age:
        lda     f:shot_clock_wram
        tax
        lda     f:QuakeBSPWeaponLiveFrames,x
        and     #$00FF
        bra     @Selected
.else
        rts
.endif
        lda     weapon_idle_frame
        bne     @Selected
        lda     f:QuakeBSPWeaponPoses
        and     #$00FF
        tax
        lda     f:QuakeBSPWeaponIdleFrames,x
        and     #$00FF
@Selected:
.ifdef QC_SSG_SOUND
        pha
        lda     render_demo_pose
        cmp     #$ffff
        bne     :+
        lda     f:axe_selected
        bne     :+
        lda     f:ShotgunPlayer+QC_FIELD_WEAPON
        cmp     #2*64
        bne     :+
        pla
        clc
        adc     #BSP_WEAPON_SSG_IDLE-1
        bra     :++
:       pla
:
.endif
        sta     render_weapon_frame
@Done:
SelectRenderWeaponComplete:
        rts

; Compose only while the immutable producer image is being staged. Restore
; the underlying world afterward: X2 deliberately retains unwritten pixels.
BlitStagingWeapon:
        RW_assume a16i16
        stz     weapon_undo_count
        lda     temporal_stage_metadata_only
        bne     @Done
        lda     staging_weapon_frame
        and     #$00FF
        beq     @Done
        asl
        asl
        asl
        tax
        lda     f:QuakeBSPWeaponDescriptors,x
        sta     FX3_R1
        lda     f:QuakeBSPWeaponDescriptors+6,x
        sta     FX3_R2
        lda     staging_weapon_frame
        and     #$FF00
        bne     @Shifted
.ifdef PLAYABLE_MAP_ID
        .assert BSP_VIEW_HEIGHT = BSP_WEAPON_PLAYABLE_HEIGHT, error, "Playable weapon rows must match the visible raster"
.endif
        lda     f:QuakeBSPWeaponDescriptors+2,x
        beq     @Done
        sta     weapon_undo_count
        sta     FX3_R12
        RW      a8
        lda     #WEAPON_CODE_ROM_BANK
        sta     FX3_PBR
        FX3_JOB_START FX3_SCMR_128X128_8BPP_ROM, .loword(WeaponBlitX2), set
        jsr     JoinWeaponJob
        bra     @Done
@Shifted:
        RW_forced a16i16
        jsr     PrepareWeaponBob
        cmp     #0
        beq     @Done
        sta     weapon_undo_count
        sta     FX3_R12
        RW      a8
        lda     #WEAPON_CODE_ROM_BANK
        sta     FX3_PBR
        FX3_JOB_START FX3_SCMR_128X128_8BPP_ROM, .loword(WeaponBlitShiftedX2), set
        jsr     JoinWeaponJob
@Done:
        RW_forced a16i16
        rts

; A contains the signed offset in the high byte; X is frame ID * 8.
; Return the visible prefix length after installing the address deltas.
PrepareWeaponBob:
        RW_assume a16i16
        xba
        clc
        adc     #BSP_WEAPON_BOB_LIMIT
        and     #$0007
        asl
        pha
        txa
        asl
        clc
        adc     1,s
        tax
        lda     f:QuakeBSPWeaponBobRows,x
        tax
        pla
        cpx     #0
        beq     @NoRows
        asl
        asl
        asl
        clc
        adc     #.loword(QuakeBSPWeaponBobDeltas)
        phy
        phb
        phx
        tax
        ldy     #WEAPON_BOB_DELTAS
        lda     #15
        mvn     #^QuakeBSPWeaponBobDeltas, #^GSU_DATA_BASE
        pla
        plb
        ply
        rts
@NoRows:
        txa
        rts

RestoreStagingWorld:
        RW_assume a16i16
        lda     weapon_undo_count
        beq     @Done
        sta     FX3_R12
        stz     weapon_undo_count
        RW      a8
        lda     #WEAPON_CODE_ROM_BANK
        sta     FX3_PBR
        FX3_JOB_START FX3_SCMR_128X128_8BPP_ROM, .loword(WeaponRestoreX2), set
        jsr     JoinWeaponJob
@Done:
        RW_forced a16i16
        rts

JoinWeaponJob:
        RW_assume a8i16
        BSP_SOUND_FX3_JOB_JOIN 2
        stz     FX3_SCMR
        lda     #$70
        sta     FX3_PBR
        RW      a16
        rts

; Mode 2 selects the precomputed flash palette for this immutable upload slot.
SelectUploadWeaponPalette:
        RW_assume a16i16
        lda     upload_slot
        asl
        tax
        lda     slot_weapon_frame,x
        and     #$00FF
        asl
        asl
        asl
        tax
        lda     f:QuakeBSPWeaponDescriptors+4,x
        asl
        sta     upload_palette_mode
        rts

.segment "LORAM"
weapon_idle_frame:      .res 2
weapon_undo_count:      .res 2
render_weapon_frame:    .res 2
staging_weapon_frame:   .res 2
scheduled_weapon_frame: .res 2
slot_weapon_frame:      .res 4
.segment "CODE"
