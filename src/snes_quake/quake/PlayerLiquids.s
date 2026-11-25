; E1M1 SV_CheckWater. w_from is the eye, 22 units above the edict origin.
WalkCanSwim:
        stz     a:walk_water_level
        lda     #.loword(-1)
        sta     a:walk_liquid_type
        lda     a:w_from+4
        sec
        sbc     #45*16                  ; origin + mins.z + 1
        sta     a:w_swim_coords+4
        eor     #$8000
        cmp     #.loword(QC_LIQUID_CEILING ^ $8000)
        bcs     @Dry
        lda     a:w_from
        sta     a:w_swim_coords
        lda     a:w_from+2
        sta     a:w_swim_coords+2
        jsr     WalkSwimVolume
        bcc     @Dry
        sta     a:walk_liquid_type
        inc     a:walk_water_level
        lda     a:w_from+4
        sec
        sbc     #18*16                  ; origin + (mins.z + maxs.z)/2
        sta     a:w_swim_coords+4
        jsr     WalkSwimVolume
        bcc     @Dry
        inc     a:walk_water_level
        sec
        rts
@Dry:   clc
        rts

.ifdef PICKUP_BLEND
; Classify the eye after the accepted sweep. Waist-deep water still has a dry view.
WalkEyePalette:
        lda     a:w_from+4
        sta     a:w_swim_coords+4
        eor     #$8000
        cmp     #.loword(QC_LIQUID_CEILING ^ $8000)
        bcs     @Dry
        lda     a:w_from
        sta     a:w_swim_coords
        lda     a:w_from+2
        sta     a:w_swim_coords+2
        jsr     WalkSwimVolume
        bcc     @Dry
        cmp     #.loword(-4)
        beq     @Slime
        lda     #$20
        bra     @Store
@Slime: lda     #$40
        bra     @Store
@Dry:   lda     #0
@Store: sta     f:walk_eye_palette
        rts
.endif

; Each node contains two child offsets, an axial selector, three integer
; normal coefficients, and a signed 32-bit distance. Leaves keep Quake's
; contents codes. The signed-dot scratch occupies unused hub coordinate lanes.
WalkSwimVolume:
        ldx     #QC_LIQUID_ROOT
@Node:  lda     f:WalkLiquidNodes+4,x
        cmp     #6
        beq     @Oblique
        tay
        lda     a:w_swim_coords,y
        eor     #$8000
        cmp     f:WalkLiquidNodes+12,x
        bcs     @Front
@Back:  lda     f:WalkLiquidNodes+2,x
        bra     @Follow
@Front: lda     f:WalkLiquidNodes,x
@Follow:
        tax
        bpl     @Node
        cmp     #.loword(-1)
        beq     @Dry
        sec
        rts
@Dry:   clc
        rts
@Oblique:
        stz     a:w_swim_coords+6
        stz     a:w_swim_coords+8
        .repeat 3, Axis
        lda     f:WalkLiquidNodes+6+2*Axis,x
        beq     :+
        phx
        tax
        lda     a:w_swim_coords+2*Axis
        jsr     WalkMultiply
        plx
        clc
        lda     z:w_mul_low
        adc     a:w_swim_coords+6
        sta     a:w_swim_coords+6
        lda     z:w_mul_high
        adc     a:w_swim_coords+8
        sta     a:w_swim_coords+8
:
        .endrepeat
        lda     a:w_swim_coords+6
        cmp     f:WalkLiquidNodes+12,x
        lda     a:w_swim_coords+8
        sbc     f:WalkLiquidNodes+14,x  ; Relative Q4 dot fits a signed dword.
        bpl     :+
        jmp     @Back
:       jmp     @Front

; WaterMove damages on a strict one-second slime deadline. Entering any
; fluid clears dmgtime after that tick's damage and plays its body cue.
WalkLiquidEffects:
        lda     a:shot_player+QC_FIELD_HEALTH
        beq     @Done
        bmi     @Done
        lda     a:walk_water_level
        beq     @Outside
        lda     a:walk_liquid_type
        cmp     #.loword(-4)
        bne     @Entry
        lda     a:shot_player+QC_FIELD_RADSUIT_FINISHED
        bne     @Entry
        lda     a:walk_slime_damage_next
        cmp     a:grunt_clock
        bcs     @Entry
        lda     a:grunt_clock
        clc
        adc     #64
        sta     a:walk_slime_damage_next
        lda     a:walk_water_level
        xba                             ; 4 points at Q6 per level.
        jsl     ArmorEnvironmentDamage
        eor     #$ffff
        sec
        adc     a:shot_player+QC_FIELD_HEALTH
        sta     a:shot_player+QC_FIELD_HEALTH
        lda     #4
        sta     a:grunt_damage_flash
@Entry: lda     a:walk_in_water
        bne     @Done
        inc     a:walk_in_water
        stz     a:walk_slime_damage_next
        lda     #11
        ldx     a:walk_liquid_type
        cpx     #.loword(-4)
        bne     @Sound
        lda     #12
        bra     @Sound
@Outside:
        lda     a:walk_in_water
        beq     @Done
        stz     a:walk_in_water
        lda     #13
@Sound: jsl     GameplayPlayTrackLong
@Done:  rtl
