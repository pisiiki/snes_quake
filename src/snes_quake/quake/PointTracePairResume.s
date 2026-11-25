.assert PLAYABLE_SHOT_PAIR_X_CELLS = 10, error, "Point prefix X stride changed"
.assert PLAYABLE_SHOT_PAIR_Z_CELLS = 4, error, "Point prefix Z stride changed"

; Called by JML from the original vertical lookup. Keep its JSL return frame,
; and leave the full visit budget in Y until both endpoints are in range.
ShotResumePair:
        ldx     #0
        jsr     ShotPairEndpoint
        bcs     @Root
        beq     @Root
        sta     z:w_d0
        ldx     #6
        jsr     ShotPairEndpoint
        bcs     @Root
        cmp     z:w_d0
        bne     @Root
        tax
        ldy     #PLAYABLE_SHOT_PAIR_VISITS
        lda     f:ShotPairNodes,x
        rtl
@Root:
        lda     #PLAYABLE_SHOT_HULL_ROOT
        rtl

.macro SHOT_PAIR_AXIS offset, minimum, cells, outside
        lda     a:w_from+offset,x
        sec
        sbc     #.loword(minimum * $0800)
        cmp     #(cells * $0800)
        bcs     outside
        xba
        and     #$00f8                 ; Cell number times eight.
.endmacro

ShotPairEndpoint:
        SHOT_PAIR_AXIS 2, PLAYABLE_SHOT_PAIR_Y_MIN, PLAYABLE_SHOT_PAIR_Y_CELLS, @Outside
        sta     z:w_mid
        asl
        asl
        adc     z:w_mid                ; Y cell times 40, with carry clear.
        sta     z:w_mid
        SHOT_PAIR_AXIS 0, PLAYABLE_SHOT_PAIR_X_MIN, PLAYABLE_SHOT_PAIR_X_CELLS, @Outside
        lsr
        adc     z:w_mid                ; Add X cell times four.
        sta     z:w_mid
        SHOT_PAIR_AXIS 4, PLAYABLE_SHOT_PAIR_Z_MIN, PLAYABLE_SHOT_PAIR_Z_CELLS, @Outside
        lsr
        lsr
        lsr
        adc     z:w_mid
        tax
        lda     f:ShotPairCells,x
        and     #$00ff
@Outside:
        rts
.delmacro SHOT_PAIR_AXIS

ShotPairCells:
        .incbin "Data/PlayableShotPair.bin"
        .assert *-ShotPairCells = PLAYABLE_SHOT_PAIR_BYTES, error, "Point prefix asset length changed"
ShotPairNodes = ShotPairCells + PLAYABLE_SHOT_PAIR_CELL_BYTES
