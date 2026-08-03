; These WRAM polling stubs are a retained scheduling implementation, not an FX3
; ownership requirement. FX3 permits simultaneous S-CPU ROM and disjoint FX
; SRAM access while RON/RAN are set; payloads must still publish commit-last.

SelectorStubImage:
        RW_assume a8i16
        FX3_JOB_START FX3_SCMR_128X128_4BPP_ROM, .loword(GSU_SelectVisibility), set
        rts
SelectorStubWait:
        ldx     FX3_R15
        bne     SelectorStubWait
        stz     FX3_SCMR
        rts
SelectorStubImageEnd:

TextureRendererStubImage:
        RW_assume a8i16
        FX3_JOB_START FX3_SCMR_128X128_8BPP_ROM, x, set
TextureRendererWait:
        ldx     FX3_R15
        bne     TextureRendererWait
        stz     FX3_SCMR
        rts
TextureRendererStubImageEnd:

FlatRendererStubImage:
        RW_assume a8i16
        FX3_JOB_START FX3_SCMR_128X128_4BPP_ROM, x, set
FlatRendererWait:
        ldx     FX3_R15
        bne     FlatRendererWait
        stz     FX3_SCMR
        rts
FlatRendererStubImageEnd:
