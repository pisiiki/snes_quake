; One instruction definition serves the public reader and X2 admission.
.macro BSP_PACKET_DECODE_WORLD_INDEX
        .local IndexBank0, IndexBankReady
        lm      R1, (PACKET_INDEX_CURSOR)
        iwt     R2, #$4000
        move    R0, R1
        with    R0
        cmp     R2
        bcc     IndexBank0
        nop
        with    R1
        sub     R2
        move    R0, #WORLD_INDICES1_ROM_BANK
        bra     IndexBankReady
        nop
IndexBank0:
        move    R0, #WORLD_INDICES0_ROM_BANK
IndexBankReady:
        romb
        with    R1
        add     R1
        iwt     R4, #$8000
        with    R4
        add     R1
        GSU_SET_ROM_BUFFER_ADDRESS R4
        BSP_ROM_LOAD_WORD R0
        sm      (PACKET_SOURCE_INDEX), R0
.endmacro

; Preserve all installed entry addresses while bypassing three redundant
; short RAM reads in X2. X3 retains its exact former instruction stream.
.macro BSP_PACKET_REUSE_SOURCE_INDEX
  .if BSP_RENDER_SCALE = 2
        .assert (PACKET_SOURCE_INDEX <= $01FE) && ((PACKET_SOURCE_INDEX & 1) = 0), error, "Source index no longer uses short even LMS"
        .res 3, $01
  .else
        lm      R0, (PACKET_SOURCE_INDEX)
  .endif
.endmacro

.macro BSP_PACKET_REUSE_CACHE_CLASS
  .if BSP_RENDER_SCALE = 2
        .assert (PACKET_CACHE_ENTRY <= $01FE) && ((PACKET_CACHE_ENTRY & 1) = 0), error, "Reload no longer uses short even LMS"
        move    R0, R3
        nop
  .else
        lm      R0, (PACKET_CACHE_ENTRY)
  .endif
.endmacro

.macro BSP_PACKET_REUSE_FIRST_X
  .if BSP_RENDER_SCALE = 2
        .assert (PACKET_FAN_X0 <= $01FE) && ((PACKET_FAN_X0 & 1) = 0), error, "Reload no longer uses short even LMS"
        .res 3, $01
  .else
        lm      R4, (PACKET_FAN_X0)
  .endif
.endmacro
