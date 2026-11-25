; Q6 trigonometry at 1/256 turn, with a shared quarter-turn cosine suffix.
; Movement retains the original round-to-even Q6 / 2 conversion to Q5.
; Verified against the mathematical definition and the legacy 32-step grid.
.pushseg
.segment "BSP_CAMERA_ANGLES"
CameraAngleSin:
        .byte $00, $02, $03, $05, $06, $08, $09, $0B, $0C, $0E, $10, $11, $13, $14, $16, $17
        .byte $18, $1A, $1B, $1D, $1E, $20, $21, $22, $24, $25, $26, $27, $29, $2A, $2B, $2C
        .byte $2D, $2E, $2F, $30, $31, $32, $33, $34, $35, $36, $37, $38, $38, $39, $3A, $3B
        .byte $3B, $3C, $3C, $3D, $3D, $3E, $3E, $3E, $3F, $3F, $3F, $40, $40, $40, $40, $40
        .byte $40, $40, $40, $40, $40, $40, $3F, $3F, $3F, $3E, $3E, $3E, $3D, $3D, $3C, $3C
        .byte $3B, $3B, $3A, $39, $38, $38, $37, $36, $35, $34, $33, $32, $31, $30, $2F, $2E
        .byte $2D, $2C, $2B, $2A, $29, $27, $26, $25, $24, $22, $21, $20, $1E, $1D, $1B, $1A
        .byte $18, $17, $16, $14, $13, $11, $10, $0E, $0C, $0B, $09, $08, $06, $05, $03, $02
        .byte $00, $FE, $FD, $FB, $FA, $F8, $F7, $F5, $F4, $F2, $F0, $EF, $ED, $EC, $EA, $E9
        .byte $E8, $E6, $E5, $E3, $E2, $E0, $DF, $DE, $DC, $DB, $DA, $D9, $D7, $D6, $D5, $D4
        .byte $D3, $D2, $D1, $D0, $CF, $CE, $CD, $CC, $CB, $CA, $C9, $C8, $C8, $C7, $C6, $C5
        .byte $C5, $C4, $C4, $C3, $C3, $C2, $C2, $C2, $C1, $C1, $C1, $C0, $C0, $C0, $C0, $C0
        .byte $C0, $C0, $C0, $C0, $C0, $C0, $C1, $C1, $C1, $C2, $C2, $C2, $C3, $C3, $C4, $C4
        .byte $C5, $C5, $C6, $C7, $C8, $C8, $C9, $CA, $CB, $CC, $CD, $CE, $CF, $D0, $D1, $D2
        .byte $D3, $D4, $D5, $D6, $D7, $D9, $DA, $DB, $DC, $DE, $DF, $E0, $E2, $E3, $E5, $E6
        .byte $E8, $E9, $EA, $EC, $ED, $EF, $F0, $F2, $F4, $F5, $F7, $F8, $FA, $FB, $FD, $FE
        .byte $00, $02, $03, $05, $06, $08, $09, $0B, $0C, $0E, $10, $11, $13, $14, $16, $17
        .byte $18, $1A, $1B, $1D, $1E, $20, $21, $22, $24, $25, $26, $27, $29, $2A, $2B, $2C
        .byte $2D, $2E, $2F, $30, $31, $32, $33, $34, $35, $36, $37, $38, $38, $39, $3A, $3B
        .byte $3B, $3C, $3C, $3D, $3D, $3E, $3E, $3E, $3F, $3F, $3F, $40, $40, $40, $40, $40
CameraAngleSinEnd:
CameraAngleCos = CameraAngleSin + CAMERA_ANGLE_QUARTER
.assert CameraAngleSinEnd-CameraAngleSin = CAMERA_ANGLE_STEPS+CAMERA_ANGLE_QUARTER, error, "Camera trigonometry table size changed"
CameraMoveSin:
        .word $0000, $0001, $0002, $0002, $0003, $0004, $0004, $0006, $0006, $0007, $0008, $0008, $000A, $000A, $000B, $000C
        .word $000C, $000D, $000E, $000E, $000F, $0010, $0010, $0011, $0012, $0012, $0013, $0014, $0014, $0015, $0016, $0016
        .word $0016, $0017, $0018, $0018, $0018, $0019, $001A, $001A, $001A, $001B, $001C, $001C, $001C, $001C, $001D, $001E
        .word $001E, $001E, $001E, $001E, $001E, $001F, $001F, $001F, $0020, $0020, $0020, $0020, $0020, $0020, $0020, $0020
        .word $0020, $0020, $0020, $0020, $0020, $0020, $0020, $0020, $0020, $001F, $001F, $001F, $001E, $001E, $001E, $001E
        .word $001E, $001E, $001D, $001C, $001C, $001C, $001C, $001B, $001A, $001A, $001A, $0019, $0018, $0018, $0018, $0017
        .word $0016, $0016, $0016, $0015, $0014, $0014, $0013, $0012, $0012, $0011, $0010, $0010, $000F, $000E, $000E, $000D
        .word $000C, $000C, $000B, $000A, $000A, $0008, $0008, $0007, $0006, $0006, $0004, $0004, $0003, $0002, $0002, $0001
        .word $0000, $FFFF, $FFFE, $FFFE, $FFFD, $FFFC, $FFFC, $FFFA, $FFFA, $FFF9, $FFF8, $FFF8, $FFF6, $FFF6, $FFF5, $FFF4
        .word $FFF4, $FFF3, $FFF2, $FFF2, $FFF1, $FFF0, $FFF0, $FFEF, $FFEE, $FFEE, $FFED, $FFEC, $FFEC, $FFEB, $FFEA, $FFEA
        .word $FFEA, $FFE9, $FFE8, $FFE8, $FFE8, $FFE7, $FFE6, $FFE6, $FFE6, $FFE5, $FFE4, $FFE4, $FFE4, $FFE4, $FFE3, $FFE2
        .word $FFE2, $FFE2, $FFE2, $FFE2, $FFE2, $FFE1, $FFE1, $FFE1, $FFE0, $FFE0, $FFE0, $FFE0, $FFE0, $FFE0, $FFE0, $FFE0
        .word $FFE0, $FFE0, $FFE0, $FFE0, $FFE0, $FFE0, $FFE0, $FFE0, $FFE0, $FFE1, $FFE1, $FFE1, $FFE2, $FFE2, $FFE2, $FFE2
        .word $FFE2, $FFE2, $FFE3, $FFE4, $FFE4, $FFE4, $FFE4, $FFE5, $FFE6, $FFE6, $FFE6, $FFE7, $FFE8, $FFE8, $FFE8, $FFE9
        .word $FFEA, $FFEA, $FFEA, $FFEB, $FFEC, $FFEC, $FFED, $FFEE, $FFEE, $FFEF, $FFF0, $FFF0, $FFF1, $FFF2, $FFF2, $FFF3
        .word $FFF4, $FFF4, $FFF5, $FFF6, $FFF6, $FFF8, $FFF8, $FFF9, $FFFA, $FFFA, $FFFC, $FFFC, $FFFD, $FFFE, $FFFE, $FFFF
        .word $0000, $0001, $0002, $0002, $0003, $0004, $0004, $0006, $0006, $0007, $0008, $0008, $000A, $000A, $000B, $000C
        .word $000C, $000D, $000E, $000E, $000F, $0010, $0010, $0011, $0012, $0012, $0013, $0014, $0014, $0015, $0016, $0016
        .word $0016, $0017, $0018, $0018, $0018, $0019, $001A, $001A, $001A, $001B, $001C, $001C, $001C, $001C, $001D, $001E
        .word $001E, $001E, $001E, $001E, $001E, $001F, $001F, $001F, $0020, $0020, $0020, $0020, $0020, $0020, $0020, $0020
CameraMoveSinEnd:
CameraMoveCos = CameraMoveSin + CAMERA_ANGLE_QUARTER*2
.assert CameraMoveSinEnd-CameraMoveSin = (CAMERA_ANGLE_STEPS+CAMERA_ANGLE_QUARTER)*2, error, "Camera movement table size changed"
.ifdef QC_QUEUED_INPUT
; Q4 displacement at the 3-VBlank simulation step, 320 units/s nominal.
.assert QC_INPUT_VBLANKS = 3, error, "Run movement table expects three VBlanks"
CameraRunSin:
        .word $0000, $0006, $000D, $0013, $0019, $001F, $0026, $002C, $0032, $0038, $003E, $0044, $004A, $0050, $0056, $005C
        .word $0062, $0068, $006D, $0073, $0079, $007E, $0084, $0089, $008E, $0093, $0098, $009D, $00A2, $00A7, $00AC, $00B1
        .word $00B5, $00B9, $00BE, $00C2, $00C6, $00CA, $00CE, $00D1, $00D5, $00D8, $00DC, $00DF, $00E2, $00E5, $00E7, $00EA
        .word $00ED, $00EF, $00F1, $00F3, $00F5, $00F7, $00F8, $00FA, $00FB, $00FC, $00FD, $00FE, $00FF, $00FF, $0100, $0100
        .word $0100, $0100, $0100, $00FF, $00FF, $00FE, $00FD, $00FC, $00FB, $00FA, $00F8, $00F7, $00F5, $00F3, $00F1, $00EF
        .word $00ED, $00EA, $00E7, $00E5, $00E2, $00DF, $00DC, $00D8, $00D5, $00D1, $00CE, $00CA, $00C6, $00C2, $00BE, $00B9
        .word $00B5, $00B1, $00AC, $00A7, $00A2, $009D, $0098, $0093, $008E, $0089, $0084, $007E, $0079, $0073, $006D, $0068
        .word $0062, $005C, $0056, $0050, $004A, $0044, $003E, $0038, $0032, $002C, $0026, $001F, $0019, $0013, $000D, $0006
        .word $0000, $FFFA, $FFF3, $FFED, $FFE7, $FFE1, $FFDA, $FFD4, $FFCE, $FFC8, $FFC2, $FFBC, $FFB6, $FFB0, $FFAA, $FFA4
        .word $FF9E, $FF98, $FF93, $FF8D, $FF87, $FF82, $FF7C, $FF77, $FF72, $FF6D, $FF68, $FF63, $FF5E, $FF59, $FF54, $FF4F
        .word $FF4B, $FF47, $FF42, $FF3E, $FF3A, $FF36, $FF32, $FF2F, $FF2B, $FF28, $FF24, $FF21, $FF1E, $FF1B, $FF19, $FF16
        .word $FF13, $FF11, $FF0F, $FF0D, $FF0B, $FF09, $FF08, $FF06, $FF05, $FF04, $FF03, $FF02, $FF01, $FF01, $FF00, $FF00
        .word $FF00, $FF00, $FF00, $FF01, $FF01, $FF02, $FF03, $FF04, $FF05, $FF06, $FF08, $FF09, $FF0B, $FF0D, $FF0F, $FF11
        .word $FF13, $FF16, $FF19, $FF1B, $FF1E, $FF21, $FF24, $FF28, $FF2B, $FF2F, $FF32, $FF36, $FF3A, $FF3E, $FF42, $FF47
        .word $FF4B, $FF4F, $FF54, $FF59, $FF5E, $FF63, $FF68, $FF6D, $FF72, $FF77, $FF7C, $FF82, $FF87, $FF8D, $FF93, $FF98
        .word $FF9E, $FFA4, $FFAA, $FFB0, $FFB6, $FFBC, $FFC2, $FFC8, $FFCE, $FFD4, $FFDA, $FFE1, $FFE7, $FFED, $FFF3, $FFFA
        .word $0000, $0006, $000D, $0013, $0019, $001F, $0026, $002C, $0032, $0038, $003E, $0044, $004A, $0050, $0056, $005C
        .word $0062, $0068, $006D, $0073, $0079, $007E, $0084, $0089, $008E, $0093, $0098, $009D, $00A2, $00A7, $00AC, $00B1
        .word $00B5, $00B9, $00BE, $00C2, $00C6, $00CA, $00CE, $00D1, $00D5, $00D8, $00DC, $00DF, $00E2, $00E5, $00E7, $00EA
        .word $00ED, $00EF, $00F1, $00F3, $00F5, $00F7, $00F8, $00FA, $00FB, $00FC, $00FD, $00FE, $00FF, $00FF, $0100, $0100
CameraRunSinEnd:
CameraRunCos = CameraRunSin + CAMERA_ANGLE_QUARTER*2
.assert CameraRunSinEnd-CameraRunSin = (CAMERA_ANGLE_STEPS+CAMERA_ANGLE_QUARTER)*2, error, "Run movement table size changed"
.endif
.popseg
