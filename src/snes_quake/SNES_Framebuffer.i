; Shared helpers for examples that present centered SNES framebuffer viewports.

.ifndef __SNES_FRAMEBUFFER_I__
__SNES_FRAMEBUFFER_I__ = 1

SNES_FRAMEBUFFER_FRAME_TILES                  = 256
SNES_FRAMEBUFFER_BLANK_TILE                   = SNES_FRAMEBUFFER_FRAME_TILES
SNES_FRAMEBUFFER_VIEWPORT_TILES               = 16
SNES_FRAMEBUFFER_VIEWPORT_TILE_X              = 8
SNES_FRAMEBUFFER_VIEWPORT_TILE_Y              = 6

SNES_FRAMEBUFFER_2BPP_TILE_BYTES              = 16
SNES_FRAMEBUFFER_4BPP_TILE_BYTES              = 32
SNES_FRAMEBUFFER_8BPP_TILE_BYTES              = 64
SNES_FRAMEBUFFER_2BPP_FRAME_BYTES             = SNES_FRAMEBUFFER_FRAME_TILES * SNES_FRAMEBUFFER_2BPP_TILE_BYTES
SNES_FRAMEBUFFER_4BPP_FRAME_BYTES             = SNES_FRAMEBUFFER_FRAME_TILES * SNES_FRAMEBUFFER_4BPP_TILE_BYTES
SNES_FRAMEBUFFER_8BPP_FRAME_BYTES             = SNES_FRAMEBUFFER_FRAME_TILES * SNES_FRAMEBUFFER_8BPP_TILE_BYTES
SNES_FRAMEBUFFER_2BPP_FRAME_WITH_BLANK_BYTES  = (SNES_FRAMEBUFFER_FRAME_TILES + 1) * SNES_FRAMEBUFFER_2BPP_TILE_BYTES
SNES_FRAMEBUFFER_4BPP_FRAME_WITH_BLANK_BYTES  = (SNES_FRAMEBUFFER_FRAME_TILES + 1) * SNES_FRAMEBUFFER_4BPP_TILE_BYTES
SNES_FRAMEBUFFER_8BPP_FRAME_WITH_BLANK_BYTES  = (SNES_FRAMEBUFFER_FRAME_TILES + 1) * SNES_FRAMEBUFFER_8BPP_TILE_BYTES

; Private parameterized BG1 register sequence used by every public depth wrapper.
.macro __SNES_FRAMEBUFFER_SETUP_BG1 bg_mode, tilemap_base, tiles_base
        lda     #bgmode(bg_mode, BG3_PRIO_NORMAL, BG_SIZE_8X8, BG_SIZE_8X8, BG_SIZE_8X8, BG_SIZE_8X8)
        sta     BGMODE
        lda     #bgsc(tilemap_base, SC_SIZE_32X32)
        sta     BG1SC
        lda     #bg12nba(tiles_base, 0)
        sta     BG12NBA
        stz     BG1HOFS
        stz     BG1HOFS
        stz     BG1VOFS
        stz     BG1VOFS
        lda     #tm(ON, OFF, OFF, OFF, OFF)
        sta     TM
.endmacro

; 2bpp contract: BGMODE=0, SCMR=$08, 21.4 MHz GSU clock, 16 bytes/tile.
; Ownership/upload: callers grant GSU RAM access with SCMR.RAN while rendering,
; then clear RAN before CPU DMA. This wrapper uploads nothing; choose the raw or
; frame-with-blank byte constant explicitly.
.macro SETUP_BG1_FRAMEBUFFER_2BPP tilemap_base, tiles_base
        __SNES_FRAMEBUFFER_SETUP_BG1 BG_MODE_0, tilemap_base, tiles_base
.endmacro

; 4bpp contract: BGMODE=1, SCMR=$09, 21.4 MHz GSU clock, 32 bytes/tile.
; Ownership/upload: callers grant GSU RAM access with SCMR.RAN while rendering,
; then clear RAN before CPU DMA. This wrapper uploads nothing; choose the raw or
; frame-with-blank byte constant explicitly.
.macro SETUP_BG1_FRAMEBUFFER_4BPP tilemap_base, tiles_base
        __SNES_FRAMEBUFFER_SETUP_BG1 BG_MODE_1, tilemap_base, tiles_base
.endmacro

; 8bpp contract: BGMODE=3, SCMR=$0B, 21.4 MHz GSU clock, 64 bytes/tile.
; Ownership/upload: callers grant GSU RAM access with SCMR.RAN while rendering,
; then clear RAN before CPU DMA. This wrapper uploads nothing; choose the raw or
; frame-with-blank byte constant explicitly.
.macro SETUP_BG1_FRAMEBUFFER_8BPP tilemap_base, tiles_base
        __SNES_FRAMEBUFFER_SETUP_BG1 BG_MODE_3, tilemap_base, tiles_base
.endmacro

; Private parameterized GSU register sequence used by every public depth wrapper.
.macro __SNES_FRAMEBUFFER_INIT_GSU framebuffer_scb, screen_mode
        lda     #$70
        sta     GSU_PBR
        stz     GSU_RAMBR
        lda     #framebuffer_scb
        sta     GSU_SCBR
        lda     #screen_mode
        sta     GSU_SCMR
        lda     #%10000000
        sta     GSU_CFGR
        lda     #$01                    ; Always select the 21.4 MHz GSU clock.
        sta     GSU_CLSR
.endmacro

; 2bpp contract: BGMODE=0, SCMR=$08, 21.4 MHz GSU clock, 16 bytes/tile.
; Ownership/upload: returns with RAN=1 for GSU RAM ownership; performs no upload,
; so callers explicitly choose raw-frame or frame-with-blank sizing.
.macro INIT_GSU_128X128_2BPP framebuffer_scb
        __SNES_FRAMEBUFFER_INIT_GSU framebuffer_scb, %00001000
.endmacro

; 4bpp contract: BGMODE=1, SCMR=$09, 21.4 MHz GSU clock, 32 bytes/tile.
; Ownership/upload: returns with RAN=1 for GSU RAM ownership; performs no upload,
; so callers explicitly choose raw-frame or frame-with-blank sizing.
.macro INIT_GSU_128X128_4BPP framebuffer_scb
        __SNES_FRAMEBUFFER_INIT_GSU framebuffer_scb, %00001001
.endmacro

; 8bpp contract: BGMODE=3, SCMR=$0B, 21.4 MHz GSU clock, 64 bytes/tile.
; Ownership/upload: returns with RAN=1 for GSU RAM ownership; performs no upload,
; so callers explicitly choose raw-frame or frame-with-blank sizing.
.macro INIT_GSU_128X128_8BPP framebuffer_scb
        __SNES_FRAMEBUFFER_INIT_GSU framebuffer_scb, %00001011
.endmacro

.macro CENTERED_FRAMEBUFFER_TILEMAP blank_tile, column_major
  .repeat SNES_FRAMEBUFFER_VIEWPORT_TILE_Y
    .repeat 32
      .word blank_tile
    .endrepeat
  .endrepeat
  .repeat SNES_FRAMEBUFFER_VIEWPORT_TILES, row
    .repeat SNES_FRAMEBUFFER_VIEWPORT_TILE_X
      .word blank_tile
    .endrepeat
    .repeat SNES_FRAMEBUFFER_VIEWPORT_TILES, col
      .if column_major
        .word col * SNES_FRAMEBUFFER_VIEWPORT_TILES + row
      .else
        .word row * SNES_FRAMEBUFFER_VIEWPORT_TILES + col
      .endif
    .endrepeat
    .repeat 32 - SNES_FRAMEBUFFER_VIEWPORT_TILE_X - SNES_FRAMEBUFFER_VIEWPORT_TILES
      .word blank_tile
    .endrepeat
  .endrepeat
  .repeat (32 - SNES_FRAMEBUFFER_VIEWPORT_TILE_Y - SNES_FRAMEBUFFER_VIEWPORT_TILES) * 32
    .word blank_tile
  .endrepeat
.endmacro

; The GSU stores 128-dot-high BG screens in column-major character order.
.macro CENTERED_FRAMEBUFFER_TILEMAP_8BPP_128X128 blank_tile
        CENTERED_FRAMEBUFFER_TILEMAP blank_tile, 1
.endmacro

.endif
