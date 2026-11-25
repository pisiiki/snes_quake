; A frame freezes its switchable lamps and fluorescent phase for both renderers.
.import SwitchedGridRequest:far, SwitchedGridResume:far, F3_SwitchedGridResume:far
.import SwitchedGridResident:far, F3_SwitchedGridResident:far
.segment "LORAM"
switched_render_mask: .res 2
switched_staging_mask: .res 2
switched_scheduled_mask: .res 2
switched_flat_valid: .res 2             ; Active table plus one; Full invalidates.
switched_destination: .res 2

.segment "BSP_QUAKEC"
SwitchedFrameMask:
        RW_assume a16i16
        lda     f:qc_fluorescent_phase_wram
        tax
        lda     f:SwitchedFluorescent,x
        and     #32
        ora     f:qc_ord_lights
        tax
        lda     f:qc_t3_state_wram
        and     #16
        sta     switched_render_mask
        txa
        ora     switched_render_mask
        rtl
SwitchedFluorescent:
        .repeat 160, tick
        .byte 32 * (.strat("mmamammmmammamamaaamammma", tick * 10 / 64) = 'a')
        .endrepeat
SwitchedGridSeeks:
        .repeat 64, mask
        .dword SWITCHED_GRID_SEEK + 2 * mask * SWITCHED_LIGHT_STRIDE
        .endrepeat

.segment "CODE"
SwitchedStageFlat:
        RW_assume a16i16
        lda     render_camera+10
        and     #$00ff
        cmp     #3
        beq     @Flat
        stz     switched_flat_valid
        rts
@Flat:
        lda     switched_render_mask
        inc
        cmp     switched_flat_valid
        beq     @Done
        sta     switched_flat_valid
        dec
        xba
        asl
        asl
        clc
        adc     #.loword(SWITCHED_COLOR_SEEK)
        sta     playable_archive_seek
        lda     #.hiword(SWITCHED_COLOR_SEEK)
        adc     #0
        sta     playable_archive_seek+2
        ldx     #GSU_LIGHTMAP_CACHE_OFFSET
        lda     #512
        jmp     SwitchedRead
@Done:  rts

SwitchedGridFill:
        RW_assume a16i16
        lda     FX3_R12                 ; Exact checked width times height.
        beq     SwitchedBadRequest
        cmp     #GSU_LIGHTMAP_CACHE_BYTES+1
        bcs     SwitchedBadRequest
        ldx     FX3_R14                 ; Byte offset of the face descriptor.
        lda     switched_render_mask
        eor     #15                     ; Resident reference has all six lamps on.
        and     f:SWITCHED_GRID_DIRECTORY+4,x
        bne     @Stream
        lda     f:SWITCHED_GRID_DIRECTORY+2,x
        sta     FX3_R14                 ; The decoder re-arms R14 after selecting ROMB.
        lda     f:SWITCHED_GRID_DIRECTORY+4,x
        xba
        and     #$00FF
        sta     FX3_R7
        lda     #.loword(SwitchedGridResident)
        rts
@Stream:
        lda     f:SWITCHED_GRID_DIRECTORY,x
        tay
        lda     switched_render_mask
        asl
        asl
        tax
        tya                             ; Byte offset of the color preceding the grid.
        inc
        asl
        clc
        adc     f:SwitchedGridSeeks,x
        sta     playable_archive_seek
        lda     f:SwitchedGridSeeks+2,x
        adc     #0
        sta     playable_archive_seek+2
        ldx     FX3_R10
        lda     FX3_R12
SwitchedRead:
        stx     switched_destination
        pha                             ; Save the requested length across the seek.
        RW      a8
        lda     playable_archive_busy
        bne     SwitchedBadRequest
        inc     playable_archive_busy
        jsr     PlayableEnsureArchive
        jsr     PlayableSeekArchive
        RW      a16
        pla
        jsl     SwitchedCopyCheckedGroups
        RW_assume a8i16
        stz     playable_archive_busy
        RW      a16
        lda     #.loword(SwitchedGridResume)
        rts
SwitchedBadRequest:
        RW_forced a8i16
        lda     #10
        jmp     PlayableArchiveFatal

; Archive ownership, MMIO checks and seek stay in the module CPU bank.
.pushseg
.segment "BSP_CPU_WALK_RUN"
SwitchedCopyCheckedGroups:
        RW_assume a16i16
        dec
        tax
        lsr
        lsr
        inc
        tay                             ; ceil(length / 4) groups.
        txa
        ldx     switched_destination
        phb
        phd
        pea     $2000
        pld
        pea     ^GSU_DATA_BASE * $0101
        plb
        plb
        cld
        RW      a8
        and     #3
        cmp     #2
        bcc     @ShortEntry
        beq     @Copy3
.macro SWITCHED_CHECKED_BYTE bad_pair
        lda     z:$01
        sta     a:$0000,x               ; DBR is the stopped FX3 data bank.
        ; Only a complement with carry set produces zero and carry set.
        adc     z:$01
        bne     bad_pair
        inx
.endmacro
@Copy4:
        SWITCHED_CHECKED_BYTE @BadPair
@Copy3:
        SWITCHED_CHECKED_BYTE @BadPair
@Copy2:
        SWITCHED_CHECKED_BYTE @BadPair
@Copy1:
        SWITCHED_CHECKED_BYTE @BadPair
        dey
        bne     @Copy4
.delmacro SWITCHED_CHECKED_BYTE
        pld
        plb
        rtl
@ShortEntry:
        RW_assume a8i16
        cmp     #1
        beq     @Copy2
        sec
        bra     @Copy1
@BadPair:
        pld
        plb
        jml     SwitchedBadRequest
.popseg
