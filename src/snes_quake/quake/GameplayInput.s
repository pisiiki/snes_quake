; VBlank makes one fixed step ready for live play. Tape replay admits every
; ordered sample, sharing a record across consecutive identical controls.
QC_INPUT_RECORD_SIZE = 8
.if .defined(PLAYABLE_WEAPON_OBJ) && .defined(QC_KNIGHT_ROSTER) && .defined(QC_E1M2_GROUP_COUNT)
; The completion tape needs more ordered samples while the trap fight
; occupies the simulation. Bank $7E has room beside the two frame slots.
QC_INPUT_QUEUE_SIZE = 1024 * QC_INPUT_RECORD_SIZE
.define QC_INPUT_QUEUE_WORD(offset) f:qc_input_queue+offset,x
.pushseg
.segment "HIRAM"
qc_input_queue:     .res QC_INPUT_QUEUE_SIZE
.assert ^qc_input_queue = $7E && ^(*-1) = $7E, lderror, "Ordered input queue escapes bank 7E"
.popseg
.else
QC_INPUT_QUEUE_SIZE = 256 * QC_INPUT_RECORD_SIZE
.define QC_INPUT_QUEUE_WORD(offset) a:qc_input_queue+offset,x
.endif
.if .defined(PLAYABLE_MAP_ID) && .defined(QC_INPUT_REPLAY_CELL_BYTES)
QC_INPUT_SPARSE_LOOK = 1
.endif
.ifdef QC_INPUT_SPARSE_LOOK
; A record begins with a tick and buttons. An optional second cell holds
; the original signed yaw and pitch. Each cell wraps independently.
QC_INPUT_CELL_BYTES = QC_INPUT_REPLAY_CELL_BYTES
QC_INPUT_LOOK_CELL = $0008
QC_INPUT_QUEUE_MASK = QC_INPUT_QUEUE_SIZE - QC_INPUT_CELL_BYTES
.else
QC_INPUT_QUEUE_MASK = QC_INPUT_QUEUE_SIZE - QC_INPUT_RECORD_SIZE
.endif
QC_INPUT_MENU = 1
QC_INPUT_RELEASE = 2
QC_LIVE_LOOK_STEP = CAMERA_ANGLE_LEGACY_STEP * QC_INPUT_VBLANKS / 2
QC_START_MENU_VBLANKS = 24

.pushseg
.segment "LORAM"
.ifndef qc_input_queue
qc_input_queue:     .res QC_INPUT_QUEUE_SIZE
.endif
qc_input_head:      .res 2
qc_input_tail:      .res 2
qc_input_tick:      .res 2
qc_input_waits:     .res 2
qc_input_divider:   .res 2
qc_input_buttons:   .res 2
qc_input_yaw:       .res 2
qc_input_pitch:     .res 2
qc_input_menu:      .res 2
qc_input_release:   .res 2
qc_respawn_release: .res 2
qc_sample_buttons:  .res 2
qc_sample_yaw:      .res 2
qc_sample_pitch:    .res 2
qc_sample_pending:  .res 2
qc_sample_actions:  .res 2
qc_previous_buttons: .res 2
qc_previous_yaw:    .res 2
qc_previous_pitch:  .res 2
; BootVector clears this on map entry. The tape runner opts in at MainLoop.
qc_input_replay:    .res 2
qc_sample_weapon:   .res 2
qc_start_hold:      .res 2

.segment "CODE"
.macro GAMEPLAY_CYCLE_CURRENT_WEAPON
.if .defined(QC_NAIL_COUNT) || .defined(QC_CAMPAIGN_ITEMS)
        jsl     NailCycleWeapon
.else
        lda     f:axe_selected
        eor     #1                     ; Both directions wrap in a two-weapon roster.
        sta     f:axe_selected
.endif
        lda     #0
        sta     f:axe_pending
        lda     #BSP_WEAPON_LIVE_TICKS
        sta     f:shot_clock_wram
        lda     f:shotgun_shots
        sta     f:shotgun_view_shot
.endmacro

GameplayInputReset:
        RW_assume a16i16
        phb
        phk
        plb
        stz     qc_input_head
        stz     qc_input_tail
        stz     qc_input_tick
        stz     qc_input_waits
        stz     qc_input_divider
        stz     qc_input_buttons
        stz     qc_input_yaw
        stz     qc_input_pitch
        stz     qc_input_menu
        stz     qc_input_release
        stz     qc_respawn_release
.ifdef PLAYABLE_E1M1_PREFETCH_GAMEPLAY
        stz     deferred_live_input_tick
.endif
        stz     qc_sample_yaw
        stz     qc_sample_pitch
        stz     qc_sample_pending
        stz     qc_sample_actions
        stz     qc_sample_weapon
        stz     qc_start_hold
        stz     qc_previous_buttons
        stz     qc_previous_yaw
        stz     qc_previous_pitch
        plb
        rtl

GameplayLatchInput:
        RW_assume a16i16
        lda     qc_input_replay
.ifdef PLAYABLE_RECORDED_TAPE
        ; A feeder can hold the input timeline while simulation drains.
        bpl     :+
        rts
:
.endif
        bne     @Replay
        jmp     GameplayLatchLiveInput
@Replay:
        lda     qc_sample_pending
.ifdef PLAYABLE_RECORDED_TAPE
        beq     :+
        jmp     @Append
:
.else
        bne     @Append
.endif
        lda     runtime_menu_open
.ifdef PLAYABLE_WEAPON_OBJ
        ora     weapon_obj_menu_pending
.endif
        ora     runtime_menu_release_gate
.ifdef PLAYABLE_RECORDED_TAPE
        beq     @ReplayActions
        lda     #JOY_SELECT
        trb     qc_sample_actions
        bra     @ReplayClock
@ReplayActions:
.else
        bne     @ReplayClock
.endif
        lda     camera_input_buttons
        and     #(JOY_L | JOY_R)
        ora     qc_sample_actions
        sta     qc_sample_actions
.ifdef PLAYABLE_RECORDED_TAPE
        lda     qc_input_replay
        cmp     #QC_INPUT_RECORDED_TAPE
        bne     @ReplayClock
        ; The C++ tape records one boolean per video sample. XOR keeps
        ; multiple recorded cycle requests within one input step exact.
        lda     camera_input_buttons
        and     #JOY_SELECT
        eor     qc_sample_actions
        sta     qc_sample_actions
.endif
@ReplayClock:
        inc     qc_input_divider
        lda     qc_input_divider
        cmp     #QC_INPUT_VBLANKS
        bcs     :+
        rts
:
        lda     runtime_menu_open
.ifdef PLAYABLE_WEAPON_OBJ
        ora     weapon_obj_menu_pending
.endif
        beq     @Closed
        stz     qc_sample_yaw
        stz     qc_sample_pitch
        lda     #QC_INPUT_MENU
        bra     @ButtonsReady
@Closed:
        lda     camera_input_buttons
        and     #$FFF0
.ifdef PLAYABLE_RECORDED_TAPE
        ldx     qc_input_replay
        cpx     #QC_INPUT_RECORDED_TAPE
        bne     :+
        and     #$FFFF-JOY_SELECT
:
.endif
        ldx     runtime_menu_release_gate
        bne     :+
        ora     qc_sample_actions
        bra     @ButtonsReady
:
        stz     qc_sample_yaw
        stz     qc_sample_pitch
        ora     #QC_INPUT_RELEASE
@ButtonsReady:
.ifdef PLAYABLE_MAP_ID
        ora     runtime_walk
.endif
        sta     qc_sample_buttons
        cmp     qc_previous_buttons
        bne     @Append
        lda     qc_sample_yaw
        cmp     qc_previous_yaw
        bne     @Append
        lda     qc_sample_pitch
        cmp     qc_previous_pitch
        beq     @Admit
@Append:
        ldx     qc_input_tail
.ifdef QC_INPUT_SPARSE_LOOK
        jsr     GameplayNextInputCell
        cpx     qc_input_head
        beq     @Full
        lda     qc_sample_yaw
        ora     qc_sample_pitch
        beq     @ShortRecord
        ; X is free. Leave the tail unpublished until both cells fit.
        lda     qc_sample_yaw
        sta     QC_INPUT_QUEUE_WORD(0)
        lda     qc_sample_pitch
        sta     QC_INPUT_QUEUE_WORD(2)
        jsr     GameplayNextInputCell
        cpx     qc_input_head
        beq     @Full
        lda     qc_sample_buttons
        ora     #QC_INPUT_LOOK_CELL
        bra     @WriteHeader
@ShortRecord:
        lda     qc_sample_buttons
@WriteHeader:
        txy
        ldx     qc_input_tail
        sta     QC_INPUT_QUEUE_WORD(2)
        bra     @WriteTick
.else
        txa
        clc
        adc     #QC_INPUT_RECORD_SIZE
        and     #QC_INPUT_QUEUE_MASK
        cmp     qc_input_head
        bne     @HaveRoom
.endif
@Full:
        ; Pin this sample and retry next VBlank. Neither the gameplay clock
        ; nor the cursor advances while the consumer is behind a full FIFO.
        lda     #1
        sta     qc_sample_pending
        inc     qc_input_waits
        rts
.ifndef QC_INPUT_SPARSE_LOOK
@HaveRoom:
        tay
.endif
@WriteTick:
        lda     qc_input_tick
        inc
        sta     QC_INPUT_QUEUE_WORD(0)
        lda     qc_sample_buttons
.ifdef PLAYABLE_RECORDED_TAPE
  .ifndef QC_INPUT_SPARSE_LOOK
        sta     QC_INPUT_QUEUE_WORD(2)
  .endif
        pha
        lda     qc_input_replay
        cmp     #QC_INPUT_RECORDED_TAPE
        bne     :+
        pla
        and     #$FFFF-JOY_SELECT
        bra     :++
:       pla
:
        sta     qc_previous_buttons
.else
        sta     qc_previous_buttons
  .ifndef QC_INPUT_SPARSE_LOOK
        sta     QC_INPUT_QUEUE_WORD(2)
  .endif
.endif
        lda     qc_sample_yaw
        sta     qc_previous_yaw
.ifndef QC_INPUT_SPARSE_LOOK
        sta     QC_INPUT_QUEUE_WORD(4)
.endif
        lda     qc_sample_pitch
        sta     qc_previous_pitch
.ifndef QC_INPUT_SPARSE_LOOK
        sta     QC_INPUT_QUEUE_WORD(6)
.endif
        sty     qc_input_tail
@Admit:
        inc     qc_input_tick
        stz     qc_input_divider
        stz     qc_sample_pending
        stz     qc_sample_actions
        stz     qc_sample_yaw
        stz     qc_sample_pitch
        rts

.ifdef QC_INPUT_SPARSE_LOOK
GameplayNextInputCell:
        txa
        clc
        adc     #QC_INPUT_CELL_BYTES
        and     #QC_INPUT_QUEUE_MASK
        tax
        rts
.endif

GameplayLatchLiveInput:
        RW_assume a16i16
        lda     runtime_menu_open
.ifdef PLAYABLE_WEAPON_OBJ
        ora     weapon_obj_menu_pending
.endif
        ora     runtime_menu_release_gate
        tay
        beq     @CheckReady
        stz     qc_sample_actions
        stz     qc_sample_yaw
        stz     qc_sample_pitch
        stz     fly_mouse_dx
        stz     fly_mouse_dy
        stz     qc_sample_weapon
@CheckReady:
        lda     qc_input_tick
        cmp     f:quakec_last_tick
.ifdef PLAYABLE_E1M1_PREFETCH_GAMEPLAY
        beq     :+
        ; A claimed sample leaves room for the next live input.
        cmp     deferred_live_input_tick
.endif
        bne     @ExpireActions
.ifdef PLAYABLE_E1M1_PREFETCH_GAMEPLAY
:
.endif
        cpy     #0
        bne     @Clock
        lda     camera_input_buttons
        and     #(JOY_L | JOY_R)
        ora     qc_sample_actions
        sta     qc_sample_actions
@Clock:
        inc     qc_input_divider
        lda     qc_input_divider
        cmp     #QC_INPUT_VBLANKS
        bcc     @Done
        inc     qc_input_tick
        stz     qc_input_divider
@Done:
        rts
@ExpireActions:
        ; The ready step stays ready. Use current holds after its tap expires.
        stz     qc_sample_actions
        rts

GameplayConsumeInput:
        RW_assume a16i16
        phb
        phk
        plb
        lda     qc_input_replay
        bne     @Replay
.ifdef PLAYABLE_E1M1_PREFETCH_GAMEPLAY
        jsl     GameplayConsumeLiveInput
.else
        jsr     GameplayReadLiveInput
.endif
        bra     @ApplyLook
@Replay:
.ifdef PLAYABLE_RECORDED_TAPE
        stz     qc_sample_weapon
.endif
        ldx     qc_input_head
        cpx     qc_input_tail
        beq     @ApplyLook
        lda     QC_INPUT_QUEUE_WORD(0)
        cmp     f:quakec_last_tick
        bne     @ApplyLook
        lda     QC_INPUT_QUEUE_WORD(2)
.ifdef QC_INPUT_SPARSE_LOOK
        tay
        and     #$FFFF-QC_INPUT_LOOK_CELL
.endif
        sta     qc_input_buttons
.ifdef PLAYABLE_RECORDED_TAPE
        lda     qc_input_replay
        bit     #QC_INPUT_RECORDED_TAPE
        beq     :+
        lda     #JOY_SELECT
        trb     qc_input_buttons
        beq     :+
        inc     qc_sample_weapon
:       lda     qc_input_buttons
.endif
        and     #QC_INPUT_MENU
        sta     qc_input_menu
.ifdef QC_INPUT_SPARSE_LOOK
        jsr     GameplayNextInputCell
        tya
        bit     #QC_INPUT_LOOK_CELL
        beq     @ClearLook
        lda     QC_INPUT_QUEUE_WORD(0)
        sta     qc_input_yaw
        lda     QC_INPUT_QUEUE_WORD(2)
        sta     qc_input_pitch
        jsr     GameplayNextInputCell
        bra     @Consume
@ClearLook:
        stz     qc_input_yaw
        stz     qc_input_pitch
@Consume:
        stx     qc_input_head
.else
        lda     QC_INPUT_QUEUE_WORD(4)
        sta     qc_input_yaw
        lda     QC_INPUT_QUEUE_WORD(6)
        sta     qc_input_pitch
        txa
        clc
        adc     #QC_INPUT_RECORD_SIZE
        and     #QC_INPUT_QUEUE_MASK
        sta     qc_input_head
.endif
@ApplyLook:
        lda     qc_input_buttons
        and     #QC_INPUT_RELEASE
        sta     qc_input_release
        lda     qc_respawn_release
        beq     @LookReady
        lda     qc_input_buttons
        and     #$FFF0
        beq     @Released
        lda     #QC_INPUT_RELEASE
        sta     qc_input_release
        bra     @Done
@Released:
        stz     qc_respawn_release
@LookReady:
.ifdef QC_INTERMISSION_COUNT
        lda     f:intermission_phase
        cmp     #2
        beq     @Done
.endif
        lda     qc_input_yaw
        ora     qc_input_pitch
        beq     @Done
        RW      a8
        lda     SFX_nmitimen
        and     #$7F
        sta     NMITIMEN
        RW      a16
        lda     qc_input_yaw
        beq     @Pitch
        clc
        adc     yaw_index
        and     #CAMERA_ANGLE_MASK
        sta     yaw_index
        inc     control_revision
@Pitch:
        lda     qc_input_pitch
        beq     @RestoreNmi
        clc
        adc     pitch_level
        bmi     @Negative
        cmp     #CAMERA_PITCH_MAX+1
        bcc     @StorePitch
        lda     #CAMERA_PITCH_MAX
        bra     @StorePitch
@Negative:
        cmp     #CAMERA_PITCH_MIN
        bcs     @StorePitch
        lda     #CAMERA_PITCH_MIN
@StorePitch:
        cmp     pitch_level
        beq     @RestoreNmi
        sta     pitch_level
        inc     control_revision
@RestoreNmi:
        RW      a8
        lda     SFX_nmitimen
        sta     NMITIMEN
        RW      a16
@Done:
        plb
        rtl

.ifdef PLAYABLE_E1M1_PREFETCH_GAMEPLAY
.pushseg
.ifdef PLAYABLE_E1M1_WALK_RESUME_BYTES
.segment "BSP_CPU_WALK_RESUME"
.else
.segment "BSP_CPU_WALK_RUN"
.endif
; A is the due tick. The frame pipeline runs with the input bank selected.
; Queued controls already have a tick-bound snapshot at admission.
GameplayCaptureDeferredLiveInput:
        RW_assume a16i16
        pha
        lda     a:qc_input_replay
        ora     a:deferred_live_input_tick ; Leave a claimed sample for its consumer.
        ora     f:quakec_fault
        bne     @Done
        lda     a:qc_sample_actions
        beq     @Done
        lda     1,s
        jsl     GameplayReadLiveInput
@Done:  pla
        rtl
.popseg

.pushseg
.segment "BSP_CPU_WALK_RUN"
GameplayConsumeLiveInput:
        RW_assume a16i16
        lda     a:deferred_live_input_tick
        stz     a:deferred_live_input_tick
        beq     @Read
        cmp     f:quakec_last_tick
        bne     @Read
        rtl
@Read:  lda     #0
        jml     GameplayReadLiveInput
.popseg
.endif

; Take current holds and read-clear relative mouse motion in one snapshot.
; Pad look is a velocity for the current step, just like pad movement.
GameplayReadLiveInput:
        RW_assume a16i16
.ifdef PLAYABLE_E1M1_PREFETCH_GAMEPLAY
        pha                             ; A holds the claimed tick, or zero.
.endif
        RW      a8
        lda     SFX_nmitimen
        and     #$7F
        sta     NMITIMEN
        RW      a16
.ifdef PLAYABLE_E1M1_PREFETCH_GAMEPLAY
        pla
        sta     deferred_live_input_tick
.endif
        stz     qc_input_yaw
        stz     qc_input_pitch
        lda     runtime_menu_open
.ifdef PLAYABLE_WEAPON_OBJ
        ora     weapon_obj_menu_pending
.endif
        beq     @Closed
        lda     #QC_INPUT_MENU
        bra     @ClearSample
@Closed:
        lda     camera_input_buttons
        and     #$FFF0
        ldx     runtime_menu_release_gate
        beq     @Active
        ora     #QC_INPUT_RELEASE
        bra     @ClearSample
@Active:
        ora     qc_sample_actions
        ldx     qc_sample_yaw
        stx     qc_input_yaw
        ldx     qc_sample_pitch
        stx     qc_input_pitch
        ldx     qc_sample_weapon
        beq     @ClearSample
        pha
.ifdef PLAYABLE_RECORDED_TAPE
        jsr     GameplayCycleCurrentWeapon
.else
        GAMEPLAY_CYCLE_CURRENT_WEAPON
.endif
        pla
@ClearSample:
.ifdef PLAYABLE_MAP_ID
        ora     runtime_walk
.endif
        sta     qc_input_buttons
        and     #QC_INPUT_MENU
        sta     qc_input_menu
        stz     qc_sample_actions
        stz     qc_sample_yaw
        stz     qc_sample_pitch
        stz     qc_sample_weapon
        RW      a8
        lda     SFX_nmitimen
        sta     NMITIMEN
        RW      a16
        lda     qc_input_buttons
        and     #(QC_INPUT_MENU | QC_INPUT_RELEASE)
        bne     @Done
        lda     qc_input_buttons
        bit     #JOY_LEFT
        bne     @YawLeft
        bit     #JOY_RIGHT
        beq     @Pitch
        lda     #.loword(-QC_LIVE_LOOK_STEP)
        bra     @Yaw
@YawLeft:
        lda     #QC_LIVE_LOOK_STEP
@Yaw:
        clc
        adc     qc_input_yaw
        sta     qc_input_yaw
@Pitch:
        lda     qc_input_buttons
        bit     #JOY_UP
        bne     @PitchUp
        bit     #JOY_DOWN
        beq     @Done
        lda     #.loword(-QC_LIVE_LOOK_STEP)
        bra     @AddPitch
@PitchUp:
        lda     #QC_LIVE_LOOK_STEP
@AddPitch:
        clc
        adc     qc_input_pitch
        sta     qc_input_pitch
@Done:
.ifdef PLAYABLE_E1M1_PREFETCH_GAMEPLAY
        rtl
.else
        rts
.endif

; Preserve the simulation's logical buttons and the original replay tapes.
.macro LIVE_BUTTON physical, logical
        tya
        bit     #physical
        beq     :+
        lda     #logical
        tsb     camera_input_buttons
:
.endmacro
MapLiveGameplayButtons:
        RW_assume a16i16
        tay
        stz     camera_input_buttons
        LIVE_BUTTON JOY_UP, JOY_X
        LIVE_BUTTON JOY_DOWN, JOY_B
        LIVE_BUTTON JOY_LEFT, JOY_Y
        LIVE_BUTTON JOY_RIGHT, JOY_A
        LIVE_BUTTON JOY_Y, JOY_LEFT
        LIVE_BUTTON JOY_A, JOY_RIGHT
        LIVE_BUTTON JOY_X, JOY_UP
        LIVE_BUTTON JOY_B, JOY_DOWN
        LIVE_BUTTON JOY_L, JOY_R
        LIVE_BUTTON JOY_R, JOY_L
        rts

; A short Start press is a weapon selection. At the hold threshold, consume
; that gesture by opening the menu. Closing the menu uses its own release gate.
GameplayLiveMenuInput:
        RW_assume a16i16
        lda     runtime_menu_release_gate
        beq     @Check
        stz     qc_start_hold
        bra     @Done
@Check:
        lda     z:SFX_joy1trig
        bit     #JOY_SELECT
        beq     :+
        lda     qc_sample_weapon
        eor     #1
        sta     qc_sample_weapon
:
        lda     z:SFX_joy1cont
        bit     #JOY_START
        beq     @Released
        inc     qc_start_hold
        lda     qc_start_hold
        cmp     #QC_START_MENU_VBLANKS
        rts
@Released:
        lda     qc_start_hold
        stz     qc_start_hold
        beq     @Done
        cmp     #QC_START_MENU_VBLANKS
        bcs     @Done
        lda     qc_sample_weapon
        eor     #1
        sta     qc_sample_weapon
@Done:
        clc
        rts

.ifdef PLAYABLE_RECORDED_TAPE
; Consume the current step's action at the weapon service, after pickups
; and existing projectiles, before dispatching the newly selected weapon.
GameplayApplyRecordedWeapon:
        RW_assume a16i16
        lda     f:qc_input_replay
        bit     #QC_INPUT_RECORDED_TAPE
        beq     @Done
        lda     f:qc_sample_weapon
        beq     @Done
        lda     #0
        sta     f:qc_sample_weapon
        jsr     GameplayCycleCurrentWeapon
@Done:
        rtl

GameplayCycleCurrentWeapon:
        GAMEPLAY_CYCLE_CURRENT_WEAPON
        rts
.endif

; WalkPublishPosition was called from NMI. Preserve its atomic XYZ/yaw
; publication while calling it from the foreground. A pending NMI is kept.
GameplayPublishPose:
        RW_assume a16i16
        lda     f:walk_pending
        beq     @Done
        RW      a8
        lda     f:SFX_nmitimen
        and     #$7F
        sta     f:NMITIMEN
        RW      a16
        jsl     WalkPublishPosition
        RW      a8
        lda     f:SFX_nmitimen
        sta     f:NMITIMEN
        RW      a16
@Done:
        rtl

; A death/release/fire sequence is gameplay input too. Request the reload
; only when the fire step is consumed. MainLoop reloads outside the FX job.
GameplayCheckRespawn:
        RW_assume a16i16
        phb
        phk
        plb
        lda     qc_input_menu
        ora     qc_input_release
        bne     @Continue
        lda     f:ShotgunPlayer+QC_FIELD_HEALTH
        beq     @Check
        bpl     @Continue
@Check:
        jsr     TryQuakeRespawn
        plb
        rtl
@Continue:
        clc
        plb
        rtl
.popseg
