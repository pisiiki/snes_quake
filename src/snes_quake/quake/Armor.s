; Checked stock pickup bounds and values come from the two original QuakeC spawns.
.pushseg
.segment "BSP_QUAKEC"
.ifdef QC_ARMOR_COUNT
ArmorTouch:
        RW_assume a16i16
        ldx     a:.loword(armor_angle_step)
        inx
        cpx     #72
        bcc     :+
        ldx     #0
:       stx     a:.loword(armor_angle_step)
        lda     f:ArmorYawTable,x
        and     #$00ff
        sta     a:.loword(armor_yaw)
        lda     a:shot_player+QC_FIELD_HEALTH
        bne     :+
        rtl
:       bpl     :+
        rtl
:
        .repeat QC_ARMOR_COUNT, I
        .scope
        lda     f:QuakeCArmorMask
        bit     #(1 << I)
        beq     skip
        .repeat 3, J
        QC_SHELL_AXIS .ident(.sprintf("BSP_WORLD_ORIGIN_%c", 88+J)), 2*J, .ident(.sprintf("QC_ARMOR_%d_%c_MIN", I, 88+J)), .ident(.sprintf("QC_ARMOR_%d_%c_MAX", I, 88+J)), skip
        .endrepeat
        ; Effective protection is value times 0.3 or 0.6.
        lda     a:shot_player+QC_FIELD_ARMORVALUE
        ldx     a:shot_player+QC_FIELD_ARMORTYPE
        cpx     #38
        bne     :+
        asl
:       cmp     #.ident(.sprintf("QC_ARMOR_%d_VALUE", I))*64*(.ident(.sprintf("QC_ARMOR_%d_TENTHS", I))/3)
        bcs     skip
        lda     #.ident(.sprintf("QC_ARMOR_%d_VALUE", I))*64
        sta     a:shot_player+QC_FIELD_ARMORVALUE
        lda     #(.ident(.sprintf("QC_ARMOR_%d_TENTHS", I))*64+5)/10
        sta     a:shot_player+QC_FIELD_ARMORTYPE
        lda     a:shot_player+QC_FIELD_ITEMS
        and     #$1fff
        ora     #.ident(.sprintf("QC_ARMOR_%d_BIT", I))
        sta     a:shot_player+QC_FIELD_ITEMS
        lda     f:QuakeCArmorMask
        eor     #(1 << I)
        sta     f:QuakeCArmorMask
.ifdef QC_PICKUP_NOTICES
        lda     #NOTICE_ARMOR
        jsl     PickupNotify
.endif
.if .defined(PLAYABLE_MAP_ID) && .defined(QC_POWERUP_COUNT)
        lda     #GAMEPLAY_PICKUP_ARMOR
        jsl     PowerupHealthSound
.else
        inc     a:.loword(quakec_sounds)
        lda     #GAMEPLAY_ARMOR_SAMPLE
        jsl     GameplayPlaySoundLong
.endif
        lda     f:control_revision
        inc
        sta     f:control_revision
        lda     f:pickup_pixels_dirty
        inc
        sta     f:pickup_pixels_dirty
skip:
        .endscope
        .endrepeat
        rtl

.endif
; A is incoming Q6 damage and X is the packed armortype (19/38).
; Match stock binary32 multiplication followed by ceil, including fractional hits.
ArmorSaved:
        RW_assume a16i16
        cpx     #0
        beq     @Zero
        stx     z:qc_factor
        ldy     #0
@Tens:
        cmp     #640
        bcc     @Tail
        sbc     #640
        iny
        bra     @Tens
@Tail:
        sta     z:qc_rhs
        asl
        adc     z:qc_rhs
        cpx     #38
        bne     :+
        asl
:       pha
        tya
        sta     z:qc_rhs
        asl
        adc     z:qc_rhs
        ldx     z:qc_factor
        cpx     #38
        bne     :+
        asl
:       tay
        pla
        beq     @Integral
@Remainder:
        iny
        sec
        sbc     #640
        beq     @Integral
        bcs     @Remainder
        bra     @Saved
@Integral:
        ; Both 0.3f and 0.6f exceed their exact decimal by a relative
        ; 2^-23 / 3. An integral product rounds up one float ULP only if
        ; its normalized significand is strictly greater than 1.5.
        tya
        beq     @Saved
@Normalize:
        asl
        bpl     @Normalize
        cmp     #$c001
        bcc     @Saved
        iny
@Saved:
        tya
        .repeat 6
        asl
        .endrepeat
        rtl
@Zero:
        lda     #0
        rtl

; A is damage in Q6. Environmental damage bypasses the monster VM.
ArmorEnvironmentDamage:
        pha
        ldx     a:shot_player+QC_FIELD_ARMORTYPE
        jsl     ArmorSaved
        cmp     a:shot_player+QC_FIELD_ARMORVALUE
        bcc     @Spend
        lda     a:shot_player+QC_FIELD_ARMORVALUE
        stz     a:shot_player+QC_FIELD_ARMORTYPE
        tax
        lda     a:shot_player+QC_FIELD_ITEMS
        and     #$1fff
        sta     a:shot_player+QC_FIELD_ITEMS
        txa
@Spend:
        sta     z:qc_rhs
        lda     a:shot_player+QC_FIELD_ARMORVALUE
        sec
        sbc     z:qc_rhs
        sta     a:shot_player+QC_FIELD_ARMORVALUE
        pla
        sec
        sbc     z:qc_rhs
        rtl
.ifdef QC_ARMOR_COUNT
ArmorYawTable:
        .repeat 72, I
        .byte (I*256)/72
        .endrepeat
.endif
.popseg
