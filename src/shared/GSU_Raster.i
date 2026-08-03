; Shared 2D SuperFX triangle raster helpers.
;
; The including file must define PROJECTED as an address containing packed x,y
; byte pairs. Define GSU_RASTER_PROJECTED_WORDS for signed x,y word pairs.
; Optional GSU_RASTER_SCRATCH selects the scratch area.

.ifndef __GSU_RASTER_I__
__GSU_RASTER_I__ = 1

.ifndef PROJECTED
  .assert 0, error, "PROJECTED must be defined before including GSU_Raster.i"
.endif

.ifndef GSU_RASTER_SCRATCH
GSU_RASTER_SCRATCH = $5F80
.endif

GSU_TRI_X0          = GSU_RASTER_SCRATCH + $00
GSU_TRI_Y0          = GSU_RASTER_SCRATCH + $02
GSU_TRI_X1          = GSU_RASTER_SCRATCH + $04
GSU_TRI_Y1          = GSU_RASTER_SCRATCH + $06
GSU_TRI_X2          = GSU_RASTER_SCRATCH + $08
GSU_TRI_Y2          = GSU_RASTER_SCRATCH + $0A
GSU_TRI_SPLIT_X     = GSU_RASTER_SCRATCH + $0C
GSU_TRI_SPLIT_Y     = GSU_RASTER_SCRATCH + $0E

GSU_EDGE0_X         = GSU_RASTER_SCRATCH + $10
GSU_EDGE0_DX        = GSU_RASTER_SCRATCH + $12
GSU_EDGE0_DY        = GSU_RASTER_SCRATCH + $14
GSU_EDGE0_ERR       = GSU_RASTER_SCRATCH + $16
GSU_EDGE0_SX        = GSU_RASTER_SCRATCH + $18
GSU_EDGE1_X         = GSU_RASTER_SCRATCH + $20
GSU_EDGE1_DX        = GSU_RASTER_SCRATCH + $22
GSU_EDGE1_DY        = GSU_RASTER_SCRATCH + $24
GSU_EDGE1_ERR       = GSU_RASTER_SCRATCH + $26
GSU_EDGE1_SX        = GSU_RASTER_SCRATCH + $28
GSU_SCAN_Y          = GSU_RASTER_SCRATCH + $30
GSU_SCAN_COUNT      = GSU_RASTER_SCRATCH + $32

.macro GSU_RASTER_LOAD_VERTEX xreg, yreg, index
  .ifdef GSU_RASTER_PROJECTED_WORDS
        iwt     R10, #(PROJECTED + (index * 4))
        movew   xreg, (R10)
        inc     R10
        inc     R10
        movew   yreg, (R10)
  .else
        move    xreg, #0
        move    yreg, #0
        iwt     R10, #(PROJECTED + (index * 2))
        moveb   xreg, (R10)
        inc     R10
        moveb   yreg, (R10)
  .endif
.endmacro

.macro GSU_RASTER_LOAD_TRI_VERTEX xaddr, yaddr, index
        GSU_RASTER_LOAD_VERTEX R0, R1, index
        sm      (xaddr), R0
        sm      (yaddr), R1
.endmacro

.macro GSU_RASTER_SWAP_WORDS addr_a, addr_b
        lm      R0, (addr_a)
        lm      R1, (addr_b)
        sm      (addr_a), R1
        sm      (addr_b), R0
.endmacro

.macro GSU_RASTER_SORT_VERTEX_PAIR ax, ay, bx, by
        .local NoSwap
        lm      R0, (ay)
        lm      R1, (by)
        with    R0
        sub     R1
        bmi     NoSwap
        nop
        beq     NoSwap
        nop
        GSU_RASTER_SWAP_WORDS ax, bx
        GSU_RASTER_SWAP_WORDS ay, by
NoSwap:
.endmacro

.macro GSU_RASTER_SORT_TRIANGLE_VERTICES
        GSU_RASTER_SORT_VERTEX_PAIR GSU_TRI_X0, GSU_TRI_Y0, GSU_TRI_X1, GSU_TRI_Y1
        GSU_RASTER_SORT_VERTEX_PAIR GSU_TRI_X1, GSU_TRI_Y1, GSU_TRI_X2, GSU_TRI_Y2
        GSU_RASTER_SORT_VERTEX_PAIR GSU_TRI_X0, GSU_TRI_Y0, GSU_TRI_X1, GSU_TRI_Y1
.endmacro

.macro GSU_RASTER_EDGE_INIT xaddr, dxaddr, dyaddr, erraddr, sxaddr, x0addr, y0addr, x1addr, y1addr
        .local PositiveDx, DxDone
        lm      R0, (x0addr)
        sm      (xaddr), R0

        lm      R0, (x1addr)
        lm      R1, (x0addr)
        with    R0
        sub     R1
        bpl     PositiveDx
        nop
        move    R2, #$ffff
        move    R1, #0
        with    R1
        sub     R0
        move    R0, R1
        bra     DxDone
        nop
PositiveDx:
        move    R2, #1
DxDone:
        sm      (dxaddr), R0
        sm      (sxaddr), R2

        lm      R0, (y1addr)
        lm      R1, (y0addr)
        with    R0
        sub     R1
        sm      (dyaddr), R0
        move    R0, #0
        sm      (erraddr), R0
.endmacro

.macro GSU_RASTER_EDGE_STEP xaddr, dxaddr, dyaddr, erraddr, sxaddr
        .local StepLoop, Done
        lm      R0, (erraddr)
        lm      R1, (dxaddr)
        with    R0
        add     R1
        ; DY, X, and SX do not change while one scanline consumes the
        ; horizontal part of a Bresenham edge step. Keep them in registers so
        ; shallow edges do not reload and rewrite the same scratch words once
        ; per crossed sample.
        lm      R1, (dyaddr)
        lm      R3, (xaddr)
        lm      R4, (sxaddr)
StepLoop:
        move    R2, R0
        with    R2
        sub     R1
        bmi     Done
        nop
        with    R3
        add     R4
        move    R0, R2
        bra     StepLoop
        nop
Done:
        sm      (xaddr), R3
        sm      (erraddr), R0
.endmacro

.macro GSU_RASTER_DRAW_EDGE_SPANS start_y, end_y, ax0, ay0, ax1, ay1, bx0, by0, bx1, by1
        .local DrawLoop, Done, NonEmpty
        lm      R0, (end_y)
        lm      R1, (start_y)
        with    R0
        sub     R1
        bpl     NonEmpty
        nop
        GSU_ABSOLUTE_GOTO Done
NonEmpty:
        inc     R0
        sm      (GSU_SCAN_COUNT), R0
        sm      (GSU_SCAN_Y), R1

        GSU_RASTER_EDGE_INIT GSU_EDGE0_X, GSU_EDGE0_DX, GSU_EDGE0_DY, GSU_EDGE0_ERR, GSU_EDGE0_SX, ax0, ay0, ax1, ay1
        GSU_RASTER_EDGE_INIT GSU_EDGE1_X, GSU_EDGE1_DX, GSU_EDGE1_DY, GSU_EDGE1_ERR, GSU_EDGE1_SX, bx0, by0, bx1, by1

DrawLoop:
        lm      R1, (GSU_EDGE0_X)
        lm      R3, (GSU_EDGE1_X)
        lm      R2, (GSU_SCAN_Y)
        jal     GSU_DrawHLine
        nop

        GSU_RASTER_EDGE_STEP GSU_EDGE0_X, GSU_EDGE0_DX, GSU_EDGE0_DY, GSU_EDGE0_ERR, GSU_EDGE0_SX
        GSU_RASTER_EDGE_STEP GSU_EDGE1_X, GSU_EDGE1_DX, GSU_EDGE1_DY, GSU_EDGE1_ERR, GSU_EDGE1_SX

        lm      R0, (GSU_SCAN_Y)
        inc     R0
        sm      (GSU_SCAN_Y), R0
        lm      R0, (GSU_SCAN_COUNT)
        dec     R0
        sm      (GSU_SCAN_COUNT), R0
        beq     Done
        nop
        GSU_ABSOLUTE_GOTO DrawLoop
Done:
.endmacro

.macro GSU_RASTER_COMPUTE_SPLIT_VERTEX
        .local SplitLoop, Done
        GSU_RASTER_EDGE_INIT GSU_EDGE0_X, GSU_EDGE0_DX, GSU_EDGE0_DY, GSU_EDGE0_ERR, GSU_EDGE0_SX, GSU_TRI_X0, GSU_TRI_Y0, GSU_TRI_X2, GSU_TRI_Y2
        lm      R0, (GSU_TRI_Y1)
        lm      R1, (GSU_TRI_Y0)
        with    R0
        sub     R1
        sm      (GSU_SCAN_COUNT), R0
SplitLoop:
        GSU_RASTER_EDGE_STEP GSU_EDGE0_X, GSU_EDGE0_DX, GSU_EDGE0_DY, GSU_EDGE0_ERR, GSU_EDGE0_SX
        lm      R0, (GSU_SCAN_COUNT)
        dec     R0
        sm      (GSU_SCAN_COUNT), R0
        beq     Done
        nop
        GSU_ABSOLUTE_GOTO SplitLoop
Done:
        lm      R0, (GSU_EDGE0_X)
        sm      (GSU_TRI_SPLIT_X), R0
        lm      R0, (GSU_TRI_Y1)
        sm      (GSU_TRI_SPLIT_Y), R0
.endmacro

.macro GSU_RASTER_FILL_TRIANGLE va, vb, vc
        .local NotDegenerate, NotFlatTop, General, FlatTop, FlatBottom, Done
        GSU_RASTER_LOAD_TRI_VERTEX GSU_TRI_X0, GSU_TRI_Y0, va
        GSU_RASTER_LOAD_TRI_VERTEX GSU_TRI_X1, GSU_TRI_Y1, vb
        GSU_RASTER_LOAD_TRI_VERTEX GSU_TRI_X2, GSU_TRI_Y2, vc
        GSU_RASTER_SORT_TRIANGLE_VERTICES

        lm      R0, (GSU_TRI_Y2)
        lm      R1, (GSU_TRI_Y0)
        with    R0
        sub     R1
        bne     NotDegenerate
        nop
        GSU_ABSOLUTE_GOTO Done
NotDegenerate:
        lm      R0, (GSU_TRI_Y0)
        lm      R1, (GSU_TRI_Y1)
        with    R0
        sub     R1
        bne     NotFlatTop
        nop
        GSU_ABSOLUTE_GOTO FlatTop
NotFlatTop:
        lm      R0, (GSU_TRI_Y1)
        lm      R1, (GSU_TRI_Y2)
        with    R0
        sub     R1
        bne     General
        nop
        GSU_ABSOLUTE_GOTO FlatBottom

General:
        GSU_RASTER_COMPUTE_SPLIT_VERTEX
        GSU_RASTER_DRAW_EDGE_SPANS GSU_TRI_Y0, GSU_TRI_Y1, GSU_TRI_X0, GSU_TRI_Y0, GSU_TRI_X1, GSU_TRI_Y1, GSU_TRI_X0, GSU_TRI_Y0, GSU_TRI_SPLIT_X, GSU_TRI_SPLIT_Y
        GSU_RASTER_DRAW_EDGE_SPANS GSU_TRI_Y1, GSU_TRI_Y2, GSU_TRI_X1, GSU_TRI_Y1, GSU_TRI_X2, GSU_TRI_Y2, GSU_TRI_SPLIT_X, GSU_TRI_SPLIT_Y, GSU_TRI_X2, GSU_TRI_Y2
        GSU_ABSOLUTE_GOTO Done

FlatTop:
        GSU_RASTER_DRAW_EDGE_SPANS GSU_TRI_Y0, GSU_TRI_Y2, GSU_TRI_X0, GSU_TRI_Y0, GSU_TRI_X2, GSU_TRI_Y2, GSU_TRI_X1, GSU_TRI_Y1, GSU_TRI_X2, GSU_TRI_Y2
        GSU_ABSOLUTE_GOTO Done

FlatBottom:
        GSU_RASTER_DRAW_EDGE_SPANS GSU_TRI_Y0, GSU_TRI_Y2, GSU_TRI_X0, GSU_TRI_Y0, GSU_TRI_X1, GSU_TRI_Y1, GSU_TRI_X0, GSU_TRI_Y0, GSU_TRI_X2, GSU_TRI_Y2
Done:
.endmacro

.macro GSU_RASTER_CULLED_FACE face_color, va, vb, vc, vd
        .local Visible, Done
        GSU_RASTER_LOAD_VERTEX R1, R2, va
        GSU_RASTER_LOAD_VERTEX R3, R4, vb
        GSU_RASTER_LOAD_VERTEX R5, R6, vc

        move    R7, R3
        with    R7
        sub     R1
        move    R8, R4
        with    R8
        sub     R2
        move    R9, R5
        with    R9
        sub     R1
        move    R12, R6
        with    R12
        sub     R2

        move    R0, R7
        move    R1, R12
        jal     GSU_RasterSignedProduct
        nop
        move    R13, R0
        move    R0, R8
        move    R1, R9
        jal     GSU_RasterSignedProduct
        nop
        with    R13
        sub     R0
        bmi     Visible
        nop
        GSU_ABSOLUTE_GOTO Done

Visible:
        move    R0, #face_color
        color
        GSU_RASTER_FILL_TRIANGLE va, vb, vc
        GSU_RASTER_FILL_TRIANGLE va, vc, vd
Done:
.endmacro

; Emits the exact signed product used by face orientation tests.
; Inputs: R0, R1 signed components with magnitudes <= 255. Output: R0.
; The sample projection domains keep both each product and their difference
; within a signed word. Clobbers R1-R3 and R11.
.macro GSU_RASTER_SIGNED_CULL_PRODUCT_ROUTINE
GSU_RasterSignedProduct:
        move    R2, #1
        moves   R0, R0
        bpl     GSU_RasterSignedLeftReady
        nop
        move    R3, #0
        with    R3
        sub     R0
        move    R0, R3
        move    R2, #$ffff

GSU_RasterSignedLeftReady:
        moves   R1, R1
        bpl     GSU_RasterSignedRightReady
        nop
        move    R3, #0
        with    R3
        sub     R1
        move    R1, R3
        move    R3, #0
        with    R3
        sub     R2
        move    R2, R3

GSU_RasterSignedRightReady:
        with    R0
        umult   R1
        moves   R2, R2
        bpl     GSU_RasterSignedDone
        nop
        move    R3, #0
        with    R3
        sub     R0
        move    R0, R3

GSU_RasterSignedDone:
        ret
        nop
.endmacro

; Emits a horizontal span routine.
; Inputs: R1=x0, R2=y, R3=x1. Clobbers R0, R12, R13.
.macro GSU_HLINE_ROUTINE
GSU_DrawHLine:
  .ifdef GSU_RASTER_CLIP_128
        moves   R2, R2
        bmi     HLineDone
        nop
        move    R0, #127
        with    R0
        sub     R2
        bmi     HLineDone
        nop
  .endif

        move    R0, R3
        with    R0
        sub     R1
        bpl     HLineForward
        nop
        move    R0, R1
        move    R1, R3
        move    R3, R0
HLineForward:
  .ifdef GSU_RASTER_CLIP_128
        moves   R3, R3
        bmi     HLineDone
        nop
        move    R0, #127
        with    R0
        sub     R1
        bmi     HLineDone
        nop

        moves   R1, R1
        bpl     HLineLeftReady
        nop
        move    R1, #0
HLineLeftReady:
        move    R0, #127
        with    R0
        sub     R3
        bpl     HLineRightReady
        nop
        move    R3, #127
HLineRightReady:
  .endif
        move    R12, R3
        with    R12
        sub     R1
        inc     R12
        iwt     R13, #HLineLoop
HLineLoop:
        plot
        nop
        loop
        nop
HLineDone:
        ret
        nop
.endmacro

.endif
