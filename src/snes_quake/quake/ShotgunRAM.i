shotgun_shots:          .res 2
shotgun_pellets:        .res 2
shotgun_hits:           .res 2
shotgun_trace_fault:    .res 2
shotgun_impact_events:  .res 2
shotgun_sound_token:    .res 1
shotgun_flash:          .res 1
shotgun_view_shot:      .res 2
QC_WORD shot_clock
QC_WORD shot_rng
QC_WORD shot_yaw
QC_WORD shot_pitch
QC_WORD shot_pitch_sin
QC_WORD shot_pitch_cos
QC_WORD shot_yaw_sin
QC_WORD shot_yaw_cos
QC_WORD shot_effect_word
.ifdef QC_STOCK_AIM
QC_WORD aim_actor
QC_WORD aim_best
QC_WORD aim_score
QC_WORD aim_dot
QC_WORD aim_distance
aim_vector_wram: .res 6
QC_WORD impact_active
QC_WORD impact_next
QC_WORD impact_message
QC_WORD impact_style
impact_origin = .loword(*)
        .res 6
impact_delta = .loword(*)
        .res 6
IMPACT_CAPACITY = 20
IMPACT_LIFE = 0
IMPACT_ROW = 2
IMPACT_POS = 4
IMPACT_DELTA = 10
IMPACT_REM = 16
IMPACT_RECORD = 22
; The door, button and first two shell pickups reserve 512-byte edicts.
; Place five records after the original fields and the two-byte pusher
; remainder. The last record ends exactly at the next edict boundary.
IMPACT_EDICT_OFFSET = QC_PUSHER_FRACTION+2
IMPACT_PER_EDICT = 5
IMPACT_END = 4*QC_ENTITY_STRIDE
.export impact_records_wram:far
impact_records_wram = QuakeCEdicts+2*QC_ENTITY_STRIDE+IMPACT_EDICT_OFFSET
impact_records = .loword(impact_records_wram)
.assert QC_EDICT_FIELD_BYTES <= QC_PUSHER_FRACTION, error, "stock fields overlap impact slots"
.assert IMPACT_EDICT_OFFSET+IMPACT_RECORD*IMPACT_PER_EDICT <= QC_ENTITY_STRIDE, error, "impact slots cross an edict"
.assert IMPACT_CAPACITY = 4*IMPACT_PER_EDICT, error, "unexpected impact pool geometry"
.endif
.ifdef QC_QUEUED_INPUT
axe_selected:          .res 2
axe_pending:           .res 2
axe_swings:            .res 2
axe_hits:              .res 2
.endif
.ifndef PLAYABLE_LARGE_DISTANCE_CACHE
shotgun_distance_cache = .loword(*)
        .res WALK_DISTANCE_CACHE_BYTES
.endif
ShotgunPlayer = QuakeCEdicts + QC_ENTITY_STRIDE
shot_player = .loword(ShotgunPlayer)
