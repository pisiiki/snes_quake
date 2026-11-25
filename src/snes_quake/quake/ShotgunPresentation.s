; E1M1 has no replay mixer. Upload the stock gameplay samples at boot and send
; a nonblocking trigger on the same sound callback as the original game.
.import ShotgunSoundDriver, ShotgunBrr, QuakeMapAudio
.include "quake/GameplayAuxSound.i"
.include "Data/QuakeBSPDogAudio.i"

.if .defined(QC_DOG_FIRST) || .defined(QC_KNIGHT_ROSTER)
.assert !QC_HUB_ENABLED, error, "Monster cues share ARAM with START teleport audio"
.pushseg
.segment "BSP_CPU_MAP_SOUND"
QuakeMonsterAudio:
.ifdef QC_DOG_FIRST
        .incbin "Data/QuakeBSPDogAudio.brr", QC_WEAPON_AUDIO_BYTES
QUAKE_MONSTER_AUDIO_BYTES = QC_DOG_AUDIO_BYTES-QC_WEAPON_AUDIO_BYTES
.elseif .defined(QC_CAMPAIGN_ITEMS)
        .incbin "Data/QuakeBSPKnightAudio.brr", QC_WEAPON_AUDIO_BYTES
QUAKE_MONSTER_AUDIO_BYTES = QC_KNIGHT_AUDIO_BYTES
.else
        .incbin "Data/QuakeBSPKnightAudio.brr"
QUAKE_MONSTER_AUDIO_BYTES = QC_KNIGHT_AUDIO_BYTES
.endif
.assert *-QuakeMonsterAudio = QUAKE_MONSTER_AUDIO_BYTES, error, "Monster sample size changed"
.assert QuakeMapAudio+QUAKE_MONSTER_AUDIO_BYTES <= $FFC0, lderror, "Warm map audio overlaps the SPC IPL ROM"
.ifdef QC_SSG_SOUND
.segment "BSP_CPU_WEAPON_SOUND"
QuakeWeaponAudio:
.ifdef QC_DOG_FIRST
        .incbin "Data/QuakeBSPDogAudio.brr", 0, QC_WEAPON_AUDIO_BYTES
.else
        .incbin "Data/QuakeBSPKnightAudio.brr", 0, QC_WEAPON_AUDIO_BYTES
.endif
SuperShotgunSample:
        .incbin "Data/QuakeBSPSuperShotgun.brr"
.assert *-SuperShotgunSample = QC_WEAPON_SLOT_BYTES, error, "Weapon voice transfer length changed"
.endif
.popseg
.endif

.pushseg
.segment "BSP_CPU_WALK_RUN"
ShotgunSoundInit:
        RW_assume a16i16
        RW_push set:a8i16
.ifdef PLAYABLE_MAP_ID
        lda     #0
        sta     f:$002007               ; Drop an old map's MSU effect on reload.
        ; The driver and all common cues survive a warm level load.
        lda     SMPIO0
        cmp     #$a5
        bne     @ColdUpload
        lda     SFX_nmitimen
        and     #$7f
        sta     NMITIMEN
        bra     @UploadMapAudio
@ColdUpload:
.endif
        lda     SFX_nmitimen
        and     #$7f
        sta     NMITIMEN
        SMP_ready
        SMP_exec __SMPCODE_RUN__, BSP_CPU_CODE_ADDRESS(__SMPCODE_LOAD__), __SMPCODE_SIZE__, ShotgunSoundDriver
@Ready:
        lda     SMPIO0
        cmp     #$a5
        bne     @Ready
.if .defined(QUAKE_MONSTER_AUDIO_BYTES) || .defined(PLAYABLE_MAP_ID)
  .ifndef QUAKE_MONSTER_AUDIO_BYTES
        bra     @Resume
  .endif
@UploadMapAudio:
        ; Reenter IPL for the one level-specific sample range. Common
        ; sample pointers and playback code stay in ARAM.
        lda     #GAMEPLAY_SAMPLE_IPL
        sta     SMPIO2
        lda     SMPIO3
        inc
        sta     SMPIO3
        SMP_ready
  .ifdef QUAKE_MONSTER_AUDIO_BYTES
    .ifdef QC_SSG_SOUND
        SMP_exec ShotgunBrr, BSP_CPU_CODE_ADDRESS(QuakeWeaponAudio), QC_WEAPON_AUDIO_BYTES, ShotgunSoundDriver
    .else
        ; Restore the full-bandwidth shotgun when switching from E1M1. Its
        ; ROM bytes belong to the common cold image, shared by every map.
        SMP_exec ShotgunBrr, BSP_CPU_CODE_ADDRESS(__SMPCODE_LOAD__)+(ShotgunBrr-__SMPCODE_RUN__), QC_STOCK_SHOT_BYTES, ShotgunSoundDriver
    .endif
:       lda     SMPIO0
        cmp     #$a5
        bne     :-
        lda     #GAMEPLAY_SAMPLE_IPL
        sta     SMPIO2
        lda     SMPIO3
        inc
        sta     SMPIO3
        SMP_ready
        SMP_exec QuakeMapAudio, BSP_CPU_CODE_ADDRESS(QuakeMonsterAudio), QUAKE_MONSTER_AUDIO_BYTES, ShotgunSoundDriver
  .else
        SMP_exec ShotgunBrr, BSP_CPU_CODE_ADDRESS(__SMPCODE_LOAD__)+(ShotgunBrr-__SMPCODE_RUN__), QC_WEAPON_AUDIO_BYTES+QC_ARRIVAL_AUDIO_BYTES, ShotgunSoundDriver
  .endif
@MapAudioReady:
        lda     SMPIO0
        cmp     #$a5
        bne     @MapAudioReady
.endif
@Resume:
        lda     SMPIO3
        sta     f:shotgun_sound_token
.if .defined(PLAYABLE_MAP_ID) && .defined(QC_E1M1_TELEPORT)
        jsl     IndustrialInit
.endif
        lda     SFX_nmitimen
        sta     NMITIMEN
@Return:
        RW_pull
        rtl

.segment "CODE"

; Port 1 echoes the full command. Its low five bits distinguish repeated
; events with the same selector. QuakeC counts the event before routing it.
GameplayPlayAuxSound:
        RW_push set:a8
        pha
        lda     f:SMPIO1
        inc
        and     #GAMEPLAY_AUX_TOKEN
        ora     1,s
        sta     f:SMPIO1
        pla
        RW_pull
        rtl

GameplayPlaySoundLong:
        RW_push set:a8
.if .defined(PLAYABLE_MAP_ID) && .defined(QC_E1M1_TELEPORT)
        pha
        jsl     IndustrialPrepareSound
        pla
.endif
        sta     f:SMPIO2
        lda     f:shotgun_sound_token
        inc
        sta     f:shotgun_sound_token
        sta     f:SMPIO3
        RW_pull
        rtl

; VBlank applies a short warm flash independently of a fresh FX3 frame.
; The runtime menu owns color math while it is open.
ShotgunVBlank:
        RW_assume a8i16
        lda     runtime_menu_open
        ora     runtime_menu_open+1
        bne     @Menu
        lda     f:grunt_damage_flash_wram
        beq     @ShotFlash
.if .defined(PLAYABLE_MAP_ID) .and .defined(QC_POWERUP_COUNT)
        jsl     StatusHudFaceDamage
.endif
        dec
        sta     f:grunt_damage_flash_wram
        beq     ShotgunClearFlashColor
.ifdef PLAYABLE_WEAPON_OBJ
        lda     #WEAPON_OBJ_DAMAGE_TINT
        sta     weapon_obj_tint_effect
.else
        stz     CGSWSEL
        lda     #CDAT_GREEN
        sta     COLDATA
        lda     #CDAT_RED | 10
        sta     COLDATA
        lda     #CG_BG1_ON | CG_BG2_ON
        sta     CGADSUB
.endif
        rts
@ShotFlash:
        lda     f:shotgun_flash
.ifdef PLAYABLE_WEAPON_OBJ
        beq     ShotgunClearFlashColor
.else
        beq     @Done
.endif
        dec
        sta     f:shotgun_flash
        beq     ShotgunClearFlashColor
.ifdef PLAYABLE_WEAPON_OBJ
        lda     #WEAPON_OBJ_SHOT_TINT
        sta     weapon_obj_tint_effect
.else
        stz     CGSWSEL
        lda     #CDAT_RED | 8
        sta     COLDATA
        lda     #CDAT_GREEN | 4
        sta     COLDATA
        lda     #CG_BG1_ON | CG_BG2_ON
        sta     CGADSUB
.endif
.ifndef PLAYABLE_WEAPON_OBJ
@Done:
.endif
        rts
@Menu:
        lda     #0
        sta     f:shotgun_flash
        sta     f:grunt_damage_flash_wram
.ifdef PLAYABLE_WEAPON_OBJ
        stz     weapon_obj_tint_effect
.endif
.ifdef PLAYABLE_MAP_ID
        bra     ShotgunResetFixedColor
.else
        ; The standalone menu owns the fixed color until it closes.
        rts
.endif
ShotgunClearFlashColor:
.ifdef PLAYABLE_WEAPON_OBJ
.ifdef QC_POWERUP_COUNT
        lda     f:QuakeCItemsHigh
        bit     #QC_POWERUP_0_ITEM_HIGH
        beq     :+
        lda     #WEAPON_OBJ_QUAD_TINT
        sta     weapon_obj_tint_effect
        rts
:       bit     #QC_POWERUP_1_ITEM_HIGH
        beq     :+
        lda     #WEAPON_OBJ_SUIT_TINT
        sta     weapon_obj_tint_effect
        rts
:
.endif
        stz     weapon_obj_tint_effect
        rts
.else
        stz     CGADSUB
        lda     #RUNTIME_MENU_COLOR_WINDOW_CLOSED
        sta     CGSWSEL
.endif
ShotgunResetFixedColor:
        lda     #$e0
        sta     COLDATA
        rts
.popseg

.include "quake/IndustrialSound.s"
