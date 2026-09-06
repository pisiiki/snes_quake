; Preserve the ordinary FX3 join contract while servicing enabled sound.
SOUND_CPU_STATE_DISABLED = 0
SOUND_CPU_STATE_READY    = 1
SOUND_CPU_STATE_PLAYING  = 2
SOUND_CPU_STATE_LOADING  = 3

.macro BSP_SOUND_HOLD_DEMO Target
.if BSP_SOUND_ENABLED
        .local Hold, Continue
        lda     demo_mode
        beq     Continue
        lda     f:GSU_BOOT_PARAMETERS+10
        and     #BOOT_PARAMETERS_PRESENT_ORDERED_SOURCE_POSE
        bne     Continue
        lda     boot_ordered_source_pose
        bne     Continue
        lda     sound_cpu_state
        beq     Hold
        ; Preserve the original one-compare/one-taken-branch ready-state path.
        ; Fly and incompatible playback use it, and their input cadence must
        ; not pay for the ordered-tail checks below.
        cmp     #SOUND_CPU_STATE_READY
        beq     Continue
        cmp     #SOUND_CPU_STATE_LOADING
        beq     Hold
        ; The ordered renderer can now reach its wrap before the deterministic
        ; mixer tail completes. Keep staging the final pose until the natural
        ; completion command makes the mixer ready; only then publish pose 0
        ; and let the existing loop restart synchronize both streams.
        cmp     #SOUND_CPU_STATE_PLAYING
        bne     Continue
        lda     demo_schedule
        bne     Continue
        lda     demo_loop_counter
        cmp     sound_demo_loop
        beq     Continue
Hold:
        jmp     Target
Continue:
.endif
.endmacro

.macro BSP_SOUND_FX3_JOB_JOIN
.if BSP_SOUND_ENABLED
        .local Active, Done
        ; Compatible playback enters the mixer-aware join. Other modes retain
        ; the original three-instruction FX3 polling loop.
        ldx     sound_cpu_state
        bne     Active
        FX3_JOB_JOIN
        bra     Done
Active:
        jsr     QuakeSoundJoinFX3
Done:
.else
        FX3_JOB_JOIN
.endif
.endmacro

.macro BSP_SOUND_WAIT_FRAME
.if BSP_SOUND_ENABLED
        jsr     QuakeSoundWaitFrame
.else
        wai
.endif
.endmacro
