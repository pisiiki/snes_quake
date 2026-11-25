; Pose CHR is uploaded into the inactive OBJ allocation beside the world
; chunks. OAM is published with the final world page.
.segment "ZEROPAGE"
weapon_obj_pointer: .res 3
weapon_obj_bob: .res 1

.segment "LORAM"
weapon_obj_resident: .res 2
weapon_obj_alternate: .res 2
weapon_obj_oam_word: .res 2
weapon_obj_page: .res 2
weapon_obj_frozen: .res 2
weapon_obj_masked: .res 2
weapon_obj_menu_pending: .res 2
weapon_obj_presented_mask: .res 2
weapon_obj_slot_mask: .res 4
weapon_obj_short_upload: .res 2
weapon_obj_menu_shadow_dirty: .res 1
weapon_obj_tint_effect: .res 1
weapon_obj_palette_key: .res 1
WEAPON_OBJ_DAMAGE_TINT = 4
WEAPON_OBJ_SHOT_TINT = 8
WEAPON_OBJ_QUAD_TINT = 12
WEAPON_OBJ_SUIT_TINT = 16

; While the weapon owns OAM, menu building is inactive. Opening the menu
; rebuilds its shadow before reusing it.
WeaponObjOam = RuntimeMenuOAM

.segment "RODATA"
.include "Data/QuakeBSPWeaponObj.i"
.assert WEAPON_OBJ_CHUNKS = BSP_TEXTURE_UPLOAD_CHUNKS, error, "World and OBJ upload chunk counts differ"
WeaponObjChunkOffsets:
.repeat WEAPON_OBJ_CHUNKS, i
        .word i*WEAPON_OBJ_CHR_DESC
.endrepeat

.segment "CODE"

; The E1M1 CPU prefix is full. Place the boot-only initializer in its
; existing CPU ROM reserve; neither steady-state path calls this helper.
.ifdef QC_E1M1_HINTS
.pushseg
.segment "BSP_CPU_PICKUP_PALETTE"
.endif
WeaponObjBoot:
        RW_assume a8i16
        RW      a16
        stz     weapon_obj_resident
        stz     weapon_obj_alternate
        stz     weapon_obj_oam_word
        stz     weapon_obj_page
        stz     weapon_obj_masked
        stz     weapon_obj_frozen
        stz     weapon_obj_menu_pending
        stz     weapon_obj_presented_mask
        stz     weapon_obj_slot_mask
        stz     weapon_obj_slot_mask+2
        stz     weapon_obj_short_upload
        lda     #0
        sta     f:GSU_DATA_BASE+WEAPON_OBJ_CORE_FLAG
        RW      a8
        stz     weapon_obj_menu_shadow_dirty
        stz     weapon_obj_tint_effect
        lda     upload_palette_mode
        sta     weapon_obj_palette_key
.ifdef QC_E1M1_HINTS
        rtl
.popseg
.else
        rts
.endif

WeaponObjBootPresent:
        RW_assume a8i16
        RW      a16
        lda     staging_weapon_frame
        beq     @Done
        sta     presented_weapon_frame
        stz     upload_slot
        RW      a8
        lda     #1
        sta     DMAP7
        lda     #$18
        sta     BBAD7
        lda     #$80
        sta     VMAINC
        RW      a16
        ldx     #0
@Chunk:
        stx     upload_chunk
        phx
        RW      a8
        jsr     WeaponObjUploadChunk
        RW      a16
        plx
        inx
        cpx     #WEAPON_OBJ_CHUNKS
        bne     @Chunk
        stz     upload_chunk
        jsr     WeaponObjPresent
@Done:
        RW      a8
        rts

; Freeze the weapon class for the frame while allowing the late shotgun
; sample to choose the flash and bob. A switch becomes visible next frame.
WeaponObjPrepareWorld:
        RW_assume a16i16
        stz     weapon_obj_frozen
.if !.defined(QC_HUB_WARNING_COUNT) .or .defined(QC_E1M1_HINTS)
        lda     weapon_obj_menu_pending
        bne     @Publish
        lda     render_camera+10
        and     #$00ff
        sec
        sbc     #RUNTIME_MENU_TECHNIQUE_FACE_COLORS
        cmp     #2
        bcs     @Publish
        lda     render_coverage_mode
        bne     @Publish
        lda     f:axe_selected
        bne     @Publish
.if .defined(QC_NAIL_COUNT) || .defined(QC_CAMPAIGN_ITEMS)
        lda     f:ShotgunPlayer+QC_FIELD_WEAPON
        cmp     #64
        bne     @Publish
.endif
        inc     weapon_obj_frozen
.endif
@Publish:
        lda     weapon_obj_frozen
        sta     f:GSU_DATA_BASE+WEAPON_OBJ_CORE_FLAG
WeaponObjMaskReady:
        bne     @Armed
        lda     weapon_obj_masked
        beq     @Done
        ; Unwritten world pixels persist in FX3 RAM. Clear the old image
        ; once when the conservative shotgun rectangle is exposed.
.if .defined(PLAYABLE_RESIDENT_WORLD) && (BSP_RENDER_SCALE = 2)
        lda     #0
        sta     f:GSU_DATA_BASE+GSU_RESIDENT_WORLD_STATUS
.endif
        RW      a8
        lda     #0
        sta     f:GSU_OUTPUT
        BSP_STATIC_COPY GSU_OUTPUT+1, GSU_OUTPUT, BSP_VIEW_STAGE_BYTES-1
        RW      a16
@Done:
        stz     weapon_obj_masked
        rts
@Armed:
        sta     weapon_obj_masked
        rts

; Read the pose asset base for the requested inactive or resident allocation.
; A16: one-based pose. Y16: byte offset of the page pointer within its pair.
WeaponObjSelect:
        RW_assume a16i16
        dec
        sta     weapon_obj_pointer
        asl
        clc
        adc     weapon_obj_pointer
        asl                     ; six address bytes per pose
        sty     weapon_obj_pointer
        clc
        adc     weapon_obj_pointer
        tax
        lda     f:WeaponObjPoseAddresses,x
        sta     weapon_obj_pointer
        lda     f:WeaponObjPoseAddresses+2,x
        RW      a8
        sta     weapon_obj_pointer+2
        RW      a16
        rts

; A8 on both entry and exit. The world transfer just used channel 7.
WeaponObjUploadChunk:
        RW_assume a8i16
        RW      a16
        lda     upload_slot
        asl
        tax
        lda     slot_weapon_frame,x
        and     #$00ff
        beq     @Done
.if .defined(QC_NAIL_COUNT) || .defined(QC_CAMPAIGN_ITEMS)
        cmp     #BSP_WEAPON_NAIL_IDLE
        bcs     @Done
.endif
        cmp     weapon_obj_resident
        beq     @Done
        cmp     weapon_obj_alternate
        beq     @Done
        pha
        ldy     #0
        lda     weapon_obj_page
        bne     :+
        ldy     #WEAPON_OBJ_POINTER_BYTES
:
        pla
        jsr     WeaponObjSelect
        lda     upload_chunk
        and     #$00ff
        asl
        tax
        lda     f:WeaponObjChunkOffsets,x
        tay
        lda     [weapon_obj_pointer],y
        lsr
        sta     VMADDL
        iny
        iny
        lda     [weapon_obj_pointer],y
        clc
        adc     #.loword(WEAPON_OBJ_CHR)
        sta     A1T7L
        iny
        iny
        lda     [weapon_obj_pointer],y
        beq     @Done
        sta     DAS7L
        RW      a8
        lda     #^WEAPON_OBJ_CHR
        sta     A1B7
        lda     #$80
        sta     MDMAEN
        RW      a16
@Done:
        RW      a8
        rts

WeaponObjPresent:
        RW_assume a16i16
        lda     presented_weapon_frame
        bne     :+
@NoWeapon:
        jmp     WeaponObjHide
:
        and     #$00ff
.if .defined(QC_NAIL_COUNT) || .defined(QC_CAMPAIGN_ITEMS)
        cmp     #BSP_WEAPON_NAIL_IDLE
        bcs     @NoWeapon
.endif
        cmp     weapon_obj_resident
        beq     @Resident
        tax
        lda     weapon_obj_resident
        sta     weapon_obj_alternate
        stx     weapon_obj_resident
        lda     weapon_obj_page
        eor     #1
        sta     weapon_obj_page
@Resident:
        lda     presented_weapon_frame
        cmp     weapon_obj_oam_word
        bne     :+
@Return:
        rts
:
        sta     weapon_obj_oam_word
        ldy     #0
        lda     weapon_obj_page
        beq     :+
        ldy     #WEAPON_OBJ_POINTER_BYTES
:
        lda     weapon_obj_resident
        jsr     WeaponObjSelect
        lda     weapon_obj_pointer
        clc
        adc     #WEAPON_OBJ_CHUNKS*WEAPON_OBJ_CHR_DESC
        sta     weapon_obj_pointer
        lda     weapon_obj_oam_word
        and     #$ff00
        bne     @Bobbing
        lda     weapon_obj_pointer
        sta     A1T7L
        ldx     #0
        stx     OAMADDL
        ldx     #$0400
        stx     DMAP7
        ldx     #544
        stx     DAS7L
        RW      a8
        lda     weapon_obj_pointer+2
        sta     A1B7
        lda     #$80
        sta     MDMAEN
        bra     @Enable
@Bobbing:
        RW_forced a16i16
        ldy     #0
        ldx     #.loword(WeaponObjOam)
        lda     weapon_obj_oam_word
        xba
        asl
        RW      a8
        sta     weapon_obj_bob
        lda     #1
        sta     weapon_obj_menu_shadow_dirty
@Copy:
        lda     [weapon_obj_pointer],y
        sta     a:$0000,x
        iny
        inx
        lda     [weapon_obj_pointer],y
        cmp     #224
        bcs     :+
        clc
        adc     weapon_obj_bob
:
        sta     a:$0000,x
        iny
        inx
        RW      a16
        lda     [weapon_obj_pointer],y
        sta     a:$0000,x
        iny
        iny
        inx
        inx
        cpy     #512
        beq     @High
        RW      a8
        bra     @Copy
@High:
        lda     [weapon_obj_pointer],y
        sta     a:$0000,x
        iny
        iny
        inx
        inx
        cpy     #544
        bne     @High
        OAM_memcpy WeaponObjOam
        RW      a16
        RW      a8
@Enable:
        RW_forced a8i16
.ifdef PLAYABLE_MAP_ID
        stz     status_hud_obj_blanked
        lda     #1
        sta     status_hud_obj_replay
.endif
        lda     #objsel($8000, OBJ_8x8_16x16, $2000)
        sta     OBJSEL
        lda     #tm(ON, OFF, OFF, OFF, ON)
        sta     TM
WeaponObjPresented:
        RW      a16
@Done:
        rts
WeaponObjHide:
        stz     weapon_obj_oam_word
        RW      a8
        lda     #tm(ON, OFF, OFF, OFF, OFF)
        sta     TM
        RW      a16
        rts

; Every page flip needs time to arm its matching HUD tilemap. A pose or
; palette change can also need 544 bytes of OAM and 512 bytes of CGRAM.
WeaponObjPageCanPublish:
        RW_assume a8i16
        ldx     #253                    ; Nine scanlines including DMA.
        lda     upload_palette_mode
        cmp     presented_palette_mode
        bne     @CheckTime
        RW      a16
        lda     upload_slot
        asl
        tay
        lda     slot_weapon_frame,y
        cmp     weapon_obj_oam_word
        RW      a8
        bne     @CheckTime
        ldx     #258                    ; Four scanlines for page and HUD setup.
@CheckTime:
        lda     HVBJOY
        bpl     @Late
        lda     STAT78
        lda     SLHV
        lda     OPVCT
        pha
        lda     OPVCT
        and     #1
        xba
        pla
        RW      a16
        phx
        cmp     1,s
        plx
        RW      a8
        rts
@Late:
        sec
        rts

; A visible world page owns the scene palette. The independent VBlank tint
; applies to every RGB555 color, including all five weapon OBJ palettes.
WeaponObjSyncPalette:
        RW_assume a8i16
.ifdef PICKUP_BLEND
        jsl     PickupPalettePublish
        bcc     :+
        rts
:
.endif
        lda     weapon_obj_tint_effect
        ora     presented_palette_mode
        cmp     weapon_obj_palette_key
        beq     @Done
        sta     weapon_obj_palette_key
        lda     weapon_obj_tint_effect
        bne     @Tint
        lda     presented_palette_mode
        jmp     LoadTexturePalette
@Tint:
        RW      a16
        and     #$001c
.ifdef QC_POWERUP_COUNT
        cmp     #WEAPON_OBJ_SUIT_TINT
        bne     :+
        lda     presented_palette_mode
        and     #3
        clc
        adc     #9
        bra     @PaletteIndex
:
        cmp     #WEAPON_OBJ_QUAD_TINT
        bne     :+
        lda     presented_palette_mode
        and     #3
        clc
        adc     #6                      ; Three pairs of damage/shot palettes precede Quad.
        bra     @PaletteIndex
:
.endif
        lsr
        lsr
        dec
        pha
        lda     presented_palette_mode
        and     #$0003
        asl
        clc
        adc     1,s
        plx
@PaletteIndex:
        xba
        asl
        clc
        adc     #.loword(WEAPON_OBJ_TINTS)
        tax
        stx     A1T7L
        ldx     #$2200
        stx     DMAP7
        ldx     #BSP_TEXTURE_PALETTE_UPLOAD_BYTES
        stx     DAS7L
        RW      a8
        lda     #^WEAPON_OBJ_TINTS
        sta     A1B7
        stz     CGADD
        lda     #$80
        sta     MDMAEN
@Done:
        rts
