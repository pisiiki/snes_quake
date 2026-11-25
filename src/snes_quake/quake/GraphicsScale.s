; Public graphics scale is independent of demo/flight scheduling. The legacy
; fly_playback_mode word identifies the requested fixed renderer in both.
RUNTIME_MENU_SCALE_X2 = 0
RUNTIME_MENU_SCALE_X3 = 1
RUNTIME_MENU_SCALE_COUNT = 2
.ifdef PLAYABLE_MAP_ID
RUNTIME_MENU_SCALE_VALUE_BYTES = 2
.else
RUNTIME_MENU_SCALE_VALUE_COLUMN = 7
RUNTIME_MENU_SCALE_VALUE_BYTES = RuntimeMenuTextRestart - RuntimeMenuTextScale - RUNTIME_MENU_SCALE_VALUE_COLUMN
.endif

SyncRuntimeMenuScaleDraft:
        RW_assume a16i16
        stz     runtime_menu_draft_scale
        lda     fly_playback_mode
        cmp     #RUNTIME_MENU_PLAYBACK_FLY3X
        bne     @Done
        lda     #RUNTIME_MENU_SCALE_X3
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

PatchRuntimeMenuScaleOAM:
        RW_forced a8i16
        RW      a16
        lda     runtime_menu_draft_scale
        asl
        asl
        asl
        clc
        adc     #(RuntimeMenuScaleValues - RuntimeMenuToggleValues)
        tax
.ifdef PLAYABLE_MAP_ID
        ldy     #RUNTIME_MENU_SCALE_VALUE_OAM + 2
.else
        ldy     #RUNTIME_MENU_SCALE_OAM + (RUNTIME_MENU_SCALE_VALUE_COLUMN * RUNTIME_MENU_ENTRY_BYTES) + 2
.endif
        RW      a8
        lda     #RUNTIME_MENU_SCALE_VALUE_BYTES
        jmp     WriteRuntimeMenuValue
