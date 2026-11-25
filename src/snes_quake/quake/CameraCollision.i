; One packed collision lookup, instantiated with independent live/forecast scratch.
; Carry set means solid; caller supplies clamped native Q4 XYZ.
.macro COLLISION_MULTIPLY_CONSTANT Factor, ScratchCell
        .assert Factor > 0 .and Factor <= $FFFF, error, "Invalid collision multiplier"
        sta     ScratchCell
        .repeat 15, Bit
        .if (Factor >> (15-Bit)) <> 0
        asl
        .if (Factor & (1 << (14-Bit))) <> 0
        clc
        adc     ScratchCell
        .endif
        .endif
        .endrepeat
.endmacro

.macro CAMERA_POINT_LOOKUP PosX, PosY, PosZ, IndexX, IndexY, Cell, Offset, Column, ZByte, Mask
        RW_assume a16i16
        lda     PosZ
        xba
        and     #$00FF
        sec
        sbc     #.lobyte(BSP_COLLISION_MIN_Z)
        and     #$00FF
        sta     ZByte

        lda     PosX
        xba
        and     #$00FF
        sec
        sbc     #.lobyte(BSP_COLLISION_MIN_X)
        and     #$00FF
        sta     IndexX
        lda     PosY
        xba
        and     #$00FF
        sec
        sbc     #.lobyte(BSP_COLLISION_MIN_Y)
        and     #$00FF
        sta     IndexY

        ; cell = y*generated_width + x.
        lda     IndexY
        COLLISION_MULTIPLY_CONSTANT BSP_COLLISION_X_COUNT, Cell
        clc
        adc     IndexX
        sta     Cell

        ; Split cell into q*8+r before multiplying by the generated bit width.
        ; This keeps the intermediate below 64 KiB even when the bit offset
        ; itself exceeds 16 bits: byte=q*bits+floor(r*bits/8).
        and     #$0007
        sta     IndexX
        lda     Cell
        lsr
        lsr
        lsr
        COLLISION_MULTIPLY_CONSTANT BSP_COLLISION_COLUMN_ID_BITS, Cell
        sta     Column

        lda     IndexX
        COLLISION_MULTIPLY_CONSTANT BSP_COLLISION_COLUMN_ID_BITS, Cell
        sta     Offset
        lsr
        lsr
        lsr
        clc
        adc     Column
        tax
        lda     f:BSP_COLLISION_MAP_ROM,x
        sta     Cell
        lda     Offset
        and     #$0007
        tax
        beq     @ColumnNoShift
        lda     Cell
@ColumnShift:
        lsr
        dex
        bne     @ColumnShift
        bra     @ColumnReady
@ColumnNoShift:
        lda     Cell
@ColumnReady:
        and     #((1 << BSP_COLLISION_COLUMN_ID_BITS) - 1)
        sta     Column

        ; Dictionary bit = column_id*generated_depth + Z.
        COLLISION_MULTIPLY_CONSTANT BSP_COLLISION_Z_COUNT, Cell
        clc
        adc     ZByte
        sta     Cell
        and     #$0007
        tax
        RW      a8
        lda     f:BSPCollisionBitMasks,x
        sta     Mask
        RW      a16
        lda     Cell
        lsr
        lsr
        lsr
        tax
        RW      a8
        lda     f:BSP_COLLISION_DICTIONARY_ROM,x
        and     Mask
        clc
        beq     @Result
        sec
@Result:
        ; Both lookup outcomes must execute the runtime width restore. A plain
        ; RW transition on separate branches lets assembler state from the
        ; first branch suppress the REP needed by the empty branch.
        RW_forced a16i16
        rts

.endmacro
