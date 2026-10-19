; Mouse/joypad input state has an independent lifetime from visual overlays.
; Keep this include after the renderer BSS to preserve its hot state placement.
.pushseg
.segment "BSS"
FlyMouseState:
camera_input_buttons: .res 2
fly_mouse_status: .res 1
fly_mouse_buttons: .res 1
fly_mouse_raw_x: .res 1
fly_mouse_raw_y: .res 1
fly_mouse_poll_counter: .res 2
fly_mouse_dx: .res 2
fly_mouse_dy: .res 2
fly_mouse_yaw_step: .res 2
fly_mouse_pitch_step: .res 2
FlyMouseStateEnd:
.assert (FlyMouseStateEnd-FlyMouseState) .mod 2 = 0, error, "Mouse state clear requires words"
.popseg
