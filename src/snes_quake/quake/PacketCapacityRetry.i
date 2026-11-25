.if BSP_RENDER_SCALE = 2 || BSP_QUAKEC_GAMEPLAY
PACKET_CAPACITY_MASK = PACKET_PAINTER_STACK
PACKET_CAPACITY_STATE = PACKET_CAPACITY_MASK + ((BSP_WORLD_FACE_BITSET_BYTES+1)&$FFFE)
PACKET_CAPACITY_RETURN = PACKET_CAPACITY_STATE + 16
.assert PACKET_CAPACITY_RETURN+2 <= PACKET_PAINTER_STACK_END, error, "Retry mask exceeds idle painter stack"
.endif

; PacketBegin's existing pointer initialization is moved, not duplicated.
.macro BSP_PACKET_CAPACITY_BEGIN
  .if BSP_RENDER_SCALE = 2 || BSP_QUAKEC_GAMEPLAY
        iwt     R0, #WORLD_VISIBILITY
        sm      (PACKET_VIS_POINTER), R0
PacketCapacityBeginCommon:
  .endif
.endmacro

.macro BSP_PACKET_CAPACITY_ORIGINAL_POINTER
  .if BSP_RENDER_SCALE <> 2 && !BSP_QUAKEC_GAMEPLAY
        iwt     R0, #WORLD_VISIBILITY
        sm      (PACKET_VIS_POINTER), R0
  .endif
.endmacro

.macro BSP_PACKET_CAPACITY_REJECT counter
  .if BSP_RENDER_SCALE = 2 || BSP_QUAKEC_GAMEPLAY
        .assert (counter <= $01FE) && ((counter & 1) = 0), error, "Capacity rejection slot no longer short"
        iwt     R7, #counter
        GSU_ABSOLUTE_GOTO PacketCapacityEnter
        .res 4, $01
  .else
        lm      R0, (counter)
        inc     R0
        sm      (counter), R0
        GSU_ABSOLUTE_GOTO PacketScanNextBit
  .endif
.endmacro

; The original decoder body is used unchanged in X2 and generated F3.
; Input R0=source vertex ordinal; output exact signed Q2 deltas R1/R2/R3.
.macro BSP_PACKET_LOAD_WORLD_VIEW_DELTAS
        move    R1, R0
        with    R1
        add     R1                       ; 2v
        with    R1
        add     R1                       ; 4v
        iwt     R4, #WORLD_VERTICES_ROM_ADDRESS
        with    R4
        add     R1
        move    R0, #WORLD_VERTICES_ROM_BANK
        romb
        GSU_SET_ROM_BUFFER_ADDRESS R4
        BSP_ROM_LOAD_SIGNED_BYTE R1
        BSP_ROM_LOAD_SIGNED_BYTE R2
        BSP_ROM_LOAD_SIGNED_BYTE R3
        BSP_ROM_LOAD_BYTE R7
        ; Decode signed Q2 = base*4 + the component's two residual bits.
        with    R1
        add     R1
        with    R1
        add     R1
        move    R0, R7
        with    R0
        and     #3
        with    R1
        add     R0
  .repeat 2
        with    R7
        lsr
  .endrepeat
        with    R2
        add     R2
        with    R2
        add     R2
        move    R0, R7
        with    R0
        and     #3
        with    R2
        add     R0
  .repeat 2
        with    R7
        lsr
  .endrepeat
        with    R3
        add     R3
        with    R3
        add     R3
        with    R7
        and     #3
        with    R3
        add     R7
        lm      R0, (PACKET_CAMERA_Q2_X)
        with    R1
        sub     R0                       ; dx
        lm      R0, (PACKET_CAMERA_Q2_Y)
        with    R2
        sub     R0                       ; dy
        lm      R0, (PACKET_CAMERA_Q2_Z)
        with    R3
        sub     R0                       ; dz
.endmacro
