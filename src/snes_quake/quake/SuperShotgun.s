; Single-player weapon_touch, after the PAK oracle resolves the linked item hull.
.ifdef QC_SSG_ROW
SuperShotgunTouch:
        lda     f:QuakeCSuperShotgunVisible
        bne     :+
        rtl
:
        lda     a:shot_player+QC_FIELD_HEALTH
        beq     :+
        bpl     :++
:       rtl
:
        .repeat 3, Axis
        lda     a:w_from+2*Axis
        sec
        sbc     #.loword(.ident(.sprintf("QC_SSG_%c_MIN", 88+Axis)) - .ident(.sprintf("BSP_WORLD_ORIGIN_%c", 88+Axis))*16)
        cmp     #.ident(.sprintf("QC_SSG_%c_MAX", 88+Axis)) - .ident(.sprintf("QC_SSG_%c_MIN", 88+Axis)) + 1
        bcs     @Done
        .endrepeat
        lda     a:shot_player+QC_FIELD_AMMO_SHELLS
        clc
        adc     #QC_SSG_AMOUNT*64
        cmp     #100*64
        bcc     :+
        lda     #100*64
:       sta     a:shot_player+QC_FIELD_AMMO_SHELLS
        sta     a:shot_player+QC_FIELD_CURRENTAMMO
        lda     a:shot_player+QC_FIELD_ITEMS
        and     #.loword(~($200|$400|$800))
        ora     #$102                    ; IT_SHELLS and IT_SUPER_SHOTGUN.
        sta     a:shot_player+QC_FIELD_ITEMS
        lda     #2*64
        sta     a:shot_player+QC_FIELD_WEAPON
        stz     a:.loword(axe_selected)
        stz     a:.loword(axe_pending)
        stz     a:.loword(nail_frame)
        lda     #BSP_WEAPON_LIVE_TICKS
        sta     a:shot_clock
        lda     f:shotgun_shots
        sta     f:shotgun_view_shot
        lda     #0
        sta     f:QuakeCSuperShotgunVisible
.ifdef QC_PICKUP_NOTICES
        lda     #NOTICE_SSG
        jsl     PickupNotify
.endif
        inc     a:.loword(quakec_sounds)
        lda     #GAMEPLAY_WEAPON_PICKUP
        jsl     GameplayPlaySoundLong
        phb
        phk
        plb
        inc     control_revision
        inc     pickup_pixels_dirty
        plb
@Done:  rtl

.endif
; The muzzle samples have the same Quake channel, so they cannot overlap.
; A swap keeps the other seven DSP voices and their BRR addresses untouched.
        ssg_sample_address = BSP_CPU_CODE_ADDRESS(SuperShotgunSample)
        nail_sample_address = BSP_CPU_CODE_ADDRESS(QuakeWeaponAudio)+QC_NAIL_AUDIO_OFFSET_0
SuperShotgunLoadSample:
        cmp     f:super_shotgun_sample
        bne     :+
        rtl
:       sta     f:super_shotgun_sample
        phx
        RW_push set:a8i16
        lda     f:shotgun_sound_token
:       cmp     f:SMPIO3
        bne     :-
        lda     #GAMEPLAY_STREAM_WEAPON
        sta     f:SMPIO2
        jsr     @Handshake
        ldx     #0
        lda     f:super_shotgun_sample
        beq     @Nail
@Shot:  lda     f:ssg_sample_address,x
        sta     f:SMPIO2
        jsr     @Handshake
        inx
        cpx     #QC_WEAPON_SLOT_BYTES
        bne     @Shot
        bra     @Return
@Nail:  lda     f:nail_sample_address,x
        sta     f:SMPIO2
        jsr     @Handshake
        inx
        cpx     #QC_WEAPON_SLOT_BYTES
        bne     @Nail
@Return:
        RW_pull
        plx
        rtl
@Handshake:
        RW_assume a8i16
        lda     f:shotgun_sound_token
        inc
        sta     f:shotgun_sound_token
        sta     f:SMPIO3
:       cmp     f:SMPIO3
        bne     :-
        rts

.ifdef QC_SSG_ROW
SuperShotgunStage:
        RW_assume a16i16
        ssg_base = (GSU_BACKPACK_FIRST-1)*GSU_GRUNT_POSE_BYTES
        lda     f:QuakeCSuperShotgunVisible
        beq     :+
        lda     a:.loword(armor_yaw)
        ora     #(QC_SSG_ROW << 8)
        bra     :++
:       lda     #GSU_HIDDEN_ACTOR_POSE
:       sta     f:GSU_LIVE_POSE_ADDRESS+ssg_base
        .repeat 3, Axis
        lda     #.loword(.ident(.sprintf("QC_SSG_%c", 88+Axis)))
        sta     f:GSU_LIVE_POSE_ADDRESS+2+ssg_base+2*Axis
        .endrepeat
        rtl

.endif
SuperShotgunEmpty:
        RW_assume a16i16
        lda     a:grunt_clock
        cmp     a:shot_player+QC_FIELD_ATTACK_FINISHED
        bcc     @Done
        lda     a:shot_player+QC_FIELD_ITEMS
        bit     #4
        beq     @Axe
        lda     a:shot_player+QC_FIELD_AMMO_NAILS
        beq     @Axe
        sta     a:shot_player+QC_FIELD_CURRENTAMMO
        lda     #4*64
        sta     a:shot_player+QC_FIELD_WEAPON
        rtl
@Axe:   stz     a:shot_player+QC_FIELD_CURRENTAMMO
        lda     #1
        sta     f:axe_selected
@Done:  rtl
