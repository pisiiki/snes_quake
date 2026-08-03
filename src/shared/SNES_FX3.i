; S-CPU-visible register map for the Super FX 3 board.

.ifndef __SNES_FX3_I__
__SNES_FX3_I__ = 1

FX3_R0    = $7000
FX3_R1    = $7002
FX3_R2    = $7004
FX3_R3    = $7006
FX3_R4    = $7008
FX3_R5    = $700A
FX3_R6    = $700C
FX3_R7    = $700E
FX3_R8    = $7010
FX3_R9    = $7012
FX3_R10   = $7014
FX3_R11   = $7016
FX3_R12   = $7018
FX3_R13   = $701A
FX3_R14   = $701C
FX3_R15   = $701E
FX3_SFR   = $7030
FX3_PBR   = $7034
FX3_ROMBR = $7036
FX3_CFGR  = $7037
FX3_SCBR  = $7038
FX3_CLSR  = $7039
FX3_SCMR  = $703A
FX3_VCR   = $703B
FX3_RAMBR = $703C
FX3_CBR   = $703E

FX3_SCMR_128X128_2BPP = %00001000
FX3_SCMR_128X128_4BPP = %00001001
FX3_SCMR_128X128_8BPP = %00001011
FX3_SCMR_128X128_2BPP_ROM = %00011000
FX3_SCMR_128X128_4BPP_ROM = %00011001
FX3_SCMR_128X128_8BPP_ROM = %00011011

; Accept only ownership/screen modes intentionally used by current examples.
; This internal assertion keeps arbitrary SCMR values out of the public job API.
.macro __FX3_JOB_ASSERT_SCMR ownership_mode
  .if ownership_mode <> FX3_SCMR_128X128_2BPP .and ownership_mode <> FX3_SCMR_128X128_4BPP .and ownership_mode <> FX3_SCMR_128X128_8BPP .and ownership_mode <> FX3_SCMR_128X128_2BPP_ROM .and ownership_mode <> FX3_SCMR_128X128_4BPP_ROM .and ownership_mode <> FX3_SCMR_128X128_8BPP_ROM
    .error "FX3 job uses an undeclared SCMR ownership mode"
  .endif
.endmacro

; Start one coarse FX3 job and fall through without waiting. ``ownership`` is
; either ``set`` (write the declared SCMR mode now) or ``keep`` (the caller has
; already established that same mode). ``entry`` is a 16-bit immediate address
; or ``x`` when X already contains it. Requires A8/I16; preserves processor
; widths, Y, and DB. Clobbers A, X, and N/Z. No interrupt mask is changed.
;
; FX3, unlike classic Super FX, permits the 65816 and FX to access cartridge
; ROM and FX SRAM simultaneously while RON/RAN are set. The official contract
; guarantees access, not contention-free throughput. Concurrent code must use
; disjoint addresses (or an explicitly synchronized immutable range), publish
; payload fields before a final commit word, and never use same-byte races.
; While a job runs, R15 is the only live general register and serves only as
; the completion poll; SFR/VCR remain status registers, but ordinary GSU
; registers are not a mailbox. Interrupt handlers obey the same memory protocol.
.macro FX3_JOB_START ownership_mode, entry, ownership
        __FX3_JOB_ASSERT_SCMR ownership_mode
  .if .xmatch({ownership}, {set})
        lda     #ownership_mode
        sta     FX3_SCMR
  .elseif .not .xmatch({ownership}, {keep})
    .error "FX3_JOB_START ownership must be set or keep"
  .endif
  .ifnblank entry
    .if .not .xmatch({entry}, {x})
        ldx     #entry
    .endif
  .else
    .error "FX3_JOB_START requires an entry address or x"
  .endif
        stx     FX3_R15
.endmacro

; Join the one active FX3 job by polling the STOP-cleared R15 register.
; Requires I16; accumulator width is unrestricted. Preserves A, Y, DB, and
; widths; clobbers X and N/Z. The polling loop does not mask interrupts, so they
; remain serviceable when their code and data follow the simultaneous-access
; protocol above. Falls through when the job has stopped.
.macro FX3_JOB_JOIN
:
        ldx     FX3_R15
        bne     :-
.endmacro

; Start and immediately join one synchronous coarse job. Parameters and SCMR
; restrictions match FX3_JOB_START. Requires A8/I16; preserves processor widths,
; Y, and DB; clobbers A, X, and N/Z. It does not mask interrupts, clear SCMR,
; interpret results, update counters, perform DMA, or return from its caller.
.macro FX3_JOB_RUN ownership_mode, entry, ownership
        FX3_JOB_START ownership_mode, entry, ownership
        FX3_JOB_JOIN
.endmacro

; Initialize one 128x128 FX3 plot screen and leave cartridge RAM owned by FX3.
; Requires A8/I16. Clobbers A and flags; preserves X/Y. FX3 has no completion
; IRQ, so callers start through FX3_R15 and poll that register until STOP clears
; it to zero. Setting CLSR selects the fastest documented FX3 clock input.
.macro __INIT_FX3_128X128 framebuffer_scb, screen_mode
        lda     #$70
        sta     FX3_PBR
        stz     FX3_RAMBR
        lda     #framebuffer_scb
        sta     FX3_SCBR
        lda     #screen_mode
        sta     FX3_SCMR
        lda     #%10000000
        sta     FX3_CFGR
        lda     #$01
        sta     FX3_CLSR
.endmacro

.macro INIT_FX3_128X128_2BPP framebuffer_scb
        __INIT_FX3_128X128 framebuffer_scb, FX3_SCMR_128X128_2BPP
.endmacro

.macro INIT_FX3_128X128_4BPP framebuffer_scb
        __INIT_FX3_128X128 framebuffer_scb, FX3_SCMR_128X128_4BPP
.endmacro

.macro INIT_FX3_128X128_8BPP framebuffer_scb
        __INIT_FX3_128X128 framebuffer_scb, FX3_SCMR_128X128_8BPP
.endmacro

.endif
