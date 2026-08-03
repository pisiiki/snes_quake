; Natural-texture CGRAM policy. Temporal mode alternates two WRAM-staged
; palettes at scanout cadence; static mode restores the unchanged nearest
; BGR555 palette once and then performs no recurring palette DMA.

TEMPORAL_PALETTE_PHASE_STATIC = $02

UpdateTemporalTexturePalette:
        RW_assume a8i16
        lda     SFX_inidisp
        bmi     TemporalTexturePaletteDone
        lda     presented_format
        cmp     #$01
        bne     TemporalTexturePaletteDone
        lda     presented_palette_mode
        bne     TemporalTexturePaletteDone
        lda     temporal_color_dither_enabled
        bne     TemporalTexturePaletteEnabled
        lda     presented_palette_phase
        cmp     #TEMPORAL_PALETTE_PHASE_STATIC
        beq     TemporalTexturePaletteDone
        CGRAM_memcpy 0, QuakeBSPTexturePalette, 512
        lda     #TEMPORAL_PALETTE_PHASE_STATIC
        sta     presented_palette_phase
        rts
TemporalTexturePaletteEnabled:
        lda     video_tick
        and     #$01
        cmp     presented_palette_phase
        beq     TemporalTexturePaletteDone
        pha
        cmp     #$00
        beq     TemporalTexturePalettePhase0
        CGRAM_memcpy 0, TemporalTexturePalette1, 512
        bra     TemporalTexturePaletteStore
TemporalTexturePalettePhase0:
        CGRAM_memcpy 0, TemporalTexturePalette0, 512
TemporalTexturePaletteStore:
        pla
        sta     presented_palette_phase
TemporalTexturePaletteDone:
        rts
