.segment "HDMA_WARP_CODE"
; Fixed pivot at X=128 and the band's center scanline. The integer center
; rounds each projected coordinate once, after correcting the Mode 7 low-six
; bit product truncation. This removes four candidate searches per band.
HdmaChoosePhase:
        .repeat 2, row
          lda   hdma_band
          .repeat 5
            asl
          .endrepeat
          sta   z:hdma_partial-hdma_work
          lda   z:hdma_registers-hdma_work+row*4+2
          and   #63
          ora   z:hdma_partial-hdma_work
          tax
          RW    a8
          lda   f:HdmaPivotResidue,x
          RW    a16
          and   #63
          clc
          adc   #128
          sta   z:hdma_partial-hdma_work
          lda   z:hdma_registers-hdma_work+row*4
          cmp   #$8000
          ror
          adc   #0                    ; ceil(A/2), retaining the low-bit carry.
          clc
          adc   z:hdma_partial-hdma_work
          .repeat 2
            cmp #$8000
            ror
          .endrepeat
          ; floor((4*q+s)/256) = floor((q+floor(s/4))/64).
          ; The addition can require 17 signed bits. If it overflows, invert
          ; the first ASR's sign bit; the remaining five shifts then fit s16.
          clc
          adc   z:hdma_origin-hdma_work+row*4
          bvc   :+
          cmp   #$8000
          ror
          eor   #$8000
          bra   :++
:
          cmp   #$8000
          ror
:
          .repeat 5
            cmp #$8000
            ror
          .endrepeat
          clc
          .if row = 0
            adc #43
          .else
            adc #37
          .endif
          sta   z:hdma_registers-hdma_work+8+row*2
          .if row = 0
            sec
            sbc #128
          .else
            sta z:hdma_partial-hdma_work
            lda hdma_band
            lsr
            sta z:hdma_product-hdma_work
            asl
            asl
            asl
            sec
            sbc z:hdma_product-hdma_work
            clc
            adc #4
            sta z:hdma_product-hdma_work
            lda z:hdma_partial-hdma_work
            sec
            sbc z:hdma_product-hdma_work
          .endif
          sta   z:hdma_registers-hdma_work+12+row*2
        .endrepeat
        ; HdmaBandRegisters bounds both Q12 projected coordinates to int16
        ; before multiplying by four. Adding the +/-64-texel slope phase and
        ; subtracting a <=224-pixel pivot keeps all centers/scrolls in s13.
        rts
