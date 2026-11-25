; Both albedo paths use the same Q10 screen-space fraction and signed X.
.macro TextureAlbedoEdgeFraction baked_x_only
        .local DivideLoop, DivideNext
        lm      R0, (CONVEX_SAMPLE_Y)
        move    R1, R0
        with    R1
        sub     R5
        move    R0, R7
        with    R0
        sub     R5
        move    R2, R0
  .ifblank baked_x_only
        sm      (CONVEX_BASE_RIGHT), R4
        move    R0, R6
        with    R0
        sub     R4
        sm      (CONVEX_DELTA_RIGHT), R0
  .else
        ; R5 and R7 survive division and feed the baked X product.
        move    R5, R4
        to      R7
        from    R6
        sub     R4
  .endif

        move    R0, R1
        move    R3, #0
        move    R12, #10
        iwt     R13, #DivideLoop
DivideLoop:
        with    R0
        add     R0
        with    R3
        add     R3
        move    R4, R0
        with    R4
        sub     R2
        bcc     DivideNext
        nop
        move    R0, R4
        inc     R3
DivideNext:
        loop
        nop
        with    R3
        add     R3
        with    R3
        add     R3
.endmacro
