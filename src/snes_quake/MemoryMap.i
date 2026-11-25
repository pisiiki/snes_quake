; Cartridge RAM layout shared by the S-CPU and GSU BSP renderer.

.ifndef __QUAKE_BSP_MEMORY_MAP_I__
__QUAKE_BSP_MEMORY_MAP_I__ = 1

.include "quake/CameraAngles.i"
.include "Data/QuakeBSPScene.i"
FLAT_BRUSH_CODE_VARIANT = 3
.ifdef PLAYABLE_MAP_ID
  .if PLAYABLE_MAP_ID = PLAYABLE_E1M1_MAP_ID
PLAYABLE_FLAT_BRUSH_DEPTH = 1
PLAYABLE_FLAT_BRUSH_PROJECTIVE_EDGE = 1
PLAYABLE_FLAT_COMPONENT_PROJECTOR = 1
PLAYABLE_E1M1_SHADED_PROJECTOR = 1
PLAYABLE_FLAT_MONOTONE_RASTER = 1
  .endif
  .if (PLAYABLE_MAP_ID = PLAYABLE_E1M2_MAP_ID) || (PLAYABLE_MAP_ID = PLAYABLE_E1M3_MAP_ID) || (PLAYABLE_MAP_ID = PLAYABLE_E1M4_MAP_ID)
PLAYABLE_FLAT_BRUSH_DEPTH = 1
PLAYABLE_FLAT_BRUSH_PROJECTIVE_EDGE = 1
PLAYABLE_FLAT_COMPONENT_PROJECTOR = 1
PLAYABLE_FLAT_BRUSH_MATERIAL = 1
PLAYABLE_FLAT_MONOTONE_RASTER = 1
  .endif
  .if .defined(PLAYABLE_FLAT_BRUSH_DEPTH) || .defined(PLAYABLE_FLAT_BRUSH_FRAGMENT)
PLAYABLE_FLAT_BRUSH_CODE = 1
  .endif
.endif
.ifndef BSP_PLAYER_WALK
BSP_PLAYER_WALK = 0
.endif
.assert .defined(BSP_DEMO_PLAYBACK_SUPPORTED), error, "A generated playable map scene is required"
.assert BSP_DEMO_PLAYBACK_SUPPORTED = 0, error, "Demo playback scenes cannot be assembled as a cartridge"
.ifndef BSP_LIGHTMAP_UNPACK_ROM_BANK
BSP_LIGHTMAP_UNPACK_ROM_BANK = 36
.endif
.ifndef BSP_WORLD_FACE_OWNERS_ROM_BANK
BSP_WORLD_FACE_OWNERS_ROM_BANK = 20
.endif
.include "Data/QuakeBSPBrushAssets.i"
.ifndef BSP_QUAKEC_GAMEPLAY
BSP_QUAKEC_GAMEPLAY = 0
.endif
.if BSP_QUAKEC_GAMEPLAY
.include "Data/QuakeBSPHubGameplay.i"
BSP_START_LARGE_PACKET = QC_HUB_ENABLED
.else
BSP_START_LARGE_PACKET = 0
.endif

; Only moving QuakeC grunts consume staged pose RAM. Immutable ambient actors
; retain their QBA1 ROM states and exact camera-independent facing records.
; BEGIN live-alias policy (QC_GRUNT_COUNT is intentionally absent for demos).
.if BSP_QUAKEC_GAMEPLAY
.if .defined(QC_GIB_FIRST_ROW) || .defined(QC_NAIL_COUNT)
GSU_HIDDEN_ACTOR_POSE = $FFFF
.else
GSU_HIDDEN_ACTOR_POSE = $8000
.endif
.ifdef QC_BACKPACK_COUNT
.ifdef QC_ARMOR_COUNT
.ifdef QC_POWERUP_COUNT
GSU_BACKPACK_FIRST = QC_GRUNT_COUNT + QC_ARMOR_COUNT + .defined(QC_NAIL_COUNT) + .defined(QC_SSG_ROW) + QC_POWERUP_COUNT
.else
GSU_BACKPACK_FIRST = QC_GRUNT_COUNT + QC_ARMOR_COUNT + .defined(QC_NAIL_COUNT)
.endif
.else
GSU_BACKPACK_FIRST = QC_GRUNT_COUNT
.endif
GSU_ALIAS_LIVE_COUNT = GSU_BACKPACK_FIRST + QC_BACKPACK_COUNT + 60 * .defined(QC_NAIL_COUNT) + .defined(QC_EXPLOBOX)
.elseif .defined(QC_ARMOR_COUNT)
GSU_ALIAS_LIVE_COUNT = QC_GRUNT_COUNT + QC_ARMOR_COUNT
.else
GSU_ALIAS_LIVE_COUNT = QC_GRUNT_COUNT + .defined(QC_KNIGHT_KEY_ROW) + 60*.defined(QC_CAMPAIGN_ITEMS)
.endif
  .if QC_GRUNT_COUNT > 0
BSP_ALIAS_LIVE_POSES = 1
  .else
BSP_ALIAS_LIVE_POSES = 0
  .endif
.else
BSP_ALIAS_LIVE_POSES = 0
.endif
; END live-alias policy
.include "Data/QuakeBSPComposedCache.i"
.include "Data/QuakeBSPAliasAssets.i"
.include "Data/QuakeBSPAliasVisibility.i"
.include "Data/QuakeBSPCollision.i"
.include "Data/QuakeBSPSkyAssets.i"
.include "Data/QuakeBSPTurbulenceAssets.i"
.include "Data/QuakeBSPSoundtrack.i"
.include "quake/RomAddressContract.i"

.ifdef PLAYABLE_SPRITE_STREAM
; The complete opaque pass retires these colormap rows before alias sampling.
SPRITE_STREAM_CACHE_OFFSET = $C000
SPRITE_STREAM_CACHE_BYTES = $0600
.endif

; Large BASIC leaf groups reuse selector-idle space after its persistent
; eight-byte packet view cache. Keep all existing small-map/demo addresses.
.ifdef QC_BASIC_GAMEPLAY
  .if BSP_BRUSH_FLY_GROUP_FRAGMENT_MAX * 20 > 94 * 16 .or BSP_BRUSH_FLY_GROUP_PROJECTED_VERTEX_MAX * 10 + $100 > 1568 * 4
BSP_BRUSH_REMAP_SCRATCH = 1
  .else
BSP_BRUSH_REMAP_SCRATCH = 0
  .endif
.else
BSP_BRUSH_REMAP_SCRATCH = 0
.endif

.ifndef BSP_COLLISION_CPU_ROM_BASE
.ifndef BSP_COLLISION_CPU_ROM_BASE
BSP_COLLISION_CPU_ROM_BASE    = $F00000
.endif
.endif
BSP_COLLISION_MAP_ROM         = BSP_COLLISION_CPU_ROM_BASE
BSP_COLLISION_DICTIONARY_ROM  = BSP_COLLISION_CPU_ROM_BASE + BSP_COLLISION_DICTIONARY_OFFSET
.assert BSP_COLLISION_PAYLOAD_BYTES <= $10000, error, "Fly collision payload exceeds one linear ROM bank"

GSU_RAM_BANK_BYTES            = $10000
GSU_BRUSH_CODE_OFFSET         = $8C00
GSU_BRUSH_CODE_CAPACITY       = $25A0
; Fly alias visibility occupies the otherwise-unused tail of the brush overlay,
; but is loaded only when fly mode is entered so ordered boot stays unchanged.
GSU_ALIAS_FLY_CODE_OFFSET     = $AA70
GSU_AUX_CODE_OFFSET           = $B1A0
GSU_AUX_CODE_CAPACITY         = $0E40
GSU_ALIAS_FLY_CODE_CAPACITY   = GSU_AUX_CODE_OFFSET - GSU_ALIAS_FLY_CODE_OFFSET
GSU_CODE_OFFSET               = $C000
GSU_CODE_CAPACITY             = $4000
; Technique 4 replaces the shared raster and its edge-mode dispatch. The
; original GSUCODE bytes remain in ROM110 for dynamic fallback.
GSU_T4_PROJECTION_CODE_OFFSET = $D9C9
GSU_T4_PROJECTION_CODE_CAPACITY = $00B7
GSU_T4_REPLAY_BOUNDS_CODE_OFFSET = $DA80
GSU_T4_REPLAY_BOUNDS_CODE_CAPACITY = $00BB
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
GSU_T4_SAMPLE_CODE_OFFSET     = $E7C7
GSU_T4_SAMPLE_CODE_CAPACITY   = $004C
GSU_T4_SAMPLE_SELECT_OFFSET   = $F68A
GSU_T4_SAMPLE_SELECT_CAPACITY = $0027
GSU_T4_SAMPLE_AUX_OFFSET      = $F8CE
GSU_T4_SAMPLE_AUX_CAPACITY    = $015A
; Technique-4 brush overlays remove mode dispatch at the same hot addresses;
; ROM123 retains the independently restorable general brush implementation.
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
.ifndef GSU_DIVIDE_Q12_RECIPROCAL_FIRST_ROM_BANK
GSU_DIVIDE_Q12_RECIPROCAL_FIRST_ROM_BANK = $26
.endif
GSU_DIVIDE_Q12_RECIPROCAL_ROM_BANKS = 4
.ifndef GSU_DIVIDE_Q12_RECIPROCAL_ROM_ADDRESS
GSU_DIVIDE_Q12_RECIPROCAL_ROM_ADDRESS = $8000
.endif
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
; Playable projection uses the vacant words between the basis and deltas.
GSU_PLAYABLE_CAMERA_Q2_X       = GSU_RENDER_STATE_OFFSET + $0E
GSU_PLAYABLE_CAMERA_Q2_Y       = GSU_PLAYABLE_CAMERA_Q2_X + 2
GSU_PLAYABLE_CAMERA_Q2_Z       = GSU_PLAYABLE_CAMERA_Q2_X + 4
; Selector-local signed ±32 products use the gap before WORLD_CAMERA_X.
GSU_PACKET_FACE_CAMERA_POSITIVE = GSU_RENDER_STATE_OFFSET + $42
GSU_PACKET_FACE_CAMERA_NEGATIVE = GSU_PACKET_FACE_CAMERA_POSITIVE + 6
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
; This formerly unused return word publishes a completely validated endpoint
; batch. It is zero outside the current qualified world replay chunk.
GSU_TEXTURE_ENDPOINT_WORLD_PROOF_OFFSET = GSU_TEXTURE_ENDPOINT_SAMPLE_RETURN_OFFSET
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
GSU_WORLD_VISIBILITY_OFFSET   = GSU_PACKET_SIDECARS_GUARD_OFFSET + 2
GSU_WORLD_VISIBILITY_CAPACITY = (BSP_WORLD_FACE_BITSET_BYTES + 1) & $FFFE
; The fixed gap between short-address state and the vertex remap holds two
; adjacent copies of Quake's immutable 128-byte displacement table.
GSU_TURBULENCE_TABLE_OFFSET  = $0200
GSU_TURBULENCE_TABLE_BYTES   = BSP_TURBULENCE_TABLE_BYTES * 2

; Runtime packet-builder scratch retained between selector passes.  The remap
; table stores one tagged local vertex ID for every full-world vertex.  The
; selected-face bitset and admission sidecars sit immediately below the packet.
GSU_VERTEX_REMAP_OFFSET       = $0300
; A level target sizes the remap for the complete source mesh. The packet
; arenas and row cache keep their existing addresses and capacities.
  .ifdef QC_BASIC_GAMEPLAY
GSU_VERTEX_REMAP_CAPACITY     = .max(BSP_WORLD_VERTEX_COUNT * 2, GSU_BRUSH_ARBITER_METADATA_OFFSET + GSU_BRUSH_ARBITER_METADATA_BYTES - GSU_VERTEX_REMAP_OFFSET)
  .else
GSU_VERTEX_REMAP_CAPACITY     = BSP_WORLD_VERTEX_COUNT * 2
  .endif
GSU_VERTEX_REMAP_GUARD_OFFSET = GSU_VERTEX_REMAP_OFFSET + GSU_VERTEX_REMAP_CAPACITY
; Persistent leaf PVS has its own cache in the unused remap/selection gap.
; Neither selector remapping nor brush/alias arenas reach beyond their guard.
GSU_BRUSH_PVS_OFFSET          = GSU_VERTEX_REMAP_GUARD_OFFSET + 2
GSU_BRUSH_PVS_BYTES           = (BSP_BRUSH_LEAF_HEAD_COUNT + 7) / 8
GSU_BRUSH_PVS_LEAF_OFFSET     = (GSU_BRUSH_PVS_OFFSET + GSU_BRUSH_PVS_BYTES + 1) & $FFFE
; Fine Q6 camera tables occupy the unused persistent PVS/admission gap.
; Keep the renderer's existing lookup instructions and all hot-code addresses.
GSU_CAMERA_SIN_OFFSET        = GSU_BRUSH_PVS_LEAF_OFFSET + 2
GSU_CAMERA_COS_OFFSET        = GSU_CAMERA_SIN_OFFSET + CAMERA_ANGLE_STEPS
; Full linear view basis and cold initializer backups share the persistent gap.
GSU_VIEW_MATRIX_OFFSET = GSU_CAMERA_COS_OFFSET + CAMERA_ANGLE_STEPS
GSU_VIEW_MATRIX_CY = GSU_VIEW_MATRIX_OFFSET + 0
GSU_VIEW_MATRIX_SY = GSU_VIEW_MATRIX_OFFSET + 2
GSU_VIEW_MATRIX_UX = GSU_VIEW_MATRIX_OFFSET + 4
GSU_VIEW_MATRIX_UY = GSU_VIEW_MATRIX_OFFSET + 6
GSU_VIEW_MATRIX_UZ = GSU_VIEW_MATRIX_OFFSET + 8
GSU_VIEW_MATRIX_DX = GSU_VIEW_MATRIX_OFFSET + 10
GSU_VIEW_MATRIX_DY = GSU_VIEW_MATRIX_OFFSET + 12
GSU_VIEW_MATRIX_DZ = GSU_VIEW_MATRIX_OFFSET + 14
GSU_VIEW_MATRIX_SAVED_R0 = GSU_VIEW_MATRIX_OFFSET + 16
GSU_VIEW_MATRIX_SAVED_R1 = GSU_VIEW_MATRIX_OFFSET + 18
GSU_VIEW_MATRIX_SAVED_R2 = GSU_VIEW_MATRIX_OFFSET + 20
GSU_VIEW_MATRIX_SAVED_R3 = GSU_VIEW_MATRIX_OFFSET + 22
GSU_VIEW_MATRIX_SAVED_R4 = GSU_VIEW_MATRIX_OFFSET + 24
GSU_VIEW_MATRIX_SAVED_R5 = GSU_VIEW_MATRIX_OFFSET + 26
GSU_VIEW_MATRIX_SAVED_R6 = GSU_VIEW_MATRIX_OFFSET + 28
GSU_VIEW_MATRIX_SAVED_R7 = GSU_VIEW_MATRIX_OFFSET + 30
GSU_VIEW_MATRIX_SAVED_R12 = GSU_VIEW_MATRIX_OFFSET + 32
GSU_VIEW_MATRIX_END = GSU_VIEW_MATRIX_OFFSET + 34
; Use the full five-byte face record arena. The sidecar guard moves
; into spare visibility storage while the texture-coordinate map stays put.
GSU_SELECTED_FACES_OFFSET     = (GSU_VIEW_MATRIX_END + 3) & $FFFC
.assert GSU_BRUSH_PVS_LEAF_OFFSET + 2 <= GSU_SELECTED_FACES_OFFSET, error, "Brush PVS overlaps selector admission"
.assert GSU_CAMERA_COS_OFFSET + CAMERA_ANGLE_STEPS <= GSU_SELECTED_FACES_OFFSET, error, "Fine camera tables overlap selector admission"
.assert GSU_VIEW_MATRIX_END <= GSU_SELECTED_FACES_OFFSET, error, "View matrix overlaps selector admission"
.assert (GSU_VIEW_MATRIX_OFFSET & 1) = 0, error, "View matrix must be word aligned"
GSU_SELECTED_FACES_CAPACITY   = .max($023E, (BSP_WORLD_FACE_BITSET_BYTES + 1) & $FFFE)
GSU_SELECTED_FACES_GUARD_OFFSET = GSU_SELECTED_FACES_OFFSET + GSU_SELECTED_FACES_CAPACITY
GSU_PACKET_SIDECARS_OFFSET    = GSU_SELECTED_FACES_GUARD_OFFSET + 2
GSU_PACKET_SIDECAR_RECORD_BYTES = 4
.ifdef E1M1_FLY_LARGE_PACKET
GSU_PACKET_FACE_CAPACITY      = 456
.elseif .defined(PLAYABLE_LARGE_VERTEX_PACKET)
GSU_PACKET_FACE_CAPACITY      = 436
.elseif BSP_START_LARGE_PACKET
GSU_PACKET_FACE_CAPACITY      = 425
.else
GSU_PACKET_FACE_CAPACITY      = 409
.endif
GSU_PACKET_SIDECARS_BYTES     = GSU_PACKET_FACE_CAPACITY * GSU_PACKET_SIDECAR_RECORD_BYTES
GSU_PACKET_SIDECARS_GUARD_OFFSET = GSU_PACKET_SIDECARS_OFFSET + GSU_PACKET_SIDECARS_BYTES
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
BSP_STATUS_HUD_HEIGHT         = 24
BSP_PLAYABLE_WORLD_HEIGHT     = BSP_PHYSICAL_HEIGHT - BSP_STATUS_HUD_HEIGHT
BSP_PLAYABLE_X2_HEIGHT        = BSP_PLAYABLE_WORLD_HEIGHT / 2
BSP_PLAYABLE_X3_HEIGHT        = (BSP_PLAYABLE_WORLD_HEIGHT + 2) / 3
BSP_PLAYABLE_X2_STAGE_BYTES   = ((BSP_PLAYABLE_X2_HEIGHT + 7) / 8) * $400
BSP_PLAYABLE_X3_STAGE_BYTES   = ((BSP_PLAYABLE_X3_HEIGHT + 7) / 8) * $400
.ifdef PLAYABLE_MAP_ID
BSP_FRAME_STAGE_BYTES         = .max(BSP_PLAYABLE_X2_STAGE_BYTES, BSP_PLAYABLE_X3_STAGE_BYTES)
.else
BSP_FRAME_STAGE_BYTES         = GSU_OUTPUT_BYTES
.endif
BSP_TEXTURE_CLEAR_BYTES       = .min(BSP_FRAME_STAGE_BYTES, GSU_TEXTURE_VISIBLE_BYTES)
BSP_TECHNIQUE_TEXTURED_LIGHTMAP   = 4
BSP_TECHNIQUE_UNTEXTURED_LIGHTMAP = 7
GSU_TEXTURE_TAIL_CODE_OFFSET  = GSU_TEXTURE_VISIBLE_BYTES
GSU_TEXTURE_TAIL_CODE_CAPACITY = GSU_TEXTURE_FRAMEBUFFER_BYTES - GSU_TEXTURE_VISIBLE_BYTES
.ifdef PLAYABLE_PAIRED_WORLD_CODE
GSU_PAIRED_WORLD_OFFSET       = $3600
.assert BSP_PLAYABLE_X2_STAGE_BYTES <= GSU_PAIRED_WORLD_OFFSET, error, "Paired world code overlaps staged tiles"
.assert GSU_PAIRED_WORLD_OFFSET + $0200 <= GSU_TEXTURE_TAIL_CODE_OFFSET, error, "Paired world code overlaps the texture tail"
.endif
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
.ifdef QUAKE_MSU_CACHE
.include "quake/MsuSurfaceCache.i"
GSU_DIVIDE_Q12_HOT_MIRROR_BYTES = MSU_SURFACE_SLOT_BASE - GSU_DIVIDE_Q12_HOT_MIRROR_OFFSET
.elseif .defined(QC_NAIL_COUNT)
; E1M1 uses the final 1.25 KiB before the turbulence kernel for all immutable
; actor poses. Displaced Q12 words retain their identical ROM fallback.
GSU_LIVE_POSE_OFFSET = $8500
GSU_DIVIDE_Q12_HOT_MIRROR_BYTES = GSU_LIVE_POSE_OFFSET - GSU_DIVIDE_Q12_HOT_MIRROR_OFFSET
.else
GSU_DIVIDE_Q12_HOT_MIRROR_BYTES = GSU_DIVIDE_Q12_HOT_MIRROR_END - GSU_DIVIDE_Q12_HOT_MIRROR_OFFSET
.endif
GSU_DIVIDE_Q12_HOT_MIRROR_ENTRIES = GSU_DIVIDE_Q12_HOT_MIRROR_BYTES / GSU_DIVIDE_Q12_RECIPROCAL_ENTRY_BYTES
; The ordinary interior brush arbiter keeps depth, texture, lightmap and
; pixel advancement in one 512-byte CACHE window. Cold support and liquid
; sampling live in hidden framebuffer scanlines. The reserved reciprocal tail
; remains excluded from lookups, which retain the exact ROM fallback.
GSU_TURBULENCE_HOT_CODE_OFFSET = $8A00
GSU_TURBULENCE_HOT_CODE_CAPACITY = $0200
.if .defined(QUAKE_MSU_CACHE) .or .defined(QC_NAIL_COUNT)
GSU_DIVIDE_Q12_HOT_MIRROR_SAFE_BYTES = GSU_DIVIDE_Q12_HOT_MIRROR_BYTES
.else
GSU_DIVIDE_Q12_HOT_MIRROR_SAFE_BYTES = GSU_TURBULENCE_HOT_CODE_OFFSET - GSU_DIVIDE_Q12_HOT_MIRROR_OFFSET
.endif
GSU_DIVIDE_Q12_HOT_MIRROR_SAFE_ENTRIES = GSU_DIVIDE_Q12_HOT_MIRROR_SAFE_BYTES / GSU_DIVIDE_Q12_RECIPROCAL_ENTRY_BYTES

; Packet vertices use four bytes: signed int8 xyz bases plus packed Q2
; residuals. Keep this cold near-clip stream above the projection cache so the
; established hot packet/index/raster layout does not move.
.ifdef E1M1_FLY_LARGE_PACKET
; Full-height Fly admits wider views than the playable viewport. Keep the
; projected packet below raster scratch and the cold vertices below live actors.
GSU_VERTICES_OFFSET           = $AAA0
GSU_VERTICES_CAPACITY         = 1088 * 4
GSU_VERTICES_GUARD_OFFSET     = GSU_VERTICES_OFFSET + GSU_VERTICES_CAPACITY
GSU_INDICES_OFFSET            = $4DC0
GSU_INDICES_CAPACITY          = 2400 * 2
GSU_INDICES_GUARD_OFFSET      = GSU_INDICES_OFFSET + GSU_INDICES_CAPACITY
GSU_FACES_OFFSET              = GSU_INDICES_GUARD_OFFSET + 2
GSU_FACES_CAPACITY            = GSU_PACKET_FACE_CAPACITY * BSP_FACE_RECORD_BYTES
GSU_PROJECTED_OFFSET          = GSU_FACES_OFFSET + GSU_FACES_CAPACITY
GSU_PROJECTED_CAPACITY        = GSU_VERTICES_CAPACITY
.elseif .defined(PLAYABLE_LARGE_VERTEX_PACKET)
; Keep vertices, indices and faces from the same selection. The E1M1
; completion camera admits 433 faces after the conservative screen retry.
GSU_VERTICES_GUARD_OFFSET     = $BBB8
GSU_VERTICES_CAPACITY         = 1000 * 4
GSU_VERTICES_OFFSET           = GSU_VERTICES_GUARD_OFFSET - GSU_VERTICES_CAPACITY
GSU_INDICES_OFFSET            = $4F00
GSU_INDICES_CAPACITY          = 2252 * 2
GSU_INDICES_GUARD_OFFSET      = GSU_INDICES_OFFSET + GSU_INDICES_CAPACITY
GSU_FACES_OFFSET              = GSU_INDICES_GUARD_OFFSET + 2
GSU_FACES_CAPACITY            = GSU_PACKET_FACE_CAPACITY * BSP_FACE_RECORD_BYTES
GSU_PROJECTED_OFFSET          = GSU_FACES_OFFSET + GSU_FACES_CAPACITY
GSU_PROJECTED_CAPACITY        = GSU_VERTICES_CAPACITY
.elseif BSP_START_LARGE_PACKET
; The X2 startup retry needs 947 vertices, 2188 indices and 425 faces.
; Move the projected base to preserve a complete 23-row lightmap chunk.
GSU_VERTICES_GUARD_OFFSET     = $BD00
GSU_VERTICES_CAPACITY         = 948 * 4
GSU_VERTICES_OFFSET           = GSU_VERTICES_GUARD_OFFSET - GSU_VERTICES_CAPACITY
GSU_PROJECTED_OFFSET          = $6A28
GSU_PROJECTED_CAPACITY        = GSU_VERTICES_CAPACITY
GSU_FACES_CAPACITY            = (GSU_PACKET_FACE_CAPACITY * BSP_FACE_RECORD_BYTES + 1) & $FFFE
GSU_FACES_OFFSET              = GSU_PROJECTED_OFFSET - GSU_FACES_CAPACITY
GSU_INDICES_GUARD_OFFSET      = GSU_FACES_OFFSET - 2
GSU_INDICES_CAPACITY          = 2188 * 2
GSU_INDICES_OFFSET            = GSU_INDICES_GUARD_OFFSET - GSU_INDICES_CAPACITY
.else
.ifdef QC_BASIC_GAMEPLAY
; E1M3 plus authored shell boxes needs 600 projected brush vertices and its
; winner row. The independent selector still has 692 packet vertices.
GSU_VERTICES_OFFSET           = $B230
GSU_VERTICES_CAPACITY         = $0AD0
.else
.ifdef QC_DOG_FIRST
GSU_VERTICES_OFFSET           = GSU_VERTICES_GUARD_OFFSET - GSU_VERTICES_CAPACITY
.else
GSU_VERTICES_OFFSET           = $AF40
.endif
GSU_VERTICES_CAPACITY         = $0DC0
.endif
.ifdef QC_DOG_FIRST
; Keep the packet extent and leave space for all actor poses after its guard.
GSU_VERTICES_GUARD_OFFSET     = $BBB8
.else
GSU_VERTICES_GUARD_OFFSET     = $BD00
.endif
GSU_INDICES_OFFSET            = $5200
GSU_INDICES_CAPACITY          = $1000
GSU_INDICES_GUARD_OFFSET      = $6200
GSU_FACES_OFFSET              = $6202
GSU_FACES_CAPACITY            = $07FE
GSU_PROJECTED_OFFSET          = $6A00
.ifdef QC_BASIC_GAMEPLAY
GSU_PROJECTED_CAPACITY        = $0AD0
.else
GSU_PROJECTED_CAPACITY        = $0DC0
.endif
.endif
; Vertex validity is only written and read by selector admission/projection.
; Mixed brush tokens occupy this tail only after selection is complete. Keep
; the packet's persistent source-face IDs before the overlaid validity bytes.
GSU_VALID_OFFSET              = GSU_SOURCE_FACE_IDS_OFFSET + GSU_SOURCE_FACE_IDS_BYTES
.if BSP_START_LARGE_PACKET .or .defined(PLAYABLE_LARGE_VERTEX_PACKET) .or .defined(E1M1_FLY_LARGE_PACKET)
GSU_VALID_CAPACITY            = GSU_VERTICES_CAPACITY / 4
.elseif .defined(QC_BASIC_GAMEPLAY)
GSU_VALID_CAPACITY            = $02B4
.else
GSU_VALID_CAPACITY            = $0370
.endif
GSU_RASTER_SCRATCH_OFFSET     = $7900
GSU_RASTER_SCRATCH_BYTES      = $0B00
; Tall world chunks resume their 28-vertex projected polygon after endpoint
; replay. Keep every live 10-byte vertex below the signed-Q4 {S,T} stream.
GSU_TEXTURE_ENDPOINT_STAGE_OFFSET = $7DC8
; Brush rows run after the world polygon is retired. Keep their existing
; candidate-depth/filter allocation independent of the world endpoint stream.
GSU_BRUSH_ROW_SCRATCH_OFFSET  = $7D50
GSU_TEXTURE_ENDPOINT_STAGE_RECORD_BYTES = 4
GSU_TEXTURE_ENDPOINT_STAGE_RECORDS = 398
GSU_TEXTURE_ENDPOINT_STAGE_BYTES = GSU_TEXTURE_ENDPOINT_STAGE_RECORDS * GSU_TEXTURE_ENDPOINT_STAGE_RECORD_BYTES
GSU_TEXTURE_ENDPOINT_STAGE_END = GSU_TEXTURE_ENDPOINT_STAGE_OFFSET + GSU_TEXTURE_ENDPOINT_STAGE_BYTES

; Dynamic brush leaves are small independent arbitration groups. Their
; projected polygons replace the now-idle world projection cache while one
; 128-pixel Q6 depth row and compact per-polygon records consume the exact
; tail of raster scratch below the trigonometry tables.
GSU_BRUSH_ARBITER_DEPTH_ROW_OFFSET = $7E80
GSU_BRUSH_ARBITER_DEPTH_ROW_BYTES = $0100
.ifdef QC_BASIC_GAMEPLAY
; Basic maps place brush metadata after the complete alias arena, including
; immutable ambient actors. The phase/end assertions below bound both users.
GSU_BRUSH_ARBITER_METADATA_OFFSET = GSU_ALIAS_VISIBILITY_MASKS_END
.else
GSU_BRUSH_ARBITER_METADATA_OFFSET = GSU_BRUSH_ARBITER_DEPTH_ROW_OFFSET + GSU_BRUSH_ARBITER_DEPTH_ROW_BYTES
.endif
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
GSU_PACKET_BIT_MASK_OFFSET = GSU_TEXTURE_EDGE_DIVIDE_CACHE_OFFSET + GSU_TEXTURE_EDGE_DIVIDE_CACHE_BYTES
GSU_PACKET_BIT_MASK_BYTES = 8 * BSP_QUAKEC_GAMEPLAY
; The selector marks only accepted-face owners and their world-root ancestors.
; This gap is in data bank $71 and remains independent of renderer scratch.
GSU_PAINTER_NODE_MASK_OFFSET  = $8640
; Clear whole words and keep the following GSU word cache even-aligned.
GSU_PAINTER_NODE_MASK_BYTES   = ((BSP_WORLD_NODE_COUNT + 15) / 16) * 2
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
.ifdef E1M1_FLY_LARGE_PACKET
GSU_LIGHTMAP_ROW_STAGE_OFFSET = GSU_BRUSH_ARBITER_WINNER_ROW_OFFSET + GSU_BRUSH_ARBITER_WINNER_ROW_BYTES
GSU_LIGHTMAP_ROW_STAGE_ROWS   = 92
.elseif BSP_BRUSH_REMAP_SCRATCH .or .defined(QC_BASIC_GAMEPLAY) .or .defined(PLAYABLE_LARGE_VERTEX_PACKET)
; Persistent VIS/sky commands follow the complete source remap. Move only
; this cache above them; tall world faces retain the exact chunked path.
GSU_LIGHTMAP_ROW_STAGE_OFFSET = .max($4C20, (WEAPON_BOB_DELTAS + 16 + 15) & $FFF0)
GSU_LIGHTMAP_ROW_STAGE_ROWS   = (GSU_INDICES_OFFSET - GSU_LIGHTMAP_ROW_STAGE_OFFSET) / 16
.else
GSU_LIGHTMAP_ROW_STAGE_OFFSET = $4C40
GSU_LIGHTMAP_ROW_STAGE_ROWS   = 92
.endif
GSU_LIGHTMAP_ROW_STAGE_BYTES  = GSU_LIGHTMAP_ROW_STAGE_ROWS * 16
; Between a world render and its successor, preserve the clean X2 pixels
; while staging the weapon composite. The selector does not use either range.
WEAPON_UNDO_ROW_BYTES = 10
.ifdef E1M1_FLY_LARGE_PACKET
WEAPON_UNDO_FIRST = WEAPON_BOB_DELTAS + 16
WEAPON_UNDO_FIRST_ROWS = (GSU_INDICES_OFFSET - WEAPON_UNDO_FIRST) / WEAPON_UNDO_ROW_BYTES
.else
WEAPON_UNDO_FIRST = GSU_LIGHTMAP_ROW_STAGE_OFFSET
WEAPON_UNDO_FIRST_ROWS = GSU_LIGHTMAP_ROW_STAGE_BYTES / WEAPON_UNDO_ROW_BYTES
.endif
WEAPON_UNDO_FIRST_LIMIT = WEAPON_UNDO_FIRST + WEAPON_UNDO_FIRST_ROWS * WEAPON_UNDO_ROW_BYTES
WEAPON_UNDO_SECOND = GSU_BRUSH_ARBITER_DEPTH_ROW_OFFSET
WEAPON_UNDO_SECOND_ROWS = (GSU_SIN_OFFSET - WEAPON_UNDO_SECOND) / WEAPON_UNDO_ROW_BYTES
WEAPON_UNDO_MAX_ROWS = WEAPON_UNDO_FIRST_ROWS + WEAPON_UNDO_SECOND_ROWS
; Tall T4 faces reuse the same arenas in bounded row chunks. A 128-pixel
; row needs at most sixteen eight-pixel intervals plus its first endpoint.
GSU_LIGHTMAP_TALL_CHUNK_ROWS  = 23
.assert GSU_LIGHTMAP_TALL_CHUNK_ROWS <= GSU_LIGHTMAP_ROW_STAGE_ROWS, error, "Tall lightmap chunk exceeds row staging"
.assert GSU_LIGHTMAP_TALL_CHUNK_ROWS * (128 / 8 + 1) <= GSU_TEXTURE_ENDPOINT_STAGE_RECORDS, error, "Tall lightmap chunk exceeds endpoint staging"
; World faces and one dynamic-brush leaf group render serially. During a brush
; row the lightmap-row arena is idle and can hold one prepared 20-byte record
; for every generated group fragment, including arbitrary fly-camera rows.
.if BSP_START_LARGE_PACKET
; Keep all persistent packet views below this scratch. START moves the
; independent material pool after the brush metadata in the remap tail.
GSU_BRUSH_ROW_STAGE_OFFSET    = GSU_VERTEX_REMAP_OFFSET + GSU_VALID_CAPACITY * 8
.elseif BSP_BRUSH_REMAP_SCRATCH
GSU_BRUSH_ROW_STAGE_OFFSET    = GSU_BRUSH_MATERIAL_POOL_LIMIT
.else
GSU_BRUSH_ROW_STAGE_OFFSET    = GSU_LIGHTMAP_ROW_STAGE_OFFSET
.endif
GSU_BRUSH_ROW_STAGE_RECORD_BYTES = 20
GSU_BRUSH_ROW_STAGE_RECORDS  = BSP_BRUSH_FLY_GROUP_FRAGMENT_MAX
GSU_BRUSH_ROW_STAGE_BYTES    = GSU_BRUSH_ROW_STAGE_RECORDS * GSU_BRUSH_ROW_STAGE_RECORD_BYTES
; Host tooling writes this one-shot block while a headless emulator is paused
; at power-on. The S-CPU consumes it after normal state initialization and
; before the first render. Cartridge RAM is required because libSFX clears
; WRAM before Main.
GSU_BOOT_PARAMETERS_OFFSET    = $87C0
GSU_BOOT_PARAMETERS_BYTES     = $0018
; After startup the rectangle is enabled by the foreground frame producer.
WEAPON_OBJ_CORE_FLAG          = GSU_BOOT_PARAMETERS_OFFSET + 20
.ifdef PLAYABLE_WEAPON_OBJ
WEAPON_OBJ_CORE_X_MIN         = 58
WEAPON_OBJ_CORE_X_END         = 69
WEAPON_OBJ_CORE_Y_MIN         = 88
WEAPON_OBJ_CORE_Y_END         = BSP_PLAYABLE_X2_HEIGHT
.endif
GSU_TEXTURE_COORD_MAP_OFFSET  = GSU_WORLD_VISIBILITY_OFFSET + GSU_WORLD_VISIBILITY_CAPACITY
GSU_TEXTURE_COORD_MAP_BYTES   = $0080
; One immutable per-job signed Q6 pickup basis in the unused map/stage gap.
GSU_ALIAS_ROTATION_OFFSET     = GSU_TEXTURE_COORD_MAP_OFFSET + GSU_TEXTURE_COORD_MAP_BYTES
.assert GSU_ALIAS_ROTATION_OFFSET + 2 <= GSU_LIGHTMAP_ROW_STAGE_OFFSET, error, "Alias rotation overlaps row staging"
; CPU selects the immutable projection/pose archive address before the GSU job.
GSU_ALIAS_ARCHIVE_ADDRESS_OFFSET = GSU_ALIAS_ROTATION_OFFSET + 2
.assert GSU_ALIAS_ARCHIVE_ADDRESS_OFFSET + 2 <= GSU_LIGHTMAP_ROW_STAGE_OFFSET, error, "Alias archive command overlaps row staging"
; Conservative logical sky-row bounds survive all opaque world/brush work.
; This bank-$71 gap is outside both alias command words and every row arena.
GSU_SKY_ROW_BOUNDS_OFFSET     = GSU_ALIAS_ARCHIVE_ADDRESS_OFFSET + 2
GSU_SKY_ROW_BOUNDS_ROWS       = 112
GSU_SKY_ROW_BOUNDS_BYTES      = 2 * GSU_SKY_ROW_BOUNDS_ROWS
GSU_SKY_MARKER_LOGICAL_Y_OFFSET = GSU_SKY_ROW_BOUNDS_OFFSET + GSU_SKY_ROW_BOUNDS_BYTES
.assert GSU_SKY_MARKER_LOGICAL_Y_OFFSET + 2 <= GSU_LIGHTMAP_ROW_STAGE_OFFSET, error, "Sky bounds overlap row staging"
; Immutable exact sky phase, separate from the stable low23 command/telemetry.
GSU_SKY_EXACT_PHASE_FORMAT_OFFSET = GSU_SKY_MARKER_LOGICAL_Y_OFFSET + 2
GSU_SKY_EXACT_PHASE_OFFSET = GSU_SKY_EXACT_PHASE_FORMAT_OFFSET + 2
GSU_SKY_EXACT_PHASE_BYTES = 6
GSU_SKY_EXACT_PHASE_BINARY32 = 0
GSU_SKY_EXACT_PHASE_Q24 = 1
GSU_SKY_EXACT_PHASE_Q16 = 2
.assert GSU_SKY_EXACT_PHASE_OFFSET + GSU_SKY_EXACT_PHASE_BYTES <= GSU_LIGHTMAP_ROW_STAGE_OFFSET, error, "Exact sky phase overlaps row staging"
; Eight signed address deltas for the X2 weapon's logical row shift.
WEAPON_BOB_DELTAS = GSU_SKY_EXACT_PHASE_OFFSET + GSU_SKY_EXACT_PHASE_BYTES
.assert WEAPON_BOB_DELTAS + 16 <= GSU_LIGHTMAP_ROW_STAGE_OFFSET, error, "Weapon bob overlaps row staging"
; The live Q2 pose belongs to the same job as the actor's frame and facing.
.if BSP_QUAKEC_GAMEPLAY
GSU_GRUNT_POSE_BYTES = 8
.ifdef QC_NAIL_COUNT
GSU_GRUNT_POSES_BYTES = 0           ; Physical actor records occupy bank $70.
GSU_PICKUP_MASK_HIGH = GSU_BACKPACK_TOKEN_COUNT+2
GSU_LIVE_POSE_ADDRESS = $700000 + GSU_LIVE_POSE_OFFSET
.assert GSU_LIVE_POSE_OFFSET + GSU_ALIAS_LIVE_COUNT*8 <= GSU_TURBULENCE_HOT_CODE_OFFSET, error, "Live projectile poses overlap turbulence code"
.else
GSU_LIVE_POSE_ADDRESS = $710000 + GSU_GRUNT_POSES_OFFSET
GSU_GRUNT_POSES_BYTES = GSU_ALIAS_LIVE_COUNT * GSU_GRUNT_POSE_BYTES + 2 * (.defined(QC_MEGA_COUNT) + .defined(QC_CAMPAIGN_ITEMS))
.ifdef QC_CAMPAIGN_ITEMS
GSU_CAMPAIGN_POSE_COUNT = GSU_GRUNT_POSES_OFFSET + GSU_ALIAS_LIVE_COUNT * GSU_GRUNT_POSE_BYTES
.endif
.ifdef QC_MEGA_COUNT
GSU_PICKUP_MASK_HIGH = GSU_GRUNT_POSES_OFFSET + GSU_ALIAS_LIVE_COUNT * GSU_GRUNT_POSE_BYTES
.endif
.endif
.ifdef QC_CAMPAIGN_ITEMS
; Keep the complete knight/projectile list outside the alias mask backup.
; Displaced reciprocal entries use their ordinary byte-identical ROM suffix.
GSU_GRUNT_POSES_OFFSET = $BD20
GSU_ENTRANCE_VARIANTS_OFFSET = GSU_PROJECTED_OFFSET + GSU_PROJECTED_CAPACITY
.elseif .defined(E1M1_FLY_LARGE_PACKET)
.ifdef QC_DOG_FIRST
GSU_GRUNT_POSES_OFFSET = $BD20 - QC_GRUNT_COUNT * 8 + 2 * .defined(QC_BACKPACK_COUNT)
; Standalone Fly does not use the two screen-bit cache words.
GSU_ENTRANCE_VARIANTS_OFFSET = GSU_PACKET_SCREEN_BIT_PTR
.assert .defined(PLAYABLE_PACKET_SCREEN_REUSE_CODE) = 0, error, "Fly mover variants occupy the screen-bit words"
.assert .defined(PLAYABLE_PACKET_SCREEN_REUSE) = 0, error, "Fly mover variants occupy the screen-bit words"
.else
GSU_GRUNT_POSES_OFFSET = $BC00
GSU_ENTRANCE_VARIANTS_OFFSET = GSU_PACKET_SCREEN_BIT_MASK + 2
.endif
.assert GSU_VERTICES_GUARD_OFFSET + 2 <= GSU_GRUNT_POSES_OFFSET, error, "Fly actors overlap packet vertices"
.assert GSU_GRUNT_POSES_OFFSET + GSU_GRUNT_POSES_BYTES <= GSU_RECIPROCAL_OFFSET, error, "Fly actors overlap reciprocals"
.assert WEAPON_BOB_DELTAS + 16 <= WEAPON_UNDO_FIRST, error, "Weapon bob overlaps undo rows"
.elseif .defined(QC_DOG_FIRST)
GSU_GRUNT_POSES_OFFSET = $BD20 - QC_GRUNT_COUNT * 8 + 2 * .defined(QC_BACKPACK_COUNT)
GSU_ENTRANCE_VARIANTS_OFFSET = GSU_PROJECTED_OFFSET + GSU_PROJECTED_CAPACITY
.assert GSU_PACKET_SCREEN_BIT_MASK + 2 <= GSU_GRUNT_POSES_OFFSET, error, "Actor poses overlap packet caches"
.elseif .defined(PLAYABLE_LARGE_VERTEX_PACKET)
; Reserve the unused tail of the mixed-token arena for persistent actor poses.
; Selector validity and mixed tokens both end before this allocation.
GSU_GRUNT_POSES_OFFSET = GSU_FACE_PLANES_OFFSET - GSU_GRUNT_POSES_BYTES
GSU_ENTRANCE_VARIANTS_OFFSET = GSU_PROJECTED_OFFSET + GSU_PROJECTED_CAPACITY
.else
GSU_GRUNT_POSES_OFFSET = GSU_PROJECTED_OFFSET + GSU_PROJECTED_CAPACITY
GSU_ENTRANCE_VARIANTS_OFFSET = GSU_GRUNT_POSES_OFFSET + GSU_GRUNT_POSES_BYTES
.assert GSU_ENTRANCE_VARIANTS_OFFSET <= GSU_RASTER_SCRATCH_OFFSET, error, "Grunt poses overlap raster scratch"
.endif
GSU_GRUNT_ORIGIN_OFFSET = GSU_GRUNT_POSES_OFFSET + 2
.if QC_ENTRANCE_COUNT > 0 .or .defined(QC_EXIT_MOVER_COUNT)
; Variant words stay immutable for the current render command.
.ifdef QC_EXIT_MOVER_COUNT
.ifdef QC_E1M1_PLATFORM_FIRST
GSU_PLATFORM_HEIGHTS = GSU_ENTRANCE_VARIANTS_OFFSET + ((QC_EXIT_VARIANT_SLOTS+1) & $FFFE)
GSU_ENTRANCE_VARIANTS_BYTES = GSU_PLATFORM_HEIGHTS + 2 - GSU_ENTRANCE_VARIANTS_OFFSET
.else
GSU_ENTRANCE_VARIANTS_BYTES = (QC_EXIT_VARIANT_SLOTS+1) & $FFFE
.endif
.else
GSU_ENTRANCE_VARIANTS_BYTES = 4
.endif
  .ifdef E1M1_FLY_LARGE_PACKET
.assert GSU_ENTRANCE_VARIANTS_OFFSET + GSU_ENTRANCE_VARIANTS_BYTES <= GSU_GRUNT_POSES_OFFSET, error, "Entrance variants overlap Fly actors"
  .else
.assert GSU_ENTRANCE_VARIANTS_OFFSET + GSU_ENTRANCE_VARIANTS_BYTES <= GSU_RASTER_SCRATCH_OFFSET, error, "Entrance variants overlap raster scratch"
  .endif
.endif
.endif
GSU_TEXTURE_COLORMAP_OFFSET   = $C000
GSU_LIGHTMAP_COLORMAP_BYTES   = $4000
.ifdef PLAYABLE_TEXTURELESS_WHITE
; Lightmaps Only needs one value per row. Mixed painters can refill sprite
; pixels midway through the frame, so keep these rows above their cache.
GSU_TEXTURELESS_ROWS_BYTES    = 64
GSU_TEXTURELESS_ROWS_OFFSET   = GSU_TEXTURE_COLORMAP_OFFSET + GSU_LIGHTMAP_COLORMAP_BYTES - GSU_TEXTURELESS_ROWS_BYTES
GSU_TEXTURELESS_MAPPER_BASE   = GSU_TEXTURELESS_ROWS_OFFSET - $C0
.ifdef PLAYABLE_SPRITE_STREAM
.assert SPRITE_STREAM_CACHE_OFFSET + SPRITE_STREAM_CACHE_BYTES <= GSU_TEXTURELESS_ROWS_OFFSET, error, "Sprite stream overlaps textureless rows"
.endif
.endif
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
.if BSP_QUAKEC_GAMEPLAY
  .ifdef QC_HEALTH_COUNT
    .ifdef QC_NAIL_COUNT
.assert BSP_EXTERNAL_BSP_FLY_STATIC_COUNT = QC_SHELL_COUNT + QC_HEALTH_COUNT + QC_NAIL_COUNT + .defined(QC_EXPLOBOX), error, "Nail, shell and health masks do not cover the external brush links"
    .else
.assert BSP_EXTERNAL_BSP_FLY_STATIC_COUNT = QC_SHELL_COUNT + QC_HEALTH_COUNT, error, "Pickup masks and external brush links disagree"
    .endif
  .else
.assert BSP_EXTERNAL_BSP_FLY_STATIC_COUNT = QC_SHELL_COUNT, error, "Shell mask and external brush links disagree"
  .endif
.assert BSP_EXTERNAL_BSP_FLY_STATIC_COUNT <= (16 + 16 * .defined(QC_MEGA_COUNT)), error, "Gameplay external brush links exceed the pickup mask"
.elseif BSP_EXTERNAL_BSP_SUPPORTED
.assert BSP_EXTERNAL_BSP_ACTIVE_ROW_BYTES = 3, error, "External BSP active rows no longer fit the 24-bit fly mask"
.endif
BSP_SKY_FLAG_ENABLED          = $01
BSP_SKY_FLAG_PRESENTED        = $02
.include "quake/fly_full/Config.i"
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
; In E1M1 each visible actor, brush link and leaf delimiter needs its own
; token, even in the largest fully populated fly frame.
.ifdef QC_NAIL_COUNT
GSU_FACE_PLANES_OFFSET = GSU_SOURCE_FACE_IDS_OFFSET + 2*(GSU_PACKET_FACE_CAPACITY+BSP_BRUSH_FLY_LINK_MAX+BSP_BRUSH_FLY_LEAF_MARKER_MAX+GSU_ALIAS_LIVE_COUNT)
.elseif .defined(E1M1_FLY_LARGE_PACKET)
GSU_FACE_PLANES_OFFSET        = $90F8
.else
GSU_FACE_PLANES_OFFSET        = $91B0
.endif
.if .defined(PLAYABLE_LARGE_VERTEX_PACKET) && (.defined(QC_DOG_FIRST) = 0)
GSU_BRUSH_MIXED_TOKENS_END    = GSU_GRUNT_POSES_OFFSET
.else
GSU_BRUSH_MIXED_TOKENS_END    = GSU_FACE_PLANES_OFFSET
.endif
GSU_BRUSH_MIXED_TOKEN_CAPACITY = (GSU_BRUSH_MIXED_TOKENS_END - GSU_BRUSH_MIXED_TOKENS_OFFSET) / 2
.ifdef QC_NAIL_COUNT
GSU_FACE_PLANES_GUARD_OFFSET = .max($99A8, (GSU_FACE_PLANES_OFFSET+GSU_PACKET_FACE_CAPACITY*BSP_FACE_PLANE_RECORD_BYTES+5) & $FFFC) - 2
GSU_FACE_PLANES_CAPACITY = GSU_FACE_PLANES_GUARD_OFFSET+2-GSU_FACE_PLANES_OFFSET
GSU_BRUSH_MATERIAL_POOL_BYTES = $03FE
.elseif .defined(E1M1_FLY_LARGE_PACKET)
GSU_FACE_PLANES_GUARD_OFFSET  = $99E6
GSU_FACE_PLANES_CAPACITY      = GSU_FACE_PLANES_GUARD_OFFSET + 2 - GSU_FACE_PLANES_OFFSET
GSU_BRUSH_MATERIAL_POOL_BYTES = $03FE
.elseif BSP_START_LARGE_PACKET
GSU_FACE_PLANES_CAPACITY      = ((GSU_PACKET_FACE_CAPACITY * BSP_FACE_PLANE_RECORD_BYTES + 1) & $FFFE) + 2
GSU_FACE_PLANES_GUARD_OFFSET  = GSU_FACE_PLANES_OFFSET + GSU_FACE_PLANES_CAPACITY - 2
GSU_BRUSH_MATERIAL_POOL_BYTES = $03FE
.else
GSU_FACE_PLANES_CAPACITY      = $99A8 - GSU_FACE_PLANES_OFFSET
GSU_FACE_PLANES_GUARD_OFFSET  = $99A6
; Material references stay relative to this unchanged 1,022-byte pool.
GSU_BRUSH_MATERIAL_POOL_BYTES = $03FE
.endif
.if BSP_START_LARGE_PACKET
GSU_BRUSH_MATERIAL_POOL_OFFSET = (GSU_BRUSH_ARBITER_METADATA_OFFSET + GSU_BRUSH_ARBITER_METADATA_BYTES + 1) & $FFFE
.elseif BSP_BRUSH_REMAP_SCRATCH
GSU_BRUSH_MATERIAL_POOL_OFFSET = GSU_VERTEX_REMAP_OFFSET + GSU_VALID_CAPACITY * 8
.else
GSU_BRUSH_MATERIAL_POOL_OFFSET = GSU_FACE_PLANES_GUARD_OFFSET - GSU_BRUSH_MATERIAL_POOL_BYTES
.endif
GSU_BRUSH_MATERIAL_POOL_LIMIT = GSU_BRUSH_MATERIAL_POOL_OFFSET + GSU_BRUSH_MATERIAL_POOL_BYTES
; Later unique projections use selector scratch until admission.
.if BSP_START_LARGE_PACKET .or .defined(PLAYABLE_LARGE_VERTEX_PACKET) .or .defined(E1M1_FLY_LARGE_PACKET) .or .defined(QC_DOG_FIRST)
GSU_PROJECTION_CACHE_OFFSET   = GSU_FACE_PLANES_OFFSET + GSU_FACE_PLANES_CAPACITY
GSU_PROJECTION_CACHE_ENTRIES  = (GSU_VERTICES_OFFSET - 8 - GSU_PROJECTION_CACHE_OFFSET) / 4
.else
GSU_PROJECTION_CACHE_OFFSET   = $99A8
.ifdef QC_BASIC_GAMEPLAY
GSU_PROJECTION_CACHE_ENTRIES  = 1568
.else
GSU_PROJECTION_CACHE_ENTRIES  = 1380
.endif
.endif
GSU_PROJECTION_CACHE_RECORD_BYTES = 4
GSU_PROJECTION_CACHE_BYTES    = GSU_PROJECTION_CACHE_ENTRIES * GSU_PROJECTION_CACHE_RECORD_BYTES
.if BSP_START_LARGE_PACKET .or .defined(PLAYABLE_LARGE_VERTEX_PACKET) .or .defined(E1M1_FLY_LARGE_PACKET) .or .defined(QC_DOG_FIRST)
GSU_PROJECTION_CACHE_GUARD_OFFSET = GSU_VERTICES_OFFSET - 8
.elseif .defined(QC_BASIC_GAMEPLAY)
GSU_PROJECTION_CACHE_GUARD_OFFSET = $B228
.else
GSU_PROJECTION_CACHE_GUARD_OFFSET = $AF38
.endif
.if BSP_START_LARGE_PACKET
; START has eight brush slots. DynamicBrushMerge checks the end of the
; persistent alias state against this start of the retired face-plane arena.
GSU_BRUSH_ARBITER_SCREEN_OFFSET = GSU_FACE_PLANES_OFFSET + $01D0
.elseif BSP_BRUSH_REMAP_SCRATCH
; The relocated material pool retires this old slot before brush rendering.
GSU_BRUSH_ARBITER_SCREEN_OFFSET = GSU_FACE_PLANES_OFFSET + $03F8
.else
GSU_BRUSH_ARBITER_SCREEN_OFFSET = GSU_PROJECTION_CACHE_OFFSET
.endif
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
BSP_BRUSH_TEN_BIT_LINKS = .defined(QC_BASIC_GAMEPLAY) .or .defined(QC_NAIL_COUNT)
GSU_BRUSH_LINK_RECORD_BYTES   = 4
.if BSP_BRUSH_TEN_BIT_LINKS
GSU_BRUSH_LINK_CAPACITY       = BSP_BRUSH_FLY_LINK_MAX
.elseif .defined(QC_ARMOR_COUNT)
; Each extra sorted model needs four sort bytes and a two-byte visibility
; pointer. Keep the original head/link layout and its map-derived lower bound.
GSU_BRUSH_LINK_CAPACITY       = 511 - (QC_ARMOR_COUNT * 6 + 3) / 4
.assert GSU_BRUSH_LINK_CAPACITY >= BSP_BRUSH_FLY_LINK_MAX, error, "E1M1 brush link budget"
.else
GSU_BRUSH_LINK_CAPACITY       = 511
.endif
GSU_BRUSH_LINKS_END           = GSU_BRUSH_LINKS_OFFSET + GSU_BRUSH_LINK_CAPACITY * GSU_BRUSH_LINK_RECORD_BYTES
; MDL billboard visibility is already reduced to at most one compact group per
; origin leaf. These tables share the selector-idle remap tail with brush links.
GSU_ALIAS_GROUPS_OFFSET       = GSU_BRUSH_LINKS_END
; A live 30 Hz inspection snapshot can contain more actors than the initial
; fly row. Reserve the complete seven-bit token domain, independent of the
; smaller maxima observed in the packaged demo-camera rows.
.if BSP_ALIAS_LIVE_POSES
GSU_ALIAS_MAX_STATES          = GSU_ALIAS_LIVE_COUNT
GSU_ALIAS_MAX_GROUPS          = 1 ; The shared atlas retains one format-only row group.
.elseif BSP_QUAKEC_GAMEPLAY
GSU_ALIAS_MAX_STATES          = BSP_ALIAS_MAX_VISIBLE_STATES
GSU_ALIAS_MAX_GROUPS          = BSP_ALIAS_MAX_GROUPS
.else
GSU_ALIAS_MAX_STATES          = 1
GSU_ALIAS_MAX_GROUPS          = 1
.endif
GSU_ALIAS_GROUP_RECORD_BYTES = 6
.ifdef QC_BACKPACK_COUNT
GSU_ALIAS_GROUPS_BYTES        = 0 ; Live E1M1 sort records have their own table.
.elseif BSP_ALIAS_LIVE_POSES
GSU_ALIAS_GROUPS_BYTES        = GSU_ALIAS_MAX_STATES * 4 ; Sort only; no leaf groups.
.elseif GSU_ALIAS_MAX_STATES * 4 > GSU_ALIAS_MAX_GROUPS * GSU_ALIAS_GROUP_RECORD_BYTES
; Sparse leaf groups can be smaller than the later complete depth-sort view.
GSU_ALIAS_GROUPS_BYTES        = GSU_ALIAS_MAX_STATES * 4
.else
GSU_ALIAS_GROUPS_BYTES        = GSU_ALIAS_MAX_GROUPS * GSU_ALIAS_GROUP_RECORD_BYTES
.endif
GSU_ALIAS_GROUPS_END          = GSU_ALIAS_GROUPS_OFFSET + GSU_ALIAS_GROUPS_BYTES
; Once painter traversal has consumed the leaf groups, reuse their arena for
; one exact-depth record per flattened token. The sorted original ordinals are
; then written into the already-reserved mixed-token alias suffix, so QAV2
; pointers and masks stay keyed by canonical QBA1 token ordinal.
.ifdef QC_NAIL_COUNT
GSU_ALIAS_RENDER_SORT_OFFSET = GSU_BACKPACK_TOKEN_COUNT + 4 + 2 * GSU_ALIAS_MAX_STATES
.elseif .defined(QC_BACKPACK_COUNT)
GSU_ALIAS_RENDER_SORT_OFFSET  = GSU_GRUNT_POSES_OFFSET + GSU_GRUNT_POSES_BYTES
.else
GSU_ALIAS_RENDER_SORT_OFFSET  = GSU_ALIAS_GROUPS_OFFSET
.endif
GSU_ALIAS_RENDER_SORT_RECORD_BYTES = 4
GSU_ALIAS_RENDER_SORT_BYTES   = GSU_ALIAS_MAX_STATES * GSU_ALIAS_RENDER_SORT_RECORD_BYTES
GSU_ALIAS_RENDER_SORT_END     = GSU_ALIAS_RENDER_SORT_OFFSET + GSU_ALIAS_RENDER_SORT_BYTES
GSU_ALIAS_TOKENS_OFFSET       = GSU_ALIAS_GROUPS_END
.if BSP_ALIAS_LIVE_POSES
GSU_ALIAS_TOKENS_BYTES        = 0 ; A live-grunt ordinal indexes the pose directly.
.else
GSU_ALIAS_TOKENS_BYTES        = GSU_ALIAS_MAX_STATES
.endif
GSU_ALIAS_TOKENS_END          = GSU_ALIAS_TOKENS_OFFSET + GSU_ALIAS_TOKENS_BYTES
; Ordered alias depth masks must survive every opaque world/brush raster. The
; selector-idle remap tail is persistent for that complete phase, unlike the
; polygon scratch. A pointer sentinel selects the zero-cost visible path or a
; projection-level hidden reject; only partial tokens point at staged masks.
; Super FX word stores use the adjacent even byte for the high half of an
; odd address. Pad an odd token capacity before writing pointer sentinels.
.ifdef QC_NAIL_COUNT
GSU_ALIAS_VISIBILITY_POINTERS_OFFSET = GSU_BACKPACK_TOKEN_COUNT + 4
.else
GSU_ALIAS_VISIBILITY_POINTERS_OFFSET = (GSU_ALIAS_TOKENS_END + 1) & $FFFE
.endif
GSU_ALIAS_VISIBILITY_POINTERS_BYTES = GSU_ALIAS_MAX_STATES * 2
GSU_ALIAS_VISIBILITY_POINTERS_END = GSU_ALIAS_VISIBILITY_POINTERS_OFFSET + GSU_ALIAS_VISIBILITY_POINTERS_BYTES
GSU_ALIAS_VISIBILITY_MASKS_OFFSET = GSU_ALIAS_VISIBILITY_POINTERS_END
GSU_ALIAS_VISIBILITY_MASKS_BYTES = BSP_ALIAS_ARCHIVE_MAX_DECODED_BYTES
GSU_ALIAS_VISIBILITY_MASKS_END = GSU_ALIAS_VISIBILITY_MASKS_OFFSET + GSU_ALIAS_VISIBILITY_MASKS_BYTES
; Quarter-depth lookup for Q6 projection: 1,024 unsigned Q12 words. The
; natural lightmap colormap begins at $C000 and phase-overlays the far suffix.
; Mixed X2 gameplay can retain its packet-local Q6 view records until
; the next selector rebuilds the remap head or the scale image changes.
GSU_PACKET_VIEW_CACHE_VALID_OFFSET = GSU_VERTICES_GUARD_OFFSET + 2
; A nonzero count publishes the linked brushes and mixed tokens for the packet.
GSU_BRUSH_MERGE_CACHE_COUNT    = GSU_PACKET_VIEW_CACHE_VALID_OFFSET + 2
GSU_BRUSH_MERGE_CACHE_VISUAL   = GSU_BRUSH_MERGE_CACHE_COUNT + 2
GSU_BRUSH_MERGE_CACHE_FLAGS    = GSU_BRUSH_MERGE_CACHE_VISUAL + 2
GSU_BRUSH_MERGE_CACHE_ACTIVE   = GSU_BRUSH_MERGE_CACHE_FLAGS + 2
GSU_BRUSH_MERGE_CACHE_RETURN   = GSU_BRUSH_MERGE_CACHE_ACTIVE + 2
GSU_PACKET_SCREEN_READY       = GSU_BRUSH_MERGE_CACHE_RETURN + 2
GSU_PACKET_SCREEN_RETURN      = GSU_PACKET_SCREEN_READY + 2
GSU_PACKET_SCREEN_BIT_PTR     = GSU_PACKET_SCREEN_RETURN + 2
GSU_PACKET_SCREEN_BIT_MASK    = GSU_PACKET_SCREEN_BIT_PTR + 2
.ifdef QC_BACKPACK_COUNT
; Extend the immutable pose table into the RAM prefix of the reciprocal
; cache. Fetch the displaced reciprocal words from their identical ROM table.
GSU_RECIPROCAL_OFFSET         = GSU_ALIAS_RENDER_SORT_END
.ifdef QC_NAIL_COUNT
GSU_BACKPACK_TOKEN_COUNT = GSU_GRUNT_POSES_OFFSET - 2
.else
GSU_BACKPACK_TOKEN_COUNT      = $BD20 - QC_GRUNT_COUNT * 8
.endif
.elseif .defined(QC_CAMPAIGN_ITEMS)
GSU_RECIPROCAL_OFFSET = GSU_GRUNT_POSES_OFFSET + GSU_GRUNT_POSES_BYTES
.assert GSU_RECIPROCAL_OFFSET <= GSU_TEXTURE_COLORMAP_OFFSET-2, error, "Campaign poses exceed the reciprocal prefix"
.elseif .defined(QC_ARMOR_COUNT)
; Dedicate eight former reciprocal words to the two persistent armor poses.
; The displaced divisors use the existing exact ROM suffix.
GSU_RECIPROCAL_OFFSET         = $BD20 + QC_ARMOR_COUNT * GSU_GRUNT_POSE_BYTES
.else
GSU_RECIPROCAL_OFFSET         = $BD20
.endif
.assert GSU_PACKET_SCREEN_BIT_MASK + 2 <= GSU_RECIPROCAL_OFFSET, error, "Packet caches overlap reciprocal table"
.ifdef PLAYABLE_RESIDENT_WORLD
GSU_RESIDENT_WORLD_STATUS  = GSU_PACKET_SCREEN_BIT_MASK + 2
GSU_RESIDENT_WORLD_COMMAND = GSU_RESIDENT_WORLD_STATUS + 2
GSU_RESIDENT_WORLD_MASK    = GSU_RESIDENT_WORLD_COMMAND + 2
.ifdef PLAYABLE_RESIDENT_WORLD_SNAPSHOT
; The normal mixed-renderer command advances from 1 to 2. A stopped
; snapshot borrows that word and the CPU returns it to 2 before resuming.
RESIDENT_WORLD_SAVE = 3
RESIDENT_WORLD_RESTORE = 4
.endif
.assert GSU_RESIDENT_WORLD_STATUS = $BD16, error, "Resident world state moved"
.ifdef GSU_ENTRANCE_VARIANTS_BYTES
.assert GSU_ENTRANCE_VARIANTS_OFFSET + GSU_ENTRANCE_VARIANTS_BYTES <= GSU_RESIDENT_WORLD_STATUS, error, "Resident world overlaps entrance variants"
.endif
.assert GSU_RESIDENT_WORLD_MASK + 2 <= GSU_RECIPROCAL_OFFSET, error, "Resident world overlaps reciprocal table"
.endif
.ifdef PLAYABLE_PACKET_SCREEN_REUSE_CODE
; Reuse the selector-only remap bytes between the view cache and leaf heads.
; Keep exact screen X/Y in four bytes per packet vertex and a ready bit per
; source face, since one source face owns one unclipped contour in the packet.
.assert !BSP_BRUSH_REMAP_SCRATCH, error, "Packet screen cache would overlap relocated brush scratch"
GSU_PACKET_SCREEN_COORDS      = GSU_VERTEX_REMAP_OFFSET + GSU_VALID_CAPACITY * 8
GSU_PACKET_SCREEN_FACE_BITS   = GSU_PACKET_SCREEN_COORDS + GSU_VALID_CAPACITY * 4
GSU_PACKET_SCREEN_FACE_BITS_BYTES = (BSP_WORLD_FACE_BITSET_BYTES + 1) & $FFFE
.assert GSU_PACKET_SCREEN_FACE_BITS + GSU_PACKET_SCREEN_FACE_BITS_BYTES <= GSU_BRUSH_LEAF_HEADS_OFFSET, error, "Packet screen cache overlaps live brush heads"
.endif
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
.if BSP_START_LARGE_PACKET
.assert BSP_BRUSH_REMAP_SCRATCH, error, "START packet requires remap scratch"
.assert GSU_PACKET_FACE_CAPACITY * BSP_FACE_PLANE_RECORD_BYTES <= GSU_FACE_PLANES_GUARD_OFFSET - GSU_FACE_PLANES_OFFSET, error, "START face planes overlap guard"
.ifdef PLAYABLE_SPRITE_STREAM
.error "START packet brush screen requires resident alias sprites"
.endif
.endif
.assert GSU_PACKET_FACE_CAPACITY * BSP_FACE_RECORD_BYTES <= GSU_FACES_CAPACITY, error, "Runtime face packet exceeds cartridge RAM"
; Fly always selects packets from the full World streams; its legacy spawn
; preview is an offline diagnostic and is never staged into these arenas.
.assert GSU_VALID_CAPACITY * 4 = GSU_VERTICES_CAPACITY, error, "Runtime vertex packet and validity capacities differ"
.assert GSU_VALID_CAPACITY * 4 = GSU_PROJECTED_CAPACITY, error, "Runtime projected and validity capacities differ"
.ifdef E1M1_FLY_LARGE_PACKET
; Bank $70 holds the sky code. The live bank $71 painter stack and polygon
; scratch start at the sky code's upper bound.
.assert GSU_PROJECTED_OFFSET + GSU_PROJECTED_CAPACITY <= GSU_SKY_COMPOSITOR_SCRATCH_OFFSET, error, "Fly projected packet overlaps painter scratch"
.else
.assert GSU_PROJECTED_OFFSET + GSU_PROJECTED_CAPACITY <= GSU_RASTER_SCRATCH_OFFSET, error, "Projected packet overlaps raster scratch"
.endif
.assert GSU_VERTEX_REMAP_OFFSET + BSP_WORLD_VERTEX_COUNT * 2 <= GSU_VALID_OFFSET, error, "World vertex remap overlaps validity"
.assert GSU_VALID_OFFSET + GSU_VALID_CAPACITY <= GSU_BRUSH_MIXED_TOKENS_END, error, "Fly selector validity escapes retired brush-token space"
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
.ifdef QUAKE_MSU_CACHE
.assert BSP_DEMO_PLAYBACK_SUPPORTED && !BSP_QUAKEC_GAMEPLAY, error, "MSU cache requires the E1M3 demo layout"
.assert MSU_SURFACE_TAG_BASE >= GSU_PROJECTED_OFFSET + GSU_PROJECTED_CAPACITY, error, "MSU tags overlap projected vertices"
.assert MSU_SURFACE_READY + 2 <= MSU_SURFACE_INDEX, error, "MSU tags overlap cache index"
.assert MSU_SURFACE_INDEX + $100 <= GSU_RASTER_SCRATCH_OFFSET, error, "MSU index overlaps raster scratch"
.assert MSU_SURFACE_SLOT_BASE + MSU_SURFACE_SLOT_BYTES * MSU_SURFACE_SLOT_COUNT = MSU_SURFACE_LOOKUP_OFFSET, error, "MSU pages overlap GSU lookup code"
.elseif .defined(QC_NAIL_COUNT)
.assert GSU_DIVIDE_Q12_HOT_MIRROR_BYTES = $4500, error, "E1M1 actor area must follow the retained Q12 prefix"
.else
.assert GSU_DIVIDE_Q12_HOT_MIRROR_BYTES = $4C00, error, "Q12 hot mirror no longer fills the phase-overlay gap"
.endif
.ifndef QUAKE_MSU_CACHE
.assert GSU_DIVIDE_Q12_HOT_MIRROR_ENTRIES = $1300 - $1c0 * .defined(QC_NAIL_COUNT), error, "Q12 hot mirror entry count changed"
.endif
.assert GSU_DIVIDE_Q12_HOT_MIRROR_BYTES <= $8000, error, "Q12 hot mirror copy crosses its source ROM bank"
.assert GSU_RASTER_SCRATCH_OFFSET + GSU_RASTER_SCRATCH_BYTES <= GSU_SIN_OFFSET, error, "Raster scratch overlaps tables"
.assert GSU_TEXTURE_ENDPOINT_STAGE_END = GSU_SIN_OFFSET, error, "Endpoint staging must fill the retired scratch arena without crossing sine data"
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
.assert (GSU_TEXTURE_EDGE_DIVIDE_CACHE_OFFSET & 1) = 0, error, "Edge divide cache requires even GSU word addresses"
.assert GSU_PAINTER_NODE_MASK_OFFSET + GSU_PAINTER_NODE_MASK_BYTES <= GSU_TEXTURE_EDGE_DIVIDE_CACHE_OFFSET, error, "Painter-node mask overlaps edge divide cache"
.assert GSU_PACKET_BIT_MASK_OFFSET + GSU_PACKET_BIT_MASK_BYTES <= GSU_BOOT_PARAMETERS_OFFSET, error, "Edge divide cache or packet mask table overlaps boot parameters"
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
.ifdef QUAKE_MSU_CACHE
.assert GSU_DIVIDE_Q12_HOT_MIRROR_SAFE_ENTRIES = (MSU_SURFACE_SLOT_BASE - $4000) / 4, error, "MSU Q12 mirror prefix changed"
.elseif .defined(QC_NAIL_COUNT)
.assert GSU_DIVIDE_Q12_HOT_MIRROR_SAFE_ENTRIES = $1140, error, "Nail poses overlap hot Q12 entries"
.else
.assert GSU_DIVIDE_Q12_HOT_MIRROR_SAFE_ENTRIES = $1280, error, "Safe Q12 mirror prefix changed"
.endif
.assert GSU_SKY_COMPOSITOR_SCRATCH_OFFSET = GSU_RASTER_SCRATCH_OFFSET + $0180, error, "Sky compositor scratch no longer begins at the texture polygon arena"
.assert GSU_SKY_COMPOSITOR_SCRATCH_OFFSET + GSU_SKY_COMPOSITOR_SCRATCH_BYTES = GSU_SIN_OFFSET, error, "Sky compositor scratch no longer ends at the trigonometry tables"
.assert GSU_TELEMETRY_OFFSET + GSU_TELEMETRY_BYTES = GSU_SOURCE_FACE_IDS_OFFSET, error, "BSP telemetry overlaps source-face sidecar"
.assert GSU_SOURCE_FACE_IDS_OFFSET + GSU_SOURCE_FACE_IDS_BYTES <= GSU_BRUSH_MIXED_TOKENS_END, error, "Source-face sidecar exceeds mixed-token arena"
.if BSP_BRUSH_DYNAMIC_REPLAY_SUPPORTED
.assert GSU_BRUSH_MIXED_TOKEN_CAPACITY >= 1028, error, "Brush mixed-token capacity regressed"
.assert GSU_BRUSH_MIXED_TOKEN_CAPACITY >= GSU_PACKET_FACE_CAPACITY + BSP_BRUSH_FLY_LINK_MAX + BSP_BRUSH_FLY_LEAF_MARKER_MAX, error, "Brush mixed tokens cannot hold the proven fly snapshot and leaf markers"
.assert GSU_BRUSH_MIXED_TOKEN_CAPACITY >= GSU_PACKET_FACE_CAPACITY + BSP_BRUSH_FLY_LINK_MAX + BSP_BRUSH_FLY_LEAF_MARKER_MAX + GSU_ALIAS_MAX_STATES, error, "Mixed tokens cannot hold the proven brush and alias maxima"
.assert GSU_ALIAS_MAX_STATES >= BSP_ALIAS_MAX_VISIBLE_STATES, error, "Alias states exceed live capacity"
.assert GSU_ALIAS_MAX_GROUPS >= BSP_ALIAS_MAX_GROUPS, error, "Alias groups exceed live capacity"
.endif
.assert GSU_BRUSH_LEAF_HEADS_OFFSET >= GSU_VERTEX_REMAP_OFFSET + BSP_WORLD_FACE_COUNT * 2, error, "Brush leaf heads overlap the face lookup"
.assert BSP_BRUSH_LEAF_HEAD_COUNT = BSP_WORLD_VIS_LEAF_COUNT + 1, error, "Brush leaf heads must cover the world VIS domain"
.assert BSP_BRUSH_FRAGMENT_BUCKET_LEAF_MAX < BSP_BRUSH_LEAF_HEAD_COUNT, error, "Brush fragment bucket escapes leaf heads"
.assert BSP_BRUSH_SOLID_FALLBACK_LEAF = 0, error, "Brush solid fallback leaf moved"
.assert GSU_BRUSH_LEAF_HEADS_END <= GSU_VERTEX_REMAP_GUARD_OFFSET, error, "Brush leaf heads escape the phase-separated remap tail"
.if BSP_BRUSH_DYNAMIC_REPLAY_SUPPORTED
.assert GSU_BRUSH_LINK_CAPACITY >= BSP_BRUSH_FLY_LINK_MAX, error, "Brush links cannot hold the proven fly snapshot"
.endif
.if BSP_BRUSH_TEN_BIT_LINKS
.assert GSU_BRUSH_LINK_CAPACITY <= 1023, error, "Basic brush links exceed packed ten-bit indices"
.else
.assert GSU_BRUSH_LINK_CAPACITY <= 511, error, "Brush links exceed packed nine-bit indices"
.endif
.assert GSU_BRUSH_LINKS_END <= GSU_VERTEX_REMAP_GUARD_OFFSET, error, "Brush links escape the phase-separated remap tail"
.assert GSU_ALIAS_GROUPS_END <= GSU_VERTEX_REMAP_GUARD_OFFSET, error, "Alias groups escape the phase-separated remap tail"
.ifdef QC_BACKPACK_COUNT
.assert GSU_ALIAS_RENDER_SORT_END <= GSU_TEXTURE_COLORMAP_OFFSET-2, error, "Backpack pose and sort tables consume the entire RAM reciprocal prefix"
.else
.assert GSU_ALIAS_RENDER_SORT_END <= GSU_ALIAS_GROUPS_END, error, "Alias render sort exceeds the retired group arena"
.endif
.assert GSU_ALIAS_TOKENS_END <= GSU_VERTEX_REMAP_GUARD_OFFSET, error, "Alias tokens escape the phase-separated remap tail"
.ifdef QC_NAIL_COUNT
.assert BSP_ALIAS_ARCHIVE_MAX_DECODED_BYTES = 0, error, "Live pose cache requires runtime occlusion"
.assert GSU_ALIAS_VISIBILITY_MASKS_END <= GSU_ALIAS_RENDER_SORT_OFFSET, error, "Projectile visibility overlaps depth sorting"
.else
.assert GSU_ALIAS_VISIBILITY_MASKS_END <= GSU_VERTEX_REMAP_GUARD_OFFSET, error, "Level brush/alias scratch escapes remap tail"
.endif
.assert GSU_FACE_PLANES_OFFSET + GSU_FACE_PLANES_CAPACITY = GSU_PROJECTION_CACHE_OFFSET, error, "Projection cache moved away from face planes"
.assert GSU_FACE_PLANES_GUARD_OFFSET + 2 <= GSU_FACE_PLANES_OFFSET + GSU_FACE_PLANES_CAPACITY, error, "Face-plane guard escapes its packet"
.ifdef E1M1_FLY_LARGE_PACKET
.assert GSU_PACKET_FACE_CAPACITY * BSP_FACE_PLANE_RECORD_BYTES <= GSU_FACE_PLANES_GUARD_OFFSET - GSU_FACE_PLANES_OFFSET, error, "Fly face planes overlap guard"
.endif
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
.ifdef E1M1_FLY_LARGE_PACKET
.assert GSU_LIGHTMAP_ROW_STAGE_OFFSET + GSU_LIGHTMAP_ROW_STAGE_BYTES <= GSU_PROJECTION_CACHE_GUARD_OFFSET, error, "Fly row stage exceeds retired projection cache"
.else
.assert GSU_LIGHTMAP_ROW_STAGE_OFFSET + GSU_LIGHTMAP_ROW_STAGE_BYTES <= GSU_INDICES_OFFSET, error, "Lightmap row stage overlaps packet indices"
.endif
.if BSP_BRUSH_DYNAMIC_REPLAY_SUPPORTED
.ifdef QC_BASIC_GAMEPLAY
.assert GSU_ALIAS_MAX_STATES <= 128, error, "Basic alias states exceed packed seven-bit indices"
.assert GSU_BRUSH_ARBITER_METADATA_OFFSET >= GSU_ALIAS_VISIBILITY_MASKS_END, error, "Basic brush metadata overlaps aliases"
.assert GSU_BRUSH_ARBITER_METADATA_OFFSET + GSU_BRUSH_ARBITER_METADATA_BYTES <= GSU_VERTEX_REMAP_GUARD_OFFSET, error, "Basic brush metadata escapes the remap tail"
.else
.assert GSU_BRUSH_ROW_STAGE_RECORDS <= 72, error, "Brush row stage exceeds its proven capacity"
.endif
.if BSP_BRUSH_REMAP_SCRATCH
.assert GSU_BRUSH_MATERIAL_POOL_OFFSET >= GSU_VERTEX_REMAP_OFFSET + GSU_VALID_CAPACITY * 8, error, "Brush material pool overlaps persistent packet views"
.if BSP_START_LARGE_PACKET
.assert GSU_BRUSH_ROW_STAGE_OFFSET >= GSU_VERTEX_REMAP_OFFSET + GSU_VALID_CAPACITY * 8, error, "START brush rows overlap packet views"
.assert GSU_BRUSH_ROW_STAGE_OFFSET + GSU_BRUSH_ROW_STAGE_BYTES <= GSU_BRUSH_MATERIAL_POOL_OFFSET, error, "START brush rows overlap material pool"
.assert GSU_BRUSH_MATERIAL_POOL_OFFSET >= GSU_BRUSH_ARBITER_METADATA_OFFSET + GSU_BRUSH_ARBITER_METADATA_BYTES, error, "START material pool overlaps brush metadata"
.assert GSU_BRUSH_MATERIAL_POOL_LIMIT <= GSU_VERTEX_REMAP_GUARD_OFFSET, error, "START material pool escapes remap tail"
.else
.assert GSU_BRUSH_MATERIAL_POOL_LIMIT <= GSU_BRUSH_ROW_STAGE_OFFSET, error, "Brush row stage overlaps material pool"
.endif
.assert GSU_BRUSH_ROW_STAGE_OFFSET + GSU_BRUSH_ROW_STAGE_BYTES <= GSU_BRUSH_LEAF_HEADS_OFFSET, error, "Brush row stage overlaps persistent leaf heads"
.else
.assert GSU_BRUSH_ROW_STAGE_OFFSET + GSU_BRUSH_ROW_STAGE_BYTES <= GSU_LIGHTMAP_ROW_STAGE_OFFSET + GSU_LIGHTMAP_ROW_STAGE_BYTES, error, "Brush row stage exceeds the idle lightmap-row arena"
.endif
.endif


.endif
