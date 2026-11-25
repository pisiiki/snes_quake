QC_WORD grunt_clock
QC_WORD grunt_frame
QC_WORD grunt_yaw
QC_WORD grunt_shots
QC_WORD grunt_damage_flash
QC_WORD gr_tick_actor
.ifdef QC_GIB_FIRST_ROW
QC_WORD gib_actor_count
QC_WORD gib_cursor
QC_WORD gib_remaining
.endif
QC_WORD gr_skill_mask
QC_WORD gr_render_offset
QC_WORD gr_lift_top
QC_WORD gr_lift_delta
QC_WORD gr_trace_passed
QC_WORD gr_trace_actor
QC_WORD gr_trace_axis
QC_WORD gr_trace_normal
QC_WORD gr_normal
QC_WORD gr_enter
QC_WORD gr_exit
QC_WORD gr_axis_hit
QC_WORD gr_min
QC_WORD gr_max
QC_WORD gr_start
QC_WORD gr_end
QC_WORD gr_sum_lo
QC_WORD gr_sum_hi
QC_WORD gr_root
QC_WORD gr_bit
QC_WORD gr_trial
QC_WORD gr_length_shift
QC_WORD gr_math_axis
QC_WORD gr_old_health
.ifdef QC_DOG_FIRST
QC_WORD dog_hit_player
QC_WORD dog_landed
.endif
GruntVector: .res 6
gr_vector = .loword(GruntVector)
QC_WORD grunt_moves
QC_WORD grunt_blocked_moves
QC_WORD grunt_unsupported_moves
QC_WORD grunt_steps_up
QC_WORD gr_move_distance
QC_WORD gr_move_angle
QC_WORD gr_close_xy
QC_WORD gr_goal_x
QC_WORD gr_goal_y
QC_WORD gr_goal_actor
QC_WORD gr_old_direction
QC_WORD gr_reverse
QC_WORD gr_nav_x
QC_WORD gr_nav_y
QC_WORD gr_nav_abs_y
QC_WORD gr_nav_scan
QC_WORD gr_nav_random
QC_WORD gr_turn_only
QC_WORD gr_foot_z
QC_WORD gr_foot_index
QC_WORD gr_min_support
gr_move_base = .loword(*)
        .res 6
gr_move_target = .loword(*)
        .res 6
gr_move_q3 = .loword(*)
        .res 6
grunt = qce + QC_GRUNT
.ifdef QC_IMPACT_ROW
; The two per-monster counters fit in the world and final shell edict tails.
.assert QC_GRUNT = 7*QC_ENTITY_STRIDE && QC_SHELL_COUNT = 3, error, "shell edict layout changed"
.assert IMPACT_EDICT_OFFSET+QC_GRUNT_COUNT*2 <= QC_ENTITY_STRIDE, error, "monster counters cross an edict"
.export GruntActorMoves:far, GruntActorShots:far
GruntActorMoves = QuakeCEdicts+IMPACT_EDICT_OFFSET
GruntActorShots = QuakeCEdicts+6*QC_ENTITY_STRIDE+IMPACT_EDICT_OFFSET
.else
GruntActorMoves: .res QC_GRUNT_COUNT*2
GruntActorShots: .res QC_GRUNT_COUNT*2
.endif
gr_actor_moves = .loword(GruntActorMoves)
gr_actor_shots = .loword(GruntActorShots)
.assert QC_ENTITY_STRIDE = $200, error, "Grunt counter indexing uses the edict stride"

; Builtins use QuakeC's current self, which may differ from the scheduled
; thinker during nested damage, pain, and death callbacks.
.macro GRUNT_FIELD op, field
        ldy     a:qcg+QC_GLOBAL_SELF
        op      a:qce+field,y
.endmacro

.macro GruntRebaseField field
        lda     a:qce+field,x
        jsr     GruntRebaseTime
        sta     a:qce+field,x
.endmacro
