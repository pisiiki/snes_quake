; Stock timed artifacts. The player's combat clock and deadlines are Q6.
.pushseg
.segment "BSP_QUAKEC"
.macro PowerupPickup I, Deadline, Warning, Pulses, Track
        .local skip
        lda     f:QuakeCPowerupMask
        bit     #(1 << I)
        beq     skip
        .repeat 3, J
        QC_SHELL_AXIS .ident(.sprintf("BSP_WORLD_ORIGIN_%c", 88+J)), 2*J, .ident(.sprintf("QC_POWERUP_%d_%c_MIN", I, 88+J)), .ident(.sprintf("QC_POWERUP_%d_%c_MAX", I, 88+J)), skip
        .endrepeat
        lda     f:QuakeCPowerupMask
        and     #.loword(~(1 << I))
        sta     f:QuakeCPowerupMask
        lda     f:QuakeCItemsHigh
        ora     #.ident(.sprintf("QC_POWERUP_%d_ITEM_HIGH", I))
        sta     f:QuakeCItemsHigh
.ifdef QC_PICKUP_NOTICES
        lda     #NOTICE_QUAD+I
        jsl     PickupNotify
.endif
        lda     a:grunt_clock
        clc
        adc     #64*.ident(.sprintf("QC_POWERUP_%d_SECONDS", I))
        sta     a:shot_player+Deadline
        stz     a:.loword(Warning)
        stz     a:.loword(Pulses)
        lda     #Track
        jsr     PowerupSelectTrack
        lda     f:control_revision
        inc
        sta     f:control_revision
        lda     f:pickup_pixels_dirty
        inc
        sta     f:pickup_pixels_dirty
skip:
.endmacro

PowerupTouch:
        RW_assume a16i16
        lda     a:shot_player+QC_FIELD_HEALTH
        beq     :+
        bpl     :++
:       rtl
:       PowerupPickup 0, QC_FIELD_SUPER_DAMAGE_FINISHED, quad_warn_next, quad_warning_pulses, 1
        PowerupPickup 1, QC_FIELD_RADSUIT_FINISHED, suit_warn_next, suit_warning_pulses, 4
@Done:  rtl

; A selects a regular health box (1 small, 2 large) or playable armor.
; Use its original PCM while the independent MSU audio port is free.
PowerupHealthSound:
        RW_assume a16i16
        pha
        lda     f:$002002
        cmp     #$2d53                  ; MSU signature 'S-'.
        bne     @Fallback
.if .defined(PLAYABLE_MAP_ID) && .defined(QC_ARMOR_COUNT)
        ldx     a:.loword(quad_msu_pending)
        bne     @Fallback
.endif
        RW      a8
        lda     f:$002000
.ifdef QC_E1M1_TELEPORT
        ldx     a:.loword(teleport_hum_playing)
        beq     :+
        and     #$ef                   ; A health sound may interrupt the idle hum.
:
.endif
        bit     #$50
        RW      a16
        bne     @Fallback
        pla
.if .defined(PLAYABLE_MAP_ID) && .defined(QC_ARMOR_COUNT)
        cmp     #GAMEPLAY_PICKUP_ARMOR
        bne     :+
        lda     #GAMEPLAY_PCM_ARMOR_PICKUP
        bra     @StartTrack
:
.endif
        cmp     #2
        beq     :+
        lda     #14
        bra     :++
:       lda     #3
:
@StartTrack:
        jsr     PowerupSelectTrack
        rtl
@Fallback:
        inc     a:.loword(quakec_sounds)
        pla
.if .defined(PLAYABLE_MAP_ID) && .defined(QC_ARMOR_COUNT)
        cmp     #GAMEPLAY_PICKUP_ARMOR
        bne     :+
        lda     #GAMEPLAY_ARMOR_SAMPLE
        jml     GameplayPlayMapCueAcknowledged
:
.endif
        clc
        adc     #20
        jml     GameplayPlaySoundLong

.include "quake/GameplayTrack.s"

.ifdef QC_E1M1_TELEPORT
; Quake's ambient uses half volume and ATTN_STATIC, audible within 1000/3 units.
; The two MSU interfaces are independent. This service touches only audio.
TeleportAmbientService:
        stz     a:hub_extent
        .repeat 3, I
        lda     f:.ident(.sprintf("camera_%c", 120+I))
        sec
        sbc     #.loword(.ident(.sprintf("QC_TELEPORT_AMBIENT_%c", 88+I)))
        bpl     :+
        neg
:       cmp     #5344
        bcc     :+
        jmp     @Far
:       clc
        adc     #128
        xba
        and     #$ff
        asl
        tax
        lda     f:TeleportAxisSquares,x
        clc
        adc     a:hub_extent
        sta     a:hub_extent
        .endrepeat
        ldx     #0
@Ring:  cmp     f:TeleportRingSquares,x
        bcc     @Volume
        inx
        inx
        cpx     #32
        bcc     @Ring
@Far:   lda     a:.loword(teleport_hum_playing)
        beq     @Done
        stz     a:.loword(teleport_hum_playing)
        RW      a8
        lda     #0
        sta     f:$002007
        RW      a16
@Done:  rts
@Volume:
        txa
        eor     #30
        asl
        asl
        clc
        adc     #4
        sta     a:.loword(teleport_hum_volume)
        lda     a:.loword(teleport_hum_playing)
        beq     @ConsiderStart
        RW      a8
        lda     f:teleport_hum_volume
        sta     f:$002006
        RW      a16
        rts
@ConsiderStart:
        lda     a:.loword(quad_msu_pending)
        bne     @Done
        lda     f:$002000
        bit     #$50
        bne     @Done
        lda     #1
        sta     a:.loword(teleport_hum_playing)
        lda     #21
.if .defined(PLAYABLE_MAP_ID) && (.defined(QC_NAIL_COUNT) || .defined(QC_CAMPAIGN_ITEMS))
        sta     a:.loword(nail_msu_track)
.endif
        sta     a:.loword(quad_msu_pending)
        sta     f:$002004
        jmp     PowerupServiceTrack
TeleportAxisSquares:
        .repeat 22,I
        .word I*I
        .endrepeat
TeleportRingSquares:
        .repeat 16,I
        .word ((1000*(I+1))*(1000*(I+1))+768*768-1)/(768*768)
        .endrepeat
.endif

; CheckPowerups warns strictly inside the last three seconds, and expires
; on the first tick strictly past the deadline.
.macro PowerupTimer Deadline, Warning, Pulses, ItemBit, Track
        .local done, expire, pulse, first
        lda     a:shot_player+Deadline
        beq     done
        sec
        sbc     a:grunt_clock
        bcc     expire
        cmp     #3*64
        bcs     done
        lda     a:.loword(Warning)
        beq     first
        cmp     a:grunt_clock
        bcs     done
        bra     pulse
first: lda     #Track
        jsr     PowerupSelectTrack
pulse: inc     a:.loword(Pulses)
        lda     a:grunt_clock
        clc
        adc     #64
        sta     a:.loword(Warning)
        bra     done
expire:
        stz     a:shot_player+Deadline
        stz     a:.loword(Warning)
        lda     f:QuakeCItemsHigh
        and     #.loword(~ItemBit)
        sta     f:QuakeCItemsHigh
done:
.endmacro

PowerupTick:
        RW_assume a16i16
        jsr     PowerupServiceTrack
.ifdef QC_E1M1_TELEPORT
        jsr     TeleportAmbientService
.ifdef PLAYABLE_MAP_ID
        jsl     IndustrialTick
.endif
.endif
        PowerupTimer QC_FIELD_SUPER_DAMAGE_FINISHED, quad_warn_next, quad_warning_pulses, QC_POWERUP_0_ITEM_HIGH, 2
        PowerupTimer QC_FIELD_RADSUIT_FINISHED, suit_warn_next, suit_warning_pulses, QC_POWERUP_1_ITEM_HIGH, 5
        ; WaterMove sees the current time and the newly expired item.
        jml     WalkLiquidEffects

; Play the original independently mixed attack hum at the stock one-second limit.
PowerupAttack:
        RW_assume a16i16
        pha
        lda     a:shot_player+QC_FIELD_SUPER_DAMAGE_FINISHED
        cmp     a:grunt_clock
        beq     @Done
        bcc     @Done
        lda     a:grunt_clock
        cmp     a:shot_player+QC_FIELD_SUPER_SOUND
        beq     @Done
        bcc     @Done
        clc
        adc     #64
        sta     a:shot_player+QC_FIELD_SUPER_SOUND
        inc     a:.loword(quakec_sounds)
        jsl     PowerupPlayAttackCue
@Done:  pla
        rtl

PowerupPlayAttackCue:
        lda     #GAMEPLAY_QUAD_ATTACK_SAMPLE
GameplayPlayMapCueAcknowledged:
        jsl     GameplayPlaySoundLong
        ; A second callback can immediately issue a command on the same port.
        ; Give the SPC a bounded window to latch this voice first.
        phx
        ldx     #256
        RW      a8
@Ack:   lda     f:SMPIO3
        cmp     f:shotgun_sound_token
        beq     @Acked
        dex
        bne     @Ack
@Acked: RW      a16
        plx
        rtl

PowerupStage:
        RW_assume a16i16
        .repeat QC_POWERUP_COUNT, I
        .scope
        base = (QC_GRUNT_COUNT+QC_ARMOR_COUNT+I)*GSU_GRUNT_POSE_BYTES
        lda     f:QuakeCPowerupMask
        bit     #(1 << I)
        beq     hidden
        lda     a:.loword(armor_yaw)
        ora     #(.ident(.sprintf("QC_POWERUP_%d_SPRITEROW", I)) << 8)
        bra     store
hidden: lda     #GSU_HIDDEN_ACTOR_POSE
store:  sta     f:GSU_LIVE_POSE_ADDRESS+base
        .repeat 3, J
        lda     #.loword(.ident(.sprintf("QC_POWERUP_%d_%c", I, 88+J)))
        sta     f:GSU_LIVE_POSE_ADDRESS+2+base+2*J
        .endrepeat
        .endscope
        .endrepeat
        rtl
.ifdef PLAYABLE_MAP_ID
; Remember the damage event on Quake's Q6 gameplay clock. The high bit
; distinguishes a hit at time zero from an inactive expression.
StatusHudFaceDamage:
        RW_assume a8i16
        cmp     #4
        beq     :+
        rtl                     ; A continuing flash does not restart the portrait.
:       RW      a16
        lda     f:QuakeCGlobals+QC_GLOBAL_TIME
        ora     #$8000
        sta     f:status_hud_face_hit
        RW      a8
        lda     #4              ; Preserve the damage flash counter for the caller.
        rtl

; Return the byte offset into PowerupFaceSources. Each portrait has three
; far pointers. The clock rebases by $4000, including during an active hit.
StatusHudDesiredFace:
        RW_assume a16i16
        lda     f:status_hud_face_hit
        bpl     @Item
        lda     f:QuakeCGlobals+QC_GLOBAL_TIME
        sec
        sbc     f:status_hud_face_hit
        and     #$3fff
        cmp     #13             ; ages 0..12 Q6 are within the stock 0.2 seconds
        bcc     @Item
        lda     #0
        sta     f:status_hud_face_hit
@Item:  lda     f:QuakeCItemsHigh
        bit     #QC_POWERUP_0_ITEM_HIGH
        beq     :+
        lda     #9
        rtl
:       lda     f:status_hud_face_hit
        bmi     @Pain
        lda     #0
        rtl
@Pain:  lda     f:ShotgunPlayer+QC_FIELD_HEALTH
        bmi     @Lowest
        .repeat 4, I
        cmp     #(80-20*I)*64
        bcc     :+
        lda     #18+9*I
        rtl
:
        .endrepeat
@Lowest:
        lda     #54
        rtl

; Replace only the three FACE1 rows. The tilemap can continue to select
; the same face slot on either displayed page.
PowerupFaceUpload:
        RW_assume a16i16
        tax
        RW      a8
        lda     #$80
        sta     VMAINC
        ldy     #$1801
        sty     DMAP7
        .repeat 3, I
        lda     f:PowerupFaceSources+2+3*I,x
        sta     A1B7
        RW      a16
        lda     f:PowerupFaceSources+3*I,x
        sta     A1T7L
        ldy     #.ident(.sprintf("HUD_FACE_ROW_%d", I))/2
        sty     VMADDL
        ldy     #3*64
        sty     DAS7L
        RW      a8
        lda     #$80
        sta     MDMAEN
        .endrepeat
        RW      a16
        rtl
PowerupFaceSources:
        .repeat 3, I
        .faraddr HUD_ATLAS+.ident(.sprintf("HUD_FACE_ROW_%d", I))-$9000
        .endrepeat
        .repeat 3, I
        .faraddr HUD_QUAD_FACE+192*I
        .endrepeat
        .repeat 15, I
        .faraddr HUD_PAIN_FACES+192*I
        .endrepeat
.endif
.popseg
