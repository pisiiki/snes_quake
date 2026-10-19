; Keep old public camera/queue addresses stable. Both HDMA streams are in
; low WRAM, separate from collision RAM and both staging buffers.
.segment "LORAM"
hdma_active:              .res 2 ; Applied buffer offset: 0 or 648.
hdma_ready:               .res 2 ; Published offset + 1; zero is invalid.
hdma_active_valid:        .res 2
hdma_nmi_counter:         .res 2
hdma_request_sequence:    .res 2
hdma_request:             .res 36 ; Key, source, target, exact sampling tick.
hdma_request_enabled:     .res 2
hdma_request_precise:     .res 2
hdma_build_precise:       .res 2
hdma_build_busy:          .res 2
hdma_build_completed:     .res 2
hdma_wait_tick:           .res 2
hdma_sound_tick:          .res 2
hdma_sound_slice:         .res 2
hdma_build_sequence:      .res 2
hdma_build_request:       .res 36
hdma_table_metadata:      .res 72 ; One immutable 36-byte record per buffer.
hdma_metadata_offset:     .res 2
hdma_ready_tick:          .res 2
hdma_build_count:         .res 2
hdma_apply_count:         .res 2
hdma_miss_count:          .res 2
hdma_build_start_line:    .res 2
hdma_build_end_line:      .res 2
hdma_build_overrun:       .res 2
hdma_ready_key:           .res 14
hdma_source_camera:       .res 10 ; Q4 XYZ, u16 turns; immutable render camera.
hdma_target_camera:       .res 10 ; Exact recorded pose / current fly camera.
hdma_next_target:         .res 10
hdma_line_latch:          .res 2
hdma_applied_source:      .res 10
hdma_applied_target:      .res 10
hdma_applied_tick:        .res 2
hdma_use_table:           .res 2
hdma_build_base:          .res 2
hdma_band:                .res 2
hdma_table_offset:        .res 2
hdma_neutral:             .res 2
hdma_camera_fault:        .res 2
hdma_bottom:              .res 12
hdma_bottom_steps:        .res 12
hdma_cofactor_constants:  .res 4
hdma_tables:             .res 1296 ; Two sets of four 162-byte direct tables.
.segment "HDMA_WORK"
hdma_work:
hdma_matrix:              .res 18
hdma_translation:         .res 6
hdma_registers:           .res 16
hdma_accum:               .res 32 ; Q12 plus eight guard bits.
hdma_steps:               .res 32
hdma_mul_a:               .res 2
hdma_mul_b:               .res 2
hdma_mul_sign:            .res 2
hdma_math_interrupt:      .res 2
hdma_div_input:           .res 2
hdma_product:             .res 4
hdma_partial:             .res 2
hdma_fault:               .res 2
hdma_sy:                  .res 2
hdma_cy:                  .res 2
hdma_sp:                  .res 2
hdma_cp:                  .res 2
hdma_ts:                  .res 2
hdma_tc:                  .res 2
hdma_ps:                  .res 2
hdma_pc:                  .res 2
hdma_q:                   .res 2
hdma_r:                   .res 2
hdma_pq:                  .res 2
hdma_cq:                  .res 2
hdma_horizontal:          .res 2
hdma_ray:                 .res 6
hdma_t:                   .res 6
hdma_inverse:             .res 2
hdma_ratio:               .res 4
hdma_remaining:           .res 2
hdma_factor:              .res 2
hdma_origin:              .res 8 ; Signed 24.8 texel coordinates.
hdma_dx:                  .res 2
hdma_dy:                  .res 2
hdma_term:                .res 8
hdma_centers:             .res 4
hdma_best_centers:        .res 4
hdma_best_dx:             .res 2
hdma_best_dy:             .res 2
hdma_best_error:          .res 2
hdma_error:               .res 2
hdma_angle:               .res 2
hdma_axis:                .res 2
hdma_phase_x:             .res 12
hdma_phase_y:             .res 12
hdma_cross:               .res 2
hdma_depth_values:        .res 6
hdma_depth_delta:         .res 2
hdma_log_z:               .res 2
hdma_center_factor:       .res 2
hdma_slope_factor:        .res 2
hdma_log_factor:          .res 2
hdma_log_sign:            .res 2
hdma_pivot_residue:       .res 2
.assert *-hdma_work <= 256, error, "HDMA scratch must fit one direct page"
.assert <hdma_work = 0, lderror, "HDMA direct page must be aligned"

.segment "LORAM"
hdma_deadline_phase:      .res 2
hdma_deadline_bands:      .res 2
hdma_deadline_tail:       .res 2 ; Latched with phase zero across mode changes.
hdma_audio_enabled:       .res 2
hdma_deadline_armed:      .res 2
hdma_deadline_tick:       .res 2
hdma_deadline_checks:     .res 2
hdma_deadline_misses:     .res 2
hdma_applied_sample_tick: .res 2
hdma_deadline_end_line:   .res 2
hdma_table_precise:       .res 4 ; Sampling basis belongs to each immutable table.
hdma_rotation_valid:      .res 2
hdma_rotation_precise:    .res 2
hdma_rotation_key:        .res 8 ; Source/target yaw and pitch, without positions.
hdma_rotation_fault:      .res 2
hdma_rotation_accum:      .res 20 ; Initial five angular recurrences.
demo_warp_clock_valid:    .res 2
demo_warp_clock_epoch:    .res 2
demo_warp_clock_pose:     .res 2
demo_warp_clock_phase:    .res 2
demo_warp_clock_tick:     .res 2
demo_warp_render_phase:   .res 2
; FOV belongs to the retained image and each immutable table, including caches.
fly_warp_reference_overscan: .res 2
hdma_request_overscan:    .res 2
hdma_build_overscan:      .res 2
hdma_table_overscan:      .res 4
hdma_applied_overscan:    .res 2
hdma_metadata_slot:       .res 2
