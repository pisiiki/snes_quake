; Fixed-point interpreter for the hash-bound stock E1M1 callback slice.
; Global values are words. Vectors are three consecutive words. An entity
; handle is its byte offset in the edict array, and fields are byte offsets.
; Globals and edicts use WRAM bank $7f. Hot scratch uses direct page.
QC_PUSHER_FRACTION = 400            ; shared native extension after the stock fields
.include "quake/GameplayAuxSound.i"
.if .defined(PLAYABLE_REGISTER_WALK_TRACE) && .defined(QC_E1M2_GROUP_COUNT) && !.defined(QC_E1M3_GOLD_KEY)
        .include "Data/PlayableE1M2MoverPlanes.i"
.endif

; Poll only at foreground boundaries with a dead accumulator. The long
; refill helper preserves X, Y, DB and processor width across the call.
.macro QC_YIELD_COORDINATE_STREAM
  .ifdef PLAYABLE_COORDINATE_COOP
    .ifdef PLAYABLE_COORDINATE_YIELD_DP
        lda     z:SpriteStreamCoordinateYield
    .else
        lda     f:SpriteStreamCoordinateYield
    .endif
        beq     :+
        lda     f:FX3_R15
        bne     :+
        jsl     SpriteStreamYieldCoordinate
:
  .endif
.endmacro

.macro QC_WORD name
        .ident(.concat(.string(name), "_wram")): .res 2
        name = .loword(*) - 2
.endmacro

.zeropage
QuakeCScratchBegin:
qc_budget: .res 2
qc_pc: .res 2
qc_a: .res 2
qc_b: .res 2
qc_c: .res 2
qc_tmp: .res 2
qc_rhs: .res 2
qc_size: .res 2
qc_descriptor: .res 2
qc_local: .res 2
qc_arg: .res 2
qc_depth: .res 2
qc_stack_top: .res 2
qc_sign: .res 2
qc_factor: .res 2
qc_prod_hi: .res 2
qc_prod_lo: .res 2
.if BSP_PLAYER_WALK
w_limit: .res 2
w_node: .res 2
w_plane: .res 2
w_tag: .res 2
w_axis_a: .res 2
w_axis_b: .res 2
w_dist: .res 2
w_dist_high: .res 2
w_sp: .res 2
w_lo: .res 2
w_hi: .res 2
w_near: .res 2
w_far: .res 2
w_mid: .res 2
w_coeff_a: .res 2
w_coeff_b: .res 2
w_d0: .res 2
w_d0_high: .res 2
w_d1: .res 2
w_d1_high: .res 2
w_eval: .res 2
w_eval_high: .res 2
w_endpoint: .res 2
w_cache_coord_a: .res 2
w_cache_coord_b: .res 2
w_cache_slot: .res 2
w_numerator: .res 2
w_numerator_high: .res 2
w_denominator: .res 2
w_denominator_high: .res 2
w_fraction: .res 2
w_mul_a: .res 2
w_mul_b: .res 2
w_mul_low: .res 2
w_mul_high: .res 2
w_mul_nmi: .res 2
.endif
.ifdef QC_E1M2_DEFER_UPLOAD
QCE1M2SimulationActive: .res 2
.endif
QuakeCScratchEnd:
.if .defined(PLAYABLE_LARGE_DISTANCE_CACHE) || .defined(PLAYABLE_FAST_WALK_PPU_MUL)
w_ppu_latch_nmi: .res 1                 ; Each PPU product clears its own guard.
.endif
.ifdef PLAYABLE_LARGE_DISTANCE_CACHE
w_oblique_front_bound: .res 2
w_oblique_negative_bound: .res 2
.endif

.ifdef PLAYABLE_E1M1_TRACE_LAYOUT
; The indexed mover paths still use the endpoints in bank $7F.
w_biased_from_dp: .res 6
w_biased_to_dp: .res 6
.endif

.segment "EXRAM"
.if .defined(PICKUP_BLEND) || (.defined(QC_LIQUID_ROOT) && .defined(QC_QUEUED_INPUT))
.include "quake/PickupPaletteCommon.i"
.endif
QuakeCRamBegin:
QuakeCGlobals: .res QC_GLOBAL_BYTES
QuakeCEdicts: .res QC_EDICT_BYTES
.ifdef QC_PICKUP_NOTICES
pickup_notice_rows: .res 8
pickup_notice_life: .res 8
pickup_notice_next: .res 2
pickup_notice_revision: .res 2
pickup_bonus_ticks: .res 2
.if .defined(PICKUP_BLEND) || (.defined(QC_LIQUID_ROOT) && .defined(QC_QUEUED_INPUT))
pickup_peak_pending: .res 2
pickup_palette_wanted: .res 2
pickup_palette_ready: .res 2
pickup_palette_shown: .res 2
.endif
.endif
quakec_brush_row: .res 2
quakec_last_tick: .res 2
quakec_contact: .res 2
quakec_fault: .res 2
quakec_fault_opcode: .res 2
quakec_ticks: .res 2
quakec_fx3_ticks: .res 2
quakec_statements: .res 2
quakec_callbacks: .res 2
quakec_sounds: .res 2
quakec_activations: .res 2
quakec_door_blocks: .res 2
quakec_door_pose: .res 2
quakec_button_pose: .res 2
quakec_entrance_pose: .res 4
quakec_entrance_pose0 = quakec_entrance_pose
quakec_entrance_pose1 = quakec_entrance_pose+2
hub_teleports: .res 2
hub_teleport_cooldown: .res 2
.ifdef QC_E1M1_TELEPORT
teleport_departure_q2: .res 6
teleport_hum_volume: .res 2
teleport_hum_playing: .res 2
.endif
.if QC_HUB_ENABLED .or .defined(QC_EPISODE_EXIT_ENABLED)
hub_point: .res 6
QC_WORD hub_sample_tick
QC_WORD hub_extent
.endif
.ifdef QC_HUB_WARNING_COUNT
QC_WORD hub_sample_yaw
hub_warning_ticks: .res 2
hub_warning_gate: .res 2
hub_warning_events: .res 2
hub_warning_cooldowns: .res 2*QC_HUB_WARNING_COUNT
.endif
.ifdef QC_SECRET_COUNT
.ifdef QC_INTERMISSION_COUNT
intermission_phase: .res 2            ; 1 schedules execute_changelevel, 2 shows its results.
intermission_wait: .res 2
intermission_video: .res 2
intermission_walk_cache_mask: .res 2
intermission_subseconds: .res 2
intermission_seconds: .res 2
intermission_camera: .res 2
intermission_kills: .res 2
intermission_monsters: .res 2
intermission_digits: .res 34
intermission_stream_base: .res 2
intermission_cache_end: .res 2
intermission_packet: .res 2
intermission_byte: .res 2
intermission_slot: .res 2
.endif
quakec_found_secrets: .res 2
qc_secret_mask: .res 2
.endif
.ifdef QC_HUB_CLUE_EDICT
hub_clue_cooldown: .res 2
.endif
.ifdef QC_LIQUID_ROOT
QC_WORD walk_water_level
QC_WORD walk_liquid_type
.ifdef PICKUP_BLEND
walk_eye_palette: .res 2
.endif
QC_WORD walk_in_water
QC_WORD walk_slime_damage_next
QC_WORD walk_ledge_ticks
QC_WORD walk_ledge_push_x
QC_WORD walk_ledge_push_y
.endif
.if .defined(QC_HUB_SWIM_OFFSET) || .defined(QC_LIQUID_ROOT)
QC_WORD swim_sound_cooldown
QC_WORD swim_sound_rng
QC_WORD walk_air_ticks
QC_WORD walk_drown_cooldown
QC_WORD walk_drown_damage
.endif
QuakeCShellMask: .res 2
.ifdef QC_CAMPAIGN_ITEMS
quad_msu_pending: .res 2
.endif
.if .defined(QC_NAIL_COUNT) || .defined(QC_CAMPAIGN_ITEMS)
QuakeCNailMask: .res 2
QuakeCSuperShotgunVisible: .res 2
super_shotgun_sample: .res 2
nail_frame:      .res 2
nail_next_frame: .res 2
nail_shots:      .res 2
nail_world_hits: .res 2
nail_actor_hits: .res 2
nail_active:     .res 2
nail_slot:       .res 2
nail_math:       .res 2
nail_math8:      .res 2
nail_remainder:  .res 2
nail_effect_rng: .res 2
nail_impact_sound: .res 2
nail_msu_track:  .res 2
; A six-second lifetime and one shot per tenth of a second bound the live pool.
NAIL_CAPACITY = 60
NAIL_LIFE = 0
NAIL_POS = 2
NAIL_DELTA = 8
NAIL_REMAINDER = 14
NAIL_YAW = 16
NAIL_RECORD = 18
.pushseg
.segment "LORAM"
NailProjectiles: .res NAIL_CAPACITY * NAIL_RECORD
NailProjectilesEnd:
.assert NailProjectilesEnd <= $2000, lderror, "Nail records must fit the low WRAM mirror"
.popseg
nails = $7e0000 + .loword(NailProjectiles)
.endif
.ifdef QC_HEALTH_COUNT
.ifdef QC_ARMOR_COUNT
.ifdef QC_POWERUP_COUNT
QuakeCPowerupMask: .res 2
quad_warn_next: .res 2
quad_warning_pulses: .res 2
suit_warn_next: .res 2
suit_warning_pulses: .res 2
quad_msu_pending: .res 2
.endif
QuakeCArmorMask: .res 2
armor_angle_step: .res 2
armor_yaw: .res 2
.endif
QuakeCHealthMask: .res 2
QuakeCHealthSound: .res 2
.ifdef QC_MEGA_COUNT
QuakeCMegaTimers:  .res QC_MEGA_COUNT * 2
.endif
.endif
.if .defined(QC_MEGA_COUNT) || .defined(QC_CAMPAIGN_ITEMS)
QuakeCItemsHigh:   .res 2              ; Stock item bits 16 through 31.
.endif
QC_WORD qc_phase
.ifdef QC_QUEUED_INPUT
QC_WORD qc_elapsed_units
QC_WORD qc_mover_steps
.endif
QC_WORD qc_collision_tick
QC_WORD qc_hi
QC_WORD qc_lo
QC_WORD qc_entity
QC_WORD qc_axis
QC_WORD qc_fraction
QC_WORD qc_displacement
QC_WORD qc_candidate
QC_WORD qc_pose
QC_WORD qc_travel
QC_WORD qc_interval
QC_WORD qc_max_pose
QC_WORD qc_entrance_index
.ifdef QC_EXIT_MOVER_COUNT
.export quakec_exit_pose_word:far, quakec_exit_targets:far
quakec_exit_pose_word: .res 2
.if QC_EXIT_MOVER_COUNT > 8
.export quakec_exit_pose_word_high:far
quakec_exit_pose_word_high: .res 2
.endif
.ifdef QC_E1M1_PLATFORM_FIRST
.ifdef QC_SECRET_DOOR_COUNT
QC_WORD qc_sd_slot
QC_WORD qc_sd_data
QC_WORD qc_sd_source
QC_WORD qc_sd_hint_wait
QC_WORD qc_t3_state              ; Bits 0/1 are spent triggers, bit 4 means style 32 is dark.
qc_sd_eye: .res 6
qc_sd_state: .res 2*QC_SECRET_DOOR_COUNT
qc_sd_wait: .res 2*QC_SECRET_DOOR_COUNT
qc_sd_travel: .res 2*QC_SECRET_DOOR_COUNT
qc_sd_pose: .res 2*QC_SECRET_DOOR_COUNT
qc_ord_pose: .res 2*QC_ORD_DOOR_COUNT
qc_sd_revision: .res 2
.endif
QC_WORD qc_plat_slot
QC_WORD qc_plat_delta
QC_WORD qc_plat_next
QC_WORD qc_plat_supported
qc_plat_phase_wram:
qc_plat_phase = .loword(*)
        .res 4
qc_plat_wait_wram:
qc_plat_wait = .loword(*)
        .res 4
.ifdef QC_SECRET_DOOR_COUNT
qc_sd_offsets: .res 4*QC_SECRET_DOOR_COUNT
.endif
; E1M1 exit hulls index the live secret axes, discrete movers and platforms.
qc_exit_active_q4: .res 2*QC_E1M1_PLATFORM_FIRST
quakec_platform_q4: .res 4
.assert quakec_platform_q4 = qc_exit_active_q4+QC_E1M1_PLATFORM_FIRST*2, error, "Platforms must follow discrete exit translations"
.ifdef QC_SECRET_DOOR_COUNT
.assert qc_exit_active_q4 = qc_sd_offsets+QC_SECRET_DOOR_COUNT*4, error, "Discrete movers must follow secret axes"
.endif
.ifdef QC_ORD_DOOR_COUNT
; Player and point hull axial selectors follow the two stock platforms.
qc_ord_offsets: .res 2*QC_ORD_DOOR_COUNT
qc_ord_state: .res 2*QC_ORD_DOOR_COUNT
qc_ord_age: .res 2*QC_ORD_DOOR_COUNT
qc_ord_wait: .res 2*QC_ORD_DOOR_COUNT
qc_ord_lights: .res 2
QC_WORD qc_fluorescent_phase
QC_WORD qc_ord_shot_cooldown
QC_WORD qc_ord_hint_wait
QC_WORD qc_ord_interest
QC_WORD qc_ord_in_motion
.endif
.export quakec_platform_q4:far
.endif
.ifdef QC_E1M2_GROUP_COUNT
.export quakec_e1m2_key:far
quakec_e1m2_key: .res 2
qc_e1m2_group_age: .res QC_E1M2_GROUP_COUNT*2
qc_e1m2_group_wait: .res QC_E1M2_GROUP_COUNT*2
QC_WORD qc_e1m2_group_bit
QC_WORD qc_e1m2_group_index
QC_WORD qc_e1m2_mover_end
.ifdef QC_E1M3_GOLD_KEY
.export QuakeCE1M3MoverOffsets:far
QuakeCE1M3MoverOffsets:
qc_e1m3_mover_offsets = .loword(*)
        .res QC_EXIT_MOVER_COUNT*4
QC_WORD qc_e1m3_move_age
QC_WORD qc_e1m3_move_slot
QC_WORD qc_e1m3_move_delta
QC_WORD qc_e1m3_move_next
QC_WORD qc_e1m3_platform_age
QC_WORD qc_e1m3_platform_phase
QC_WORD qc_e1m3_platform_wait
QC_WORD qc_e1m3_stair_button_hit
.else
QC_E1M2_TRANSLATION_CACHE = 1
qc_e1m2_mover_q4 = .loword(*)
        .res QC_EXIT_MOVER_COUNT*2
qc_e1m2_mover_q3 = .loword(*)
        .res QC_EXIT_MOVER_COUNT*2
.endif
.endif
quakec_exit_targets: .res 2
qc_exit_poses = .loword(QuakeCExitPoses)
QuakeCExitPoses:
.if .defined(QC_E1M2_GROUP_COUNT) .and !.defined(QC_E1M3_GOLD_KEY)
        ; The two packed pose words always store sixteen slots.
        .res 16*2
.else
        .res QC_EXIT_MOVER_COUNT*2
.endif
qc_exit_ages_wram:
qc_exit_ages = .loword(*)
        .res QC_EXIT_MOVER_COUNT*2
QC_WORD qc_exit_wait
QC_WORD qc_exit_started
QC_WORD qc_exit_updated
QC_WORD qc_exit_age
qc_exit_eye = .loword(*)
        .res 6
.endif
QCStack: .res 256
.ifdef PLAYABLE_LARGE_DISTANCE_CACHE
; Reserve 1,024 exact distance rows per hull in the combat module.
WALK_DISTANCE_CACHE_MASK = $1FF8
.endif
.ifndef WALK_DISTANCE_CACHE_MASK
WALK_DISTANCE_CACHE_MASK = $0078
.endif
WALK_DISTANCE_CACHE_BYTES = (WALK_DISTANCE_CACHE_MASK + 8) * 2
.if .defined(QC_DOG_FIRST) && .defined(PLAYABLE_LARGE_DISTANCE_CACHE)
POINT_DISTANCE_CACHE_MASK = $0FF8
.else
POINT_DISTANCE_CACHE_MASK = WALK_DISTANCE_CACHE_MASK
.endif
POINT_DISTANCE_CACHE_BYTES = (POINT_DISTANCE_CACHE_MASK + 8) * 2
.include "quake/ShotgunRAM.i"
.include "quake/GruntRAM.i"
.if BSP_PLAYER_WALK
.include "quake/PlayerWalkRAM.i"
.endif
quake_respawn_armed: .res 2
QuakeCRamEnd:
.ifdef QC_SECRET_DOOR_COUNT
; Private to the synchronous walk or shot trace. Excluded from snapshots.
QC_WORD w_secret_tail_state
.endif
.ifdef QC_E1M2_Q4_BYTES
; Rebuilt from authored mover poses, outside the gameplay snapshot.
qc_e1m2_threshold_q4 = .loword(*)
        .res QC_E1M2_Q4_BYTES
qc_e1m2_threshold_q3 = .loword(*)
        .res QC_E1M2_Q3_BYTES
.endif
.ifdef PLAYABLE_FX3_PLANE_DISTANCE
QC_WORD qc_fx3_plane_foreground
.endif
.ifdef PLAYABLE_LARGE_DISTANCE_CACHE
; Reset these with the VM, but keep derived cache bytes out of state snapshots.
shotgun_distance_cache = .loword(*)
        .res POINT_DISTANCE_CACHE_BYTES
w_distance_cache = .loword(*)
        .res WALK_DISTANCE_CACHE_BYTES
POINT_TRACE_CACHE_BYTES = 128 * 32
QC_WORD point_trace_cache_door
QC_WORD point_trace_cache_button
QC_WORD point_trace_cache_entrance0
QC_WORD point_trace_cache_entrance1
point_trace_cache = .loword(*)
        .res POINT_TRACE_CACHE_BYTES
.ifdef PLAYABLE_POINT_MOVING_RANK
POINT_MOVING_CACHE_BYTES = 16 * 8
POINT_MOVING_RANK_BYTES = 128
point_moving_ranks = .loword(*)
        .res POINT_MOVING_RANK_BYTES
.else
POINT_MOVING_CACHE_BYTES = 32 * 8
.endif
point_moving_cache = .loword(*)
        .res POINT_MOVING_CACHE_BYTES
POINT_FRACTION_CACHE_SLOTS = 256
; Parallel word arrays keep each exact cache row at six bytes.
point_fraction_denominators = .loword(*)
        .res 2 * POINT_FRACTION_CACHE_SLOTS
.ifdef QC_EXPLOBOX
; Keep all exact division cache entries. Only the denominator is the validity
; key and needs to be zeroed on restart; its table stays in the VM clear.
PLAYABLE_SPLIT_POINT_FRACTIONS = 1
.pushseg
.segment "LORAM"
point_fraction_numerators: .res 2 * POINT_FRACTION_CACHE_SLOTS
point_fraction_quotients:  .res 2 * POINT_FRACTION_CACHE_SLOTS
.popseg
.else
point_fraction_numerators = .loword(*)
        .res 2 * POINT_FRACTION_CACHE_SLOTS
point_fraction_quotients = .loword(*)
        .res 2 * POINT_FRACTION_CACHE_SLOTS
.endif
.endif
.if .defined(PLAYABLE_PACKET_VIEW_REUSE) && .defined(QC_E1M2_GROUP_COUNT)
; The shadow survives GSU selectors, renderer overlays and scale image changes.
; QuakeCInit clears the validity word on each new level and restart.
.assert QC_ENTRANCE_COUNT = 0, error, "Exit pose words must key every visual slot"
exit_variant_shadow_valid: .res 2
.endif
QuakeCInitRamEnd:
.ifdef PLAYABLE_KNIGHT_POINT_FRACTIONS
; Both software-weapon and OBJ builds have room below the CPU stack.
; A quotient is identified solely by its two exact numeric operands.
.pushseg
.segment "LORAM"
POINT_FRACTION_CACHE_SLOTS = 256
point_fraction_denominators: .res 2 * POINT_FRACTION_CACHE_SLOTS
point_fraction_numerators:   .res 2 * POINT_FRACTION_CACHE_SLOTS
point_fraction_quotients:    .res 2 * POINT_FRACTION_CACHE_SLOTS
.assert * <= $2000, lderror, "Point fractions must fit in the low WRAM mirror"
.popseg
.endif
.if .defined(PLAYABLE_PACKET_VIEW_REUSE) && .defined(QC_E1M2_GROUP_COUNT)
exit_variant_shadow: .res GSU_ENTRANCE_VARIANTS_BYTES
.endif
.ifdef PLAYABLE_POINT_SIGHT_CACHE
SIGHT_TRACE_ROW_BYTES = 32
.assert QC_HAS_PUSHERS = 0, error, "Sight cache needs explicit invalidation for collision pushers"
.assert (!.defined(QC_EXIT_MOVER_COUNT)) || .defined(QC_E1M2_GROUP_COUNT), error, "Sight cache needs explicit invalidation for moving brushes"
.endif

.import __BSP_QUAKEC_LOAD__, __BSP_QUAKEC_RUN__
.assert __BSP_QUAKEC_RUN__ = BSP_CPU_CODE_ADDRESS(__BSP_QUAKEC_LOAD__), lderror, "QuakeC must execute from the S-CPU ROM mirror"
.segment "BSP_QUAKEC"
.if .defined(PLAYABLE_MAP_ID) && .defined(PLAYABLE_WEAPON_OBJ)
.pushseg
.segment "BSP_QUAKEC"
; Forced blank at level boot. Each X2 tile occupies a horizontally mirrored
; pair on the upper row and a vertically mirrored pair on the following row.
BuildPlayableTextureTilemap:
        RW_forced a8i16
        lda     #$80
        sta     VMAINC
        ldx     #VRAM_TEXTURE_TILEMAP/2
        stx     VMADDL
        RW      a16
        lda     #15
@Row:   tax
        ldy     #16
@Pair:  sta     VMDATAL
        eor     #$4000
        sta     VMDATAL
        eor     #$4000
        dec
        dey
        bne     @Pair
        txa
        eor     #$8000
        bmi     @Row
        clc
        adc     #16
        cmp     #14*16+15
        bne     @Row
        lda     #$4000
        ldx     #4*32
@Fill:  sta     VMDATAL
        dex
        bne     @Fill
        RW      a8
        rtl
.popseg
.endif

QuakeCProgramBegin:
.pushseg
.segment "BSP_QUAKEC_BYTECODE"
QuakeCCode:
.ifdef PLAYABLE_E1M1_LINKED_QC_CODE
        .include "Data/PlayableQuakeCCode.i"
        .assert * - QuakeCCode = QC_CODE_BYTES, error, "Linked QuakeC records changed size"
.else
        .incbin "Data/QuakeBSPQuakeCCode.bin"
.endif
.if .defined(QC_DOG_FIRST) || .defined(QC_KNIGHT_ROSTER)
.segment "BSP_QUAKEC_INIT"
.endif
.if .defined(QC_SECRET_DOOR_COUNT) || .defined(QC_CAMPAIGN_ITEMS)
QuakeCSparseInitial:
        .incbin "Data/QuakeBSPQuakeCInitSparse.bin"
QuakeCInitEdicts = * - QC_GRUNT
        .incbin "Data/QuakeBSPQuakeCEdicts.bin", QC_GRUNT
.else
QuakeCInitGlobals:
        .incbin "Data/QuakeBSPQuakeCGlobals.bin"
QuakeCInitEdicts:
        .incbin "Data/QuakeBSPQuakeCEdicts.bin"
.endif
QuakeCInitGruntFields:
        .incbin "Data/QuakeBSPQuakeCGruntFields.bin"
.popseg
.pushseg
.if .defined(QC_DOG_FIRST) || .defined(QC_KNIGHT_ROSTER)
.segment "BSP_QUAKEC_FUNCTIONS"
.endif
QuakeCFunctions:
.ifdef PLAYABLE_E1M1_LINKED_BUILTINS
        .include "Data/PlayableQuakeCBuiltins.i"
.elseif .defined(PLAYABLE_INDEXED_QUAKEC_FUNCTIONS)
        .incbin "Data/PlayableQuakeCFunctions.bin"
.else
        .incbin "Data/QuakeBSPQuakeCFunctions.bin"
.endif
.popseg

; Use bank-relative WRAM addresses while DB=$7f. The code and its dispatch
; table share a ROM bank. Never change direct page or touch the CPU multiplier.
qcg = .loword(QuakeCGlobals)
qce = .loword(QuakeCEdicts)
qcs = .loword(QCStack)
qcb = .loword(QuakeCRamBegin)
qcn = QuakeCInitRamEnd - QuakeCRamBegin
.assert (qcn > 0) && ((qcn & 1) = 0), error, "QuakeC RAM clear requires a nonempty word count"
.ifdef PLAYABLE_E1M1_WIDE_Q3
.include "quake/PointWideFraction.s"
.endif

QuakeCInit:
        RW_forced a16i16
.ifdef QC_QUEUED_INPUT
        lda     f:quake_restart_pending
        bne     :+
        jsl     GameplayInputReset
:
.endif
        phb
        pea     $7f7f
        plb
        plb
        ldx     #qcn
@Zero:
        dex
        dex
        stz     a:qcb,x                  ; STZ preserves Z, even above $7FFF.
        bne     @Zero
        ldx     #QuakeCScratchEnd-QuakeCScratchBegin-2
@ZeroScratch:
        stz     z:QuakeCScratchBegin,x
        dex
        dex
        bpl     @ZeroScratch
.ifdef PLAYABLE_E1M1_WIDE_Q3
        jsl     PointWideFractionInit
.endif
.if .defined(QC_INTERMISSION_COUNT) && .defined(PLAYABLE_LARGE_DISTANCE_CACHE)
        lda     #WALK_DISTANCE_CACHE_MASK
        sta     f:intermission_walk_cache_mask
.endif
.ifdef PLAYABLE_KNIGHT_POINT_FRACTIONS
        ; A zero denominator misses every admissible division.
        lda     #0
        ldx     #(POINT_FRACTION_CACHE_SLOTS-1)*2
@ClearPointFractions:
        sta     f:point_fraction_denominators,x
        dex
        dex
        bpl     @ClearPointFractions
.endif
.ifdef PLAYABLE_POINT_SIGHT_CACHE
        jsr     ShotHull::WalkSightCacheInvalidate
.endif
.ifdef QC_E1M1_PLATFORM_FIRST
        jsr     QCExitInitActive
        lda     f:QCPlatformBottom
        sta     f:quakec_platform_q4
        lda     f:QCPlatformBottom+2
        sta     f:quakec_platform_q4+2
.ifdef QC_ORD_DOOR_COUNT
        ldx     #2*(QC_ORD_DOOR_COUNT-1)
@DoorRest:
        lda     f:QCOrdRest,x
        sta     f:qc_ord_offsets,x
        dex
        dex
        bpl     @DoorRest
.endif
.ifdef PLAYABLE_POINT_MOVING_RANK
        jsl     ShotRefreshMovingRanks
.endif
.endif
.ifdef QC_E1M3_GOLD_KEY
        jsr     QCE1M3InitMovers
.elseif .defined(QC_E1M2_TRANSLATION_CACHE)
        ldx     #(QC_EXIT_MOVER_COUNT-1)*2
@MoverOffsets:
        ldy     #0
        jsr     QCE1M2StoreMoverOffset
        dex
        dex
        bpl     @MoverOffsets
.endif
.if .defined(QC_SECRET_DOOR_COUNT) || .defined(QC_CAMPAIGN_ITEMS)
        ldx     #0
@Sparse:
        lda     f:QuakeCSparseInitial,x
        bmi     @Initialized
        tay
        lda     f:QuakeCSparseInitial+2,x
        sta     a:qcg,y
        txa
        clc
        adc     #4
        tax
        bra     @Sparse
@Initialized:
.else
        ldx     #QC_GLOBAL_BYTES-2
@Globals:
        lda     f:QuakeCInitGlobals,x
        sta     a:qcg,x
        dex
        dex
        bpl     @Globals
.endif
        ; StartFrame in stock QuakeC copies the skill cvar into this global.
        lda     f:quake_skill_selected
        and     #3
        sta     f:quake_skill_active
        .repeat 6
        asl
        .endrepeat
        sta     a:qcg+QC_GLOBAL_SKILL
        lda     f:quake_skill_active
        asl
        tax
        lda     f:QuakeSkillSpawnExclusions,x
        sta     a:gr_skill_mask
.if (.defined(QC_SECRET_DOOR_COUNT) || .defined(QC_CAMPAIGN_ITEMS)) = 0
.ifdef QC_HUB_CLUE_EDICT
        ldx     #QC_EDICT_BYTES-2       ; START also initializes the spare clue actor.
.else
        ldx     #QC_GRUNT-2
.endif
@Edicts:
        lda     f:QuakeCInitEdicts,x
        sta     a:qce,x
        dex
        dex
        bpl     @Edicts
.endif
        jsr     GruntInitRoster
.if QC_ENTRANCE_INIT_BYTES > 0
        ldx     #0
@EntranceEdicts:
        lda     f:QuakeCInitEdicts+QC_ENTRANCE_INIT_OFFSET,x
        sta     a:qce+QC_ENTRANCE_INIT_TARGET,x
        inx
        inx
        cpx     #QC_ENTRANCE_INIT_BYTES
        bcc     @EntranceEdicts
.endif
        lda     #(1 << QC_SHELL_COUNT)-1
        sta     f:QuakeCShellMask
.if .defined(QC_NAIL_COUNT) || .defined(QC_CAMPAIGN_ITEMS)
.ifdef QC_NAIL_COUNT
        lda     #(1 << (QC_NAIL_COUNT+1))-1
        sta     f:QuakeCNailMask
        lda     #1
        sta     f:QuakeCSuperShotgunVisible
.endif
        stz     a:.loword(super_shotgun_sample)
        stz     a:.loword(nail_frame)
        stz     a:.loword(nail_next_frame)
        stz     a:.loword(nail_shots)
        stz     a:.loword(nail_active)
        stz     a:.loword(nail_world_hits)
        stz     a:.loword(nail_actor_hits)
        stz     a:.loword(nail_impact_sound)
        stz     a:.loword(nail_msu_track)
        lda     #$4a3d
        sta     a:.loword(nail_effect_rng)
        ldx     #0
:       lda     #0
        sta     f:nails+NAIL_LIFE,x
        txa
        clc
        adc     #NAIL_RECORD
        tax
        cpx     #NAIL_RECORD*NAIL_CAPACITY
        bcc     :-
.endif
.ifdef QC_HEALTH_COUNT
.ifdef QC_ARMOR_COUNT
        lda     #(1 << QC_ARMOR_COUNT)-1
        sta     f:QuakeCArmorMask
.ifdef QC_POWERUP_COUNT
        lda     #(1 << QC_POWERUP_COUNT)-1
        sta     f:QuakeCPowerupMask
        stz     a:.loword(quad_warn_next)
        stz     a:.loword(quad_warning_pulses)
        lda     #.loword(-1)
        sta     a:walk_liquid_type
        stz     a:.loword(suit_warn_next)
        stz     a:.loword(suit_warning_pulses)
        stz     a:.loword(quad_msu_pending)
  .ifdef QC_E1M1_TELEPORT
        stz     a:.loword(teleport_hum_volume)
        stz     a:.loword(teleport_hum_playing)
  .endif
.endif
        stz     a:.loword(armor_angle_step)
        stz     a:.loword(armor_yaw)
.endif
        lda     #(1 << QC_HEALTH_COUNT)-1
        sta     f:QuakeCHealthMask
.ifdef QC_MEGA_COUNT
        stz     a:.loword(QuakeCItemsHigh)
        .repeat QC_MEGA_COUNT, I
        stz     a:.loword(QuakeCMegaTimers)+2*I
        .endrepeat
.endif
        lda     #100*64                 ; Stock single-player spawn maximum.
        sta     a:qce+QC_ENTITY_STRIDE+QC_FIELD_MAX_HEALTH
.endif
        lda     #QC_GRUNT_START_TIME
        sta     a:grunt_clock
.ifdef QC_FLUORESCENT_STYLE
        lda     #QC_GRUNT_START_TIME .mod 160
        sta     a:qc_fluorescent_phase
.endif
        lda     #QC_GRUNT_START_YAW
        sta     a:grunt_yaw
        plb
        rtl

QuakeSkillSpawnExclusions:
        .word   $0100, $0200, $0400, $0400

; Each outer callback owns the statement budget. Nested calls share it.
.ifdef PLAYABLE_E1M1_STATEMENT_BATCH
.define QuakeCInvokeOuter QuakeCInvokeCounted
QuakeCInvokeCounted:
        pei     (qc_budget)
        jsr     QuakeCInvoke
        pla
        sec
        sbc     z:qc_budget
        clc
        adc     a:.loword(quakec_statements)
        sta     a:.loword(quakec_statements)
        rts
.else
.define QuakeCInvokeOuter QuakeCInvoke
.endif

QuakeCInvoke:
        cmp     #QC_FUNCTION_COUNT
        bcc     :+
        jmp     QuakeCTrap
:       asl
.ifdef PLAYABLE_INDEXED_QUAKEC_FUNCTIONS
        tax
        lda     f:QuakeCFunctions,x
.else
        asl
        asl
        asl
.endif
        tax
        lda     f:QuakeCFunctions,x
.ifdef PLAYABLE_E1M1_LINKED_BUILTINS
        sec                             ; Match CMP #0 on entry to a script.
        bpl     @Function
        cmp     #$8000
        bne     :+
        jmp     QuakeCTrap
:       ; The descriptor stores the validated near destination minus one.
        ; RTS consumes our synthetic return and leaves the original caller on
        ; the hardware stack. Restore A, X (the descriptor), and CMP flags.
        lda     f:QuakeCFunctions+2,x
        pha
        lda     f:QuakeCFunctions,x
        cmp     f:QuakeCFunctions,x
        rts
.else
        cmp     #$8000                  ; -1 is the stock makevectors builtin.
        bne     :+
        jmp     QuakeCTrap
:       cmp     #0                      ; Classify the entry, not the sentinel comparison.
        bpl     @Function
        jmp     QuakeCBuiltin
.endif
@Function:
        pha                             ; Entry PC.
        stx     z:qc_descriptor
        lda     f:QuakeCFunctions+2,x
        sta     z:qc_local
        pha                             ; First local byte.
        lda     f:QuakeCFunctions+4,x
        sta     z:qc_size
        pha                             ; Saved local byte count.
        clc
        adc     z:qc_stack_top
        cmp     #257
        bcc     :+
        jmp     @StackFault
:
.ifdef PLAYABLE_E1M1_LOCAL_COPY_END
        ; Keep the checked end of the frame for the local copy loop.
        sta     z:qc_arg
.endif
        lda     z:qc_depth
.ifdef QC_EXPLOBOX
        ; FireBullets can kill a box whose radius kills and gibs a monster.
        cmp     #20
.else
        cmp     #12
.endif
        bcc     :+
        jmp     @StackFault
:
        inc     z:qc_depth
        ldx     z:qc_local
        ldy     z:qc_stack_top
.ifdef PLAYABLE_E1M1_LOCAL_COPY_END
        cpy     z:qc_arg
.else
        lda     z:qc_size
.endif
        beq     @Saved
.ifdef PLAYABLE_E1M1_BOUNDED_QC_LOCALS
        jsr     QCSaveLocalFrame
.else
@Save:
        lda     a:qcg,x
        sta     a:qcs,y
        inx
        inx
        iny
        iny
.ifdef PLAYABLE_E1M1_LOCAL_COPY_END
        cpy     z:qc_arg
.else
        dec     z:qc_size
        dec     z:qc_size
.endif
        bne     @Save
.endif
@Saved:
.ifdef PLAYABLE_E1M1_LOCAL_COPY_END
        clc                             ; Preserve the accepted depth check's carry.
.endif
        sty     z:qc_stack_top
        ldx     z:qc_descriptor
        lda     f:QuakeCFunctions+6,x
.ifndef PLAYABLE_E1M1_SINGLE_SCALAR_ARG
        and     #$ff
.endif
        sta     z:qc_size
        beq     @Ready
.ifdef PLAYABLE_E1M1_SINGLE_SCALAR_ARG
        cmp     #1
        bne     @OtherArguments
        ; Every one-argument script in this linked module takes one word.
        tax
        inx
        ldy     z:qc_local
        lda     a:qcg+8
        sta     a:qcg,y
        iny
        iny
        inc     z:qc_descriptor
        stz     z:qc_tmp
        ; X is two and the successful scalar comparison left carry set.
        txa
        adc     #3
        sta     z:qc_arg
        dec     z:qc_size
        bra     @Ready
@OtherArguments:
.endif
        stz     z:qc_arg
        ldy     z:qc_local
@Argument:
        ldx     z:qc_descriptor
        lda     f:QuakeCFunctions+8,x
        and     #$ff
        sta     z:qc_tmp
        ldx     z:qc_arg
@Copy:
        lda     a:qcg+8,x
        sta     a:qcg,y
        inx
        inx
        iny
        iny
        dec     z:qc_tmp
        dec     z:qc_tmp
        bne     @Copy
        inc     z:qc_descriptor
        lda     z:qc_arg
        clc
        adc     #6
        sta     z:qc_arg
        dec     z:qc_size
        bne     @Argument
@Ready:
        QC_YIELD_COORDINATE_STREAM
        lda     5,s
        sta     z:qc_pc
        jsr     QuakeCDispatchChecked
        pla
        sta     z:qc_size
        lda     z:qc_stack_top
.ifdef PLAYABLE_E1M1_LOCAL_COPY_END
        sta     z:qc_arg
.endif
        sec
        sbc     z:qc_size
        sta     z:qc_stack_top
        tay
        pla
        tax
.ifdef PLAYABLE_E1M1_LOCAL_COPY_END
        cpy     z:qc_arg
.else
        lda     z:qc_size
.endif
        beq     @Restored
.ifdef PLAYABLE_E1M1_BOUNDED_QC_LOCALS
        jsr     QCRestoreLocalFrame
.else
@Restore:
        lda     a:qcs,y
        sta     a:qcg,x
        inx
        inx
        iny
        iny
.ifdef PLAYABLE_E1M1_LOCAL_COPY_END
        cpy     z:qc_arg
.else
        dec     z:qc_size
        dec     z:qc_size
.endif
        bne     @Restore
.endif
@Restored:
.ifdef PLAYABLE_E1M1_LOCAL_COPY_END
        stz     z:qc_size
.endif
        pla
        dec     z:qc_depth
        rts
@StackFault:
        pla
        pla
        pla
        jmp     QuakeCTrap

.ifdef PLAYABLE_E1M1_BOUNDED_QC_LOCALS
        .include "quake/QuakeCLocalFrame.i"
.endif

; Traps return to the enclosing call. Only call entry and return need
; to check for an existing fault before continuing with another statement.
QuakeCDispatchChecked:
        lda     a:.loword(quakec_fault)
        bne     QuakeCDispatchDone
.ifdef PLAYABLE_E1M1_LINKED_QC_CODE
        ; Check function entry and the saved caller PC before resuming.
        ; A rejected fetch never consumes a statement from the budget.
        ldx     z:qc_pc
        cpx     #QC_CODE_BYTES
        bcs     QuakeCInvalidEntry
.endif
QuakeCDispatch:
        dec     z:qc_budget
        beq     QCNoOpcode
        ldx     z:qc_pc
.ifndef PLAYABLE_E1M1_LINKED_QC_CODE
        cpx     #QC_CODE_BYTES
        bcs     QCNoOpcode
.endif
.ifdef PLAYABLE_E1M1_LAZY_QC_OPERANDS
  .ifndef PLAYABLE_E1M1_LINKED_QC_CODE
        ; The opcode-table dispatch overwrites X with the opcode index.
        txy
  .endif
.else
        lda     f:QuakeCCode+2,x
        sta     z:qc_a
        lda     f:QuakeCCode+4,x
        sta     z:qc_b
        lda     f:QuakeCCode+6,x
        sta     z:qc_c
.endif
        txa
        ; The linker validates every branch and nonterminal successor.
        clc
        adc     #8
        sta     z:qc_pc
.ifdef PLAYABLE_E1M1_VM_PBR_DISPATCH
        ; Indexed indirect JMP fetches the checked statement's handler through PBR.
        .assert ^QuakeCCode = ^QuakeCDispatch, lderror, "Linked QuakeC dispatch requires a shared ROM bank"
        .assert ^(QuakeCCode + QC_CODE_BYTES - 1) = ^QuakeCDispatch, lderror, "Linked QuakeC records cross a ROM bank"
        jmp     (.loword(QuakeCCode),x)
.elseif .defined(PLAYABLE_E1M1_LINKED_QC_CODE)
        lda     f:QuakeCCode,x
        sta     z:qc_descriptor
        jmp     (qc_descriptor)
.else
        lda     f:QuakeCCode,x
.ifdef QC_GIB_FIRST_ROW
        cmp     #140
.elseif .defined(QC_ARMOR_COUNT) || .defined(QC_CAMPAIGN_ITEMS)
        cmp     #138
.else
        cmp     #136
.endif
        bcs     QCBadFetch
.ifndef PLAYABLE_E1M1_STATEMENT_BATCH
        inc     a:.loword(quakec_statements)
.endif
        tax
        jmp     (.loword(QuakeCDispatchTable),x)
.endif
QCNoOpcode:
.ifdef PLAYABLE_E1M1_LINKED_QC_CODE
        inc     z:qc_budget             ; Undo only a budget decrement that ran.
QuakeCInvalidEntry:
        lda     #0
.else
        lda     #0
QCBadFetch:
  .ifdef PLAYABLE_E1M1_STATEMENT_BATCH
        inc     z:qc_budget             ; A rejected fetch did not run a statement.
  .endif
.endif
        jmp     QuakeCTrap
QuakeCDispatchDone:
        rts

.ifdef PLAYABLE_E1M1_LINKED_QC_CODE
.assert PLAYABLE_E1M1_STATEMENT_BATCH = 1, error, "Linked dispatch requires batched VM statement accounting"
QCOpUnrecorded:
        ; The original $FFFF record advances qc_pc without charging a statement.
        inc     z:qc_budget
        lda     #$ffff
        bra     QuakeCTrap
QCOpTrap16:
        lda     #16*2
        bra     QuakeCTrap
QCOpTrap45:
        lda     #45*2
.endif
QuakeCTrap:
        sta     f:quakec_fault_opcode
        lda     z:qc_pc
        inc
        sta     f:quakec_fault
        rts

; Linked dispatch leaves X at the checked statement. Opcode-table dispatch
; keeps that offset in Y. Save the result index before reusing either register.
.macro QC_LOAD_A_X save_result
.ifdef PLAYABLE_E1M1_LAZY_QC_OPERANDS
  .ifndef PLAYABLE_E1M1_LINKED_QC_CODE
        tyx
  .endif
  .if save_result
        lda     f:QuakeCCode+6,x
        sta     z:qc_c
  .endif
        lda     f:QuakeCCode+2,x
        tax
.else
        ldx     z:qc_a
.endif
.endmacro

.macro QC_LOAD_AB_XY save_result
.ifdef PLAYABLE_E1M1_LAZY_QC_OPERANDS
  .ifndef PLAYABLE_E1M1_LINKED_QC_CODE
        tyx
  .endif
  .if save_result
        lda     f:QuakeCCode+6,x
        sta     z:qc_c
  .endif
        lda     f:QuakeCCode+4,x
        tay
        lda     f:QuakeCCode+2,x
        tax
.else
        ldx     z:qc_a
        ldy     z:qc_b
.endif
.endmacro

.macro QC_BRANCH_TO_RESULT
.ifdef PLAYABLE_E1M1_LAZY_QC_OPERANDS
        jmp     QCStoreResult
.else
        bra     QCStoreResult
.endif
.endmacro

.ifdef PLAYABLE_E1M1_LAZY_QC_OPERANDS
; Dot and scale advance through scratch operand offsets. The gib hook also
; uses scratch and consumes the raw statement before it can clobber Y.
QCReadOperands:
        QC_LOAD_AB_XY 1
        stx     z:qc_a
        sty     z:qc_b
        rts
.endif

.macro QC_OPCODE token, handler
.ifdef PLAYABLE_E1M1_LINKED_QC_CODE
    .if token = 16
        .ident(.sprintf("QCLinkedOp%d", token)) = QCOpTrap16
    .elseif token = 45
        .ident(.sprintf("QCLinkedOp%d", token)) = QCOpTrap45
    .else
        .ident(.sprintf("QCLinkedOp%d", token)) = handler
    .endif
    .assert ^.ident(.sprintf("QCLinkedOp%d", token)) = ^QuakeCDispatch, lderror, "Linked QuakeC handler escaped dispatch bank"
.else
        .word   .loword(handler)
.endif
.endmacro

.macro QC_OPCODE4 token, op0, op1, op2, op3
        QC_OPCODE token, op0
        QC_OPCODE token+1, op1
        QC_OPCODE token+2, op2
        QC_OPCODE token+3, op3
.endmacro

.ifndef PLAYABLE_E1M1_LINKED_QC_CODE
QuakeCDispatchTable:
.else
.assert ^QCOpUnrecorded = ^QuakeCDispatch, lderror, "QuakeC placeholder escaped dispatch bank"
.endif
        QC_OPCODE4 0, QCOpReturn, QCOpMul, QCOpDot, QCOpScaleLeft
        QC_OPCODE4 4, QCOpScale, QCOpDivide, QCOpAdd, QCOpAddVector
        QC_OPCODE4 8, QCOpSub, QCOpSubVector, QCOpEqual, QCOpEqualVector
        QC_OPCODE4 12, QCOpEqual, QCOpEqual, QCOpEqual, QCOpNotEqual
        QC_OPCODE4 16, QuakeCTrap, QCOpNotEqual, QCOpNotEqual, QCOpNotEqual
        QC_OPCODE4 20, QCOpLessEqual, QCOpGreaterEqual, QCOpLess, QCOpGreater
        QC_OPCODE4 24, QCOpLoad, QCOpLoadVector, QCOpLoad, QCOpLoad
        QC_OPCODE4 28, QCOpLoad, QCOpLoad, QCOpAddress, QCOpStore
        QC_OPCODE4 32, QCOpStoreVector, QCOpStore, QCOpStore, QCOpStore
        QC_OPCODE4 36, QCOpStore, QCOpStorePointer, QCOpStorePointerVector, QCOpStorePointer
        QC_OPCODE4 40, QCOpStorePointer, QCOpStorePointer, QCOpStorePointer, QCOpReturn
        QC_OPCODE4 44, QCOpNot, QuakeCTrap, QCOpNot, QCOpNot
        QC_OPCODE4 48, QCOpNot, QCOpIf, QCOpIfNot, QCOpCall
        QC_OPCODE4 52, QCOpCall, QCOpCall, QCOpCall, QCOpCall
        QC_OPCODE4 56, QCOpCall, QCOpCall, QCOpCall, QCOpCall
        QC_OPCODE4 60, QCOpState, QCOpGoto, QCOpAnd, QCOpOr
        QC_OPCODE 64, QCOpBitAnd
        QC_OPCODE 65, QCOpBitOr
        QC_OPCODE 66, QCOpInventoryAnd
        QC_OPCODE 67, QCOpInventoryOr

.if .defined(QC_ARMOR_COUNT) || .defined(QC_CAMPAIGN_ITEMS)
        QC_OPCODE 68, QCOpArmorSave
.ifdef QC_GIB_FIRST_ROW
        QC_OPCODE 69, QCOpGibReturn
QCOpGibReturn:
.ifdef PLAYABLE_E1M1_LAZY_QC_OPERANDS
        jsr     QCReadOperands
.endif
        jsr     GibCapture
.ifdef PLAYABLE_E1M1_LAZY_QC_OPERANDS
        ldx     z:qc_a
        bra     QCOpReturnCopy
.else
        bra     QCOpReturn
.endif
.endif
QCOpArmorSave:
        jsr     QCOperands
        tax
        lda     a:qcg,y
        jsl     ArmorSaved
        jmp     QCStoreResult
.endif

QCOpReturn:
        QC_LOAD_A_X 0
QCOpReturnCopy:
        lda     a:qcg,x
        sta     a:qcg+2
        lda     a:qcg+2,x
        sta     a:qcg+4
        lda     a:qcg+4,x
        sta     a:qcg+6
        rts
QCOpCall:
        lda     z:qc_pc
        pha
        QC_LOAD_A_X 0
        lda     a:qcg,x
        jsr     QuakeCInvoke
        pla
        sta     z:qc_pc
        jmp     QuakeCDispatchChecked
QCOpIf:
.ifdef PLAYABLE_E1M1_LINKED_QC_CODE
        txy                             ; A taken branch needs the raw B operand.
.endif
        QC_LOAD_A_X 0
        lda     a:qcg,x
        bne     QCBranch
        jmp     QuakeCDispatch
QCOpIfNot:
.ifdef PLAYABLE_E1M1_LINKED_QC_CODE
        txy
.endif
        QC_LOAD_A_X 0
        lda     a:qcg,x
        beq     QCBranch
        jmp     QuakeCDispatch
QCOpGoto:
.ifdef PLAYABLE_E1M1_LAZY_QC_OPERANDS
  .ifndef PLAYABLE_E1M1_LINKED_QC_CODE
        tyx
  .endif
        lda     f:QuakeCCode+2,x
.else
        lda     z:qc_a
.endif
        bra     QCJump
QCBranch:
.ifdef PLAYABLE_E1M1_LAZY_QC_OPERANDS
        tyx
        lda     f:QuakeCCode+4,x
.else
        lda     z:qc_b
.endif
QCJump:
        sta     z:qc_pc
        jmp     QuakeCDispatch

QCOpLoad:
        jsr     QCEntityAddress
        lda     a:qce,x
        jmp     QCStoreResult
QCOpLoadVector:
        jsr     QCEntityAddress
        ldy     z:qc_c
QCLoadFieldVectorXY:
        lda     a:qce,x
        sta     a:qcg,y
        lda     a:qce+2,x
        sta     a:qcg+2,y
        lda     a:qce+4,x
        sta     a:qcg+4,y
        jmp     QuakeCDispatch
QCOpAddress:
        jsr     QCEntityAddress
        txa
        QC_BRANCH_TO_RESULT
QCEntityAddress:
.ifdef PLAYABLE_E1M1_LINKED_QC_FIELDS
.assert PLAYABLE_E1M1_LINKED_QC_CODE = 1, error, "Literal fields require the linked bytecode record"
        ; X still holds the linked statement offset and B is the field value.
        lda     f:QuakeCCode+6,x
        sta     z:qc_c
        lda     f:QuakeCCode+2,x
        tay
        lda     a:qcg,y
        clc
        adc     f:QuakeCCode+4,x
.else
        QC_LOAD_AB_XY 1
        lda     a:qcg,x
        clc
        adc     a:qcg,y
.endif
        tax
        rts
QCOpStore:
        QC_LOAD_AB_XY 0
        lda     a:qcg,x
        sta     a:qcg,y
        jmp     QuakeCDispatch
QCOpStoreVector:
.ifdef PLAYABLE_E1M1_LINKED_QC_CODE
        lda     f:QuakeCCode+4,x
        tay
QCStoreVectorSource:
        lda     f:QuakeCCode+2,x
        tax
.else
        QC_LOAD_AB_XY 0
.endif
        lda     a:qcg,x
        sta     a:qcg,y
        lda     a:qcg+2,x
        sta     a:qcg+2,y
        lda     a:qcg+4,x
        sta     a:qcg+4,y
        jmp     QuakeCDispatch
.ifdef PLAYABLE_E1M1_LINKED_QC_CODE
        .include "quake/QuakeCLinkedOperands.i"
        .include "quake/QuakeCLinkedCompare.i"
.endif

QCOpStorePointer:
.ifdef PLAYABLE_E1M1_LAZY_QC_OPERANDS
        QC_LOAD_AB_XY 0
        lda     a:qcg,y
        tay
.else
        ldx     z:qc_b
        lda     a:qcg,x
        tay
        ldx     z:qc_a
.endif
        lda     a:qcg,x
        sta     a:qce,y
        jmp     QuakeCDispatch
QCOpStorePointerVector:
.ifdef PLAYABLE_E1M1_LAZY_QC_OPERANDS
        QC_LOAD_AB_XY 0
        lda     a:qcg,y
        tay
.else
        ldx     z:qc_b
        lda     a:qcg,x
        tay
        ldx     z:qc_a
.endif
        lda     a:qcg,x
        sta     a:qce,y
        lda     a:qcg+2,x
        sta     a:qce+2,y
        lda     a:qcg+4,x
        sta     a:qce+4,y
        jmp     QuakeCDispatch

QCStoreResult:
        ldy     z:qc_c
        sta     a:qcg,y
        jmp     QuakeCDispatch
QCOpEqualVector:
        QC_LOAD_AB_XY 1
        lda     a:qcg+4,x
        cmp     a:qcg+4,y
        bne     QCFalse
        lda     a:qcg+2,x
        cmp     a:qcg+2,y
        bne     QCFalse
.ifdef PLAYABLE_E1M1_LAZY_QC_OPERANDS
        lda     a:qcg,x
        cmp     a:qcg,y
        bra     QCEqualResult
.endif
QCOpEqual:
        jsr     QCCompare
QCEqualResult:
        beq     QCTrue
QCFalse:
        lda     #0
        bra     QCStoreResult
QCTrue:
        lda     #64
        bra     QCStoreResult
QCOpNotEqual:
        jsr     QCCompare
        bne     QCTrue
        bra     QCFalse
QCOpLess:
        jsr     QCSignedCompare
        bcc     QCTrue
        bra     QCFalse
QCOpGreaterEqual:
        jsr     QCSignedCompare
        bcs     QCTrue
        bra     QCFalse
QCOpNot:
        QC_LOAD_A_X 1
        lda     a:qcg,x
        beq     QCTrue
        bra     QCFalse
QCOpAnd:
.ifdef PLAYABLE_E1M1_LAZY_QC_OPERANDS
        jsr     QCOperands
        beq     QCFalse
        lda     a:qcg,y
.else
        ldx     z:qc_a
        lda     a:qcg,x
        beq     QCFalse
        ldx     z:qc_b
        lda     a:qcg,x
.endif
        bne     QCTrue
        bra     QCFalse
QCOpOr:
        jsr     QCOperands
        ora     a:qcg,y
        bne     QCTrue
        bra     QCFalse
QCOpBitAnd:
        jsr     QCOperands
        and     a:qcg,y
        and     #$ffc0
        QC_BRANCH_TO_RESULT
QCOpAdd:
        jsr     QCOperands
        clc
        adc     a:qcg,y
        QC_BRANCH_TO_RESULT
QCOpSubVector:
        jsr     QCOperands
.ifdef PLAYABLE_E1M1_LAZY_QC_OPERANDS
        sty     z:qc_b
.endif
        sec
        sbc     a:qcg,y
        ldy     z:qc_c
        sta     a:qcg,y
        ldy     z:qc_b
        lda     a:qcg+2,x
        sec
        sbc     a:qcg+2,y
        ldy     z:qc_c
        sta     a:qcg+2,y
        ldy     z:qc_b
        lda     a:qcg+4,x
        sec
        sbc     a:qcg+4,y
        ldy     z:qc_c
        sta     a:qcg+4,y
        jmp     QuakeCDispatch
QCCompare:
        jsr     QCOperands
        cmp     a:qcg,y
        rts
QCSignedCompare:
        jsr     QCOperands
        eor     #$8000
        sta     z:qc_tmp
        lda     a:qcg,y
        eor     #$8000
        sta     z:qc_rhs
        lda     z:qc_tmp
        cmp     z:qc_rhs
        rts
QCOperands:
        QC_LOAD_AB_XY 1
        lda     a:qcg,x
        rts

QCOpDivide:
.ifdef PLAYABLE_E1M1_LAZY_QC_OPERANDS
        QC_LOAD_AB_XY 1
        lda     a:qcg,y
.else
        ldx     z:qc_b
        lda     a:qcg,x
.endif
        bne     :+
        jmp     QuakeCTrap
:       sta     z:qc_rhs
.ifndef PLAYABLE_E1M1_LAZY_QC_OPERANDS
        ldx     z:qc_a
.endif
        lda     a:qcg,x
        jsr     QCAbsOperands
        stz     a:qc_hi
        .repeat 6
        asl     a:qc_lo
        rol     a:qc_hi
        .endrepeat
        ldx     #16
@Divide:
        asl     a:qc_lo
        rol     a:qc_hi
        bcs     @Subtract
        lda     a:qc_hi
        cmp     z:qc_factor
        bcc     @Next
@Subtract:
        lda     a:qc_hi
        sec
        sbc     z:qc_factor
        sta     a:qc_hi
        inc     a:qc_lo
@Next:
        dex
        bne     @Divide
        lda     a:qc_hi
        asl
        cmp     z:qc_factor
        bcc     :+
        inc     a:qc_lo
:       lda     a:qc_lo
        jsr     QCApplySign
        jmp     QCStoreResult

QCOpScaleLeft:
.ifdef PLAYABLE_E1M1_LAZY_QC_OPERANDS
        jsr     QCReadOperands
.endif
        ldx     z:qc_a
        ldy     z:qc_b
        stx     z:qc_b
        sty     z:qc_a
.ifdef PLAYABLE_E1M1_LAZY_QC_OPERANDS
        bra     QCScaleDecoded
.endif
QCOpScale:
.ifdef PLAYABLE_E1M1_LAZY_QC_OPERANDS
        jsr     QCReadOperands
QCScaleDecoded:
.endif
        ldx     z:qc_b
        lda     a:qcg,x
        sta     z:qc_rhs
        lda     #3
        sta     z:qc_size
@Component:
        ldx     z:qc_a
        lda     a:qcg,x
        jsr     QCMulRound
        ldy     z:qc_c
        sta     a:qcg,y
        inc     z:qc_a
        inc     z:qc_a
        inc     z:qc_c
        inc     z:qc_c
        dec     z:qc_size
        bne     @Component
        jmp     QuakeCDispatch

QCAbsOperands:
        sta     a:qc_lo
        eor     z:qc_rhs
        sta     z:qc_sign
        lda     a:qc_lo
        jsr     QCAbs
        sta     a:qc_lo
        lda     z:qc_rhs
        jsr     QCAbs
        sta     z:qc_factor
        rts
QCApplySign:
        ldx     z:qc_sign
        bpl     QCPositive
        bra     QCNegate
QCAbs:
        cmp     #$8000
        bcc     QCPositive
QCNegate:
        eor     #$ffff
        inc
QCPositive:
        rts

; Inventory masks are raw integer words; all ordinary scalars remain Q6.
QCOpInventoryAnd:
        jsr     QCOperands
        and     a:qcg,y
        jmp     QCStoreResult
QCOpInventoryOr:
        jsr     QCOperands
        ora     a:qcg,y
        jmp     QCStoreResult

.ifdef PLAYABLE_E1M1_LINKED_BUILTINS
QCGenericBuiltin:
        cmp     #0                      ; The ordinary classifier selected a negative entry.
.endif
QuakeCBuiltin:
        cmp     #$fffe                  ; setorigin(entity, vector)
        beq     @SetOrigin
        cmp     #$fff8                  ; sound(entity, channel, sample, ...)
        beq     @Sound
        cmp     #$fff4                  ; vlen(vector)
        bne     :+
        jmp     @Length
:       cmp     #$ffee                  ; find(start, field, string)
        bne     :+
        jmp     @Find
:
        cmp     #$ffeb                  ; stuffcmd: no console in the cartridge.
        beq     @NoClientConsole
        cmp     #$ffe8                  ; sprint: the HUD reads the live ammo.
        beq     @NoClientConsole
        jmp     GruntBuiltin
@NoClientConsole:
        rts
@SetOrigin:
        ldx     a:qcg+8
        lda     a:qcg+14
        sta     a:qce+QC_FIELD_ORIGIN,x
        lda     a:qcg+16
        sta     a:qce+QC_FIELD_ORIGIN+2,x
        lda     a:qcg+18
        sta     a:qce+QC_FIELD_ORIGIN+4,x
        stz     a:qce+QC_PUSHER_FRACTION,x              ; Drop fractional integration remainder.
        rts
@Sound:
.ifdef QC_EXPLOBOX
        lda     a:qcg+20
        cmp     #QC_EXPLOBOX_SOUND
        bne     :+
        lda     #15
        jsl     GameplayPlayTrackLong
        rts
:
.endif
        inc     a:.loword(quakec_sounds)
        lda     a:qcg+20
.ifdef QC_GIB_FIRST_ROW
        cmp     #QC_GIB_SOUND
        bne     :+
        lda     #GAMEPLAY_GIB_SAMPLE
        jsl     GameplayPlayMapCueAcknowledged
        rts
:
.endif
.ifdef QC_POWERUP_COUNT
        cmp     #QC_QUAD_SOUND
        bne     :+
        jsl     PowerupPlayAttackCue
        rts
:
.endif
.ifdef QC_SSG_SOUND
        cmp     #QC_SSG_SOUND
        beq     @Shotgun
.endif
        cmp     #QC_SHOTGUN_SOUND
        beq     @Shotgun
        cmp     #QC_SHELL_SOUND
        beq     @Shell
        cmp     #QC_AXE_HIT_SOUND
        beq     @Axe
.ifndef QC_BASIC_GAMEPLAY
        jsl     QuakeCPusherSound
        bcs     @NoClientConsole
.endif
        jmp     GruntSound
@Shell: lda     #1
        jmp     GameplayPlaySound
@Axe:   lda     #9
        jmp     GameplayPlaySound
@Shotgun:
        jmp     ShotgunFired
@Length:
        lda     a:qcg+QC_GLOBAL_SELF
.ifdef QC_EXPLOBOX
        cmp     #QC_EXPLOBOX
        bne     :+
        jmp     ExploboxLength
:
.endif
        cmp     #QC_GRUNT
        bcc     :+
        cmp     #QC_GRUNT_DROP
        bcs     :+
        jmp     GruntLength
:       ; Movers may travel on X, Y or Z. Only a diagonal traps.
        lda     a:qcg+8
        beq     @UseY
        ldx     a:qcg+10
        bne     @BadLength
        ldx     a:qcg+12
        bne     @BadLength
        bra     @Magnitude
@UseY:
        lda     a:qcg+10
        beq     @UseZ
        ldx     a:qcg+12
        bne     @BadLength
        bra     @Magnitude
@UseZ:
        lda     a:qcg+12
@Magnitude:
        jsr     QCAbs
        sta     a:qcg+2
        rts
@BadLength:
        jmp     QuakeCTrap
@Find:
        lda     a:qcg+8
        sta     z:qc_tmp
@Next:
        lda     z:qc_tmp
        clc
        adc     #QC_ENTITY_STRIDE
        cmp     #QC_EDICT_BYTES
        bcs     @NoMatch
        sta     z:qc_tmp
        clc
        adc     a:qcg+14
        tax
        lda     a:qce,x
        beq     @Next
        cmp     a:qcg+20
        bne     @Next
        lda     z:qc_tmp
        bra     @Found
@NoMatch:
        lda     #0
@Found:
        sta     a:qcg+2
        rts

.ifdef PLAYABLE_E1M1_LINKED_BUILTINS
QCVectorLengthBuiltin = @Length
.endif
.include "quake/QuakeCPushers.s"
.include "quake/QuakeCEntrance.s"
.ifdef QC_E1M2_GROUP_COUNT
.include "quake/QuakeCE1M2.s"
.elseif .defined(QC_EXIT_MOVER_COUNT)
.include "quake/QuakeCExit.s"
.endif
.include "quake/QuakeCHub.s"
.ifdef QC_INTERMISSION_COUNT
.include "quake/Intermission.s"
.include "quake/IntermissionOverlay.s"
.endif
.include "quake/Shotgun.s"
.include "quake/Grunt.s"
.include "quake/GruntMath.s"
.ifdef QC_EXPLOBOX
.include "quake/Explobox.s"
.endif
.include "quake/GruntTrace.s"
.include "quake/GruntMove.s"
.ifdef QC_BACKPACK_COUNT
.include "quake/Backpacks.s"
.ifdef QC_GIB_FIRST_ROW
.include "quake/Gibs.s"
.endif
.endif
.ifdef QC_DOG_FIRST
.include "quake/DogMovement.s"
.endif
.if QC_ENTRANCE_COUNT > 0 .or .defined(QC_EXIT_MOVER_COUNT)
.include "quake/QuakeCEntranceVisuals.s"
.endif

QuakeCProgramEnd:
.if BSP_PLAYER_WALK
.ifdef PLAYABLE_REGISTER_WALK_TRACE
.include "Data/PlayableWalkHull.i"
.endif
WalkProgramBegin:
.if .defined(PLAYABLE_WALK_HULL_EXIT_GUARD) .or .defined(PLAYABLE_SHOT_HULL_EXIT_GUARD)
; Keep the word pair at its encoded tag-byte offset in CPU-only ROM.
.pushseg
.segment "BSP_QUAKEC_BYTECODE"
.macro WALK_AXES_BY_TAG axis_a, axis_b
        .word axis_a, axis_b
        .res 28, 0
.endmacro
WalkAxesByTag:
        WALK_AXES_BY_TAG 0, 2
        WALK_AXES_BY_TAG 0, 4
        WALK_AXES_BY_TAG 2, 4
        WALK_AXES_BY_TAG 0, 0
        WALK_AXES_BY_TAG 2, 0
        WALK_AXES_BY_TAG 4, 0
        WALK_AXES_BY_TAG 4, 0
        .word 0, 0
.delmacro WALK_AXES_BY_TAG
        .assert * - WalkAxesByTag = $E4, error, "Encoded plane axis table has the wrong extent"
.popseg
.endif
.ifdef QC_PICKUP_NOTICES
.include "quake/PickupNotice.s"
.endif
.include "quake/ShellPickups.s"
.include "quake/HealthPickups.s"
.if .defined(QC_NAIL_COUNT) || .defined(QC_CAMPAIGN_ITEMS)
.include "quake/Nailgun.s"
.endif
.if .defined(QC_ARMOR_COUNT) || .defined(QC_CAMPAIGN_ITEMS)
.include "quake/Armor.s"
.ifdef QC_POWERUP_COUNT
.include "quake/Powerups.s"
.endif
.endif
.include "quake/PointTraceLateSplit.i"
.include "quake/PlayerWalkTrace.s"
.ifdef PLAYABLE_REGISTER_POINT_TRACE
.include "Data/PlayableShotHull.i"
.endif
.ifdef PLAYABLE_POINT_MOVING_RANK
.include "quake/PointTraceMovingRank.s"
.endif
.scope ShotHull
POINT_SHOT = 1
WALK_HULL_ROOT = SHOT_HULL_ROOT
WALK_HULL_PLANES = SHOT_HULL_PLANES
WALK_HULL_STACK_ENTRIES = SHOT_HULL_STACK_ENTRIES
w_distance_cache = shotgun_distance_cache
WalkHullData = ::ShotHullData
.include "quake/PlayerWalkTrace.s"
.ifdef PLAYABLE_POINT_SIGHT_CACHE
.include "quake/PointSightTraceCache.s"
.endif
.endscope
.ifdef PLAYABLE_E1M1_WALK_RESUME_BYTES
.include "quake/WalkTraceResultCache.s"
.endif
.include "quake/PlayerWalkMath.s"
.include "quake/PlayerLanding.s"
.include "quake/PlayerWalk.s"
.ifdef QC_E1M3_GOLD_KEY
.include "quake/QuakeCE1M3.s"
.endif
.ifdef PLAYABLE_FX3_PLANE_DISTANCE
.include "quake/CollisionFx3.s"
.endif
WalkProgramEnd:
.ifdef PLAYABLE_E1M1_FOOTING
.include "quake/PointTraceFooting.s"
.endif
.import __BSP_WALK_HULL_LOAD__, __BSP_WALK_HULL_RUN__
.assert __BSP_WALK_HULL_RUN__ = BSP_CPU_CODE_ADDRESS(__BSP_WALK_HULL_LOAD__), lderror, "Player hull needs the S-CPU ROM mirror"
.segment "BSP_WALK_HULL"
WalkHullData:
.ifdef PLAYABLE_REGISTER_WALK_TRACE
  .ifdef PLAYABLE_WALK_HULL_SPLIT_THIRD
        .incbin "Data/PlayableWalkHull.bin", 0, PLAYABLE_WALK_HULL_THIRD
.assert *-WalkHullData = PLAYABLE_WALK_HULL_THIRD, error, "Playable walk node/plane length changed"
  .else
        .incbin "Data/PlayableWalkHull.bin"
.assert *-WalkHullData = PLAYABLE_WALK_HULL_BYTES, error, "Playable hull asset length changed"
  .endif
.else
        .incbin "Data/QuakeBSPWalkHull.bin"
.assert *-WalkHullData = WALK_HULL_BYTES, error, "Player hull asset length changed"
.endif
.ifdef QC_LIQUID_ROOT
WalkLiquidNodes:
        .incbin "Data/QuakeBSPLiquids.bin"
.endif
.ifdef QC_HUB_SWIM_OFFSET
WalkSwimData:
        .incbin "Data/QuakeBSPHubGameplay.bin", QC_HUB_SWIM_OFFSET, QC_HUB_SWIM_END-QC_HUB_SWIM_OFFSET
.assert QC_HUB_SWIM_END = QC_HUB_BYTES, error, "Pool table must be last in the hub asset"
.endif
.import __BSP_SHOT_HULL_LOAD__, __BSP_SHOT_HULL_RUN__
.assert __BSP_SHOT_HULL_RUN__ = BSP_CPU_CODE_ADDRESS(__BSP_SHOT_HULL_LOAD__), lderror, "Shot hull needs the S-CPU ROM mirror"
.segment "BSP_SHOT_HULL"
ShotHullData:
.ifdef PLAYABLE_SHOT_HULL_BYTES
        .incbin "Data/PlayableShotHull.bin"
.assert *-ShotHullData = PLAYABLE_SHOT_HULL_BYTES, error, "Playable shot hull asset length changed"
  .ifdef PLAYABLE_SHOT_RESUME_BYTES
ShotResumeGrid:
        .incbin "Data/PlayableShotResume.bin"
        .assert *-ShotResumeGrid = PLAYABLE_SHOT_RESUME_BYTES, error, "Point-hull resume asset length changed"
    .ifdef PLAYABLE_SHOT_TAIL_MASK_BYTES
        .pushseg
        .segment "BSP_CPU_SHOT_TAIL_MASK"
ShotTailColumnMasks:
      .ifdef PLAYABLE_SHOT_TAIL_PACKED_BYTES
        .assert PLAYABLE_SHOT_TAIL_PACKED_BYTES * 2 = PLAYABLE_SHOT_TAIL_MASK_BYTES, error, "Point-tail column count changed"
        .incbin "Data/PlayableShotTailMask.bin", 0, PLAYABLE_SHOT_TAIL_PACKED_BYTES
ShotTailMaskDictionary:
        .incbin "Data/PlayableShotTailMask.bin", PLAYABLE_SHOT_TAIL_PACKED_BYTES
        .assert *-ShotTailMaskDictionary = PLAYABLE_SHOT_TAIL_DICTIONARY_BYTES, error, "Point-tail mask dictionary length changed"
      .else
        .incbin "Data/PlayableShotTailMask.bin"
        .assert *-ShotTailColumnMasks = PLAYABLE_SHOT_TAIL_MASK_BYTES, error, "Point-tail certificate asset length changed"
      .endif
        .popseg
    .endif
    .ifdef PLAYABLE_E1M1_POINT_OBLIQUE
        .assert *-ShotHullData <= $8000, error, "E1M1 point hull and resume grid exceed one halfbank"
        .pushseg
        .segment "BSP_WALK_HULL"
        ; Both helpers use far dispatch and long table reads. Keep the larger
        ; point hull contiguous and use the remaining player hull bank space.
        .include "quake/PointTraceVerticalResume.s"
        .include "quake/PointTraceObliqueBounds.s"
        .assert *-WalkHullData <= $8000, error, "E1M1 player hull and point helpers exceed one halfbank"
      .ifdef PLAYABLE_SHOT_PAIR_BYTES
        .segment "BSP_CPU_SHOT_PAIR"
        .include "quake/PointTracePairResume.s"
      .endif
        .popseg
    .endif
  .endif
.else
        .incbin "Data/QuakeBSPShotHull.bin"
.assert *-ShotHullData = SHOT_HULL_BYTES, error, "Shot hull asset length changed"
.endif
.ifdef PLAYABLE_WALK_HULL_SPLIT_THIRD
WalkHullThirdData:
        .incbin "Data/PlayableWalkHull.bin", PLAYABLE_WALK_HULL_THIRD, PLAYABLE_WALK_HULL_BYTES-PLAYABLE_WALK_HULL_THIRD
.assert *-ShotHullData <= $8000, error, "Shot hull and walk coefficients exceed a halfbank"
.endif
.endif

.ifdef QC_STOCK_AIM
; These routines share the player-hull CPU bank with the point-trace helpers.
; The main VM bank is full. Every cross-bank entry has a long return.
.pushseg
.segment "BSP_WALK_HULL"
.include "quake/PlayerAim.s"
.include "quake/CombatImpacts.s"
.assert *-WalkHullData <= $8000, error, "E1M1 player hull and combat routines exceed one halfbank"
.popseg
.endif
