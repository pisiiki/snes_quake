.segment "HDMA_WARP_CODE"
.macro HDMA_BAND_REGISTERS routine, scale
routine:
        stz     z:hdma_fault-hdma_work
        lda     hdma_band
        cmp     #WARP_DEPTH_SPLIT
        bne     :+
        .repeat 6, word
          lda   hdma_bottom+word*2
          sta   z:hdma_accum-hdma_work+20+word*2
          lda   hdma_bottom_steps+word*2
          sta   z:hdma_steps-hdma_work+20+word*2
        .endrepeat
:
        .repeat 3, row
          lda   z:hdma_accum-hdma_work+row*4+1
          sta   z:hdma_ray-hdma_work+row*2
          lda   z:hdma_accum-hdma_work+(5+row)*4+1
          sta   z:hdma_t-hdma_work+row*2
        .endrepeat
        lda     z:hdma_ray-hdma_work+4
        cmp     #513
        bcs     :+
        jmp     HdmaBlankBand
:
        cmp     #6144
        bcc     :+
        jmp     HdmaBlankBand
:
        asl
        tax
        lda     f:HdmaLog,x
        sta     z:hdma_log_z-hdma_work
        lda     #4096
        sec
        sbc     z:hdma_t-hdma_work+4
        bvc     :+
        jmp     HdmaBlankBand
:
        bpl     :+
        jmp     HdmaBlankBand
:
        bne     :+
        jmp     HdmaBlankBand
:
        asl
        tax
        lda     f:HdmaLog,x
        sec
        sbc     z:hdma_log_z-hdma_work
        sta     z:hdma_center_factor-hdma_work
        sec
        sbc     z:hdma_log_z-hdma_work
        clc
        adc     #6569
        sta     z:hdma_log_factor-hdma_work
        .repeat 2, row
          lda   z:hdma_accum-hdma_work+(3+row)*4+1
          jsr   scale
          .if row = 0
            neg
          .endif
          sta   z:hdma_registers-hdma_work+row*4
          lda   hdma_cofactor_constants+row*2
          jsr   scale
          .if row = 0
            neg
          .endif
          sta   z:hdma_registers-hdma_work+row*4+2
.if BSP_SOUND_ENABLED
          jsl   QuakeSoundWarpPacket
.endif
        .endrepeat
        lda     z:hdma_center_factor-hdma_work
        sta     z:hdma_log_factor-hdma_work
        .repeat 2, row
          lda   z:hdma_ray-hdma_work+row*2
          jsr   scale
          clc
          adc   z:hdma_t-hdma_work+row*2
          bvc   :+
          jmp   HdmaBlankBand
:
          .if row = 1
            neg
          .endif
          ; Keep the projected Q12 coordinate. The fixed-pivot phase folds
          ; its x4 conversion and final /256 rounding into a signed /64.
          sta   z:hdma_origin-hdma_work+row*4
        .endrepeat
.if BSP_SOUND_ENABLED
        jsl     QuakeSoundWarpPacket
.endif
        lda     z:hdma_fault-hdma_work
        beq     :+
        jmp     HdmaBlankBand
:
        jsr     HdmaChoosePhase
        rts

.endmacro
HDMA_BAND_REGISTERS HdmaBandRegisters, HdmaLogScale
HDMA_BAND_REGISTERS HdmaOverscanBandRegisters, HdmaOverscanLogScale

HdmaBlankBand:
        stz     z:hdma_registers-hdma_work
        stz     z:hdma_registers-hdma_work+2
        stz     z:hdma_registers-hdma_work+4
        stz     z:hdma_registers-hdma_work+6
        lda     #96
        sta     z:hdma_registers-hdma_work+8
        sta     z:hdma_registers-hdma_work+10
        sta     z:hdma_registers-hdma_work+12
        sta     z:hdma_registers-hdma_work+14
        rts

HdmaIdentityBand:
        lda     #.loword(-85)
        sta     z:hdma_registers-hdma_work
        stz     z:hdma_registers-hdma_work+2
        stz     z:hdma_registers-hdma_work+4
        lda     #85
        sta     z:hdma_registers-hdma_work+6
        sta     z:hdma_registers-hdma_work+8
        sta     z:hdma_registers-hdma_work+12
        stz     z:hdma_registers-hdma_work+10
        stz     z:hdma_registers-hdma_work+14
        rts
