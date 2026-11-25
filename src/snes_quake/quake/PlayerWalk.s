; Fixed-step player movement in the foreground, using the same VBlank clock
; as QuakeC. Publish complete XYZ on the next NMI before sampling the next pose.
WALK_STEP_HEIGHT = 18*16
WALK_FLOOR_Z = 11469             ; 0.7 in Q14.
WALK_GRAVITY = 57                ; 800 units/s² at 60 Hz, Q8 units/tick.
WALK_MAX_FALL = .loword(-16*256)
WALK_JUMP_SPEED = 270*256/60     ; Stock PlayerJump impulse, Q8 units/tick.
WALK_SUPPORT_PROBE = 4          ; Q4 drop from one gravity tick at rest.
.if .defined(QC_HUB_SWIM_OFFSET) || .defined(QC_LIQUID_ROOT)
WALK_SWIM_SPEED = (100*256+30)/60 ; Stock water jump speed in Q8.
  .ifdef QC_QUEUED_INPUT
WALK_WATER_VBLANKS = QC_INPUT_VBLANKS
  .else
WALK_WATER_VBLANKS = 1
  .endif
WALK_SWIM_STEP = 100*16*WALK_WATER_VBLANKS/60
WALK_WATER_FRICTION = ((60-4*WALK_WATER_VBLANKS)*16384+30)/60
WALK_WATER_WAIST_DRAG = ((600-16*WALK_WATER_VBLANKS)*16384+300)/600
WALK_WATER_DEEP_DRAG = ((600-24*WALK_WATER_VBLANKS)*16384+300)/600
WALK_WATER_IDLE_SPEED = (42*256+30)/60
WALK_WATER_IDLE_ACCEL = (42*256*10*WALK_WATER_VBLANKS+1800)/3600
WALK_WATER_STEER_ACCEL = (10*WALK_WATER_VBLANKS*16384+30)/60
WALK_AIR_TICKS = 12*60/WALK_WATER_VBLANKS
WALK_GASP_TICKS = 3*60/WALK_WATER_VBLANKS
WALK_DROWN_TICKS = 60/WALK_WATER_VBLANKS
        .pushseg
        .segment "EXRAM"
walk_swim_coords: .res 7*2
w_swim_coords = .loword(walk_swim_coords)
walk_swim_wish_z: .res 2
w_swim_wish_z = .loword(walk_swim_wish_z)
walk_swim_pitch_cos: .res 2
w_swim_pitch_cos = .loword(walk_swim_pitch_cos)
walk_swim_reverse: .res 2
w_swim_reverse = .loword(walk_swim_reverse)
walk_water_drag: .res 2
w_water_drag = .loword(walk_water_drag)
  .ifndef QC_QUEUED_INPUT
walk_swim_angles: .res 4
w_swim_angles = .loword(walk_swim_angles)
  .endif
        .popseg
.endif

WalkService:
        lda     f:walk_pending_yaw_valid
        bne     @Idle
        lda     f:QC_INPUT_MENU_OPEN
        ora     f:QC_INPUT_RELEASE_GATE
        bne     @Idle
        lda     a:shot_player+QC_FIELD_HEALTH
        beq     @Idle
        bpl     WalkSimulationBegin
@Idle:  rts
WalkSimulationBegin:
        lda     a:w_pending
        beq     @Live
        ldx     #4
@Pending:
        lda     a:w_pending_xyz,x
        sta     a:w_from,x
        dex
        dex
        bpl     @Pending
        bra     @Simulate
@Live:
        lda     f:camera_x
        sta     a:w_from
        lda     f:camera_y
        sta     a:w_from+2
        lda     f:camera_z
        sta     a:w_from+4
@Simulate:
        inc     a:w_ticks
        stz     a:w_button_contact
        lda     a:w_velocity_z
        sta     a:w_landing_velocity
        jsr     WalkBuildWish
        jsr     WalkTryJump
.if .defined(QC_HUB_SWIM_OFFSET) || .defined(QC_LIQUID_ROOT)
        bcc     @Land
        jsr     WalkSweepVertical
        lda     a:w_wish
        ora     a:w_wish+2
        bne     @Horizontal
        bra     @Publish
@Land:
.endif
        lda     a:w_wish
        ora     a:w_wish+2
        bne     @Move
        jsr     WalkStationary
        bra     @Publish
@Move:
        stz     a:w_support_valid
        jsr     WalkGravity
@Horizontal:
        ldx     #4
@Base:
        lda     a:w_from,x
        sta     a:w_base,x
        dex
        dex
        bpl     @Base
        lda     a:w_button_contact
        sta     a:w_saved_contact
        stz     a:w_can_step
        jsr     WalkHorizontal
.ifdef QC_QUEUED_INPUT
        jsr     WalkRunSaveSlide
.endif
        lda     a:w_can_step
        and     a:w_grounded
        beq     @Publish
        ; Retry a rejected stair route on the same wall at half cadence.
        ; A new face still gets an immediate attempt.
        lda     a:w_step_plane
        cmp     a:w_failed_step_plane
        bne     @TryStep
        lda     a:w_ticks
        dec
        cmp     a:w_failed_step_tick
        beq     @Publish
@TryStep:
        lda     a:w_step_plane
        sta     a:w_failed_step_plane
        lda     a:w_ticks
        sta     a:w_failed_step_tick
        jsr     WalkTryStep
@Publish:
        lda     a:w_button_contact
        beq     :+
        sta     f:quakec_contact
:
.if .defined(QC_LIQUID_ROOT) && .defined(PICKUP_BLEND)
        jsr     WalkEyePalette
.endif
        lda     a:w_from
        cmp     f:camera_x
        bne     @Changed
        lda     a:w_from+2
        cmp     f:camera_y
        bne     @Changed
        lda     a:w_from+4
        cmp     f:camera_z
        beq     WalkSimulationEnd
@Changed:
        ; A second tick may coalesce into a pending position. Clear ready
        ; before replacing its words so NMI cannot observe a mixed pose.
        stz     a:w_pending
        ldx     #4
@Write:
        lda     a:w_from,x
        sta     a:w_pending_xyz,x
        dex
        dex
        bpl     @Write
        lda     #1
        sta     a:w_pending
WalkSimulationEnd:
        rts

WalkPublishPosition:
        RW_assume a16i16
        lda     f:walk_pending
        beq     @Done
        lda     f:WalkPendingXYZ
        sta     f:camera_x
        lda     f:WalkPendingXYZ+2
        sta     f:camera_y
        lda     f:WalkPendingXYZ+4
        sta     f:camera_z
        lda     f:walk_pending_yaw_valid
        beq     @PositionOnly
        lda     f:walk_pending_yaw
        sta     f:yaw_index
.ifdef QC_INTERMISSION_COUNT
        lda     f:intermission_phase
        cmp     #2
        bne     :+
        lda     #.loword(QC_INTERMISSION_0_PITCH)
        bra     :++
:
.endif
        lda     #0
:       sta     f:pitch_level
.ifdef QC_INTERMISSION_COUNT
        lda     #0
.endif
        sta     f:walk_pending_yaw_valid
@PositionOnly:
        lda     #0
        sta     f:walk_pending
        lda     f:control_revision
        inc
        sta     f:control_revision
@Done:
        rtl

; A stationary, supported player cannot lose ground until a brush
; changes pose. A changed camera also invalidates the cached contact.
WalkStationary:
        lda     a:w_support_valid
        beq     @Probe
.if QC_ENTRANCE_COUNT > 0
        jsr     QuakeCWalkSupportPose
.else
        lda     f:quakec_brush_row
.endif
        cmp     a:w_support_pose
        bne     @Probe
        lda     a:w_from
        cmp     a:w_support_xyz
        bne     @Probe
        lda     a:w_from+2
        cmp     a:w_support_xyz+2
        bne     @Probe
        lda     a:w_from+4
        cmp     a:w_support_xyz+4
        bne     @Probe
        rts
@Probe:
        jsr     WalkGravity
        lda     a:w_grounded
        sta     a:w_support_valid
        beq     @Done
.if QC_ENTRANCE_COUNT > 0
        jsr     QuakeCWalkSupportPose
.else
        lda     f:quakec_brush_row
.endif
        sta     a:w_support_pose
        ldx     #4
@Copy:
        lda     a:w_from,x
        sta     a:w_support_xyz,x
        dex
        dex
        bpl     @Copy
@Done:
        rts

WalkTryJump:
.if .defined(QC_HUB_SWIM_OFFSET) || .defined(QC_LIQUID_ROOT)
        lda     a:swim_sound_cooldown
        beq     :+
        dec     a:swim_sound_cooldown
:
.endif
        lda     a:w_buttons
        and     #JOY_R
        sta     a:w_jump_held
        bne     :+
        stz     a:w_jump_consumed
:
.if .defined(QC_HUB_SWIM_OFFSET) || .defined(QC_LIQUID_ROOT)
        jsr     WalkCanSwim
        bcs     @Swimming
.ifdef QC_LIQUID_ROOT
        lda     a:walk_ledge_ticks
        beq     :+
        jsl     WalkWaterJump
        bcs     @Ledge
:
.endif
        jmp     @Dry
@Swimming:
        jsr     WalkCheckEyeWater
.ifdef QC_LIQUID_ROOT
        jsl     WalkWaterJump
        bcc     :+
@Ledge: rts
:
.endif
.if .defined(QC_LIQUID_ROOT) && .defined(QC_QUEUED_INPUT)
        stz     a:w_grounded
        stz     a:w_support_valid
        stz     a:w_run_swimming       ; Retain velocity clipped by the accepted slide.
        jsl     WalkWaterMove
        ldx     a:w_jump_held
        bne     @SwimJump
        sec
        rts
.else
  .ifdef QC_QUEUED_INPUT
        lda     #1
        sta     a:w_run_swimming
        stz     a:w_velocity_x
        stz     a:w_velocity_y
        ldx     a:w_wish+4
        stz     a:w_wish+4
        jsr     WalkBuildLegacyWish
  .endif
        jsr     WalkBuildSwimWish
        stz     a:w_grounded
        stz     a:w_support_valid
        lda     a:w_jump_held
        bne     :+
        jmp     WalkWaterDrift
:
.endif
@SwimJump:
        lda     #WALK_SWIM_SPEED
.ifdef QC_LIQUID_ROOT
        ldx     a:walk_liquid_type
        cpx     #.loword(-4)
        bne     :+
        lda     #(80*256+30)/60
:
.endif
        sta     a:w_velocity_z
        lda     a:swim_sound_cooldown
        bne     @SwimStep
        ; PlayerJump requires time strictly beyond the one-second deadline.
        lda     #60/WALK_WATER_VBLANKS+1
        sta     a:swim_sound_cooldown
        ; Keep sample selection independent of gameplay RNG.
        lda     a:swim_sound_rng
        bne     :+
        lda     #$4a21
:       lsr
        bcc     :+
        eor     #$b400
:       sta     a:swim_sound_rng
        lda     #$40
        bcc     :+
        lda     #$80
:       jsr     GameplayPlayBodySound
@SwimStep:
        lda     #WALK_SWIM_STEP
.ifdef QC_LIQUID_ROOT
        ldx     a:walk_liquid_type
        cpx     #.loword(-4)
        bne     :+
        lda     #80*16*WALK_WATER_VBLANKS/60
:
.endif
        sec
        rts                           ; Carry selects the water displacement.
@Dry:
        jsr     WalkBreathe
.endif
.ifdef QC_QUEUED_INPUT
        jsl     WalkBuildRunWish
        jsr     WalkRunMove
        stz     a:w_wish+4
.endif
        lda     a:w_jump_held
        beq     @Done
        lda     a:w_jump_consumed
        bne     @Done
        lda     a:w_grounded
        beq     @Done
        ; Walking can leave the last floor and a pusher can move after
        ; the last tick. Check the current hull before applying an impulse.
        lda     #.loword(-WALK_SUPPORT_PROBE)
        jsr     WalkTraceVertical
        bcc     @Done
        lda     a:w_normal+4
        bmi     @Done
        cmp     #WALK_FLOOR_Z
        bcc     @Done
        lda     #WALK_JUMP_SPEED
        sta     a:w_velocity_z
        inc     a:w_jump_consumed      ; Only a successful jump consumes the hold.
        stz     a:w_grounded
        stz     a:w_support_valid
        lda     #0
        jsr     GameplayPlayBodySound
@Done:
.if .defined(QC_HUB_SWIM_OFFSET) || .defined(QC_LIQUID_ROOT)
        clc
.endif
        rts

.if .defined(QC_HUB_SWIM_OFFSET) || .defined(QC_LIQUID_ROOT)
.if !(.defined(QC_LIQUID_ROOT) && .defined(QC_QUEUED_INPUT))
WalkWaterDrift:
        ; SV_WaterMove damps the current velocity before the idle down wish.
        lda     a:w_velocity_z
        ldx     #WALK_WATER_FRICTION
        jsr     WalkMultiply
        jsr     WalkProductQ14
        sta     a:w_velocity_z
        lda     a:w_swim_wish_z
        beq     @IdleWish
        jsr     WalkAccelerateSwimZ
        bra     @WaterMoveDrag
@IdleWish:
        lda     a:w_wish
        ora     a:w_wish+2
        bne     @WaterMoveDrag
        lda     a:w_velocity_z
        bpl     :+
        eor     #$ffff
        inc
:       cmp     #WALK_WATER_IDLE_SPEED
        bcs     @WaterMoveDrag
        eor     #$ffff
        sec
        adc     #WALK_WATER_IDLE_SPEED
        cmp     #WALK_WATER_IDLE_ACCEL
        bcc     :+
        lda     #WALK_WATER_IDLE_ACCEL
:       eor     #$ffff
        sec
        adc     a:w_velocity_z
        sta     a:w_velocity_z
@WaterMoveDrag:
        ldx     a:w_water_drag
        lda     a:w_velocity_z
        jsr     WalkMultiply
        jsr     WalkProductQ14
        sta     a:w_velocity_z
        .repeat WALK_WATER_VBLANKS-1
        clc
        adc     a:w_velocity_z
        .endrepeat
        clc
        adc     #8                    ; Round the whole Q4 sweep once.
        .repeat 4
        cmp     #$8000
        ror
        .endrepeat
        sec
        rts

.endif

WalkCheckEyeWater:
        ; The eye is 18 units above the waist probe in the same column.
        lda     a:w_swim_coords+4
        clc
        adc     #18*16
        sta     a:w_swim_coords+4
        jsr     WalkSwimVolume
        bcc     @Air
.ifdef QC_LIQUID_ROOT
        inc     a:walk_water_level
.endif
        lda     #WALK_WATER_DEEP_DRAG
        sta     a:w_water_drag
.ifdef QC_LIQUID_ROOT
        lda     a:shot_player+QC_FIELD_RADSUIT_FINISHED
        beq     :+
        stz     a:walk_air_ticks
        rts
:
.endif
        lda     a:walk_air_ticks
        cmp     #WALK_AIR_TICKS+1
        bcs     @NoAir
        inc
        sta     a:walk_air_ticks
        cmp     #WALK_AIR_TICKS+1
        bcc     @Done
@NoAir:
        lda     a:walk_drown_cooldown
        beq     @Damage
        dec     a:walk_drown_cooldown
@Done:
        rts
@Damage:
        lda     #WALK_DROWN_TICKS
        sta     a:walk_drown_cooldown
        lda     a:walk_drown_damage
        bne     :+
        lda     #2
:       inc
        inc
        cmp     #16
        bcc     :+
        lda     #10
:       sta     a:walk_drown_damage
        .repeat 6
        asl
        .endrepeat
.if .defined(QC_ARMOR_COUNT) || .defined(QC_CAMPAIGN_ITEMS)
        jsl     ArmorEnvironmentDamage
.endif
        eor     #$ffff
        sec
        adc     a:shot_player+QC_FIELD_HEALTH
        sta     a:shot_player+QC_FIELD_HEALTH
        lda     #4
        sta     a:grunt_damage_flash
        rts
@Air:
        lda     #WALK_WATER_WAIST_DRAG
        sta     a:w_water_drag
WalkBreathe:
        lda     a:walk_air_ticks
        beq     @Done
        stz     a:walk_air_ticks
        stz     a:walk_drown_cooldown
        stz     a:walk_drown_damage
        ; The surfacing tick follows the last submerged tick.
        cmp     #WALK_AIR_TICKS
        bcs     @Empty
        cmp     #WALK_GASP_TICKS
        bcc     @Done
        lda     #GAMEPLAY_AUX_GASP_LOW
        bra     @Gasp
@Empty:
        lda     #GAMEPLAY_AUX_GASP_EMPTY
@Gasp:
        inc     a:.loword(quakec_sounds)
        jsl     GameplayPlayAuxSound
@Done:
        rts

.if !(.defined(QC_LIQUID_ROOT) && .defined(QC_QUEUED_INPUT))
; The forward command supplies a signed vertical velocity wish. Accelerate
; along it after water friction, with no idle descent while steering.
WalkAccelerateSwimZ:
        ldx     a:w_velocity_z
        cmp     #0
        bpl     @Projected
        neg
        pha
        txa
        neg
        tax
        pla
@Projected:
        sta     a:w_temp
        stx     z:w_mul_low
        sec
        sbc     z:w_mul_low
        beq     @Done
        bmi     @Done
        pha
        lda     a:w_temp
        ldx     #WALK_WATER_STEER_ACCEL
        jsr     WalkMultiply
        jsr     WalkProductQ14
        sta     a:w_temp
        pla
        cmp     a:w_temp
        bcc     :+
        lda     a:w_temp
:       ldx     a:w_swim_wish_z
        bpl     :+
        neg
:       clc
        adc     a:w_velocity_z
        sta     a:w_velocity_z
@Done:  rts

WalkBuildSwimWish:
        stz     a:w_swim_wish_z
        lda     a:w_buttons
        and     #(JOY_X | JOY_B)
        cmp     #JOY_X
        beq     @Direction
        cmp     #JOY_B
        bne     @Done
@Direction:
        and     #JOY_B
        sta     a:w_swim_reverse
.ifdef QC_QUEUED_INPUT
        lda     f:pitch_level
.else
        lda     a:w_swim_angles+2
.endif
        beq     @Done
        and     #CAMERA_ANGLE_MASK
        asl
        tax
        lda     f:CameraMoveSin,x
        ldy     a:w_swim_reverse
        beq     :+
        neg
:       .repeat 4
        asl
        .endrepeat
        sta     a:w_swim_wish_z       ; Q5 direction to Q8 units per VBlank.
        lda     f:CameraMoveCos,x
        sta     a:w_swim_pitch_cos
.ifdef QC_QUEUED_INPUT
        lda     f:yaw_index
        and     #CAMERA_ANGLE_MASK
        asl
        tax
.else
        ldx     a:w_swim_angles
.endif
        phx
        lda     f:CameraMoveCos,x
        jsr     WalkScaleSwimAxis
        sta     a:w_wish
        plx
        phx
        lda     f:CameraMoveSin,x
        jsr     WalkScaleSwimAxis
        sta     a:w_wish+2
        plx
        jmp     WalkAddStrafe
@Done:  rts

; Signed nearest Q5 multiply, with backward reversing only the forward axis.
WalkScaleSwimAxis:
        ldy     a:w_swim_reverse
        beq     :+
        neg
:       pha
        cmp     #0
        bpl     :+
        neg
:       ldx     a:w_swim_pitch_cos
        jsr     WalkMultiply
        lda     z:w_mul_low
        clc
        adc     #16
        .repeat 5
        lsr
        .endrepeat
        ply
        bpl     :+
        neg
:       rts

.endif

.ifdef QC_LIQUID_ROOT
.include "quake/PlayerLiquids.s"
.include "quake/PlayerWaterJump.s"
.ifdef QC_QUEUED_INPUT
.include "quake/PlayerWaterMove.s"
.endif
.else
WalkCanSwim:
        ; Reject distant X/Y before evaluating the signed oblique axes.
        lda     a:w_from
        sec
        sbc     #.loword(QC_HUB_SWIM_X_MIN)
        cmp     #QC_HUB_SWIM_X_SPAN
        bcs     WalkSwimMiss
        lda     a:w_from+2
        sec
        sbc     #.loword(QC_HUB_SWIM_Y_MIN)
        cmp     #QC_HUB_SWIM_Y_SPAN
        bcs     WalkSwimMiss
        lda     a:w_from+4
        sta     a:w_swim_coords+4
        lda     a:w_from+2
        sta     a:w_swim_coords+2
        lda     a:w_from
        sta     a:w_swim_coords
        clc
        adc     a:w_from+2
        sta     a:w_swim_coords+6
        clc
        adc     a:w_from
        sta     a:w_swim_coords+10
        lda     a:w_from
        sec
        sbc     a:w_from+2
        sta     a:w_swim_coords+8
        clc
        adc     a:w_from
        sta     a:w_swim_coords+12
WalkSwimVolume:
        ldx     #0
@Zone:
        phx
        ldy     #0
@Axis:
        lda     a:w_swim_coords,y
        sec
        sbc     f:WalkSwimData,x
        cmp     f:WalkSwimData+2,x
        bcs     @NextZone
        .repeat 4
        inx
        .endrepeat
        iny
        iny
        cpy     #7*2
        bcc     @Axis
        plx
        sec
        rts
@NextZone:
        plx
        txa
        clc
        adc     #7*4
        tax
        cpx     #QC_HUB_SWIM_END-QC_HUB_SWIM_OFFSET
        bcc     @Zone
WalkSwimMiss:
        clc
        rts
.endif
.endif

WalkGravity:
.ifdef QC_QUEUED_INPUT
        ; Integrate the three VBlank velocities at Q8 and round the
        ; displacement once before the fixed-step hull sweep.
        stz     a:w_temp
        ldx     #QC_INPUT_VBLANKS
@Integrate:
.endif
        lda     a:w_velocity_z
        sec
        sbc     #WALK_GRAVITY
        bpl     @StoreVelocity
        cmp     #WALK_MAX_FALL
        bcs     @StoreVelocity
        lda     #WALK_MAX_FALL
@StoreVelocity:
        sta     a:w_velocity_z
.ifdef QC_QUEUED_INPUT
        clc
        adc     a:w_temp
        sta     a:w_temp
        dex
        bne     @Integrate
        clc
        adc     #8
.endif
        .repeat 4
        cmp     #$8000
        ror
        .endrepeat
WalkSweepVertical:
        jsr     WalkVertical
        stz     a:w_grounded
        bcc     @Done
        stz     a:w_velocity_z
        jsr     WalkRememberContact
        lda     a:w_normal+4
        cmp     #$8000
        bcs     @Done
        cmp     #WALK_FLOOR_Z
        bcc     @Done
        inc     a:w_grounded
        lda     a:w_landing_velocity
        bpl     @Done
        cmp     #.loword(-300*256/60)
        bcs     @Done
        jmp     WalkQueueLanding
@Done:
        rts

; A signed Q4 Z displacement, with X and Y fixed.
WalkVertical:
        jsr     WalkTraceVertical
        jmp     WalkApplyResult

WalkTraceVertical:
        clc
        adc     a:w_from+4
        bvc     :+
        lda     a:w_from+4
:       sta     a:w_to+4
        lda     a:w_from
        sta     a:w_to
        lda     a:w_from+2
        sta     a:w_to+2
        jmp     WalkTrace

WalkBuildWish:
        stz     a:w_wish
        stz     a:w_wish+2
        stz     a:w_wish+4
@Input:
        lda     f:video_tick
        sta     a:w_temp
        lda     f:yaw_index
        and     #CAMERA_ANGLE_MASK
        asl
        tax
.if .defined(QC_HUB_SWIM_OFFSET) && !.defined(QC_QUEUED_INPUT)
        stx     a:w_swim_angles
        lda     f:pitch_level
        sta     a:w_swim_angles+2
.endif
        lda     f:QC_INPUT_BUTTONS
.ifdef QC_E1M1_TELEPORT
        ; SV_AirMove discards negative forwardmove for .7s after a teleport.
        ; Preserve conflicting forward/back input (net zero) and all strafing.
        pha
        and     #(JOY_X | JOY_B)
        cmp     #JOY_B
        bne     :+
        lda     f:hub_teleport_cooldown
        beq     :+
        pla
        and     #.loword(~JOY_B)
        bra     :++
:       pla
:
.endif
        sta     a:w_buttons
        lda     f:video_tick
        cmp     a:w_temp
        bne     @Input
.ifdef QC_QUEUED_INPUT
        stx     a:w_wish+4             ; Keep the yaw from this input sample.
        rts
.endif
WalkBuildLegacyWish:
        lda     a:w_buttons
        and     #(JOY_X | JOY_B)
        cmp     #JOY_X
        beq     @Forward
        cmp     #JOY_B
        bne     WalkAddStrafe
        lda     #0
        sec
        sbc     f:CameraMoveCos,x
        sta     a:w_wish
        lda     #0
        sec
        sbc     f:CameraMoveSin,x
        sta     a:w_wish+2
        bra     WalkAddStrafe
@Forward:
        lda     f:CameraMoveCos,x
        sta     a:w_wish
        lda     f:CameraMoveSin,x
        sta     a:w_wish+2
WalkAddStrafe:
        lda     a:w_buttons
        and     #(JOY_Y | JOY_A)
        cmp     #JOY_A
        beq     @Right
        cmp     #JOY_Y
        bne     @Done
        lda     a:w_wish
        sec
        sbc     f:CameraMoveSin,x
        sta     a:w_wish
        lda     a:w_wish+2
        clc
        adc     f:CameraMoveCos,x
        sta     a:w_wish+2
        bra     @Done
@Right:
        lda     a:w_wish
        clc
        adc     f:CameraMoveSin,x
        sta     a:w_wish
        lda     a:w_wish+2
        sec
        sbc     f:CameraMoveCos,x
        sta     a:w_wish+2
@Done:
.ifdef QC_QUEUED_INPUT
        .repeat 2, axis
          lda   a:w_wish+axis*2
          asl
          clc
          adc   a:w_wish+axis*2
          sta   a:w_wish+axis*2
        .endrepeat
.endif
        rts

.ifdef QC_QUEUED_INPUT
.pushseg
.segment "BSP_CPU_WALK_RUN"
; Quake uses 400 or 200 forward/back and 350 strafe, capped at 320
; units/s. The nearest diagonal headings are 29 or 43 steps off axis.
; The sampled yaw in wish Z becomes the temporary dry-move speed.
WalkBuildRunWish:
        lda     a:w_buttons
        xba
        and     #$00C0
        .repeat 5
        lsr
        .endrepeat
        sta     a:w_temp
        lda     a:w_buttons
        and     #$00C0
        .repeat 3
        lsr
        .endrepeat
        ora     a:w_temp
        tax
        lda     a:w_buttons
        bit     #QC_INPUT_WALK
        beq     @Run
        lda     f:WalkAngles,x
        bra     @Direction
@Run:
        lda     f:WalkRunAngles,x
@Direction:
        ldx     a:w_wish+4
        stz     a:w_wish+4
        cmp     #$0200
        beq     @Done
        bit     #$0400
        beq     :+
        and     #(CAMERA_ANGLE_MASK*2)
        ldy     #RUN_WALK_SPEED
        sty     a:w_wish+4
:       stx     a:w_temp
        clc
        adc     a:w_temp
        and     #(CAMERA_ANGLE_MASK*2)
        tax
        lda     f:CameraRunCos,x
        sta     a:w_wish
        lda     f:CameraRunSin,x
        sta     a:w_wish+2
@Done:
        rtl
WalkRunAngles:
        .word $0200, $0080, $0100, $00C6, $0000, $003A, $0200, $0080
        .word $0180, $0200, $013A, $0100, $01C6, $0000, $0180, $0200
; Bit 10 marks a 200 units/s pure forward/back command.
WalkAngles:
        .word $0200, $0080, $0500, $00AA, $0400, $0056, $0200, $0080
        .word $0180, $0200, $0156, $0500, $01AA, $0400, $0180, $0200
.popseg
.include "quake/PlayerRun.s"
.endif

WalkHorizontal:
.ifdef QC_QUEUED_INPUT
        jsr     WalkRunBeginSlide
.endif
        ldx     #4
@Delta:
        lda     a:w_wish,x
        sta     a:w_delta,x
        dex
        dex
        bpl     @Delta
        jsr     WalkBuildTo
        jsr     WalkTrace
        bcs     @Hit
        jmp     WalkApplyResult
@Hit:
.ifdef QC_QUEUED_INPUT
        jsr     WalkRunClipSlide
.endif
        jsr     WalkRememberContact
        lda     a:w_enter
        cmp     #WALK_NO_PLANE
        bne     :+
        jmp     WalkApplyResult
:       and     #WALK_PLANE_OFFSET
.ifdef QC_E1M1_PLATFORM_FIRST
        ; E1M1's powered lift and exit brushes can have stair-height lips,
        ; including fixed side planes on vertically translated decks.
        cmp     #WALK_BUTTON_PLANE
        bcc     @StepFace
        cmp     #WALK_EXIT_PLANE_FIRST
        bcc     @Remaining
@StepFace:
.else
        cmp     #WALK_DOOR_PLANE
        bcs     @Remaining
.endif
        lda     a:w_normal+4
        clc
        adc     #WALK_FLOOR_Z
        cmp     #2*WALK_FLOOR_Z
        bcs     @Remaining
        lda     a:w_enter
        sta     a:w_step_plane
        lda     #1
        sta     a:w_can_step
@Remaining:
        ldx     #4
@Residual:
        lda     a:w_to,x
        sec
        sbc     a:w_result,x
        sta     a:w_delta,x
        dex
        dex
        bpl     @Residual
        jsr     WalkApplyResult
        stz     a:w_dot
        stz     a:w_dot_high
        ldy     #4
@Dot:
        lda     a:w_delta,y
        beq     @NextAxis
.ifdef QC_QUEUED_INPUT
        tax                             ; Short residual uses the byte operand.
        lda     a:w_normal,y
        beq     @NextAxis
.else
        lda     a:w_normal,y
        beq     @NextAxis
        tax
        lda     a:w_delta,y
.endif
        jsr     WalkMultiply
        lda     a:w_dot
        clc
        adc     z:w_mul_low
        sta     a:w_dot
        lda     a:w_dot_high
        adc     z:w_mul_high
        sta     a:w_dot_high
@NextAxis:
        dey
        dey
        bpl     @Dot
        lda     a:w_dot_high
        bpl     @Done
        sta     z:w_mul_high
        lda     a:w_dot
        sta     z:w_mul_low
        jsr     WalkProductQ14
        sta     a:w_progress
        ldy     #4
@Clip:
        lda     a:w_normal,y
        beq     @NextClip
        ldx     a:w_progress
        jsr     WalkMultiply
        jsr     WalkProductQ14
        sta     a:w_temp
        lda     a:w_delta,y
        sec
        sbc     a:w_temp
        sta     a:w_delta,y
@NextClip:
        dey
        dey
        bpl     @Clip
        lda     a:w_delta
        ora     a:w_delta+2
        ora     a:w_delta+4
        beq     @Done
        inc     a:w_slides
        jsr     WalkBuildTo
        jsr     WalkTrace
        bcc     :+
.ifdef QC_QUEUED_INPUT
        jsr     WalkRunClipSlide
.endif
        jsr     WalkRememberContact
:       jmp     WalkApplyResult
@Done:
        rts

WalkTryStep:
        lda     a:w_button_contact
        sta     a:w_new_contact
        lda     a:w_saved_contact
        sta     a:w_button_contact
        ldx     #4
@Save:
        lda     a:w_from,x
        sta     a:w_unstepped,x
        lda     a:w_base,x
        sta     a:w_from,x
        dex
        dex
        bpl     @Save
        lda     #WALK_STEP_HEIGHT
        jsr     WalkVertical
        bcs     @Reject
        jsr     WalkHorizontal
        ; Downward tracing leaves XY unchanged. Test progress first and
        ; skip that trace for a wall that also blocks the raised route.
        lda     a:w_from
        sec
        sbc     a:w_unstepped
        ldx     a:w_wish
        jsr     WalkMultiply
        lda     z:w_mul_low
        sta     a:w_progress
        lda     z:w_mul_high
        sta     a:w_dot_high
        lda     a:w_from+2
        sec
        sbc     a:w_unstepped+2
        ldx     a:w_wish+2
        jsr     WalkMultiply
        lda     a:w_progress
        clc
        adc     z:w_mul_low
        tax
        lda     a:w_dot_high
        adc     z:w_mul_high
        bmi     @Reject
        bne     @Progress
        cpx     #0
        beq     @Reject
@Progress:
        lda     #.loword(-WALK_STEP_HEIGHT-4)
        jsr     WalkVertical
        bcc     @Reject
        lda     a:w_normal+4
        bmi     @Reject
        cmp     #WALK_FLOOR_Z
        bcc     @Reject
        lda     a:w_from+4
        sec
        sbc     a:w_base+4
        beq     @Reject
        bmi     @Reject
        jsr     WalkRememberContact
        lda     #WALK_NO_PLANE
        sta     a:w_failed_step_plane
        inc     a:w_stairs
.ifdef QC_QUEUED_INPUT
        jsr     WalkRunSaveSlide
.endif
        rts
@Reject:
        lda     a:w_new_contact
        sta     a:w_button_contact
        ldx     #4
@Restore:
        lda     a:w_unstepped,x
        sta     a:w_from,x
        dex
        dex
        bpl     @Restore
        rts

WalkRememberContact:
        lda     a:w_enter
        cmp     #WALK_NO_PLANE
        beq     @Done
        and     #WALK_PLANE_OFFSET
        cmp     #WALK_BUTTON_PLANE
        bcc     @Done
.if !.defined(QC_BASIC_GAMEPLAY)
        cmp     #WALK_BUTTON_PLANE_END
        bcs     @Done
.endif
        lda     #1
        sta     a:w_button_contact
@Done:
        rts

WalkBuildTo:
        ldx     #4
@Axis:
        lda     a:w_from,x
        clc
        adc     a:w_delta,x
        bvc     :+
        lda     a:w_from,x
:       sta     a:w_to,x
        dex
        dex
        bpl     @Axis
        rts

WalkApplyResult:
        ldx     #4
@Axis:
        lda     a:w_result,x
        sta     a:w_from,x
        dex
        dex
        bpl     @Axis
        rts
