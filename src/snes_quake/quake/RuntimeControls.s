; Modal runtime menu and Controller-1 policy for QuakeBSP.
;
; Start is exclusively the menu key. The closed-menu Select shortcut remains
; available for benchmark/tool compatibility. Host-only setup uses the
; versioned frame-zero boot-parameter ABI rather than a hidden second pad.

.macro RecenterFlyCameraPose
        lda     #BSP_START_YAW_INDEX*CAMERA_ANGLE_LEGACY_STEP
        sta     yaw_index
        stz     pitch_level
        lda     #BSP_FLY_START_X_Q8
        sta     camera_x
        lda     #BSP_FLY_START_Y_Q8
        sta     camera_y
        lda     #BSP_FLY_START_Z_Q8
        sta     camera_z
        inc     control_revision
        jsr     InvalidateScheduledFrameIdentity
.endmacro

RUNTIME_MENU_FIRST_ROW    = 0
.ifdef PLAYABLE_MAP_ID
RUNTIME_MENU_ROW_PLAYBACK = RUNTIME_MENU_FIRST_ROW
RUNTIME_MENU_ROW_RENDER   = 1
RUNTIME_MENU_ROW_BRUSHES  = 2
RUNTIME_MENU_ROW_ENTITIES = 3
RUNTIME_MENU_ROW_SCALE    = 4
RUNTIME_MENU_ROW_SKILL    = 5
RUNTIME_MENU_ROW_ALWAYS_RUN = 6
RUNTIME_MENU_ROW_RESTART  = 7
RUNTIME_MENU_ROW_COUNT    = 8
RUNTIME_MENU_VALUE_BYTES  = 3
RUNTIME_MENU_PLAYBACK_VALUE_BYTES = 7
RUNTIME_MENU_RENDER_VALUE_BYTES = 9
RUNTIME_MENU_SKILL_VALUE_BYTES = 9
RUNTIME_MENU_GAP_X        = 128
RUNTIME_MENU_GAP_COLUMNS  = 1
RUNTIME_MENU_COLUMNS      = 22
RUNTIME_MENU_Y            = 72
RUNTIME_MENU_RESTART_GAP_PIXELS = 8
RUNTIME_MENU_HIGHLIGHT_X = 40
RUNTIME_MENU_HIGHLIGHT_COLUMNS = 22
RUNTIME_MENU_HIGHLIGHT_OAM = RUNTIME_MENU_USED_ENTRIES * RUNTIME_MENU_ENTRY_BYTES
.assert RUNTIME_MENU_USED_ENTRIES + RUNTIME_MENU_HIGHLIGHT_COLUMNS <= 128, error, "Runtime menu and highlight exceed OAM capacity"
.else
RUNTIME_MENU_ROW_PLAYBACK = 1
RUNTIME_MENU_ROW_TEXTURES = 2
RUNTIME_MENU_ROW_LIGHTING = 3
RUNTIME_MENU_ROW_BRUSHES  = 4
RUNTIME_MENU_ROW_ENTITIES = 5
RUNTIME_MENU_ROW_SCALE    = 6
RUNTIME_MENU_ROW_RESTART  = 7
.if BSP_QUAKEC_GAMEPLAY
RUNTIME_MENU_ROW_SKILL    = 8
RUNTIME_MENU_ROW_COUNT    = 9
RUNTIME_MENU_SKILL_COLUMNS = 16
.else
RUNTIME_MENU_ROW_COUNT    = 8
.endif
RUNTIME_MENU_COLUMNS      = 14
RUNTIME_MENU_VALUE_COLUMN = 8
RUNTIME_MENU_VALUE_BYTES  = 6
RUNTIME_MENU_PLAYBACK_VALUE_COLUMN = 4
RUNTIME_MENU_PLAYBACK_VALUE_BYTES  = 10
RUNTIME_MENU_X            = 72
RUNTIME_MENU_Y            = 72
.endif
RUNTIME_MENU_ENTRY_BYTES  = 4
RUNTIME_MENU_USED_ENTRIES = RuntimeMenuTextEnd - RuntimeMenuText
RUNTIME_MENU_PLAYBACK_OAM = (RuntimeMenuTextPlayback - RuntimeMenuText) * RUNTIME_MENU_ENTRY_BYTES
.ifndef PLAYABLE_MAP_ID
RUNTIME_MENU_TEXTURES_OAM = (RuntimeMenuTextTextures - RuntimeMenuText) * RUNTIME_MENU_ENTRY_BYTES
RUNTIME_MENU_LIGHTING_OAM = (RuntimeMenuTextLighting - RuntimeMenuText) * RUNTIME_MENU_ENTRY_BYTES
.endif
RUNTIME_MENU_BRUSHES_OAM  = (RuntimeMenuTextBrushes - RuntimeMenuText) * RUNTIME_MENU_ENTRY_BYTES
RUNTIME_MENU_ENTITIES_OAM = (RuntimeMenuTextEntities - RuntimeMenuText) * RUNTIME_MENU_ENTRY_BYTES
RUNTIME_MENU_SCALE_OAM    = (RuntimeMenuTextScale - RuntimeMenuText) * RUNTIME_MENU_ENTRY_BYTES
.if BSP_QUAKEC_GAMEPLAY
RUNTIME_MENU_SKILL_OAM    = (RuntimeMenuTextSkill - RuntimeMenuText) * RUNTIME_MENU_ENTRY_BYTES
.endif
.ifdef PLAYABLE_MAP_ID
RUNTIME_MENU_ALWAYS_RUN_OAM = (RuntimeMenuTextAlwaysRun - RuntimeMenuText) * RUNTIME_MENU_ENTRY_BYTES
.endif
RUNTIME_MENU_OBJ_ATTR     = $3F ; name bit 8, palette 7, priority 3
.ifndef PLAYABLE_MAP_ID
RUNTIME_MENU_BLACK_BACKDROP = CG_BACK_ON | CG_MODE_SUB
.endif
RUNTIME_MENU_COLOR_WINDOW_CLOSED = $30 ; LibSFX idle state: prevent math
RUNTIME_MENU_TILE_SPACE   = .lobyte(RUNTIME_MENU_TILE_BASE)
RUNTIME_MENU_TILE_CURSOR  = .lobyte(RUNTIME_MENU_TILE_BASE + (62 - RUNTIME_MENU_ASCII_FIRST))
RUNTIME_MENU_PLAYBACK_FLY          = 2
RUNTIME_MENU_PLAYBACK_FLY3X        = 6
RUNTIME_MENU_LIGHTING_NONE     = 0
RUNTIME_MENU_LIGHTING_LIGHTMAP = 1
RUNTIME_MENU_TEXTURES_OFF       = 0
RUNTIME_MENU_TEXTURES_ON        = 1
RUNTIME_MENU_TEXTURES_COUNT     = 2
RUNTIME_MENU_TECHNIQUE_TEXTURED_NONE = 2
RUNTIME_MENU_TECHNIQUE_FACE_COLORS = 3
RUNTIME_MENU_TECHNIQUE_TEXTURED_LIGHTMAP = BSP_TECHNIQUE_TEXTURED_LIGHTMAP
RUNTIME_MENU_TECHNIQUE_UNTEXTURED_LIGHTMAP = BSP_TECHNIQUE_UNTEXTURED_LIGHTMAP
CAMERA_PITCH_MIN               = .loword(-CAMERA_ANGLE_QUARTER) ; -90 degrees
CAMERA_PITCH_MAX               = CAMERA_ANGLE_QUARTER ; +90 degrees
CAMERA_FORWARD_SCALE_ROUND     = $0010

BOOT_PARAMETERS_VERSION       = $0004
BOOT_PARAMETERS_SIZE          = $0018
BOOT_PARAMETERS_REQUEST_LO    = $4251 ; "QB"
BOOT_PARAMETERS_REQUEST_HI    = $3450 ; "P4"
BOOT_PARAMETERS_ACK_HI        = $3441 ; "A4"
BOOT_PARAMETERS_ERROR_HI      = $3445 ; "E4"
BOOT_PARAMETERS_PRESENT_PLAYBACK = $0001
BOOT_PARAMETERS_PRESENT_TECHNIQUE = $0002
BOOT_PARAMETERS_PRESENT_BRUSHES = $0004
BOOT_PARAMETERS_PRESENT_FIXED_STEP_SAMPLE = $0008
BOOT_PARAMETERS_PRESENT_COVERAGE = $0010
BOOT_PARAMETERS_PRESENT_ORDERED_SOURCE_POSE = $0020
BOOT_PARAMETERS_PRESENT_ORDERED_STRIDE = $0040
BOOT_PARAMETERS_PRESENT_ALL   = $007F
BOOT_PARAMETERS_STATUS_APPLIED = $01
BOOT_PARAMETERS_ERROR_HEADER  = $E1
BOOT_PARAMETERS_ERROR_MASK    = $E2
BOOT_PARAMETERS_ERROR_PLAYBACK = $E3
BOOT_PARAMETERS_ERROR_TECHNIQUE = $E4
BOOT_PARAMETERS_ERROR_BRUSHES = $E5
BOOT_PARAMETERS_ERROR_FIXED_STEP_SAMPLE = $E6
BOOT_PARAMETERS_ERROR_COVERAGE = $E7
BOOT_PARAMETERS_ERROR_ORDERED_SOURCE_POSE = $E8
BOOT_PARAMETERS_ERROR_ORDERED_STRIDE = $E9

.assert RUNTIME_MENU_USED_ENTRIES <= 128, error, "Runtime menu exceeds SNES OAM capacity"
.assert RUNTIME_MENU_COLUMNS <= 32, error, "Runtime menu exceeds the per-scanline OBJ limit"
.ifndef PLAYABLE_MAP_ID
.assert RUNTIME_MENU_VALUE_COLUMN + RUNTIME_MENU_VALUE_BYTES = RUNTIME_MENU_COLUMNS, error, "Runtime-menu values must end at the menu edge"
.assert RUNTIME_MENU_PLAYBACK_VALUE_COLUMN + RUNTIME_MENU_PLAYBACK_VALUE_BYTES = RUNTIME_MENU_COLUMNS, error, "Runtime-menu playback value must end at the menu edge"
.endif
.assert BOOT_PARAMETERS_SIZE = GSU_BOOT_PARAMETERS_BYTES, error, "Boot parameter ABI size disagrees with cartridge RAM"

; Consume an optional one-shot host request before the first render. The host
; writes offsets 4..23 while Mesen is paused at power-on and commits the magic
; at offsets 0..3 last. Validation is a separate pass, so malformed requests
; leave the normal startup defaults untouched. Status is published before the
; high acknowledgement word changes the request into "QBA4" or "QBE4".
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
        and     #$FF80
        beq     :+
        jmp     BootParametersErrorMask
:

        lda     f:GSU_BOOT_PARAMETERS+10
        and     #BOOT_PARAMETERS_PRESENT_PLAYBACK
        beq     BootParametersValidateTechnique
        lda     f:GSU_BOOT_PARAMETERS+12
        and     #$00FF
        cmp     #RUNTIME_MENU_PLAYBACK_FLY
        beq     BootParametersValidateTechnique
        cmp     #RUNTIME_MENU_PLAYBACK_FLY3X
        beq     BootParametersValidateTechnique
        jmp     BootParametersErrorPlayback
BootParametersValidateTechnique:
        lda     f:GSU_BOOT_PARAMETERS+10
        and     #BOOT_PARAMETERS_PRESENT_TECHNIQUE
        beq     BootParametersValidateBrushes
        lda     f:GSU_BOOT_PARAMETERS+13
        and     #$00FF
.ifdef PLAYABLE_MAP_ID
        cmp     #RUNTIME_MENU_TECHNIQUE_FACE_COLORS
        beq     :+
.endif
        cmp     #RUNTIME_MENU_TECHNIQUE_TEXTURED_NONE
        beq     :+
        cmp     #RUNTIME_MENU_TECHNIQUE_TEXTURED_LIGHTMAP
        beq     :+
        cmp     #RUNTIME_MENU_TECHNIQUE_UNTEXTURED_LIGHTMAP
        beq     :+
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
        jmp     BootParametersErrorFixedStepSample

BootParametersValidateCoverage:
        lda     f:GSU_BOOT_PARAMETERS+10
        and     #BOOT_PARAMETERS_PRESENT_COVERAGE
        beq     BootParametersValidateOrderedSourcePose
        lda     f:GSU_BOOT_PARAMETERS+16
        and     #$00FF
        cmp     #$0003
        bcc     BootParametersValidateOrderedSourcePose
        jmp     BootParametersErrorCoverage

BootParametersValidateOrderedSourcePose:
        lda     f:GSU_BOOT_PARAMETERS+10
        and     #BOOT_PARAMETERS_PRESENT_ORDERED_SOURCE_POSE
        beq     BootParametersValidateOrderedStride
        jmp     BootParametersErrorOrderedSourcePose

BootParametersValidateOrderedStride:
        lda     f:GSU_BOOT_PARAMETERS+10
        and     #BOOT_PARAMETERS_PRESENT_ORDERED_STRIDE
        beq     BootParametersApplyPlayback
        jmp     BootParametersErrorOrderedStride

BootParametersApplyPlayback:
        lda     f:GSU_BOOT_PARAMETERS+10
        and     #BOOT_PARAMETERS_PRESENT_PLAYBACK
        bne     :+
        jmp     BootParametersApplyTechnique
:
        lda     f:GSU_BOOT_PARAMETERS+12
        and     #$00FF
        cmp     #RUNTIME_MENU_PLAYBACK_FLY3X
        beq     @Three
        stz     runtime_menu_draft_scale
        bra     @ApplyViewport
@Three:
        lda     #RUNTIME_MENU_SCALE_X3
        sta     runtime_menu_draft_scale
@ApplyViewport:
        jsr     RequestFlyViewport

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
        beq     BootParametersApplyCoverage
        lda     f:GSU_BOOT_PARAMETERS+14
        and     #$00FF
        and     #BSP_BRUSH_DYNAMIC_REPLAY_SUPPORTED
        sta     dynamic_brushes_enabled
        sta     runtime_menu_draft_brushes

BootParametersApplyCoverage:
        lda     f:GSU_BOOT_PARAMETERS+10
        and     #BOOT_PARAMETERS_PRESENT_COVERAGE
        beq     BootParametersPublishApplied
        lda     f:GSU_BOOT_PARAMETERS+16
        and     #$00FF
        sta     coverage_debug

BootParametersPublishApplied:
        RW      a8
        lda     #BOOT_PARAMETERS_STATUS_APPLIED
        sta     f:GSU_BOOT_PARAMETERS+23
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
        bra     BootParametersPublishError
BootParametersErrorOrderedSourcePose:
        lda     #BOOT_PARAMETERS_ERROR_ORDERED_SOURCE_POSE
        bra     BootParametersPublishError
BootParametersErrorOrderedStride:
        lda     #BOOT_PARAMETERS_ERROR_ORDERED_STRIDE
        bra     BootParametersPublishError
BootParametersPublishError:
        RW      a8
        sta     f:GSU_BOOT_PARAMETERS+23
        RW      a16
        lda     #BOOT_PARAMETERS_ERROR_HI
        sta     f:GSU_BOOT_PARAMETERS+2
BootParametersDone:
        RW_forced a16i16
        rts

; Called once per VBlank before Controller-1 gameplay input. While open, the
; menu consumes Controller 1 and the caller skips camera controls.
UpdateRuntimeMenu:
        RW_assume a16i16
.if BSP_QUAKEC_GAMEPLAY
        lda     quake_restart_pending
        beq     :+
        jmp     RuntimeMenuUpdateDone
:
.endif
        lda     runtime_menu_open
        bne     RuntimeMenuHandleOpen
.ifdef PLAYABLE_WEAPON_OBJ
        lda     weapon_obj_menu_pending
        beq     :+
        lda     SFX_inidisp
        and     #$0080
        ora     weapon_obj_presented_mask
        beq     @Ready
        rts
@Ready:
        stz     weapon_obj_menu_pending
        bra     @Show
:
.endif
.ifdef QC_QUEUED_INPUT
        lda     qc_input_replay
        bne     :+
        jsr     GameplayLiveMenuInput
        bcs     @Open
        jmp     RuntimeMenuUpdateDone
:
.endif
        lda     z:SFX_joy1trig
        and     #JOY_START
.ifdef PLAYABLE_WEAPON_OBJ
        bne     @Open
        rts
.else
        beq     RuntimeMenuUpdateDone
.endif
@Open:
.ifdef PLAYABLE_WEAPON_OBJ
        lda     SFX_inidisp
        and     #$0080
        ora     weapon_obj_presented_mask
        beq     @Show
        lda     #1
        sta     weapon_obj_menu_pending
        jsr     InvalidateScheduledFrameIdentity
        bra     RuntimeMenuUpdateDone
@Show:
.endif
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
        lda     #RUNTIME_MENU_FIRST_ROW
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
.ifndef PLAYABLE_MAP_ID
        beq     RuntimeMenuActivateClose
.endif
        cmp     #RUNTIME_MENU_ROW_RESTART
        beq     RuntimeMenuActivateRestart
.ifdef PLAYABLE_MAP_ID
        jsr     PlayableMenuActivateValue
.else
        jsr     RuntimeMenuNextValue
.endif
        bra     RuntimeMenuUpdateDone
RuntimeMenuActivateRestart:
        lda     #$0001
        sta     runtime_menu_restart_action
RuntimeMenuActivateClose:
        jsr     CloseRuntimeMenu
RuntimeMenuUpdateDone:
        RW_assume a16i16
        rts

OpenRuntimeMenu:
        RW_assume a16i16
        stz     fly_mouse_dx
        stz     fly_mouse_dy
        jsr     InvalidateScheduledFrameIdentity
        jsr     SyncRuntimeMenuDrafts
        stz     runtime_menu_selection
        stz     runtime_menu_restart_action
        lda     #$0001
        sta     runtime_menu_open
.ifdef PLAYABLE_WEAPON_OBJ
        stz     weapon_obj_oam_word
        stz     status_hud_obj_blanked
        RW      a8
        lda     #objsel(VRAM_RUNTIME_MENU_OBJ_BASE, OBJ_8x8_16x16, 0)
        sta     OBJSEL
        lda     weapon_obj_menu_shadow_dirty
        beq     :+
        stz     weapon_obj_menu_shadow_dirty
        stz     RuntimeMenuBuildRow+1
        jsr     BuildRuntimeMenuOAM
:
        RW      a16
.endif
        jsr     RefreshRuntimeMenuOAM
        RW      a8
.ifdef PLAYABLE_MAP_ID
        lda     SFX_inidisp
        sta     runtime_menu_saved_inidisp
        lda     #inidisp(ON, DISP_BRIGHTNESS_MAX)
        sta     SFX_inidisp
        stz     CGADD
        lda     CGDATAREAD
        sta     runtime_menu_saved_backdrop
        lda     CGDATAREAD
        and     #$7f
        sta     runtime_menu_saved_backdrop+1
        stz     HDMAEN
        stz     TMW
.endif
        lda     #tm(OFF, OFF, OFF, OFF, ON)
        sta     TM
.ifdef PLAYABLE_MAP_ID
        stz     CGADSUB
        lda     #RUNTIME_MENU_COLOR_WINDOW_CLOSED
        sta     CGSWSEL
        stz     CGADD
        stz     CGDATA
        stz     CGDATA
.else
        ; Pending demo uploads may still change CGRAM. Subtract white from
        ; the backdrop only so those writes cannot color the menu background.
        lda     #inidisp(ON, DISP_BRIGHTNESS_MAX)
        sta     SFX_inidisp
        lda     #$FF
        sta     COLDATA
        stz     CGSWSEL
        lda     #RUNTIME_MENU_BLACK_BACKDROP
        sta     CGADSUB
.endif
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
.ifdef PLAYABLE_MAP_ID
        lda     runtime_menu_saved_inidisp
        sta     SFX_inidisp
        stz     CGADD
        lda     runtime_menu_saved_backdrop
        sta     CGDATA
        lda     runtime_menu_saved_backdrop+1
        sta     CGDATA
.else
        lda     #CDAT_RED | CDAT_GREEN | CDAT_BLUE
        sta     COLDATA
        ; If a hidden format upload is unfinished, keep its partial page
        ; blank until the regular presentation path commits the new format.
        lda     upload_active
        beq     :+
        lda     upload_format
        cmp     presented_format
        beq     :+
        lda     #inidisp(OFF, DISP_BRIGHTNESS_MIN)
        sta     SFX_inidisp
:
.endif
        RW_forced a16i16
.ifdef PLAYABLE_WEAPON_OBJ
        jsr     WeaponObjPresent
.endif
        rts

; Synchronize the supported renderer draft fields before displaying the menu.
SyncRuntimeMenuDrafts:
        RW_assume a16i16
.ifdef PLAYABLE_MAP_ID
        lda     #PLAYABLE_MAP_ID
        sta     runtime_menu_draft_map
.endif
        lda     #RUNTIME_MENU_PLAYBACK_FLY
        sta     runtime_menu_draft_playback
        jsr     SyncRuntimeMenuScaleDraft
        lda     technique
        sta     runtime_menu_draft_technique
.ifndef PLAYABLE_MAP_ID
        cmp     #RUNTIME_MENU_TECHNIQUE_TEXTURED_NONE
        beq     @TexturedNone
        cmp     #RUNTIME_MENU_TECHNIQUE_TEXTURED_LIGHTMAP
        beq     @TexturedLightmap
        stz     runtime_menu_draft_textures
        lda     #RUNTIME_MENU_LIGHTING_LIGHTMAP
        sta     runtime_menu_draft_lighting
        bra     @RendererReady
@TexturedNone:
        stz     runtime_menu_draft_lighting
        lda     #RUNTIME_MENU_TEXTURES_ON
        sta     runtime_menu_draft_textures
        bra     @RendererReady
@TexturedLightmap:
        lda     #RUNTIME_MENU_LIGHTING_LIGHTMAP
        sta     runtime_menu_draft_lighting
        lda     #RUNTIME_MENU_TEXTURES_ON
        sta     runtime_menu_draft_textures
@RendererReady:
.endif
        lda     dynamic_brushes_enabled
        sta     runtime_menu_draft_brushes
        lda     mdl_entities_enabled
        sta     runtime_menu_draft_entities
        rts

; Compose the texture and lighting drafts into a renderer technique.
.ifndef PLAYABLE_MAP_ID
ComposeRuntimeMenuTechnique:
        RW_assume a16i16
        lda     runtime_menu_draft_textures
        beq     @UntexturedLightmap
        lda     runtime_menu_draft_lighting
        beq     @TexturedNone
        lda     #RUNTIME_MENU_TECHNIQUE_TEXTURED_LIGHTMAP
        bra     @Store
@TexturedNone:
        lda     #RUNTIME_MENU_TECHNIQUE_TEXTURED_NONE
        bra     @Store
@UntexturedLightmap:
        lda     #RUNTIME_MENU_LIGHTING_LIGHTMAP
        sta     runtime_menu_draft_lighting
        lda     #RUNTIME_MENU_TECHNIQUE_UNTEXTURED_LIGHTMAP
@Store:
        sta     runtime_menu_draft_technique
        rts
.else
; Find the draft in display order. Unknown techniques show Full.
RuntimeMenuRenderIndex:
        RW_assume a16i16
        ldx     #0
        lda     runtime_menu_draft_technique
@Search:
        cmp     f:RuntimeMenuRenderTechniques,x
        beq     @Done
        inx
        inx
        cpx     #8
        bcc     @Search
        ldx     #0
@Done:
        rts

StoreRuntimeMenuRender:
        txa
        and     #6
        tax
        lda     f:RuntimeMenuRenderTechniques,x
        sta     runtime_menu_draft_technique
        jmp     RefreshRuntimeMenuOAM

.pushseg
.segment "RODATA"
RuntimeMenuRenderTechniques:
        .word   RUNTIME_MENU_TECHNIQUE_TEXTURED_LIGHTMAP, RUNTIME_MENU_TECHNIQUE_FACE_COLORS
        .word   RUNTIME_MENU_TECHNIQUE_TEXTURED_NONE, RUNTIME_MENU_TECHNIQUE_UNTEXTURED_LIGHTMAP
.popseg
.endif

; Public state application path for both the UI and host tooling:
;   runtime_menu_draft_technique: 2, 3 (playable only), 4, or 7
;   runtime_menu_draft_textures: 0 off, 1 on
;   runtime_menu_draft_lighting: 0 None, 1 LightMap
;   runtime_menu_draft_brushes: 0 off, 1 on
;   runtime_menu_draft_entities: 0 off, 1 on
; Set runtime_menu_restart_action for restart/recenter semantics.
ApplyRuntimeMenuSelection:
        RW_forced a16i16
        lda     runtime_menu_restart_action
        beq     @ApplyRenderer
        stz     runtime_menu_restart_action
.if BSP_QUAKEC_GAMEPLAY
        jsr     QueueQuakeRestart
.else
        RecenterFlyCameraPose
.endif

@ApplyRenderer:
        jsr     RequestFlyViewport
        lda     runtime_menu_draft_technique
        cmp     technique
        beq     @ApplyBrushes
        sta     technique
        inc     control_revision
        jsr     InvalidateScheduledFrameIdentity

@ApplyBrushes:
        lda     runtime_menu_draft_brushes
        and     #BSP_BRUSH_DYNAMIC_REPLAY_SUPPORTED
        cmp     dynamic_brushes_enabled
        beq     @ApplyEntities
        sta     dynamic_brushes_enabled
        jsr     InvalidateDynamicBrushRenderState
@ApplyEntities:
        lda     runtime_menu_draft_entities
        and     #BSP_RENDER_ENTITIES_SUPPORTED
        cmp     mdl_entities_enabled
        beq     @ApplyDone
        sta     mdl_entities_enabled
        ; The brush-capable renderer phase-overlays selector face-plane state.
        ; Force one selector rebuild before a world-only renderer can consume
        ; the packet after an entity-path transition.
        stz     active_packet_guard_status
        inc     control_revision
        jsr     InvalidateScheduledFrameIdentity
@ApplyDone:
        RW_forced a16i16
        rts

; Public force-render hook. Call after changing the enabled state or advancing
; the resolved brush replay row. The brush-capable renderer phase-overlays
; selector state, so feature-path transitions also invalidate the CPU's packet
; guard mirror and force one selector rebuild.
InvalidateDynamicBrushRenderState:
        RW_forced a16i16
        inc     dynamic_brush_revision
        inc     control_revision
        stz     active_packet_guard_status
        jsr     InvalidateScheduledFrameIdentity
        rts

RuntimeMenuPreviousValue:
        RW_assume a16i16
        lda     runtime_menu_selection
        cmp     #RUNTIME_MENU_ROW_PLAYBACK
        beq     @Playback
.ifdef PLAYABLE_MAP_ID
        cmp     #RUNTIME_MENU_ROW_RENDER
        beq     @Render
.else
        cmp     #RUNTIME_MENU_ROW_TEXTURES
        beq     @Textures
        cmp     #RUNTIME_MENU_ROW_LIGHTING
        beq     @Lighting
.endif
        cmp     #RUNTIME_MENU_ROW_BRUSHES
        beq     @Brushes
        cmp     #RUNTIME_MENU_ROW_ENTITIES
        beq     @Entities
        cmp     #RUNTIME_MENU_ROW_SCALE
        bne     :+
        jmp     PreviousRuntimeMenuScale
:
.ifdef PLAYABLE_MAP_ID
        cmp     #RUNTIME_MENU_ROW_ALWAYS_RUN
        bne     :+
        jmp     RuntimeMenuToggleAlwaysRun
:
.endif
.if BSP_QUAKEC_GAMEPLAY
        cmp     #RUNTIME_MENU_ROW_SKILL
        bne     :+
        lda     quake_skill_selected
        dec
        and     #3
        sta     quake_skill_selected
        jmp     RefreshRuntimeMenuOAM
:
.endif
        rts
@Playback:
.ifdef PLAYABLE_MAP_ID
        jmp     PlayableMenuPreviousMap
.else
        rts
.endif
.ifdef PLAYABLE_MAP_ID
@Render:
        jsr     RuntimeMenuRenderIndex
        dex
        dex
        jmp     StoreRuntimeMenuRender
.else
@Textures:
        lda     runtime_menu_draft_textures
        bne     :+
        lda     #RUNTIME_MENU_TEXTURES_COUNT
:
        dec
        sta     runtime_menu_draft_textures
        bne     :+
        lda     #RUNTIME_MENU_LIGHTING_LIGHTMAP
        sta     runtime_menu_draft_lighting
:
        jsr     ComposeRuntimeMenuTechnique
        bra     @Refresh
@Lighting:
        lda     runtime_menu_draft_textures
        beq     @Refresh
        lda     runtime_menu_draft_lighting
        bne     :+
        lda     #RUNTIME_MENU_LIGHTING_LIGHTMAP+1
:
        dec
        sta     runtime_menu_draft_lighting
        jsr     ComposeRuntimeMenuTechnique
        bra     @Refresh
.endif
@Brushes:
        lda     runtime_menu_draft_brushes
        eor     #$0001
        and     #BSP_BRUSH_DYNAMIC_REPLAY_SUPPORTED
        sta     runtime_menu_draft_brushes
        bra     @Refresh
@Entities:
        lda     runtime_menu_draft_entities
        eor     #$0001
        and     #BSP_RENDER_ENTITIES_SUPPORTED
        sta     runtime_menu_draft_entities
        bra     @Refresh
@Refresh:
        jsr     RefreshRuntimeMenuOAM
        rts

RuntimeMenuNextValue:
        RW_assume a16i16
        lda     runtime_menu_selection
        cmp     #RUNTIME_MENU_ROW_PLAYBACK
        beq     @NextPlayback
.ifdef PLAYABLE_MAP_ID
        cmp     #RUNTIME_MENU_ROW_RENDER
        beq     @NextRender
.else
        cmp     #RUNTIME_MENU_ROW_TEXTURES
        beq     @NextTextures
        cmp     #RUNTIME_MENU_ROW_LIGHTING
        beq     @NextLighting
.endif
        cmp     #RUNTIME_MENU_ROW_BRUSHES
        beq     @NextBrushes
        cmp     #RUNTIME_MENU_ROW_ENTITIES
        beq     @NextEntities
        cmp     #RUNTIME_MENU_ROW_SCALE
        bne     :+
        jmp     NextRuntimeMenuScale
:
.ifdef PLAYABLE_MAP_ID
        cmp     #RUNTIME_MENU_ROW_ALWAYS_RUN
        bne     :+
        jmp     RuntimeMenuToggleAlwaysRun
:
.endif
.if BSP_QUAKEC_GAMEPLAY
        cmp     #RUNTIME_MENU_ROW_SKILL
        bne     :+
        lda     quake_skill_selected
        inc
        and     #3
        sta     quake_skill_selected
        jmp     RefreshRuntimeMenuOAM
:
.endif
        rts
@NextPlayback:
.ifdef PLAYABLE_MAP_ID
        jmp     PlayableMenuNextMap
.else
        rts
.endif
.ifdef PLAYABLE_MAP_ID
@NextRender:
        jsr     RuntimeMenuRenderIndex
        inx
        inx
        jmp     StoreRuntimeMenuRender
.else
@NextTextures:
        lda     runtime_menu_draft_textures
        inc
        cmp     #RUNTIME_MENU_TEXTURES_COUNT
        bcc     :+
        lda     #RUNTIME_MENU_TEXTURES_OFF
:
        sta     runtime_menu_draft_textures
        bne     :+
        lda     #RUNTIME_MENU_LIGHTING_LIGHTMAP
        sta     runtime_menu_draft_lighting
:
        jsr     ComposeRuntimeMenuTechnique
        bra     @NextRefresh
@NextLighting:
        lda     runtime_menu_draft_textures
        beq     @NextRefresh
        lda     runtime_menu_draft_lighting
        inc
        cmp     #RUNTIME_MENU_LIGHTING_LIGHTMAP+1
        bcc     :+
        lda     #RUNTIME_MENU_LIGHTING_NONE
:
        sta     runtime_menu_draft_lighting
        jsr     ComposeRuntimeMenuTechnique
        bra     @NextRefresh
.endif
@NextBrushes:
        lda     runtime_menu_draft_brushes
        eor     #$0001
        and     #BSP_BRUSH_DYNAMIC_REPLAY_SUPPORTED
        sta     runtime_menu_draft_brushes
        bra     @NextRefresh
@NextEntities:
        lda     runtime_menu_draft_entities
        eor     #$0001
        and     #BSP_RENDER_ENTITIES_SUPPORTED
        sta     runtime_menu_draft_entities
        bra     @NextRefresh
@NextRefresh:
        jsr     RefreshRuntimeMenuOAM
        rts

.include "RuntimeMenuOAM.s"

; Closed-menu controller and mouse look.
UpdateCameraControls:
        RW_forced a16i16
.if .defined(QC_QUEUED_INPUT) .and .defined(PLAYABLE_RECORDED_TAPE)
        lda     qc_input_replay
        bpl     :+
        rts
:
.endif
        stz     control_dirty
        inc     control_divider
        lda     #CAMERA_ANGLE_LEGACY_STEP
        sta     fly_look_step_limit
.ifndef QC_QUEUED_INPUT
        lda     fly_playback_mode
        cmp     #RUNTIME_MENU_PLAYBACK_FLY3X
        bne     :+
        lsr     fly_look_step_limit
:
.endif
        lda     z:SFX_joy1cont
        sta     camera_input_buttons
.ifdef QC_QUEUED_INPUT
        ldx     qc_input_replay
        bne     :+
        jsr     MapLiveGameplayButtons
:
.endif
        jsr     ReadFlyMouseControls

        lda     runtime_menu_release_gate
        beq     @TechniqueToggle
        lda     camera_input_buttons
.ifdef QC_QUEUED_INPUT
        ora     z:SFX_joy1cont
  .ifdef PLAYABLE_RECORDED_TAPE
        pha
        lda     qc_input_replay
        bit     #QC_INPUT_RECORDED_TAPE
        beq     :+
        pla
        and     #$FFFF-JOY_SELECT
        bra     :++
:       pla
:
  .endif
.endif
        beq     :+
        jmp     @Return
:
        stz     runtime_menu_release_gate
        jmp     @Return

@TechniqueToggle:
.ifdef QC_QUEUED_INPUT
        lda     qc_input_replay
  .ifdef PLAYABLE_RECORDED_TAPE
        cmp     #1                     ; Legacy timing tape SELECT changes technique.
        bne     @AngleControls
  .else
        beq     @AngleControls
  .endif
.endif
.if BSP_QUAKEC_GAMEPLAY && !.defined(QC_QUEUED_INPUT)
        lda     f:ShotgunPlayer+QC_FIELD_HEALTH
        beq     @CheckRespawn
        bpl     @TechniqueInput
@CheckRespawn:
        jsr     TryQuakeRespawn
        bcc     @TechniqueInput
        jmp     @Return
@TechniqueInput:
.endif
        lda     z:SFX_joy1trig
        and     #JOY_SELECT
        beq     @AngleControls
        lda     technique
        cmp     #RUNTIME_MENU_TECHNIQUE_TEXTURED_NONE
        beq     @SelectTechnique4
        cmp     #RUNTIME_MENU_TECHNIQUE_TEXTURED_LIGHTMAP
        beq     @SelectTechnique7
        lda     #RUNTIME_MENU_TECHNIQUE_TEXTURED_NONE
        bra     @StoreSelectedTechnique
@SelectTechnique4:
        lda     #RUNTIME_MENU_TECHNIQUE_TEXTURED_LIGHTMAP
        bra     @StoreSelectedTechnique
@SelectTechnique7:
        lda     #RUNTIME_MENU_TECHNIQUE_UNTEXTURED_LIGHTMAP
@StoreSelectedTechnique:
        sta     technique
        inc     control_dirty

@AngleControls:
@AngleStep:
.ifndef QC_QUEUED_INPUT
        lda     fly_playback_mode
        cmp     #RUNTIME_MENU_PLAYBACK_FLY3X
        beq     @ApplyAngles
.endif
        lda     control_divider
        and     #$0001
        beq     :+
        jmp     @Clamp
:
@ApplyAngles:
        ; 3x takes half-sized joypad/capped mouse steps every video frame;
        ; 2x retains the old alternate-frame cadence and the same turn speed.
        ldx     camera_input_buttons
.ifdef QC_QUEUED_INPUT
        ; Live pad look is sampled in the foreground. Only accumulate mouse
        ; motion here so old held turns cannot survive release or reversal.
        lda     qc_input_replay
        bne     :+
        ldx     #0
:
.endif
        txa
        and     #JOY_LEFT
        beq     @YawRight
        lda     fly_mouse_yaw_step
        sec
        sbc     fly_look_step_limit
        bra     @YawApply
@YawRight:
        txa
        and     #JOY_RIGHT
        beq     @YawMouse
        lda     fly_mouse_yaw_step
        clc
        adc     fly_look_step_limit
        bra     @YawApply
@YawMouse:
        lda     fly_mouse_yaw_step
@YawApply:
.if BSP_QUAKEC_GAMEPLAY
        eor     #$FFFF                 ; Stock right looks toward decreasing yaw.
        inc
.endif
.ifdef QC_QUEUED_INPUT
        ldy     qc_sample_pending
        bne     @PitchUp
        clc
        adc     qc_sample_yaw
        ldy     qc_input_replay
        bne     :+
        ora     #$0000                 ; Restore N from the signed sum after LDY.
        jsr     ClampFlyMouseDelta
:
        sta     qc_sample_yaw
.else
        beq     @PitchUp
        clc
        adc     yaw_index
        and     #CAMERA_ANGLE_MASK
        sta     yaw_index
        inc     control_dirty
.endif
@PitchUp:
        txa
        and     #JOY_UP
        beq     @PitchDown
        lda     fly_mouse_pitch_step
        clc
        adc     fly_look_step_limit
        bra     @PitchApply
@PitchDown:
        txa
        and     #JOY_DOWN
        beq     @PitchMouse
        lda     fly_mouse_pitch_step
        sec
        sbc     fly_look_step_limit
        bra     @PitchApply
@PitchMouse:
        lda     fly_mouse_pitch_step
@PitchApply:
.ifdef QC_QUEUED_INPUT
        ldy     qc_sample_pending
        bne     @Clamp
        clc
        adc     qc_sample_pitch
        ldy     qc_input_replay
        bne     :+
        ora     #$0000
        jsr     ClampFlyMouseDelta
:
        sta     qc_sample_pitch
.else
        beq     @Clamp
        clc
        adc     pitch_level
        bmi     @PitchNegative
        cmp     #CAMERA_PITCH_MAX+1
        bcc     @PitchStore
        lda     #CAMERA_PITCH_MAX
        bra     @PitchStore
@PitchNegative:
        cmp     #CAMERA_PITCH_MIN
        bcs     @PitchStore
        lda     #CAMERA_PITCH_MIN
@PitchStore:
        cmp     pitch_level
        beq     @Clamp
        sta     pitch_level
        inc     control_dirty
.endif

@Clamp:
        lda     control_dirty
        beq     @Return
        jsr     ClampCamera
@PublishDirty:
        inc     control_revision
@Return:
        RW_forced a8i16
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
BSPCollisionBitMasks:
        .byte   $01, $02, $04, $08, $10, $20, $40, $80
BSPCollisionBitMasksEnd:
.assert BSPCollisionBitMasksEnd - BSPCollisionBitMasks = 8, error, "Fly collision bit-mask table size changed"

RuntimeMenuPalette:
        .incbin "../Data/QuakeBSPTexturePalette.bin", 480, 32
RuntimeMenuPaletteEnd:
.assert RuntimeMenuPaletteEnd - RuntimeMenuPalette = 32, error, "Runtime-menu palette tail size changed"

.include "RuntimeMenuFont.s"
.include "FlyMouse.s"
.segment "CODE"
.include "GraphicsScale.s"
