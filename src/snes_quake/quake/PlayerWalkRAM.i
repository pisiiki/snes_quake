WalkRamBegin:
w_from = .loword(*)
        .res 6
w_to = .loword(*)
        .res 6
w_result = .loword(*)
        .res 6
w_normal = .loword(*)
        .res 6
w_delta = .loword(*)
        .res 6
w_base = .loword(*)
        .res 6
w_wish = .loword(*)
        .res 6
w_unstepped = .loword(*)
        .res 6
WalkPendingXYZ:
w_pending_xyz = .loword(*)
        .res 6
w_support_xyz = .loword(*)
        .res 6
WalkTraceStack:
w_stack = .loword(WalkTraceStack)
        .if SHOT_HULL_STACK_ENTRIES > WALK_HULL_STACK_ENTRIES
        .res SHOT_HULL_STACK_ENTRIES * 8
        .else
        .res WALK_HULL_STACK_ENTRIES * 8
        .endif
QC_WORD w_enter
QC_WORD w_front
QC_WORD w_back
.if .defined(QC_BASIC_GAMEPLAY)
QC_WORD w_coeff_c
.endif
.if !.defined(QC_BASIC_GAMEPLAY)
QC_WORD w_entrance_probe_owner
QC_WORD w_entrance_probe_pose
.ifdef QC_EXIT_MOVER_COUNT
QC_WORD qc_exit_collision_dirty
.endif
.endif
QC_WORD w_safe_t
QC_WORD w_fallback_count
QC_WORD w_dot
QC_WORD w_dot_high
QC_WORD w_progress
QC_WORD w_temp
QC_WORD w_button_contact
QC_WORD w_saved_contact
QC_WORD w_new_contact
QC_WORD w_can_step
QC_WORD w_buttons
QC_WORD w_support_valid
QC_WORD w_support_pose
QC_WORD w_step_plane
QC_WORD w_failed_step_plane
QC_WORD w_failed_step_tick
walk_pending: .res 2
w_pending = .loword(walk_pending)
walk_pending_yaw: .res 2
walk_pending_yaw_valid: .res 2
walk_ticks: .res 2
w_ticks = .loword(walk_ticks)
walk_grounded: .res 2
w_grounded = .loword(walk_grounded)
walk_velocity_z: .res 2
w_velocity_z = .loword(walk_velocity_z)
walk_impacts: .res 2
w_impacts = .loword(walk_impacts)
walk_slides: .res 2
w_slides = .loword(walk_slides)
walk_stairs: .res 2
w_stairs = .loword(walk_stairs)
walk_trace_fault: .res 2
w_trace_fault = .loword(walk_trace_fault)
walk_startsolid: .res 2
w_startsolid = .loword(walk_startsolid)
; Compare static axial endpoints as unsigned words after biasing their sign bit.
w_biased_from = .loword(*)
        .res 6
w_biased_to = .loword(*)
        .res 6
.ifdef PLAYABLE_E1M1_TRACE_LAYOUT
w_biased_from_fast = w_biased_from_dp
w_biased_to_fast = w_biased_to_dp
.else
w_biased_from_fast = w_biased_from
w_biased_to_fast = w_biased_to
.endif
; Oblique plane key, two Q4 coordinates, and the exact signed distance.
.ifndef PLAYABLE_LARGE_DISTANCE_CACHE
w_distance_cache = .loword(*)
        .res WALK_DISTANCE_CACHE_BYTES
.endif
QC_WORD w_jump_held
.if .defined(QC_BASIC_GAMEPLAY) .and (QC_HUB_ENABLED = 0)
; Six recent checked static-hull impacts, six words of exact input and
; seven words of output per record. Boot clears the validity words.
WALK_IMPACT_CACHE_STRIDE = 32
WALK_IMPACT_CACHE_BYTES = 6 * WALK_IMPACT_CACHE_STRIDE
QC_WORD w_impact_cache_next
w_impact_cache = .loword(*)
        .res WALK_IMPACT_CACHE_BYTES
.endif
QC_WORD w_jump_consumed
.ifdef QC_QUEUED_INPUT
walk_velocity_x: .res 2
w_velocity_x = .loword(walk_velocity_x)
walk_velocity_y: .res 2
w_velocity_y = .loword(walk_velocity_y)
w_run_slide = .loword(*)
        .res 4
QC_WORD w_run_swimming
QC_WORD w_run_speed
QC_WORD w_run_drop
QC_WORD w_run_gain
QC_WORD w_run_trial
.endif
.if BSP_PLAYER_WALK
QC_WORD w_landing_velocity
QC_WORD w_landing_cue
w_landing_sum = .loword(*)
        .res 4
.endif
.ifdef PLAYABLE_E1M1_TRACE_LAYOUT
; Packed axial splits share one span and starting side per sweep axis.
w_axial_span = .loword(*)
        .res 6
w_axial_front = .loword(*)
        .res 6
.endif
WalkRamEnd:
