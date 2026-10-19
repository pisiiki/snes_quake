; CPU-only table builder. The active HDMA buffer is never modified here.
.segment "HDMA_WARP_CODE"
BuildHdmaWarp:
        RW_assume a16i16
        phd
        lda     #.loword(hdma_work)
        tcd
        stz     z:hdma_fault-hdma_work
        stz     hdma_camera_fault
        stz     hdma_neutral
        ldx     #8
@Compare:
        lda     hdma_source_camera,x
        cmp     hdma_target_camera,x
        bne     @Camera
        dex
        dex
        bpl     @Compare
        lda     hdma_build_overscan
        bne     @Camera                 ; Equal poses still need the fixed zoom.
        inc     hdma_neutral
        bra     @Begin
@Camera:
        jsr     HdmaCameraTerms
        lda     hdma_build_overscan
        beq     @NormalRecurrences
        jsr     HdmaPrepareOverscanRecurrences
        bra     @RecurrencesReady
@NormalRecurrences:
        jsr     HdmaPrepareRecurrences
@RecurrencesReady:
        lda     z:hdma_fault-hdma_work
        sta     hdma_camera_fault
@Begin:
        lda     #648
        sec
        sbc     hdma_active
        sta     hdma_build_base
        sta     hdma_table_offset
        stz     hdma_band
        lda     #1
        sta     hdma_build_busy
        pld
        rtl

BuildHdmaWarpBand:
        RW_assume a16i16
        phd
        lda     #.loword(hdma_work)
        tcd
        lda     hdma_build_overscan
        beq     @Normal
        jsr     HdmaBuildOneOverscanBand
        bra     @Done
@Normal:
        jsr     HdmaBuildOneBand
@Done:
        pld
        rtl

; One direct-page setup per interrupt slice, with no foreground ABI saves
; between bands. A fixed count bounds this loop independently of other work.
BuildHdmaWarpBands:
        RW_assume a16i16
        phd
        lda     #.loword(hdma_work)
        tcd
        lda     hdma_build_overscan
        bne     @Overscan
@Next:
        jsr     HdmaBuildOneBand
        dec     hdma_deadline_bands
        bne     @Next
        pld
        rtl

@Overscan:
        jsr     HdmaBuildOneOverscanBand
        dec     hdma_deadline_bands
        bne     @Overscan
        pld
        rtl

.macro HDMA_BUILD_ONE_BAND routine, projection
routine:
        lda     hdma_neutral
        beq     @Project
        jsr     HdmaIdentityBand
        bra     @Store
@Project:
        lda     hdma_camera_fault
        beq     :+
        jsr     HdmaBlankBand
        bra     @Store
:
        jsr     projection
@Store:
        jsr     HdmaAdvanceRecurrences
.if BSP_SOUND_ENABLED
        jsl     QuakeSoundWarpPacket
.endif
        ldx     hdma_table_offset
        .repeat 4, channel
          lda   z:hdma_registers-hdma_work+channel*4
          sta   hdma_tables+channel*162+1,x
          lda   z:hdma_registers-hdma_work+channel*4+2
          sta   hdma_tables+channel*162+3,x
        .endrepeat
        RW      a8
        lda     #7
        .repeat 4, channel
          sta   hdma_tables+channel*162,x
        .endrepeat
        RW      a16
        lda     hdma_table_offset
        clc
        adc     #5
        sta     hdma_table_offset
        inc     hdma_band
        inc     hdma_band
        lda     hdma_band
        cmp     #64
        beq     @Complete
        rts
@Complete:
        ldx     hdma_build_base
        lda     #0
        .repeat 4, channel
          sta   hdma_tables+channel*162+160,x
        .endrepeat
        inc     hdma_build_count
        stz     hdma_build_busy
        rts

.endmacro
HDMA_BUILD_ONE_BAND HdmaBuildOneBand, HdmaBandRegisters
HDMA_BUILD_ONE_BAND HdmaBuildOneOverscanBand, HdmaOverscanBandRegisters
