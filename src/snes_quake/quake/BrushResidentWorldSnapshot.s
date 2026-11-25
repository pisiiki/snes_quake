; Briefly stop the mixed renderer to retain or restore the X2 opaque pixels.
.import AliasResidentWorldSaveResume:far, BrushResidentWorldRestoreResume:far
.assert .bankbyte(AliasResidentWorldSaveResume) = $70, lderror, "Alias snapshot resume must stay in FX RAM"
.assert .bankbyte(BrushResidentWorldRestoreResume) = $70, lderror, "Opaque restore resume must stay in FX RAM"

RESIDENT_WORLD_DMA_BYTES = $0400
.assert BSP_PLAYABLE_X2_STAGE_BYTES .mod RESIDENT_WORLD_DMA_BYTES = 0, error, "Resident world DMA requires full tile rows"

.pushseg
.segment "HIRAM"
BrushResidentWorldSnapshot: .res BSP_PLAYABLE_X2_STAGE_BYTES
.assert .bankbyte(BrushResidentWorldSnapshot) = $7E && .bankbyte(*-1) = $7E, lderror, "Opaque snapshot must fit in WRAM bank $7E"

.segment "BSP_QUAKEC"
; On a snapshot request, service it and resume the stopped renderer.
; Otherwise return the normal lightmap request in A with carry clear.
; DMA6 and the WRAM port are owned by the foreground job throughout the copy.
ServiceBrushResidentWorldSnapshot:
        RW_assume a16i16
        lda     f:GSU_DATA_BASE+GSU_RESIDENT_WORLD_COMMAND
        cmp     #RESIDENT_WORLD_RESTORE
        beq     @Restore
        cmp     #RESIDENT_WORLD_SAVE
        beq     @Save
        lda     f:WorldLightmapStreamBank
        clc
        rtl
@Save:
        ldx     #.loword(AliasResidentWorldSaveResume)
        lda     #$8000
        bra     @Configure
@Restore:
        ldx     #.loword(BrushResidentWorldRestoreResume)
        lda     #$8080
@Configure:
        sta     DMAP6
        stz     A1T6L
        lda     #.loword(BrushResidentWorldSnapshot)
        sta     WMADDL
        RW      a8
        stz     WMADDH
        lda     #$70
        sta     A1B6
        ldy     #BSP_PLAYABLE_X2_STAGE_BYTES / RESIDENT_WORLD_DMA_BYTES
@WaitChunk:
        ; A 1 KiB DMA takes six scanlines. Keep input and video NMI enabled,
        ; and defer each chunk only in the band that could cross its boundary.
        lda     STAT78
        lda     SLHV
        lda     OPVCT
        pha
        lda     OPVCT
        and     #$01
        xba
        pla
        RW      a16
        cmp     #216
        bcc     @Copy
        cmp     #228
        bcs     @Copy
        RW      a8
        bra     @WaitChunk
@Copy:
        RW_forced a16i16
        lda     #RESIDENT_WORLD_DMA_BYTES
        sta     DAS6L
        RW      a8
        lda     #$40
        sta     MDMAEN
        dey
        bne     @WaitChunk
        RW      a16
        lda     #2
        sta     f:GSU_DATA_BASE+GSU_RESIDENT_WORLD_COMMAND
        stx     FX3_R15
        sec
        rtl
.popseg
