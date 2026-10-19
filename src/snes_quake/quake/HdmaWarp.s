; VBlank publishes complete tables, then its CPU-only tail builds one bounded
; slice after every PPU write. Two slices produce the next 30 Hz camera view.
.segment "CODE"
HdmaReferenceMatches:
        RW_assume a16i16
        .repeat 2, angle
          lda   fly_warp_reference_yaw+angle*2
          cmp   hdma_table_metadata+angle*2,x
          bne   @Miss
        .endrepeat
        .repeat 3, position
          lda   fly_warp_reference_x+position*2
          cmp   hdma_table_metadata+4+position*2,x
          bne   @Miss
        .endrepeat
        lda     fly_warp_reference_epoch
        cmp     hdma_table_metadata+10,x
        bne     @Miss
        lda     fly_warp_target_page
        cmp     hdma_table_metadata+12,x
        bne     @Miss
        ldx     hdma_metadata_slot
        lda     fly_warp_reference_overscan
        cmp     hdma_table_overscan,x
        bne     @Miss
        sec
        rts
@Miss:
        clc
        rts

HdmaMetadataIndex:
        ldx     #0
        stz     hdma_metadata_slot
        cmp     #649
        bne     :+
        ldx     #2
        stx     hdma_metadata_slot
        ldx     #36
:
        stx     hdma_metadata_offset
        rts

CheckHdmaWarp:
        stz     hdma_use_table
        lda     fly_warp_enabled
        beq     @Done
        lda     runtime_menu_open
        bne     @Done
        ; The retained image keeps its own epoch through playback restarts.
        ; Its camera remains the correct source until a new image is mapped.
        lda     hdma_ready
        beq     @Active
        jsr     HdmaMetadataIndex
        jsr     HdmaReferenceMatches
        bcc     @RejectReady
        lda     hdma_ready
        stz     hdma_ready              ; NMI owns it until ApplyHdmaWarp returns.
        bra     @Use
@RejectReady:
        ; A complete table can belong to the pending image. Leave it intact
        ; until that image is published later in this same VBlank.
@Active:
        lda     hdma_active_valid
        beq     @Miss
        lda     hdma_active
        inc
        jsr     HdmaMetadataIndex
        jsr     HdmaReferenceMatches
        bcc     @Miss
        lda     hdma_active
        inc
@Use:
        sta     hdma_use_table
        rts
@Miss:
        inc     hdma_miss_count
@Done:
        rts

ApplyHdmaWarp:
        RW_forced a16i16
        lda     hdma_use_table
        bne     @Table
        RW      a8
        lda     fly_warp_target_page
        jmp     SetFlyMode7Display
@Table:
        RW_forced a16i16
        lda     hdma_use_table
        dec
        sta     hdma_active
        tax
        ; First band is also preloaded. Native probes qualify HBlank line 0
        ; and every following seven-line boundary against PPU pixels.
        RW      a8
        .repeat 4, channel
          .repeat 4, byte
            lda hdma_tables+channel*162+1+byte,x
            .if channel = 0
              sta M7A+(byte/2)
            .elseif channel = 1
              sta M7C+(byte/2)
            .elseif channel = 2
              sta M7X+(byte/2)
            .else
              sta BG1HOFS+(byte/2)
            .endif
          .endrepeat
        .endrepeat
        .repeat 4, channel
          lda   #3
          sta   DMAP0+channel*$10
          .if channel = 0
            lda #$1B
          .elseif channel = 1
            lda #$1D
          .elseif channel = 2
            lda #$1F
          .else
            lda #$0D
          .endif
          sta   BBAD0+channel*$10
          lda   #0
          sta   A1B0+channel*$10
          RW    a16
          txa
          clc
          adc   #.loword(hdma_tables+channel*162)
          sta   A1T0L+channel*$10
          RW    a8
        .endrepeat
        lda     #$0F
        sta     HDMAEN
        RW      a16
        ldx     hdma_metadata_offset
        lda     hdma_table_metadata+34,x
        sta     hdma_applied_sample_tick
        .repeat 5, component
          lda   hdma_table_metadata+14+component*2,x
          sta   hdma_applied_source+component*2
          lda   hdma_table_metadata+24+component*2,x
          sta   hdma_applied_target+component*2
        .endrepeat
        lda     #1
        sta     hdma_active_valid
        lda     video_tick
        sta     hdma_applied_tick
        ldx     hdma_metadata_slot
        lda     hdma_table_overscan,x
        sta     hdma_applied_overscan
        inc     hdma_apply_count
.if WARP_BACKGROUND_MOTION_ENABLED
        jsr     SelectWarpBackgroundPhase
        jsr     ApplyWarpBackgroundScroll
.endif
        rts

FinishHdmaWarpCamera:
        RW_forced a16i16
        lda     fly_warp_enabled
        beq     @Disabled
        lda     fly_playback_mode
        cmp     #RUNTIME_MENU_PLAYBACK_FLY3X
        bne     @Disabled
        lda     runtime_menu_open
        beq     @Enabled
@Disabled:
        stz     hdma_request_enabled
        rts
@Enabled:
        lda     presented_format
        cmp     #BSP_UPLOAD_FORMAT_MODE7
        beq     :+
        lda     upload_active
        beq     @Disabled
        lda     upload_format
        cmp     #BSP_UPLOAD_FORMAT_MODE7
        bne     @Disabled
        lda     upload_chunk
        cmp     #2
        bne     @Disabled
:
        lda     #1
        sta     hdma_request_enabled
        inc     hdma_request_sequence
        lda     upload_active
        beq     @Current
        lda     upload_format
        cmp     #BSP_UPLOAD_FORMAT_MODE7
        bne     @Current
        lda     upload_chunk
        cmp     #2
        bne     @Current
        jsr     LoadUploadFlyWarpReference
        bra     @Camera
@Current:
        jsr     LoadPresentedFlyWarpReference
@Camera:
        lda     fly_warp_reference_overscan
        sta     hdma_request_overscan
.if WARP_BACKGROUND_MOTION_ENABLED
        stz     warp_background_request_phase
.endif
        lda     demo_mode
        sta     hdma_request_precise
        beq     @Fly
        .repeat 3, axis
          lda   demo_warp_camera+axis*2
          sec
          .if axis = 0
            sbc #.loword(BSP_WORLD_ORIGIN_X*8)
          .elseif axis = 1
            sbc #.loword(BSP_WORLD_ORIGIN_Y*8)
          .else
            sbc #.loword(BSP_WORLD_ORIGIN_Z*8)
          .endif
          asl
          sta   hdma_request+24+axis*2
        .endrepeat
        lda     demo_warp_camera+6
        sta     hdma_request+24+6
        lda     demo_warp_camera+8
        sta     hdma_request+24+8
.if WARP_BACKGROUND_MOTION_ENABLED
        lda     demo_warp_pose
        asl
        tax
        lda     f:WarpBackgroundMotion,x
        sta     warp_background_request_phase
.endif
        bra     @Snapshot
@Fly:
        lda     camera_x
        sta     hdma_request+24
        lda     camera_y
        sta     hdma_request+24+2
        lda     camera_z
        sta     hdma_request+24+4
        lda     yaw_index
        xba
        and     #$FF00
        sta     hdma_request+24+6
        lda     pitch_level
        xba
        and     #$FF00
        sta     hdma_request+24+8
@Snapshot:
        .repeat 3, axis
          lda   fly_warp_reference_x+axis*2
          sta   hdma_request+14+axis*2
          sta   hdma_request+4+axis*2
        .endrepeat
        .repeat 2, angle
          lda   fly_warp_reference_yaw+angle*2
          sta   hdma_request+angle*2
          xba
          and   #$FF00
          sta   hdma_request+20+angle*2
        .endrepeat
        lda     fly_warp_reference_epoch
        sta     hdma_request+10
        lda     fly_warp_target_page
        sta     hdma_request+12
        lda     video_tick
        sta     hdma_request+34
        inc     hdma_request_sequence
        rts

LatchHdmaBuildLine:
        RW      a8
        lda     STAT78
        lda     SLHV
        lda     OPVCT
        sta     hdma_line_latch
        lda     OPVCT
        and     #1
        sta     hdma_line_latch+1
        RW      a16
        lda     hdma_line_latch
        rts

.include "WarpFocalTables.s"
.include "HdmaWarpWorker.s"
.include "HdmaWarpMath.s"
.include "HdmaWarpCamera.s"
.include "HdmaWarpRecurrence.s"
.include "HdmaWarpBands.s"
.include "HdmaWarpPhase.s"
.include "HdmaWarpBuild.s"
.include "HdmaWarpTables.s"
.include "HdmaWarpLogLow.s"
.include "HdmaWarpLogHigh.s"
.include "HdmaWarpExp.s"
.segment "CODE"
