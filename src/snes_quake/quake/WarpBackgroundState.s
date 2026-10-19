; Append after the existing low-WRAM state; keep hot renderer addresses stable.
.segment "LORAM"
warp_background_phase:         .res 2 ; Applied packed six-bit X/Y phases.
warp_background_request_phase: .res 2
warp_background_build_phase:   .res 2
warp_background_table_phase:   .res 4 ; Indexed like hdma_table_precise.
warp_background_oam:           .res 80
