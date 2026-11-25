; The X3 world only owns the first 9 KiB of its producer slot. Fill the
; shared slot's unused tail with checked mask rows while NMI is enabled.
.pushseg
.segment "BSP_CPU_X3_WEAPON_VIEW"
.assert X3_WEAPON_FIRST_POSE = BSP_WEAPON_NAIL_IDLE, error, "X3 weapon pose order changed"
X3_WEAPON_PACKET_BYTES = $300
.assert BSP_PLAYABLE_X3_STAGE_BYTES+X3_WEAPON_PACKET_BYTES <= BSP_FRAME_STAGE_BYTES, error, "X3 weapon staging tail exceeds the producer slot"
.assert ^StagedFrame0 = ^StagedFrame1, lderror, "X3 staging slots must share a WRAM bank"
.assert ^StagedFrame0 = $7E, lderror, "X3 weapon stage uses bank $7E"

; A is the zero-based software pose. Hardware poses stay in OBJ.
.macro X3_WEAPON_INDEX
        lda     f:staging_weapon_frame
        and     #$00ff
        sec
        sbc     #X3_WEAPON_FIRST_POSE
        cmp     #X3_WEAPON_POSE_COUNT
        bcc     :+
        rtl
:
.endmacro

X3WeaponPrepare:
        RW_assume a16i16
        X3_WEAPON_INDEX
        sta     f:nail_view_mask
        .repeat 3
        asl
        .endrepeat
        clc
        adc     f:nail_view_mask       ; Nine 256-byte units per pose.
        sta     f:nail_view_mask
        lda     f:staging_weapon_frame
        xba
        and     #$00ff
        clc
        adc     #BSP_WEAPON_BOB_LIMIT
        and     #7
        asl
        tax
        lda     f:X3WeaponPhaseBlocks,x
        clc
        adc     f:nail_view_mask
        xba                            ; Slot index ? $300, before pairing.
        asl
        pha
        lda     #.hiword(X3_WEAPON_SEEK)
        adc     #0
        sta     f:playable_archive_seek+2
        pla
        clc
        adc     #.loword(X3_WEAPON_SEEK)
        sta     f:playable_archive_seek
        bcc     :+
        lda     f:playable_archive_seek+2
        inc
        sta     f:playable_archive_seek+2
:
        jsl     X3WeaponSeekLong
        lda     f:producer_slot
        beq     :+
        lda     #.loword(StagedFrame1)+BSP_PLAYABLE_X3_STAGE_BYTES
        bra     :++
:       lda     #.loword(StagedFrame0)+BSP_PLAYABLE_X3_STAGE_BYTES
:       sta     f:PlayableCopyDestination
        lda     #X3_WEAPON_PACKET_BYTES
        sta     f:PlayableCopyLength
        RW      a8
        lda     #^StagedFrame0
        sta     f:PlayableCopyDestination+2
        ldx     #0
        jsl     PlayableCopyKernel
        bcc     X3WeaponBadPacket
        lda     #0
        sta     f:playable_archive_busy
X3WeaponPrepared:
        RW      a16
        rtl
X3WeaponBadPacket:
        RW_forced a8i16
        lda     #10
        jml     PlayableArchiveFatal

; DMA copied the unmodified X3 world into this slot's prefix. The paired
; read touched only the tail, so compose one bounded row at a time.
StageX3SoftwareWeapon:
        RW_assume a16i16
        X3_WEAPON_INDEX
        lda     f:staging_weapon_frame
        xba
        and     #$00ff
        clc
        adc     #BSP_WEAPON_BOB_LIMIT
        and     #7
        asl
        tax
        lda     f:X3WeaponBobOffsets,x
        sta     f:nail_view_bob
        lda     f:producer_slot
        beq     :+
        lda     #.loword(StagedFrame1)
        bra     :++
:       lda     #.loword(StagedFrame0)
:       sta     f:nail_view_slot
        clc
        adc     #BSP_PLAYABLE_X3_STAGE_BYTES
        tax
        phb
        pea     $7e7e
        plb
        plb
        lda     a:$0000,x
        beq     @Release
        cmp     #((X3_WEAPON_PACKET_BYTES-2)/11)+1
        bcc     :+
        jmp     X3WeaponBadPacket
:
        sta     a:nail_view_rows
        inx
        inx
@Row:
        lda     a:$0000,x
        and     #$000e
        clc
        adc     a:nail_view_bob
        phx
        tax
        lda     f:X3WeaponBobDeltas,x
        plx
        clc
        adc     a:$0000,x
        cmp     #(BSP_PLAYABLE_X3_STAGE_BYTES-$31)
        bcc     :+
        jmp     X3WeaponBadPacket
:
        clc
        adc     a:nail_view_slot
        tay
        lda     a:$0002,x
        and     #$00ff
        sta     a:nail_view_mask
        xba
        ora     a:nail_view_mask
        eor     #$ffff
        sta     a:nail_view_mask
        .repeat 4, plane
        lda     a:16*plane,y
        and     a:nail_view_mask
        ora     a:$0003+2*plane,x
        sta     a:16*plane,y
        .endrepeat
        txa
        clc
        adc     #11
        tax
        dec     a:nail_view_rows
        bne     @Row
@Release:
        plb
@Done:
X3SoftwareWeaponStageComplete:
        rtl

X3WeaponPhaseBlocks:
        .word 0,3,6,0,3,6,0,0
X3WeaponBobOffsets:
        .word 0,0,0,16,16,16,32,16
X3WeaponBobDeltas:
        .repeat 3, shift
        .repeat 8, physical
        .word .loword(((((physical*3 & 7)+2*(shift-1)+8)/8)-1)*$0400 + 2*((((physical*3 & 7)+2*(shift-1))*3 & 7)-physical))
        .endrepeat
        .endrepeat
.delmacro X3_WEAPON_INDEX
.popseg
