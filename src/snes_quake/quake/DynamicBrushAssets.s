; Deterministic QBSA/QBSF banks consumed only by the enabled brush path.

.segment "BSP_BRUSH_TEXTURE_0"
        .incbin "Data/QuakeBSPBrushTexturePixels0.bin"
.segment "BSP_BRUSH_TEXTURE_1"
        .incbin "Data/QuakeBSPBrushTexturePixels1.bin"
.segment "BSP_BRUSH_TEXTURE_2"
        .incbin "Data/QuakeBSPBrushTexturePixels2.bin"
.segment "BSP_BRUSH_TEXTURE_3"
.ifdef BSP_BRUSH_PVS_RUNTIME_TAIL
        .incbin "Data/QuakeBSPBrushTexturePixels3.bin"
.else
; Keep the reserved-palette pixels, but pair the embedded visibility directory
; packed directory can point into the middle of those normal RLE streams.
; Slicing addresses the original files, not their relocated ROM views.
.ifndef BSP_BRUSH_LINKED_PVS_SOURCE_OFFSET
BSP_BRUSH_LINKED_PVS_SOURCE_OFFSET = BSP_BRUSH_PVS_DIRECTORY_ADDRESS - $8000
.endif
BSP_BRUSH_LINKED_PVS_OFFSET = BSP_BRUSH_LINKED_PVS_SOURCE_OFFSET
BSP_BRUSH_LINKED_PVS_BYTES = BSP_BRUSH_LEAF_HEAD_COUNT * BSP_BRUSH_PVS_DIRECTORY_RECORD_BYTES
.assert BSP_BRUSH_PVS_DIRECTORY_BANK = (^__BSP_BRUSH_TEXTURE_3_LOAD__ & $7F), lderror, "Brush PVS directory moved from texture bank 3"
.assert BSP_BRUSH_LINKED_PVS_OFFSET >= 0, error, "Brush PVS directory precedes its bank"
.assert BSP_BRUSH_LINKED_PVS_OFFSET + BSP_BRUSH_LINKED_PVS_BYTES <= BSP_WORLD_ROM_BANK_BYTES, error, "Brush PVS directory escapes its bank"
        .incbin "Data/QuakeBSPBrushTexturePixels3.bin", 0, BSP_BRUSH_LINKED_PVS_OFFSET
        .incbin "Data/QuakeBSPBrushTexturePixels3.bin", BSP_BRUSH_LINKED_PVS_OFFSET, BSP_BRUSH_LINKED_PVS_BYTES
        .incbin "Data/QuakeBSPBrushTexturePixels3.bin", BSP_BRUSH_LINKED_PVS_OFFSET + BSP_BRUSH_LINKED_PVS_BYTES, BSP_WORLD_ROM_BANK_BYTES - BSP_BRUSH_LINKED_PVS_OFFSET - BSP_BRUSH_LINKED_PVS_BYTES
.endif
.segment "BSP_BRUSH_RUNTIME_0"
        .incbin "Data/QuakeBSPBrushRuntime0.bin"
.segment "BSP_BRUSH_RUNTIME_1"
        .incbin "Data/QuakeBSPBrushRuntime1.bin"
.segment "BSP_BRUSH_RUNTIME_2"
        .incbin "Data/QuakeBSPBrushRuntime2.bin"
.if BSP_BRUSH_FRAGMENT_BANK_COUNT > 0
        .segment "BSP_BRUSH_FRAGMENTS_0"
        .incbin "Data/QuakeBSPBrushFragments0.bin"
.endif
.if BSP_BRUSH_FRAGMENT_BANK_COUNT > 1
        .segment "BSP_BRUSH_FRAGMENTS_1"
        .incbin "Data/QuakeBSPBrushFragments1.bin"
.endif
.if BSP_BRUSH_FRAGMENT_BANK_COUNT > 2
        .segment "BSP_BRUSH_FRAGMENTS_2"
        .incbin "Data/QuakeBSPBrushFragments2.bin"
.endif
.if BSP_BRUSH_FRAGMENT_BANK_COUNT > 3
        .segment "BSP_BRUSH_FRAGMENTS_3"
        .incbin "Data/QuakeBSPBrushFragments3.bin"
.endif
.if BSP_BRUSH_FRAGMENT_BANK_COUNT > 4
        .segment "BSP_BRUSH_FRAGMENTS_4"
        .incbin "Data/QuakeBSPBrushFragments4.bin"
.endif
.if BSP_BRUSH_FRAGMENT_BANK_COUNT > 5
        .segment "BSP_BRUSH_FRAGMENTS_5"
        .incbin "Data/QuakeBSPBrushFragments5.bin"
.endif
.if BSP_BRUSH_FRAGMENT_BANK_COUNT > 6
        .segment "BSP_BRUSH_FRAGMENTS_6"
        .incbin "Data/QuakeBSPBrushFragments6.bin"
.endif
.assert __BSP_BRUSH_TEXTURE_0_LOAD__ = BSP_ROM_LOAD_BSP_BRUSH_TEXTURE_0, lderror, "Brush texture bank 0 moved"
.assert __BSP_BRUSH_TEXTURE_1_LOAD__ = BSP_ROM_LOAD_BSP_BRUSH_TEXTURE_1, lderror, "Brush texture bank 1 moved"
.assert __BSP_BRUSH_TEXTURE_2_LOAD__ = BSP_ROM_LOAD_BSP_BRUSH_TEXTURE_2, lderror, "Brush texture bank 2 moved"
.assert __BSP_BRUSH_TEXTURE_3_LOAD__ = BSP_ROM_LOAD_BSP_BRUSH_TEXTURE_3, lderror, "Brush texture bank 3 moved"
.assert __BSP_BRUSH_RUNTIME_0_LOAD__ = BSP_ROM_LOAD_BSP_BRUSH_RUNTIME_0, lderror, "QBSA runtime bank 0 moved"
.assert __BSP_BRUSH_RUNTIME_1_LOAD__ = BSP_ROM_LOAD_BSP_BRUSH_RUNTIME_1, lderror, "QBSA runtime bank 1 moved"
.assert __BSP_BRUSH_RUNTIME_2_LOAD__ = BSP_ROM_LOAD_BSP_BRUSH_RUNTIME_2, lderror, "QBSA runtime bank 2 moved"
.if BSP_BRUSH_FRAGMENT_BANK_COUNT > 0
        .assert __BSP_BRUSH_FRAGMENTS_0_LOAD__ = BSP_ROM_LOAD_BSP_BRUSH_FRAGMENTS_0, lderror, "QBSF bank 0 moved"
.endif
.if BSP_BRUSH_FRAGMENT_BANK_COUNT > 1
        .assert __BSP_BRUSH_FRAGMENTS_1_LOAD__ = BSP_ROM_LOAD_BSP_BRUSH_FRAGMENTS_1, lderror, "QBSF bank 1 moved"
.endif
.if BSP_BRUSH_FRAGMENT_BANK_COUNT > 2
        .assert __BSP_BRUSH_FRAGMENTS_2_LOAD__ = BSP_ROM_LOAD_BSP_BRUSH_FRAGMENTS_2, lderror, "QBSF bank 2 moved"
.endif
.if BSP_BRUSH_FRAGMENT_BANK_COUNT > 3
        .assert __BSP_BRUSH_FRAGMENTS_3_LOAD__ = BSP_ROM_LOAD_BSP_BRUSH_FRAGMENTS_3, lderror, "QBSF bank 3 moved"
.endif
.if BSP_BRUSH_FRAGMENT_BANK_COUNT > 4
        .assert __BSP_BRUSH_FRAGMENTS_4_LOAD__ = BSP_ROM_LOAD_BSP_BRUSH_FRAGMENTS_4, lderror, "QBSF bank 4 moved"
.endif
.if BSP_BRUSH_FRAGMENT_BANK_COUNT > 5
        .assert __BSP_BRUSH_FRAGMENTS_5_LOAD__ = BSP_ROM_LOAD_BSP_BRUSH_FRAGMENTS_5, lderror, "QBSF bank 5 moved"
.endif
.if BSP_BRUSH_FRAGMENT_BANK_COUNT > 6
        .assert __BSP_BRUSH_FRAGMENTS_6_LOAD__ = BSP_ROM_LOAD_BSP_BRUSH_FRAGMENTS_6, lderror, "QBSF bank 6 moved"
.endif

.assert __BSP_BRUSH_TEXTURE_0_SIZE__ = BSP_WORLD_ROM_BANK_BYTES, lderror, "Brush texture bank 0 is incomplete"
.assert __BSP_BRUSH_TEXTURE_1_SIZE__ = BSP_WORLD_ROM_BANK_BYTES, lderror, "Brush texture bank 1 is incomplete"
.assert __BSP_BRUSH_TEXTURE_2_SIZE__ = BSP_WORLD_ROM_BANK_BYTES, lderror, "Brush texture bank 2 is incomplete"
.assert __BSP_BRUSH_TEXTURE_3_SIZE__ = BSP_WORLD_ROM_BANK_BYTES, lderror, "Brush texture bank 3 is incomplete"
.assert __BSP_BRUSH_RUNTIME_0_SIZE__ = BSP_WORLD_ROM_BANK_BYTES, lderror, "QBSA runtime bank 0 is incomplete"
.assert __BSP_BRUSH_RUNTIME_1_SIZE__ = BSP_WORLD_ROM_BANK_BYTES, lderror, "QBSA runtime bank 1 is incomplete"
.assert __BSP_BRUSH_RUNTIME_2_SIZE__ = BSP_WORLD_ROM_BANK_BYTES, lderror, "QBSA runtime bank 2 is incomplete"
.if BSP_BRUSH_FRAGMENT_BANK_COUNT > 0
        .assert __BSP_BRUSH_FRAGMENTS_0_SIZE__ = BSP_WORLD_ROM_BANK_BYTES, lderror, "QBSF bank 0 is incomplete"
.endif
.if BSP_BRUSH_FRAGMENT_BANK_COUNT > 1
        .assert __BSP_BRUSH_FRAGMENTS_1_SIZE__ = BSP_WORLD_ROM_BANK_BYTES, lderror, "QBSF bank 1 is incomplete"
.endif
.if BSP_BRUSH_FRAGMENT_BANK_COUNT > 2
        .assert __BSP_BRUSH_FRAGMENTS_2_SIZE__ = BSP_WORLD_ROM_BANK_BYTES, lderror, "QBSF bank 2 is incomplete"
.endif
.if BSP_BRUSH_FRAGMENT_BANK_COUNT > 3
        .assert __BSP_BRUSH_FRAGMENTS_3_SIZE__ = BSP_WORLD_ROM_BANK_BYTES, lderror, "QBSF bank 3 is incomplete"
.endif
.if BSP_BRUSH_FRAGMENT_BANK_COUNT > 4
        .assert __BSP_BRUSH_FRAGMENTS_4_SIZE__ = BSP_WORLD_ROM_BANK_BYTES, lderror, "QBSF bank 4 is incomplete"
.endif
.if BSP_BRUSH_FRAGMENT_BANK_COUNT > 5
        .assert __BSP_BRUSH_FRAGMENTS_5_SIZE__ = BSP_WORLD_ROM_BANK_BYTES, lderror, "QBSF bank 5 is incomplete"
.endif
.if BSP_BRUSH_FRAGMENT_BANK_COUNT > 6
        .assert __BSP_BRUSH_FRAGMENTS_6_SIZE__ = BSP_WORLD_ROM_BANK_BYTES, lderror, "QBSF bank 6 is incomplete"
.endif
.assert BSP_BRUSH_FRAGMENT_BANK_COUNT <= 7, lderror, "QBSF package exceeds the documented FX3 mapping"
