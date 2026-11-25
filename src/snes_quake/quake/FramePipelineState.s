; Qualification-only state follows the runtime BSS so adding it cannot move
; the hot renderer or sound state across an indexed-address page boundary.
.segment "BSS"
temporal_reuse_enabled: .res 2
; Keep mode state after existing BSS declarations. BSS growth can still move
; the following LORAM segment; qualify its final addresses and frame timing.
frame_pipeline_entry: .res 2
fly_playback_mode: .res 2
fly_look_step_limit: .res 2
active_render_scale: .res 2
presented_render_scale: .res 2
slot_present_direct: .res 4
runtime_menu_draft_scale: .res 2
.ifdef QC_QUEUED_INPUT
.include "quake/GameplayInput.s"
.endif
