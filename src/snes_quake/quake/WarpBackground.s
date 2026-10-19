; Shared 64x64 texture repeated by 20 priority-zero OBJs below Mode 7.
; 2 KiB of tile bytes occupy eight 256-byte rows at a 512-byte VRAM stride.
; Moving phases upload only 80 OAM bytes; texture/palette stay resident.
InitWarpBackground:
        RW_assume a8i16
  .repeat 8, row
        VRAM_memcpy ($8000+row*512), (WarpBackgroundTile+row*256), 256
  .endrepeat
        rts

RefreshWarpBackground:
        RW_assume a8i16
        lda     runtime_menu_open
        bne     @Done                  ; Menu owns all OAM while it is open.
        lda     presented_render_scale
        cmp     #3
        bne     @Hide
        lda     fly_warp_enabled
        beq     @Hide
        lda     warp_background_active
        bne     @Show
        OAM_memcpy WarpBackgroundOAM
        inc     warp_background_active
.if WARP_BACKGROUND_MOTION_ENABLED
        RW      a16
        jsr     InitializeWarpBackgroundOam
        RW      a8
.endif
@Show:
        lda     #tm(ON, OFF, OFF, OFF, ON)
        sta     TM
.if WARP_BACKGROUND_MOTION_ENABLED
        RW      a16
        jsr     SelectWarpBackgroundPhase
        jsr     ApplyWarpBackgroundScroll
        RW      a8
.endif
@Done:
        rts
@Hide:
        stz     warp_background_active
        lda     #tm(ON, OFF, OFF, OFF, OFF)
        sta     TM
        rts

.if WARP_BACKGROUND_MOTION_ENABLED
InitializeWarpBackgroundOam:
        RW_assume a16i16
        stz     warp_background_phase
        ldx     #78
@Copy:
        lda     f:WarpBackgroundOAM,x
        sta     warp_background_oam,x
        dex
        dex
        bpl     @Copy
        rts

; Called in VBlank. Use the exact table phase while HDMA is active; identity
; fallback uses the displayed source pose. Fly has a fixed zero phase.
SelectWarpBackgroundPhase:
        RW_assume a16i16
        lda     demo_mode
        beq     @Zero
        lda     hdma_use_table
        beq     @Identity
        ldx     #0
        cmp     #649
        bne     :+
        ldx     #2
:
        lda     warp_background_table_phase,x
        rts
@Identity:
        lda     presented_demo_pose
        cmp     #WARP_BACKGROUND_MOTION_POSES
        bcs     @Zero
        asl
        tax
        lda     f:WarpBackgroundMotion,x
        rts
@Zero:
        lda     #0
        rts

ApplyWarpBackgroundScroll:
        RW_assume a16i16
        ldx     runtime_menu_open
        beq     :+
        rts
:
        ldx     warp_background_active
        bne     :+
        rts
:
        cmp     warp_background_phase
        bne     :+
        rts
:
        tax
        eor     warp_background_phase
        and     #$00FF
        bne     @BothAxes
        ; Vertical-only changes keep the resident X bytes. This is common
        ; for small pitch/elevation steps and avoids twenty packed additions.
        stx     warp_background_phase
        RW      a8
        lda     warp_background_phase+1
        clc
        .repeat 4, row
          .if row > 0
            adc #64
          .endif
          .repeat 5, column
            sta warp_background_oam+(row*5+column)*4+1
          .endrepeat
        .endrepeat
        jmp     @Upload
@BothAxes:
        RW_forced a16i16
        stx     warp_background_phase
        ; Build a row from one packed X/Y load. X stays below 256, so adding
        ; 64 neither carries into Y nor sets carry. Edge columns share X's
        ; low byte; their permanently different ninth bits clip opposite edges.
        .repeat 4, row
          lda   warp_background_phase
          clc
          .if row > 0
            adc #(row*64*256)
          .endif
          sta   warp_background_oam+(row*5+1)*4
          .repeat 3, column
            adc #64
            sta warp_background_oam+(row*5+column+2)*4
          .endrepeat
          sta   warp_background_oam+(row*5)*4
        .endrepeat
        RW      a8
@Upload:
        stz     OAMADDL
        stz     OAMADDH
        stz     DMAP7
        lda     #$04
        sta     BBAD7
        ldx     #.loword(warp_background_oam)
        stx     A1T7L
        stz     A1B7
        ldx     #80
        stx     DAS7L
        lda     #$80
        sta     MDMAEN
        RW      a16
@Done:
        rts
.endif

.segment "FLY_VIEWPORT_DATA"
WarpBackgroundTile:
        .incbin "../Data/Warp/WarpBackgroundTile.bin"
WarpBackgroundTileEnd:
.assert WarpBackgroundTileEnd-WarpBackgroundTile = 2048, error, "Backdrop must contain 64 OBJ tiles"

WarpBackgroundOAM:
        .incbin "../Data/Warp/WarpBackgroundOam.bin"
WarpBackgroundOAMEnd:
.assert WarpBackgroundOAMEnd-WarpBackgroundOAM = 544, error, "Backdrop OAM must cover all entries"
WarpBackgroundMotion:
        .incbin "../Data/Warp/WarpBackgroundMotion.bin"
WarpBackgroundMotionEnd:
.assert WarpBackgroundMotionEnd-WarpBackgroundMotion = WARP_BACKGROUND_MOTION_POSES*2, error, "Backdrop phases must match the demo track"
.segment "CODE"
