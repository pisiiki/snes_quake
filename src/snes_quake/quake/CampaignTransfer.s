; The checked warm header is live only from the quiescent module switch through
; BootVector. Keep stock map-change parameters outside both modules' edict RAM.
.if PLAYABLE_MAP_ID = PLAYABLE_E1M1_MAP_ID || PLAYABLE_MAP_ID = PLAYABLE_E1M2_MAP_ID
CampaignPacket = PLAYABLE_HANDOFF+12
CampaignSignature = $4349
CampaignFields:
        .word QC_FIELD_ITEMS, QC_FIELD_HEALTH, QC_FIELD_ARMORVALUE
        .word QC_FIELD_AMMO_SHELLS, QC_FIELD_AMMO_NAILS, QC_FIELD_AMMO_ROCKETS
        .word QC_FIELD_AMMO_CELLS, QC_FIELD_WEAPON, QC_FIELD_ARMORTYPE
CampaignFieldBytes = * - CampaignFields
CampaignItemsHighWord = 2+CampaignFieldBytes
CampaignAxeWord = CampaignItemsHighWord+2
CampaignBytes = CampaignAxeWord+2
.endif

.if PLAYABLE_MAP_ID = PLAYABLE_E1M1_MAP_ID
CampaignRequestMap:
        RW_assume a16i16
        jsl     PlayableRequestMapLong
        lda     #2                      ; Explicit intermission action.
        sta     f:playable_switch_pending
        rtl

CampaignWrite:
        RW_assume a16i16
        lda     f:playable_switch_pending
        cmp     #2
        bne     @Done
        lda     #CampaignSignature
        sta     f:CampaignPacket
        lda     f:ShotgunPlayer+QC_FIELD_HEALTH
        beq     @NewPlayer
        bmi     @NewPlayer
        ldy     #0
@Copy:  tyx
        lda     f:CampaignFields,x
        tax
        lda     f:ShotgunPlayer,x
        tyx
        sta     f:CampaignPacket+2,x
        iny
        iny
        cpy     #CampaignFieldBytes
        bcc     @Copy
        lda     f:QuakeCItemsHigh
        and     #$ff81                  ; Strip both keys and timed artifacts.
        sta     f:CampaignPacket+CampaignItemsHighWord
        lda     f:axe_selected
        sta     f:CampaignPacket+CampaignAxeWord
        lda     f:CampaignPacket+4
        cmp     #50*64
        bcs     :+
        lda     #50*64
:       cmp     #100*64
        bcc     :+
        lda     #100*64
:       sta     f:CampaignPacket+4
        lda     f:CampaignPacket+8
        cmp     #25*64
        bcs     @Done
        bra     @ShellMinimum
@NewPlayer:
        ; SetNewParms. Other parameters are zero from PlayableClearFxRam.
        lda     #4097
        sta     f:CampaignPacket+2
        lda     #100*64
        sta     f:CampaignPacket+4
        lda     #64
        sta     f:CampaignPacket+16
@ShellMinimum:
        lda     #25*64
        sta     f:CampaignPacket+8
@Done:  rts
.endif

.ifdef QC_CAMPAIGN_ITEMS
.pushseg
.segment "LORAM"
CampaignEntry: .res CampaignBytes
.popseg
CampaignRead:
        RW_assume a16i16
        ldx     #CampaignBytes-2
@Copy:  lda     f:CampaignPacket,x
        sta     f:CampaignEntry,x
        dex
        dex
        bpl     @Copy
        rtl

CampaignApply:
        RW_assume a16i16
        lda     f:CampaignEntry
        cmp     #CampaignSignature
        bne     @Done
        lda     #0
        sta     f:CampaignEntry
        ldy     #0
@Copy:  tyx
        lda     f:CampaignEntry+2,x
        pha
        lda     f:CampaignFields,x
        tax
        pla
        sta     f:ShotgunPlayer,x
        iny
        iny
        cpy     #CampaignFieldBytes
        bcc     @Copy
        lda     f:CampaignEntry+CampaignItemsHighWord
        sta     f:QuakeCItemsHigh
        lda     f:CampaignEntry+CampaignAxeWord
        sta     f:axe_selected
        beq     :+
        lda     #0
        bra     @Ammo
:
        lda     f:ShotgunPlayer+QC_FIELD_WEAPON
        cmp     #4*64
        beq     @Nails
        lda     f:ShotgunPlayer+QC_FIELD_AMMO_SHELLS
        bra     @Ammo
@Nails: lda     f:ShotgunPlayer+QC_FIELD_AMMO_NAILS
@Ammo:  sta     f:ShotgunPlayer+QC_FIELD_CURRENTAMMO
@Done:  rtl
.endif
