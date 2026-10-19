.segment "CODE"
; One bounded slice, preserving the surrounding renderer/sound call contract.
; NMI owns request, the worker owns build_request and the inactive table.
ServiceHdmaWarp:
        ; Foreground joins retain their ABI. Only the bounded NMI slices own
        ; the arithmetic now: sound/packing cannot postpone the deadline.
        rts
ServiceHdmaWarpSlice:
        php
        RW_forced a16i16
        pha
        phx
        phy
        lda     hdma_request_enabled
        bne     @Enabled
        stz     hdma_build_busy
        stz     hdma_build_completed
        jmp     HdmaWarpWorkerReturn
@Enabled:
        lda     hdma_build_busy
        beq     @Request
        jmp     @Band
@Request:
        lda     hdma_ready
        beq     :+
        jmp     HdmaWarpWorkerReturn    ; Let VBlank consume the publication.
:
.if WARP_BACKGROUND_MOTION_ENABLED
        lda     warp_background_request_phase
        cmp     warp_background_build_phase
        bne     @Snapshot
.endif
        lda     hdma_request_precise
        cmp     hdma_build_precise
        bne     @Snapshot
        lda     hdma_request_overscan
        cmp     hdma_build_overscan
        bne     @Snapshot
        lda     hdma_build_completed
        beq     @Snapshot
        ldx     #32
@Same:
        lda     hdma_request,x
        cmp     hdma_build_request,x
        bne     @Snapshot
        dex
        dex
        bpl     @Same
        jmp     HdmaWarpWorkerReturn
@Snapshot:
        lda     hdma_request_sequence
        bit     #1
        bne     @Snapshot
        sta     hdma_build_sequence
        ldx     #34
@Copy:
        lda     hdma_request,x
        sta     hdma_build_request,x
        dex
        dex
        bpl     @Copy
        lda     hdma_request_precise
        sta     hdma_build_precise
        lda     hdma_request_overscan
        sta     hdma_build_overscan
.if WARP_BACKGROUND_MOTION_ENABLED
        lda     warp_background_request_phase
        sta     warp_background_build_phase
.endif
        lda     hdma_build_sequence
        cmp     hdma_request_sequence
        bne     @Snapshot
        ; VBlank has consumed or rejected the previous publication. Reserve
        ; the back buffer while NMI keeps using its immutable active table.
        stz     hdma_ready
        stz     hdma_build_completed
        .repeat 5, component
          lda   hdma_build_request+14+component*2
          sta   hdma_source_camera+component*2
          lda   hdma_build_request+24+component*2
          sta   hdma_target_camera+component*2
        .endrepeat
        jsr     LatchHdmaBuildLine
        sta     hdma_build_start_line
        jsl     BuildHdmaWarp
        jmp     HdmaWarpWorkerReturn
@Band:
        jsl     BuildHdmaWarpBand
        lda     hdma_build_busy
        beq     :+
        jmp     HdmaWarpWorkerReturn
:
        jsr     PublishHdmaWarpTable
        jmp     HdmaWarpWorkerReturn

PublishHdmaWarpTable:
        ldx     #0
        lda     hdma_build_base
        beq     :+
        ldx     #36
:
        .repeat 18, word
          lda   hdma_build_request+word*2
          sta   hdma_table_metadata+word*2,x
        .endrepeat
        ldx     #0
        lda     hdma_build_base
        beq     :+
        ldx     #2
:
        lda     hdma_build_precise
        sta     hdma_table_precise,x
        lda     hdma_build_overscan
        sta     hdma_table_overscan,x
.if WARP_BACKGROUND_MOTION_ENABLED
        lda     warp_background_build_phase
        sta     warp_background_table_phase,x
.endif
        jsr     LatchHdmaBuildLine
        sta     hdma_build_end_line
        lda     #1
        sta     hdma_build_completed
        lda     hdma_build_request+34
        sta     hdma_ready_tick
        lda     hdma_build_base
        inc
        sta     hdma_ready              ; Atomic publication after bytes and key.
HdmaBuildFinished:
        rts
HdmaWarpWorkerReturn:
        ply
        plx
        pla
        plp
        rts

; All PPU writes and input processing have finished before this CPU-only tail.
; Live audio uses twelve/twenty bands and reserves phase zero from video DMA.
; Silent/fly playback retains ten/twenty-two for its larger camera setup.
; Latch the split and packet enable together so a mode change cannot skip bands.
ServiceHdmaWarpDeadline:
        RW_forced a16i16
        lda     runtime_menu_open
        beq     :+
        jmp     @Reset
:
        lda     hdma_request_enabled
        bne     :+
        jmp     @Reset
:
        lda     hdma_deadline_phase
        bne     @Finish
        lda     hdma_deadline_armed
        beq     @Start
        inc     hdma_deadline_checks
        lda     hdma_deadline_tick
        cmp     video_tick
        bne     @Miss
        lda     hdma_applied_sample_tick
        clc
        adc     #2
        cmp     video_tick
        bne     @Miss
        lda     hdma_use_table
        bne     @Start
@Miss:
        inc     hdma_deadline_misses
@Start:
        lda     hdma_ready
        bne     @Reset                ; A changed epoch/page did not consume it.
        stz     hdma_build_completed   ; Even a static camera gets a dated table.
        jsr     ServiceHdmaWarpSlice   ; Setup only.
        stz     hdma_audio_enabled
        ldx     #10
        ldy     #22
.if BSP_SOUND_ENABLED
        jsr     QuakeSoundCompatible
        bcc     @SplitReady
        lda     sound_cpu_state
        cmp     #SOUND_CPU_STATE_PLAYING
        bne     @SplitReady
        inc     hdma_audio_enabled
        ldx     #12
        ldy     #20
.endif
@SplitReady:
        sty     hdma_deadline_tail
        txa
        sta     hdma_deadline_bands
        lda     video_tick
        clc
        adc     #2
        sta     hdma_deadline_tick
        lda     #1
        sta     hdma_deadline_armed
        sta     hdma_deadline_phase
        bra     @Bands
@Finish:
        stz     hdma_deadline_phase
        lda     hdma_deadline_tail
        sta     hdma_deadline_bands
@Bands:
        jsl     BuildHdmaWarpBands
        lda     hdma_build_busy
        bne     :+
        jsr     PublishHdmaWarpTable
:
        jsr     LatchHdmaBuildLine
        sta     hdma_deadline_end_line
        jmp     HdmaDeadlineSliceFinished
@Reset:
        stz     hdma_audio_enabled
        stz     hdma_deadline_phase
        stz     hdma_deadline_armed
        stz     hdma_ready
        stz     hdma_build_busy
        stz     hdma_build_completed
        rts
HdmaDeadlineSliceFinished:
        rts

HdmaWarpJoinFX3:
        php
        RW_forced a16i16
        pha
        phy
@Wait:
        ldx     FX3_R15
        beq     @Done
        jsr     ServiceHdmaWarp
.if BSP_SOUND_ENABLED
        jsr     HdmaWarpSoundSlice
.endif
        bra     @Wait
@Done:
        ply
        pla
        plp
        rts

HdmaWarpWaitFrame:
        php
        RW_forced a16i16
        pha
        lda     video_tick
        sta     hdma_wait_tick
@Wait:
        jsr     ServiceHdmaWarp
.if BSP_SOUND_ENABLED
        jsr     HdmaWarpSoundSlice
.endif
        lda     video_tick
        cmp     hdma_wait_tick
        beq     @Wait
        pla
        plp
        rts

.if BSP_SOUND_ENABLED
; READY/DISABLED still observe playback changes each video tick. Streaming
; gets one service slice per two join polls; joins retain the existing
; rule that cache completion/start is published at the main-loop boundary.
HdmaWarpSoundSlice:
        RW_assume a16i16
        lda     sound_cpu_state
        cmp     #SOUND_CPU_STATE_PLAYING
        bcs     @Streaming
        lda     video_tick
        cmp     hdma_sound_tick
        beq     @Done
        sta     hdma_sound_tick
        jmp     QuakeSoundServiceMain
@Streaming:
        inc     hdma_sound_slice
        lda     hdma_sound_slice
        and     #1
        bne     @Done
        lda     sound_cpu_state
        cmp     #SOUND_CPU_STATE_LOADING
        bne     @Service
        lda     sound_cache_slot
        cmp     #BSP_SOUND_CACHE_CHUNK_COUNT
        bcc     @Service
        lda     video_tick
        cmp     #SOUND_BOOT_START_TICK
        bcs     @Done
@Service:
        jmp     QuakeSoundServiceMain
@Done:
        rts
.endif
