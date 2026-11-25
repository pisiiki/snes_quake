; Signed packed face plane dot product. Inputs: R14=plane ROM address.
.if BSP_QUAKEC_GAMEPLAY
        ; Use the same signed Q2 position for face admission and projection.
        BSP_ROM_LOAD_SIGNED_BYTE R6
        lm      R0, (PACKET_CAMERA_Q2_X)
        lmult
        move    R12, R4
        BSP_ROM_LOAD_SIGNED_BYTE R6
        lm      R0, (PACKET_CAMERA_Q2_Y)
        lmult
        with    R12
        add     R4
        BSP_ROM_LOAD_SIGNED_BYTE R6
        lm      R0, (PACKET_CAMERA_Q2_Z)
        lmult
        with    R12
        add     R4
        BSP_ROM_LOAD_WORD R10
.elseif BSP_RENDER_SCALE = 2
        ; Camera bytes are exact: 4*sum(c*n) mod65536 equals the Q2 dot.
        BSP_ROM_LOAD_SIGNED_BYTE R0
        lm      R6, (PACKET_CAMERA_X)
        mult    R6
        move    R12, R0
        BSP_ROM_LOAD_SIGNED_BYTE R0
        lm      R6, (PACKET_CAMERA_Y)
        mult    R6
        with    R12
        add     R0
        BSP_ROM_LOAD_SIGNED_BYTE R0
        lm      R6, (PACKET_CAMERA_Z)
        mult    R6
        with    R12
        add     R0
        BSP_ROM_LOAD_WORD R10
        with    R12
        add     R12
        with    R12
        add     R12
.else
        BSP_ROM_LOAD_SIGNED_BYTE R7
        BSP_ROM_LOAD_SIGNED_BYTE R8
        BSP_ROM_LOAD_SIGNED_BYTE R9
        BSP_ROM_LOAD_WORD R10
        ; Preserve the original F3 signed-word product sequence.
        lm      R0, (PACKET_CAMERA_Q2_X)
        move    R6, R7
        with    R0
        lmult
        move    R12, R4
        lm      R0, (PACKET_CAMERA_Q2_Y)
        move    R6, R8
        with    R0
        lmult
        with    R12
        add     R4
        lm      R0, (PACKET_CAMERA_Q2_Z)
        move    R6, R9
        with    R0
        lmult
        with    R12
        add     R4
.endif
