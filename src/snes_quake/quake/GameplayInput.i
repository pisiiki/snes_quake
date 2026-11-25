.ifdef QC_QUEUED_INPUT
QC_INPUT_VBLANKS = 3
QC_SIMULATION_HZ = 20
QC_INPUT_WALK = $0004             ; Clear keeps the original running default.
QC_INPUT_TICK = qc_input_tick
QC_INPUT_BUTTONS = qc_input_buttons
QC_INPUT_MENU_OPEN = qc_input_menu
QC_INPUT_RELEASE_GATE = qc_input_release
QC_RNG_TICK = quakec_last_tick
.else
QC_INPUT_TICK = video_tick
QC_INPUT_BUTTONS = camera_input_buttons
QC_INPUT_MENU_OPEN = runtime_menu_open
QC_INPUT_RELEASE_GATE = runtime_menu_release_gate
QC_RNG_TICK = video_tick
.endif

.macro GameplayInputEndVBlank
.ifdef QC_QUEUED_INPUT
        RW_forced a16i16
        jsr     GameplayLatchInput
.endif
.endmacro

; Recorded tapes transport the separate weapon action through SELECT.
.ifdef PLAYABLE_RECORDED_TAPE
QC_INPUT_RECORDED_TAPE = 2
QC_INPUT_RECORDED_HOLD = $8000
.endif
