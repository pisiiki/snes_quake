.assert WALK_REGISTER_TRACE, error, "Walk resume requires register traversal"
.assert WALK_MAX_NODES_PER_TRACE >= 64, error, "Walk resume debt can exhaust the visit limit"

.pushseg
.segment "BSP_CPU_WALK_RESUME"

.macro WALK_RESUME_AXIS axis, bias, extent
        lda     a:w_from+axis
        eor     a:w_to+axis
        and     #$F000
        bne     @Root
        lda     a:w_from+axis
        clc
        adc     #bias
        cmp     #extent
        bcs     @Root
        xba
        and     #$00F0
.endmacro

; The caller selected the solid explobox hull. All positions are signed Q4.
; The grid proves the same child for both endpoints at every skipped node.
WalkResumePrefix:
        RW_assume a16i16
        WALK_RESUME_AXIS 2, $7000, $E000
        lsr
        lsr
        lsr
        tax
        lda     f:WalkResumeRows,x
        sta     z:w_mid
        WALK_RESUME_AXIS 0, $5000, $A000
        lsr
        lsr
        adc     z:w_mid
        sta     z:w_mid

        ; The certified Z interval extends 18 Quake units below each cell.
        lda     a:w_from+4
        clc
        adc     #$2000
        cmp     #$4000
        bcs     @Root
        and     #$F000
        sta     z:w_limit
        lda     a:w_to+4
        clc
        adc     #$2120
        sec
        sbc     z:w_limit
        cmp     #$1120
        bcs     @Root
        lda     z:w_limit
        xba
        .repeat 4
        lsr
        .endrepeat
        adc     z:w_mid
        tax
        lda     f:WalkResumeGrid,x
        and     #$00FF
        asl
        asl
        tax
        tya
        sec
        sbc     f:WalkResumeGrid+560+2,x
        tay
        lda     f:WalkResumeGrid+560,x
        rtl
@Root:
        lda     #PLAYABLE_WALK_HULL_EXPLOBOX_ROOT
        rtl
.delmacro WALK_RESUME_AXIS

WalkResumeRows:
        .repeat 14, row
        .word row * 40
        .endrepeat
WalkResumeGrid:
        .incbin "Data/PlayableWalkResume.bin"
.assert * - WalkResumeGrid = PLAYABLE_E1M1_WALK_RESUME_BYTES, error, "Walk resume grid size changed"

.popseg
