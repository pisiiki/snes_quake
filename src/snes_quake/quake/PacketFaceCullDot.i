.ifdef PLAYABLE_AXIAL_FACE_FLAGS
        ibt     R1, #$1C
        from    R6
        and     R1
        bne     PacketScanAxialFacePlane
        lsr                             ; 4 * tag becomes a word offset.
        jal     PacketGeneralFacePlaneDot
        nop
        bra     PacketScanCompareFacePlane
        nop
PacketScanAxialFacePlane:
        iwt     R9, #GSU_PACKET_FACE_CAMERA_POSITIVE-2
        with    R9
        add     R0
        movew   R12, (R9)
        with    R4
        add     #3
        GSU_SET_ROM_BUFFER_ADDRESS R4
        BSP_ROM_LOAD_WORD R10
PacketScanCompareFacePlane:
.else
        GSU_SET_ROM_BUFFER_ADDRESS R4
.include "quake/PacketFacePlaneDot.i"
.endif
