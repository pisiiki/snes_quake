.segment "BSP_DIVIDE_Q12_RECIPROCAL_0"
QuakeBSPDivideQ12Reciprocal:
        .incbin "Data/QuakeBSPDivideQ12Reciprocal.bin", 0, $8000
QuakeBSPDivideQ12ReciprocalBank0End:
.assert QuakeBSPDivideQ12ReciprocalBank0End - QuakeBSPDivideQ12Reciprocal = $8000, error, "Q12 reciprocal bank 0 asset has the wrong size"
.segment "BSP_DIVIDE_Q12_RECIPROCAL_1"
QuakeBSPDivideQ12ReciprocalBank1:
        .incbin "Data/QuakeBSPDivideQ12Reciprocal.bin", $8000, $8000
QuakeBSPDivideQ12ReciprocalBank1End:
.assert QuakeBSPDivideQ12ReciprocalBank1End - QuakeBSPDivideQ12ReciprocalBank1 = $8000, error, "Q12 reciprocal bank 1 asset has the wrong size"
.segment "BSP_DIVIDE_Q12_RECIPROCAL_2"
QuakeBSPDivideQ12ReciprocalBank2:
        .incbin "Data/QuakeBSPDivideQ12Reciprocal.bin", $10000, $8000
QuakeBSPDivideQ12ReciprocalBank2End:
.assert QuakeBSPDivideQ12ReciprocalBank2End - QuakeBSPDivideQ12ReciprocalBank2 = $8000, error, "Q12 reciprocal bank 2 asset has the wrong size"
.segment "BSP_DIVIDE_Q12_RECIPROCAL_3"
QuakeBSPDivideQ12ReciprocalBank3:
        .incbin "Data/QuakeBSPDivideQ12Reciprocal.bin", $18000, $7FFC
QuakeBSPDivideQ12ReciprocalEnd:
.assert QuakeBSPDivideQ12ReciprocalEnd - QuakeBSPDivideQ12ReciprocalBank3 = $7FFC, error, "Q12 reciprocal bank 3 asset has the wrong size"
