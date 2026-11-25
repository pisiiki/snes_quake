; Original single-player weapon and ammunition pickups, after their QuakeC
; startup callbacks have established the linked trigger bounds.
.pushseg
.segment "BSP_QUAKEC"
.ifdef QC_CAMPAIGN_ITEMS
.include "quake/GameplayTrack.s"
.endif
; Replay weapon-channel gunfire at its original sample rate. An active
; item/ambient track keeps the MSU transport while the SPC fires independently.
NailShotgunSound:
        ldx     #10
        lda     a:qcg+20
        cmp     #QC_SSG_SOUND
        bne     :+
        ldx     #22
:
.ifdef PLAYABLE_MAP_ID
        jsl     NailWeaponMsuAvailable
        bcs     @MSU
        bra     @SPC
.else
        lda     f:$002002
        cmp     #$2d53
        bne     @SPC
        lda     a:.loword(nail_msu_track)
        cmp     #10
        beq     @MSU
        cmp     #22
        beq     @MSU
        RW      a8
        lda     f:$002000
        bit     #$50
        RW      a16
        bne     @SPC
.endif
@MSU:   dec     a:.loword(quakec_sounds) ; The builtin counted the event.
        txa
        jmp     PowerupSelectTrack
@SPC:   lda     #GAMEPLAY_NAIL_SHOTGUN_FALLBACK
        cpx     #22
        bne     :+
        lda     #1
        jsl     SuperShotgunLoadSample
        lda     #GAMEPLAY_SSG_FIRE
:
        jmp     GameplayPlaySound

.ifdef PLAYABLE_MAP_ID
; This helper lives in the module's main CPU bank. E1M2's fixed QuakeC
; reservation has no spare space for the complete MSU path.
.pushseg
.segment "CODE"
NailWeaponMsuAvailable:
        RW_assume a16i16
        lda     f:$002002
        cmp     #$2d53
        bne     @Busy
        lda     a:.loword(nail_msu_track)
        cmp     #10
        beq     @Ready
        cmp     #22
        beq     @Ready
        cmp     #GAMEPLAY_PCM_NAIL_FIRE
        beq     @Ready
        RW      a8
        lda     f:$002000
        bit     #$50
        RW      a16
        bne     @Busy
@Ready: sec
        rtl
@Busy:  clc
        rtl

NailPlayMuzzle:
        jsl     NailWeaponMsuAvailable
        bcc     @Fallback
        lda     a:.loword(nail_msu_track)
        cmp     #GAMEPLAY_PCM_NAIL_FIRE
        beq     @Select
        lda     #GAMEPLAY_STOP_NAIL
        jsl     GameplayPlaySoundLong
@Select:
        dec     a:.loword(quakec_sounds) ; The track handler counts the same event.
        lda     #GAMEPLAY_PCM_NAIL_FIRE
        jml     GameplayPlayTrackLong
@Fallback:
        lda     #0
        jsl     SuperShotgunLoadSample
        lda     #GAMEPLAY_NAIL_FIRE
        jml     GameplayPlaySoundLong
.popseg
.endif

; Cycle the stock weapon order, skipping unowned or empty weapons.
; The axe uses the existing independent selection flag (IT_AXE is 4096).
NailCycleWeapon:
        RW_assume a16i16
        lda     #0
        sta     f:nail_frame
        lda     f:axe_selected
        bne     @TryShotgun
        lda     f:ShotgunPlayer+QC_FIELD_WEAPON
        cmp     #4*64
        beq     @Axe
        cmp     #2*64
        beq     @TryNail
        lda     f:ShotgunPlayer+QC_FIELD_ITEMS
        bit     #2
        beq     @TryNail
        lda     f:ShotgunPlayer+QC_FIELD_AMMO_SHELLS
        beq     @TryNail
        ldx     #2*64
        bra     @Equip
@TryNail:
        lda     f:ShotgunPlayer+QC_FIELD_ITEMS
        bit     #4
        beq     @Axe
        lda     f:ShotgunPlayer+QC_FIELD_AMMO_NAILS
        beq     @Axe
        ldx     #4*64
        bra     @Equip
@TryShotgun:
        lda     f:ShotgunPlayer+QC_FIELD_AMMO_SHELLS
        beq     @TryNail
        ldx     #64
@Equip: sta     f:ShotgunPlayer+QC_FIELD_CURRENTAMMO
        txa
        sta     f:ShotgunPlayer+QC_FIELD_WEAPON
        lda     #0
        sta     f:axe_selected
        rtl
@Axe:   lda     #1
        sta     f:axe_selected
        lda     #0
        sta     f:ShotgunPlayer+QC_FIELD_CURRENTAMMO
        rtl

.ifdef QC_NAIL_COUNT
NailPickupTouch:
        RW_assume a16i16
        lda     a:shot_player+QC_FIELD_HEALTH
        beq     :+
        bpl     :++
:       rtl
:       ldx     #0
@Scan:
        lda     f:QuakeCNailMask
        and     f:NailPickupRecords,x
        bne     :+
        jmp     @Next
:       .repeat 3, Axis
        lda     a:w_from+2*Axis
        sec
        sbc     f:NailPickupRecords+2+4*Axis,x
        cmp     f:NailPickupRecords+4+4*Axis,x
        bcc     :+
        jmp     @Next
:       .endrepeat
        lda     a:shot_player+QC_FIELD_AMMO_NAILS
        cpx     #0
        beq     @Collect
        cmp     #200*64
        bcs     @Next
@Collect:
        clc
        adc     f:NailPickupRecords+14,x
        cmp     #200*64
        bcc     :+
        lda     #200*64
:       sta     a:shot_player+QC_FIELD_AMMO_NAILS
        cpx     #0
        bne     @Equipped
        lda     a:shot_player+QC_FIELD_ITEMS
        ora     #4
        sta     a:shot_player+QC_FIELD_ITEMS
        lda     #4*64
        sta     a:shot_player+QC_FIELD_WEAPON
        stz     a:.loword(axe_selected)
        stz     a:.loword(axe_pending)
        stz     a:.loword(nail_frame)
@Equipped:
        lda     f:axe_selected
        bne     :+
        lda     a:shot_player+QC_FIELD_WEAPON
        cmp     #4*64
        bne     :+
        lda     a:shot_player+QC_FIELD_AMMO_NAILS
        sta     a:shot_player+QC_FIELD_CURRENTAMMO
:       lda     f:QuakeCNailMask
        eor     f:NailPickupRecords,x
        sta     f:QuakeCNailMask
.ifdef QC_PICKUP_NOTICES
        lda     #NOTICE_NAILS
        cpx     #0
        bne     :+
        lda     #NOTICE_NAILGUN
:       jsl     PickupNotify
.endif
        phx
        lda     #1                    ; Original ammo pickup.
        cpx     #0
        bne     :+
        lda     #GAMEPLAY_WEAPON_PICKUP
:       inc     a:.loword(quakec_sounds)
        jsl     GameplayPlaySoundLong
        plx
        phb
        phk
        plb
        inc     control_revision
        inc     pickup_pixels_dirty
        plb
@Next:  txa
        clc
        adc     #16
        tax
        cpx     #(1+QC_NAIL_COUNT)*16
        bcs     @Done
        jmp     @Scan
@Done:  rtl

.endif
.ifdef PLAYABLE_WEAPON_OBJ
.segment "LORAM"
nail_view_slot: .res 2
nail_view_mask: .res 2
nail_view_rows: .res 2
nail_view_bob:  .res 2
.segment "BSP_QUAKEC"
; Compose the original eight-plane records after the selected GSU frame was
; copied to WRAM. The next world render still sees its unmodified framebuffer.
StageNailgunView:
        RW_assume a16i16
        lda     f:staging_weapon_frame
        and     #$ff
        cmp     #BSP_WEAPON_NAIL_IDLE
        bcs     :+
        rtl
:       asl
        asl
        asl
        tax
        lda     f:QuakeBSPWeaponDescriptors,x
        sec
        sbc     #.loword(QuakeBSPWeaponData0)
        pha
        txa
        asl
        pha
        lda     f:staging_weapon_frame
        xba
        clc
        adc     #BSP_WEAPON_BOB_LIMIT
        and     #7
        asl
        tay
        asl
        asl
        asl
        sta     f:nail_view_bob
        tya
        clc
        adc     1,s
        tax
        pla
        lda     f:QuakeBSPWeaponBobRows,x
        sta     f:nail_view_rows
        plx
        lda     f:nail_view_rows
        bne     :+
        rtl
:
        lda     f:producer_slot
        beq     :+
        lda     #.loword(StagedFrame1)
        bra     @Page
:       lda     #.loword(StagedFrame0)
@Page:  sta     f:nail_view_slot
        phb
        pea     $7e7e
        plb
        plb
@Row:   lda     f:QuakeBSPWeaponData0,x
        and     #14
        clc
        adc     a:nail_view_bob
        tay
        phx
        tyx
        lda     f:QuakeBSPWeaponBobDeltas,x
        plx
        clc
        adc     f:QuakeBSPWeaponData0,x
        clc
        adc     a:nail_view_slot
        tay
        lda     f:QuakeBSPWeaponData0+2,x
        and     #$ff
        sta     a:nail_view_mask
        xba
        ora     a:nail_view_mask
        eor     #$ffff
        sta     a:nail_view_mask
        .repeat 4, Plane
        lda     a:16*Plane,y
        and     a:nail_view_mask
        ora     f:QuakeBSPWeaponData0+3+2*Plane,x
        sta     a:16*Plane,y
        .endrepeat
        txa
        clc
        adc     #11
        tax
        dec     a:nail_view_rows
        bne     @Row
        plb
@Done:  rtl
.endif

.ifdef PLAYABLE_MAP_ID
NailHudSelected:
        lda     f:axe_selected
        bne     @Off
        lda     f:ShotgunPlayer+QC_FIELD_WEAPON
        cmp     #4*64
        bne     @Off
        lda     #1
        rtl
@Off:   lda     #0
        rtl
NailHudUpload:
        RW_assume a16i16
        tax
        RW      a8
        lda     #$80
        sta     VMAINC
        ldy     #$1801
        sty     DMAP7
        cpx     #0
        beq     :+
        ldx     #9
:       .repeat 3, I
        lda     f:NailHudSources+2+3*I,x
        sta     A1B7
        RW      a16
        lda     f:NailHudSources+3*I,x
        sta     A1T7L
        ldy     #.ident(.sprintf("HUD_AMMO_ROW_%d", I))/2
        sty     VMADDL
        ldy     #3*64
        sty     DAS7L
        RW      a8
        lda     #$80
        sta     MDMAEN
        .endrepeat
        RW      a16
        rtl
NailHudSources:
        .repeat 3, I
        .faraddr HUD_ATLAS+.ident(.sprintf("HUD_AMMO_ROW_%d", I))-$9000
        .endrepeat
        .repeat 3, I
        .faraddr HUD_NAIL_ICON+192*I
        .endrepeat
.endif

.include "quake/NailFlight.s"
.include "quake/SuperShotgun.s"

.ifdef QC_NAIL_COUNT
NailPickupRecords:
        .repeat (1+QC_NAIL_COUNT), I
        .if I = 0
        .word 1 << QC_NAIL_COUNT
        .else
        .word 1 << (I-1)
        .endif
        .repeat 3, Axis
        .word .loword(.ident(.sprintf("QC_NAIL_PICKUP_%d_%c_MIN", I, 88+Axis)) - .ident(.sprintf("BSP_WORLD_ORIGIN_%c", 88+Axis))*16)
        .word .ident(.sprintf("QC_NAIL_PICKUP_%d_%c_MAX", I, 88+Axis)) - .ident(.sprintf("QC_NAIL_PICKUP_%d_%c_MIN", I, 88+Axis)) + 1
        .endrepeat
        .word .ident(.sprintf("QC_NAIL_PICKUP_%d_AMOUNT", I))*64
        .endrepeat
.endif
.popseg
