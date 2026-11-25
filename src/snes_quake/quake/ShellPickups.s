; The asset builder converts original linked item/player boxes into
; inclusive eye-coordinate bounds. WalkService has just computed w_from.
.macro QC_SHELL_AXIS axis, offset, lower, upper, skip
        lda     a:w_from+offset
        sec
        sbc     #.loword(lower - axis * 16)
        cmp     #upper-lower+1
        bcs     skip
.endmacro

.macro QC_SHELL_ITEM I
        .local next
        lda     f:QuakeCShellMask
        bit     #(1 << I)
        beq     next
        QC_SHELL_AXIS BSP_WORLD_ORIGIN_X, 0, .ident(.sprintf("QC_SHELL_%d_X_MIN", I)), .ident(.sprintf("QC_SHELL_%d_X_MAX", I)), next
        QC_SHELL_AXIS BSP_WORLD_ORIGIN_Y, 2, .ident(.sprintf("QC_SHELL_%d_Y_MIN", I)), .ident(.sprintf("QC_SHELL_%d_Y_MAX", I)), next
        QC_SHELL_AXIS BSP_WORLD_ORIGIN_Z, 4, .ident(.sprintf("QC_SHELL_%d_Z_MIN", I)), .ident(.sprintf("QC_SHELL_%d_Z_MAX", I)), next
        ldx     #(4+I)*QC_ENTITY_STRIDE
        ldy     #QC_ENTITY_STRIDE
        lda     a:qce+(4+I)*QC_ENTITY_STRIDE+QC_FIELD_TOUCH
        jsr     QuakeCEvent
        lda     a:qce+(4+I)*QC_ENTITY_STRIDE+QC_FIELD_SOLID
        bne     next
        lda     f:QuakeCShellMask
        and     #.loword(~(1 << I))
        sta     f:QuakeCShellMask
.ifdef QC_PICKUP_NOTICES
        lda     #NOTICE_SHELLS
        jsl     PickupNotify
.endif
next:
.endmacro

QuakeCShellTouch:
        lda     f:QC_INPUT_MENU_OPEN
        ora     f:QC_INPUT_RELEASE_GATE
        beq     :+
        rts
:       .repeat QC_SHELL_COUNT, I
        QC_SHELL_ITEM I
        .endrepeat
.ifdef QC_HEALTH_COUNT
.ifdef QC_ARMOR_COUNT
        jsl     ArmorTouch
.endif
.ifdef QC_NAIL_COUNT
        jsl     NailPickupTouch
        jsl     SuperShotgunTouch
.endif
        jsl     QuakeCHealthTouch
.ifdef QC_POWERUP_COUNT
        jsl     PowerupTouch
.endif
.endif
        rts
