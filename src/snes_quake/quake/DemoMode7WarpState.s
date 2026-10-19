; Append to LORAM, not BSS: growing BSS relocates every existing LORAM word.
; The immutable image reference changes only on a real pixel presentation.
.segment "LORAM"
presented_warp_x:          .res 2
presented_warp_y:          .res 2
presented_warp_z:          .res 2
presented_warp_epoch:      .res 2
fly_warp_reference_x:      .res 2
fly_warp_reference_y:      .res 2
fly_warp_reference_z:      .res 2
fly_warp_reference_epoch:  .res 2
demo_warp_camera:         .res 10 ; Absolute Q3 XYZ, u16 yaw and engine pitch.
demo_warp_sample_tick:     .res 2
demo_warp_epoch:           .res 2
demo_warp_pose:            .res 2
demo_warp_offset:          .res 2
demo_warp_sign:            .res 2
demo_warp_magnitude:       .res 2
demo_warp_partial:         .res 2
demo_warp_multiplier:      .res 2
demo_warp_delta_x:         .res 2
demo_warp_delta_y:         .res 2
demo_warp_delta_z:         .res 2
demo_warp_sin:             .res 2
demo_warp_cos:             .res 2
demo_warp_horizontal:      .res 2
demo_warp_cached_x:        .res 2
demo_warp_cached_y:        .res 2
demo_warp_cached_zoom:     .res 2
demo_warp_cache_key:      .res 14
demo_warp_cache_tick:      .res 2
