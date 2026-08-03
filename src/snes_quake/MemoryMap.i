; Cartridge RAM layout shared by the S-CPU and GSU BSP renderer.

.ifndef __QUAKE_BSP_MEMORY_MAP_I__
__QUAKE_BSP_MEMORY_MAP_I__ = 1

.include "Data/QuakeBSPScene.i"
.include "Data/QuakeBSPBrushAssets.i"
.include "Data/QuakeBSPMonsterCameras.i"

GSU_RAM_BANK_BYTES            = $10000
GSU_BRUSH_CODE_OFFSET         = $8C00
GSU_BRUSH_CODE_CAPACITY       = $2400
GSU_AUX_CODE_OFFSET           = $B210
GSU_AUX_CODE_CAPACITY         = $0DD0
GSU_CODE_OFFSET               = $C000
GSU_CODE_CAPACITY             = $4000

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
GSU_PACKET_STATE_OFFSET       = GSU_TEXTURE_STATE_OFFSET
GSU_PACKET_STATE_BYTES        = $0080
GSU_WORLD_VISIBILITY_OFFSET   = $4800
GSU_WORLD_VISIBILITY_CAPACITY = $0280

; Runtime packet-builder scratch retained between selector passes.  The remap
; table stores one tagged local vertex ID for every full-world vertex.  The
; selected-face bitset and admission sidecars sit immediately below the packet.
GSU_VERTEX_REMAP_OFFSET       = $0280
GSU_VERTEX_REMAP_CAPACITY     = $397C
GSU_VERTEX_REMAP_GUARD_OFFSET = $3BFC
GSU_SELECTED_FACES_OFFSET     = $4000
GSU_SELECTED_FACES_CAPACITY   = $027E
GSU_SELECTED_FACES_GUARD_OFFSET = $427E
GSU_PACKET_SIDECARS_OFFSET    = $4280
GSU_PACKET_SIDECAR_RECORD_BYTES = 4
GSU_PACKET_FACE_CAPACITY      = 341
GSU_PACKET_SIDECARS_BYTES     = GSU_PACKET_FACE_CAPACITY * GSU_PACKET_SIDECAR_RECORD_BYTES
GSU_PACKET_SIDECARS_GUARD_OFFSET = $47FE
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
; Textured renderers leave the remainder of bank $70 idle. Mirror the hot
; prefix of the exact Q12 reciprocal table there; flat rendering invalidates
; this phase overlay and the S-CPU restores it only on the next textured frame.
GSU_DIVIDE_Q12_HOT_MIRROR_OFFSET = GSU_TEXTURE_FRAMEBUFFER_OFFSET + GSU_TEXTURE_FRAMEBUFFER_BYTES
GSU_DIVIDE_Q12_HOT_MIRROR_END = GSU_BRUSH_CODE_OFFSET
GSU_DIVIDE_Q12_HOT_MIRROR_BYTES = GSU_DIVIDE_Q12_HOT_MIRROR_END - GSU_DIVIDE_Q12_HOT_MIRROR_OFFSET
GSU_DIVIDE_Q12_HOT_MIRROR_ENTRIES = GSU_DIVIDE_Q12_HOT_MIRROR_BYTES / GSU_DIVIDE_Q12_RECIPROCAL_ENTRY_BYTES

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
GSU_COS_OFFSET                = $8420
; Technique 4 copies the current face's complete packed light grid here.
GSU_LIGHTMAP_CACHE_OFFSET     = $8440
GSU_LIGHTMAP_CACHE_BYTES      = $0100
; Technique 4 prepares one exact nine-sample S/T projective block here.
GSU_TEXTURE_BLOCK_COORDS_OFFSET = $8540
GSU_TEXTURE_BLOCK_COORDS_BYTES = 9 * 4
; Two shaded active edges retain exact Q12 reciprocal limbs while their
; endpoint pair (and therefore screen-Y denominator) remains unchanged.
GSU_TEXTURE_EDGE_DIVIDE_CACHE_OFFSET = GSU_TEXTURE_BLOCK_COORDS_OFFSET + GSU_TEXTURE_BLOCK_COORDS_BYTES
GSU_TEXTURE_EDGE_DIVIDE_CACHE_ENTRY_BYTES = 6
GSU_TEXTURE_EDGE_DIVIDE_CACHE_BYTES = 2 * GSU_TEXTURE_EDGE_DIVIDE_CACHE_ENTRY_BYTES
; The selector marks only accepted-face owners and their world-root ancestors.
; This gap is in data bank $71 and remains independent of renderer scratch.
GSU_PAINTER_NODE_MASK_OFFSET  = $8640
GSU_PAINTER_NODE_MASK_BYTES   = (BSP_WORLD_NODE_COUNT + 7) / 8
GSU_PAINTER_NODE_MASK_GUARD_OFFSET = $87FE
; Expansion switches RAMBR to bank $70, so its lookup tables live beside code.
GSU_EXPAND_LEFT_OFFSET        = $B000
GSU_EXPAND_RIGHT_OFFSET       = $B100
; ExpandFrame runs with RAMBR=0 so its bookkeeping must also live in bank $70.
; Keeping it beside the lookup tables prevents its stores from corrupting the
; 4bpp logical framebuffer at the bank-$70 mirror of raster scratch.
GSU_EXPAND_STATE_OFFSET       = $B200
GSU_EXPAND_STATE_BYTES        = $000C
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
GSU_BOOT_PARAMETERS_OFFSET    = $BFE0
GSU_BOOT_PARAMETERS_BYTES     = $0012
GSU_TEXTURE_COORD_MAP_OFFSET  = $4A80
GSU_TEXTURE_COORD_MAP_BYTES   = $0080
GSU_TEXTURE_DEPTH_SHADE_OFFSET = $4B00
GSU_TEXTURE_DEPTH_SHADE_BYTES = $0100
GSU_LIGHTMAP_COLORMAP_MAP_OFFSET = $4C00
GSU_LIGHTMAP_COLORMAP_MAP_BYTES = $0040
GSU_TEXTURE_COLORMAP_OFFSET   = $C000
GSU_TEXTURE_COLORMAP_BYTES    = $3700
GSU_LIGHTMAP_COLORMAP_BYTES   = $4000
GSU_COMMAND_OFFSET            = $8800
GSU_COMMAND_BYTES             = 13
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
GSU_FACE_PLANES_OFFSET        = $9000
GSU_FACE_PLANES_CAPACITY      = $0800
GSU_FACE_PLANES_GUARD_OFFSET  = $97FE
; A selector command can encounter at most 1,297 drawable vertices in any
; non-solid E1M3 PVS row. Cache 1,536 projected x/y pairs with explicit tagged
; remap state, leaving deterministic headroom without generation counters.
GSU_PROJECTION_CACHE_OFFSET   = $9800
GSU_PROJECTION_CACHE_ENTRIES  = 1536
GSU_PROJECTION_CACHE_RECORD_BYTES = 4
GSU_PROJECTION_CACHE_BYTES    = GSU_PROJECTION_CACHE_ENTRIES * GSU_PROJECTION_CACHE_RECORD_BYTES
GSU_PROJECTION_CACHE_GUARD_OFFSET = $B000
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
; Link word 1 packs a 10-bit one-based next index and a 6-bit unified slot.
GSU_BRUSH_LINK_RECORD_BYTES   = 4
GSU_BRUSH_LINK_CAPACITY       = 625
GSU_BRUSH_LINKS_END           = GSU_BRUSH_LINKS_OFFSET + GSU_BRUSH_LINK_CAPACITY * GSU_BRUSH_LINK_RECORD_BYTES
; Quarter-depth lookup for Q6 projection: 1,024 unsigned Q12 words.
GSU_RECIPROCAL_OFFSET         = $BD20
GSU_RECIPROCAL_BYTES          = $0800
GSU_RECIPROCAL_GUARD_OFFSET   = $C520

BSP_LOGICAL_WIDTH             = 128
BSP_LOGICAL_HEIGHT            = 112
BSP_PHYSICAL_WIDTH            = 256
BSP_PHYSICAL_HEIGHT           = 224
BSP_UPLOAD_CHUNKS             = 8
BSP_UPLOAD_CHUNK_BYTES        = GSU_OUTPUT_BYTES / BSP_UPLOAD_CHUNKS
BSP_TEXTURE_UPLOAD_CHUNKS     = 3
BSP_TEXTURE_UPLOAD_CHUNK_BYTES = $12AC
BSP_TEXTURE_UPLOAD_LAST_CHUNK_BYTES = GSU_TEXTURE_VISIBLE_BYTES - BSP_TEXTURE_UPLOAD_CHUNK_BYTES * (BSP_TEXTURE_UPLOAD_CHUNKS - 1)

.assert BSP_VERTEX_COUNT * 4 <= GSU_VERTICES_CAPACITY, error, "BSP vertices exceed cartridge RAM"
.assert BSP_INDEX_COUNT * 2 <= GSU_INDICES_CAPACITY, error, "BSP indices exceed cartridge RAM"
.assert BSP_FACE_COUNT * BSP_FACE_RECORD_BYTES <= GSU_FACES_CAPACITY, error, "BSP faces exceed cartridge RAM"
.assert BSP_FACE_COUNT * BSP_FACE_PLANE_RECORD_BYTES <= GSU_FACE_PLANES_CAPACITY, error, "BSP face planes exceed cartridge RAM"
.assert BSP_VERTEX_COUNT * 4 <= GSU_PROJECTED_CAPACITY, error, "BSP projected vertices exceed cartridge RAM"
.assert BSP_VERTEX_COUNT <= GSU_VALID_CAPACITY, error, "BSP validity array exceeds cartridge RAM"
.assert BSP_WORLD_FACE_BITSET_BYTES <= GSU_WORLD_VISIBILITY_CAPACITY, error, "Full-map face visibility row exceeds cartridge RAM"
.assert BSP_TEXTURE_UPLOAD_LAST_CHUNK_BYTES > 0, error, "Texture upload tail must be non-empty"
.assert (BSP_TEXTURE_UPLOAD_LAST_CHUNK_BYTES & 1) = 0, error, "Texture upload tail must be word aligned"
.assert (GSU_TEXTURE_STATE_OFFSET & 1) = 0, error, "Texture state must remain word aligned"
.assert GSU_TEXTURE_STATE_OFFSET + GSU_TEXTURE_STATE_BYTES <= $0200, error, "Texture state exceeds short-address RAM"
.assert (GSU_CONVEX_STATE_OFFSET & 1) = 0, error, "Convex state must remain word aligned"
.assert GSU_CONVEX_STATE_OFFSET + GSU_CONVEX_STATE_BYTES <= $0200, error, "Convex state exceeds short-address RAM"
.assert (GSU_RENDER_STATE_OFFSET & 1) = 0, error, "Renderer state must remain word aligned"
.assert GSU_RENDER_STATE_OFFSET + GSU_RENDER_STATE_BYTES <= $0200, error, "Renderer state exceeds short-address RAM"
.assert GSU_RENDER_SOURCE_INDEX_OFFSET + 2 <= $0200, error, "Renderer source index exceeds short-address RAM"
.assert GSU_PACKET_STATE_OFFSET + GSU_PACKET_STATE_BYTES <= GSU_TEXTURE_STATE_OFFSET + GSU_TEXTURE_STATE_BYTES, error, "Overlaid packet state exceeds texture state"
.assert GSU_TEXTURE_ENDPOINT_STATE_OFFSET + GSU_TEXTURE_ENDPOINT_STATE_BYTES <= $0200, error, "Endpoint precompute state exceeds low RAM"
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
.assert GSU_BRUSH_CODE_OFFSET + GSU_BRUSH_CODE_CAPACITY <= GSU_EXPAND_LEFT_OFFSET, error, "Brush code overlaps flat expansion tables"
.assert GSU_TEXTURE_FRAMEBUFFER_OFFSET + GSU_TEXTURE_FRAMEBUFFER_BYTES <= GSU_EXPAND_LEFT_OFFSET, error, "8bpp framebuffer overlaps flat expansion tables"
.assert GSU_DIVIDE_Q12_HOT_MIRROR_OFFSET = $4000, error, "Q12 hot mirror moved away from the textured framebuffer tail"
.assert GSU_DIVIDE_Q12_HOT_MIRROR_END = GSU_BRUSH_CODE_OFFSET, error, "Q12 hot mirror no longer ends at brush code"
.assert GSU_DIVIDE_Q12_HOT_MIRROR_BYTES = $4C00, error, "Q12 hot mirror no longer fills the phase-overlay gap"
.assert GSU_DIVIDE_Q12_HOT_MIRROR_ENTRIES = $1300, error, "Q12 hot mirror entry count changed"
.assert GSU_DIVIDE_Q12_HOT_MIRROR_BYTES <= $8000, error, "Q12 hot mirror copy crosses its source ROM bank"
.assert GSU_RASTER_SCRATCH_OFFSET + GSU_RASTER_SCRATCH_BYTES <= GSU_SIN_OFFSET, error, "Raster scratch overlaps tables"
.assert GSU_TEXTURE_ENDPOINT_STAGE_END = $83F8, error, "Endpoint staging arena no longer contains 426 records"
.assert GSU_TEXTURE_ENDPOINT_STAGE_OFFSET >= GSU_RASTER_SCRATCH_OFFSET, error, "Endpoint staging starts below raster scratch"
.assert GSU_TEXTURE_ENDPOINT_STAGE_END <= GSU_SIN_OFFSET, error, "Endpoint staging overlaps trigonometry tables"
.assert GSU_BRUSH_ARBITER_DEPTH_ROW_OFFSET >= GSU_RASTER_SCRATCH_OFFSET + $0580, error, "Brush depth row overlaps texture polygon scratch"
.assert GSU_BRUSH_ARBITER_DEPTH_ROW_BYTES = BSP_LOGICAL_WIDTH * 2, error, "Brush depth row no longer matches the logical width"
.assert GSU_BRUSH_ARBITER_METADATA_OFFSET + GSU_BRUSH_ARBITER_METADATA_BYTES <= GSU_SIN_OFFSET, error, "Brush metadata overlaps trigonometry tables"
.assert GSU_BRUSH_ARBITER_SCREEN_OFFSET + GSU_BRUSH_ARBITER_SCREEN_BYTES <= GSU_PROJECTION_CACHE_GUARD_OFFSET, error, "Brush projected polygons exceed the idle projection cache"
.assert GSU_BRUSH_ARBITER_WINNER_ROW_OFFSET + GSU_BRUSH_ARBITER_WINNER_ROW_BYTES <= GSU_PROJECTION_CACHE_GUARD_OFFSET, error, "Brush winner row exceeds the idle projection cache"
.assert GSU_LIGHTMAP_CACHE_OFFSET + GSU_LIGHTMAP_CACHE_BYTES <= GSU_PAINTER_NODE_MASK_OFFSET, error, "Lightmap cache overlaps painter-node state"
.assert GSU_LIGHTMAP_CACHE_OFFSET + GSU_LIGHTMAP_CACHE_BYTES <= GSU_TEXTURE_BLOCK_COORDS_OFFSET, error, "Lightmap cache overlaps block coordinates"
.assert GSU_TEXTURE_BLOCK_COORDS_OFFSET + GSU_TEXTURE_BLOCK_COORDS_BYTES <= GSU_PAINTER_NODE_MASK_OFFSET, error, "Block coordinates overlap painter-node state"
.assert GSU_TEXTURE_EDGE_DIVIDE_CACHE_OFFSET + GSU_TEXTURE_EDGE_DIVIDE_CACHE_BYTES <= GSU_PAINTER_NODE_MASK_OFFSET, error, "Edge divide cache overlaps painter-node state"
.assert GSU_RECIPROCAL_OFFSET + GSU_RECIPROCAL_BYTES = GSU_RECIPROCAL_GUARD_OFFSET, error, "Reciprocal table disagrees with its guard"
.assert GSU_RECIPROCAL_GUARD_OFFSET + 2 <= GSU_RAM_BANK_BYTES, error, "Reciprocal table exceeds cartridge RAM bank $71"
.assert GSU_BOOT_PARAMETERS_OFFSET + GSU_BOOT_PARAMETERS_BYTES <= GSU_TEXTURE_COLORMAP_OFFSET, error, "Boot parameters overlap the texture colormap"
.assert GSU_PAINTER_NODE_MASK_OFFSET + GSU_PAINTER_NODE_MASK_BYTES <= GSU_PAINTER_NODE_MASK_GUARD_OFFSET, error, "Painter-node mask overlaps its guard"
.assert GSU_PAINTER_NODE_MASK_GUARD_OFFSET + 2 = GSU_COMMAND_OFFSET, error, "Painter-node guard moved away from command buffer"
.assert GSU_COMMAND_OFFSET + GSU_COMMAND_BYTES <= GSU_TELEMETRY_OFFSET, error, "BSP command overlaps telemetry"
.assert GSU_TELEMETRY_OFFSET + GSU_TELEMETRY_BYTES = GSU_SOURCE_FACE_IDS_OFFSET, error, "BSP telemetry overlaps source-face sidecar"
.assert GSU_SOURCE_FACE_IDS_OFFSET + GSU_SOURCE_FACE_IDS_BYTES <= GSU_FACE_PLANES_OFFSET, error, "Source-face sidecar overlaps face planes"
.assert GSU_BRUSH_MIXED_TOKEN_CAPACITY >= 976, error, "Brush mixed-token capacity regressed"
.assert GSU_BRUSH_MIXED_TOKEN_CAPACITY >= GSU_PACKET_FACE_CAPACITY + BSP_BRUSH_FLY_LINK_MAX + BSP_BRUSH_FLY_LEAF_MARKER_MAX, error, "Brush mixed tokens cannot hold the proven fly snapshot and leaf markers"
.assert GSU_BRUSH_LEAF_HEADS_OFFSET >= GSU_VERTEX_REMAP_OFFSET + BSP_WORLD_FACE_COUNT * 2, error, "Brush leaf heads overlap the face lookup"
.assert BSP_BRUSH_LEAF_HEAD_COUNT = BSP_WORLD_VIS_LEAF_COUNT + 1, error, "Brush leaf heads must cover the world VIS domain"
.assert BSP_BRUSH_FRAGMENT_BUCKET_LEAF_MAX < BSP_BRUSH_LEAF_HEAD_COUNT, error, "Brush fragment bucket escapes leaf heads"
.assert BSP_BRUSH_SOLID_FALLBACK_LEAF = 0, error, "Brush solid fallback leaf moved"
.assert GSU_BRUSH_LEAF_HEADS_END <= GSU_VERTEX_REMAP_GUARD_OFFSET, error, "Brush leaf heads escape the phase-separated remap tail"
.assert GSU_BRUSH_LINK_CAPACITY >= BSP_BRUSH_FLY_LINK_MAX, error, "Brush links cannot hold the proven fly snapshot"
.assert GSU_BRUSH_LINK_CAPACITY <= 1024, error, "Brush links exceed packed ten-bit indices"
.assert GSU_BRUSH_LINKS_END <= GSU_VERTEX_REMAP_GUARD_OFFSET, error, "Brush links escape the phase-separated remap tail"
.assert GSU_VERTEX_REMAP_GUARD_OFFSET - GSU_BRUSH_LINKS_END >= 1442, error, "Brush leaf-head compaction lost its RAM reserve"
.assert GSU_FACE_PLANES_OFFSET + GSU_FACE_PLANES_CAPACITY = GSU_PROJECTION_CACHE_OFFSET, error, "Projection cache moved away from face planes"
.assert GSU_FACE_PLANES_GUARD_OFFSET + 2 <= GSU_FACE_PLANES_OFFSET + GSU_FACE_PLANES_CAPACITY, error, "Face-plane guard escapes its packet"
.assert GSU_PROJECTION_CACHE_OFFSET + GSU_PROJECTION_CACHE_BYTES = GSU_PROJECTION_CACHE_GUARD_OFFSET, error, "Projection cache capacity disagrees with its guard"
.assert GSU_PROJECTION_CACHE_GUARD_OFFSET + 2 <= GSU_RAM_BANK_BYTES, error, "Projection cache exceeds cartridge RAM bank $71"
.assert GSU_EXPAND_STATE_OFFSET + GSU_EXPAND_STATE_BYTES <= GSU_CODE_OFFSET, error, "Flat expansion assets overlap GSU code"
.assert GSU_CODE_OFFSET + GSU_CODE_CAPACITY = GSU_RAM_BANK_BYTES, error, "GSU code no longer reaches the bank-$70 limit"
.assert GSU_EXPAND_LEFT_OFFSET + $0100 = GSU_EXPAND_RIGHT_OFFSET, error, "Expansion lookup tables overlap"
.assert GSU_EXPAND_RIGHT_OFFSET + $0100 = GSU_EXPAND_STATE_OFFSET, error, "Expansion state is not adjacent to lookup tables"
.assert GSU_EXPAND_STATE_OFFSET + GSU_EXPAND_STATE_BYTES <= GSU_RAM_BANK_BYTES, error, "Expansion state exceeds cartridge RAM bank $70"
.assert GSU_EXPAND_STATE_OFFSET + GSU_EXPAND_STATE_BYTES <= GSU_BOOT_PARAMETERS_OFFSET, error, "Expansion state overlaps boot parameters"
.assert GSU_EXPAND_STATE_OFFSET + GSU_EXPAND_STATE_BYTES <= GSU_AUX_CODE_OFFSET, error, "Expansion state overlaps auxiliary GSU code"
.assert GSU_AUX_CODE_OFFSET + GSU_AUX_CODE_CAPACITY = GSU_BOOT_PARAMETERS_OFFSET, error, "Auxiliary GSU code no longer ends at boot parameters"
.assert GSU_AUX_CODE_OFFSET + GSU_AUX_CODE_CAPACITY <= GSU_BOOT_PARAMETERS_OFFSET, error, "Auxiliary GSU code overlaps boot parameters"
.assert GSU_BOOT_PARAMETERS_OFFSET + GSU_BOOT_PARAMETERS_BYTES <= GSU_CODE_OFFSET, error, "Boot parameters overlap GSU code"
.assert GSU_WORLD_VISIBILITY_OFFSET + GSU_WORLD_VISIBILITY_CAPACITY <= GSU_TEXTURE_COORD_MAP_OFFSET, error, "Texture coordinate map overlaps world visibility"
.assert GSU_TEXTURE_COORD_MAP_OFFSET + GSU_TEXTURE_COORD_MAP_BYTES <= GSU_RAM_BANK_BYTES, error, "Texture coordinate map exceeds data RAM"
.assert GSU_TEXTURE_COORD_MAP_OFFSET + GSU_TEXTURE_COORD_MAP_BYTES = GSU_TEXTURE_DEPTH_SHADE_OFFSET, error, "Texture depth LUT is not adjacent to the coordinate map"
.assert GSU_TEXTURE_DEPTH_SHADE_OFFSET + GSU_TEXTURE_DEPTH_SHADE_BYTES = GSU_LIGHTMAP_COLORMAP_MAP_OFFSET, error, "Texture depth LUT overlaps the lightmap row map"
.assert GSU_LIGHTMAP_COLORMAP_MAP_OFFSET + GSU_LIGHTMAP_COLORMAP_MAP_BYTES <= GSU_INDICES_OFFSET, error, "Lightmap row map overlaps packet indices"
.assert GSU_TEXTURE_COLORMAP_OFFSET + GSU_TEXTURE_COLORMAP_BYTES <= GSU_RAM_BANK_BYTES, error, "Texture shading colormap exceeds data RAM"
.assert GSU_TEXTURE_COLORMAP_OFFSET + GSU_LIGHTMAP_COLORMAP_BYTES = GSU_RAM_BANK_BYTES, error, "Natural lightmap colormap must fill the bank tail"
.assert GSU_LIGHTMAP_COLORMAP_MAP_OFFSET + GSU_LIGHTMAP_COLORMAP_MAP_BYTES <= GSU_LIGHTMAP_ROW_STAGE_OFFSET, error, "Lightmap row stage overlaps the colormap map"
.assert GSU_LIGHTMAP_ROW_STAGE_OFFSET + GSU_LIGHTMAP_ROW_STAGE_BYTES <= GSU_INDICES_OFFSET, error, "Lightmap row stage overlaps packet indices"
.assert GSU_BRUSH_ROW_STAGE_RECORDS = 72, error, "Brush row stage no longer covers the generated fly bound"
.assert GSU_BRUSH_ROW_STAGE_OFFSET + GSU_BRUSH_ROW_STAGE_BYTES <= GSU_LIGHTMAP_ROW_STAGE_OFFSET + GSU_LIGHTMAP_ROW_STAGE_BYTES, error, "Brush row stage exceeds the idle lightmap-row arena"

.endif
