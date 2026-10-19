; Compile-time viewport constants. The generated fly3x copy changes SCALE
; and every private symbol name; neither renderer tests resolution at runtime.
BSP_RENDER_SCALE = 2
.if BSP_RENDER_SCALE = 2
BSP_VIEW_WIDTH = 128
BSP_VIEW_HEIGHT = 112
BSP_VIEW_CENTER_X = 64
BSP_VIEW_CENTER_Y = 56
BSP_VIEW_CENTER_X_Q7 = 8192
BSP_VIEW_CENTER_Y_Q7 = 7168
BSP_VIEW_RECIPROCAL_NUMERATOR = 24576
.else
BSP_VIEW_WIDTH = 85
BSP_VIEW_HEIGHT = 74
; Round the camera center to a whole framebuffer texel in both projections.
BSP_VIEW_CENTER_X = 43
BSP_VIEW_CENTER_Y = 37
BSP_VIEW_CENTER_X_Q7 = BSP_VIEW_CENTER_X * 128
BSP_VIEW_CENTER_Y_Q7 = BSP_VIEW_CENTER_Y * 128
BSP_VIEW_RECIPROCAL_NUMERATOR = 16384
.endif
