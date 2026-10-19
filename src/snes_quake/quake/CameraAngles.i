; Camera orientation uses one byte per full revolution; storage stays 16-bit.
; Recorded poses and joypad steps retain their previous physical angles.
.ifndef CAMERA_ANGLE_STEPS
CAMERA_ANGLE_STEPS = 256
CAMERA_ANGLE_MASK = CAMERA_ANGLE_STEPS - 1
CAMERA_ANGLE_LEGACY_STEP = CAMERA_ANGLE_STEPS / 32
CAMERA_ANGLE_QUARTER = CAMERA_ANGLE_STEPS / 4
.endif
