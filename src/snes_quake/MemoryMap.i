; Cartridge RAM layout shared by the S-CPU and GSU BSP renderer.

.ifndef __QUAKE_BSP_MEMORY_MAP_I__
__QUAKE_BSP_MEMORY_MAP_I__ = 1

.include "Data/QuakeBSPScene.i"
.include "Data/QuakeBSPBrushAssets.i"
.include "Data/QuakeBSPMonsterCameras.i"
.include "Data/QuakeBSPComposedCache.i"
.include "Data/QuakeBSPAliasAssets.i"
.include "Data/QuakeBSPAliasVisibility.i"
.include "Data/QuakeBSPCollision.i"
.include "Data/QuakeBSPSkyAssets.i"
.include "Data/QuakeBSPTurbulenceAssets.i"
.include "Data/QuakeBSPSoundtrack.i"

BSP_COLLISION_RAM_BASE        = $7F0000
BSP_COLLISION_MAP_RAM         = BSP_COLLISION_RAM_BASE
BSP_COLLISION_DICTIONARY_RAM  = BSP_COLLISION_RAM_BASE + BSP_COLLISION_DICTIONARY_OFFSET
BSP_COLLISION_RAM_END         = BSP_COLLISION_RAM_BASE + BSP_COLLISION_PAYLOAD_BYTES
BSP_COLLISION_CPU_ROM_BASE    = $F00000
.assert BSP_COLLISION_RAM_END <= $800000, error, "Fly collision payload exceeds bank $7F"

GSU_RAM_BANK_BYTES            = $10000
GSU_BRUSH_CODE_OFFSET         = $8C00
GSU_BRUSH_CODE_CAPACITY       = $25A0
; Fly alias tracing occupies the otherwise-unused tail of the brush overlay,
; but is loaded only when fly mode is entered so ordered boot stays unchanged.
; Align the overlay to a cache line for its plane-distance kernel.
GSU_ALIAS_FLY_CODE_OFFSET     = $AA70
GSU_AUX_CODE_OFFSET           = $B1A0
GSU_AUX_CODE_CAPACITY         = $0E40
GSU_ALIAS_FLY_CODE_CAPACITY   = GSU_AUX_CODE_OFFSET - GSU_ALIAS_FLY_CODE_OFFSET
GSU_CODE_OFFSET               = $C000
GSU_CODE_CAPACITY             = $4000
; Technique 4 replaces the shared raster and its edge-mode dispatch. The
; original GSUCODE bytes remain in ROM110 for dynamic fallback.
GSU_T4_RASTER_CODE_OFFSET     = $DB3B
GSU_T4_RASTER_CODE_CAPACITY   = $02F5
GSU_T4_EDGE_PATCH_OFFSET      = $DE98
GSU_T4_EDGE_PATCH_CAPACITY    = $000F
GSU_T4_EDGE_DEPTH_OFFSET      = $DEB6
GSU_T4_EDGE_DEPTH_CAPACITY    = $001F
GSU_T4_STAGE_CODE_OFFSET      = $DED9
GSU_T4_STAGE_CODE_CAPACITY    = $0042
GSU_T4_EDGE_OUTPUT_OFFSET     = $DF1B
GSU_T4_EDGE_OUTPUT_CAPACITY   = $004C
GSU_T4_FACE_DISPATCH_OFFSET   = $D293
GSU_T4_FACE_DISPATCH_CAPACITY = $0014
GSU_T4_BLOCK_SELECT_OFFSET    = $E214
GSU_T4_BLOCK_SELECT_CAPACITY  = $003E
GSU_T4_SAMPLE_WRAP_OFFSET     = $E4F1
GSU_T4_SAMPLE_WRAP_CAPACITY   = $005D
GSU_T4_SAMPLE_CODE_OFFSET     = $E7DC
GSU_T4_SAMPLE_CODE_CAPACITY   = $0028
GSU_T4_SAMPLE_SELECT_OFFSET   = $F68A
GSU_T4_SAMPLE_SELECT_CAPACITY = $0027
GSU_T4_SAMPLE_AUX_OFFSET      = $F8CE
GSU_T4_SAMPLE_AUX_CAPACITY    = $015A
; Technique-4 brush overlays remove mode dispatch at the same hot addresses;
; ROM63 retains the independently restorable general brush implementation.
GSU_T4_BRUSH_FRAGMENT_OFFSET  = $952C
GSU_T4_BRUSH_FRAGMENT_CAPACITY = $000D
GSU_T4_BRUSH_WORLD_OFFSET     = $9743
GSU_T4_BRUSH_WORLD_CAPACITY   = $0015
GSU_T4_BRUSH_SAMPLE_OFFSET    = $97FF
GSU_T4_BRUSH_SAMPLE_CAPACITY  = $0014
GSU_T4_BRUSH_RASTER_OFFSET    = $9C2D
GSU_T4_BRUSH_RASTER_CAPACITY  = $0025
GSU_T4_BRUSH_MODE_OFFSET      = $9C7F
GSU_T4_BRUSH_MODE_CAPACITY    = $000C
GSU_T4_BRUSH_PREP_OFFSET      = $9EEE
GSU_T4_BRUSH_PREP_CAPACITY    = $000B
GSU_T4_BRUSH_ROW_OFFSET       = $A051
GSU_T4_BRUSH_ROW_CAPACITY     = $0025
GSU_T4_BRUSH_MATERIAL_OFFSET  = $A15A
GSU_T4_BRUSH_MATERIAL_CAPACITY = $000B
GSU_T4_BRUSH_FORWARD_OFFSET   = $A2B6
GSU_T4_BRUSH_FORWARD_CAPACITY = $001D
GSU_T4_BRUSH_REVERSE_OFFSET   = $A351
GSU_T4_BRUSH_REVERSE_CAPACITY = $0017
GSU_T4_BRUSH_SPAN_OFFSET      = $A41C
GSU_T4_BRUSH_SPAN_CAPACITY    = $000B
GSU_T4_BRUSH_BLOCK_OFFSET     = $A54D
GSU_T4_BRUSH_BLOCK_CAPACITY   = $000B
GSU_T4_BRUSH_FINAL_OFFSET     = $A577
GSU_T4_BRUSH_FINAL_CAPACITY   = $0012
GSU_T4_BRUSH_FALLBACK_OFFSET  = $A892
GSU_T4_BRUSH_FALLBACK_CAPACITY = $0021
; Exact Q12 division uses ceil(2^27 / denominator), split into two unsigned
; base-2^15 words. Four 32-KiB ROM banks cover the full positive word domain.
GSU_DIVIDE_Q12_RECIPROCAL_FIRST_ROM_BANK = $26
GSU_DIVIDE_Q12_RECIPROCAL_ROM_BANKS = 4
GSU_DIVIDE_Q12_RECIPROCAL_ROM_ADDRESS = $8000
GSU_DIVIDE_Q12_RECIPROCAL_ENTRY_BYTES = 4
GSU_DIVIDE_Q12_RECIPROCAL_ENTRIES_PER_BANK = $2000
GSU_DIVIDE_Q12_RECIPROCAL_MAX_DENOMINATOR = $7FFF
GSU_DIVIDE_Q12_RECIPROCAL_SCALE_BITS = 27
GSU_DIVIDE_Q12_RECIPROCAL_LIMB_BITS = 15
GSU_DIVIDE_Q12_RECIPROCAL_BYTES = $1FFFC

; Low cartridge RAM gives phase-separated packet/texture, convex, and renderer
; state access to the GSU's short word-load/store encodings. Packet and texture
; state intentionally overlap because their jobs never run concurrently.
; Runtime BSP visibility occupies the free gap below the index packet.
GSU_TEXTURE_STATE_OFFSET      = $0000
GSU_TEXTURE_STATE_BYTES       = $00AE
GSU_CONVEX_STATE_OFFSET       = GSU_TEXTURE_STATE_OFFSET + GSU_TEXTURE_STATE_BYTES
GSU_CONVEX_STATE_BYTES        = $007A
GSU_RENDER_STATE_OFFSET       = GSU_CONVEX_STATE_OFFSET + GSU_CONVEX_STATE_BYTES
GSU_RENDER_STATE_BYTES        = $00BE
GSU_RENDER_SOURCE_INDEX_OFFSET = GSU_RENDER_STATE_OFFSET + GSU_RENDER_STATE_BYTES
; Full-face endpoint precomputation runs after packet construction and before
; raster replay, so it can use the otherwise-free low-RAM tail below $0200.
GSU_TEXTURE_ENDPOINT_STATE_OFFSET = GSU_RENDER_SOURCE_INDEX_OFFSET + 2
GSU_TEXTURE_ENDPOINT_READ_PTR_OFFSET = GSU_TEXTURE_ENDPOINT_STATE_OFFSET + $00
GSU_TEXTURE_ENDPOINT_WRITE_PTR_OFFSET = GSU_TEXTURE_ENDPOINT_STATE_OFFSET + $02
GSU_TEXTURE_ENDPOINT_ROW_PTR_OFFSET = GSU_TEXTURE_ENDPOINT_STATE_OFFSET + $04
GSU_TEXTURE_ENDPOINT_ROWS_LEFT_OFFSET = GSU_TEXTURE_ENDPOINT_STATE_OFFSET + $06
GSU_TEXTURE_ENDPOINT_RETURN_OFFSET = GSU_TEXTURE_ENDPOINT_STATE_OFFSET + $08
GSU_TEXTURE_ENDPOINT_SAMPLE_RETURN_OFFSET = GSU_TEXTURE_ENDPOINT_STATE_OFFSET + $0A
GSU_TEXTURE_ENDPOINT_DIVIDE_RETURN_OFFSET = GSU_TEXTURE_ENDPOINT_STATE_OFFSET + $0C
GSU_TEXTURE_ENDPOINT_STATE_BYTES = $0E
; Reciprocal dispatch remains live across projection, clipping, endpoint
; staging, rasterization, and the dynamic-brush arbiter. Give it dedicated
; short-address words instead of phase-overlaying transient texture state.
GSU_TEXTURE_Q12_ROUTE_STATE_OFFSET = GSU_TEXTURE_ENDPOINT_STATE_OFFSET + GSU_TEXTURE_ENDPOINT_STATE_BYTES
GSU_TEXTURE_Q12_LOOKUP_ROUTINE_OFFSET = GSU_TEXTURE_Q12_ROUTE_STATE_OFFSET + $00
GSU_TEXTURE_Q12_LOADED_ROUTINE_OFFSET = GSU_TEXTURE_Q12_ROUTE_STATE_OFFSET + $02
GSU_TEXTURE_Q12_PREPARED_ROUTINE_OFFSET = GSU_TEXTURE_Q12_ROUTE_STATE_OFFSET + $04
GSU_TEXTURE_Q12_ROUTE_STATE_BYTES = $06
; CPU renderer dispatch publishes exact technique-4 cache eligibility once per
; frame. Keeping it in the unused low-RAM tail preserves the established
; one-load/one-decrement composed-face gate without charging every face for a
; command decode.
GSU_TEXTURE_COMPOSED_ALLOWED_OFFSET = GSU_TEXTURE_Q12_ROUTE_STATE_OFFSET + GSU_TEXTURE_Q12_ROUTE_STATE_BYTES
GSU_TEXTURE_COMPOSED_ALLOWED_BYTES = 2
; The final short-address word stores the first byte of the phase-adjusted
; doubled turbulence table. Keeping the base here lets the per-pixel sampler
; wrap through the duplicate without reloading and adding the phase twice.
GSU_TURBULENCE_TABLE_BASE_OFFSET = $01FE
GSU_PACKET_STATE_OFFSET       = GSU_TEXTURE_STATE_OFFSET
GSU_PACKET_STATE_BYTES        = $0080
GSU_WORLD_VISIBILITY_OFFSET   = $4806
GSU_WORLD_VISIBILITY_CAPACITY = $027A
; The fixed gap between short-address state and the vertex remap holds two
; adjacent copies of Quake's immutable 128-byte displacement table.
GSU_TURBULENCE_TABLE_OFFSET  = $0200
GSU_TURBULENCE_TABLE_BYTES   = BSP_TURBULENCE_TABLE_BYTES * 2

; Runtime packet-builder scratch retained between selector passes.  The remap
; table stores one tagged local vertex ID for every full-world vertex.  The
; selected-face bitset and admission sidecars sit immediately below the packet.
GSU_VERTEX_REMAP_OFFSET       = $0300
GSU_VERTEX_REMAP_CAPACITY     = $38FC
GSU_VERTEX_REMAP_GUARD_OFFSET = $3BFC
; The modern E1M3 profile needs 403 admitted faces. Pull the selected-face
; bitset into the unused remap/bitset gap and grow the sidecar tail to 405.
GSU_SELECTED_FACES_OFFSET     = $3F70
GSU_SELECTED_FACES_CAPACITY   = $023E
GSU_SELECTED_FACES_GUARD_OFFSET = $41AE
GSU_PACKET_SIDECARS_OFFSET    = $41B0
GSU_PACKET_SIDECAR_RECORD_BYTES = 4
GSU_PACKET_FACE_CAPACITY      = 405
GSU_PACKET_SIDECARS_BYTES     = GSU_PACKET_FACE_CAPACITY * GSU_PACKET_SIDECAR_RECORD_BYTES
GSU_PACKET_SIDECARS_GUARD_OFFSET = $4804
GSU_PACKET_GUARD_VALUE        = $A55A

; PLOT always targets bank $70. Keep its logical screen and the expanded frame
; there, put executable code high in the same bank, and keep BSP data in $71.
GSU_OUTPUT_OFFSET             = $0000
GSU_OUTPUT_BYTES              = $7000
GSU_LOGICAL_OFFSET            = $7000
GSU_LOGICAL_SCBR              = GSU_LOGICAL_OFFSET >> 10
GSU_LOGICAL_BYTES             = $1C00
GSU_TEXTURE_FRAMEBUFFER_OFFSET = $0000
GSU_TEXTURE_FRAMEBUFFER_SCBR  = 0
GSU_TEXTURE_FRAMEBUFFER_BYTES = $4000
GSU_TEXTURE_VISIBLE_BYTES     = $3800
BSP_TECHNIQUE_TEXTURED_LIGHTMAP   = 4
BSP_TECHNIQUE_UNTEXTURED_LIGHTMAP = 7
GSU_TEXTURE_TAIL_CODE_OFFSET  = GSU_TEXTURE_VISIBLE_BYTES
GSU_TEXTURE_TAIL_CODE_CAPACITY = GSU_TEXTURE_FRAMEBUFFER_BYTES - GSU_TEXTURE_VISIBLE_BYTES
; Sky's retired bank-$70 hot-code range is the matching numeric address for the
; bank-$71 compositor scratch. Preserve that established lifetime contract.
GSU_SKY_HOT_CODE_OFFSET       = $7900
GSU_SKY_HOT_CODE_CAPACITY     = $0180
GSU_SKY_COMPOSITOR_SCRATCH_OFFSET = GSU_SKY_HOT_CODE_OFFSET + GSU_SKY_HOT_CODE_CAPACITY
; Textured renderers leave the remainder of bank $70 idle. Mirror the hot
; prefix of the exact Q12 reciprocal table there; flat rendering invalidates
; this phase overlay and the S-CPU restores it only on the next textured frame.
GSU_DIVIDE_Q12_HOT_MIRROR_OFFSET = GSU_TEXTURE_FRAMEBUFFER_OFFSET + GSU_TEXTURE_FRAMEBUFFER_BYTES
GSU_DIVIDE_Q12_HOT_MIRROR_END = GSU_BRUSH_CODE_OFFSET
GSU_DIVIDE_Q12_HOT_MIRROR_BYTES = GSU_DIVIDE_Q12_HOT_MIRROR_END - GSU_DIVIDE_Q12_HOT_MIRROR_OFFSET
GSU_DIVIDE_Q12_HOT_MIRROR_ENTRIES = GSU_DIVIDE_Q12_HOT_MIRROR_BYTES / GSU_DIVIDE_Q12_RECIPROCAL_ENTRY_BYTES
; The bank-$70 turbulence sampler occupies the mirror's final 260-byte tail.
; Reciprocal lookups exclude this reserved tail and use the exact ROM fallback.
GSU_TURBULENCE_HOT_CODE_OFFSET = $8AFC
GSU_TURBULENCE_HOT_CODE_CAPACITY = $0104
GSU_DIVIDE_Q12_HOT_MIRROR_SAFE_BYTES = GSU_TURBULENCE_HOT_CODE_OFFSET - GSU_DIVIDE_Q12_HOT_MIRROR_OFFSET
GSU_DIVIDE_Q12_HOT_MIRROR_SAFE_ENTRIES = GSU_DIVIDE_Q12_HOT_MIRROR_SAFE_BYTES / GSU_DIVIDE_Q12_RECIPROCAL_ENTRY_BYTES

; Packet vertices use four bytes: signed int8 xyz bases plus packed Q2
; residuals. Keep this cold near-clip stream above the projection cache so the
; established hot packet/index/raster layout does not move.
GSU_VERTICES_OFFSET           = $B100
GSU_VERTICES_CAPACITY         = $0C00
GSU_VERTICES_GUARD_OFFSET     = $BD00
GSU_INDICES_OFFSET            = $5200
GSU_INDICES_CAPACITY          = $1000
GSU_INDICES_GUARD_OFFSET      = $6200
GSU_FACES_OFFSET              = $6202
GSU_FACES_CAPACITY            = $07FE
GSU_PROJECTED_OFFSET          = $6A00
GSU_PROJECTED_CAPACITY        = $0C00
GSU_VALID_OFFSET              = $7600
GSU_VALID_CAPACITY            = $0300
GSU_RASTER_SCRATCH_OFFSET     = $7900
GSU_RASTER_SCRATCH_BYTES      = $0B00
; Exact projective endpoint pairs are staged only while the phase-separated
; raster and dynamic-brush scratch is idle. Each record is signed-Q4 {S,T}.
GSU_TEXTURE_ENDPOINT_STAGE_OFFSET = $7D50
GSU_TEXTURE_ENDPOINT_STAGE_RECORD_BYTES = 4
GSU_TEXTURE_ENDPOINT_STAGE_RECORDS = 426
GSU_TEXTURE_ENDPOINT_STAGE_BYTES = GSU_TEXTURE_ENDPOINT_STAGE_RECORDS * GSU_TEXTURE_ENDPOINT_STAGE_RECORD_BYTES
GSU_TEXTURE_ENDPOINT_STAGE_END = GSU_TEXTURE_ENDPOINT_STAGE_OFFSET + GSU_TEXTURE_ENDPOINT_STAGE_BYTES

; Dynamic brush leaves are small independent arbitration groups. Their
; projected polygons replace the now-idle world projection cache while one
; 128-pixel Q6 depth row and compact per-polygon records consume the exact
; tail of raster scratch below the trigonometry tables.
GSU_BRUSH_ARBITER_DEPTH_ROW_OFFSET = $7E80
GSU_BRUSH_ARBITER_DEPTH_ROW_BYTES = $0100
GSU_BRUSH_ARBITER_METADATA_OFFSET = GSU_BRUSH_ARBITER_DEPTH_ROW_OFFSET + GSU_BRUSH_ARBITER_DEPTH_ROW_BYTES
GSU_BRUSH_ARBITER_METADATA_RECORD_BYTES = 16
GSU_BRUSH_ARBITER_METADATA_BYTES = BSP_BRUSH_FLY_GROUP_FRAGMENT_MAX * GSU_BRUSH_ARBITER_METADATA_RECORD_BYTES
GSU_BRUSH_ARBITER_SCREEN_RECORD_BYTES = 10

GSU_SIN_OFFSET                = $8400
GSU_SKY_COMPOSITOR_SCRATCH_BYTES = GSU_SIN_OFFSET - GSU_SKY_COMPOSITOR_SCRATCH_OFFSET
GSU_COS_OFFSET                = $8420
; Technique 4 copies the current face's complete packed light grid here.
GSU_LIGHTMAP_CACHE_OFFSET     = $8440
GSU_LIGHTMAP_CACHE_BYTES      = $0200
; Technique 4 prepares one exact nine-sample S/T projective block here.
; The block coordinates occupy the guarded tail after boot parameters while
; rendering; boot has already consumed the parameters before this phase.
GSU_TEXTURE_BLOCK_COORDS_OFFSET = $87D8
GSU_TEXTURE_BLOCK_COORDS_BYTES = 9 * 4
; The guarded two-byte tail records whether the turbulence sampler actually
; produced a texel. Face selection alone is insufficient: a selected liquid
; surface can be fully occluded and therefore independent of its phase.
GSU_TURBULENCE_PRESENT_OFFSET = GSU_TEXTURE_BLOCK_COORDS_OFFSET + GSU_TEXTURE_BLOCK_COORDS_BYTES
; Two shaded active edges retain exact Q12 reciprocal limbs while their
; endpoint pair (and therefore screen-Y denominator) remains unchanged.
; Follow the generated painter mask so compatible BSP trees can use every
; required node bit without overlapping this independent cache.
GSU_TEXTURE_EDGE_DIVIDE_CACHE_OFFSET = GSU_PAINTER_NODE_MASK_OFFSET + GSU_PAINTER_NODE_MASK_BYTES
GSU_TEXTURE_EDGE_DIVIDE_CACHE_ENTRY_BYTES = 6
GSU_TEXTURE_EDGE_DIVIDE_CACHE_BYTES = 2 * GSU_TEXTURE_EDGE_DIVIDE_CACHE_ENTRY_BYTES
; The selector marks only accepted-face owners and their world-root ancestors.
; This gap is in data bank $71 and remains independent of renderer scratch.
GSU_PAINTER_NODE_MASK_OFFSET  = $8640
GSU_PAINTER_NODE_MASK_BYTES   = (BSP_WORLD_NODE_COUNT + 7) / 8
GSU_PAINTER_NODE_MASK_GUARD_OFFSET = $87FE
; Expansion switches RAMBR to bank $70. A single 16-byte nibble table replaces
; the old redundant 512-byte left/right byte tables and lives above aux code.
GSU_EXPAND_NIBBLE_OFFSET      = $BFE0
; ExpandFrame runs with RAMBR=0 so its bookkeeping must also live in bank $70.
; Keeping it beside the lookup table prevents its stores from corrupting the
; 4bpp logical framebuffer at the bank-$70 mirror of raster scratch.
GSU_EXPAND_STATE_OFFSET       = $BFF0
GSU_EXPAND_STATE_BYTES        = $000E
; The free bank-$71 gap below the index packet stages complete faces through
; 92 rows. Taller faces retain the exact direct row path.
GSU_LIGHTMAP_ROW_STAGE_OFFSET = $4C40
GSU_LIGHTMAP_ROW_STAGE_ROWS   = 92
GSU_LIGHTMAP_ROW_STAGE_BYTES  = GSU_LIGHTMAP_ROW_STAGE_ROWS * 16
; World faces and one dynamic-brush leaf group render serially. During a brush
; row the lightmap-row arena is idle and can hold one prepared 20-byte record
; for every generated group fragment, including arbitrary fly-camera rows.
GSU_BRUSH_ROW_STAGE_OFFSET    = GSU_LIGHTMAP_ROW_STAGE_OFFSET
GSU_BRUSH_ROW_STAGE_RECORD_BYTES = 20
GSU_BRUSH_ROW_STAGE_RECORDS  = BSP_BRUSH_FLY_GROUP_FRAGMENT_MAX
GSU_BRUSH_ROW_STAGE_BYTES    = GSU_BRUSH_ROW_STAGE_RECORDS * GSU_BRUSH_ROW_STAGE_RECORD_BYTES
; Host tooling writes this one-shot block while a headless emulator is paused
; at power-on. The S-CPU consumes it after normal state initialization and
; before the first render. Cartridge RAM is required because libSFX clears
; WRAM before Main.
GSU_BOOT_PARAMETERS_OFFSET    = $87C0
GSU_BOOT_PARAMETERS_BYTES     = $0018
GSU_TEXTURE_COORD_MAP_OFFSET  = $4A80
GSU_TEXTURE_COORD_MAP_BYTES   = $0080
; One immutable per-job signed Q6 pickup basis in the unused map/stage gap.
GSU_ALIAS_ROTATION_OFFSET     = GSU_TEXTURE_COORD_MAP_OFFSET + GSU_TEXTURE_COORD_MAP_BYTES
.assert GSU_ALIAS_ROTATION_OFFSET + 2 <= GSU_LIGHTMAP_ROW_STAGE_OFFSET, error, "Alias rotation overlaps row staging"
GSU_TEXTURE_COLORMAP_OFFSET   = $C000
GSU_LIGHTMAP_COLORMAP_BYTES   = $4000
GSU_COMMAND_OFFSET            = $8800
GSU_COMMAND_BYTES             = 16
; StageCommand pins the selected QBA/QAV row outside selector and renderer
; scratch. The command/telemetry gap is dedicated cartridge RAM, so the word
; survives a selector pass without consuming hot raster state.
GSU_ALIAS_RENDER_ROW_OFFSET   = GSU_COMMAND_OFFSET + GSU_COMMAND_BYTES
GSU_ALIAS_RENDER_ROW_BYTES    = 2
GSU_SKY_PRESENT_OFFSET        = GSU_ALIAS_RENDER_ROW_OFFSET + GSU_ALIAS_RENDER_ROW_BYTES
GSU_SKY_ROM_RETURN_OFFSET     = GSU_SKY_PRESENT_OFFSET + 2
GSU_SKY_PHASE_OFFSET          = GSU_SKY_ROM_RETURN_OFFSET + 2
GSU_SKY_MIN_Y_OFFSET          = GSU_SKY_PHASE_OFFSET + BSP_SKY_PHASE_RECORD_BYTES
GSU_SKY_FLAGS_OFFSET          = GSU_SKY_MIN_Y_OFFSET + 1
GSU_SKY_MAX_Y_OFFSET          = GSU_SKY_FLAGS_OFFSET + 1
GSU_SKY_TEXTURE_RETURN_OFFSET = GSU_SKY_MAX_Y_OFFSET + 1
GSU_SKY_BRUSH_RETURN_OFFSET   = GSU_SKY_TEXTURE_RETURN_OFFSET + 2
GSU_SKY_COMMAND_END_OFFSET    = GSU_SKY_BRUSH_RETURN_OFFSET + 2
GSU_BRUSH_RASTER_RETURN_OFFSET = GSU_FACE_PLANES_OFFSET + $40
BSP_OVERLAY_DYNAMIC_BRUSHES   = $01
BSP_OVERLAY_ALIAS_ENTITIES    = $02
BSP_OVERLAY_FLY_STATICS       = $04
BSP_OVERLAY_SKY_DEFER         = $10
BSP_OVERLAY_EXTERNAL_BSP      = $20
.if BSP_EXTERNAL_BSP_SUPPORTED
.assert BSP_EXTERNAL_BSP_ACTIVE_ROW_BYTES = 3, error, "External BSP active rows no longer fit the 24-bit fly mask"
.endif
BSP_SKY_FLAG_ENABLED          = $01
BSP_SKY_FLAG_PRESENTED        = $02
GSU_TELEMETRY_OFFSET          = $8820
GSU_TELEMETRY_BYTES           = $40
; Geometry-stage observation counters are optional telemetry.  $FFFF exceeds
; every E1M3 node/face capacity and explicitly means "not collected".
GSU_OBSERVATION_UNAVAILABLE   = $FFFF
GSU_TELEMETRY_MAGIC           = GSU_TELEMETRY_OFFSET + $00
GSU_TELEMETRY_LEAF            = GSU_TELEMETRY_OFFSET + $02
GSU_TELEMETRY_PVS_FACE_COUNT  = GSU_TELEMETRY_OFFSET + $04
GSU_TELEMETRY_FACE_COUNT      = GSU_TELEMETRY_PVS_FACE_COUNT
GSU_TELEMETRY_PVS_REVISION    = GSU_TELEMETRY_OFFSET + $06
GSU_TELEMETRY_SELECTION_REVISION = GSU_TELEMETRY_OFFSET + $08
GSU_TELEMETRY_ENCODED_BYTES   = GSU_TELEMETRY_OFFSET + $0A
GSU_TELEMETRY_NODE_COUNT      = GSU_TELEMETRY_OFFSET + $0C
GSU_TELEMETRY_PACKET_VERTEX_COUNT = GSU_TELEMETRY_OFFSET + $0E
GSU_TELEMETRY_PACKET_INDEX_COUNT = GSU_TELEMETRY_OFFSET + $10
GSU_TELEMETRY_PACKET_FACE_COUNT = GSU_TELEMETRY_OFFSET + $12
GSU_TELEMETRY_PACKET_PLANE_COUNT = GSU_TELEMETRY_OFFSET + $14
GSU_TELEMETRY_REJECT_FACE     = GSU_TELEMETRY_OFFSET + $16
GSU_TELEMETRY_REJECT_VERTEX   = GSU_TELEMETRY_OFFSET + $18
GSU_TELEMETRY_REJECT_INDEX    = GSU_TELEMETRY_OFFSET + $1A
GSU_TELEMETRY_PACKET_REVISION = GSU_TELEMETRY_OFFSET + $1C
GSU_TELEMETRY_PACKET_CAMERA_REVISION = GSU_TELEMETRY_OFFSET + $1E
GSU_TELEMETRY_GUARD_STATUS    = GSU_TELEMETRY_OFFSET + $20
GSU_TELEMETRY_DRAWABLE_COUNT  = GSU_TELEMETRY_OFFSET + $22
GSU_TELEMETRY_FRONT_COUNT     = GSU_TELEMETRY_OFFSET + $24
GSU_TELEMETRY_NEAR_COUNT      = GSU_TELEMETRY_OFFSET + $26
GSU_TELEMETRY_SCREEN_COUNT    = GSU_TELEMETRY_OFFSET + $28
GSU_TELEMETRY_PAINTER_NODE_COUNT = GSU_TELEMETRY_OFFSET + $2A
GSU_TELEMETRY_ERROR           = GSU_TELEMETRY_OFFSET + $2C
GSU_TELEMETRY_BRUSH_VISUAL_STATE = GSU_TELEMETRY_OFFSET + $2E
GSU_TELEMETRY_BRUSH_TRANSFORM_COUNT = GSU_TELEMETRY_OFFSET + $30
GSU_TELEMETRY_BRUSH_LINK_COUNT = GSU_TELEMETRY_OFFSET + $32
GSU_TELEMETRY_BRUSH_MIXED_TOKEN_COUNT = GSU_TELEMETRY_OFFSET + $34
GSU_TELEMETRY_BRUSH_OVERFLOW = GSU_TELEMETRY_OFFSET + $36
GSU_TELEMETRY_BRUSH_CURRENT_TOKEN = GSU_TELEMETRY_OFFSET + $38
GSU_TELEMETRY_BRUSH_CURRENT_SLOT = GSU_TELEMETRY_OFFSET + $3A
GSU_TELEMETRY_BRUSH_CURRENT_FACE = GSU_TELEMETRY_OFFSET + $3C
GSU_TELEMETRY_BRUSH_CURRENT_TEXTURE = GSU_TELEMETRY_OFFSET + $3E
GSU_SOURCE_FACE_IDS_OFFSET    = $8860
GSU_SOURCE_FACE_IDS_BYTES     = GSU_PACKET_FACE_CAPACITY * 2
; Brush-enabled rendering replaces the painter-ordered source-face sidecar
; with one tagged world/fragment token stream after world selection.
GSU_BRUSH_MIXED_TOKENS_OFFSET = GSU_SOURCE_FACE_IDS_OFFSET
GSU_BRUSH_MIXED_TOKEN_CAPACITY = (GSU_FACE_PLANES_OFFSET - GSU_BRUSH_MIXED_TOKENS_OFFSET) / 2
; Complete fly brush states require at most 1,149 mixed tokens. Trade 32
; spare projection-cache entries for 64 tokens without moving the vertices.
GSU_FACE_PLANES_OFFSET        = $9170
GSU_FACE_PLANES_CAPACITY      = $07F8
GSU_FACE_PLANES_GUARD_OFFSET  = $9966
; A selector command can encounter at most 1,297 drawable vertices in any
; non-solid E1M3 PVS row. Cache 1,504 projected x/y pairs with explicit tagged
; remap state, leaving deterministic headroom without generation counters.
GSU_PROJECTION_CACHE_OFFSET   = $9968
GSU_PROJECTION_CACHE_ENTRIES  = 1504
GSU_PROJECTION_CACHE_RECORD_BYTES = 4
GSU_PROJECTION_CACHE_BYTES    = GSU_PROJECTION_CACHE_ENTRIES * GSU_PROJECTION_CACHE_RECORD_BYTES
GSU_PROJECTION_CACHE_GUARD_OFFSET = $B0E8
GSU_BRUSH_ARBITER_SCREEN_OFFSET = GSU_PROJECTION_CACHE_OFFSET
GSU_BRUSH_ARBITER_SCREEN_BYTES = BSP_BRUSH_FLY_GROUP_PROJECTED_VERTEX_MAX * GSU_BRUSH_ARBITER_SCREEN_RECORD_BYTES
; Contested dynamic-brush rows may visit candidates near-to-far. Preserve the
; reference renderer's exact equal-depth authority with one metadata pointer
; per logical X.
; A valid depth-row entry owns the corresponding metadata word, so this row needs no
; separate clear. Both arrays occupy the otherwise-idle projection-cache tail.
GSU_BRUSH_ARBITER_WINNER_ROW_OFFSET = GSU_BRUSH_ARBITER_SCREEN_OFFSET + GSU_BRUSH_ARBITER_SCREEN_BYTES
GSU_BRUSH_ARBITER_WINNER_ROW_BYTES = GSU_BRUSH_ARBITER_DEPTH_ROW_BYTES
; After admission, the selector reuses WORLD_VERTEX_REMAP as a direct source-
; face -> packet-first-index map. Its untouched tail is phase-separated
; renderer storage for direct raw-QBSF-leaf heads.
GSU_BRUSH_LEAF_HEADS_OFFSET   = GSU_VERTEX_REMAP_OFFSET + BSP_WORLD_FACE_COUNT * 2
GSU_BRUSH_LEAF_HEADS_BYTES    = BSP_BRUSH_LEAF_HEAD_COUNT * 2
GSU_BRUSH_LEAF_HEADS_END      = GSU_BRUSH_LEAF_HEADS_OFFSET + GSU_BRUSH_LEAF_HEADS_BYTES
; Links follow the direct heads in the remap tail. Rejecting QBSF solid
; buckets proves 393 live replay+signon fragments for fly; reserve 625 records
; so the runtime never depends on the smaller replay-only maximum.
GSU_BRUSH_LINKS_OFFSET        = GSU_BRUSH_LEAF_HEADS_END
; Link word 1 packs a 9-bit one-based next index and a 7-bit unified slot.
GSU_BRUSH_LINK_RECORD_BYTES   = 4
GSU_BRUSH_LINK_CAPACITY       = 511
GSU_BRUSH_LINKS_END           = GSU_BRUSH_LINKS_OFFSET + GSU_BRUSH_LINK_CAPACITY * GSU_BRUSH_LINK_RECORD_BYTES
; MDL billboard visibility is already reduced to at most one compact group per
; origin leaf. These tables share the selector-idle remap tail with brush links.
GSU_ALIAS_GROUPS_OFFSET       = GSU_BRUSH_LINKS_END
GSU_ALIAS_GROUP_RECORD_BYTES = 6
GSU_ALIAS_GROUPS_BYTES        = BSP_ALIAS_MAX_GROUPS * GSU_ALIAS_GROUP_RECORD_BYTES
GSU_ALIAS_GROUPS_END          = GSU_ALIAS_GROUPS_OFFSET + GSU_ALIAS_GROUPS_BYTES
; Once painter traversal has consumed the leaf groups, reuse their arena for
; one exact-depth record per flattened token. The sorted original ordinals are
; then written into the already-reserved mixed-token alias suffix, so QAV2
; pointers and masks stay keyed by canonical QBA1 token ordinal.
GSU_ALIAS_RENDER_SORT_OFFSET  = GSU_ALIAS_GROUPS_OFFSET
GSU_ALIAS_RENDER_SORT_RECORD_BYTES = 4
GSU_ALIAS_RENDER_SORT_BYTES   = BSP_ALIAS_MAX_VISIBLE_STATES * GSU_ALIAS_RENDER_SORT_RECORD_BYTES
GSU_ALIAS_RENDER_SORT_END     = GSU_ALIAS_RENDER_SORT_OFFSET + GSU_ALIAS_RENDER_SORT_BYTES
GSU_ALIAS_TOKENS_OFFSET       = GSU_ALIAS_GROUPS_END
GSU_ALIAS_TOKENS_BYTES        = BSP_ALIAS_MAX_VISIBLE_STATES
GSU_ALIAS_TOKENS_END          = GSU_ALIAS_TOKENS_OFFSET + GSU_ALIAS_TOKENS_BYTES
; Ordered alias depth masks must survive every opaque world/brush raster. The
; selector-idle remap tail is persistent for that complete phase, unlike the
; polygon scratch. A pointer sentinel selects the zero-cost visible path or a
; projection-level hidden reject; only partial tokens point at staged masks.
GSU_ALIAS_VISIBILITY_POINTERS_OFFSET = GSU_ALIAS_TOKENS_END
GSU_ALIAS_VISIBILITY_POINTERS_BYTES = BSP_ALIAS_MAX_VISIBLE_STATES * 2
GSU_ALIAS_VISIBILITY_POINTERS_END = GSU_ALIAS_VISIBILITY_POINTERS_OFFSET + GSU_ALIAS_VISIBILITY_POINTERS_BYTES
GSU_ALIAS_VISIBILITY_MASKS_OFFSET = GSU_ALIAS_VISIBILITY_POINTERS_END
GSU_ALIAS_VISIBILITY_MASKS_BYTES = BSP_ALIAS_VISIBILITY_MAX_MASK_BYTES
GSU_ALIAS_VISIBILITY_MASKS_END = GSU_ALIAS_VISIBILITY_MASKS_OFFSET + GSU_ALIAS_VISIBILITY_MASKS_BYTES
; Painter traversal and alias sorting are complete before billboard raster.
; Reuse their group arena for the fly-only BSP segment stack, keeping the
; per-token visibility pointers intact throughout every traced sprite.
GSU_ALIAS_FLY_TRACE_STACK_OFFSET = GSU_ALIAS_GROUPS_OFFSET
GSU_ALIAS_FLY_TRACE_RECORD_BYTES = 8
GSU_ALIAS_FLY_TRACE_STACK_BYTES = BSP_WORLD_MAX_NODE_DEPTH * GSU_ALIAS_FLY_TRACE_RECORD_BYTES
GSU_ALIAS_FLY_TRACE_STACK_END = GSU_ALIAS_FLY_TRACE_STACK_OFFSET + GSU_ALIAS_FLY_TRACE_STACK_BYTES
; Quarter-depth lookup for Q6 projection: 1,024 unsigned Q12 words. The
; natural lightmap colormap begins at $C000 and phase-overlays the far suffix.
GSU_RECIPROCAL_OFFSET         = $BD20
GSU_RECIPROCAL_ENTRIES        = 1024
GSU_RECIPROCAL_BYTES          = GSU_RECIPROCAL_ENTRIES * 2
GSU_RECIPROCAL_RAM_BYTES      = GSU_TEXTURE_COLORMAP_OFFSET - GSU_RECIPROCAL_OFFSET
GSU_RECIPROCAL_RAM_ENTRIES    = GSU_RECIPROCAL_RAM_BYTES / 2
GSU_RECIPROCAL_SUFFIX_BYTES   = GSU_RECIPROCAL_BYTES - GSU_RECIPROCAL_RAM_BYTES
GSU_RECIPROCAL_GUARD_OFFSET   = GSU_RECIPROCAL_OFFSET + GSU_RECIPROCAL_BYTES

BSP_LOGICAL_WIDTH             = 128
BSP_LOGICAL_HEIGHT            = 112
BSP_PHYSICAL_WIDTH            = 256
BSP_PHYSICAL_HEIGHT           = 224
BSP_UPLOAD_CHUNKS             = 8
BSP_UPLOAD_CHUNK_BYTES        = GSU_OUTPUT_BYTES / BSP_UPLOAD_CHUNKS
BSP_TEXTURE_UPLOAD_CHUNKS     = 4
; Four equal chunks keep the worst visible-page DMA near 21 scanlines, leaving
; enough VBlank for the 512-byte temporal CGRAM DMA and interrupt bookkeeping.
BSP_TEXTURE_UPLOAD_CHUNK_BYTES = GSU_TEXTURE_VISIBLE_BYTES / BSP_TEXTURE_UPLOAD_CHUNKS
BSP_TEXTURE_UPLOAD_LAST_CHUNK_BYTES = GSU_TEXTURE_VISIBLE_BYTES - BSP_TEXTURE_UPLOAD_CHUNK_BYTES * (BSP_TEXTURE_UPLOAD_CHUNKS - 1)
.assert BSP_VERTEX_COUNT * 4 <= GSU_VERTICES_CAPACITY, error, "BSP vertices exceed cartridge RAM"
.assert BSP_INDEX_COUNT * 2 <= GSU_INDICES_CAPACITY, error, "BSP indices exceed cartridge RAM"
.assert BSP_FACE_COUNT * BSP_FACE_RECORD_BYTES <= GSU_FACES_CAPACITY, error, "BSP faces exceed cartridge RAM"
.assert GSU_PACKET_FACE_CAPACITY * BSP_FACE_RECORD_BYTES <= GSU_FACES_CAPACITY, error, "Runtime face packet exceeds cartridge RAM"
.assert BSP_FACE_COUNT * BSP_FACE_PLANE_RECORD_BYTES <= GSU_FACE_PLANES_CAPACITY, error, "BSP face planes exceed cartridge RAM"
.assert BSP_VERTEX_COUNT * 4 <= GSU_PROJECTED_CAPACITY, error, "BSP projected vertices exceed cartridge RAM"
.assert BSP_VERTEX_COUNT <= GSU_VALID_CAPACITY, error, "BSP validity array exceeds cartridge RAM"
.assert BSP_WORLD_FACE_BITSET_BYTES <= GSU_WORLD_VISIBILITY_CAPACITY, error, "Full-map face visibility row exceeds cartridge RAM"
.assert BSP_TEXTURE_UPLOAD_LAST_CHUNK_BYTES > 0, error, "Texture upload tail must be non-empty"
.assert (BSP_TEXTURE_UPLOAD_LAST_CHUNK_BYTES & 1) = 0, error, "Texture upload tail must be word aligned"
.assert BSP_TEXTURE_UPLOAD_LAST_CHUNK_BYTES <= BSP_TEXTURE_UPLOAD_CHUNK_BYTES, error, "Texture upload tail exceeds the bounded chunk"
.assert (GSU_TEXTURE_STATE_OFFSET & 1) = 0, error, "Texture state must remain word aligned"
.assert GSU_TEXTURE_STATE_OFFSET + GSU_TEXTURE_STATE_BYTES <= $0200, error, "Texture state exceeds short-address RAM"
.assert (GSU_CONVEX_STATE_OFFSET & 1) = 0, error, "Convex state must remain word aligned"
.assert GSU_CONVEX_STATE_OFFSET + GSU_CONVEX_STATE_BYTES <= $0200, error, "Convex state exceeds short-address RAM"
.assert (GSU_RENDER_STATE_OFFSET & 1) = 0, error, "Renderer state must remain word aligned"
.assert GSU_RENDER_STATE_OFFSET + GSU_RENDER_STATE_BYTES <= $0200, error, "Renderer state exceeds short-address RAM"
.assert GSU_RENDER_SOURCE_INDEX_OFFSET + 2 <= $0200, error, "Renderer source index exceeds short-address RAM"
.assert GSU_PACKET_STATE_OFFSET + GSU_PACKET_STATE_BYTES <= GSU_TEXTURE_STATE_OFFSET + GSU_TEXTURE_STATE_BYTES, error, "Overlaid packet state exceeds texture state"
.assert GSU_TEXTURE_ENDPOINT_STATE_OFFSET + GSU_TEXTURE_ENDPOINT_STATE_BYTES <= $0200, error, "Endpoint precompute state exceeds low RAM"
.assert GSU_TEXTURE_Q12_ROUTE_STATE_OFFSET + GSU_TEXTURE_Q12_ROUTE_STATE_BYTES <= $0200, error, "Q12 route state exceeds low RAM"
.assert GSU_TEXTURE_COMPOSED_ALLOWED_OFFSET + GSU_TEXTURE_COMPOSED_ALLOWED_BYTES <= $0200, error, "Composed-cache eligibility exceeds low RAM"
.assert GSU_TEXTURE_COMPOSED_ALLOWED_OFFSET + GSU_TEXTURE_COMPOSED_ALLOWED_BYTES <= GSU_TURBULENCE_TABLE_BASE_OFFSET, error, "Turbulence table base overlaps texture state"
.assert GSU_TURBULENCE_TABLE_BASE_OFFSET + 2 = $0200, error, "Turbulence table base must occupy the final short-address word"
.assert GSU_PACKET_SIDECARS_GUARD_OFFSET + 2 <= GSU_WORLD_VISIBILITY_OFFSET, error, "Packet-sidecar guard overlaps world visibility"
.assert GSU_WORLD_VISIBILITY_OFFSET + GSU_WORLD_VISIBILITY_CAPACITY <= GSU_INDICES_OFFSET, error, "World visibility overlaps index packet"
.assert BSP_WORLD_VERTEX_COUNT * 2 <= GSU_VERTEX_REMAP_CAPACITY, error, "Vertex remap cannot hold every full-world vertex ID"
.assert GSU_VERTEX_REMAP_OFFSET + GSU_VERTEX_REMAP_CAPACITY = GSU_VERTEX_REMAP_GUARD_OFFSET, error, "Vertex remap capacity disagrees with its guard"
.assert GSU_VERTEX_REMAP_GUARD_OFFSET + 2 <= GSU_SELECTED_FACES_OFFSET, error, "Vertex remap guard overlaps selected faces"
.assert BSP_WORLD_FACE_BITSET_BYTES <= GSU_SELECTED_FACES_CAPACITY, error, "Selected-face scratch cannot hold every full-world face bit"
.assert GSU_SELECTED_FACES_OFFSET + GSU_SELECTED_FACES_CAPACITY = GSU_SELECTED_FACES_GUARD_OFFSET, error, "Selected-face scratch disagrees with its guard"
.assert GSU_SELECTED_FACES_GUARD_OFFSET + 2 = GSU_PACKET_SIDECARS_OFFSET, error, "Selected-face guard moved"
.assert GSU_PACKET_SIDECARS_OFFSET + GSU_PACKET_SIDECARS_BYTES <= GSU_PACKET_SIDECARS_GUARD_OFFSET, error, "Packet sidecars overlap their guard"
.assert GSU_PACKET_SIDECARS_GUARD_OFFSET + 2 <= GSU_INDICES_OFFSET, error, "Packet-sidecar guard overlaps indices"
.assert GSU_VERTICES_OFFSET + GSU_VERTICES_CAPACITY = GSU_VERTICES_GUARD_OFFSET, error, "Vertex packet disagrees with its guard"
.assert GSU_PROJECTION_CACHE_GUARD_OFFSET + 2 <= GSU_VERTICES_OFFSET, error, "Projection-cache guard overlaps packet vertices"
.assert GSU_VERTICES_GUARD_OFFSET + 2 <= GSU_RECIPROCAL_OFFSET, error, "Vertex-tail guard overlaps reciprocal table"
.assert GSU_INDICES_OFFSET + GSU_INDICES_CAPACITY = GSU_INDICES_GUARD_OFFSET, error, "Index packet disagrees with its guard"
.assert GSU_INDICES_GUARD_OFFSET + 2 = GSU_FACES_OFFSET, error, "Index/face guard moved"
.assert GSU_FACES_OFFSET + GSU_FACES_CAPACITY = GSU_PROJECTED_OFFSET, error, "Face packet overlaps projected vertices"
.assert GSU_OUTPUT_OFFSET + GSU_OUTPUT_BYTES = GSU_LOGICAL_OFFSET, error, "Expanded and logical frames must be adjacent"
.assert GSU_LOGICAL_OFFSET + GSU_LOGICAL_BYTES <= GSU_CODE_OFFSET, error, "Logical frame overlaps GSU code"
.assert GSU_LOGICAL_OFFSET + GSU_LOGICAL_BYTES = GSU_BRUSH_CODE_OFFSET, error, "Brush code must start after the logical frame"
.assert GSU_BRUSH_CODE_OFFSET + GSU_BRUSH_CODE_CAPACITY <= GSU_AUX_CODE_OFFSET, error, "Brush code overlaps auxiliary GSU code"
.assert GSU_TEXTURE_FRAMEBUFFER_OFFSET + GSU_TEXTURE_FRAMEBUFFER_BYTES <= GSU_BRUSH_CODE_OFFSET, error, "8bpp framebuffer overlaps GSU overlays"
.assert GSU_DIVIDE_Q12_HOT_MIRROR_OFFSET = $4000, error, "Q12 hot mirror moved away from the textured framebuffer tail"
.assert GSU_DIVIDE_Q12_HOT_MIRROR_END = GSU_BRUSH_CODE_OFFSET, error, "Q12 hot mirror no longer ends at brush code"
.assert GSU_DIVIDE_Q12_HOT_MIRROR_BYTES = $4C00, error, "Q12 hot mirror no longer fills the phase-overlay gap"
.assert GSU_DIVIDE_Q12_HOT_MIRROR_ENTRIES = $1300, error, "Q12 hot mirror entry count changed"
.assert GSU_DIVIDE_Q12_HOT_MIRROR_BYTES <= $8000, error, "Q12 hot mirror copy crosses its source ROM bank"
.assert GSU_RASTER_SCRATCH_OFFSET + GSU_RASTER_SCRATCH_BYTES <= GSU_SIN_OFFSET, error, "Raster scratch overlaps tables"
.assert GSU_TEXTURE_ENDPOINT_STAGE_END = $83F8, error, "Endpoint staging arena no longer contains 426 records"
.assert GSU_TEXTURE_ENDPOINT_STAGE_OFFSET >= GSU_RASTER_SCRATCH_OFFSET, error, "Endpoint staging starts below raster scratch"
.assert GSU_TEXTURE_ENDPOINT_STAGE_END <= GSU_SIN_OFFSET, error, "Endpoint staging overlaps trigonometry tables"
.if BSP_BRUSH_DYNAMIC_REPLAY_SUPPORTED
.assert GSU_BRUSH_ARBITER_DEPTH_ROW_OFFSET >= GSU_RASTER_SCRATCH_OFFSET + $0580, error, "Brush depth row overlaps texture polygon scratch"
.assert GSU_BRUSH_ARBITER_DEPTH_ROW_BYTES = BSP_LOGICAL_WIDTH * 2, error, "Brush depth row no longer matches the logical width"
.assert GSU_BRUSH_ARBITER_METADATA_OFFSET + GSU_BRUSH_ARBITER_METADATA_BYTES <= GSU_SIN_OFFSET, error, "Brush metadata overlaps trigonometry tables"
.assert GSU_BRUSH_ARBITER_SCREEN_OFFSET + GSU_BRUSH_ARBITER_SCREEN_BYTES <= GSU_PROJECTION_CACHE_GUARD_OFFSET, error, "Brush projected polygons exceed the idle projection cache"
.assert GSU_BRUSH_ARBITER_WINNER_ROW_OFFSET + GSU_BRUSH_ARBITER_WINNER_ROW_BYTES <= GSU_PROJECTION_CACHE_GUARD_OFFSET, error, "Brush winner row exceeds the idle projection cache"
.endif
.assert GSU_LIGHTMAP_CACHE_OFFSET + GSU_LIGHTMAP_CACHE_BYTES <= GSU_PAINTER_NODE_MASK_OFFSET, error, "Lightmap cache overlaps painter-node state"
.assert GSU_PAINTER_NODE_MASK_OFFSET + GSU_PAINTER_NODE_MASK_BYTES <= GSU_TEXTURE_EDGE_DIVIDE_CACHE_OFFSET, error, "Painter-node mask overlaps edge divide cache"
.assert GSU_TEXTURE_EDGE_DIVIDE_CACHE_OFFSET + GSU_TEXTURE_EDGE_DIVIDE_CACHE_BYTES <= GSU_BOOT_PARAMETERS_OFFSET, error, "Edge divide cache overlaps boot parameters"
.assert GSU_BOOT_PARAMETERS_OFFSET + GSU_BOOT_PARAMETERS_BYTES <= GSU_TEXTURE_BLOCK_COORDS_OFFSET, error, "Boot parameters overlap block coordinates"
.assert GSU_TEXTURE_BLOCK_COORDS_OFFSET + GSU_TEXTURE_BLOCK_COORDS_BYTES <= GSU_PAINTER_NODE_MASK_GUARD_OFFSET, error, "Block coordinates overlap painter-node guard"
.assert GSU_TURBULENCE_PRESENT_OFFSET + 2 <= GSU_PAINTER_NODE_MASK_GUARD_OFFSET, error, "Turbulence-present word overlaps painter-node guard"
.assert (GSU_RECIPROCAL_RAM_BYTES & 1) = 0, error, "RAM reciprocal prefix must contain complete words"
.assert GSU_RECIPROCAL_RAM_BYTES < GSU_RECIPROCAL_BYTES, error, "RAM reciprocal prefix must leave a ROM fallback suffix"
.assert GSU_RECIPROCAL_OFFSET + GSU_RECIPROCAL_RAM_BYTES = GSU_TEXTURE_COLORMAP_OFFSET, error, "Reciprocal suffix moved away from its colormap phase overlay"
.assert GSU_RECIPROCAL_SUFFIX_BYTES > 0, error, "Reciprocal suffix phase overlay must not be empty"
.assert GSU_RECIPROCAL_GUARD_OFFSET <= GSU_RAM_BANK_BYTES, error, "Reciprocal table exceeds cartridge RAM bank $71"
.assert GSU_BOOT_PARAMETERS_OFFSET + GSU_BOOT_PARAMETERS_BYTES <= GSU_PAINTER_NODE_MASK_GUARD_OFFSET, error, "Boot parameters overlap painter-node state"
.assert GSU_PAINTER_NODE_MASK_OFFSET + GSU_PAINTER_NODE_MASK_BYTES <= GSU_PAINTER_NODE_MASK_GUARD_OFFSET, error, "Painter-node mask overlaps its guard"
.assert GSU_PAINTER_NODE_MASK_GUARD_OFFSET + 2 = GSU_COMMAND_OFFSET, error, "Painter-node guard moved away from command buffer"
.assert GSU_COMMAND_OFFSET + GSU_COMMAND_BYTES <= GSU_TELEMETRY_OFFSET, error, "BSP command overlaps telemetry"
.assert GSU_ALIAS_RENDER_ROW_OFFSET + GSU_ALIAS_RENDER_ROW_BYTES <= GSU_TELEMETRY_OFFSET, error, "Alias render-row snapshot overlaps telemetry"
.assert GSU_SKY_COMMAND_END_OFFSET = GSU_TELEMETRY_OFFSET, error, "Sky command state must fill the reserved command/telemetry gap exactly"
.assert GSU_SKY_HOT_CODE_OFFSET = GSU_RASTER_SCRATCH_OFFSET, error, "Sky hot overlay moved away from the raster phase gap"
.assert GSU_SKY_HOT_CODE_OFFSET + GSU_SKY_HOT_CODE_CAPACITY = GSU_SKY_COMPOSITOR_SCRATCH_OFFSET, error, "Sky hot overlay no longer fills its bounded raster gap"
.assert GSU_TURBULENCE_HOT_CODE_OFFSET >= GSU_DIVIDE_Q12_HOT_MIRROR_OFFSET, error, "Turbulence hot code starts below the reciprocal mirror"
.assert GSU_TURBULENCE_HOT_CODE_OFFSET + GSU_TURBULENCE_HOT_CODE_CAPACITY = GSU_DIVIDE_Q12_HOT_MIRROR_END, error, "Turbulence hot code no longer fills the reciprocal mirror tail"
.assert (GSU_DIVIDE_Q12_HOT_MIRROR_SAFE_BYTES & (GSU_DIVIDE_Q12_RECIPROCAL_ENTRY_BYTES-1)) = 0, error, "Sky hot overlay splits a reciprocal entry"
.assert GSU_DIVIDE_Q12_HOT_MIRROR_SAFE_ENTRIES = $12BF, error, "Safe Q12 mirror prefix changed"
.assert GSU_SKY_COMPOSITOR_SCRATCH_OFFSET = GSU_RASTER_SCRATCH_OFFSET + $0180, error, "Sky compositor scratch no longer begins at the texture polygon arena"
.assert GSU_SKY_COMPOSITOR_SCRATCH_OFFSET + GSU_SKY_COMPOSITOR_SCRATCH_BYTES = GSU_SIN_OFFSET, error, "Sky compositor scratch no longer ends at the trigonometry tables"
.assert GSU_TELEMETRY_OFFSET + GSU_TELEMETRY_BYTES = GSU_SOURCE_FACE_IDS_OFFSET, error, "BSP telemetry overlaps source-face sidecar"
.assert GSU_SOURCE_FACE_IDS_OFFSET + GSU_SOURCE_FACE_IDS_BYTES <= GSU_FACE_PLANES_OFFSET, error, "Source-face sidecar overlaps face planes"
.if BSP_BRUSH_DYNAMIC_REPLAY_SUPPORTED
.assert GSU_BRUSH_MIXED_TOKEN_CAPACITY >= 1028, error, "Brush mixed-token capacity regressed"
.assert GSU_BRUSH_MIXED_TOKEN_CAPACITY >= GSU_PACKET_FACE_CAPACITY + BSP_BRUSH_FLY_LINK_MAX + BSP_BRUSH_FLY_LEAF_MARKER_MAX, error, "Brush mixed tokens cannot hold the proven fly snapshot and leaf markers"
.assert GSU_BRUSH_MIXED_TOKEN_CAPACITY >= GSU_PACKET_FACE_CAPACITY + BSP_BRUSH_FLY_LINK_MAX + BSP_BRUSH_FLY_LEAF_MARKER_MAX + BSP_ALIAS_MAX_VISIBLE_STATES, error, "Mixed tokens cannot hold the proven brush and alias maxima"
.endif
.assert GSU_BRUSH_LEAF_HEADS_OFFSET >= GSU_VERTEX_REMAP_OFFSET + BSP_WORLD_FACE_COUNT * 2, error, "Brush leaf heads overlap the face lookup"
.assert BSP_BRUSH_LEAF_HEAD_COUNT = BSP_WORLD_VIS_LEAF_COUNT + 1, error, "Brush leaf heads must cover the world VIS domain"
.assert BSP_BRUSH_FRAGMENT_BUCKET_LEAF_MAX < BSP_BRUSH_LEAF_HEAD_COUNT, error, "Brush fragment bucket escapes leaf heads"
.assert BSP_BRUSH_SOLID_FALLBACK_LEAF = 0, error, "Brush solid fallback leaf moved"
.assert GSU_BRUSH_LEAF_HEADS_END <= GSU_VERTEX_REMAP_GUARD_OFFSET, error, "Brush leaf heads escape the phase-separated remap tail"
.if BSP_BRUSH_DYNAMIC_REPLAY_SUPPORTED
.assert GSU_BRUSH_LINK_CAPACITY >= BSP_BRUSH_FLY_LINK_MAX, error, "Brush links cannot hold the proven fly snapshot"
.endif
.assert GSU_BRUSH_LINK_CAPACITY <= 511, error, "Brush links exceed packed nine-bit indices"
.assert GSU_BRUSH_LINKS_END <= GSU_VERTEX_REMAP_GUARD_OFFSET, error, "Brush links escape the phase-separated remap tail"
.assert GSU_ALIAS_GROUPS_END <= GSU_VERTEX_REMAP_GUARD_OFFSET, error, "Alias groups escape the phase-separated remap tail"
.assert GSU_ALIAS_RENDER_SORT_END <= GSU_ALIAS_GROUPS_END, error, "Alias render sort exceeds the retired group arena"
.assert GSU_ALIAS_TOKENS_END <= GSU_VERTEX_REMAP_GUARD_OFFSET, error, "Alias tokens escape the phase-separated remap tail"
.assert GSU_ALIAS_VISIBILITY_MASKS_END <= GSU_VERTEX_REMAP_GUARD_OFFSET, error, "Alias visibility masks escape the persistent remap tail"
.assert GSU_ALIAS_FLY_TRACE_STACK_END <= GSU_ALIAS_GROUPS_END, error, "Fly alias trace stack escapes the retired group arena"
.assert GSU_FACE_PLANES_OFFSET + GSU_FACE_PLANES_CAPACITY = GSU_PROJECTION_CACHE_OFFSET, error, "Projection cache moved away from face planes"
.assert GSU_FACE_PLANES_GUARD_OFFSET + 2 <= GSU_FACE_PLANES_OFFSET + GSU_FACE_PLANES_CAPACITY, error, "Face-plane guard escapes its packet"
.assert GSU_PROJECTION_CACHE_OFFSET + GSU_PROJECTION_CACHE_BYTES = GSU_PROJECTION_CACHE_GUARD_OFFSET, error, "Projection cache capacity disagrees with its guard"
.assert GSU_PROJECTION_CACHE_GUARD_OFFSET + 2 <= GSU_RAM_BANK_BYTES, error, "Projection cache exceeds cartridge RAM bank $71"
.assert GSU_EXPAND_STATE_OFFSET + GSU_EXPAND_STATE_BYTES <= GSU_CODE_OFFSET, error, "Flat expansion assets overlap GSU code"
.assert GSU_CODE_OFFSET + GSU_CODE_CAPACITY = GSU_RAM_BANK_BYTES, error, "GSU code no longer reaches the bank-$70 limit"
.assert GSU_AUX_CODE_OFFSET + GSU_AUX_CODE_CAPACITY = GSU_EXPAND_NIBBLE_OFFSET, error, "Auxiliary GSU code no longer ends at expansion lookup"
.assert GSU_EXPAND_NIBBLE_OFFSET + $0010 = GSU_EXPAND_STATE_OFFSET, error, "Expansion state is not adjacent to nibble lookup"
.assert GSU_EXPAND_STATE_OFFSET + GSU_EXPAND_STATE_BYTES <= GSU_RAM_BANK_BYTES, error, "Expansion state exceeds cartridge RAM bank $70"
.assert GSU_EXPAND_STATE_OFFSET + GSU_EXPAND_STATE_BYTES <= GSU_CODE_OFFSET, error, "Expansion state overlaps GSU code"
.assert GSU_AUX_CODE_OFFSET + GSU_AUX_CODE_CAPACITY <= GSU_EXPAND_NIBBLE_OFFSET, error, "Auxiliary GSU code overlaps expansion lookup"
.assert GSU_WORLD_VISIBILITY_OFFSET + GSU_WORLD_VISIBILITY_CAPACITY <= GSU_TEXTURE_COORD_MAP_OFFSET, error, "Texture coordinate map overlaps world visibility"
.assert GSU_TURBULENCE_TABLE_BASE_OFFSET + 2 <= GSU_TURBULENCE_TABLE_OFFSET, error, "Turbulence table overlaps short-address state"
.assert GSU_TURBULENCE_TABLE_OFFSET + GSU_TURBULENCE_TABLE_BYTES <= GSU_VERTEX_REMAP_OFFSET, error, "Turbulence table exceeds the pre-remap gap"
.assert GSU_TEXTURE_COORD_MAP_OFFSET + GSU_TEXTURE_COORD_MAP_BYTES <= GSU_RAM_BANK_BYTES, error, "Texture coordinate map exceeds data RAM"
.assert GSU_TEXTURE_COLORMAP_OFFSET + GSU_LIGHTMAP_COLORMAP_BYTES = GSU_RAM_BANK_BYTES, error, "Natural lightmap colormap must fill the bank tail"
.assert GSU_LIGHTMAP_ROW_STAGE_OFFSET + GSU_LIGHTMAP_ROW_STAGE_BYTES <= GSU_INDICES_OFFSET, error, "Lightmap row stage overlaps packet indices"
.if BSP_BRUSH_DYNAMIC_REPLAY_SUPPORTED
.assert GSU_BRUSH_ROW_STAGE_RECORDS <= 72, error, "Brush row stage exceeds its proven capacity"
.assert GSU_BRUSH_ROW_STAGE_OFFSET + GSU_BRUSH_ROW_STAGE_BYTES <= GSU_LIGHTMAP_ROW_STAGE_OFFSET + GSU_LIGHTMAP_ROW_STAGE_BYTES, error, "Brush row stage exceeds the idle lightmap-row arena"
.endif

.endif
