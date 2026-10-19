; Immutable image-camera references and VBlank publication for HDMA warp.
; Legacy motion counters remain available to movement/regression telemetry.
AccumulateFlyMode7Movement:
        RW_assume a16i16
        lda     camera_input_buttons
        bit     #JOY_X
        beq     :+
        inc     fly_warp_forward
:
        bit     #JOY_B
        beq     :+
        dec     fly_warp_forward
:
        bit     #JOY_A
        beq     :+
        inc     fly_warp_strafe
:
        bit     #JOY_Y
        beq     :+
        dec     fly_warp_strafe
:
        rts

ClampFlyWarpShift:
        RW_assume a16i16
        bmi     @Negative
        cmp     #81
        bcc     @Done
        lda     #80
        rts
@Negative:
        cmp     #.loword(-80)
        bcs     @Done
        lda     #.loword(-80)
@Done:
        rts

; One transform per VBlank. A completing upload prepares its new reference
; before DMA and writes it at the page switch, instead of warping both pages.
UpdateFlyMode7Warp:
        RW_forced a8i16
        stz     HDMAEN
        RW      a16
        lda     presented_format
        cmp     #BSP_UPLOAD_FORMAT_MODE7
        beq     :+
        rts
:
@Current:
        jsr     LoadPresentedFlyWarpReference
        jsr     CalculateFlyMode7Warp
        jmp     WriteFlyMode7Warp

LoadPresentedFlyWarpReference:
        RW_assume a16i16
        lda     presented_camera+10
        and     #$8000
        sta     fly_warp_reference_overscan
        lda     fly_warp_page
        sta     fly_warp_target_page
        lda     presented_warp_yaw
        sta     fly_warp_reference_yaw
        lda     presented_warp_pitch
        sta     fly_warp_reference_pitch
        lda     presented_warp_strafe
        sta     fly_warp_reference_strafe
        lda     presented_warp_forward
        sta     fly_warp_reference_forward
        lda     presented_warp_x
        sta     fly_warp_reference_x
        lda     presented_warp_y
        sta     fly_warp_reference_y
        lda     presented_warp_z
        sta     fly_warp_reference_z
        lda     presented_warp_epoch
        sta     fly_warp_reference_epoch
        rts

PrepareFlyMode7UploadWarp:
        RW_forced a16i16
        jsr     LoadUploadFlyWarpReference
        jmp     CalculateFlyMode7Warp

LoadUploadFlyWarpReference:
        RW_assume a16i16
        lda     upload_target
        sta     fly_warp_target_page
        ldx     #0
        lda     upload_slot
        beq     :+
        ldx     #CAMERA_COMMAND_BYTES
:
        lda     slot_camera+0,x
        sta     fly_warp_reference_yaw
        lda     slot_camera+2,x
        sta     fly_warp_reference_pitch
        lda     slot_camera+10,x
        and     #$8000
        sta     fly_warp_reference_overscan
        lda     upload_slot
        asl
        tax
        lda     slot_warp_x,x
        sta     fly_warp_reference_x
        lda     slot_warp_y,x
        sta     fly_warp_reference_y
        lda     slot_warp_z,x
        sta     fly_warp_reference_z
        lda     slot_warp_strafe,x
        sta     fly_warp_reference_strafe
        lda     slot_warp_forward,x
        sta     fly_warp_reference_forward
        lda     slot_demo_epoch,x
        sta     fly_warp_reference_epoch
        rts

CalculateFlyMode7Warp:
        RW_assume a16i16
        stz     fly_warp_shift_x
        stz     fly_warp_shift_y
        stz     fly_warp_zoom
        lda     #85
        sta     fly_warp_scale
        jmp     CheckHdmaWarp

WriteFlyMode7Warp:
        RW_forced a8i16
        lda     HVBJOY
        bpl     @Defer
        lda     STAT78
        lda     SLHV
        lda     OPVCT
        sta     fly_warp_write_scanline
        lda     OPVCT
        and     #1
        sta     fly_warp_write_scanline+1
        RW      a16
        lda     fly_warp_write_scanline
        cmp     #261
        bcc     @Write
@Defer:
        RW_forced a16i16
        inc     fly_warp_deferred_counter
        rts
@Write:
        jsr     ApplyHdmaWarp
        RW_forced a16i16
        lda     fly_warp_target_page
        sta     fly_warp_page
        lda     video_tick
        cmp     fly_warp_tick
        beq     @Done
        sta     fly_warp_tick
        inc     fly_warp_update_counter
@Done:
        rts
