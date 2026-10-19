; Public graphics scale is independent of demo/flight scheduling. The legacy
; fly_playback_mode word identifies the requested fixed renderer in both.
; Warp uses live input in flight and the precise recorded camera in demos.
RUNTIME_MENU_SCALE_X2 = 0
RUNTIME_MENU_SCALE_X3 = 1
RUNTIME_MENU_SCALE_WARP = 2
RUNTIME_MENU_SCALE_COUNT = 3
RUNTIME_MENU_SCALE_VALUE_COLUMN = 7
RUNTIME_MENU_SCALE_VALUE_BYTES = 7
.assert RUNTIME_MENU_SCALE_VALUE_COLUMN + RUNTIME_MENU_SCALE_VALUE_BYTES = RUNTIME_MENU_COLUMNS, error, "Scale value must end at the menu edge"

SyncRuntimeMenuScaleDraft:
        RW_assume a16i16
        stz     runtime_menu_draft_scale
        lda     fly_playback_mode
        cmp     #RUNTIME_MENU_PLAYBACK_FLY3X
        bne     @Done
        lda     #RUNTIME_MENU_SCALE_X3
        ldx     fly_warp_enabled
        beq     :+
        inc
:
        sta     runtime_menu_draft_scale
@Done:
        rts

PreviousRuntimeMenuScale:
        RW_assume a16i16
        lda     runtime_menu_draft_scale
        bne     :+
        lda     #RUNTIME_MENU_SCALE_COUNT
:
        dec
        bra     StoreRuntimeMenuScale

NextRuntimeMenuScale:
        RW_assume a16i16
        lda     runtime_menu_draft_scale
        inc
        cmp     #RUNTIME_MENU_SCALE_COUNT
        bcc     StoreRuntimeMenuScale
        lda     #RUNTIME_MENU_SCALE_X2
StoreRuntimeMenuScale:
        sta     runtime_menu_draft_scale
        jsr     RefreshRuntimeMenuOAM
        rts

ApplyRuntimeMenuScale:
        RW_assume a16i16
        lda     fly_warp_enabled
        pha
        stz     fly_warp_enabled
        lda     runtime_menu_draft_scale
        cmp     #RUNTIME_MENU_SCALE_WARP
        bne     @Done
        inc     fly_warp_enabled
@Done:
        pla
        cmp     fly_warp_enabled
        beq     @Return
        stz     demo_warp_clock_valid
        lda     demo_mode
        beq     @Return
        lda     demo_schedule
        bne     @Return
        ; Resume ordinary step playback after the current rendered-command
        ; pose, rather than the cursor saved before entering clocked warp.
        lda     demo_track_pose
        sta     demo_next_pose
        asl
        sta     demo_timing_offset
        asl
        asl
        clc
        adc     demo_timing_offset
        sta     demo_offset
        jsr     AdvanceDemoCursor
@Return:
        rts

PatchRuntimeMenuScaleOAM:
        RW_forced a8i16
        RW      a16
        lda     runtime_menu_draft_scale
        asl
        asl
        asl
        tax
        ldy     #(RUNTIME_MENU_ROW_BYTES * RUNTIME_MENU_ROW_SCALE) + (RUNTIME_MENU_SCALE_VALUE_COLUMN * RUNTIME_MENU_ENTRY_BYTES) + 2
        RW      a8
        lda     #RUNTIME_MENU_SCALE_VALUE_BYTES
        sta     RuntimeMenuBuildColumns
@Value:
        lda     f:RuntimeMenuScaleValues,x
        sec
        sbc     #RUNTIME_MENU_ASCII_FIRST
        clc
        adc     #.lobyte(RUNTIME_MENU_TILE_BASE)
        sta     a:RuntimeMenuOAM,y
        inx
        iny
        iny
        iny
        iny
        dec     RuntimeMenuBuildColumns
        bne     @Value
        rts

.segment "RODATA"
RuntimeMenuScaleValues:
        .byte   "X2      "
        .byte   "X3      "
        .byte   "X3 WARP "
RuntimeMenuScaleValuesEnd:
.assert RuntimeMenuScaleValuesEnd - RuntimeMenuScaleValues = RUNTIME_MENU_SCALE_COUNT * 8, error, "Scale values must retain eight-byte indexing"
.segment "CODE"
