; Keep optional composed-face routing compact at the two projective span
; entries. Ordinary faces fall through without changing any live register.
.macro GSU_COMPOSED_GOTO_IF_SELECTED target
        .local Ordinary
        lm      R0, (TEXTURE_WRAP_FLAGS)
        moves   R0, R0
        bpl     Ordinary
        nop
        GSU_ABSOLUTE_GOTO target
Ordinary:
.endmacro

.macro GSU_COMPOSED_CALL_DIVIDE_Q12_PREPARED ordinary, alternate
        .local Ordinary, Done
        lm      R7, (TEXTURE_WRAP_FLAGS)
        moves   R7, R7
        bpl     Ordinary
        nop
        jal     alternate
        bra     Done
        nop
Ordinary:
        jal     ordinary
Done:
.endmacro

.macro GSU_COMPOSED_GOTO_LIGHTMAP_BLOCK8 alternate, ordinary
        .local Ordinary
        lm      R0, (TEXTURE_WRAP_FLAGS)
        moves   R0, R0
        bpl     Ordinary
        nop
        GSU_ABSOLUTE_GOTO alternate
Ordinary:
        GSU_ABSOLUTE_GOTO ordinary
.endmacro
