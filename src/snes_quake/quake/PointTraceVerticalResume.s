.macro SHOT_RESUME_RETURN
.ifdef PLAYABLE_E1M1_POINT_OBLIQUE
        rtl
.else
        rts
.endif
.endmacro

; Bias by the generated minimum before taking a cell index. The bounded
; difference is unsigned even when the physical coordinate is negative.
.macro SHOT_RESUME_INDEX minimum, cells, outside
        sec
        sbc     #.loword(minimum * $0400)
        cmp     #(cells * $0400)
        bcs     outside
        xba
        and     #$00fc
        lsr
        lsr
.endmacro

; Exact unchanged X/Y and a short downward segment fit the generated cell.
; Return the original root/visit count on any out-of-range coordinate.
ShotResumeVertical:
        lda     a:w_from
        cmp     a:w_to
        bne     @Root
        lda     a:w_from+2
        cmp     a:w_to+2
        bne     @Root
        lda     a:w_from+4
        sec
        sbc     a:w_to+4
        bvs     @Root
        cmp     #PLAYABLE_SHOT_RESUME_DELTA+1
        bcc     @Grid
@Root:
  .if .defined(PLAYABLE_E1M1_POINT_OBLIQUE) .and .defined(PLAYABLE_SHOT_PAIR_BYTES)
        jml     ::ShotResumePair
  .elseif .defined(PLAYABLE_E1M1_POINT_OBLIQUE)
        lda     #PLAYABLE_SHOT_HULL_ROOT
        SHOT_RESUME_RETURN
  .else
        lda     #WALK_TRACE_ROOT
        SHOT_RESUME_RETURN
  .endif

@Grid:
        ; Each Y row contains 18 columns with eight Z cells per column.
        lda     a:w_from+2
        SHOT_RESUME_INDEX PLAYABLE_SHOT_RESUME_MIN_Y, 28, @Root
        asl
        sta     z:w_mid
        .repeat 3
        asl
        .endrepeat
        adc     z:w_mid
        sta     z:w_mid
        lda     a:w_from
        SHOT_RESUME_INDEX PLAYABLE_SHOT_RESUME_MIN_X, 18, @Root
        adc     z:w_mid
  .ifdef PLAYABLE_SHOT_TAIL_PACKED_BYTES
        sta     z:w_mid                 ; Preserve the full column for the resume grid.
        lsr
        tax
@PointTailColumnMask:
        lda     f:ShotTailColumnMasks,x
        bcc     :+
    .repeat 4
        lsr
    .endrepeat
:
        and     #$000f
        tax
@PointTailDictionaryMask:
        lda     f:ShotTailMaskDictionary,x
        and     #$00ff
        sta     z:w_d0
        ldx     z:w_mid
  .else
        tax
    .ifdef PLAYABLE_SHOT_TAIL_MASK_BYTES
        .assert PLAYABLE_SHOT_TAIL_MASK_BYTES = PLAYABLE_SHOT_RESUME_COLUMNS, error, "Point tail mask shape changed"
@PointTailColumnMask:
        lda     f:ShotTailColumnMasks,x
        and     #$00ff                 ; Exclude the next column from the 16-bit BIT.
        sta     z:w_d0
    .endif
  .endif
        lda     f:::ShotResumeGrid,x
        and     #$00ff
        .repeat 3
        asl
        .endrepeat
        sta     z:w_mid
        lda     a:w_from+4
        SHOT_RESUME_INDEX PLAYABLE_SHOT_RESUME_MIN_Z, 8, @Root
  .ifdef PLAYABLE_SHOT_TAIL_MASK_BYTES
        tax
@PointTailHeightMask:
        lda     f:ShotTailHeightMask,x
        bit     z:w_d0
        beq     :+
        lda     #2
        tsb     a:w_secret_tail_state
:       txa
        clc
  .endif
        adc     z:w_mid
        tax
        lda     f:::ShotResumeGrid+PLAYABLE_SHOT_RESUME_COLUMNS,x
        and     #$00ff
        asl
        asl
        tax
        lda     f:::ShotResumeGrid+PLAYABLE_SHOT_RESUME_INDEX_BYTES+2,x
        tay
        lda     f:::ShotResumeGrid+PLAYABLE_SHOT_RESUME_INDEX_BYTES,x
        SHOT_RESUME_RETURN

.ifdef PLAYABLE_SHOT_TAIL_MASK_BYTES
ShotTailHeightMask:
        .byte 1, 2, 4, 8, 16, 32, 64, 128, 0
.endif

.delmacro SHOT_RESUME_INDEX
.delmacro SHOT_RESUME_RETURN
