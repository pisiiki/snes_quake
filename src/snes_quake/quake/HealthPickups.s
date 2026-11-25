.ifdef QC_HEALTH_COUNT
.pushseg

HEALTH_RECORD_BYTES = 18
HEALTH_SMALL_SAMPLE = 21
HEALTH_MAX_Q6 = 250*64
.ifdef QC_QUEUED_INPUT
HEALTH_ROT_HZ = QC_SIMULATION_HZ
.else
HEALTH_ROT_HZ = 64
.endif

.segment "LORAM"
pickup_render_mask: .res 2
.ifdef QC_MEGA_COUNT
pickup_render_high: .res 2
.endif
pickup_pixels_dirty: .res 2

; Table reads are long-addressed; share the map's allocated ROM bank
; with its immutable initial VM data, leaving bank zero for near code.
.segment "BSP_QUAKEC_INIT"
QuakeCHealthPacks:
        .repeat QC_HEALTH_COUNT, I
        .word   1 << I
        .word   .loword(.ident(.sprintf("QC_HEALTH_%d_X_MIN", I)) - BSP_WORLD_ORIGIN_X*16)
        .word   .ident(.sprintf("QC_HEALTH_%d_X_MAX", I)) - .ident(.sprintf("QC_HEALTH_%d_X_MIN", I)) + 1
        .word   .loword(.ident(.sprintf("QC_HEALTH_%d_Y_MIN", I)) - BSP_WORLD_ORIGIN_Y*16)
        .word   .ident(.sprintf("QC_HEALTH_%d_Y_MAX", I)) - .ident(.sprintf("QC_HEALTH_%d_Y_MIN", I)) + 1
        .word   .loword(.ident(.sprintf("QC_HEALTH_%d_Z_MIN", I)) - BSP_WORLD_ORIGIN_Z*16)
        .word   .ident(.sprintf("QC_HEALTH_%d_Z_MAX", I)) - .ident(.sprintf("QC_HEALTH_%d_Z_MIN", I)) + 1
        .word   .ident(.sprintf("QC_HEALTH_%d_AMOUNT", I))*64
        .word   .ident(.sprintf("QC_HEALTH_%d_SOUND", I))+1
        .endrepeat
.assert *-QuakeCHealthPacks = QC_HEALTH_COUNT*HEALTH_RECORD_BYTES, error, "health record size changed"

.segment "CODE"
; The shell touch gate already excludes menu and release. The player eye
; and health fields use the same WRAM bank as the existing QuakeC service.
QuakeCHealthTouch:
        RW_assume a16i16
        lda     a:qce+QC_ENTITY_STRIDE+QC_FIELD_HEALTH
        beq     @Reject
        bmi     @Reject
        cmp     #HEALTH_MAX_Q6
        bcc     @Scan
@Reject:
        rtl
@Scan:
        ldx     #0
@Box:
        lda     f:QuakeCHealthMask
        and     f:QuakeCHealthPacks,x
        bne     :+
        jmp     @Next
:       cpx     #QC_REGULAR_HEALTH_COUNT*HEALTH_RECORD_BYTES
        bcs     @Bounds
        lda     a:qce+QC_ENTITY_STRIDE+QC_FIELD_HEALTH
        cmp     a:qce+QC_ENTITY_STRIDE+QC_FIELD_MAX_HEALTH
        bcc     @Bounds
        jmp     @Next
@Bounds:
        .repeat 3, Axis
        lda     a:w_from+2*Axis
        sec
        sbc     f:QuakeCHealthPacks+2+4*Axis,x
        cmp     f:QuakeCHealthPacks+4+4*Axis,x
        bcc     :+
        jmp     @Next
:       .endrepeat
        lda     a:qce+QC_ENTITY_STRIDE+QC_FIELD_HEALTH
        clc
        adc     f:QuakeCHealthPacks+14,x
        cpx     #QC_REGULAR_HEALTH_COUNT*HEALTH_RECORD_BYTES
        bcs     @Limit
        cmp     a:qce+QC_ENTITY_STRIDE+QC_FIELD_MAX_HEALTH
        bcc     @Limit
        lda     a:qce+QC_ENTITY_STRIDE+QC_FIELD_MAX_HEALTH
@Limit: cmp     #HEALTH_MAX_Q6
        bcc     :+
        lda     #HEALTH_MAX_Q6
:       sta     a:qce+QC_ENTITY_STRIDE+QC_FIELD_HEALTH
        lda     f:QuakeCHealthPacks,x
        eor     f:QuakeCHealthMask
        sta     f:QuakeCHealthMask
.ifdef QC_PICKUP_NOTICES
        lda     f:QuakeCHealthPacks+16,x
        clc
        adc     #NOTICE_HEALTH15-1
        jsl     PickupNotify
.endif
        lda     f:QuakeCHealthPacks+16,x
        sta     f:QuakeCHealthSound
        cmp     #3
        bne     @RegularSound
        lda     f:QuakeCItemsHigh
        ora     #1
        sta     f:QuakeCItemsHigh
        ; Each consumed box owns its own stock item_megahealth_rot think.
        ldy     #0
        cpx     #(QC_REGULAR_HEALTH_COUNT+1)*HEALTH_RECORD_BYTES
        bcc     :+
        iny
        iny
:       lda     #5*HEALTH_ROT_HZ+1
        sta     a:.loword(QuakeCMegaTimers),y
        lda     #GAMEPLAY_MEGA_SAMPLE
        bra     @PlaySound
@RegularSound:
.ifdef QC_POWERUP_COUNT
        phx                            ; The MSU audio selector uses X; resume at this box.
        jsl     PowerupHealthSound
        plx
        bra     @Invalidate
.endif
        clc
        adc     #HEALTH_SMALL_SAMPLE-1
@PlaySound:
        inc     a:.loword(quakec_sounds)
        jsl     GameplayPlaySoundLong
@Invalidate:
        ; Also invalidate a stationary producer command after a pickup.
        phb
        phk
        plb
        inc     control_revision
        inc     pickup_pixels_dirty
        plb
@Next:
        txa
        clc
        adc     #HEALTH_RECORD_BYTES
        tax
        cpx     #QC_HEALTH_COUNT*HEALTH_RECORD_BYTES
        bcs     @Done
        jmp     @Box
@Done:
        rtl

.pushseg
.segment "BSP_QUAKEC"
; Called after the same menu/release gate as the monster thinkers.
QuakeCMegaRot:
        RW_assume a16i16
        ldx     #2*(QC_MEGA_COUNT-1)
@Box:   lda     a:.loword(QuakeCMegaTimers),x
        beq     @Next
        dec     a:.loword(QuakeCMegaTimers),x
        bne     @Next
        lda     a:qce+QC_ENTITY_STRIDE+QC_FIELD_HEALTH
        cmp     a:qce+QC_ENTITY_STRIDE+QC_FIELD_MAX_HEALTH
        beq     @Finished
        bmi     @Finished
        sec
        sbc     #64
        sta     a:qce+QC_ENTITY_STRIDE+QC_FIELD_HEALTH
        lda     #HEALTH_ROT_HZ
        sta     a:.loword(QuakeCMegaTimers),x
        bra     @Next
@Finished:
        lda     f:QuakeCItemsHigh
        and     #$fffe
        sta     f:QuakeCItemsHigh
@Next:  dex
        dex
        bpl     @Box
        rtl
.popseg

.macro QC_PICKUP_RENDER_BIT group, state, index
        .local skip
        lda     f:state
        bit     #(1 << index)
        beq     skip
        .if .ident(.sprintf("QC_%s_%d_RENDER_HIGH", .string(group), index))
        lda     pickup_render_high
        ora     #.ident(.sprintf("QC_%s_%d_RENDER_BIT", .string(group), index))
        sta     pickup_render_high
        .else
        lda     pickup_render_mask
        ora     #.ident(.sprintf("QC_%s_%d_RENDER_BIT", .string(group), index))
        sta     pickup_render_mask
        .endif
skip:
.endmacro

QuakeCExternalPickupMask:
        RW_assume a16i16
        stz     pickup_render_mask
        stz     pickup_render_high
        .repeat QC_SHELL_COUNT, I
        QC_PICKUP_RENDER_BIT SHELL, QuakeCShellMask, I
        .endrepeat
        .repeat QC_HEALTH_COUNT, I
        QC_PICKUP_RENDER_BIT HEALTH, QuakeCHealthMask, I
        .endrepeat
        .ifdef QC_NAIL_COUNT
        .repeat QC_NAIL_COUNT, I
        QC_PICKUP_RENDER_BIT NAIL, QuakeCNailMask, I
        .endrepeat
        .endif
        .ifdef QC_EXPLOBOX
        lda     f:QuakeCEdicts+QC_EXPLOBOX+QC_FIELD_SOLID
        beq     :+
        .if QC_EXPLOBOX_0_RENDER_HIGH
        lda     pickup_render_high
        ora     #QC_EXPLOBOX_0_RENDER_BIT
        sta     pickup_render_high
        .else
        lda     pickup_render_mask
        ora     #QC_EXPLOBOX_0_RENDER_BIT
        sta     pickup_render_mask
        .endif
:
        .endif
        lda     pickup_render_mask
        rts

QuakeCClearCollectedHealthPixels:
        RW_assume a16i16
        lda     pickup_pixels_dirty
        beq     :+
        ; An overlapped selector may still own a command staged before touch.
        jsr     QuakeCExternalPickupMask
        cmp     f:GSU_COMMAND+14
        bne     :+
        lda     pickup_render_high
        cmp     f:GSU_DATA_BASE+GSU_PICKUP_MASK_HIGH
        bne     :+
        stz     pickup_pixels_dirty
        ; Uncovered pixels must not retain the collected box's previous draw.
QuakeCClearVisibleOutput:
        lda     #0
.if .defined(PLAYABLE_RESIDENT_WORLD) && (BSP_RENDER_SCALE = 2)
        sta     f:GSU_DATA_BASE+GSU_RESIDENT_WORLD_STATUS
.endif
        sta     f:GSU_OUTPUT
        BSP_STATIC_COPY GSU_OUTPUT+1, GSU_OUTPUT, BSP_TEXTURE_CLEAR_BYTES-1
:       rts
.popseg
.endif
