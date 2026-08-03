; Modal runtime menu and Controller-1 policy for QuakeBSP.
;
; Start is exclusively the menu key. The closed-menu Select shortcut remains
; available for benchmark/tool compatibility. Host-only setup uses the
; versioned frame-zero boot-parameter ABI rather than a hidden second pad.

RUNTIME_MENU_ROW_RESUME   = 0
RUNTIME_MENU_ROW_PLAYBACK = 1
RUNTIME_MENU_ROW_TEXTURES = 2
RUNTIME_MENU_ROW_LIGHTING = 3
RUNTIME_MENU_ROW_BRUSHES  = 4
RUNTIME_MENU_ROW_TEMPORAL = 5
RUNTIME_MENU_ROW_RESTART  = 6
RUNTIME_MENU_ROW_COUNT    = 7
RUNTIME_MENU_COLUMNS      = 18
RUNTIME_MENU_VALUE_COLUMN = 10
RUNTIME_MENU_VALUE_BYTES  = 8
RUNTIME_MENU_VALUE_X_SHIFT = 8
RUNTIME_MENU_BRUSH_VALUE_COLUMN = 11
RUNTIME_MENU_BRUSH_VALUE_BYTES = RUNTIME_MENU_COLUMNS - RUNTIME_MENU_BRUSH_VALUE_COLUMN
RUNTIME_MENU_X            = 56
RUNTIME_MENU_Y            = 72
RUNTIME_MENU_ENTRY_BYTES  = 4
RUNTIME_MENU_ROW_BYTES    = RUNTIME_MENU_COLUMNS * RUNTIME_MENU_ENTRY_BYTES
RUNTIME_MENU_USED_ENTRIES = RUNTIME_MENU_ROW_COUNT * RUNTIME_MENU_COLUMNS
RUNTIME_MENU_OBJ_ATTR     = $3F ; name bit 8, palette 7, priority 3
RUNTIME_MENU_COLOR_MATH   = CG_BG1_ON | CG_BACK_ON | CG_HALF_ON
RUNTIME_MENU_COLOR_WINDOW_OPEN   = $00 ; permit fixed-black math everywhere
RUNTIME_MENU_COLOR_WINDOW_CLOSED = $30 ; LibSFX idle state: prevent math
RUNTIME_MENU_TILE_SPACE   = .lobyte(RUNTIME_MENU_TILE_BASE)
RUNTIME_MENU_TILE_CURSOR  = .lobyte(RUNTIME_MENU_TILE_BASE + (62 - RUNTIME_MENU_ASCII_FIRST))
RUNTIME_MENU_PLAYBACK_ORDERED  = 0
RUNTIME_MENU_PLAYBACK_REALTIME = 1
RUNTIME_MENU_PLAYBACK_FLY      = 2
RUNTIME_MENU_PLAYBACK_HALF     = 3
RUNTIME_MENU_PLAYBACK_QUARTER  = 4
RUNTIME_MENU_PLAYBACK_COUNT    = 5
DEMO_PLAYBACK_RATE_REALTIME    = 0
DEMO_PLAYBACK_RATE_HALF        = 1
DEMO_PLAYBACK_RATE_QUARTER     = 2
RUNTIME_MENU_LIGHTING_NONE     = 0
RUNTIME_MENU_LIGHTING_DISTANCE = 1
RUNTIME_MENU_LIGHTING_LIGHTMAP = 2
RUNTIME_MENU_TEXTURED_BASE     = 2
RUNTIME_MENU_UNTEXTURED_BASE   = 5
RUNTIME_MENU_TECHNIQUE_COUNT   = 8
CAMERA_PITCH_MIN               = $FFF8 ; -8 * 11.25 degrees = -90
CAMERA_PITCH_MAX               = $0008 ; +8 * 11.25 degrees = +90
CAMERA_FORWARD_SCALE_ROUND     = $0010

BOOT_PARAMETERS_VERSION       = $0002
BOOT_PARAMETERS_SIZE          = $0012
BOOT_PARAMETERS_REQUEST_LO    = $4251 ; "QB"
BOOT_PARAMETERS_REQUEST_HI    = $3250 ; "P2"
BOOT_PARAMETERS_ACK_HI        = $3241 ; "A2"
BOOT_PARAMETERS_ERROR_HI      = $3245 ; "E2"
BOOT_PARAMETERS_PRESENT_PLAYBACK = $0001
BOOT_PARAMETERS_PRESENT_TECHNIQUE = $0002
BOOT_PARAMETERS_PRESENT_BRUSHES = $0004
BOOT_PARAMETERS_PRESENT_FIXED_STEP_SAMPLE = $0008
BOOT_PARAMETERS_PRESENT_COVERAGE = $0010
BOOT_PARAMETERS_PRESENT_ALL   = $001F
BOOT_PARAMETERS_STATUS_APPLIED = $01
BOOT_PARAMETERS_ERROR_HEADER  = $E1
BOOT_PARAMETERS_ERROR_MASK    = $E2
BOOT_PARAMETERS_ERROR_PLAYBACK = $E3
BOOT_PARAMETERS_ERROR_TECHNIQUE = $E4
BOOT_PARAMETERS_ERROR_BRUSHES = $E5
BOOT_PARAMETERS_ERROR_FIXED_STEP_SAMPLE = $E6
BOOT_PARAMETERS_ERROR_COVERAGE = $E7

.assert RUNTIME_MENU_USED_ENTRIES <= 128, error, "Runtime menu exceeds SNES OAM capacity"
.assert RUNTIME_MENU_COLUMNS <= 32, error, "Runtime menu exceeds the per-scanline OBJ limit"
.assert RUNTIME_MENU_BRUSH_VALUE_COLUMN + RUNTIME_MENU_BRUSH_VALUE_BYTES = RUNTIME_MENU_COLUMNS, error, "Dynamic-brush value must end at the menu edge"
.assert BOOT_PARAMETERS_SIZE = GSU_BOOT_PARAMETERS_BYTES, error, "Boot parameter ABI size disagrees with cartridge RAM"

; Consume an optional one-shot host request before the first render. The host
; writes offsets 4..17 while Mesen is paused at power-on and commits the magic
; at offsets 0..3 last. Validation is a separate pass, so malformed requests
; leave the normal startup defaults untouched. Status is published before the
; high acknowledgement word changes the request into "QBA2" or "QBE2".
ApplyBootParameters:
        RW_forced a16i16
        lda     f:GSU_BOOT_PARAMETERS+0
        cmp     #BOOT_PARAMETERS_REQUEST_LO
        beq     :+
        rts
:
        lda     f:GSU_BOOT_PARAMETERS+2
        cmp     #BOOT_PARAMETERS_REQUEST_HI
        beq     :+
        rts
:
        lda     f:GSU_BOOT_PARAMETERS+4
        cmp     #BOOT_PARAMETERS_VERSION
        beq     :+
        jmp     BootParametersErrorHeader
:
        lda     f:GSU_BOOT_PARAMETERS+6
        cmp     #BOOT_PARAMETERS_SIZE
        beq     :+
        jmp     BootParametersErrorHeader
:
        lda     f:GSU_BOOT_PARAMETERS+10
        and     #$FFE0
        beq     :+
        jmp     BootParametersErrorMask
:

        lda     f:GSU_BOOT_PARAMETERS+10
        and     #BOOT_PARAMETERS_PRESENT_PLAYBACK
        beq     BootParametersValidateTechnique
        lda     f:GSU_BOOT_PARAMETERS+12
        and     #$00FF
        cmp     #RUNTIME_MENU_PLAYBACK_COUNT
        bcc     :+
        jmp     BootParametersErrorPlayback
:
BootParametersValidateTechnique:
        lda     f:GSU_BOOT_PARAMETERS+10
        and     #BOOT_PARAMETERS_PRESENT_TECHNIQUE
        beq     BootParametersValidateBrushes
        lda     f:GSU_BOOT_PARAMETERS+13
        and     #$00FF
        cmp     #RUNTIME_MENU_TECHNIQUE_COUNT
        bcc     :+
        jmp     BootParametersErrorTechnique
:
BootParametersValidateBrushes:
        lda     f:GSU_BOOT_PARAMETERS+10
        and     #BOOT_PARAMETERS_PRESENT_BRUSHES
        beq     BootParametersValidateFixedStepSample
        lda     f:GSU_BOOT_PARAMETERS+14
        and     #$00FF
        cmp     #$0002
        bcc     :+
        jmp     BootParametersErrorBrushes
:
BootParametersValidateFixedStepSample:
        lda     f:GSU_BOOT_PARAMETERS+10
        and     #BOOT_PARAMETERS_PRESENT_FIXED_STEP_SAMPLE
        beq     BootParametersValidateCoverage
        lda     f:GSU_BOOT_PARAMETERS+10
        and     #BOOT_PARAMETERS_PRESENT_PLAYBACK
        beq     :+
        lda     f:GSU_BOOT_PARAMETERS+12
        and     #$00FF
        beq     :+
        jmp     BootParametersErrorFixedStepSample
:
        lda     f:GSU_BOOT_PARAMETERS+15
        and     #$00FF
        cmp     #BSP_DEMO_STEP_POSE_COUNT
        bcc     BootParametersValidateCoverage
        jmp     BootParametersErrorFixedStepSample

BootParametersValidateCoverage:
        lda     f:GSU_BOOT_PARAMETERS+10
        and     #BOOT_PARAMETERS_PRESENT_COVERAGE
        beq     BootParametersApplyPlayback
        lda     f:GSU_BOOT_PARAMETERS+16
        and     #$00FF
        cmp     #$0003
        bcc     BootParametersApplyPlayback
        jmp     BootParametersErrorCoverage

BootParametersApplyPlayback:
        lda     f:GSU_BOOT_PARAMETERS+10
        and     #BOOT_PARAMETERS_PRESENT_PLAYBACK
        beq     BootParametersApplyTechnique
        lda     f:GSU_BOOT_PARAMETERS+12
        and     #$00FF
        sta     runtime_menu_draft_playback
        cmp     #RUNTIME_MENU_PLAYBACK_REALTIME
        beq     BootParametersPlaybackRealtime
        cmp     #RUNTIME_MENU_PLAYBACK_FLY
        beq     BootParametersPlaybackFly
        cmp     #RUNTIME_MENU_PLAYBACK_HALF
        beq     BootParametersPlaybackHalf
        cmp     #RUNTIME_MENU_PLAYBACK_QUARTER
        beq     BootParametersPlaybackQuarter
        lda     #$0001
        sta     demo_mode
        stz     demo_schedule
        stz     demo_playback_rate_shift
        bra     BootParametersApplyTechnique
BootParametersPlaybackRealtime:
        lda     #$0001
        sta     demo_mode
        sta     demo_schedule
        stz     demo_playback_rate_shift
        bra     BootParametersApplyTechnique
BootParametersPlaybackFly:
        stz     demo_mode
        stz     demo_schedule
        stz     demo_playback_rate_shift
        bra     BootParametersApplyTechnique
BootParametersPlaybackHalf:
        lda     #$0001
        sta     demo_mode
        sta     demo_schedule
        sta     demo_playback_rate_shift
        bra     BootParametersApplyTechnique
BootParametersPlaybackQuarter:
        lda     #$0001
        sta     demo_mode
        sta     demo_schedule
        lda     #DEMO_PLAYBACK_RATE_QUARTER
        sta     demo_playback_rate_shift

BootParametersApplyTechnique:
        lda     f:GSU_BOOT_PARAMETERS+10
        and     #BOOT_PARAMETERS_PRESENT_TECHNIQUE
        beq     BootParametersApplyBrushes
        lda     f:GSU_BOOT_PARAMETERS+13
        and     #$00FF
        sta     technique
        sta     runtime_menu_draft_technique
BootParametersApplyBrushes:
        lda     f:GSU_BOOT_PARAMETERS+10
        and     #BOOT_PARAMETERS_PRESENT_BRUSHES
        beq     BootParametersApplyFixedStepSample
        lda     f:GSU_BOOT_PARAMETERS+14
        and     #$00FF
        sta     dynamic_brushes_enabled
        sta     runtime_menu_draft_brushes

BootParametersApplyFixedStepSample:
        lda     f:GSU_BOOT_PARAMETERS+10
        and     #BOOT_PARAMETERS_PRESENT_FIXED_STEP_SAMPLE
        beq     BootParametersApplyCoverage
        lda     f:GSU_BOOT_PARAMETERS+15
        and     #$00FF
        inc
        sta     boot_fixed_step_sample

BootParametersApplyCoverage:
        lda     f:GSU_BOOT_PARAMETERS+10
        and     #BOOT_PARAMETERS_PRESENT_COVERAGE
        beq     BootParametersPublishApplied
        lda     f:GSU_BOOT_PARAMETERS+16
        and     #$00FF
        sta     coverage_debug

BootParametersPublishApplied:
        jsr     SyncRuntimeMenuDrafts
        RW      a8
        lda     #BOOT_PARAMETERS_STATUS_APPLIED
        sta     f:GSU_BOOT_PARAMETERS+17
        RW      a16
        lda     #BOOT_PARAMETERS_ACK_HI
        sta     f:GSU_BOOT_PARAMETERS+2
        bra     BootParametersDone

BootParametersErrorHeader:
        lda     #BOOT_PARAMETERS_ERROR_HEADER
        bra     BootParametersPublishError
BootParametersErrorMask:
        lda     #BOOT_PARAMETERS_ERROR_MASK
        bra     BootParametersPublishError
BootParametersErrorPlayback:
        lda     #BOOT_PARAMETERS_ERROR_PLAYBACK
        bra     BootParametersPublishError
BootParametersErrorTechnique:
        lda     #BOOT_PARAMETERS_ERROR_TECHNIQUE
        bra     BootParametersPublishError
BootParametersErrorBrushes:
        lda     #BOOT_PARAMETERS_ERROR_BRUSHES
        bra     BootParametersPublishError
BootParametersErrorFixedStepSample:
        lda     #BOOT_PARAMETERS_ERROR_FIXED_STEP_SAMPLE
        bra     BootParametersPublishError
BootParametersErrorCoverage:
        lda     #BOOT_PARAMETERS_ERROR_COVERAGE
BootParametersPublishError:
        RW      a8
        sta     f:GSU_BOOT_PARAMETERS+17
        RW      a16
        lda     #BOOT_PARAMETERS_ERROR_HI
        sta     f:GSU_BOOT_PARAMETERS+2
BootParametersDone:
        RW_forced a16i16
        rts

; Seed an ordered 2 Hz restart at a host-selected sample. The one-based field
; distinguishes sample zero from an omitted request and is consumed once.
ApplyBootFixedStepSample:
        RW_assume a16i16
        lda     boot_fixed_step_sample
        beq     ApplyBootFixedStepSampleDone
        stz     boot_fixed_step_sample
        dec
        sta     demo_next_pose
        asl
        asl
        asl
        asl
        sec
        sbc     demo_next_pose
        sta     demo_next_pose
        asl
        sta     demo_timing_offset
        lda     demo_next_pose
        asl
        sta     demo_offset
        asl
        asl
        clc
        adc     demo_offset
        sta     demo_offset
ApplyBootFixedStepSampleDone:
        rts

; Called once per VBlank before Controller-1 gameplay input. While open, the
; menu consumes Controller 1 and the caller skips camera/demo progression.
UpdateRuntimeMenu:
        RW_forced a16i16
        lda     runtime_menu_open
        bne     RuntimeMenuHandleOpen
        lda     z:SFX_joy1trig
        and     #JOY_START
        beq     RuntimeMenuUpdateDone
        jsr     OpenRuntimeMenu
        bra     RuntimeMenuUpdateDone

RuntimeMenuHandleOpen:
        lda     z:SFX_joy1trig
        and     #(JOY_B | JOY_START)
        beq     RuntimeMenuCheckUp
        jsr     CloseRuntimeMenu
        bra     RuntimeMenuUpdateDone
RuntimeMenuCheckUp:
        lda     z:SFX_joy1trig
        and     #JOY_UP
        beq     RuntimeMenuCheckDown
        lda     runtime_menu_selection
        bne     :+
        lda     #RUNTIME_MENU_ROW_COUNT
:
        dec
        sta     runtime_menu_selection
        jsr     RefreshRuntimeMenuOAM
        bra     RuntimeMenuUpdateDone
RuntimeMenuCheckDown:
        lda     z:SFX_joy1trig
        and     #JOY_DOWN
        beq     RuntimeMenuCheckLeft
        lda     runtime_menu_selection
        inc
        cmp     #RUNTIME_MENU_ROW_COUNT
        bcc     :+
        lda     #RUNTIME_MENU_ROW_RESUME
:
        sta     runtime_menu_selection
        jsr     RefreshRuntimeMenuOAM
        bra     RuntimeMenuUpdateDone
RuntimeMenuCheckLeft:
        lda     z:SFX_joy1trig
        and     #JOY_LEFT
        beq     RuntimeMenuCheckRight
        jsr     RuntimeMenuPreviousValue
        bra     RuntimeMenuUpdateDone
RuntimeMenuCheckRight:
        lda     z:SFX_joy1trig
        and     #JOY_RIGHT
        beq     RuntimeMenuCheckActivate
        jsr     RuntimeMenuNextValue
        bra     RuntimeMenuUpdateDone
RuntimeMenuCheckActivate:
        lda     z:SFX_joy1trig
        and     #JOY_A
        beq     RuntimeMenuUpdateDone
        lda     runtime_menu_selection
        beq     RuntimeMenuActivateClose
        cmp     #RUNTIME_MENU_ROW_RESTART
        beq     RuntimeMenuActivateRestart
        jsr     RuntimeMenuNextValue
        bra     RuntimeMenuUpdateDone
RuntimeMenuActivateRestart:
        lda     #$0001
        sta     runtime_menu_restart_action
RuntimeMenuActivateClose:
        jsr     CloseRuntimeMenu
RuntimeMenuUpdateDone:
        RW_forced a8i16
        rts

OpenRuntimeMenu:
        RW_assume a16i16
        jsr     SyncRuntimeMenuDrafts
        stz     runtime_menu_selection
        stz     runtime_menu_restart_action
        lda     video_tick
        sec
        sbc     demo_playhead_origin
        dec
        sta     runtime_menu_saved_playhead_tick
        lda     #$0001
        sta     runtime_menu_open
        jsr     RefreshRuntimeMenuOAM
        RW      a8
        lda     #tm(ON, OFF, OFF, OFF, ON)
        sta     TM
        lda     #RUNTIME_MENU_COLOR_WINDOW_OPEN
        sta     CGSWSEL
        lda     #RUNTIME_MENU_COLOR_MATH
        sta     CGADSUB
        RW_forced a16i16
        rts

CloseRuntimeMenu:
        RW_assume a16i16
        jsr     ApplyRuntimeMenuSelection
        stz     runtime_menu_open
        lda     #$0001
        sta     runtime_menu_release_gate
        RW      a8
        lda     #tm(ON, OFF, OFF, OFF, OFF)
        sta     TM
        stz     CGADSUB
        lda     #RUNTIME_MENU_COLOR_WINDOW_CLOSED
        sta     CGSWSEL
        RW_forced a16i16
        rts

; Synchronize the draft fields before displaying the menu. Techniques 0 and 1
; remain reachable through the closed-menu Select shortcut. They display the
; canonical textured/None matrix state, but runtime_menu_draft_technique keeps
; the legacy value unless the user explicitly edits a matrix row.
SyncRuntimeMenuDrafts:
        RW_assume a16i16
        lda     demo_mode
        beq     @Fly
        lda     demo_schedule
        beq     @Ordered
        lda     demo_playback_rate_shift
        cmp     #DEMO_PLAYBACK_RATE_HALF
        beq     @Half
        cmp     #DEMO_PLAYBACK_RATE_QUARTER
        beq     @Quarter
        lda     #RUNTIME_MENU_PLAYBACK_REALTIME
        bra     @PlaybackReady
@Half:
        lda     #RUNTIME_MENU_PLAYBACK_HALF
        bra     @PlaybackReady
@Quarter:
        lda     #RUNTIME_MENU_PLAYBACK_QUARTER
        bra     @PlaybackReady
@Ordered:
        lda     #RUNTIME_MENU_PLAYBACK_ORDERED
        bra     @PlaybackReady
@Fly:
        lda     #RUNTIME_MENU_PLAYBACK_FLY
@PlaybackReady:
        sta     runtime_menu_draft_playback
        lda     technique
        sta     runtime_menu_draft_technique
        cmp     #RUNTIME_MENU_TEXTURED_BASE
        bcc     @LegacyRenderer
        cmp     #RUNTIME_MENU_UNTEXTURED_BASE
        bcc     @TexturedRenderer
        stz     runtime_menu_draft_textures
        sec
        sbc     #RUNTIME_MENU_UNTEXTURED_BASE
        sta     runtime_menu_draft_lighting
        bra     @RendererReady
@TexturedRenderer:
        sec
        sbc     #RUNTIME_MENU_TEXTURED_BASE
        sta     runtime_menu_draft_lighting
        lda     #$0001
        sta     runtime_menu_draft_textures
        bra     @RendererReady
@LegacyRenderer:
        lda     #$0001
        sta     runtime_menu_draft_textures
        stz     runtime_menu_draft_lighting
@RendererReady:
        lda     dynamic_brushes_enabled
        sta     runtime_menu_draft_brushes
        lda     temporal_color_dither_enabled
        sta     runtime_menu_draft_temporal_dither
        rts

; Compose the independent matrix drafts into the retained numeric technique
; field. This is called only after a matrix row changes, so opening and closing
; the menu without edits preserves legacy techniques 0 and 1.
ComposeRuntimeMenuTechnique:
        RW_assume a16i16
        lda     runtime_menu_draft_textures
        and     #$0001
        beq     @Untextured
        lda     runtime_menu_draft_lighting
        clc
        adc     #RUNTIME_MENU_TEXTURED_BASE
        bra     @Store
@Untextured:
        lda     runtime_menu_draft_lighting
        clc
        adc     #RUNTIME_MENU_UNTEXTURED_BASE
@Store:
        sta     runtime_menu_draft_technique
        rts

; Public state application path for both the UI and host tooling:
;   runtime_menu_draft_playback: 0 ordered, 1 real-time, 2 fly,
;                                3 half real-time, 4 quarter real-time
;   runtime_menu_draft_technique: compatible numeric technique 0..7
;   runtime_menu_draft_textures: 0 off, 1 on
;   runtime_menu_draft_lighting: 0 None, 1 Distance, 2 LightMap
;   runtime_menu_draft_brushes: 0 off, 1 on
;   runtime_menu_draft_temporal_dither: 0 static, 1 temporal
; Set runtime_menu_restart_action for restart/recenter semantics.
ApplyRuntimeMenuSelection:
        RW_forced a16i16
        stz     runtime_menu_apply_flags
        lda     runtime_menu_draft_playback
        cmp     #RUNTIME_MENU_PLAYBACK_REALTIME
        beq     @ApplyRealtime
        cmp     #RUNTIME_MENU_PLAYBACK_FLY
        beq     @ApplyFly
        cmp     #RUNTIME_MENU_PLAYBACK_HALF
        beq     @ApplyHalf
        cmp     #RUNTIME_MENU_PLAYBACK_QUARTER
        beq     @ApplyQuarter

@ApplyOrdered:
        lda     demo_mode
        cmp     #$0001
        bne     @OrderedChanged
        lda     demo_schedule
        bne     @OrderedChanged
        lda     demo_playback_rate_shift
        beq     @PlaybackApplied
@OrderedChanged:
        lda     #$0001
        sta     demo_mode
        stz     demo_schedule
        stz     demo_playback_rate_shift
        inc     runtime_menu_apply_flags
        bra     @PlaybackApplied

@ApplyRealtime:
        ldx     #DEMO_PLAYBACK_RATE_REALTIME
        bra     @ApplyRealtimeRate
@ApplyHalf:
        ldx     #DEMO_PLAYBACK_RATE_HALF
        bra     @ApplyRealtimeRate
@ApplyQuarter:
        ldx     #DEMO_PLAYBACK_RATE_QUARTER
@ApplyRealtimeRate:
        lda     demo_mode
        cmp     #$0001
        bne     @RealtimeChanged
        lda     demo_schedule
        cmp     #$0001
        bne     @RealtimeChanged
        txa
        cmp     demo_playback_rate_shift
        beq     @PlaybackApplied
@RealtimeChanged:
        lda     #$0001
        sta     demo_mode
        sta     demo_schedule
        txa
        sta     demo_playback_rate_shift
        inc     runtime_menu_apply_flags
        bra     @PlaybackApplied

@ApplyFly:
        lda     demo_mode
        beq     @PlaybackApplied
@FlyChanged:
        stz     demo_mode
        inc     runtime_menu_apply_flags

@PlaybackApplied:
        lda     runtime_menu_restart_action
        bne     @RestartOrRecenter
        lda     runtime_menu_apply_flags
        beq     @PreserveRealtimeClock
        lda     demo_mode
        beq     @EnteredFly
        jsr     RestartDemoPlayback
        bra     @ApplyRenderer
@EnteredFly:
        inc     control_revision
        stz     scheduled_frame_valid
        bra     @ApplyRenderer

@PreserveRealtimeClock:
        lda     runtime_menu_open
        beq     @ApplyRenderer
        lda     demo_mode
        beq     @ApplyRenderer
        lda     demo_schedule
        beq     @ApplyRenderer
        lda     video_tick
        sec
        sbc     runtime_menu_saved_playhead_tick
        sta     demo_playhead_origin
        bra     @ApplyRenderer

@RestartOrRecenter:
        stz     runtime_menu_restart_action
        lda     demo_mode
        beq     @RecenterFlyCamera
        jsr     RestartDemoPlayback
        bra     @ApplyRenderer
@RecenterFlyCamera:
        lda     #BSP_START_YAW_INDEX
        sta     yaw_index
        stz     pitch_level
        lda     #BSP_WORLD_START_X_Q8
        sta     camera_x
        lda     #BSP_WORLD_START_Y_Q8
        sta     camera_y
        lda     #BSP_WORLD_START_Z_Q8
        sta     camera_z
        lda     #$FFFF
        sta     monster_camera_index
        inc     control_revision
        stz     scheduled_frame_valid

@ApplyRenderer:
        lda     runtime_menu_draft_technique
        cmp     technique
        beq     @ApplyBrushes
        sta     technique
        inc     control_revision
        stz     scheduled_frame_valid

@ApplyBrushes:
        lda     runtime_menu_draft_brushes
        and     #$0001
        cmp     dynamic_brushes_enabled
        beq     @ApplyTemporalDither
        sta     dynamic_brushes_enabled
        jsr     InvalidateDynamicBrushRenderState
@ApplyTemporalDither:
        lda     runtime_menu_draft_temporal_dither
        and     #$0001
        sta     temporal_color_dither_enabled
@ApplyDone:
        RW_forced a16i16
        rts

; Public force-render hook. Call after changing the enabled state or advancing
; the resolved brush replay row. Brush fragments merge after world selection,
; so the immutable world packet remains valid across this state change.
InvalidateDynamicBrushRenderState:
        RW_forced a16i16
        inc     dynamic_brush_revision
        inc     control_revision
        stz     scheduled_frame_valid
        rts

RuntimeMenuPreviousValue:
        RW_assume a16i16
        lda     runtime_menu_selection
        cmp     #RUNTIME_MENU_ROW_PLAYBACK
        beq     @Playback
        cmp     #RUNTIME_MENU_ROW_TEXTURES
        beq     @Textures
        cmp     #RUNTIME_MENU_ROW_LIGHTING
        beq     @Lighting
        cmp     #RUNTIME_MENU_ROW_BRUSHES
        beq     @Brushes
        cmp     #RUNTIME_MENU_ROW_TEMPORAL
        beq     @Temporal
        rts
@Playback:
        lda     runtime_menu_draft_playback
        cmp     #RUNTIME_MENU_PLAYBACK_COUNT
        bcc     :+
        lda     #RUNTIME_MENU_PLAYBACK_ORDERED
:
        asl
        tax
        lda     f:RuntimeMenuPlaybackPrevious,x
        sta     runtime_menu_draft_playback
        bra     @Refresh
@Textures:
        lda     runtime_menu_draft_textures
        eor     #$0001
        sta     runtime_menu_draft_textures
        jsr     ComposeRuntimeMenuTechnique
        bra     @Refresh
@Lighting:
        lda     runtime_menu_draft_lighting
        bne     :+
        lda     #RUNTIME_MENU_LIGHTING_LIGHTMAP+1
:
        dec
        sta     runtime_menu_draft_lighting
        jsr     ComposeRuntimeMenuTechnique
        bra     @Refresh
@Brushes:
        lda     runtime_menu_draft_brushes
        eor     #$0001
        sta     runtime_menu_draft_brushes
        bra     @Refresh
@Temporal:
        lda     runtime_menu_draft_temporal_dither
        eor     #$0001
        sta     runtime_menu_draft_temporal_dither
@Refresh:
        jsr     RefreshRuntimeMenuOAM
        rts

RuntimeMenuNextValue:
        RW_assume a16i16
        lda     runtime_menu_selection
        cmp     #RUNTIME_MENU_ROW_PLAYBACK
        beq     @NextPlayback
        cmp     #RUNTIME_MENU_ROW_TEXTURES
        beq     @NextTextures
        cmp     #RUNTIME_MENU_ROW_LIGHTING
        beq     @NextLighting
        cmp     #RUNTIME_MENU_ROW_BRUSHES
        beq     @NextBrushes
        cmp     #RUNTIME_MENU_ROW_TEMPORAL
        beq     @NextTemporal
        rts
@NextPlayback:
        lda     runtime_menu_draft_playback
        cmp     #RUNTIME_MENU_PLAYBACK_COUNT
        bcc     :+
        lda     #RUNTIME_MENU_PLAYBACK_ORDERED
:
        asl
        tax
        lda     f:RuntimeMenuPlaybackNext,x
        sta     runtime_menu_draft_playback
        bra     @NextRefresh
@NextTextures:
        lda     runtime_menu_draft_textures
        eor     #$0001
        sta     runtime_menu_draft_textures
        jsr     ComposeRuntimeMenuTechnique
        bra     @NextRefresh
@NextLighting:
        lda     runtime_menu_draft_lighting
        inc
        cmp     #RUNTIME_MENU_LIGHTING_LIGHTMAP+1
        bcc     :+
        lda     #RUNTIME_MENU_LIGHTING_NONE
:
        sta     runtime_menu_draft_lighting
        jsr     ComposeRuntimeMenuTechnique
        bra     @NextRefresh
@NextBrushes:
        lda     runtime_menu_draft_brushes
        eor     #$0001
        sta     runtime_menu_draft_brushes
        bra     @NextRefresh
@NextTemporal:
        lda     runtime_menu_draft_temporal_dither
        eor     #$0001
        sta     runtime_menu_draft_temporal_dither
@NextRefresh:
        jsr     RefreshRuntimeMenuOAM
        rts

; Static OAM positions and labels are built once before display is enabled.
; Glyph tiles use transparent color zero, leaving the paused scene visible.
BuildRuntimeMenuOAM:
        RW_forced a8i16
        OAM_init RuntimeMenuOAM, 0, $F0, 0
        stz     RuntimeMenuBuildRow
        ldx     #$0000
        ldy     #$0000
@Row:
        lda     RuntimeMenuBuildRow
        asl
        asl
        asl
        clc
        adc     #RUNTIME_MENU_Y
        sta     RuntimeMenuBuildY
        lda     #RUNTIME_MENU_X
        sta     RuntimeMenuBuildX
        lda     #RUNTIME_MENU_COLUMNS
        sta     RuntimeMenuBuildColumns
@Column:
        ; Reuse slots 10..17 but place editable values at screen columns
        ; 11..18. D-BRUSHES already uses slots/columns 11..17.
        lda     RuntimeMenuBuildColumns
        cmp     #(RUNTIME_MENU_VALUE_BYTES + 1)
        bcs     @ColumnBaseX
        lda     RuntimeMenuBuildRow
        beq     @ColumnBaseX
        cmp     #RUNTIME_MENU_ROW_BRUSHES
        beq     @ColumnBaseX
        cmp     #RUNTIME_MENU_ROW_RESTART
        beq     @ColumnBaseX
        lda     RuntimeMenuBuildX
        clc
        adc     #RUNTIME_MENU_VALUE_X_SHIFT
        bra     @ColumnXReady
@ColumnBaseX:
        lda     RuntimeMenuBuildX
@ColumnXReady:
        sta     a:RuntimeMenuOAM+0,y
        lda     RuntimeMenuBuildY
        sta     a:RuntimeMenuOAM+1,y
        lda     f:RuntimeMenuText,x
        sec
        sbc     #RUNTIME_MENU_ASCII_FIRST
        clc
        adc     #.lobyte(RUNTIME_MENU_TILE_BASE)
        sta     a:RuntimeMenuOAM+2,y
        lda     #RUNTIME_MENU_OBJ_ATTR
        sta     a:RuntimeMenuOAM+3,y
        inx
        iny
        iny
        iny
        iny
        lda     RuntimeMenuBuildX
        clc
        adc     #$08
        sta     RuntimeMenuBuildX
        dec     RuntimeMenuBuildColumns
        bne     @Column
        inc     RuntimeMenuBuildRow
        lda     RuntimeMenuBuildRow
        cmp     #RUNTIME_MENU_ROW_COUNT
        bne     @Row
        jsr     PatchRuntimeMenuOAM
        RW_forced a8i16
        rts

RefreshRuntimeMenuOAM:
        RW_forced a8i16
        jsr     PatchRuntimeMenuOAM
        OAM_memcpy RuntimeMenuOAM
        RW_forced a16i16
        rts

PatchRuntimeMenuOAM:
        RW_forced a8i16
        lda     #RUNTIME_MENU_TILE_SPACE
        sta     a:RuntimeMenuOAM + (RUNTIME_MENU_ROW_BYTES * 0) + 2
        sta     a:RuntimeMenuOAM + (RUNTIME_MENU_ROW_BYTES * 1) + 2
        sta     a:RuntimeMenuOAM + (RUNTIME_MENU_ROW_BYTES * 2) + 2
        sta     a:RuntimeMenuOAM + (RUNTIME_MENU_ROW_BYTES * 3) + 2
        sta     a:RuntimeMenuOAM + (RUNTIME_MENU_ROW_BYTES * 4) + 2
        sta     a:RuntimeMenuOAM + (RUNTIME_MENU_ROW_BYTES * 5) + 2
        sta     a:RuntimeMenuOAM + (RUNTIME_MENU_ROW_BYTES * 6) + 2
        RW      a16
        lda     runtime_menu_selection
        cmp     #RUNTIME_MENU_ROW_PLAYBACK
        beq     @CursorPlayback
        cmp     #RUNTIME_MENU_ROW_TEXTURES
        beq     @CursorTextures
        cmp     #RUNTIME_MENU_ROW_LIGHTING
        beq     @CursorLighting
        cmp     #RUNTIME_MENU_ROW_BRUSHES
        beq     @CursorBrushes
        cmp     #RUNTIME_MENU_ROW_TEMPORAL
        beq     @CursorTemporal
        cmp     #RUNTIME_MENU_ROW_RESTART
        beq     @CursorRestart
        ldx     #(RUNTIME_MENU_ROW_BYTES * RUNTIME_MENU_ROW_RESUME) + 2
        bra     @CursorReady
@CursorPlayback:
        ldx     #(RUNTIME_MENU_ROW_BYTES * RUNTIME_MENU_ROW_PLAYBACK) + 2
        bra     @CursorReady
@CursorTextures:
        ldx     #(RUNTIME_MENU_ROW_BYTES * RUNTIME_MENU_ROW_TEXTURES) + 2
        bra     @CursorReady
@CursorLighting:
        ldx     #(RUNTIME_MENU_ROW_BYTES * RUNTIME_MENU_ROW_LIGHTING) + 2
        bra     @CursorReady
@CursorBrushes:
        ldx     #(RUNTIME_MENU_ROW_BYTES * RUNTIME_MENU_ROW_BRUSHES) + 2
        bra     @CursorReady
@CursorTemporal:
        ldx     #(RUNTIME_MENU_ROW_BYTES * RUNTIME_MENU_ROW_TEMPORAL) + 2
        bra     @CursorReady
@CursorRestart:
        ldx     #(RUNTIME_MENU_ROW_BYTES * RUNTIME_MENU_ROW_RESTART) + 2
@CursorReady:
        RW      a8
        lda     #RUNTIME_MENU_TILE_CURSOR
        sta     a:RuntimeMenuOAM,x

        RW      a16
        lda     runtime_menu_draft_playback
        cmp     #RUNTIME_MENU_PLAYBACK_COUNT
        bcc     :+
        lda     #RUNTIME_MENU_PLAYBACK_ORDERED
:
        asl
        asl
        asl
        tax
        ldy     #(RUNTIME_MENU_ROW_BYTES * RUNTIME_MENU_ROW_PLAYBACK) + (RUNTIME_MENU_VALUE_COLUMN * RUNTIME_MENU_ENTRY_BYTES) + 2
        RW      a8
        lda     #RUNTIME_MENU_VALUE_BYTES
        sta     RuntimeMenuBuildColumns
@PlaybackValue:
        lda     f:RuntimeMenuPlaybackValues,x
        sec
        sbc     #RUNTIME_MENU_ASCII_FIRST
        clc
        adc     #.lobyte(RUNTIME_MENU_TILE_BASE)
        sta     a:RuntimeMenuOAM,y
        inx
        iny
        iny
        iny
        iny
        dec     RuntimeMenuBuildColumns
        bne     @PlaybackValue

        RW      a16
        lda     runtime_menu_draft_textures
        and     #$0001
        asl
        asl
        asl
        tax
        ldy     #(RUNTIME_MENU_ROW_BYTES * RUNTIME_MENU_ROW_TEXTURES) + (RUNTIME_MENU_VALUE_COLUMN * RUNTIME_MENU_ENTRY_BYTES) + 2
        RW      a8
        lda     #RUNTIME_MENU_VALUE_BYTES
        sta     RuntimeMenuBuildColumns
@TexturesValue:
        lda     f:RuntimeMenuToggleValues,x
        sec
        sbc     #RUNTIME_MENU_ASCII_FIRST
        clc
        adc     #.lobyte(RUNTIME_MENU_TILE_BASE)
        sta     a:RuntimeMenuOAM,y
        inx
        iny
        iny
        iny
        iny
        dec     RuntimeMenuBuildColumns
        bne     @TexturesValue

        RW      a16
        lda     runtime_menu_draft_lighting
        and     #$0003
        asl
        asl
        asl
        tax
        ldy     #(RUNTIME_MENU_ROW_BYTES * RUNTIME_MENU_ROW_LIGHTING) + (RUNTIME_MENU_VALUE_COLUMN * RUNTIME_MENU_ENTRY_BYTES) + 2
        RW      a8
        lda     #RUNTIME_MENU_VALUE_BYTES
        sta     RuntimeMenuBuildColumns
@LightingValue:
        lda     f:RuntimeMenuLightingValues,x
        sec
        sbc     #RUNTIME_MENU_ASCII_FIRST
        clc
        adc     #.lobyte(RUNTIME_MENU_TILE_BASE)
        sta     a:RuntimeMenuOAM,y
        inx
        iny
        iny
        iny
        iny
        dec     RuntimeMenuBuildColumns
        bne     @LightingValue

        RW      a16
        lda     runtime_menu_draft_brushes
        and     #$0001
        asl
        asl
        asl
        tax
        ldy     #(RUNTIME_MENU_ROW_BYTES * RUNTIME_MENU_ROW_BRUSHES) + (RUNTIME_MENU_BRUSH_VALUE_COLUMN * RUNTIME_MENU_ENTRY_BYTES) + 2
        RW      a8
        lda     #RUNTIME_MENU_BRUSH_VALUE_BYTES
        sta     RuntimeMenuBuildColumns
@BrushesValue:
        lda     f:RuntimeMenuToggleValues,x
        sec
        sbc     #RUNTIME_MENU_ASCII_FIRST
        clc
        adc     #.lobyte(RUNTIME_MENU_TILE_BASE)
        sta     a:RuntimeMenuOAM,y
        inx
        iny
        iny
        iny
        iny
        dec     RuntimeMenuBuildColumns
        bne     @BrushesValue

        RW      a16
        lda     runtime_menu_draft_temporal_dither
        and     #$0001
        asl
        asl
        asl
        tax
        ldy     #(RUNTIME_MENU_ROW_BYTES * RUNTIME_MENU_ROW_TEMPORAL) + (RUNTIME_MENU_VALUE_COLUMN * RUNTIME_MENU_ENTRY_BYTES) + 2
        RW      a8
        lda     #RUNTIME_MENU_VALUE_BYTES
        sta     RuntimeMenuBuildColumns
@TemporalValue:
        lda     f:RuntimeMenuToggleValues,x
        sec
        sbc     #RUNTIME_MENU_ASCII_FIRST
        clc
        adc     #.lobyte(RUNTIME_MENU_TILE_BASE)
        sta     a:RuntimeMenuOAM,y
        inx
        iny
        iny
        iny
        iny
        dec     RuntimeMenuBuildColumns
        bne     @TemporalValue
@PatchDone:
        RW_forced a8i16
        rts

; Closed-menu Controller 1. Exact fly layout:
;   X/B forward/back, Y/A strafe, L/R monster placements, D-pad look.
UpdateCameraControls:
        RW_forced a16i16
        stz     control_dirty
        inc     control_divider

        lda     runtime_menu_release_gate
        beq     @TechniqueToggle
        lda     z:SFX_joy1cont
        beq     :+
        jmp     @Return
:
        stz     runtime_menu_release_gate
        jmp     @Return

@TechniqueToggle:
        lda     z:SFX_joy1trig
        and     #JOY_SELECT
        beq     @AngleControls
        lda     technique
        inc
        cmp     #RUNTIME_MENU_TECHNIQUE_COUNT
        bcc     :+
        lda     #$0000
:
        sta     technique
        inc     control_dirty

@AngleControls:
        lda     demo_mode
        beq     @ManualControls
        jmp     @Clamp
@ManualControls:
        lda     z:SFX_joy1trig
        and     #JOY_L
        beq     @NextMonsterCamera
        jsr     SelectPreviousMonsterCamera
        jmp     @Clamp
@NextMonsterCamera:
        lda     z:SFX_joy1trig
        and     #JOY_R
        beq     @AngleStep
        jsr     SelectNextMonsterCamera
        jmp     @Clamp

@AngleStep:
        lda     control_divider
        and     #$0001
        bne     @MovementControls
        lda     z:SFX_joy1cont
        and     #JOY_LEFT
        beq     @YawRight
        lda     yaw_index
        dec
        and     #$001F
        sta     yaw_index
        inc     control_dirty
        bra     @PitchUp
@YawRight:
        lda     z:SFX_joy1cont
        and     #JOY_RIGHT
        beq     @PitchUp
        lda     yaw_index
        inc
        and     #$001F
        sta     yaw_index
        inc     control_dirty

@PitchUp:
        lda     z:SFX_joy1cont
        and     #JOY_UP
        beq     @PitchDown
        lda     pitch_level
        cmp     #CAMERA_PITCH_MAX
        beq     @MovementControls
        inc
        sta     pitch_level
        inc     control_dirty
        bra     @MovementControls
@PitchDown:
        lda     z:SFX_joy1cont
        and     #JOY_DOWN
        beq     @MovementControls
        lda     pitch_level
        cmp     #CAMERA_PITCH_MIN
        beq     @MovementControls
        dec
        sta     pitch_level
        inc     control_dirty

@MovementControls:
        lda     z:SFX_joy1cont
        and     #(JOY_X | JOY_B)
        beq     @StrafeBasis
        jsr     BuildCameraForwardVector

        lda     z:SFX_joy1cont
        and     #JOY_X
        beq     @Backward
        lda     camera_x
        clc
        adc     camera_forward_x
        sta     camera_x
        lda     camera_y
        clc
        adc     camera_forward_y
        sta     camera_y
        lda     camera_z
        clc
        adc     camera_forward_z
        sta     camera_z
        inc     control_dirty
@Backward:
        lda     z:SFX_joy1cont
        and     #JOY_B
        beq     @StrafeBasis
        lda     camera_x
        sec
        sbc     camera_forward_x
        sta     camera_x
        lda     camera_y
        sec
        sbc     camera_forward_y
        sta     camera_y
        lda     camera_z
        sec
        sbc     camera_forward_z
        sta     camera_z
        inc     control_dirty

@StrafeBasis:
        lda     yaw_index
        and     #$001F
        asl
        tax

@StrafeLeft:
        lda     z:SFX_joy1cont
        and     #JOY_Y
        beq     @StrafeRight
        lda     camera_x
        clc
        adc     f:BSPCameraMoveSin,x
        sta     camera_x
        lda     camera_y
        sec
        sbc     f:BSPCameraMoveCos,x
        sta     camera_y
        inc     control_dirty
@StrafeRight:
        lda     z:SFX_joy1cont
        and     #JOY_A
        beq     @Clamp
        lda     camera_x
        sec
        sbc     f:BSPCameraMoveSin,x
        sta     camera_x
        lda     camera_y
        clc
        adc     f:BSPCameraMoveCos,x
        sta     camera_y
        inc     control_dirty

@Clamp:
        lda     control_dirty
        beq     @Return
        jsr     ClampCamera
        inc     control_revision
@Return:
        RW_forced a8i16
        rts

; L/R cycle the BSP entity-order monster viewpoints at the default player eye
; height. The invalid startup index makes first R select zero and first L last.
SelectNextMonsterCamera:
        RW_assume a16i16
        lda     monster_camera_index
        inc
        cmp     #BSP_MONSTER_CAMERA_COUNT
        bcc     @StoreNext
        lda     #$0000
@StoreNext:
        sta     monster_camera_index
        bra     LoadMonsterCamera

SelectPreviousMonsterCamera:
        RW_assume a16i16
        lda     monster_camera_index
        cmp     #BSP_MONSTER_CAMERA_COUNT
        bcs     @Wrap
        cmp     #$0000
        beq     @Wrap
        dec
        bra     @StorePrevious
@Wrap:
        lda     #BSP_MONSTER_CAMERA_COUNT-1
@StorePrevious:
        sta     monster_camera_index

LoadMonsterCamera:
        asl
        asl
        asl
        tax
        lda     f:QuakeBSPMonsterCameras+0,x
        sta     camera_x
        lda     f:QuakeBSPMonsterCameras+2,x
        sta     camera_y
        lda     f:QuakeBSPMonsterCameras+4,x
        sta     camera_z
        lda     f:QuakeBSPMonsterCameras+6,x
        sta     yaw_index
        stz     pitch_level
        inc     control_dirty
        rts

; Build the camera's full forward vector at the existing Q8 step length.
; Horizontal yaw components and pitch cosine are both Q5; Z is already Q5.
BuildCameraForwardVector:
        RW_assume a16i16
        lda     pitch_level
        and     #$001F
        asl
        tax
        lda     f:BSPCameraMoveCos,x
        sta     camera_forward_pitch_cos
        lda     f:BSPCameraMoveSin,x
        sta     camera_forward_z

        lda     yaw_index
        and     #$001F
        asl
        tax
        lda     f:BSPCameraMoveCos,x
        tax
        jsr     ScaleCameraForwardHorizontal
        sta     camera_forward_x

        lda     yaw_index
        and     #$001F
        asl
        tax
        lda     f:BSPCameraMoveSin,x
        tax
        jsr     ScaleCameraForwardHorizontal
        sta     camera_forward_y
        rts

; Signed round-to-nearest of X * pitchCos / 32. The Mode-7 multiplier remains
; available in this Mode-3 VBlank path and returns the bounded product in MPYL.
ScaleCameraForwardHorizontal:
        RW_assume a16i16
        RW      a8
        lda     camera_forward_pitch_cos
        muls    x, a
        RW      a16
        lda     MPYL
        bpl     @Positive
        neg
        clc
        adc     #CAMERA_FORWARD_SCALE_ROUND
        lsr
        lsr
        lsr
        lsr
        lsr
        neg
        rts
@Positive:
        clc
        adc     #CAMERA_FORWARD_SCALE_ROUND
        lsr
        lsr
        lsr
        lsr
        lsr
        rts

ClampCamera:
        RW_assume a16i16
        lda     camera_x
        bpl     @XPositive
        cmp     #BSP_WORLD_COORD_MIN_X_Q8
        bcs     @Y
        lda     #BSP_WORLD_COORD_MIN_X_Q8
        sta     camera_x
        bra     @Y
@XPositive:
        cmp     #BSP_WORLD_COORD_MAX_X_Q8+1
        bcc     @Y
        lda     #BSP_WORLD_COORD_MAX_X_Q8
        sta     camera_x
@Y:
        lda     camera_y
        bpl     @YPositive
        cmp     #BSP_WORLD_COORD_MIN_Y_Q8
        bcs     @Z
        lda     #BSP_WORLD_COORD_MIN_Y_Q8
        sta     camera_y
        bra     @Z
@YPositive:
        cmp     #BSP_WORLD_COORD_MAX_Y_Q8+1
        bcc     @Z
        lda     #BSP_WORLD_COORD_MAX_Y_Q8
        sta     camera_y
@Z:
        lda     camera_z
        bpl     @ZPositive
        cmp     #BSP_WORLD_COORD_MIN_Z_Q8
        bcs     @ClampDone
        lda     #BSP_WORLD_COORD_MIN_Z_Q8
        sta     camera_z
        rts
@ZPositive:
        cmp     #BSP_WORLD_COORD_MAX_Z_Q8+1
        bcc     @ClampDone
        lda     #BSP_WORLD_COORD_MAX_Z_Q8
        sta     camera_z
@ClampDone:
        rts

.segment "RODATA"
QuakeBSPMonsterCameras:
        .incbin "../Data/QuakeBSPMonsterCameras.bin"
QuakeBSPMonsterCamerasEnd:
.assert QuakeBSPMonsterCamerasEnd - QuakeBSPMonsterCameras = BSP_MONSTER_CAMERA_COUNT * BSP_MONSTER_CAMERA_RECORD_BYTES, error, "Monster-camera table size disagrees with generated constants"

RuntimeMenuPalette:
        .incbin "../Data/QuakeBSPTexturePalette.bin", 480, 32
RuntimeMenuPaletteEnd:
.assert RuntimeMenuPaletteEnd - RuntimeMenuPalette = 32, error, "Runtime-menu palette tail size changed"

RuntimeMenuText:
        .byte   " RESUME           "
        .byte   " PLAYBACK ORDERED "
        .byte   " TEXTURES ON      "
        .byte   " LIGHTING LIGHTMAP"
        .byte   " D-BRUSHES ON     "
        .byte   " T-DITHER OFF     "
        .byte   " RESTART          "
RuntimeMenuTextEnd:
.assert RuntimeMenuTextEnd - RuntimeMenuText = RUNTIME_MENU_ROW_COUNT * RUNTIME_MENU_COLUMNS, error, "Runtime-menu text dimensions changed"

RuntimeMenuPlaybackValues:
        .byte   "ORDERED "
        .byte   "REALTIME"
        .byte   "FLY     "
        .byte   "1/2 REAL"
        .byte   "1/4 REAL"
RuntimeMenuPlaybackValuesEnd:
.assert RuntimeMenuPlaybackValuesEnd - RuntimeMenuPlaybackValues = RUNTIME_MENU_PLAYBACK_COUNT * 8, error, "Runtime-menu playback values must stay fixed-width"

RuntimeMenuPlaybackNext:
        .word   RUNTIME_MENU_PLAYBACK_REALTIME
        .word   RUNTIME_MENU_PLAYBACK_HALF
        .word   RUNTIME_MENU_PLAYBACK_ORDERED
        .word   RUNTIME_MENU_PLAYBACK_QUARTER
        .word   RUNTIME_MENU_PLAYBACK_FLY
RuntimeMenuPlaybackPrevious:
        .word   RUNTIME_MENU_PLAYBACK_FLY
        .word   RUNTIME_MENU_PLAYBACK_ORDERED
        .word   RUNTIME_MENU_PLAYBACK_QUARTER
        .word   RUNTIME_MENU_PLAYBACK_REALTIME
        .word   RUNTIME_MENU_PLAYBACK_HALF

RuntimeMenuLightingValues:
        .byte   "NONE    "
        .byte   "DISTANCE"
        .byte   "LIGHTMAP"
RuntimeMenuLightingValuesEnd:
.assert RuntimeMenuLightingValuesEnd - RuntimeMenuLightingValues = 3 * 8, error, "Runtime-menu lighting values must stay fixed-width"

RuntimeMenuToggleValues:
        .byte   "OFF     "
        .byte   "ON      "
RuntimeMenuToggleValuesEnd:
.assert RuntimeMenuToggleValuesEnd - RuntimeMenuToggleValues = 2 * 8, error, "Runtime-menu toggle values must stay fixed-width"

.include "RuntimeMenuFont.s"
.segment "CODE"
