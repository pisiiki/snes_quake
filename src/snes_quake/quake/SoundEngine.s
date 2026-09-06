; Eight-voice 8 kHz Quake sound scheduler and cartridge-to-SPC streamer.

SOUND_COMMAND_UPLOAD_STREAM = $01
SOUND_COMMAND_UPLOAD_CACHE  = $02
SOUND_COMMAND_BEGIN         = $03
SOUND_COMMAND_STOP_ALL      = $04
SOUND_COMMAND_SYNC          = $05
SOUND_COMMAND_CANCEL_STREAM = $06
SOUND_COMMAND_SET_BASE      = $20
SOUND_COMMAND_START_BASE    = $40
SOUND_COMMAND_STOP_BASE     = $60
SOUND_COMMAND_VOLUME_BASE   = $80
SOUND_COMMAND_VOICE_MASK    = $07
SOUND_STATUS_READY          = $08
SOUND_STATUS_ERROR          = $20
SOUND_REQUEST_NONE          = $FF
SOUND_SAMPLE_FLAG_LOOP      = $01
SOUND_MIX_START             = 1
SOUND_MIX_STOP              = 2
SOUND_MIX_VOLUME            = 3
SOUND_MIX_COMPLETE          = 4
SOUND_NO_CHUNK              = $FFFF
SOUND_UPLOAD_CONTINUE_NONE  = 0
SOUND_UPLOAD_CONTINUE_REFILL = 1
SOUND_UPLOAD_CONTINUE_START = 2
; Twenty-four packets per realtime slice cover the dense four-stream mix
; while retaining interruptible transfers outside VBlank. A 576-byte chunk
; takes eight slices. Ordered playback uses eight packets and also pumps
; refills while waiting for the next video tick.
SOUND_UPLOAD_BATCH_PACKETS_REALTIME = 24
SOUND_UPLOAD_BATCH_PACKETS_ORDERED = 8
SOUND_JOIN_POLL_COUNT       = 4
SOUND_BOOT_START_TICK       = 240
; Realtime presents source poses after the renderer finishes.  The current
; full-route median presentation age is 30 NTSC ticks (499.18 ms), so keep the
; dry soundtrack one half-second behind the source clock on real hardware.
; Ordered 2 Hz is render-completion paced and must retain its zero offset.
SOUND_REALTIME_PRESENTATION_OFFSET_TICKS = 30
SOUND_CHUNK_TICK_NUMERATOR  = 125
SOUND_CHUNK_TICK_DENOMINATOR = 960

.if BSP_SOUND_ENABLED
.import QuakeSoundDriver

.segment "CODE"
QuakeSoundInit:
        RW_assume a16i16
        stz     sound_cpu_state
        stz     sound_service_busy
        stz     sound_demo_epoch
        stz     sound_demo_loop
        stz     sound_start_tick
        stz     sound_elapsed_tick
        stz     sound_target_tick
        stz     sound_next_command
        stz     sound_mix_command_counter
        stz     sound_driver_status
        stz     sound_driver_request
        stz     sound_driver_command_counter
        stz     sound_upload_active
        stz     sound_upload_continuation
        stz     sound_upload_offset
        stz     sound_pending_start_active
        stz     sound_pending_start_voice
        stz     sound_pending_start_relative
        stz     sound_pending_start_slot
        stz     sound_transfer_counter
        stz     sound_cache_transfer_counter
        stz     sound_stream_transfer_counter
        stz     sound_start_counter
        stz     sound_late_skip_counter
        stz     sound_stop_counter
        stz     sound_complete_counter
        stz     sound_protocol_error_counter
        stz     sound_status_error_counter
        stz     sound_request_error_counter
        stz     sound_stale_request_counter
        stz     sound_schedule_error_counter
        stz     sound_cancel_request_counter
        stz     sound_last_bad_request
        stz     sound_schedule_finished
        stz     sound_finished_epoch
        jsr     QuakeSoundClearVoiceState
        SMP_ready
        SMP_exec __SMPCODE_RUN__, __SMPCODE_LOAD__, __SMPCODE_SIZE__, QuakeSoundDriver
        RW_forced a8i16
@WaitForDriver:
        lda     SMPIO0
        cmp     #(BSP_SOUND_PROTOCOL_SIGNATURE | SOUND_STATUS_READY)
        bne     @WaitForDriver
        lda     SMPIO3
        sta     z:sound_command_token
        RW_forced a16i16
        stz     sound_cache_slot
        lda     f:GSU_BOOT_PARAMETERS+10
        and     #BOOT_PARAMETERS_PRESENT_ORDERED_SOURCE_POSE
        beq     @IncrementalCache
@DirectCacheLoop:
        lda     sound_cache_slot
        cmp     #BSP_SOUND_CACHE_CHUNK_COUNT
        bcs     @DirectCacheReady
        asl
        tax
        lda     f:QuakeBSPSoundCacheDirectory+BSP_SOUND_CPU_MIRROR_DELTA,x
        ldx     sound_cache_slot
        ldy     #SOUND_COMMAND_UPLOAD_CACHE
        jsr     QuakeSoundUploadChunk
        inc     sound_cache_slot
        bra     @DirectCacheLoop
@DirectCacheReady:
        lda     #SOUND_CPU_STATE_READY
        sta     sound_cpu_state
        lda     demo_track_pose
        jsr     QuakeSoundStartPose
        rts
@IncrementalCache:
        ; Cache warm-up shares the ordinary bounded upload pump with live
        ; refills. This lets video staging and the first render proceed while
        ; the one-time cartridge-to-ARAM preload runs outside VBlank.
        lda     #SOUND_CPU_STATE_LOADING
        sta     sound_cpu_state
        rts

QuakeSoundCompatible:
        RW_assume a16i16
        lda     demo_mode
        cmp     #$0001
        bne     @No
        lda     demo_schedule
        beq     @Ordered
        cmp     #$0001
        bne     @No
        lda     demo_playback_rate_shift
        bne     @No
        bra     @Menu
@Ordered:
        lda     demo_ordered_pose_stride
        cmp     #BSP_DEMO_ORDERED_POSE_STRIDE
        bne     @No
@Menu:
        lda     runtime_menu_open
        bne     @No
        sec
        rts
@No:
        clc
        rts

; A = exact configured-rate demo pose. Reconstruct the eight voice states at
; the pose's canonical tick, then resume each live source at its current chunk.
QuakeSoundStartPose:
        RW_assume a16i16
        sta     sound_work_pose
        jsr     QuakeSoundCompatible
        bcs     :+
        jmp     @Return
:
        lda     sound_work_pose
        cmp     #BSP_DEMO_PRECISE_TRACK_POSE_COUNT
        bcc     :+
        jmp     @Return
:
        asl
        tax
        lda     f:QuakeBSPDemoPreciseTiming,x
        sta     sound_target_tick
        lda     demo_schedule
        beq     @TargetReady
        lda     sound_target_tick
        sec
        sbc     #SOUND_REALTIME_PRESENTATION_OFFSET_TICKS
        bcs     @StoreTarget
        lda     #$0000
@StoreTarget:
        sta     sound_target_tick
@TargetReady:
        lda     sound_target_tick
        sta     sound_elapsed_tick
        lda     video_tick
        sec
        sbc     sound_target_tick
        sta     sound_start_tick
        jsr     QuakeSoundStopDriver
        jsr     QuakeSoundClearVoiceState
        stz     sound_next_command
@SeekCommand:
        lda     sound_next_command
        cmp     #BSP_SOUND_MIX_COMMAND_COUNT
        bcs     @SeekReady
        jsr     QuakeSoundLoadMixCommand
        lda     sound_work_due
        cmp     sound_target_tick
        bcs     @SeekReady
        jsr     QuakeSoundApplyShadowCommand
        inc     sound_next_command
        bra     @SeekCommand
@SeekReady:
        ldx     #$0000
        ldy     #$0000
        RW_forced a8i16
        lda     #SOUND_COMMAND_BEGIN
        jsr     QuakeSoundCommand
        RW_forced a16i16
        stz     sound_work_voice
@StartActive:
        lda     sound_work_voice
        asl
        tax
        lda     sound_voice_active,x
        beq     @NextVoice
        lda     sound_voice_sample,x
        sta     sound_work_sample
        lda     sound_voice_left,x
        sta     sound_work_left
        lda     sound_voice_right,x
        sta     sound_work_right
        lda     sound_voice_start_tick,x
        sta     sound_work_start_tick
        jsr     QuakeSoundStartVoice
@NextVoice:
        inc     sound_work_voice
        lda     sound_work_voice
        cmp     #BSP_SOUND_VOICE_COUNT
        bcc     @StartActive
        lda     demo_schedule_revision
        sta     sound_demo_epoch
        lda     demo_loop_counter
        sta     sound_demo_loop
        stz     sound_schedule_finished
        lda     #SOUND_CPU_STATE_PLAYING
        sta     sound_cpu_state
@Return:
        rts

QuakeSoundStopDriver:
        RW_assume a16i16
        ldx     #$0000
        ldy     #$0000
        RW_forced a8i16
        lda     #SOUND_COMMAND_STOP_ALL
        jsr     QuakeSoundCommand
        RW_forced a16i16
        rts

QuakeSoundStop:
        RW_assume a16i16
        stz     sound_pending_start_active
        lda     sound_cpu_state
        cmp     #SOUND_CPU_STATE_PLAYING
        bne     @Return
        jsr     QuakeSoundStopDriver
        lda     #SOUND_CPU_STATE_READY
        sta     sound_cpu_state
        stz     sound_schedule_finished
        inc     sound_stop_counter
@Return:
        rts

QuakeSoundService:
        RW_assume a16i16
        lda     sound_upload_active
        beq     @NoUpload
        jsr     QuakeSoundPumpUpload
        rts
@NoUpload:
        lda     sound_cpu_state
        bne     :+
        jmp     @Return
:
        cmp     #SOUND_CPU_STATE_LOADING
        beq     @LoadCache
        bra     @ReadDriver
@LoadCache:
        lda     sound_cache_slot
        cmp     #BSP_SOUND_CACHE_CHUNK_COUNT
        bcs     @CacheReady
        asl
        tax
        lda     f:QuakeBSPSoundCacheDirectory+BSP_SOUND_CPU_MIRROR_DELTA,x
        ldx     sound_cache_slot
        inc     sound_cache_slot
        ldy     #SOUND_COMMAND_UPLOAD_CACHE
        jsr     QuakeSoundBeginUploadChunk
        rts
@CacheReady:
        lda     video_tick
        cmp     #SOUND_BOOT_START_TICK
        bcc     @LoadingReturn
        lda     #SOUND_CPU_STATE_READY
        sta     sound_cpu_state
        lda     #SOUND_BOOT_START_TICK
        sta     demo_playhead_origin
        lda     demo_track_pose
        jsr     QuakeSoundStartPose
@LoadingReturn:
        rts
@ReadDriver:
        jsr     QuakeSoundReadDriverStatus
        lda     sound_driver_status
        and     #BSP_SOUND_PROTOCOL_MASK
        cmp     #BSP_SOUND_PROTOCOL_SIGNATURE
        beq     @DriverValid
        inc     sound_status_error_counter
        inc     sound_protocol_error_counter
        rts
@DriverValid:
        lda     sound_driver_status
        and     #SOUND_STATUS_ERROR
        beq     :+
        inc     sound_status_error_counter
        inc     sound_protocol_error_counter
:
        jsr     QuakeSoundCompatible
        bcs     @Compatible
        jsr     QuakeSoundStop
        rts
@Compatible:
        lda     sound_cpu_state
        cmp     #SOUND_CPU_STATE_PLAYING
        beq     @Playing
        lda     presented_demo_epoch
        cmp     demo_schedule_revision
        bne     @IdleReturn
        lda     sound_schedule_finished
        beq     @RestartReady
        lda     sound_finished_epoch
        cmp     demo_schedule_revision
        bne     @RestartReady
        lda     sound_demo_loop
        cmp     demo_loop_counter
        beq     @IdleReturn
        lda     presented_demo_pose
        bne     @IdleReturn
@RestartReady:
        lda     presented_demo_pose
        jsr     QuakeSoundStartPose
@IdleReturn:
        rts
@Playing:
        lda     sound_demo_epoch
        cmp     demo_schedule_revision
        beq     @ServicePlaying
        jsr     QuakeSoundStop
        rts
@ServicePlaying:
        lda     sound_demo_loop
        cmp     demo_loop_counter
        beq     :+
        lda     presented_demo_pose
        bne     :+
        jsr     QuakeSoundStop
        lda     presented_demo_pose
        jsr     QuakeSoundStartPose
        rts
:
        jsr     QuakeSoundDrainRequests
        lda     sound_upload_active
        bne     @Return
        lda     sound_pending_start_active
        beq     :+
        jsr     QuakeSoundContinuePendingStart
        lda     sound_upload_active
        bne     @Return
        lda     sound_pending_start_active
        bne     @Return
:
        lda     demo_schedule
        beq     @OrderedElapsed
        lda     demo_playhead_tick
        cmp     #SOUND_REALTIME_PRESENTATION_OFFSET_TICKS
        bcc     @Return
        sec
        sbc     #SOUND_REALTIME_PRESENTATION_OFFSET_TICKS
        bra     @StoreElapsed
@OrderedElapsed:
        lda     video_tick
        sec
        sbc     sound_start_tick
@StoreElapsed:
        sta     sound_elapsed_tick
@ScheduleLoop:
        lda     sound_next_command
        cmp     #BSP_SOUND_MIX_COMMAND_COUNT
        bcs     @RequestsAfterCommands
        jsr     QuakeSoundLoadMixCommand
        lda     sound_work_due
        cmp     sound_elapsed_tick
        bcc     @CommandDue
        beq     @CommandDue
        bra     @RequestsAfterCommands
@CommandDue:
        jsr     QuakeSoundApplyLiveCommand
        inc     sound_next_command
        inc     sound_mix_command_counter
        lda     sound_upload_active
        bne     @Return
        lda     sound_pending_start_active
        bne     @Return
        lda     sound_cpu_state
        cmp     #SOUND_CPU_STATE_PLAYING
        beq     @ScheduleLoop
        rts
@RequestsAfterCommands:
        jsr     QuakeSoundDrainRequests
@Return:
        rts

QuakeSoundReadDriverStatus:
        RW_assume a16i16
        RW_forced a8i16
        lda     SMPIO0
        sta     sound_driver_status
        lda     SMPIO1
        sta     sound_driver_request
        lda     SMPIO2
        sta     sound_driver_command_counter
        RW_forced a16i16
        lda     sound_driver_status
        and     #$00FF
        sta     sound_driver_status
        lda     sound_driver_request
        and     #$00FF
        sta     sound_driver_request
        lda     sound_driver_command_counter
        and     #$00FF
        sta     sound_driver_command_counter
        rts

QuakeSoundDrainRequests:
        RW_assume a16i16
        lda     #BSP_SOUND_VOICE_COUNT * BSP_SOUND_STREAM_BUFFER_COUNT
        sta     sound_request_budget
@RequestLoop:
        jsr     QuakeSoundReadDriverStatus
        lda     sound_driver_request
        cmp     #SOUND_REQUEST_NONE
        beq     @Done
        cmp     #BSP_SOUND_VOICE_COUNT * BSP_SOUND_STREAM_BUFFER_COUNT
        bcs     @BadRequest
        sta     sound_work_descriptor
        jsr     QuakeSoundRefillDescriptor
        lda     sound_upload_active
        bne     @Done
        dec     sound_request_budget
        bne     @RequestLoop
@BadRequest:
        lda     sound_driver_request
        sta     sound_last_bad_request
        inc     sound_request_error_counter
        inc     sound_protocol_error_counter
@Done:
        rts

QuakeSoundRefillDescriptor:
        RW_assume a16i16
        lda     sound_work_descriptor
        tax
        RW_forced a8i16
        lda     f:QuakeSoundDescriptorVoices,x
        RW_forced a16i16
        and     #$00FF
        sta     sound_work_voice
        asl
        tax
        lda     sound_voice_active,x
        beq     @Stale
        lda     sound_voice_next_chunk,x
        cmp     #SOUND_NO_CHUNK
        beq     @Stale
        sta     sound_work_relative
        lda     sound_voice_sample,x
        sta     sound_work_sample
        jsr     QuakeSoundLoadSampleRecord
        lda     sound_work_first_chunk
        clc
        adc     sound_work_relative
        ldx     sound_work_descriptor
        ldy     #SOUND_COMMAND_UPLOAD_STREAM
        pha
        lda     #SOUND_UPLOAD_CONTINUE_REFILL
        sta     sound_upload_continuation
        pla
        jsr     QuakeSoundBeginUploadChunk
        rts
@Stale:
        ldx     sound_work_descriptor
        ldy     #$0000
        RW_forced a8i16
        lda     #SOUND_COMMAND_CANCEL_STREAM
        jsr     QuakeSoundCommand
        RW_forced a16i16
        inc     sound_cancel_request_counter
        rts

QuakeSoundFinishRefill:
        RW_assume a16i16
        jsr     QuakeSoundAdvanceRelative
        lda     sound_work_voice
        asl
        tax
        lda     sound_work_relative
        sta     sound_voice_next_chunk,x
        rts

QuakeSoundLoadMixCommand:
        RW_assume a16i16
        lda     sound_next_command
        asl
        asl
        asl
        tax
        lda     f:QuakeBSPSoundMixSchedule+BSP_SOUND_CPU_MIRROR_DELTA,x
        sta     sound_work_due
        RW_forced a8i16
        lda     f:QuakeBSPSoundMixSchedule+BSP_SOUND_CPU_MIRROR_DELTA+2,x
        sta     sound_work_opcode
        lda     f:QuakeBSPSoundMixSchedule+BSP_SOUND_CPU_MIRROR_DELTA+3,x
        sta     sound_work_voice
        lda     f:QuakeBSPSoundMixSchedule+BSP_SOUND_CPU_MIRROR_DELTA+4,x
        sta     sound_work_sample
        lda     f:QuakeBSPSoundMixSchedule+BSP_SOUND_CPU_MIRROR_DELTA+5,x
        sta     sound_work_left
        lda     f:QuakeBSPSoundMixSchedule+BSP_SOUND_CPU_MIRROR_DELTA+6,x
        sta     sound_work_right
        RW_forced a16i16
        lda     sound_work_opcode
        and     #$00FF
        sta     sound_work_opcode
        lda     sound_work_voice
        and     #$00FF
        sta     sound_work_voice
        lda     sound_work_sample
        and     #$00FF
        sta     sound_work_sample
        lda     sound_work_left
        and     #$00FF
        sta     sound_work_left
        lda     sound_work_right
        and     #$00FF
        sta     sound_work_right
        rts

QuakeSoundApplyShadowCommand:
        RW_assume a16i16
        lda     sound_work_opcode
        cmp     #SOUND_MIX_START
        beq     QuakeSoundShadowStart
        cmp     #SOUND_MIX_STOP
        beq     QuakeSoundShadowStop
        cmp     #SOUND_MIX_VOLUME
        beq     QuakeSoundShadowVolume
        cmp     #SOUND_MIX_COMPLETE
        bne     @Return
        jsr     QuakeSoundClearVoiceState
@Return:
        rts

QuakeSoundShadowStart:
        RW_assume a16i16
        lda     sound_work_voice
        asl
        tax
        lda     #$0001
        sta     sound_voice_active,x
        lda     sound_work_sample
        sta     sound_voice_sample,x
        lda     sound_work_left
        sta     sound_voice_left,x
        lda     sound_work_right
        sta     sound_voice_right,x
        lda     sound_work_due
        sta     sound_voice_start_tick,x
        rts

QuakeSoundShadowStop:
        RW_assume a16i16
        lda     sound_work_voice
        asl
        tax
        stz     sound_voice_active,x
        rts

QuakeSoundShadowVolume:
        RW_assume a16i16
        lda     sound_work_voice
        asl
        tax
        lda     sound_work_left
        sta     sound_voice_left,x
        lda     sound_work_right
        sta     sound_voice_right,x
        rts

QuakeSoundApplyLiveCommand:
        RW_assume a16i16
        lda     sound_work_opcode
        cmp     #SOUND_MIX_START
        beq     @Start
        cmp     #SOUND_MIX_STOP
        beq     @Stop
        cmp     #SOUND_MIX_VOLUME
        beq     @Volume
        cmp     #SOUND_MIX_COMPLETE
        beq     @Complete
        inc     sound_schedule_error_counter
        inc     sound_protocol_error_counter
        rts
@Start:
        ; A voice steal must release its old stream ring before new chunks are
        ; uploaded; free voices avoid this command entirely.
        lda     sound_work_voice
        asl
        tax
        lda     sound_voice_active,x
        beq     @StartReady
        ldx     #$0000
        ldy     #$0000
        RW_forced a8i16
        lda     sound_work_voice
        ora     #SOUND_COMMAND_STOP_BASE
        jsr     QuakeSoundCommand
        RW_forced a16i16
@StartReady:
        jsr     QuakeSoundShadowStart
        lda     sound_work_due
        sta     sound_work_start_tick
        jsr     QuakeSoundStartVoice
        rts
@Stop:
        jsr     QuakeSoundShadowStop
        ldx     #$0000
        ldy     #$0000
        RW_forced a8i16
        lda     sound_work_voice
        ora     #SOUND_COMMAND_STOP_BASE
        jsr     QuakeSoundCommand
        RW_forced a16i16
        inc     sound_stop_counter
        rts
@Volume:
        jsr     QuakeSoundShadowVolume
        ldx     sound_work_left
        ldy     sound_work_right
        RW_forced a8i16
        lda     sound_work_voice
        ora     #SOUND_COMMAND_VOLUME_BASE
        jsr     QuakeSoundCommand
        RW_forced a16i16
        rts
@Complete:
        jsr     QuakeSoundStopDriver
        jsr     QuakeSoundClearVoiceState
        lda     #SOUND_CPU_STATE_READY
        sta     sound_cpu_state
        lda     #$0001
        sta     sound_schedule_finished
        lda     sound_demo_epoch
        sta     sound_finished_epoch
        inc     sound_complete_counter
        rts

; Start sound_work_sample on sound_work_voice. Late commands and seeks skip to
; the current 128 ms source chunk; all steady-state mixing remains in S-DSP.
QuakeSoundStartVoice:
        RW_assume a16i16
        jsr     QuakeSoundLoadSampleRecord
        jsr     QuakeSoundComputeStartRelative
        bcs     :+
        jmp     QuakeSoundStartAlreadyEnded
:
        lda     sound_work_voice
        asl
        tax
        lda     sound_work_relative
        sta     sound_voice_current_chunk,x
        lda     sound_work_sample
        sta     sound_voice_sample,x
        lda     sound_work_left
        sta     sound_voice_left,x
        lda     sound_work_right
        sta     sound_voice_right,x
        lda     sound_work_start_tick
        sta     sound_voice_start_tick,x
        lda     #$0001
        sta     sound_voice_active,x
        lda     sound_work_cache_first
        cmp     #$00FF
        beq     @Stream
        lda     #SOUND_NO_CHUNK
        sta     sound_voice_next_chunk,x
        bra     QuakeSoundConfigureVoice
@Stream:
        lda     sound_work_voice
        sta     sound_pending_start_voice
        lda     sound_work_relative
        sta     sound_pending_start_relative
        stz     sound_pending_start_slot
        lda     #$0001
        sta     sound_pending_start_active
        jsr     QuakeSoundContinuePendingStart
        sec
        rts
QuakeSoundConfigureVoice:
        lda     sound_work_voice
        asl
        tax
        lda     sound_voice_current_chunk,x
        tay
        ldx     sound_work_sample
        RW_forced a8i16
        lda     sound_work_voice
        ora     #SOUND_COMMAND_SET_BASE
        jsr     QuakeSoundCommand
        ldx     sound_work_left
        ldy     sound_work_right
        lda     sound_work_voice
        ora     #SOUND_COMMAND_START_BASE
        jsr     QuakeSoundCommand
        RW_forced a16i16
        inc     sound_start_counter
        sec
        rts
QuakeSoundStartAlreadyEnded:
        inc     sound_late_skip_counter
        lda     sound_work_voice
        asl
        tax
        stz     sound_voice_active,x
        clc
        rts

; Upload one ring chunk for the pending voice. Existing refill requests run
; first, so starting a new sound never consumes an already-playing deadline.
QuakeSoundContinuePendingStart:
        RW_assume a16i16
        lda     sound_pending_start_voice
        sta     sound_work_voice
        asl
        tax
        lda     sound_voice_sample,x
        sta     sound_work_sample
        jsr     QuakeSoundLoadSampleRecord
        lda     sound_pending_start_relative
        cmp     #SOUND_NO_CHUNK
        beq     QuakeSoundFinishPendingStart
        sta     sound_work_relative
        lda     sound_work_first_chunk
        clc
        adc     sound_work_relative
        sta     sound_work_global_chunk
        lda     sound_work_voice
        tax
        RW_forced a8i16
        lda     f:QuakeSoundVoiceFirstDescriptors,x
        RW_forced a16i16
        and     #$00FF
        clc
        adc     sound_pending_start_slot
        tax
        lda     sound_work_global_chunk
        ldy     #SOUND_COMMAND_UPLOAD_STREAM
        pha
        lda     #SOUND_UPLOAD_CONTINUE_START
        sta     sound_upload_continuation
        pla
        jsr     QuakeSoundBeginUploadChunk
        rts

QuakeSoundFinishStartUpload:
        RW_assume a16i16
        lda     sound_pending_start_voice
        sta     sound_work_voice
        asl
        tax
        lda     sound_voice_sample,x
        sta     sound_work_sample
        jsr     QuakeSoundLoadSampleRecord
        lda     sound_pending_start_relative
        sta     sound_work_relative
        jsr     QuakeSoundAdvanceRelative
        lda     sound_work_relative
        sta     sound_pending_start_relative
        inc     sound_pending_start_slot
        lda     sound_pending_start_relative
        cmp     #SOUND_NO_CHUNK
        beq     QuakeSoundFinishPendingStart
        lda     sound_pending_start_slot
        cmp     #BSP_SOUND_STREAM_BUFFER_COUNT
        bcs     QuakeSoundFinishPendingStart
        rts

QuakeSoundFinishPendingStart:
        RW_assume a16i16
        lda     sound_pending_start_voice
        sta     sound_work_voice
        asl
        tax
        lda     sound_pending_start_relative
        sta     sound_voice_next_chunk,x
        lda     sound_voice_sample,x
        sta     sound_work_sample
        lda     sound_voice_left,x
        sta     sound_work_left
        lda     sound_voice_right,x
        sta     sound_work_right
        jsr     QuakeSoundConfigureVoice
        stz     sound_pending_start_active
@Return:
        rts

QuakeSoundLoadSampleRecord:
        RW_assume a16i16
        lda     sound_work_sample
        asl
        asl
        asl
        tax
        lda     f:QuakeBSPSoundSampleDirectory+BSP_SOUND_CPU_MIRROR_DELTA,x
        sta     sound_work_first_chunk
        lda     f:QuakeBSPSoundSampleDirectory+BSP_SOUND_CPU_MIRROR_DELTA+2,x
        sta     sound_work_chunk_count
        RW_forced a8i16
        lda     f:QuakeBSPSoundSampleDirectory+BSP_SOUND_CPU_MIRROR_DELTA+4,x
        sta     sound_work_cache_first
        lda     f:QuakeBSPSoundSampleDirectory+BSP_SOUND_CPU_MIRROR_DELTA+5,x
        sta     sound_work_flags
        RW_forced a16i16
        lda     sound_work_cache_first
        and     #$00FF
        sta     sound_work_cache_first
        lda     sound_work_flags
        and     #$00FF
        sta     sound_work_flags
        lda     f:QuakeBSPSoundSampleDirectory+BSP_SOUND_CPU_MIRROR_DELTA+6,x
        sta     sound_work_loop_chunk
        rts

; floor((elapsed 60 Hz ticks) * 125 / 960) gives the current 1024-sample
; chunk at 8 kHz without a multiply/divide helper. This runs only on starts.
QuakeSoundComputeStartRelative:
        RW_assume a16i16
        lda     sound_elapsed_tick
        sec
        sbc     sound_work_start_tick
        sta     sound_work_delta
        stz     sound_work_fraction
        stz     sound_work_relative
@Tick:
        lda     sound_work_delta
        beq     @Normalize
        dec     sound_work_delta
        lda     sound_work_fraction
        clc
        adc     #SOUND_CHUNK_TICK_NUMERATOR
        cmp     #SOUND_CHUNK_TICK_DENOMINATOR
        bcc     @StoreFraction
        sec
        sbc     #SOUND_CHUNK_TICK_DENOMINATOR
        inc     sound_work_relative
@StoreFraction:
        sta     sound_work_fraction
        bra     @Tick
@Normalize:
        lda     sound_work_relative
        cmp     sound_work_chunk_count
        bcc     @Playable
        lda     sound_work_flags
        and     #SOUND_SAMPLE_FLAG_LOOP
        beq     @Ended
        lda     sound_work_chunk_count
        sec
        sbc     sound_work_loop_chunk
        sta     sound_work_loop_span
@Wrap:
        lda     sound_work_relative
        cmp     sound_work_chunk_count
        bcc     @Playable
        sec
        sbc     sound_work_loop_span
        sta     sound_work_relative
        bra     @Wrap
@Playable:
        sec
        rts
@Ended:
        clc
        rts

; Advance sound_work_relative once, wrapping a loop or returning $FFFF for a
; terminal one-shot. The current sample record must already be loaded.
QuakeSoundAdvanceRelative:
        RW_assume a16i16
        inc     sound_work_relative
        lda     sound_work_relative
        cmp     sound_work_chunk_count
        bcc     @Return
        lda     sound_work_flags
        and     #SOUND_SAMPLE_FLAG_LOOP
        beq     @Terminal
        lda     sound_work_loop_chunk
        sta     sound_work_relative
        rts
@Terminal:
        lda     #SOUND_NO_CHUNK
        sta     sound_work_relative
@Return:
        rts

QuakeSoundClearVoiceState:
        RW_assume a16i16
        stz     sound_pending_start_active
        ldx     #$0000
@Clear:
        stz     sound_voice_active,x
        stz     sound_voice_sample,x
        stz     sound_voice_left,x
        stz     sound_voice_right,x
        stz     sound_voice_start_tick,x
        stz     sound_voice_current_chunk,x
        lda     #SOUND_NO_CHUNK
        sta     sound_voice_next_chunk,x
        inx
        inx
        cpx     #BSP_SOUND_VOICE_COUNT * 2
        bcc     @Clear
        rts

; A16 = global chunk identity, X16 = upload descriptor/cache slot,
; Y16 = upload command. Boot cache loads use the blocking wrapper; live work
; advances in bounded slices outside VBlank.
QuakeSoundUploadChunk:
        RW_assume a16i16
        pha
        lda     #SOUND_UPLOAD_CONTINUE_NONE
        sta     sound_upload_continuation
        pla
        jsr     QuakeSoundBeginUploadChunk
@Wait:
        lda     sound_upload_active
        beq     @Done
        jsr     QuakeSoundPumpUpload
        bra     @Wait
@Done:
        rts

QuakeSoundBeginUploadChunk:
        RW_assume a16i16
        sta     sound_work_global_chunk
        stx     sound_upload_target
        sty     sound_upload_command
        asl
        asl
        tax
        lda     f:QuakeBSPSoundChunkDirectory+BSP_SOUND_CPU_MIRROR_DELTA,x
        sta     z:sound_source_pointer
        RW_forced a8i16
        lda     f:QuakeBSPSoundChunkDirectory+BSP_SOUND_CPU_MIRROR_DELTA+2,x
        clc
        adc     #BSP_SOUND_CPU_MIRROR_BANK_DELTA
        sta     z:sound_source_pointer+2
        ldx     sound_upload_target
        ldy     #$0000
        lda     sound_upload_command
        jsr     QuakeSoundCommand
        RW_forced a16i16
        stz     sound_upload_offset
        lda     #$0001
        sta     sound_upload_active
        jmp     QuakeSoundPumpUpload

QuakeSoundPumpUpload:
        RW_assume a16i16
        ldy     sound_upload_offset
        lda     demo_schedule
        beq     @OrderedBatch
        ldx     #SOUND_UPLOAD_BATCH_PACKETS_REALTIME
        bra     @BatchReady
@OrderedBatch:
        ldx     #SOUND_UPLOAD_BATCH_PACKETS_ORDERED
@BatchReady:
        RW_forced a8i16
@Packet:
        lda     [sound_source_pointer],y
        sta     SMPIO0
        iny
        lda     [sound_source_pointer],y
        sta     SMPIO1
        iny
        lda     [sound_source_pointer],y
        sta     SMPIO2
        iny
        inc     z:sound_command_token
        lda     z:sound_command_token
        sta     SMPIO3
@WaitPacket:
        cmp     SMPIO3
        bne     @WaitPacket
        cpy     #BSP_SOUND_STREAM_CHUNK_BYTES
        beq     @Complete
        dex
        bne     @Packet
        RW_forced a16i16
        sty     sound_upload_offset
        rts
@Complete:
        ; The SPC publishes ready/request state before acknowledging the final
        ; packet, so completion is also the status-ordering edge.
        RW_forced a16i16
        sty     sound_upload_offset
        stz     sound_upload_active
        inc     sound_transfer_counter
        lda     sound_upload_command
        cmp     #SOUND_COMMAND_UPLOAD_CACHE
        bne     @Stream
        inc     sound_cache_transfer_counter
        bra     @Continue
@Stream:
        inc     sound_stream_transfer_counter
@Continue:
        lda     sound_upload_continuation
        stz     sound_upload_continuation
        cmp     #SOUND_UPLOAD_CONTINUE_REFILL
        bne     :+
        jmp     QuakeSoundFinishRefill
:
        cmp     #SOUND_UPLOAD_CONTINUE_START
        bne     :+
        jmp     QuakeSoundFinishStartUpload
:
        rts

; A8 = command, X16 low byte = argument, Y16 low byte = second argument.
; Port 3 is a monotonic strobe/ack and remains safe across NMI.
QuakeSoundCommand:
        RW_assume a8i16
        sta     SMPIO0
        txa
        sta     SMPIO1
        tya
        sta     SMPIO2
        inc     z:sound_command_token
        lda     z:sound_command_token
        sta     SMPIO3
@Wait:
        cmp     SMPIO3
        bne     @Wait
        rts

; Run bounded streaming work while a GSU job is active. This preserves the
; existing join contract: A, Y, DB, and widths survive; X/N/Z are clobbered.
QuakeSoundJoinFX3:
        phy
@Service:
        ; Finish cache packets during a GSU job, but publish READY/start only
        ; from the ordinary pre-render service boundary.
        ldx     sound_cpu_state
        cpx     #SOUND_CPU_STATE_LOADING
        bne     @RunService
        ldx     sound_cache_slot
        cpx     #BSP_SOUND_CACHE_CHUNK_COUNT
        bcc     @RunService
        ldx     video_tick
        cpx     #SOUND_BOOT_START_TICK
        bcs     @PollSetup
@RunService:
        jsr     QuakeSoundServiceMain
@PollSetup:
        ldy     #SOUND_JOIN_POLL_COUNT
@Wait:
        ldx     FX3_R15
        beq     @Done
        dey
        bne     @Wait
        bra     @Service
@Done:
        ply
        rts

; A reused/paced frame has no GSU join to pump the stream. Use that idle
; CPU time until the next video tick, retaining bounded, interruptible slices.
QuakeSoundWaitFrame:
        php
        RW_forced a16i16
        pha
        lda     sound_cpu_state
        cmp     #SOUND_CPU_STATE_PLAYING
        beq     @Pump
        cmp     #SOUND_CPU_STATE_LOADING
        beq     @Pump
        wai
        bra     @Done
@Pump:
        lda     video_tick
@Wait:
        jsr     QuakeSoundServiceMain
        cmp     video_tick
        beq     @Wait
@Done:
        pla
        plp
        rts

QuakeSoundServiceMain:
        php
        RW_forced a16i16
        pha
        phx
        phy
        phb
        phk
        plb
        lda     sound_service_busy
        bne     @Done
        inc     sound_service_busy
        jsr     QuakeSoundService
        stz     sound_service_busy
@Done:
QuakeSoundServiceIdle:
        plb
        ply
        plx
        pla
        plp
        rts

QuakeSoundDescriptorVoices:
        .repeat BSP_SOUND_VOICE_COUNT, Voice
        .repeat BSP_SOUND_STREAM_BUFFER_COUNT
        .byte   Voice
        .endrepeat
        .endrepeat
QuakeSoundVoiceFirstDescriptors:
        .repeat BSP_SOUND_VOICE_COUNT, Voice
        .byte   Voice * BSP_SOUND_STREAM_BUFFER_COUNT
        .endrepeat

.segment "ZEROPAGE"
sound_command_token: .res 1
sound_source_pointer: .res 3

.segment "LORAM"
sound_cpu_state: .res 2
sound_service_busy: .res 2
sound_demo_epoch: .res 2
sound_demo_loop: .res 2
sound_start_tick: .res 2
sound_elapsed_tick: .res 2
sound_target_tick: .res 2
sound_next_command: .res 2
sound_mix_command_counter: .res 2
sound_driver_status: .res 2
sound_driver_request: .res 2
sound_driver_command_counter: .res 2
sound_transfer_counter: .res 2
sound_cache_transfer_counter: .res 2
sound_stream_transfer_counter: .res 2
sound_start_counter: .res 2
sound_late_skip_counter: .res 2
sound_stop_counter: .res 2
sound_complete_counter: .res 2
sound_protocol_error_counter: .res 2
sound_status_error_counter: .res 2
sound_request_error_counter: .res 2
sound_stale_request_counter: .res 2
sound_schedule_error_counter: .res 2
sound_cancel_request_counter: .res 2
sound_last_bad_request: .res 2
sound_schedule_finished: .res 2
sound_finished_epoch: .res 2
sound_cache_slot: .res 2
sound_request_budget: .res 2
sound_work_pose: .res 2
sound_work_due: .res 2
sound_work_opcode: .res 2
sound_work_voice: .res 2
sound_work_sample: .res 2
sound_work_left: .res 2
sound_work_right: .res 2
sound_work_start_tick: .res 2
sound_work_descriptor: .res 2
sound_work_global_chunk: .res 2
sound_work_first_chunk: .res 2
sound_work_chunk_count: .res 2
sound_work_cache_first: .res 2
sound_work_flags: .res 2
sound_work_loop_chunk: .res 2
sound_work_relative: .res 2
sound_work_delta: .res 2
sound_work_fraction: .res 2
sound_work_loop_span: .res 2
sound_upload_target: .res 2
sound_upload_command: .res 2
sound_upload_active: .res 2
sound_upload_continuation: .res 2
sound_upload_offset: .res 2
sound_pending_start_active: .res 2
sound_pending_start_voice: .res 2
sound_pending_start_relative: .res 2
sound_pending_start_slot: .res 2
sound_voice_active: .res BSP_SOUND_VOICE_COUNT * 2
sound_voice_sample: .res BSP_SOUND_VOICE_COUNT * 2
sound_voice_left: .res BSP_SOUND_VOICE_COUNT * 2
sound_voice_right: .res BSP_SOUND_VOICE_COUNT * 2
sound_voice_start_tick: .res BSP_SOUND_VOICE_COUNT * 2
sound_voice_current_chunk: .res BSP_SOUND_VOICE_COUNT * 2
sound_voice_next_chunk: .res BSP_SOUND_VOICE_COUNT * 2

.endif

.include "Data/QuakeBSPSoundtrackAssets.s"
