; Stock changelevel_touch schedules execute_changelevel 0.1 s later. Only
; attack/use/jump after the two-second single-player gate may advance the map.
; Preserve the near calls into the main QuakeC bank. The intermission
; controller and tables use their own long-addressed CPU ROM section.
IntermissionRandomLong:
        jsr     ShotgunRandom
        rtl
IntermissionAnimateLong:
        jsr     QuakeCStep
        sec
        rtl

.pushseg
.segment "BSP_CPU_WALK_RUN"
IntermissionTouch:
        lda     f:intermission_phase
        bne     @Done
        lda     #1
        sta     f:intermission_phase
        lda     #2
        sta     f:intermission_wait
@Done:  rtl

IntermissionService:
        lda     f:QC_INPUT_MENU_OPEN
        ora     f:QC_INPUT_RELEASE_GATE
        beq     @Clock
        lda     f:intermission_phase
        beq     :+
        sec
        rtl
:       clc
        rtl
@Clock: lda     f:intermission_phase
        cmp     #2
        bne     :+
        jmp     @Show
:       inc     a:.loword(intermission_subseconds)
        lda     f:intermission_subseconds
        cmp     #QC_SIMULATION_HZ
        bcc     :+
        stz     a:.loword(intermission_subseconds)
        inc     a:.loword(intermission_seconds)
:       lda     f:intermission_phase
        bne     :+
        clc
        rtl
:       dec     a:.loword(intermission_wait)
        beq     :+
        sec
        rtl
:
        jsl     IntermissionRandomLong
        lda     a:qcg+2
        beq     :+
        dec
:       lsr
        lsr
        lsr
        lsr
        sta     f:intermission_camera
        asl
        asl
        asl
        tax
        ldy     #0
@Axis:  lda     f:IntermissionCameras,x
        sta     a:w_pending_xyz,y
        cmp     #$8000
        ror
        sta     a:shot_player+QC_FIELD_ORIGIN,y
        lda     #0
        sta     a:shot_player+QC_FIELD_VIEW_OFS,y
        sta     a:shot_player+QC_FIELD_VELOCITY,y
        inx
        inx
        iny
        iny
        cpy     #6
        bne     @Axis
        lda     f:IntermissionCameras,x
        sta     f:walk_pending_yaw
        lda     #1
        sta     f:walk_pending_yaw_valid
        sta     a:w_pending
        lda     #2
        sta     f:intermission_phase
        lda     #2*QC_VIDEO_RATE
        sta     f:intermission_wait
        lda     a:qcg+QC_GLOBAL_KILLED_MONSTERS
        .repeat 6
        lsr
        .endrepeat
        sta     f:intermission_kills
        lda     f:quake_skill_active
        asl
        tax
        lda     f:IntermissionMonsterTotals,x
        sta     f:intermission_monsters
        stz     a:shot_player+QC_FIELD_SOLID
        stz     a:shot_player+QC_FIELD_TAKEDAMAGE
        stz     a:shot_player+QC_FIELD_MOVETYPE
        stz     a:w_velocity_x
        stz     a:w_velocity_y
        stz     a:w_velocity_z
        jsl     GameplayPublishPose
.ifdef PLAYABLE_LARGE_DISTANCE_CACHE
  .ifdef PLAYABLE_MAP_ID
        jsl     IntermissionPrepare
  .else
        .res    4,$ea
  .endif
.endif
        ; Let the player see the complete panel for the stock two seconds.
        ; The initial paired-MSU reads can span several real VBlanks.
.ifdef PLAYABLE_RECORDED_TAPE
        jsr     @ReadVideoClock
.else
        lda     f:video_tick
.endif
        sta     f:intermission_video
@Handled:
        sec
        rtl
@Show:  lda     f:intermission_wait
        beq     @Input
.ifdef PLAYABLE_RECORDED_TAPE
        jsr     @ReadVideoClock
.else
        lda     f:video_tick
.endif
        sec
        sbc     a:.loword(intermission_video)
        cmp     #2*QC_VIDEO_RATE
        bcs     @GateOpen
        eor     #$ffff
        sec
        adc     #2*QC_VIDEO_RATE
        sta     f:intermission_wait
        bra     @Animate
@GateOpen:
        stz     a:.loword(intermission_wait)
@Input: lda     f:QC_INPUT_BUTTONS
        and     #(JOY_L | JOY_R)
        beq     @Animate
  .ifdef PLAYABLE_MAP_ID
        lda     #QC_EPISODE_EXIT_MAP_ID
        jsl     CampaignRequestMap
  .else
        .res    7, $EA
  .endif
        sec
        rtl

@Animate:
        ; The player is intangible, but the server still advances monsters,
        ; flying fragments, and brush movers behind the results panel.
        jml     IntermissionAnimateLong

.ifdef PLAYABLE_RECORDED_TAPE
@ReadVideoClock:
        lda     f:qc_input_replay
        bit     #QC_INPUT_RECORDED_TAPE
        beq     @PhysicalVideoClock
        ; One gameplay service represents three admitted tape samples.
        ; Feeder wait VBlanks do not advance the recorded exit lockout.
        .assert QC_INPUT_VBLANKS = 3, error, "intermission tape clock expects three samples per service"
        lda     f:quakec_last_tick
        asl
        clc
        adc     f:quakec_last_tick
        rts
@PhysicalVideoClock:
        lda     f:video_tick
        rts
.endif

IntermissionCameras:
.repeat QC_INTERMISSION_COUNT,I
        .word .loword(.ident(.sprintf("QC_INTERMISSION_%u_X",I))), .loword(.ident(.sprintf("QC_INTERMISSION_%u_Y",I)))
        .word .loword(.ident(.sprintf("QC_INTERMISSION_%u_Z",I))), .ident(.sprintf("QC_INTERMISSION_%u_YAW",I))
        .assert .ident(.sprintf("QC_INTERMISSION_%u_PITCH",I)) = QC_INTERMISSION_0_PITCH, error, "unexpected intermission pitch"
.endrepeat
IntermissionMonsterTotals:
.repeat 4,I
        .word .ident(.sprintf("QC_INTERMISSION_%u_MONSTERS",I))
.endrepeat
.popseg
