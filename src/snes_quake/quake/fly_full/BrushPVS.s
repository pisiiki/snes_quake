; JAL is LINK #4 followed by IWT R15; replace only its two-byte operand.
; S-CPU dispatch runs while the GSU is stopped. Demo/general restoration uses
; the same four sites, so no renderer pays a per-brush feature-state branch.
.import BrushReplayGeometryCall, BrushStaticGeometryCall, BrushExternalGeometryCall
.import BrushBucketPainterCall, BrushBuildGeometryLinks, BrushMarkPainterAncestors
.import FlyBrushBuildGeometryLinks, FlyBrushMarkVisiblePainter

EnsureFlyBrushPVSCode:
        RW_assume a16i16
        lda     texture_renderer_code_variant
        cmp     #$0002
        beq     @Ready
        jsr     EnsureTechnique4RendererCode
        lda     #.loword(FlyBrushBuildGeometryLinks)
        ldx     #.loword(FlyBrushMarkVisiblePainter)
        jsr     SetBrushPVSCode
        lda     #$0002
        sta     texture_renderer_code_variant
@Ready:
        rts

RestoreBrushPVSCode:
        RW_assume a16i16
        lda     #.loword(BrushBuildGeometryLinks)
        ldx     #.loword(BrushMarkPainterAncestors)
SetBrushPVSCode:
        sta     f:BrushReplayGeometryCall+2
        sta     f:BrushStaticGeometryCall+2
        sta     f:BrushExternalGeometryCall+2
        txa
        sta     f:BrushBucketPainterCall+2
        rts
