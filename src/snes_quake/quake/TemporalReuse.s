; Exact temporal reuse for configured technique-4 ordered playback. The
; scheduler may publish a fresh camera pose without manufacturing new pixels.

.macro TEMPORAL_REQUIRE_EQUAL cached, current
        lda     cached
        cmp     current
        beq     :+
        jmp     TemporalReuseRenderRequired
:
.endmacro

; Cache/compare the generated raster-reachable QBA1/QAV2 identity. Equal IDs
; prove exact painter groups, referenced alias states, and brush-aware masks;
; dynamic states excluded from every painter group cannot contribute pixels.
.macro TEXTURE_TEMPORAL_CACHE_ALIAS_INPUT row
        lda     row
        cmp     #BSP_ALIAS_VISIBILITY_SOURCE_ROW_COUNT
        bcc     :+
        jmp     TemporalReuseRenderRequired
:
        asl
        tax
        lda     render_camera+10
        and     #(BSP_OVERLAY_DYNAMIC_BRUSHES << 8)
        beq     :+
        lda     f:QuakeBSPAliasVisibilityEnabled+BSP_ALIAS_TEMPORAL_IDENTITY_OFFSET,x
        bra     :++
:
        lda     f:QuakeBSPAliasVisibilityDisabled+BSP_ALIAS_TEMPORAL_IDENTITY_OFFSET,x
:
        sta     temporal_alias_raster_identity
.endmacro

.macro TEXTURE_TEMPORAL_REQUIRE_ALIAS_INPUT row
        lda     row
        cmp     #BSP_ALIAS_VISIBILITY_SOURCE_ROW_COUNT
        bcc     :+
        jmp     TemporalReuseRenderRequired
:
        asl
        tax
        lda     render_camera+10
        and     #(BSP_OVERLAY_DYNAMIC_BRUSHES << 8)
        beq     :+
        lda     f:QuakeBSPAliasVisibilityEnabled+BSP_ALIAS_TEMPORAL_IDENTITY_OFFSET,x
        bra     :++
:
        lda     f:QuakeBSPAliasVisibilityDisabled+BSP_ALIAS_TEMPORAL_IDENTITY_OFFSET,x
:
        cmp     temporal_alias_raster_identity
        beq     :+
        jmp     TemporalReuseRenderRequired
:
.endmacro

; The fully qualified canonical sequence contributes one bit per current pose.
; A set bit proves that pose's complete indexed output equals its circular
; predecessor. Runtime guards bind this narrow oracle to every qualified input
; and require that exact predecessor to be the retained staged identity.
TryReuseOrdered20Predecessor:
        RW_assume a16i16
        lda     render_coverage_mode
        bne     @Different
        lda     demo_mode
        cmp     #$0001
        bne     @Different
        lda     demo_schedule
        bne     @Different
        lda     demo_ordered_pose_stride
        cmp     #$0001
        bne     @Different
        lda     dynamic_brushes_enabled
        cmp     #$0001
        bne     @Different
        lda     mdl_entities_enabled
        cmp     #$0001
        bne     @Different
        lda     sky_phase_override_valid
        bne     @Different
        lda     render_camera+10
        cmp     #(BSP_TECHNIQUE_TEXTURED_LIGHTMAP | ((BSP_OVERLAY_DYNAMIC_BRUSHES | BSP_OVERLAY_ALIAS_ENTITIES | BSP_OVERLAY_EXTERNAL_BSP) << 8))
        bne     @Different
        cmp     scheduled_frame_camera+10
        bne     @Different
        lda     render_camera+14
        cmp     render_demo_pose
        bne     @Different
        cmp     #BSP_ALIAS_PREDECESSOR_REUSE_POSE_COUNT
        bcs     @Different
        cmp     #$0000
        beq     @WrappedPredecessor
        dec
        bra     @PredecessorReady
@WrappedPredecessor:
        lda     #BSP_ALIAS_PREDECESSOR_REUSE_POSE_COUNT-1
@PredecessorReady:
        cmp     scheduled_frame_camera+14
        bne     @Different

        lda     render_camera+14
        and     #$000F
        asl
        tax
        lda     f:Ordered20PredecessorReuseMasks,x
        sta     temporal_alias_raster_identity
        lda     render_camera+14
        lsr
        lsr
        lsr
        lsr
        asl
        tax
        lda     f:QuakeBSPAliasVisibilityEnabled+BSP_ALIAS_PREDECESSOR_REUSE_OFFSET,x
        bit     temporal_alias_raster_identity
        beq     @Different
        sec
        rts
@Different:
        clc
        rts

Ordered20PredecessorReuseMasks:
        .word   $0001, $0002, $0004, $0008
        .word   $0010, $0020, $0040, $0080
        .word   $0100, $0200, $0400, $0800
        .word   $1000, $2000, $4000, $8000

; Return A=0 for a render, A=1 for ordinary idle reuse, or A=2 for a fresh
; metadata-only presentation. Revision and due-tick fields are deliberately
; excluded from the raster key: they distinguish command publication, not
; pixels. A changed revision is handled only after the exact key matches.
ClassifyScheduledFrameReuse:
        RW_assume a16i16
        lda     scheduled_frame_valid
        bne     :+
        jmp     TemporalReuseRenderRequired
:
        TEMPORAL_REQUIRE_EQUAL scheduled_frame_coverage_mode, render_coverage_mode
        lda     render_camera+10
        and     #$00FF
        cmp     #BSP_TECHNIQUE_TEXTURED_LIGHTMAP
        beq     @OrderedLightmap
        jmp     TemporalReuseRenderRequired
@OrderedLightmap:
        ; Configured ordered playback can repeat a fully quantized camera and
        ; every dynamic input on adjacent source rows. Reuse only that narrow
        ; technique-4 route, and only when the prior render proved that neither
        ; time-varying special surface contributed a pixel.
        lda     demo_mode
        bne     :+
        jmp     TemporalReuseRenderRequired
:
        lda     demo_schedule
        beq     :+
        jmp     TemporalReuseRenderRequired
:
        ; Qualification disables only ordered reuse. Keep its switch outside
        ; the realtime/fly path and preserve production material selection.
        lda     temporal_reuse_enabled
        bne     :+
        jmp     TemporalReuseRenderRequired
:
        lda     render_demo_pose
        cmp     #$FFFF
        bne     :+
        jmp     TemporalReuseRenderRequired
:
        jsr     TryReuseOrdered20Predecessor
        bcc     :+
        lda     #$0002
        rts
:
        TEMPORAL_REQUIRE_EQUAL scheduled_frame_camera+0, render_camera+0
        TEMPORAL_REQUIRE_EQUAL scheduled_frame_camera+2, render_camera+2
        ; Technique 4 consumes the packed high-byte position below. Changes in
        ; the retained low bytes cannot alter selection or rasterization.
        TEMPORAL_REQUIRE_EQUAL scheduled_frame_camera+4, render_camera+4
        TEMPORAL_REQUIRE_EQUAL scheduled_frame_camera+6, render_camera+6
        TEMPORAL_REQUIRE_EQUAL scheduled_frame_camera+8, render_camera+8
        TEMPORAL_REQUIRE_EQUAL scheduled_frame_camera+10, render_camera+10
        TEMPORAL_REQUIRE_EQUAL scheduled_frame_brush_visual_state, render_brush_visual_state
        lda     staging_sky_present
        ora     staging_turbulence_present
        beq     :+
        jmp     TemporalReuseRenderRequired
:
        TEXTURE_TEMPORAL_CACHE_ALIAS_INPUT scheduled_frame_camera+14
        TEXTURE_TEMPORAL_REQUIRE_ALIAS_INPUT render_camera+14
        lda     scheduled_frame_camera+12
        cmp     render_camera+12
        beq     @OrderedIdle
        lda     #$0002
        rts
@OrderedIdle:
        lda     #$0001
        rts
TemporalReuseRenderRequired:
        lda     #$0000
        rts

; Bind the producer's reuse kind to the NMI consumer before releasing frame_ready.
LoadUploadReuseState:
        RW_forced a16i16
        ldx     #$0000
        lda     upload_slot
        beq     @SlotReady
        ldx     #$0002
@SlotReady:
        lda     slot_metadata_only,x
        sta     upload_metadata_only
        RW_forced a8i16
        rts

; Metadata-only work must execute the existing global completion marker once.
TryCommitMetadataUpload:
        RW_assume a8i16
        lda     upload_metadata_only
        beq     @Pixels
        jsr     UploadPresented
        sec
        rts
@Pixels:
        clc
        rts

InvalidateScheduledFrameIdentity:
        RW_assume a16i16
        stz     scheduled_frame_valid
        rts

InvalidateScheduledFrameHistory:
        RW_assume a16i16
        jsr     InvalidateScheduledFrameIdentity
        rts

InitTemporalReuse:
        RW_assume a16i16
        jsr     InvalidateScheduledFrameHistory
        stz     temporal_stage_metadata_only
        stz     upload_metadata_only
        stz     slot_metadata_only+0
        stz     slot_metadata_only+2
        stz     texture_input_reuse_counter
        stz     metadata_present_counter
        stz     camera_collision_rejected
        stz     camera_collision_reject_counter
        rts
