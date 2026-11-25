; First test the cached ordinary outcode in the existing RAM code window.
; An inside vertex disproves a common outside plane without any ROM jump.
.if BSP_RENDER_SCALE = 2
TextureBeginWorldCoordinates:
        lm      R10, (CONVEX_INDEX_PTR)
        movew   R0, (R10)
        add     R0
        add     R0
        add     R0
        iwt     R4, #PACKET_VIEW_CACHE+6
        with    R4
        add     R0
        movew   R0, (R4)
        moves   R0, R0
        bne     TextureWorldFrustumProbeROM
        nop
.ifdef PLAYABLE_WORLD_AFFINE_UV
        GSU_ABSOLUTE_GOTO TextureBeginAffineWorldCoordinates
.else
        GSU_ABSOLUTE_GOTO TextureBeginCoordinateStream
.endif
TextureWorldFrustumProbeROM:
        iwt     R1, #.loword(TextureWorldFrustumROM)
        move    R12, #BSP_GSU_ROM3_BANK
        from    R1
        ljmp    R12
        nop
.ifdef PLAYABLE_WORLD_AFFINE_UV
TextureBeginAffineWorldCoordinates:
        iwt     R0, #.loword(TextureLookupAffineWorldCoordinatesROM)
        move    R12, #BSP_GSU_ROM3_BANK
        from    R0
        ljmp    R12
        nop
.endif
.endif
