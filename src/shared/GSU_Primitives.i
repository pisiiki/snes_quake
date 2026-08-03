; Small, smoke-tested SuperFX helpers.

.ifndef __GSU_PRIMITIVES_I__
__GSU_PRIMITIVES_I__ = 1

; Unconditional jump to a link-time target.
; Input: target=link-time address. Output/clobber: R15=target; R0-R14 and
; condition flags are preserved. By default the required control-flow delay
; slot is a fixed NOP. Pass a nonblank shared_delay only when the immediately
; following instruction is deliberately shared with another entry point.
.macro GSU_ABSOLUTE_GOTO target, shared_delay
        iwt     R15, #target
  .ifblank shared_delay
        nop
  .endif
.endmacro

; Read one unsigned byte through R10.
; Input: R10=source pointer. Output: reg=0..255, R10=R10+1.
; reg must not be R10. Clobbers: reg, R10, condition flags.
.macro GSU_LOAD_BYTE reg
        move    reg, #0
        moveb   reg, (R10)
        inc     R10
.endmacro

; Read and sign-extend table[indexreg].
; Inputs: table=link-time address, indexreg=byte index.
; reg and indexreg must not be R10. Output: reg=-128..127 and
; R10=table+indexreg; the byte load does not advance R10.
; Clobbers: reg, R10, condition flags.
.macro GSU_LOAD_SIGNED_TABLE reg, table, indexreg
        iwt     R10, #table
        with    R10
        add     indexreg
        moveb   reg, (R10)
        with    reg
        sex
.endmacro

; Output: dest=(signed8(source) * signed8(multiplier)) arithmetic-shifted right
; by 6. source may alias dest; multiplier must be distinct from dest because it
; is read after dest is assigned. Other input registers are preserved.
; Clobbers: dest and condition flags.
.macro GSU_SIGNED_MUL_SHIFT6 dest, source, multiplier
        move    dest, source
        with    dest
        mult    multiplier
  .repeat 6
        with    dest
        asr
  .endrepeat
.endmacro

; Add a compile-time signed axis contribution to target.
; sign must be -1, 0, or +1; zero deliberately emits no instructions.
; target and axis must be distinct. Clobbers: target and flags for nonzero
; signs. Preserves axis.
.macro GSU_ADD_SIGNED_AXIS target, axis, sign
  .if .xmatch ({target}, {axis})
        .error "GSU_ADD_SIGNED_AXIS target and axis must be distinct"
  .elseif sign > 1
        .error "GSU_ADD_SIGNED_AXIS sign must be -1, 0, or +1"
  .elseif sign < -1
        .error "GSU_ADD_SIGNED_AXIS sign must be -1, 0, or +1"
  .elseif sign > 0
        with    target
        add     axis
  .elseif sign < 0
        with    target
        sub     axis
  .endif
.endmacro

.macro GSU_RAMBANK0
        move    R0, #0
        ramb
.endmacro

.macro GSU_CLEAR_WORDS address, count
        .local ClearLoop
        iwt     R10, #address
        iwt     R12, #count
        iwt     R13, #ClearLoop
        move    R0, #0
ClearLoop:
        movew   (R10), R0
        inc     R10
        inc     R10
        loop
        nop
.endmacro

.macro GSU_STORE_BYTE address, value
        iwt     R10, #address
        move    R0, #value
        moveb   (R10), R0
.endmacro

.macro GSU_STORE_WORD address, value
        iwt     R10, #address
        iwt     R0, #value
        movew   (R10), R0
.endmacro

.macro GSU_COLOR value
        move    R0, #value
        color
.endmacro

.macro GSU_PLOT_XY px, py
        move    R1, #(px)
        move    R2, #(py)
        plot
        nop
.endmacro

.macro GSU_FLUSH_PLOT px, py
        move    R1, #(px)
        move    R2, #(py)
        rpix
.endmacro

.macro GSU_HLINE px, py, count
  .repeat count, i
        GSU_PLOT_XY px+i, py
  .endrepeat
.endmacro

.macro GSU_VLINE px, py, count
  .repeat count, i
        GSU_PLOT_XY px, py+i
  .endrepeat
.endmacro

.macro GSU_DIAG_UP px, py, count
  .repeat count, i
        GSU_PLOT_XY px+i, py-i
  .endrepeat
.endmacro

.macro GSU_DIAG_DOWN px, py, count
  .repeat count, i
        GSU_PLOT_XY px+i, py+i
  .endrepeat
.endmacro

; Emits a bounded Bresenham line routine.
; Inputs follow the SuperFX plot convention: R1=x0, R2=y0, R3=x1, R4=y1.
; Clobbers R0, R5-R9, R12, R13.
.macro GSU_DRAWLINE_ROUTINE
        .local DxPositive, DxDone, DyPositive, DyDone
        .local XMajor, XLoop, XSkipY, YMajor, YLoop, YSkipX
GSU_DrawLine:
        move    R5, R3
        with    R5
        sub     R1
        bpl     DxPositive
        nop
        move    R7, #$ffff
        move    R0, #0
        with    R0
        sub     R5
        move    R5, R0
        bra     DxDone
        nop
DxPositive:
        move    R7, #1
DxDone:
        move    R6, R4
        with    R6
        sub     R2
        bpl     DyPositive
        nop
        move    R8, #$ffff
        move    R0, #0
        with    R0
        sub     R6
        move    R6, R0
        bra     DyDone
        nop
DyPositive:
        move    R8, #1
DyDone:
        move    R0, R6
        with    R0
        sub     R5
        bpl     YMajor
        nop

XMajor:
        move    R9, #0
        move    R12, R5
        inc     R12
        iwt     R13, #XLoop
XLoop:
        plot
        nop
        dec     R1
        with    R1
        add     R7
        with    R9
        add     R6
        move    R0, R9
        with    R0
        sub     R5
        bmi     XSkipY
        nop
        with    R2
        add     R8
        with    R9
        sub     R5
XSkipY:
        dec     R12
        bne     XLoop
        nop
        ret
        nop

YMajor:
        move    R9, #0
        move    R12, R6
        inc     R12
        iwt     R13, #YLoop
YLoop:
        plot
        nop
        dec     R1
        with    R2
        add     R8
        with    R9
        add     R5
        move    R0, R9
        with    R0
        sub     R6
        bmi     YSkipX
        nop
        with    R1
        add     R7
        with    R9
        sub     R6
YSkipX:
        dec     R12
        bne     YLoop
        nop
        ret
        nop
.endmacro

.endif
