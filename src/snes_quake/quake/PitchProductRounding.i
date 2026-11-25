; Round all camera Q2 products and pitched Q6 forward products to nearest.
; Prefixes preserve the final discarded LMULT bit, including negative ties.
.macro BSP_SIGNED_MUL_SHIFT_ROUND dest, source, multiplier, shift
        move    R6, multiplier
        from    source
        lmult
  .repeat shift
        asr
        with    R4
        ror
  .endrepeat
        from    R4
        to      dest
        adc     #0
.endmacro
