; Four stationary loops share the existing DSP mixer. The original V0/V2
; foreground packets stay in the common cartridge image and retain their pitch.
; Only E1M1 replaces their previously permanent SPC sample regions.
.if .defined(PLAYABLE_MAP_ID) && .defined(QC_E1M1_TELEPORT)
.include "Data/QuakeIndustrialAmbient.i"
.import IndustrialBulkImage
.importzp IndustrialBulkSize
.import IndustrialCompBrr, IndustrialDroneBrr, IndustrialLightBrr, IndustrialSparkBrr
.import ShotgunDirectory, ShellPickupBrr, LandBrr, JumpBrr, SecretBrr, LiftButtonBrr
.import GruntBrr0, GruntBrr1, GruntBrr2, GruntBrr3, GruntBrr4, GruntBrr5
.import AxeSwingBrr, AxeWallBrr, TalkBrr, Swim1Brr, Swim2Brr, LandHardBrr, LandWaterBrr
.assert IndustrialCompBrr+INDUSTRIAL_BYTES_0 <= IndustrialSparkBrr, lderror, "Computer loop overlaps sparks"
.assert IndustrialSparkBrr+INDUSTRIAL_BYTES_3 <= SecretBrr, lderror, "Sparks escape the V0 region"
.assert IndustrialLightBrr+INDUSTRIAL_BYTES_2 <= LiftButtonBrr, lderror, "Lamp loop escapes the V2 region"
.assert IndustrialDroneBrr+INDUSTRIAL_BYTES_1 <= ShotgunBrr, lderror, "Drone overlaps weapon audio"
.pushseg
.segment "LORAM"
industrial_slot0: .res 1
industrial_slot1: .res 1
industrial_voice0_slot: .res 1
industrial_voice2_slot: .res 1
industrial_request: .res 1
industrial_dest: .res 2
industrial_bytes: .res 2
industrial_wave: .res 2
industrial_source: .res 2
industrial_mask: .res 1
industrial_packet: .res 1
industrial_offset: .res 4
industrial_left: .res 8
industrial_right: .res 8
industrial_previous: .res 8
industrial_delta: .res 6
industrial_square: .res 2
industrial_gain: .res 2
industrial_spot: .res 2
industrial_pan: .res 2
industrial_update: .res 2
.segment "BSP_CPU_WALK_RUN"
.macro PUBLISH_INDUSTRIAL_TOKEN
        lda     f:shotgun_sound_token
        inc
        sta     f:shotgun_sound_token
        sta     f:SMPIO3
:       cmp     f:SMPIO3
        bne     :-
.endmacro
; X and Y are preserved. Each input byte is consumed before its matching echo.
IndustrialCommand:
        pha                             ; Let an earlier nonblocking foreground command reach SPC.
        lda     f:shotgun_sound_token
:       cmp     f:SMPIO3
        bne     :-
        pla
IndustrialSend:
        RW_assume a8i16
        sta     f:SMPIO2
        PUBLISH_INDUSTRIAL_TOKEN
        rts
IndustrialHeader:
        RW_assume a8i16
        sta     f:industrial_mask
        lda     #GAMEPLAY_TRANSFER_SAMPLE
        jsr     IndustrialCommand
        .repeat 4, I
        lda     f:industrial_dest+I
        jsr     IndustrialSend
        .endrepeat
        lda     f:industrial_mask
        jmp     IndustrialSend
IndustrialWaitMSU:
        RW_assume a8i16
:       lda     f:$002000
        bmi     :-
        rts
IndustrialInit:
        RW_assume a8i16
        phx
        phy
        jsl     IndustrialInstallBulk
        RW      a16
        lda     #0
        sta     f:industrial_slot0
        sta     f:industrial_voice0_slot
        lda     #32                    ; Checked QPL1 header's ambient-bank pointer.
        sta     f:$002000
        lda     #0
        sta     f:$002002
        RW      a8
        jsr     IndustrialWaitMSU
        .repeat 4, I
        lda     f:$002001
        sta     f:industrial_offset+I
        .endrepeat
        RW      a16
        lda     f:industrial_offset
        sta     f:$002000
        lda     f:industrial_offset+2
        sta     f:$002002
        lda     #0
        sta     f:industrial_wave
        RW      a8
        jsr     IndustrialWaitMSU
@Wave:
        RW      a16
        lda     f:industrial_wave
        tax
        lda     f:IndustrialAddresses,x
        sta     f:industrial_dest
        lda     f:IndustrialSizes,x
        sta     f:industrial_bytes
        tay
        RW      a8
        lda     #0
        jsr     IndustrialHeader
@Data:  lda     f:$002001
        sta     f:industrial_packet
        eor     f:$002001
        cmp     #$ff
        beq     :+
        lda     #3
        jml     PlayableArchiveFatal
:       lda     f:industrial_packet
        jsr     IndustrialSend
        dey
        bne     @Data
        RW      a16
        lda     f:industrial_wave
        inc
        inc
        sta     f:industrial_wave
        cmp     #8
        bcc     @Wave
        ldx     #ShotgunDirectory+4
        ldy     #10*4
        lda     #ShellPickupBrr
        jsl     IndustrialDirectoryRange
        ldx     #ShotgunDirectory+13*4
        ldy     #3*4
        lda     #LandBrr
        jsl     IndustrialDirectoryRange
        ldx     #ShotgunDirectory+23*4
        ldy     #3*4
        lda     #LandBrr
        jsl     IndustrialDirectoryRange
        RW      a8
        ply
        plx
        rtl
IndustrialAddresses:
        .word IndustrialCompBrr, IndustrialDroneBrr, IndustrialLightBrr, IndustrialSparkBrr
IndustrialSizes:
        .word INDUSTRIAL_BYTES_0, INDUSTRIAL_BYTES_1, INDUSTRIAL_BYTES_2, INDUSTRIAL_BYTES_3

.pushseg
.segment "BSP_CPU_WALK_RESUME"
; V0 can use both buffers until V2 needs one. Then give V2 the slot V0
; is not playing, and keep it there so asynchronous body triggers cannot
; leave V0 overwriting a still-active V2 source.
IndustrialPrepareSound:
        RW_assume a8i16
        cmp     #1
        bcc     @Done
        cmp     #11
        bcs     @Done
        phx
        phy
        sta     f:industrial_request
        ldx     #0
        lda     f:industrial_voice2_slot
        cmp     #1
        beq     @SlotOne
        cmp     #2
        beq     @Selected
        lda     f:industrial_request
        cmp     f:industrial_slot0
        beq     @Selected
        cmp     f:industrial_slot1
        beq     @SlotOne
        ; On a miss, keep the packet that would take longer to reload.
        ; The transfer releases V0 before writing either slot.
        lda     f:industrial_slot0
        beq     @Selected
        lda     f:industrial_slot1
        beq     @SlotOne
        RW      a16
        jsr     IndustrialCachedPacketLength
        pha
        lda     f:industrial_slot0
        jsr     IndustrialCachedPacketLength
        cmp     1,s
        pla
        ldx     #0
        RW      a8
        bcc     @Selected
@SlotOne:
        inx
@Selected:
        txa
        inc
        sta     f:industrial_voice0_slot
        lda     #1                     ; Release the old V0 before replacing its packet.
        bra     IndustrialPrepareSelectedSlot
@Done:  rtl

IndustrialCachedPacketLength:
        RW_assume a16i16
        and     #$00ff
        dec
        asl
        asl
        tax
        lda     f:IndustrialForeground+2,x
        rts

IndustrialPrepareBody:
        RW_assume a8i16
        cmp     #$c0
        bcs     @Land
        .repeat 6
        lsr
        .endrepeat
        bra     @Body
@Land:  .repeat 4
        lsr
        .endrepeat
        sec
        sbc     #9                     ; $C/$D/$E become indices 3/4/5.
@Body:  clc
        adc     #11                    ; V2 packets follow the ten V0 packets.
        phx
        phy
        sta     f:industrial_request
        ldx     #0
        lda     f:industrial_voice2_slot
        bne     @KeepSlot
        lda     f:industrial_voice0_slot
        cmp     #2
        beq     @Selected
        bra     @SlotOne
@KeepSlot:
        cmp     #2
        bne     @Selected
@SlotOne:
        inx
@Selected:
        txa
        inc
        sta     f:industrial_voice2_slot
        lda     #4

IndustrialPrepareSelectedSlot:
        pha
        lda     f:industrial_request
        cmp     f:industrial_slot0,x
        beq     @Done
        sta     f:industrial_slot0,x
        RW      a16
        txa
        asl
        tax
        lda     f:IndustrialSlotAddresses,x
        pha
        ; A miss has a new SRCN, so neither foreground voice is reading
        ; this directory entry. Update it before entering the bulk transfer.
        lda     f:industrial_request
        and     #$ff
        dec
        tax
        lda     f:IndustrialDirectoryOffsets,x
        and     #$ff
        clc
        adc     #ShotgunDirectory
        tax
        ldy     #4
        pla
        jsl     IndustrialDirectoryRange
        lda     f:industrial_source
        sta     f:industrial_dest
        lda     f:industrial_request
        and     #$ff
        dec
        asl
        asl
        tax
        RW      a8
        pla
        jml     IndustrialLoadForeground
@Done:
        pla
        ply
        plx
        rtl

IndustrialSlotAddresses:
        .word ShellPickupBrr, LandBrr
IndustrialDirectoryOffsets:
        .byte 4, 8, 12, 16, 20, 24, 28, 32, 36, 40
        .byte 13*4, 14*4, 15*4, 23*4, 24*4, 25*4

IndustrialDirectoryRange:
        RW_assume a16i16
        sta     f:industrial_source
        txa
        sta     f:industrial_dest
        tya
        sta     f:industrial_bytes
        RW      a8
        lda     #0
        jsl     IndustrialHeaderFar
@Pointer:
        lda     f:industrial_source
        jsl     IndustrialSendFar
        lda     f:industrial_source+1
        jsl     IndustrialSendFar
        dey
        dey
        bne     @Pointer
        RW      a16
        rtl
.popseg

IndustrialColdImage = BSP_CPU_CODE_ADDRESS(__SMPCODE_LOAD__)
IndustrialHeaderFar:
        jsr     IndustrialHeader
        rtl
IndustrialSendFar:
        jsr     IndustrialSend
        rtl

.pushseg
.segment "BSP_CPU_BRR_INSTALL"
IndustrialInstallBulk:
        RW_assume a8i16
        RW      a16
        lda     #GAMEPLAY_TRANSFER_BULK_RUN
        sta     f:industrial_dest
        lda     #IndustrialBulkSize
        sta     f:industrial_bytes
        tay
        ldx     #0
        RW      a8
        lda     #0
        jsl     IndustrialHeaderFar
@Byte:  lda     f:IndustrialBulkImage,x
        jsl     IndustrialSendFar
        inx
        dey
        bne     @Byte
        rtl
.popseg

.pushseg
.segment "BSP_CPU_BRR_BULK"
IndustrialLoadForeground:
        RW_assume a8i16
        sta     f:industrial_mask
        RW      a16
        lda     f:IndustrialForeground+2,x
        sta     f:industrial_bytes
        tay
        lda     f:IndustrialForeground,x
        tax
        jsr     IndustrialBulkYield
        RW      a8
        lda     f:industrial_mask
        ora     #GAMEPLAY_TRANSFER_BULK
        jsl     IndustrialHeaderFar
        ; The extra strobe acknowledges the SPC's snapshot of both mailboxes.
        lda     #0
        sta     f:SMPIO2
        PUBLISH_INDUSTRIAL_TOKEN
        RW      a16
        lda     f:SMPIO0
        pha
        RW      a8
@Packet:
        ; VBlank leaves the audio mailboxes alone. The token publishes all
        ; three bytes together after the two data stores.
        RW      a16
        lda     f:IndustrialColdImage,x
        sta     f:SMPIO0
        RW      a8
        lda     f:IndustrialColdImage+2,x
        sta     f:SMPIO2
        lda     f:shotgun_sound_token
        inc
        sta     f:shotgun_sound_token
        sta     f:SMPIO3
        ; Advance while the SPC consumes the packet. The next port write
        ; and any renderer refill still wait for the current echo.
        .repeat 3
          inx
        .endrepeat
        .repeat 3
          dey
        .endrepeat
        beq     @FinishPacket
        xba                             ; Keep the token in B while classifying Y.
        tya
        and     #$3f
        beq     @RefillPacket
        xba
:       cmp     f:SMPIO3
        bne     :-
        bra     @Packet
@RefillPacket:
        xba
:       cmp     f:SMPIO3
        bne     :-
        RW      a16
        jsr     IndustrialBulkYield
        RW      a8
        bra     @Packet
@FinishPacket:
:       cmp     f:SMPIO3
        bne     :-
        ; Restore CPU-to-SPC values before releasing the transfer transaction.
        RW      a16
        pla
        sta     f:SMPIO0
        RW      a8
        PUBLISH_INDUSTRIAL_TOKEN
        ply
        plx
        rtl
IndustrialBulkYield:
        RW_assume a16i16
        QC_YIELD_COORDINATE_STREAM
        rts
.popseg
.delmacro PUBLISH_INDUSTRIAL_TOKEN
.macro INDUSTRIAL_PACKET Start, Finish
        .assert Finish > Start, lderror, "Foreground sample must be nonempty"
        .assert (Finish-Start) .mod 9 = 0, lderror, "Foreground sample must contain complete BRR blocks"
        .assert Finish-Start <= INDUSTRIAL_FOREGROUND_CAPACITY, lderror, "Foreground packet exceeds its cache slot"
        .word Start-__SMPCODE_RUN__, Finish-Start
.endmacro
IndustrialForeground:
        INDUSTRIAL_PACKET ShellPickupBrr, GruntBrr0
        INDUSTRIAL_PACKET GruntBrr0, GruntBrr1
        INDUSTRIAL_PACKET GruntBrr1, GruntBrr2
        INDUSTRIAL_PACKET GruntBrr2, GruntBrr3
        INDUSTRIAL_PACKET GruntBrr3, GruntBrr4
        INDUSTRIAL_PACKET GruntBrr4, GruntBrr5
        INDUSTRIAL_PACKET GruntBrr5, AxeSwingBrr
        INDUSTRIAL_PACKET AxeSwingBrr, AxeWallBrr
        INDUSTRIAL_PACKET AxeWallBrr, TalkBrr
        INDUSTRIAL_PACKET TalkBrr, SecretBrr
        INDUSTRIAL_PACKET JumpBrr, Swim1Brr
        INDUSTRIAL_PACKET Swim1Brr, Swim2Brr
        INDUSTRIAL_PACKET Swim2Brr, LiftButtonBrr
        INDUSTRIAL_PACKET LandBrr, LandHardBrr
        INDUSTRIAL_PACKET LandHardBrr, LandWaterBrr
        INDUSTRIAL_PACKET LandWaterBrr, ShotgunBrr
.include "quake/IndustrialSpatial.s"
.popseg
.endif
