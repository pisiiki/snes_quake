; Super FX 3 map module for the playable cartridge.
.include "libSFX.i"
.include "SNES_FX3.i"
.include "MemoryMap.i"
.import T4TextureEndpointLoadRow, TextureEndpointLoadRowCall, TextureEndpointLoadRow
.import T4PrepareEndpointDepth, BrushArbiterDepthMathCall, T4TextureEndpointDepthBatch
.import WeaponCullCoveredFace, WorldLightmapRasterCall, WorldLightmapRasterTarget
.export CAMERA_ANGLE_STEPS
.export GSU_CAMERA_SIN_OFFSET, GSU_CAMERA_COS_OFFSET
.ifdef QUAKE_MSU_WORLD_KEEP
.export MSU_WORLD_KEEP_MASK, MSU_WORLD_KEEP_READY, MSU_WORLD_KEEP_COUNT, MSU_WORLD_KEEP_ORDINAL
.endif
.include "quake/SoundJoin.i"
.include "quake/CameraCollision.i"
.include "quake/GameplayInput.i"
.if .defined(PLAYABLE_WEAPON_OBJ) && .defined(QC_QUEUED_INPUT) && .defined(QC_E1M2_GROUP_COUNT) && (!.defined(QC_E1M3_GOLD_KEY))
QC_E1M2_DEFER_UPLOAD = 1
E1M2_DEFER_ACTIVE = 1
E1M2_DEFER_LATCH = 2
.endif
; Resolve CPU mirrors at link time for either fixed renderer's ROM image.
.ifdef PLAYABLE_MAP_ID
; Playable linker addresses already name actual CPU data or virtual MSU images.
.define BSP_CPU_CODE_ADDRESS(address) ((address) + (((^(address) >= $60) .and (^(address) < $70)) * $800000))
.else
.define BSP_CPU_CODE_ADDRESS(address) ((address) + (((^(address) >= $C0) .and (^(address) < $F0)) * BSP_SOUND_CPU_MIRROR_DELTA))
.endif
; External BSP pickups remain renderable when a map has no alias roster.
.ifdef PLAYABLE_MAP_ID
BSP_RENDER_ENTITIES_SUPPORTED = BSP_ALIAS_ENTITY_SUPPORTED | BSP_EXTERNAL_BSP_SUPPORTED
.else
BSP_RENDER_ENTITIES_SUPPORTED = BSP_ALIAS_ENTITY_SUPPORTED
.endif
GSU_RENDER_BASE    = $700000
GSU_DATA_BASE      = $710000
GSU_OUTPUT         = GSU_RENDER_BASE + GSU_OUTPUT_OFFSET
GSU_VERTICES       = GSU_DATA_BASE + GSU_VERTICES_OFFSET
GSU_INDICES        = GSU_DATA_BASE + GSU_INDICES_OFFSET
GSU_FACES          = GSU_DATA_BASE + GSU_FACES_OFFSET
GSU_FACE_PLANES    = GSU_DATA_BASE + GSU_FACE_PLANES_OFFSET
GSU_SIN             = GSU_DATA_BASE + GSU_CAMERA_SIN_OFFSET
GSU_COS             = GSU_DATA_BASE + GSU_CAMERA_COS_OFFSET
GSU_RECIPROCAL      = GSU_DATA_BASE + GSU_RECIPROCAL_OFFSET
GSU_EXPAND_NIBBLE   = GSU_RENDER_BASE + GSU_EXPAND_NIBBLE_OFFSET
GSU_TEXTURE_COORD_MAP = GSU_DATA_BASE + GSU_TEXTURE_COORD_MAP_OFFSET
GSU_TEXTURE_COLORMAP = GSU_DATA_BASE + GSU_TEXTURE_COLORMAP_OFFSET
GSU_TEXTURE_EDGE_DIVIDE_CACHE = GSU_DATA_BASE + GSU_TEXTURE_EDGE_DIVIDE_CACHE_OFFSET
.export GSU_TEXTURE_EDGE_DIVIDE_CACHE
GSU_DIVIDE_Q12_HOT_MIRROR = GSU_RENDER_BASE + GSU_DIVIDE_Q12_HOT_MIRROR_OFFSET
GSU_COMMAND         = GSU_DATA_BASE + GSU_COMMAND_OFFSET
GSU_TELEMETRY       = GSU_DATA_BASE + GSU_TELEMETRY_OFFSET
GSU_WORLD_VISIBILITY = GSU_DATA_BASE + GSU_WORLD_VISIBILITY_OFFSET
GSU_TURBULENCE_TABLE = GSU_DATA_BASE + GSU_TURBULENCE_TABLE_OFFSET
GSU_BOOT_PARAMETERS = GSU_DATA_BASE + GSU_BOOT_PARAMETERS_OFFSET
VRAM_TILES_A        = $0000
VRAM_TILES_B        = $8000
VRAM_TILEMAP        = $F800
VRAM_FLY3_TILEMAP   = VRAM_TILEMAP
VRAM_TEXTURE_TILES_A = $0000
VRAM_TEXTURE_TILES_B = $4000
VRAM_TEXTURE_TILEMAP = $F000
VRAM_RUNTIME_MENU_TILES = $7800
VRAM_RUNTIME_MENU_OBJ_BASE = $4000
RUNTIME_MENU_ASCII_FIRST = 32
RUNTIME_MENU_ASCII_LAST = 90
RUNTIME_MENU_TILE_BASE = $1C0
RUNTIME_MENU_FONT_TILE_COUNT = RUNTIME_MENU_ASCII_LAST - RUNTIME_MENU_ASCII_FIRST + 1
RUNTIME_MENU_FONT_BYTES = RUNTIME_MENU_FONT_TILE_COUNT * 32
VRAM_RUNTIME_MENU_HIGHLIGHT = $7400
RUNTIME_MENU_HIGHLIGHT_TILE_BASE = $1A0
.ifdef PLAYABLE_MAP_ID
.assert VRAM_TEXTURE_TILES_B + BSP_FRAME_STAGE_BYTES <= VRAM_RUNTIME_MENU_HIGHLIGHT, error, "Frame upload overlaps menu highlight font"
.assert VRAM_RUNTIME_MENU_HIGHLIGHT = VRAM_RUNTIME_MENU_TILES + (RUNTIME_MENU_HIGHLIGHT_TILE_BASE - RUNTIME_MENU_TILE_BASE) * 32, error, "Menu highlight tile address disagrees with VRAM placement"
.endif
; Base and flash palettes include the shared menu/HUD colors.
BSP_TEXTURE_PALETTE_UPLOAD_BYTES = 512
CAMERA_COMMAND_WORDS = 8
CAMERA_COMMAND_BYTES = CAMERA_COMMAND_WORDS * 2
BSP_UPLOAD_FORMAT_FLAT = 0
BSP_UPLOAD_FORMAT_TEXTURE = 1
BSP_UPLOAD_FORMAT_TEXTURE_X3 = 2
BSP_STAGING_FLAT_LIMIT = 49
BSP_STAGING_TEXTURE_LIMIT = 132
BSP_WORLD_ROM_BANK_BYTES = $8000
BSP_BRUSH_ROWSTATE_CPU_ADDRESS = (BSP_BRUSH_ROWSTATE_BANK + $80) * $10000 + BSP_BRUSH_ROWSTATE_ADDRESS
BSP_BRUSH_FLYSTATE_CPU_ADDRESS = (BSP_BRUSH_FLYSTATE_BANK + $80) * $10000 + BSP_BRUSH_FLYSTATE_ADDRESS
.assert __GSUCODE_SIZE__ <= GSU_CODE_CAPACITY, lderror, "GSU BSP code exceeds bank-$70 partition"
.assert .loword(__GSUCODE_RUN__) = GSU_CODE_OFFSET, lderror, "GSU BSP code address disagrees with MemoryMap.i"
.assert __GSU_T4_PROJECTION_CODE_SIZE__ <= GSU_T4_PROJECTION_CODE_CAPACITY, lderror, "Technique-4 projector exceeds its resident cache prefix"
.assert .loword(__GSU_T4_PROJECTION_CODE_RUN__) = GSU_T4_PROJECTION_CODE_OFFSET, lderror, "Technique-4 projector moved away from its T2 overlay"
.assert __GSU_T4_REPLAY_BOUNDS_CODE_SIZE__ <= GSU_T4_REPLAY_BOUNDS_CODE_CAPACITY, lderror, "Replay helpers exceed retired T2 raster"
.assert .loword(__GSU_T4_REPLAY_BOUNDS_CODE_RUN__) = GSU_T4_REPLAY_BOUNDS_CODE_OFFSET, lderror, "Replay helpers moved"
.assert __GSU_T4_REPLAY_BOUNDS_LOAD_PATCH_SIZE__ = 68, lderror, "Replay producer changed original loader extent"
.assert __GSU_T4_REPLAY_BOUNDS_MATH_CODE_SIZE__ = 74, lderror, "Replay cached depth changed size"
.assert __GSU_T4_RASTER_CODE_SIZE__ <= GSU_T4_RASTER_CODE_CAPACITY, lderror, "Technique-4 raster overlay exceeds its general-code window"
.assert .loword(__GSU_T4_RASTER_CODE_RUN__) = GSU_T4_RASTER_CODE_OFFSET, lderror, "Technique-4 raster overlay moved away from the general raster"
.assert __GSU_T4_EDGE_PATCH_SIZE__ <= GSU_T4_EDGE_PATCH_CAPACITY, lderror, "Technique-4 edge patch exceeds the general mode-dispatch window"
.assert .loword(__GSU_T4_EDGE_PATCH_RUN__) = GSU_T4_EDGE_PATCH_OFFSET, lderror, "Technique-4 edge patch moved away from the general mode dispatch"
.assert __GSU_T4_EDGE_DEPTH_CODE_SIZE__ <= GSU_T4_EDGE_DEPTH_CAPACITY, lderror, "Technique-4 edge depth output exceeds its general window"
.assert .loword(__GSU_T4_EDGE_DEPTH_CODE_RUN__) = GSU_T4_EDGE_DEPTH_OFFSET, lderror, "Technique-4 edge depth output moved away from its general window"
.assert __GSU_T4_STAGE_CODE_SIZE__ <= GSU_T4_STAGE_CODE_CAPACITY, lderror, "Technique-4 stage helper exceeds the general row-writer window"
.assert .loword(__GSU_T4_STAGE_CODE_RUN__) = GSU_T4_STAGE_CODE_OFFSET, lderror, "Technique-4 stage helper moved away from the general row writer"
.assert __GSU_T4_EDGE_OUTPUT_CODE_SIZE__ <= GSU_T4_EDGE_OUTPUT_CAPACITY, lderror, "Technique-4 edge outputs exceed the general attribute window"
.assert .loword(__GSU_T4_EDGE_OUTPUT_CODE_RUN__) = GSU_T4_EDGE_OUTPUT_OFFSET, lderror, "Technique-4 edge outputs moved away from the general attribute window"
.assert __GSU_T4_FACE_DISPATCH_PATCH_SIZE__ <= GSU_T4_FACE_DISPATCH_CAPACITY, lderror, "Technique-4 face dispatch exceeds the general dispatch window"
.assert .loword(__GSU_T4_FACE_DISPATCH_PATCH_RUN__) = GSU_T4_FACE_DISPATCH_OFFSET, lderror, "Technique-4 face dispatch moved away from the general dispatch"
.assert __GSU_T4_BLOCK_SELECT_CODE_SIZE__ <= GSU_T4_BLOCK_SELECT_CAPACITY, lderror, "Technique-4 block selector exceeds the general route window"
.assert .loword(__GSU_T4_BLOCK_SELECT_CODE_RUN__) = GSU_T4_BLOCK_SELECT_OFFSET, lderror, "Technique-4 block selector moved away from the general route window"
.assert __GSU_T4_SAMPLE_WRAP_CODE_SIZE__ <= GSU_T4_SAMPLE_WRAP_CAPACITY, lderror, "Technique-4 wrap sampler exceeds the general coordinate-wrap window"
.assert .loword(__GSU_T4_SAMPLE_WRAP_CODE_RUN__) = GSU_T4_SAMPLE_WRAP_OFFSET, lderror, "Technique-4 wrap sampler moved away from the general coordinate-wrap window"
.assert __GSU_T4_SAMPLE_CODE_SIZE__ <= GSU_T4_SAMPLE_CODE_CAPACITY, lderror, "Technique-4 sampler exceeds the general power-of-two sampler window"
.assert .loword(__GSU_T4_SAMPLE_CODE_RUN__) = GSU_T4_SAMPLE_CODE_OFFSET, lderror, "Technique-4 sampler moved away from the general sampler"
.assert __GSU_T4_SAMPLE_SELECT_PATCH_SIZE__ <= GSU_T4_SAMPLE_SELECT_CAPACITY, lderror, "Technique-4 sample selector patch exceeds the general selector suffix"
.assert .loword(__GSU_T4_SAMPLE_SELECT_PATCH_RUN__) = GSU_T4_SAMPLE_SELECT_OFFSET, lderror, "Technique-4 sample selector patch moved away from the general selector suffix"
.assert __GSU_T4_SAMPLE_AUX_CODE_SIZE__ <= GSU_T4_SAMPLE_AUX_CAPACITY, lderror, "Technique-4 sampler auxiliaries exceed the projective-albedo span window"
.assert .loword(__GSU_T4_SAMPLE_AUX_CODE_RUN__) = GSU_T4_SAMPLE_AUX_OFFSET, lderror, "Technique-4 sampler auxiliaries moved away from the projective-albedo span window"
.assert __GSU_T4_BRUSH_FRAGMENT_PATCH_SIZE__ <= GSU_T4_BRUSH_FRAGMENT_CAPACITY, lderror, "Technique-4 brush fragment patch exceeds its window"
.assert __GSU_T4_BRUSH_WORLD_PATCH_SIZE__ <= GSU_T4_BRUSH_WORLD_CAPACITY, lderror, "Technique-4 brush world patch exceeds its window"
.assert __GSU_T4_BRUSH_SAMPLE_PATCH_SIZE__ <= GSU_T4_BRUSH_SAMPLE_CAPACITY, lderror, "Technique-4 brush sample patch exceeds its window"
.assert __GSU_T4_BRUSH_RASTER_PATCH_SIZE__ <= GSU_T4_BRUSH_RASTER_CAPACITY, lderror, "Technique-4 brush raster patch exceeds its window"
.assert __GSU_T4_BRUSH_MODE_PATCH_SIZE__ <= GSU_T4_BRUSH_MODE_CAPACITY, lderror, "Technique-4 brush mode patch exceeds its window"
.assert __GSU_T4_BRUSH_PREP_PATCH_SIZE__ <= GSU_T4_BRUSH_PREP_CAPACITY, lderror, "Technique-4 brush preparation patch exceeds its window"
.assert __GSU_T4_BRUSH_ROW_PATCH_SIZE__ <= GSU_T4_BRUSH_ROW_CAPACITY, lderror, "Technique-4 brush row patch exceeds its window"
.assert __GSU_T4_BRUSH_MATERIAL_PATCH_SIZE__ <= GSU_T4_BRUSH_MATERIAL_CAPACITY, lderror, "Technique-4 brush material patch exceeds its window"
.assert __GSU_T4_BRUSH_FORWARD_PATCH_SIZE__ <= GSU_T4_BRUSH_FORWARD_CAPACITY, lderror, "Technique-4 brush forward-edge patch exceeds its window"
.assert __GSU_T4_BRUSH_REVERSE_PATCH_SIZE__ <= GSU_T4_BRUSH_REVERSE_CAPACITY, lderror, "Technique-4 brush reverse-edge patch exceeds its window"
.assert __GSU_T4_BRUSH_SPAN_PATCH_SIZE__ <= GSU_T4_BRUSH_SPAN_CAPACITY, lderror, "Technique-4 brush span patch exceeds its window"
.assert __GSU_T4_BRUSH_BLOCK_PATCH_SIZE__ <= GSU_T4_BRUSH_BLOCK_CAPACITY, lderror, "Technique-4 brush block patch exceeds its window"
.assert __GSU_T4_BRUSH_FINAL_PATCH_SIZE__ <= GSU_T4_BRUSH_FINAL_CAPACITY, lderror, "Technique-4 brush final-coordinate patch exceeds its window"
.assert __GSU_T4_BRUSH_FALLBACK_PATCH_SIZE__ <= GSU_T4_BRUSH_FALLBACK_CAPACITY, lderror, "Technique-4 brush fallback patch exceeds its window"
.assert __GSU_AUX_CODE_SIZE__ <= GSU_AUX_CODE_CAPACITY, lderror, "Auxiliary GSU code exceeds bank-$70 partition"
.assert .loword(__GSU_AUX_CODE_RUN__) = GSU_AUX_CODE_OFFSET, lderror, "Auxiliary GSU code address disagrees with MemoryMap.i"
.assert __GSU_AUX_CODE_LOAD__ = BSP_ROM_LOAD_GSU_AUX_CODE, lderror, "Auxiliary GSU code moved out of ROM2"
.assert __GSU_BRUSH_CODE_SIZE__ <= GSU_BRUSH_CODE_CAPACITY, lderror, "Dynamic-brush GSU overlay exceeds bank-$70 partition"
.assert .loword(__GSU_BRUSH_CODE_RUN__) = GSU_BRUSH_CODE_OFFSET, lderror, "Dynamic-brush GSU overlay address disagrees with MemoryMap.i"
.assert __GSU_BRUSH_CODE_LOAD__ = BSP_ROM_LOAD_GSU_BRUSH_CODE, lderror, "Dynamic-brush GSU overlay moved out of ROM123"
.assert __GSU_BRUSH_CODE_RUN__ + __GSU_BRUSH_CODE_SIZE__ <= __GSU_ALIAS_FLY_CODE_RUN__, lderror, "Dynamic-brush overlay overlaps deferred fly alias code"
.assert __GSU_ALIAS_FLY_CODE_SIZE__ <= GSU_ALIAS_FLY_CODE_CAPACITY, lderror, "Fly alias GSU overlay exceeds the brush-code tail"
.assert .loword(__GSU_ALIAS_FLY_CODE_RUN__) = GSU_ALIAS_FLY_CODE_OFFSET, lderror, "Fly alias GSU overlay moved away from the brush-code tail"
.ifndef BSP_ROM_LOAD_BANK_GSU_ALIAS_FLY_CODE
BSP_ROM_LOAD_BANK_GSU_ALIAS_FLY_CODE = $FD
.endif
.assert ^__GSU_ALIAS_FLY_CODE_LOAD__ = BSP_ROM_LOAD_BANK_GSU_ALIAS_FLY_CODE, lderror, "Fly alias GSU overlay moved out of ROM123"
.assert __GSU_TEXTURE_TAIL_CODE_SIZE__ <= GSU_TEXTURE_TAIL_CODE_CAPACITY, lderror, "Texture-tail GSU helper exceeds hidden scanlines"
.assert .loword(__GSU_TEXTURE_TAIL_CODE_RUN__) = GSU_TEXTURE_TAIL_CODE_OFFSET, lderror, "Texture-tail GSU helper address disagrees with MemoryMap.i"
.ifndef BSP_ROM_LOAD_BANK_GSU_TEXTURE_TAIL_CODE
BSP_ROM_LOAD_BANK_GSU_TEXTURE_TAIL_CODE = $FD
.endif
.assert ^__GSU_TEXTURE_TAIL_CODE_LOAD__ = BSP_ROM_LOAD_BANK_GSU_TEXTURE_TAIL_CODE, lderror, "Texture-tail GSU helper moved out of ROM123"
.ifdef PLAYABLE_PAIRED_WORLD_CODE
.assert __GSU_PAIRED_WORLD_CODE_RUN__ = GSU_RENDER_BASE + GSU_PAIRED_WORLD_OFFSET, lderror, "Paired world run address changed"
.assert __GSU_PAIRED_WORLD_CODE_SIZE__ <= $0200, lderror, "Paired world code exceeds its run area"
.endif
.assert __GSU_TURBULENCE_HOT_CODE_SIZE__ <= GSU_TURBULENCE_HOT_CODE_CAPACITY, lderror, "Turbulence sampler exceeds the reciprocal-mirror tail"
.assert .loword(__GSU_TURBULENCE_HOT_CODE_RUN__) = GSU_TURBULENCE_HOT_CODE_OFFSET, lderror, "Turbulence sampler address disagrees with MemoryMap.i"
.assert ^__GSU_TURBULENCE_HOT_CODE_LOAD__ = BSP_ROM_LOAD_BANK_GSU_TURBULENCE_HOT_CODE, lderror, "Turbulence sampler moved out of ROM2"
.assert ^__GSU_LIGHTMAP_UNPACK_ROM_CODE_LOAD__ = $80+BSP_LIGHTMAP_UNPACK_ROM_BANK, lderror, "Six-bit lightmap unpacker moved out of ROM36"
.ifdef PLAYABLE_RESIDENT_NIBBLE_LIGHTMAPS
.assert __GSU_LIGHTMAP_UNPACK_ROM_CODE_SIZE__ <= 640, lderror, "Packed lightmap code exceeds its ROM allocation"
.else
.assert __GSU_LIGHTMAP_UNPACK_ROM_CODE_SIZE__ <= 512, lderror, "Six-bit lightmap unpacker exceeds one GSU cache window"
.endif
.assert VRAM_TILES_A + GSU_OUTPUT_BYTES <= VRAM_TILES_B, error, "BSP VRAM page A overlaps page B"
.assert VRAM_TILES_B + GSU_OUTPUT_BYTES <= VRAM_TILEMAP, error, "BSP VRAM page B overlaps tilemap"
.assert VRAM_TILEMAP + $0800 <= $10000, error, "BSP tilemap exceeds VRAM"
.assert VRAM_TEXTURE_TILES_A + GSU_TEXTURE_VISIBLE_BYTES <= VRAM_TEXTURE_TILES_B, error, "8bpp texture page A overlaps page B"
.assert VRAM_TEXTURE_TILES_B + GSU_TEXTURE_VISIBLE_BYTES <= VRAM_TEXTURE_TILEMAP, error, "8bpp texture page B overlaps tilemap"
.assert VRAM_TEXTURE_TILEMAP + $0800 <= VRAM_TILEMAP, error, "8bpp and flat tilemaps overlap"
.assert VRAM_TILES_A + GSU_OUTPUT_BYTES <= VRAM_RUNTIME_MENU_TILES, error, "Flat page A overlaps runtime-menu glyphs"
.assert VRAM_TEXTURE_TILES_B + GSU_TEXTURE_VISIBLE_BYTES <= VRAM_RUNTIME_MENU_TILES, error, "Texture page B overlaps runtime-menu glyphs"
.assert VRAM_RUNTIME_MENU_TILES + RUNTIME_MENU_FONT_BYTES <= VRAM_TILES_B, error, "Runtime-menu glyphs exceed shared free VRAM"
.assert RUNTIME_MENU_TILE_BASE = $100 + ((VRAM_RUNTIME_MENU_TILES - (VRAM_RUNTIME_MENU_OBJ_BASE + $2000)) / 32), error, "Runtime-menu OBJ tile index disagrees with VRAM placement"
.assert BSP_WORLD_VERTEX_COUNT * BSP_WORLD_VERTEX_RECORD_BYTES <= BSP_WORLD_ROM_BANK_BYTES, error, "Full-map vertices exceed one ROM bank"
.assert BSP_WORLD_INDEX_COUNT * BSP_WORLD_INDEX_RECORD_BYTES <= BSP_WORLD_ROM_BANK_BYTES * 2, error, "Full-map indices exceed two ROM banks"
.assert BSP_WORLD_INDICES_0_BYTES + BSP_WORLD_INDICES_1_BYTES = BSP_WORLD_INDEX_COUNT * BSP_WORLD_INDEX_RECORD_BYTES, error, "Full-map index chunks disagree with generated counts"
.assert BSP_WORLD_FACE_COUNT * BSP_WORLD_FACE_RECORD_BYTES <= BSP_WORLD_ROM_BANK_BYTES, error, "Full-map faces exceed one ROM bank"
.assert BSP_WORLD_FACE_COUNT * BSP_WORLD_FACE_PLANE_RECORD_BYTES <= BSP_WORLD_ROM_BANK_BYTES, error, "Full-map face planes exceed one ROM bank"
.assert BSP_WORLD_NODE_COUNT * BSP_WORLD_NODE_RECORD_BYTES <= BSP_WORLD_ROM_BANK_BYTES, error, "Full-map nodes exceed one ROM bank"
.ifdef PLAYABLE_FACE_OWNER_BIAS
BSP_PHYSICAL_FACE_OWNER_BYTES = BSP_WORLD_FACE_COUNT + PLAYABLE_FACE_OWNER_HEADER
.else
BSP_PHYSICAL_FACE_OWNER_BYTES = BSP_WORLD_FACE_COUNT * BSP_WORLD_FACE_OWNER_RECORD_BYTES
.endif
.assert BSP_PHYSICAL_FACE_OWNER_BYTES <= BSP_WORLD_ROM_BANK_BYTES, error, "Full-map face owners exceed one ROM bank"
.assert BSP_WORLD_NODE_COUNT * BSP_WORLD_NODE_PARENT_RECORD_BYTES <= BSP_WORLD_ROM_BANK_BYTES, error, "Full-map node parents exceed one ROM bank"
.assert BSP_WORLD_SHADING_BYTES = BSP_WORLD_FACE_COUNT * BSP_WORLD_SHADING_RECORD_BYTES + BSP_WORLD_SHADING_DISTANCE_LUT_BYTES + BSP_WORLD_SHADING_TABLE_BYTES, error, "Full-map shading counts disagree"
.assert BSP_WORLD_SHADING_BYTES <= BSP_WORLD_ROM_BANK_BYTES, error, "Full-map shading exceeds one ROM bank"
.assert BSP_WORLD_TEXTURE_COORD_BYTES = BSP_WORLD_INDEX_COUNT * BSP_WORLD_TEXTURE_COORD_RECORD_BYTES, error, "Exact texture coordinates disagree with world indices"
.assert BSP_WORLD_TEXTURE_COORD_0_BYTES <= BSP_WORLD_ROM_BANK_BYTES, error, "Texture-coordinate bank 0 exceeds its ROM bank"
.assert BSP_WORLD_TEXTURE_COORD_1_BYTES <= BSP_WORLD_ROM_BANK_BYTES, error, "Texture-coordinate bank 1 exceeds its ROM bank"
.assert BSP_WORLD_TEXTURE_COORD_2_BYTES <= BSP_WORLD_ROM_BANK_BYTES, error, "Level UV bank 2 overflow"
.assert BSP_WORLD_TEXTURE_COORD_3_BYTES <= BSP_WORLD_ROM_BANK_BYTES, error, "Level UV bank 3 overflow"
.assert BSP_WORLD_FACE_TEXTURE_ID_BYTES = BSP_WORLD_FACE_COUNT, error, "Face texture IDs lost world-face identity"
.assert BSP_WORLD_TEXTURE_DIRECTORY_BYTES = BSP_WORLD_TEXTURE_COUNT * BSP_WORLD_TEXTURE_DIRECTORY_RECORD_BYTES, error, "Exact texture directory count disagrees"
.assert BSP_WORLD_TEXTURE_PIXEL_CHUNK_COUNT = 12, error, "Fly texture bank layout changed"
.assert BSP_WORLD_LIGHTMAP_DIRECTORY_BYTES = BSP_WORLD_FACE_COUNT * BSP_WORLD_LIGHTMAP_DIRECTORY_RECORD_BYTES, error, "Lightmap directory lost world-face identity"
.assert BSP_WORLD_LIGHTMAP_DIRECTORY_BYTES <= 2*BSP_WORLD_ROM_BANK_BYTES, error, "Fly lightmap directory exceeds one GSU bank"
.assert BSP_WORLD_LIGHTMAP_CHUNK_COUNT <= 5, error, "World lightmaps exceed their ROM bank reservation"
.assert BSP_WORLD_PLANE_COUNT * BSP_WORLD_PLANE_RECORD_BYTES <= BSP_WORLD_ROM_BANK_BYTES, error, "Full-map planes exceed one ROM bank"
.assert BSP_WORLD_LEAF_COUNT * BSP_WORLD_LEAF_RECORD_BYTES <= BSP_WORLD_ROM_BANK_BYTES, error, "Full-map leaves exceed one ROM bank"
.assert BSP_WORLD_MARKSURFACE_COUNT * BSP_WORLD_MARKSURFACE_RECORD_BYTES <= BSP_WORLD_ROM_BANK_BYTES, error, "Full-map marksurfaces exceed one ROM bank"
.assert BSP_WORLD_VISIBILITY_BYTES <= BSP_WORLD_ROM_BANK_BYTES * 2, error, "Full-map visibility exceeds two ROM banks"
.assert BSP_WORLD_VISIBILITY_0_BYTES + BSP_WORLD_VISIBILITY_1_BYTES = BSP_WORLD_VISIBILITY_BYTES, error, "Full-map visibility chunks disagree with generated byte count"
.assert BSP_WORLD_PVS_DIRECTORY_BYTES = (BSP_WORLD_VIS_LEAF_COUNT + 1) * BSP_WORLD_PVS_DIRECTORY_RECORD_BYTES, error, "Full-map face-PVS directory disagrees with generated leaf count"
.assert BSP_WORLD_PVS_DIRECTORY_BYTES <= BSP_WORLD_ROM_BANK_BYTES, error, "Full-map face-PVS directory exceeds one ROM bank"
.assert BSP_WORLD_PVS_GUARD_RECORD_COUNT > 0, error, "Full-map face-PVS guard table must not be empty"
.assert BSP_WORLD_PVS_GUARD_BYTES = BSP_WORLD_PVS_GUARD_RECORD_COUNT * BSP_WORLD_PVS_GUARD_RECORD_BYTES, error, "Full-map face-PVS guard records disagree"
.assert BSP_WORLD_PVS_DIRECTORY_BYTES + BSP_WORLD_PVS_GUARD_BYTES <= BSP_WORLD_ROM_BANK_BYTES, error, "Full-map face-PVS directory and guards exceed one ROM bank"
.assert BSP_WORLD_PVS_CHUNK_COUNT <= 5, error, "Fly face-PVS data exceeds its ROM reservation"
.assert BSP_COLLISION_MIN_X = BSP_WORLD_COORD_MIN_X, error, "Fly collision X minimum disagrees with the camera clamp"
.assert BSP_COLLISION_MIN_Y = BSP_WORLD_COORD_MIN_Y, error, "Fly collision Y minimum disagrees with the camera clamp"
.assert BSP_COLLISION_MIN_Z = BSP_WORLD_COORD_MIN_Z, error, "Fly collision Z minimum disagrees with the camera clamp"
.assert BSP_COLLISION_MAX_X = BSP_WORLD_COORD_MAX_X, error, "Fly collision X maximum disagrees with the camera clamp"
.assert BSP_COLLISION_MAX_Y = BSP_WORLD_COORD_MAX_Y, error, "Fly collision Y maximum disagrees with the camera clamp"
.assert BSP_COLLISION_MAX_Z = BSP_WORLD_COORD_MAX_Z, error, "Fly collision Z maximum disagrees with the camera clamp"
.assert BSP_COLLISION_COLUMN_ID_BITS >= 1 .and BSP_COLLISION_COLUMN_ID_BITS <= 10, error, "Fly collision column IDs escape the packed runtime width"
.assert BSP_COLLISION_MAP_BYTES = (BSP_COLLISION_COLUMN_COUNT * BSP_COLLISION_COLUMN_ID_BITS + 7) / 8, error, "Fly collision map lost an XY column"
.assert BSP_COLLISION_DICTIONARY_BYTES = (BSP_COLLISION_DICTIONARY_COUNT * BSP_COLLISION_Z_COUNT + 7) / 8, error, "Fly collision dictionary size disagrees"
.assert BSP_COLLISION_DICTIONARY_OFFSET = BSP_COLLISION_MAP_BYTES, error, "Fly collision dictionary no longer follows its map"
.assert BSP_COLLISION_PAYLOAD_BYTES = BSP_COLLISION_MAP_BYTES + BSP_COLLISION_DICTIONARY_BYTES, error, "Fly collision payload size disagrees"
.assert BSP_COLLISION_PACKED_CHUNK_COUNT >= 1 .and BSP_COLLISION_PACKED_CHUNK_COUNT <= 2, error, "Fly collision payload exceeds its ROM reservation"
.assert BSP_COLLISION_PACKED_0_BYTES <= BSP_WORLD_ROM_BANK_BYTES, error, "Fly collision payload head exceeds one halfbank"
.assert BSP_COLLISION_PACKED_1_BYTES <= BSP_WORLD_ROM_BANK_BYTES, error, "Fly collision payload tail exceeds one halfbank"
.assert BSP_COLLISION_PAYLOAD_BYTES <= $10000, error, "Fly collision payload exceeds one WRAM bank"
; ROM3 holds configured-demo timing. Full world data starts at ROM4, and every
; linker segment is bounded to one 32 KiB LoROM window.
.assert __BSP_DEMO_TIMING_LOAD__ = BSP_ROM_LOAD_BSP_DEMO_TIMING, lderror, "configured demo timing moved out of ROM3"
.assert __BSP_WORLD_VERTICES_LOAD__ = BSP_ROM_LOAD_BSP_WORLD_VERTICES, lderror, "Full-map vertices moved out of ROM4"
.assert __BSP_WORLD_INDICES_0_LOAD__ = BSP_ROM_LOAD_BSP_WORLD_INDICES_0, lderror, "Full-map index head moved out of ROM5"
.assert __BSP_WORLD_INDICES_1_LOAD__ = BSP_ROM_LOAD_BSP_WORLD_INDICES_1, lderror, "Full-map index tail moved out of ROM6"
.assert __BSP_WORLD_FACES_LOAD__ = BSP_ROM_LOAD_BSP_WORLD_FACES, lderror, "Full-map faces moved out of ROM7"
.assert __BSP_WORLD_FACE_PLANES_LOAD__ = BSP_ROM_LOAD_BSP_WORLD_FACE_PLANES, lderror, "Full-map face planes moved out of ROM8"
.assert __BSP_WORLD_NODES_LOAD__ = BSP_ROM_LOAD_BSP_WORLD_NODES, lderror, "Full-map nodes moved out of ROM9"
.assert __BSP_WORLD_PLANES_LOAD__ = BSP_ROM_LOAD_BSP_WORLD_PLANES, lderror, "Full-map planes moved out of ROM10"
.assert __BSP_WORLD_LEAVES_LOAD__ = BSP_ROM_LOAD_BSP_WORLD_LEAVES, lderror, "Full-map leaves moved out of ROM11"
.assert __BSP_WORLD_MARKSURFACES_LOAD__ = BSP_ROM_LOAD_BSP_WORLD_MARKSURFACES, lderror, "Raw marksurfaces moved out of ROM124"
.assert __BSP_WORLD_VISIBILITY_0_LOAD__ = BSP_ROM_LOAD_BSP_WORLD_VISIBILITY_0, lderror, "Raw visibility head moved out of ROM125"
.assert __BSP_WORLD_VISIBILITY_1_LOAD__ = BSP_ROM_LOAD_BSP_WORLD_VISIBILITY_1, lderror, "Raw visibility tail moved out of ROM126"
.assert __BSP_WORLD_PVS_DIRECTORY_LOAD__ = BSP_ROM_LOAD_BSP_WORLD_PVS_DIRECTORY, lderror, "Face-PVS directory disagrees with generated address"
.ifndef PLAYABLE_MAP_ID
.assert __BSP_WORLD_PVS_DIRECTORY_LOAD__ = ((__BSP_WORLD_PVS_2_LOAD__ + __BSP_WORLD_PVS_2_SIZE__ + 7) & $FFFFF8), lderror, "Face-PVS directory must follow aligned PVS2"
.endif
.assert BSP_WORLD_PVS_GUARD_ROM_ADDRESS + BSP_WORLD_PVS_GUARD_BYTES <= $10000, error, "Face-PVS guards cross bank 18"
.assert __BSP_WORLD_PVS_0_LOAD__ = BSP_ROM_LOAD_BSP_WORLD_PVS_0, lderror, "Full-map face-PVS chunk 0 moved out of ROM16"
.assert __BSP_WORLD_PVS_1_LOAD__ = BSP_ROM_LOAD_BSP_WORLD_PVS_1, lderror, "Full-map face-PVS chunk 1 moved out of ROM17"
.assert __BSP_WORLD_PVS_2_LOAD__ = BSP_ROM_LOAD_BSP_WORLD_PVS_2, lderror, "Full-map face-PVS chunk 2 moved out of ROM18"
.assert __BSP_WORLD_PVS_3_LOAD__ = BSP_ROM_LOAD_BSP_WORLD_PVS_3, lderror, "Full-map face-PVS chunk 3 moved out of ROM19"
.assert __BSP_WORLD_FACE_OWNERS_LOAD__ = BSP_ROM_LOAD_BSP_WORLD_FACE_OWNERS, lderror, "World face owners moved"
.assert __BSP_WORLD_NODE_PARENTS_LOAD__ = BSP_ROM_LOAD_BSP_WORLD_NODE_PARENTS, lderror, "Full-map node parents moved out of ROM21"
.assert __BSP_WORLD_SHADING_LOAD__ = BSP_ROM_LOAD_BSP_WORLD_SHADING, lderror, "Full-map shading moved out of ROM22"
.assert __BSP_WORLD_TEXCOORD_0_LOAD__ = BSP_ROM_LOAD_BSP_WORLD_TEXCOORD_0, lderror, "Texture coordinates moved out of ROM23"
.assert __BSP_WORLD_TEXCOORD_1_LOAD__ = BSP_ROM_LOAD_BSP_WORLD_TEXCOORD_1, lderror, "Texture coordinates moved out of ROM24"
.assert __BSP_WORLD_TEXTURE_AUX_LOAD__ = BSP_ROM_LOAD_BSP_WORLD_TEXTURE_AUX, lderror, "Texture auxiliary data moved out of ROM25"
.assert __BSP_WORLD_TEXTURE_AUX_SIZE__ <= BSP_WORLD_ROM_BANK_BYTES, lderror, "Texture auxiliary data exceeds ROM25"
.assert __BSP_WORLD_TEXTURE_0_LOAD__ = BSP_ROM_LOAD_BSP_WORLD_TEXTURE_0, lderror, "Exact texture bank 0 moved"
.assert __BSP_WORLD_TEXTURE_1_LOAD__ = BSP_ROM_LOAD_BSP_WORLD_TEXTURE_1, lderror, "Exact texture bank 1 moved"
.assert __BSP_WORLD_TEXTURE_2_LOAD__ = BSP_ROM_LOAD_BSP_WORLD_TEXTURE_2, lderror, "Exact texture bank 2 moved"
.assert __BSP_WORLD_TEXTURE_3_LOAD__ = BSP_ROM_LOAD_BSP_WORLD_TEXTURE_3, lderror, "Exact texture bank 3 moved"
.assert __BSP_WORLD_TEXTURE_4_LOAD__ = BSP_ROM_LOAD_BSP_WORLD_TEXTURE_4, lderror, "Exact texture bank 4 moved"
.assert __BSP_WORLD_TEXTURE_5_LOAD__ = BSP_ROM_LOAD_BSP_WORLD_TEXTURE_5, lderror, "Exact texture bank 5 moved"
.assert __BSP_WORLD_LIGHTMAP_DIRECTORY_LOAD__ = BSP_ROM_LOAD_BSP_WORLD_LIGHTMAP_DIRECTORY, lderror, "Fly lightmap directory moved"
.assert __BSP_WORLD_LIGHTMAP_0_LOAD__ = BSP_ROM_LOAD_BSP_WORLD_LIGHTMAP_0, lderror, "Lightmap bank 0 moved"
.assert __BSP_WORLD_LIGHTMAP_1_LOAD__ = BSP_ROM_LOAD_BSP_WORLD_LIGHTMAP_1, lderror, "Lightmap bank 1 moved"
.assert __BSP_WORLD_LIGHTMAP_2_LOAD__ = BSP_ROM_LOAD_BSP_WORLD_LIGHTMAP_2, lderror, "Lightmap bank 2 moved"
.assert __BSP_WORLD_LIGHTMAP_3_LOAD__ = BSP_ROM_LOAD_BSP_WORLD_LIGHTMAP_3, lderror, "Lightmap bank 3 moved"
.ifndef PLAYABLE_MAP_ID
.assert __BSP_LIGHTMAP_COLORMAPS_LOAD__ = __BSP_DEMO_TIMING_LOAD__ + __BSP_DEMO_TIMING_SIZE__, lderror, "Lightmap colormaps no longer follow demo timing"
.else
.assert __BSP_LIGHTMAP_COLORMAPS_LOAD__ = BSP_ROM_LOAD_BSP_LIGHTMAP_COLORMAPS, lderror, "Playable segment disagrees with its derived placement"
.endif
.assert __BSP_DIVIDE_Q12_RECIPROCAL_0_LOAD__ = $800000 + (GSU_DIVIDE_Q12_RECIPROCAL_FIRST_ROM_BANK+0)*$10000 + GSU_DIVIDE_Q12_RECIPROCAL_ROM_ADDRESS, lderror, "Q12 reciprocal bank 0 moved"
.assert __BSP_DIVIDE_Q12_RECIPROCAL_1_LOAD__ = $800000 + (GSU_DIVIDE_Q12_RECIPROCAL_FIRST_ROM_BANK+1)*$10000 + GSU_DIVIDE_Q12_RECIPROCAL_ROM_ADDRESS, lderror, "Q12 reciprocal bank 1 moved"
.assert __BSP_DIVIDE_Q12_RECIPROCAL_2_LOAD__ = $800000 + (GSU_DIVIDE_Q12_RECIPROCAL_FIRST_ROM_BANK+2)*$10000 + GSU_DIVIDE_Q12_RECIPROCAL_ROM_ADDRESS, lderror, "Q12 reciprocal bank 2 moved"
.ifndef PLAYABLE_COMPACT_Q12_RECIPROCALS
.assert __BSP_DIVIDE_Q12_RECIPROCAL_3_LOAD__ = $800000 + (GSU_DIVIDE_Q12_RECIPROCAL_FIRST_ROM_BANK+3)*$10000 + GSU_DIVIDE_Q12_RECIPROCAL_ROM_ADDRESS, lderror, "Q12 reciprocal bank 3 moved"
.endif
.assert __BSP_COLLISION_PACKED_0_LOAD__ = BSP_ROM_LOAD_BSP_COLLISION_PACKED_0, lderror, "Fly collision payload chunk 0 moved"
.assert __BSP_COLLISION_PACKED_1_LOAD__ = BSP_ROM_LOAD_BSP_COLLISION_PACKED_1, lderror, "Fly collision payload chunk 1 moved"
.assert __BSP_WORLD_VERTICES_SIZE__ <= BSP_WORLD_ROM_BANK_BYTES, lderror, "Full-map vertex segment exceeds its ROM bank"
.assert __BSP_WORLD_INDICES_0_SIZE__ <= BSP_WORLD_ROM_BANK_BYTES, lderror, "Full-map index head exceeds its ROM bank"
.assert __BSP_WORLD_INDICES_1_SIZE__ <= BSP_WORLD_ROM_BANK_BYTES, lderror, "Full-map index tail exceeds its ROM bank"
.assert __BSP_WORLD_FACES_SIZE__ <= BSP_WORLD_ROM_BANK_BYTES, lderror, "Full-map face segment exceeds its ROM bank"
.assert __BSP_WORLD_FACE_PLANES_SIZE__ <= BSP_WORLD_ROM_BANK_BYTES, lderror, "Full-map face-plane segment exceeds its ROM bank"
.assert __BSP_WORLD_NODES_SIZE__ <= BSP_WORLD_ROM_BANK_BYTES, lderror, "Full-map node segment exceeds its ROM bank"
.assert __BSP_WORLD_PLANES_SIZE__ <= BSP_WORLD_ROM_BANK_BYTES, lderror, "Full-map plane segment exceeds its ROM bank"
.assert __BSP_WORLD_LEAVES_SIZE__ <= BSP_WORLD_ROM_BANK_BYTES, lderror, "Full-map leaf segment exceeds its ROM bank"
.assert __BSP_WORLD_MARKSURFACES_SIZE__ <= BSP_WORLD_ROM_BANK_BYTES, lderror, "Full-map marksurface segment exceeds its ROM bank"
.assert __BSP_WORLD_VISIBILITY_0_SIZE__ <= BSP_WORLD_ROM_BANK_BYTES, lderror, "Full-map visibility head exceeds its ROM bank"
.assert __BSP_WORLD_VISIBILITY_1_SIZE__ <= BSP_WORLD_ROM_BANK_BYTES, lderror, "Full-map visibility tail exceeds its ROM bank"
.assert __BSP_WORLD_PVS_DIRECTORY_SIZE__ = BSP_WORLD_PVS_DIRECTORY_BYTES + BSP_WORLD_PVS_GUARD_BYTES, lderror, "Full-map face-PVS directory/guard segment has the wrong size"
.assert __BSP_WORLD_PVS_0_SIZE__ <= BSP_WORLD_ROM_BANK_BYTES, lderror, "Full-map face-PVS chunk 0 exceeds its ROM bank"
.assert __BSP_WORLD_PVS_1_SIZE__ <= BSP_WORLD_ROM_BANK_BYTES, lderror, "Full-map face-PVS chunk 1 exceeds its ROM bank"
.assert __BSP_WORLD_PVS_2_SIZE__ <= BSP_WORLD_ROM_BANK_BYTES, lderror, "Full-map face-PVS chunk 2 exceeds its ROM bank"
.assert __BSP_WORLD_PVS_3_SIZE__ <= BSP_WORLD_ROM_BANK_BYTES, lderror, "Full-map face-PVS chunk 3 exceeds its ROM bank"
.ifndef PLAYABLE_MAP_ID
.assert __BSP_SKY_FLOAT_PHASES_LOAD__ >= __BSP_ALIAS_TEMPORAL_LOAD__ + __BSP_ALIAS_TEMPORAL_SIZE__, lderror, "Float sky phases overlap CPU timing or reuse tables"
.assert __BSP_SKY_FLOAT_PHASES_LOAD__ + __BSP_SKY_FLOAT_PHASES_SIZE__ <= $F88000, lderror, "Float sky phases exceed ROM112's CPU mirror"
.else
.assert __BSP_SKY_FLOAT_PHASES_LOAD__ = BSP_ROM_LOAD_BSP_SKY_FLOAT_PHASES, lderror, "Playable float sky phases disagree with their derived placement"
.assert __BSP_SKY_FLOAT_PHASES_SIZE__ <= BSP_WORLD_ROM_BANK_BYTES, lderror, "Float sky phases exceed their segment capacity"
.assert .loword(__BSP_SKY_FLOAT_PHASES_LOAD__) + __BSP_SKY_FLOAT_PHASES_SIZE__ <= $10000, lderror, "Float sky phases cross their CPU bank"
.endif
.assert __BSP_SKY_FLOAT_PHASES_SIZE__ = BSP_SKY_FLOAT_PHASE_BYTES, lderror, "Float sky phase segment size disagrees"
.assert __BSP_DEMO_TIMING_SIZE__ = BSP_SKY_PHASE_BYTES+BSP_TURBULENCE_PHASE_BYTES+BSP_TURBULENCE_TABLE_BYTES, lderror, "configured special-phase segment has the wrong size"
.assert __BSP_DEMO_TIMING_SIZE__ + __BSP_LIGHTMAP_COLORMAPS_SIZE__ <= BSP_WORLD_ROM_BANK_BYTES, lderror, "Demo timing and lightmap colormaps exceed ROM3"
.assert __BSP_DEMO_TIMING_SIZE__ <= BSP_WORLD_ROM_BANK_BYTES, lderror, "configured demo timing exceeds its ROM bank"
.assert __BSP_COLLISION_PACKED_0_SIZE__ = BSP_COLLISION_PACKED_0_BYTES, lderror, "Fly collision payload chunk 0 has the wrong size"
.assert __BSP_COLLISION_PACKED_1_SIZE__ = BSP_COLLISION_PACKED_1_BYTES, lderror, "Fly collision payload chunk 1 has the wrong size"
.assert __BSP_WORLD_FACE_OWNERS_SIZE__ = BSP_PHYSICAL_FACE_OWNER_BYTES, lderror, "Full-map face-owner segment has the wrong size"
.assert __BSP_WORLD_NODE_PARENTS_SIZE__ = BSP_WORLD_NODE_COUNT * BSP_WORLD_NODE_PARENT_RECORD_BYTES, lderror, "Full-map node-parent segment has the wrong size"
.assert __BSP_WORLD_SHADING_SIZE__ = BSP_WORLD_SHADING_BYTES, lderror, "Full-map shading segment has the wrong size"
.assert __BSP_WORLD_TEXCOORD_0_SIZE__ = BSP_WORLD_TEXTURE_COORD_0_BYTES, lderror, "Texture-coordinate bank 0 has the wrong size"
.assert __BSP_WORLD_TEXCOORD_1_SIZE__ = BSP_WORLD_TEXTURE_COORD_1_BYTES, lderror, "Texture-coordinate bank 1 has the wrong size"
.if BSP_WORLD_LIGHTMAP_DIRECTORY_BYTES <= BSP_WORLD_ROM_BANK_BYTES
.assert __BSP_WORLD_LIGHTMAP_DIRECTORY_SIZE__ = BSP_WORLD_LIGHTMAP_DIRECTORY_BYTES, lderror, "Lightmap directory segment has the wrong size"
.else
.assert __BSP_WORLD_LIGHTMAP_DIRECTORY_SIZE__ + __BSP_WORLD_LIGHTMAP_DIRECTORY_TAIL_SIZE__ = BSP_WORLD_LIGHTMAP_DIRECTORY_BYTES, lderror, "Fly lightmap directory size disagrees"
.assert __BSP_WORLD_LIGHTMAP_DIRECTORY_TAIL_LOAD__ = BSP_ROM_LOAD_BSP_WORLD_LIGHTMAP_DIRECTORY_TAIL, lderror, "Fly lightmap directory tail moved"
.endif
.assert __BSP_WORLD_LIGHTMAP_0_SIZE__ <= BSP_WORLD_ROM_BANK_BYTES, lderror, "Lightmap bank 0 exceeds its ROM bank"
.assert __BSP_WORLD_LIGHTMAP_1_SIZE__ <= BSP_WORLD_ROM_BANK_BYTES, lderror, "Lightmap bank 1 exceeds its ROM bank"
.assert __BSP_WORLD_LIGHTMAP_2_SIZE__ <= BSP_WORLD_ROM_BANK_BYTES, lderror, "Lightmap bank 2 exceeds its ROM bank"
.assert __BSP_WORLD_LIGHTMAP_3_SIZE__ <= BSP_WORLD_ROM_BANK_BYTES, lderror, "Lightmap bank 3 exceeds its ROM bank"
.assert __BSP_LIGHTMAP_COLORMAPS_SIZE__ <= BSP_WORLD_ROM_BANK_BYTES, lderror, "Lightmap colormaps exceed their ROM bank"
.assert __BSP_DIVIDE_Q12_RECIPROCAL_0_SIZE__ = BSP_WORLD_ROM_BANK_BYTES, lderror, "Q12 reciprocal bank 0 has the wrong size"
.assert __BSP_DIVIDE_Q12_RECIPROCAL_1_SIZE__ = BSP_WORLD_ROM_BANK_BYTES, lderror, "Q12 reciprocal bank 1 has the wrong size"
.ifdef PLAYABLE_COMPACT_Q12_RECIPROCALS
.assert __BSP_DIVIDE_Q12_RECIPROCAL_2_SIZE__ = $3FFE, lderror, "Packed Q12 tail has the wrong size"
.else
.assert __BSP_DIVIDE_Q12_RECIPROCAL_2_SIZE__ = BSP_WORLD_ROM_BANK_BYTES, lderror, "Q12 reciprocal bank 2 has the wrong size"
.assert __BSP_DIVIDE_Q12_RECIPROCAL_3_SIZE__ = $7FFC, lderror, "Q12 reciprocal bank 3 has the wrong size"
.endif
; These assets always cross distinct banks, so a forward MVN is overlap-safe.
; Avoid memcpy's low-word-only overlap heuristic selecting a backward MVP.
.include "quake/PlayableModule.s"
.include "quake/WorldLightmapStream.s"
.ifdef PLAYABLE_SWITCHED_LIGHTS
.include "quake/SwitchedLights.s"
.endif
.include "quake/WorldCoordinateStream.s"
.include "quake/SpriteStream.s"
.include "quake/VisibilityStream.s"
.ifdef PLAYABLE_MAP_ID
.import __GSU_FACE_COLOR_CODE_RUN__, __GSU_FACE_COLOR_CODE_LOAD__, __GSU_FACE_COLOR_CODE_SIZE__
.import __F3_GSU_FACE_COLOR_CODE_RUN__, __F3_GSU_FACE_COLOR_CODE_LOAD__, __F3_GSU_FACE_COLOR_CODE_SIZE__
.endif
.ifdef PLAYABLE_FLAT_MONOTONE_RASTER
.import __GSU_FLAT_MONOTONE_CODE_RUN__, __GSU_FLAT_MONOTONE_CODE_LOAD__, __GSU_FLAT_MONOTONE_CODE_SIZE__
.endif
.macro BSP_STATIC_COPY dest, source, length
.ifdef PLAYABLE_MAP_ID
        .local source_is_ram
        .define source_is_ram 0
        .if .const(source)
          .if (^(source) = $70) .or (^(source) = $71) .or (^(source) = $7E) .or (^(source) = $7F)
            .undefine source_is_ram
            .define source_is_ram 1
          .endif
        .endif
        .if source_is_ram
        RW_push set:a16i16
        phb
        lda     #length-1
        ldx     #.loword(source)
        ldy     #.loword(dest)
        mvn     #^(source), #^(dest)
        plb
        RW_pull
        .else
        .local playable_source_address
        .define playable_source_address + (source)
        .assert (length) > 0 .and (length) <= $FFFF, lderror, "Playable static-copy length is invalid"
        .assert (^(source) <> $70) .and (^(source) <> $71) .and (^(source) <> $7E) .and (^(source) <> $7F), lderror, "Relocatable RAM copies require the MVN path"
        .assert (^(playable_source_address) >= $80) .or ((^(playable_source_address) >= $60) .and (^(playable_source_address) < $70)) .or ((^(playable_source_address) >= $40) .and (^(playable_source_address) < $50)), lderror, "Unsupported playable archive source"
        RW_push set:a16i16
        ; The inline descriptor bank becomes DB while the copy helper uses low WRAM.
        .assert (.bankbyte(*) & $40) = 0, lderror, "Playable inline copy requires a caller bank with the low WRAM mirror"
        jsl     PlayableCopyInline
        .faraddr PLAYABLE_MSU_OFFSET(playable_source_address)
        .faraddr dest
        .word length
        .undefine playable_source_address
        RW_pull
        .endif
        .undefine source_is_ram
.else
        RW_push set:a16i16
        phb
        lda     #length-1
        ldx     #.loword(source)
        ldy     #.loword(dest)
        mvn     #^(source), #^(dest)
        plb
        RW_pull
.endif
.endmacro
.include "quake/SkyRenderer.s"
.include "quake/SkyPhaseExact.s"
.include "quake/TurbulenceRenderer.s"
.include "quake/AliasAnimation.s"
; FX3 keeps the S-CPU and NMI serviceable while RON/RAN own cartridge buses.
.segment "RODATA"
QuakeBSPEdgeDivideCacheInitial:
        .res    GSU_TEXTURE_EDGE_DIVIDE_CACHE_BYTES, 0
.if BSP_QUAKEC_GAMEPLAY
        .byte   1, 2, 4, 8, 16, 32, 64, 128
.endif
QuakeBSPEdgeDivideCacheInitialEnd:
.assert QuakeBSPEdgeDivideCacheInitialEnd - QuakeBSPEdgeDivideCacheInitial = GSU_TEXTURE_EDGE_DIVIDE_CACHE_BYTES + GSU_PACKET_BIT_MASK_BYTES, error, "Edge cache and packet mask initializer has the wrong size"
.segment "CODE"
Main:
        CPU_init
        REG_init
.ifdef PLAYABLE_MAP_ID
        rep     #$30
        RW_assume a16i16
        jsr     PlayableInitMenuPreferences
.endif
        BSP_STATIC_COPY __GSUCODE_RUN__, BSP_CPU_CODE_ADDRESS(__GSUCODE_LOAD__), __GSUCODE_SIZE__
        BSP_STATIC_COPY __GSU_AUX_CODE_RUN__, __GSU_AUX_CODE_LOAD__, __GSU_AUX_CODE_SIZE__
        BSP_STATIC_COPY __GSU_BRUSH_CODE_RUN__, __GSU_BRUSH_CODE_LOAD__, __GSU_BRUSH_CODE_SIZE__
.ifdef PLAYABLE_MAP_ID
        BSP_STATIC_COPY __GSU_FACE_COLOR_CODE_RUN__, BSP_CPU_CODE_ADDRESS(__GSU_FACE_COLOR_CODE_LOAD__), __GSU_FACE_COLOR_CODE_SIZE__
.endif
.if .defined(PLAYABLE_FLAT_MONOTONE_RASTER) && !.defined(PLAYABLE_PAIRED_WORLD_CODE)
        BSP_STATIC_COPY __GSU_FLAT_MONOTONE_CODE_RUN__, BSP_CPU_CODE_ADDRESS(__GSU_FLAT_MONOTONE_CODE_LOAD__), __GSU_FLAT_MONOTONE_CODE_SIZE__
.endif
        BSP_STATIC_COPY __GSU_TEXTURE_TAIL_CODE_RUN__, __GSU_TEXTURE_TAIL_CODE_LOAD__, __GSU_TEXTURE_TAIL_CODE_SIZE__
        jsr     StageStaticAssets
.if BSP_QUAKEC_GAMEPLAY
        RW_forced a16i16
.ifndef PLAYABLE_MAP_ID
        lda     #1                      ; Normal, the original Quake default.
        sta     quake_skill_selected
.endif
        stz     quake_restart_pending
        jsl     QuakeCInit
.if .defined(PLAYABLE_MAP_ID) && .defined(QC_CAMPAIGN_ITEMS)
        jsl     CampaignApply
.endif
        jsl     ShotgunSoundInit
.endif
        RW_forced a16i16
        lda     #$FFFF
        sta     f:GSU_DATA_BASE+GSU_BRUSH_PVS_LEAF_OFFSET
        ; StageStaticAssets fills the Q12 mirror through $8BFF, including the
        ; sampler's reserved $8B00 tail. Install the sampler only afterward.
        RW_forced a16i16
        BSP_STATIC_COPY __GSU_TURBULENCE_HOT_CODE_RUN__, __GSU_TURBULENCE_HOT_CODE_LOAD__, __GSU_TURBULENCE_HOT_CODE_SIZE__
.ifdef PLAYABLE_PAIRED_WORLD_CODE
  .ifdef PLAYABLE_FLAT_MONOTONE_RASTER
        stz     flat_monotone_resident
  .endif
        jsr     InstallPairedWorldOverlay
.endif
        lda     #BSP_START_YAW_INDEX*CAMERA_ANGLE_LEGACY_STEP
        sta     yaw_index
        stz     pitch_level
        lda     #BSP_FLY_START_X_Q8
        sta     camera_x
        lda     #BSP_FLY_START_Y_Q8
        sta     camera_y
        lda     #BSP_FLY_START_Z_Q8
        sta     camera_z
        stz     control_divider
        jsr     InitFlyMouse
        RW_forced a16i16
        stz     control_revision
        stz     coverage_debug
        stz     render_coverage_mode
        stz     scheduled_frame_valid
        stz     scheduled_frame_coverage_mode
        stz     scheduled_frame_brush_visual_state
.if BSP_QUAKEC_GAMEPLAY
  .if QC_ENTRANCE_COUNT > 0
        stz     scheduled_entrance_variants
        stz     scheduled_entrance_variants+2
  .endif
  .ifdef QC_EXIT_MOVER_COUNT
        stz     scheduled_exit_pose_word
    .if QC_EXIT_MOVER_COUNT > 8
        stz     scheduled_exit_pose_word_high
    .endif
  .endif
.endif
        lda     #$0001
        sta     temporal_reuse_enabled
        stz     demo_mode               ; Always zero for probes that also inspect older ROMs.
        stz     demo_track_pose
        stz     demo_schedule_revision
        stz     video_tick
        stz     staging_scanline
.ifndef PLAYABLE_MAP_ID
        lda     #$0004
        sta     technique
.endif
        lda     #$0001
        sta     technique4_specialized_path
        sta     texture_colormap_mode
        sta     texture_phase_overlay_valid
        sta     brush_code_valid
        stz     texture_renderer_code_variant
        jsr     InitSkyClock
        jsr     InitAliasClock
        jsr     InitTurbulenceClock
        stz     runtime_menu_open
        stz     runtime_menu_selection
        stz     runtime_menu_release_gate
        stz     runtime_menu_restart_action
        stz     runtime_menu_draft_playback
.ifndef PLAYABLE_MAP_ID
        lda     #$0004
        sta     runtime_menu_draft_technique
        lda     #$0001
        sta     runtime_menu_draft_textures
        lda     #$0001
        sta     runtime_menu_draft_lighting
        lda     #BSP_BRUSH_DYNAMIC_REPLAY_SUPPORTED
        sta     dynamic_brushes_enabled
        sta     runtime_menu_draft_brushes
        lda     #BSP_RENDER_ENTITIES_SUPPORTED
        sta     mdl_entities_enabled
        sta     runtime_menu_draft_entities
.endif
        stz     dynamic_brush_revision
        stz     brush_visual_state
        stz     producer_slot
        stz     ready_slot
        stz     upload_slot
        stz     frame_ready
        stz     upload_active
        stz     upload_target
        stz     upload_format
        stz     presented_format
        stz     upload_palette_mode
        stz     presented_palette_mode
        stz     upload_offset
        stz     upload_chunk
        stz     stage_frame_required
        stz     overlap_selector_active
        stz     prefetched_selector_valid
        stz     render_counter
        stz     present_counter
        stz     presented_weapon_frame
        stz     gsu_job_counter
        stz     staging_dma_counter
        stz     vram_chunk_counter
        stz     page_flip_counter
        stz     presented_coverage_mode
        stz     slot_coverage_mode
        stz     slot_coverage_mode+2
        stz     video_active
        stz     active_leaf
        stz     active_pvs_face_count
        stz     active_pvs_revision
        stz     active_selection_revision
        stz     active_pvs_encoded_bytes
        stz     active_packet_vertex_count
        stz     active_packet_index_count
        stz     active_packet_face_count
        stz     active_packet_plane_count
        stz     active_packet_overflow_face
        stz     active_packet_overflow_vertex
        stz     active_packet_overflow_index
        stz     active_packet_revision
        stz     active_packet_camera_revision
        stz     active_packet_guard_status
        stz     active_packet_error
        lda     #GSU_OBSERVATION_UNAVAILABLE
        sta     active_bsp_node_count
        sta     active_packet_drawable_count
        sta     active_packet_front_count
        sta     active_packet_near_count
        sta     active_packet_screen_count
        sta     active_packet_painter_node_count
        jsr     InitTemporalReuse
        jsr     InitFlyViewport
        jsr     ApplyBootParameters
        ; Runtime state is authoritative. Derive every menu draft only after
        ; optional frame-zero overrides have been applied and before InitVideo
        ; builds the first OAM image.
        jsr     SyncRuntimeMenuDrafts
        ; Force the first selector pass to decode even if cartridge RAM retained
        ; a prior session's telemetry.
        lda     #$0000
        sta     f:GSU_TELEMETRY+0
        lda     #$FFFF
        sta     f:GSU_TELEMETRY+2
        lda     #$0000
        sta     f:GSU_TELEMETRY+6
        sta     f:GSU_TELEMETRY+28      ; No packet is valid across power-up.
        lda     #GSU_OBSERVATION_UNAVAILABLE
        sta     f:GSU_TELEMETRY+30
        sta     f:GSU_DATA_BASE+GSU_TELEMETRY_NODE_COUNT
        sta     f:GSU_DATA_BASE+GSU_TELEMETRY_DRAWABLE_COUNT
        sta     f:GSU_DATA_BASE+GSU_TELEMETRY_FRONT_COUNT
        sta     f:GSU_DATA_BASE+GSU_TELEMETRY_NEAR_COUNT
        sta     f:GSU_DATA_BASE+GSU_TELEMETRY_SCREEN_COUNT
        sta     f:GSU_DATA_BASE+GSU_TELEMETRY_PAINTER_NODE_COUNT
        sta     f:GSU_DATA_BASE+GSU_TELEMETRY_BRUSH_CURRENT_TOKEN
        sta     f:GSU_DATA_BASE+GSU_TELEMETRY_BRUSH_CURRENT_SLOT
        sta     f:GSU_DATA_BASE+GSU_TELEMETRY_BRUSH_CURRENT_FACE
        sta     f:GSU_DATA_BASE+GSU_TELEMETRY_BRUSH_CURRENT_TEXTURE
        jsr     InitGSU
        jsr     BootRenderViewport
.ifdef PLAYABLE_MAP_ID
        jsr     StatusHudInit
.endif
        ; InitVideo returns in 8-bit accumulator mode. These queue fields are
        ; words, so restore the runtime width before encoding their stores.
        RW_forced a16i16
        lda     #$0001
        sta     producer_slot
        sta     upload_target
        ; InitVideo already made slot 0 visible. Publish that slot's complete
        ; identity before present_counter advertises the startup commit.
        stz     upload_slot
        jsr     PublishUploadSlotState
        lda     #$0001
        sta     present_counter
        RW      a8
        VBL_set BSPVBlank
.ifndef PLAYABLE_MAP_ID
        lda     RDNMI                   ; Drop any VBlank latched during startup.
        VBL_on
.endif
        lda     #$01
        sta     video_active
        stz     video_active+1
        lda     #inidisp(ON, DISP_BRIGHTNESS_MAX)
        sta     SFX_inidisp
.ifdef PLAYABLE_MAP_ID
        jsl     ArmPlayableVBlank
.endif
.include "quake/SoundMainLoop.s"
        lda     runtime_menu_open
        beq     MainLoopRender
.ifdef PLAYABLE_E1M1_PREFETCH_GAMEPLAY
        ; VBlank can open the menu after the prefetch was admitted.
        lda     deferred_gameplay_tick
        beq     MainLoopMenuWait
        jsr     ServiceDeferredGameplay
MainLoopMenuWait:
.endif
        stz     prefetched_selector_valid
        BSP_SOUND_WAIT_FRAME
        bra     MainLoop
MainLoopRender:
        jmp     (frame_pipeline_entry)

.ifdef PLAYABLE_MAP_ID
.pushseg
.segment "BSP_QUAKEC"
; Keep controller time stopped until sound and video are ready. Leave at
; least one scanline before a new VBlank edge when arming from active display.
ArmPlayableVBlank:
        RW_assume a8i16
@Beam:
        lda     STAT78
        lda     SLHV
        lda     OPVCT
        cmp     #224
        beq     @Beam
        lda     RDNMI
        VBL_on
        rtl
.popseg
.endif

.ifdef PLAYABLE_E1M1_PREFETCH_GAMEPLAY
; Serve the deferred input only if the renderer join did not already use it.
ServiceDeferredGameplay:
        RW_assume a16i16
        stz     deferred_gameplay_tick
        dec
        cmp     f:quakec_last_tick
        bne     :+
        jsl     QuakeCService
:
        rts

DeferPrefetchedGameplay:
        RW_assume a16i16
        lda     active_render_scale
        cmp     #2
        bne     @Rejected
        lda     render_coverage_mode
        bne     @Rejected
        lda     active_packet_guard_status
        cmp     #GSU_PACKET_GUARD_VALUE
        bne     @Rejected
        lda     active_packet_error
        bne     @Rejected
        lda     demo_schedule_revision
        cmp     render_demo_epoch
        bne     @Rejected
        ; Both renderers service gameplay while their frozen X2 job runs.
        .assert RUNTIME_MENU_TECHNIQUE_FACE_COLORS = 3, error, "Flat technique changed"
        .assert BSP_TECHNIQUE_TEXTURED_LIGHTMAP = 4, error, "Full technique changed"
        lda     render_camera+10
        dec
        and     #$00FE
        cmp     #(RUNTIME_MENU_TECHNIQUE_FACE_COLORS-1)
        bne     @Rejected
        lda     runtime_menu_open
        bne     @Rejected
        lda     f:quakec_last_tick
        cmp     a:QC_INPUT_TICK
        beq     @Rejected
        inc
        beq     @Rejected               ; Zero is the inactive token.
        ; Capture the due live tap before VBlank can expire it.
        jsl     GameplayCaptureDeferredLiveInput
        sta     deferred_gameplay_tick
        sec
        rts
@Rejected:
        clc
        rts
.endif
;-------------------------------------------------------------------------------
.ifdef PLAYABLE_PAIRED_WORLD_CODE
InstallPairedWorldOverlay:
        RW_assume a16i16
        BSP_STATIC_COPY __GSU_PAIRED_WORLD_CODE_RUN__, __GSU_PAIRED_WORLD_CODE_LOAD__, __GSU_PAIRED_WORLD_CODE_SIZE__
  .ifdef PLAYABLE_FLAT_MONOTONE_RASTER
        lda     flat_monotone_resident
        beq     @Ready
        stz     flat_monotone_resident
        jmp     InvalidateFlatBrushCodeCache
@Ready:
  .endif
        rts
.endif
StageStaticAssets:
        RW_forced a8i16
        ; FX3 permits concurrent CPU ROM reads. Immutable collision occupancy
        ; is read directly through its linear $F0 mirror, without a WRAM copy.
        BSP_STATIC_COPY GSU_SIN, CameraAngleSin, CAMERA_ANGLE_STEPS
        BSP_STATIC_COPY GSU_COS, CameraAngleCos, CAMERA_ANGLE_STEPS
        BSP_STATIC_COPY GSU_RECIPROCAL, QuakeBSPReciprocal, GSU_RECIPROCAL_RAM_BYTES
        BSP_STATIC_COPY GSU_EXPAND_NIBBLE, QuakeBSPExpandRight, 16
        BSP_STATIC_COPY GSU_TURBULENCE_TABLE, QuakeBSPTurbulenceTable, BSP_TURBULENCE_TABLE_BYTES
        BSP_STATIC_COPY GSU_TURBULENCE_TABLE+BSP_TURBULENCE_TABLE_BYTES, QuakeBSPTurbulenceTable, BSP_TURBULENCE_TABLE_BYTES
        BSP_STATIC_COPY GSU_TEXTURE_COORD_MAP, QuakeBSPTextureCoordinateMap, GSU_TEXTURE_COORD_MAP_BYTES
        ; Persistent cartridge RAM may contain an old denominator/reciprocal
        ; pair. Zero both records so the first positive edge denominator misses.
        BSP_STATIC_COPY GSU_TEXTURE_EDGE_DIVIDE_CACHE, QuakeBSPEdgeDivideCacheInitial, GSU_TEXTURE_EDGE_DIVIDE_CACHE_BYTES + GSU_PACKET_BIT_MASK_BYTES
        BSP_STATIC_COPY GSU_DIVIDE_Q12_HOT_MIRROR, QuakeBSPDivideQ12Reciprocal, GSU_DIVIDE_Q12_HOT_MIRROR_BYTES
.ifdef QUAKE_MSU_CACHE
        jsr     MsuCacheResetArena
.endif
        ; Technique 4 is the default renderer, so stage its natural pages once
        ; at boot instead of paying a transition copy before the first frame.
        BSP_STATIC_COPY GSU_TEXTURE_COLORMAP, QuakeBSPLightmapColormap, GSU_LIGHTMAP_COLORMAP_BYTES
.ifdef PLAYABLE_SPRITE_STREAM
        ; Save the verified rows that sprite uploads will overwrite.
        BSP_STATIC_COPY SpriteStreamColormapShadow, GSU_TEXTURE_COLORMAP, SPRITE_STREAM_CACHE_BYTES
.endif
        rts
.include "quake/TemporalReuse.s"
.ifdef QUAKE_MSU_CACHE
.include "quake/MsuSurfaceCache.s"
.endif
;-------------------------------------------------------------------------------
InitGSU:
        RW_forced a8i16
        lda     #$70
        sta     FX3_PBR
        stz     FX3_RAMBR
        lda     #GSU_LOGICAL_SCBR
        sta     FX3_SCBR
        stz     FX3_SCMR
        lda     #%10000000
        sta     FX3_CFGR
        lda     #$01                    ; Select the FX3 high-speed clock.
        sta     FX3_CLSR
        rts
;-------------------------------------------------------------------------------
.include "quake/FramePipeline.s"
.include "Data/Fly3x/quake/FramePipeline.s.inc"
.include "quake/FlyViewport.s"
;-------------------------------------------------------------------------------
CaptureSelectorTelemetry:
        RW_forced a16i16
        lda     f:GSU_TELEMETRY+2
        sta     active_leaf
        lda     f:GSU_TELEMETRY+4
        sta     active_pvs_face_count
        lda     f:GSU_TELEMETRY+6
        sta     active_pvs_revision
        lda     f:GSU_TELEMETRY+10
        sta     active_pvs_encoded_bytes
        ; Publish the selector revision after every field it commits.
        lda     f:GSU_TELEMETRY+8
        sta     active_selection_revision
        lda     f:GSU_TELEMETRY+14
        sta     active_packet_vertex_count
        lda     f:GSU_TELEMETRY+16
        sta     active_packet_index_count
        lda     f:GSU_TELEMETRY+18
        sta     active_packet_face_count
        lda     f:GSU_TELEMETRY+20
        sta     active_packet_plane_count
        lda     f:GSU_TELEMETRY+22
        sta     active_packet_overflow_face
        lda     f:GSU_TELEMETRY+24
        sta     active_packet_overflow_vertex
        lda     f:GSU_TELEMETRY+26
        sta     active_packet_overflow_index
        lda     f:GSU_TELEMETRY+30
        sta     active_packet_camera_revision
        lda     f:GSU_TELEMETRY+32
        sta     active_packet_guard_status
        lda     f:GSU_TELEMETRY+44
        sta     active_packet_error
        ; The packet revision is the CPU mirror's commit word as well.
        lda     f:GSU_TELEMETRY+28
        sta     active_packet_revision
        lda     render_camera+0
        sta     active_packet_camera+0
        lda     render_camera+2
        sta     active_packet_camera+2
        lda     render_camera_q8+0
        sta     active_packet_camera_q8+0
        lda     render_camera_q8+2
        sta     active_packet_camera_q8+2
        lda     render_camera_q8+4
        sta     active_packet_camera_q8+4
        rts


;-------------------------------------------------------------------------------
; Joypad sampling remains at 60 Hz even when rendering or presentation takes
; several video frames. Start toggles native demo1 playback/manual flight;
; Select cycles the supported albedo, lightmapped, and untextured renderers.
BSPVBlank:
.ifdef PLAYABLE_MAP_ID
        phb
        phk
        plb
.endif
        RW_forced a8i16
        ; VBL_on can service a latched NMI immediately when the long selector
        ; returns during active display. Never let that deferred interrupt
        ; mutate presentation state or start a VRAM DMA outside VBlank.
        lda     HVBJOY
        bmi     :+
        jmp     BSPVBlankDone
:
.if .defined(PLAYABLE_LARGE_DISTANCE_CACHE) || .defined(PLAYABLE_FAST_WALK_PPU_MUL)
        inc     z:w_ppu_latch_nmi
.endif
        RW_forced a16i16
        inc     video_tick
.ifdef QC_PICKUP_NOTICES
        jsl     PickupNotifyVideo
.endif
.ifdef PLAYABLE_MAP_ID
        ; Playable maps always fly. Gate all three animation clocks once.
        lda     runtime_menu_open
        bne     :+
.endif
        jsr     UpdateFlySkyClock
        jsr     UpdateFlyAliasClock
        jsr     UpdateFlyTurbulenceClock
.ifdef PLAYABLE_MAP_ID
:
.endif
        jsr     UpdateRuntimeMenu
.ifdef PLAYABLE_MAP_ID
        lda     runtime_menu_open
        beq     :+
        jmp     BSPVBlankInputReady
:
  .ifdef PLAYABLE_WEAPON_OBJ
        lda     weapon_obj_menu_pending
        bne     @ControlsDone
  .endif
        jsr     PollFlyMouse
.else
        lda     runtime_menu_open
        bne     @ControlsDone
        jsr     PollFlyMouse
.endif
@ControlsDone:
        RW_forced a8i16
.ifdef PLAYABLE_WEAPON_OBJ
        lda     quake_restart_pending
        bne     :+
        jsr     ShotgunVBlank
:
  .ifdef QC_HUB_WARNING_COUNT
        ; Reserve this VBlank for a changed centerprint. A bulk upload
        ; could otherwise use the time needed for the BG2 tilemap DMA.
    .ifdef QC_E1M1_HINTS
        jsl     StartWarningVBlank
    .else
        jsr     StartWarningVBlank
    .endif
        bcc     :+
        jmp     @SoundVBlank
:
  .endif
        ; Reserve the extra CGRAM DMA on a tint transition while retaining
        ; the regular world cadence on steady tint frames.
        lda     weapon_obj_palette_key
        and     #$1c
        cmp     weapon_obj_tint_effect
        beq     :+
        jmp     @SoundVBlank
:
.endif
        lda     upload_active
        beq     :+
        jmp     @Upload
:
        lda     frame_ready
        bne     :+
        jmp     @SoundVBlank
:
        ; Publish busy before changing the consumer slot, then release the
        ; producer only after every upload field is coherent. Instrumentation
        ; may pause on any instruction inside this NMI handoff.
        lda     #$01
        sta     upload_active
        lda     ready_slot
        sta     upload_slot
        jsr     LoadUploadReuseState
        stz     upload_offset
        stz     upload_offset+1
        stz     upload_chunk
        stz     frame_ready
        RW_forced a16i16
        ldx     #0
        lda     upload_slot
        beq     :+
        ldx     #CAMERA_COMMAND_BYTES
:
        lda     slot_camera+10,x
        and     #$00FF
.ifdef QC_E1M2_DEFER_UPLOAD
        stz     upload_defer_budget
        cmp     #RUNTIME_MENU_TECHNIQUE_FACE_COLORS
        bne     :+
        pha
        lda     #(E1M2_DEFER_ACTIVE | E1M2_DEFER_LATCH)
        sta     upload_defer_budget
        pla
:
.endif
        cmp     #$0002
        bcs     @TextureUploadFormat
        stz     upload_palette_mode
        lda     #BSP_UPLOAD_FORMAT_FLAT
        bra     @UploadFormatReady
@TextureUploadFormat:
        cmp     #BSP_TECHNIQUE_UNTEXTURED_LIGHTMAP
        bne     @NaturalTexturePalette
        lda     #$0001
        sta     upload_palette_mode
        bra     @TextureUploadFormatReady
@NaturalTexturePalette:
        jsr     SelectUploadWeaponPalette
@TextureUploadFormatReady:
        lda     upload_slot
        asl
        tax
        lda     slot_present_direct,x
        cmp     #.loword(F3_UploadPresentDirect)
        bne     @PlanarTextureFormat
        lda     #BSP_UPLOAD_FORMAT_TEXTURE_X3
        bra     @UploadFormatReady
@PlanarTextureFormat:
        lda     #BSP_UPLOAD_FORMAT_TEXTURE
@UploadFormatReady:
        sta     upload_format
.ifdef PLAYABLE_WEAPON_OBJ
        ; Resident weapon tiles free enough VBlank bandwidth for three
        ; equally sized world transfers, with no OBJ CHR DMA on those blanks.
        ldx     #0
        cmp     #BSP_UPLOAD_FORMAT_TEXTURE
        bne     @ObjUploadPlanReady
        lda     upload_slot
        asl
        tay
        lda     slot_weapon_frame,y
        and     #$00ff
        beq     @ObjShortUpload
        cmp     weapon_obj_resident
        beq     @ObjShortUpload
        cmp     weapon_obj_alternate
        bne     @ObjUploadPlanReady
@ObjShortUpload:
        inx
@ObjUploadPlanReady:
        stx     weapon_obj_short_upload
        lda     upload_format
.endif
        cmp     presented_format
        beq     :+
        RW_forced a8i16
.ifndef PLAYABLE_MAP_ID
        lda     runtime_menu_open
        bne     @ReloadFormatMap
.endif
        lda     #inidisp(OFF, DISP_BRIGHTNESS_MIN)
        sta     SFX_inidisp
        sta     INIDISP
.ifndef PLAYABLE_MAP_ID
@ReloadFormatMap:
.endif
        ; Reload the tilemap in its own VBlank before the regular frame DMA.
        lda     upload_format
.ifndef PLAYABLE_MAP_ID
        beq     @ReloadFlatMap
.endif
        cmp     #BSP_UPLOAD_FORMAT_TEXTURE_X3
        bne     @Upload
        VRAM_memcpy VRAM_FLY3_TILEMAP, BSP_CPU_CODE_ADDRESS(Fly3Tilemap), $0800
        jmp     @SoundVBlank
.ifndef PLAYABLE_MAP_ID
@ReloadFlatMap:
        VRAM_memcpy VRAM_TILEMAP, BSP_CPU_CODE_ADDRESS(QuakeBSPTilemap), $0800
        jmp     @SoundVBlank
.endif
:
        RW_forced a8i16
@Upload:
        jsr     TryCommitMetadataUpload
        bcs     @SoundVBlank
        jsr     UploadFrameChunk
@SoundVBlank:
.if BSP_QUAKEC_GAMEPLAY
.ifdef PLAYABLE_WEAPON_OBJ
        jsr     WeaponObjSyncPalette
.else
        lda     quake_restart_pending
        bne     :+
        jsr     ShotgunVBlank
:
.endif
.if .defined(PLAYABLE_MAP_ID) && !.defined(PLAYABLE_WEAPON_OBJ)
        jsr     StatusHudVBlank
.endif
.if .defined(QC_HUB_WARNING_COUNT) && !.defined(PLAYABLE_WEAPON_OBJ)
        jsr     StartWarningVBlank
.endif
.if .defined(PLAYABLE_MAP_ID) && .defined(PLAYABLE_WEAPON_OBJ)
        jsr     StatusHudVBlank
.endif
.endif
        ; Pixel and palette publication are finished for this VBlank.
        RW_forced a8i16
        lda     SFX_inidisp
        sta     INIDISP
        RW_forced a16i16
.ifdef PLAYABLE_WEAPON_OBJ
        lda     weapon_obj_menu_pending
        bne     BSPVBlankInputReady
.endif
.ifndef PLAYABLE_MAP_ID
        lda     runtime_menu_open
        bne     BSPVBlankInputReady
.endif
        RW_forced a8i16
FlyControlsVisible:
.if BSP_QUAKEC_GAMEPLAY && !.defined(QC_QUEUED_INPUT)
        RW_forced a16i16
        lda     quake_restart_pending
        bne     BSPVBlankInputReady
.endif
.if BSP_PLAYER_WALK && !.defined(QC_QUEUED_INPUT)
        RW_forced a16i16
        jsl     WalkPublishPosition
.endif
        jsr     UpdateCameraControls
        RW_forced a16i16
BSPVBlankInputReady:
        GameplayInputEndVBlank
BSPVBlankDone:
        ; Menu exits can arrive here in A16; retain the byte-wide callback
        ; contract for the libSFX epilogue's NMITIMEN and INIDISP writes.
        RW_forced a8i16
.ifdef PLAYABLE_MAP_ID
        plb
.endif
        rtl
.include "quake/RuntimeControls.s"
.if BSP_QUAKEC_GAMEPLAY
.include "quake/QuakeSkill.s"
.endif
.include "Data/QuakeBSPWeaponSprites.i"
.include "quake/WeaponSprites.s"
.ifdef PLAYABLE_WEAPON_OBJ
.include "quake/WeaponObj.s"
  .ifdef PLAYABLE_X3_SOFTWARE_WEAPON
        .include "quake/X3SoftwareWeapon.s"
  .endif
.endif
.include "quake/FrameUpload.s"
.segment "LORAM"
yaw_index:          .res 2
pitch_level:        .res 2
camera_x:           .res 2
camera_y:           .res 2
camera_z:           .res 2
temporal_stage_metadata_only: .res 2
upload_metadata_only: .res 2
slot_metadata_only: .res 4
texture_input_reuse_counter: .res 2
metadata_present_counter: .res 2
technique:          .res 2
; Nonzero selects the dedicated technique-4 renderer. Keeping this writable
; makes the legacy dynamic technique-4 path directly qualifiable in the same
; ROM without changing any feature or camera configuration.
technique4_specialized_path: .res 2
; Zero means general GSUCODE is resident; one means the technique-4 overlays
; are resident. Transition copies happen once at the S-CPU job boundary.
texture_renderer_code_variant: .res 2
texture_colormap_mode: .res 2
texture_phase_overlay_valid: .res 2
.if .defined(PLAYABLE_FLAT_MONOTONE_RASTER) && .defined(PLAYABLE_PAIRED_WORLD_CODE)
flat_monotone_resident: .res 2
.endif
brush_code_valid: .res 2
control_divider:    .res 2
control_revision:   .res 2
runtime_menu_open:  .res 2
runtime_menu_selection: .res 2
runtime_menu_release_gate: .res 2
runtime_menu_restart_action: .res 2
.ifdef PLAYABLE_MAP_ID
runtime_menu_saved_backdrop: .res 2
runtime_menu_saved_inidisp: .res 1
.endif
runtime_menu_draft_playback: .res 2
runtime_menu_draft_technique: .res 2
.ifndef PLAYABLE_MAP_ID
runtime_menu_draft_textures: .res 2
runtime_menu_draft_lighting: .res 2
.else
        .res 4                          ; Preserve following WRAM bindings.
.endif
runtime_menu_draft_brushes: .res 2
runtime_menu_draft_entities: .res 2
.if BSP_QUAKEC_GAMEPLAY
quake_skill_selected: .res 2
quake_skill_active: .res 2
quake_restart_pending: .res 2
.endif
dynamic_brushes_enabled: .res 2
mdl_entities_enabled: .res 2
dynamic_brush_revision: .res 2
brush_visual_state: .res 2
coverage_debug:     .res 2
control_dirty:      .res 2
demo_mode:          .res 2
demo_track_pose:    .res 2
demo_schedule_revision: .res 2
video_tick:         .res 2
staging_scanline:    .res 2
producer_slot:      .res 2
ready_slot:         .res 2
upload_slot:        .res 2
frame_ready:        .res 2
upload_active:      .res 2
upload_target:      .res 2
upload_format:      .res 2
presented_format:   .res 2
upload_palette_mode: .res 2
presented_palette_mode: .res 2
upload_offset:      .res 2
upload_chunk:       .res 2
.ifdef QC_E1M2_DEFER_UPLOAD
upload_defer_budget: .res 2
.endif
stage_frame_required: .res 2
render_counter:     .res 2
present_counter:    .res 2
gsu_job_counter:    .res 2
staging_dma_counter: .res 2
vram_chunk_counter: .res 2
page_flip_counter:  .res 2
video_active:       .res 2
active_leaf:        .res 2
active_pvs_face_count: .res 2
active_pvs_revision: .res 2
active_selection_revision: .res 2
active_pvs_encoded_bytes: .res 2
active_bsp_node_count: .res 2
active_packet_vertex_count: .res 2
active_packet_index_count: .res 2
active_packet_face_count: .res 2
active_packet_plane_count: .res 2
active_packet_overflow_face: .res 2
active_packet_overflow_vertex: .res 2
active_packet_overflow_index: .res 2
active_packet_revision: .res 2
active_packet_camera_revision: .res 2
active_packet_guard_status: .res 2
active_packet_drawable_count: .res 2
active_packet_front_count: .res 2
active_packet_near_count: .res 2
active_packet_screen_count: .res 2
active_packet_painter_node_count: .res 2
active_packet_error: .res 2
active_packet_camera: .res 4
active_packet_camera_q8: .res 6
render_camera:      .res CAMERA_COMMAND_BYTES
render_camera_q8:   .res 6
render_brush_visual_state: .res 2
staging_camera:     .res CAMERA_COMMAND_BYTES
staging_camera_q8:  .res 6
staging_brush_visual_state: .res 2
staging_coverage_mode: .res 2
staging_demo_pose:  .res 2
staging_demo_due_tick: .res 2
staging_demo_epoch: .res 2
overlap_selector_active: .res 2
prefetched_selector_valid: .res 2
slot_camera:        .res CAMERA_COMMAND_BYTES * 2
presented_camera:   .res CAMERA_COMMAND_BYTES
slot_brush_visual_state: .res 4
presented_brush_visual_state: .res 2
slot_coverage_mode: .res 4
presented_coverage_mode: .res 2
render_demo_pose:   .res 2
render_demo_due_tick: .res 2
render_demo_epoch:  .res 2
slot_demo_pose:     .res 4
slot_demo_due_tick: .res 4
slot_demo_epoch:    .res 4
presented_demo_pose: .res 2
presented_weapon_frame: .res 2
presented_demo_due_tick: .res 2
presented_demo_epoch: .res 2
scheduled_frame_camera: .res CAMERA_COMMAND_BYTES
scheduled_frame_camera_q8: .res 6
scheduled_frame_coverage_mode: .res 2
scheduled_frame_brush_visual_state: .res 2
.if BSP_QUAKEC_GAMEPLAY
  .if QC_ENTRANCE_COUNT > 0
render_entrance_variants: .res 4
staging_entrance_variants: .res 4
scheduled_entrance_variants: .res 4
slot_entrance_variants: .res 8
presented_entrance_variants: .res 4
  .endif
  .ifdef QC_EXIT_MOVER_COUNT
.export presented_exit_pose_word
.ifdef QC_SECRET_DOOR_COUNT
render_secret_poses: .res 2*QC_MOVING_DOOR_POSES
render_secret_revision: .res 2
uploaded_secret_revision: .res 2
staging_secret_revision: .res 2
scheduled_secret_revision: .res 2
.endif
render_exit_pose_word: .res 2
render_exit_pose_index: .res 2
staging_exit_pose_word: .res 2
scheduled_exit_pose_word: .res 2
slot_exit_pose_word: .res 4
presented_exit_pose_word: .res 2
    .ifdef PLAYABLE_PACKET_VIEW_REUSE
uploaded_exit_pose_word: .res 2
    .endif
    .if QC_EXIT_MOVER_COUNT > 8
.export presented_exit_pose_word_high
render_exit_pose_word_high: .res 2
staging_exit_pose_word_high: .res 2
scheduled_exit_pose_word_high: .res 2
slot_exit_pose_word_high: .res 4
presented_exit_pose_word_high: .res 2
      .ifdef PLAYABLE_PACKET_VIEW_REUSE
uploaded_exit_pose_word_high: .res 2
      .endif
    .endif
  .endif
.endif
scheduled_frame_valid: .res 2
temporal_alias_raster_identity: .res 2
render_coverage_mode: .res 2
RuntimeMenuBuildX:  .res 2
RuntimeMenuBuildY:  .res 2
RuntimeMenuBuildRow: .res 2
RuntimeMenuBuildColumns: .res 2
RuntimeMenuOAM:     .res 512+32
sky_phase_override_valid: .res 2
sky_phase_override_q16: .res 4
sky_phase_override_float32_valid: .res 2
sky_phase_override_float32: .res 4
.segment "EXRAM"
.if BSP_QUAKEC_GAMEPLAY
.include "quake/QuakeCGameplay.s"
.endif
.ifdef PLAYABLE_SPRITE_STREAM
.if .defined(QC_SECRET_DOOR_COUNT) || .defined(QC_CAMPAIGN_ITEMS)
; The combat VM occupies high WRAM. DMA6 can read the same shadow from low WRAM.
.segment "LORAM"
SpriteStreamColormapStorage: .res SPRITE_STREAM_CACHE_BYTES
SpriteStreamColormapShadow = $7E0000 + .loword(SpriteStreamColormapStorage)
.assert SpriteStreamColormapShadow + SPRITE_STREAM_CACHE_BYTES <= $7E2000, lderror, "Colormap shadow exceeds the low WRAM mirror"
.else
.segment "EXRAM"
SpriteStreamColormapShadow: .res SPRITE_STREAM_CACHE_BYTES
.endif
.assert ^SpriteStreamColormapShadow = ^(SpriteStreamColormapShadow+SPRITE_STREAM_CACHE_BYTES-1), lderror, "Sprite colormap shadow must fit one WRAM DMA bank"
.endif
.segment "HIRAM"
StagedFrame0:       .res BSP_FRAME_STAGE_BYTES
StagedFrame1:       .res BSP_FRAME_STAGE_BYTES
.assert ^StagedFrame0 = ^(StagedFrame1+BSP_FRAME_STAGE_BYTES-1), lderror, "Frame DMA slots must share one WRAM bank"
.ifdef PLAYABLE_POINT_SIGHT_CACHE
  .ifndef PLAYABLE_WEAPON_OBJ
; The source build uses the larger software-weapon staging slots.
.segment "EXRAM"
  .endif
SightTraceCache: .res QC_GRUNT_COUNT*SIGHT_TRACE_ROW_BYTES
.endif
;-------------------------------------------------------------------------------
.segment "RODATA"
BSP_CAMERA_MOVE_TABLES
.segment "BSPDATA"
.segment "BSP_CPU_MAP_PALETTE"
QuakeBSPPalette:
        .incbin "Data/QuakeBSPPalette.bin"
.ifndef PLAYABLE_MAP_ID
.if BSP_QUAKEC_GAMEPLAY
.segment "BSP_CPU_MAP_TILEMAP"
QuakeBSPTilemap: .incbin "Data/QuakeBSPDisplayTilemap.bin"
.else
.segment "BSPDATA"
QuakeBSPTilemap: .incbin "Data/QuakeBSPTilemap.bin"
.endif
.endif
.segment "BSPDATA"
QuakeBSPSin:
        .incbin "Data/QuakeBSPSin.bin"
QuakeBSPCos:
        .incbin "Data/QuakeBSPCos.bin"
.export QuakeBSPReciprocal
QuakeBSPReciprocal:
        .incbin "Data/QuakeBSPReciprocal.bin"
QuakeBSPReciprocalEnd:
.assert QuakeBSPReciprocalEnd - QuakeBSPReciprocal = GSU_RECIPROCAL_BYTES, error, "Projection reciprocal asset has the wrong size"
.assert ^QuakeBSPReciprocal = ^(QuakeBSPReciprocalEnd - 1), lderror, "Projection reciprocal asset crosses a GSU ROM bank"
QuakeBSPExpandLeft:
        .incbin "Data/QuakeBSPExpandLeft.bin"
QuakeBSPExpandRight:
        .incbin "Data/QuakeBSPExpandRight.bin"
; Complete E1M3 world-model archive for runtime BSP/PVS traversal.
; It remains cartridge-resident; the selector stages only the active bounded
; camera packet into GSU RAM.
.segment "BSP_WORLD_VERTICES"
QuakeBSPWorldVertices:
        .incbin "Data/QuakeBSPWorldVertices.bin"
QuakeBSPWorldVerticesEnd:
.assert QuakeBSPWorldVerticesEnd - QuakeBSPWorldVertices = BSP_WORLD_VERTEX_COUNT * BSP_WORLD_VERTEX_RECORD_BYTES, error, "Full-map vertex asset size disagrees with generated counts"
.segment "BSP_WORLD_INDICES_0"
QuakeBSPWorldIndices:
QuakeBSPWorldIndices0:
        .incbin "Data/QuakeBSPWorldIndices0.bin"
QuakeBSPWorldIndices0End:
.assert QuakeBSPWorldIndices0End - QuakeBSPWorldIndices0 = BSP_WORLD_INDICES_0_BYTES, error, "Full-map index head size disagrees with generated constants"
.segment "BSP_WORLD_INDICES_1"
QuakeBSPWorldIndices1:
        .incbin "Data/QuakeBSPWorldIndices1.bin"
QuakeBSPWorldIndices1End:
.assert QuakeBSPWorldIndices1End - QuakeBSPWorldIndices1 = BSP_WORLD_INDICES_1_BYTES, error, "Full-map index tail size disagrees with generated constants"
.segment "BSP_WORLD_FACES"
QuakeBSPWorldFaces:
        .incbin "Data/QuakeBSPWorldFaces.bin"
QuakeBSPWorldFacesEnd:
.assert QuakeBSPWorldFacesEnd - QuakeBSPWorldFaces = BSP_WORLD_FACE_COUNT * BSP_WORLD_FACE_RECORD_BYTES, error, "Full-map face asset size disagrees with generated counts"
.segment "BSP_WORLD_FACE_PLANES"
QuakeBSPWorldFacePlanes:
        .incbin "Data/QuakeBSPWorldFacePlanes.bin"
QuakeBSPWorldFacePlanesEnd:
.assert QuakeBSPWorldFacePlanesEnd - QuakeBSPWorldFacePlanes = BSP_WORLD_FACE_COUNT * BSP_WORLD_FACE_PLANE_RECORD_BYTES, error, "Full-map face-plane asset size disagrees with generated counts"
.segment "BSP_WORLD_NODES"
QuakeBSPWorldNodes:
        .incbin "Data/QuakeBSPWorldNodes.bin"
QuakeBSPWorldNodesEnd:
.assert QuakeBSPWorldNodesEnd - QuakeBSPWorldNodes = BSP_WORLD_NODE_COUNT * BSP_WORLD_NODE_RECORD_BYTES, error, "Full-map node asset size disagrees with generated counts"

.segment "BSP_WORLD_PLANES"
QuakeBSPWorldPlanes:
        .incbin "Data/QuakeBSPWorldPlanes.bin"
QuakeBSPWorldPlanesEnd:
.assert QuakeBSPWorldPlanesEnd - QuakeBSPWorldPlanes = BSP_WORLD_PLANE_COUNT * BSP_WORLD_PLANE_RECORD_BYTES, error, "Full-map plane asset size disagrees with generated counts"
.segment "BSP_WORLD_LEAVES"
QuakeBSPWorldLeaves:
        .incbin "Data/QuakeBSPWorldLeaves.bin"
QuakeBSPWorldLeavesEnd:
.assert QuakeBSPWorldLeavesEnd - QuakeBSPWorldLeaves = BSP_WORLD_LEAF_COUNT * BSP_WORLD_LEAF_RECORD_BYTES, error, "Full-map leaf asset size disagrees with generated counts"
.segment "BSP_WORLD_MARKSURFACES"
QuakeBSPWorldMarkSurfaces:
        .incbin "Data/QuakeBSPWorldMarksurfaces.bin"
QuakeBSPWorldMarkSurfacesEnd:
.assert QuakeBSPWorldMarkSurfacesEnd - QuakeBSPWorldMarkSurfaces = BSP_WORLD_MARKSURFACE_COUNT * BSP_WORLD_MARKSURFACE_RECORD_BYTES, error, "Full-map marksurface asset size disagrees with generated counts"
.segment "BSP_WORLD_VISIBILITY_0"
QuakeBSPWorldVisibility:
QuakeBSPWorldVisibility0:
        .incbin "Data/QuakeBSPWorldVisibility0.bin"
QuakeBSPWorldVisibility0End:
.assert QuakeBSPWorldVisibility0End - QuakeBSPWorldVisibility0 = BSP_WORLD_VISIBILITY_0_BYTES, error, "Full-map visibility head size disagrees with generated constants"
.segment "BSP_WORLD_VISIBILITY_1"
QuakeBSPWorldVisibility1:
        .incbin "Data/QuakeBSPWorldVisibility1.bin"
QuakeBSPWorldVisibility1End:
.assert QuakeBSPWorldVisibility1End - QuakeBSPWorldVisibility1 = BSP_WORLD_VISIBILITY_1_BYTES, error, "Full-map visibility tail size disagrees with generated constants"
.segment "BSP_WORLD_PVS_DIRECTORY"
QuakeBSPWorldPVSDirectory:
        .incbin "Data/QuakeBSPWorldPVSDirectory.bin"
QuakeBSPWorldPVSDirectoryEnd:
.assert QuakeBSPWorldPVSDirectoryEnd - QuakeBSPWorldPVSDirectory = BSP_WORLD_PVS_DIRECTORY_BYTES, error, "Full-map face-PVS directory size disagrees with generated constants"
QuakeBSPWorldPVSGuards:
        .incbin "Data/QuakeBSPWorldPVSGuards.bin"
QuakeBSPWorldPVSGuardsEnd:
.assert QuakeBSPWorldPVSGuards = QuakeBSPWorldPVSDirectory + BSP_WORLD_PVS_DIRECTORY_BYTES, error, "Full-map face-PVS guards moved away from their generated ROM address"
.assert QuakeBSPWorldPVSGuardsEnd - QuakeBSPWorldPVSGuards = BSP_WORLD_PVS_GUARD_BYTES, error, "Full-map face-PVS guard size disagrees with generated constants"
.segment "BSP_WORLD_PVS_0"
QuakeBSPWorldPVS0:
        .incbin "Data/QuakeBSPWorldPVS0.bin"
.segment "BSP_WORLD_PVS_1"
QuakeBSPWorldPVS1:
        .incbin "Data/QuakeBSPWorldPVS1.bin"
.segment "BSP_WORLD_PVS_2"
QuakeBSPWorldPVS2:
        .incbin "Data/QuakeBSPWorldPVS2.bin"
.segment "BSP_WORLD_PVS_3"
QuakeBSPWorldPVS3:
        .incbin "Data/QuakeBSPWorldPVS3.bin"
.segment "BSP_WORLD_PVS_4"
        .incbin "Data/QuakeBSPWorldPVS4.bin"
.assert __BSP_WORLD_PVS_4_LOAD__ = BSP_ROM_LOAD_BSP_WORLD_PVS_4, lderror, "Fly PVS bank 4 moved"
.include "Data/QuakeBSPSkyAssets.s"
.include "Data/QuakeBSPTurbulenceAssets.s"
.include "Data/QuakeBSPSkyFloatPhases.s"
.segment "BSP_WORLD_FACE_OWNERS"
QuakeBSPWorldFaceOwners:
        .incbin "Data/QuakeBSPWorldFaceOwners.bin"
QuakeBSPWorldFaceOwnersEnd:
.assert QuakeBSPWorldFaceOwnersEnd - QuakeBSPWorldFaceOwners = BSP_PHYSICAL_FACE_OWNER_BYTES, error, "Full-map face-owner asset size disagrees with generated counts"
.segment "BSP_WORLD_NODE_PARENTS"
QuakeBSPWorldNodeParents:
        .incbin "Data/QuakeBSPWorldNodeParents.bin"
QuakeBSPWorldNodeParentsEnd:
.assert QuakeBSPWorldNodeParentsEnd - QuakeBSPWorldNodeParents = BSP_WORLD_NODE_COUNT * BSP_WORLD_NODE_PARENT_RECORD_BYTES, error, "Full-map node-parent asset size disagrees with generated counts"
.segment "BSP_WORLD_SHADING"
QuakeBSPWorldShading:
        .incbin "Data/QuakeBSPWorldShading.bin"
QuakeBSPWorldShadingEnd:
.assert QuakeBSPWorldShadingEnd - QuakeBSPWorldShading = BSP_WORLD_SHADING_BYTES, error, "Full-map shading asset size disagrees with generated constants"
.segment "BSP_WORLD_TEXCOORD_0"
QuakeBSPWorldTextureCoordinates0:
        .incbin "Data/QuakeBSPWorldTextureCoordinates0.bin"
QuakeBSPWorldTextureCoordinates0End:
.assert QuakeBSPWorldTextureCoordinates0End - QuakeBSPWorldTextureCoordinates0 = BSP_WORLD_TEXTURE_COORD_0_BYTES, error, "Texture-coordinate bank 0 size disagrees"
.segment "BSP_WORLD_TEXCOORD_1"
QuakeBSPWorldTextureCoordinates1:
        .incbin "Data/QuakeBSPWorldTextureCoordinates1.bin"
QuakeBSPWorldTextureCoordinates1End:
.assert QuakeBSPWorldTextureCoordinates1End - QuakeBSPWorldTextureCoordinates1 = BSP_WORLD_TEXTURE_COORD_1_BYTES, error, "Texture-coordinate bank 1 size disagrees"
.segment "BSP_WORLD_TEXCOORD_2"
QuakeBSPWorldTextureCoordinates2:
        .incbin "Data/QuakeBSPWorldTextureCoordinates2.bin"
QuakeBSPWorldTextureCoordinates2End:
.segment "BSP_WORLD_TEXCOORD_3"
QuakeBSPWorldTextureCoordinates3:
        .incbin "Data/QuakeBSPWorldTextureCoordinates3.bin"
QuakeBSPWorldTextureCoordinates3End:
.assert QuakeBSPWorldTextureCoordinates3End-QuakeBSPWorldTextureCoordinates3 = BSP_WORLD_TEXTURE_COORD_3_BYTES, error, "Level UV3 size"
.ifndef PLAYABLE_WORLD_COORDINATE_STREAM
.if BSP_WORLD_TEXTURE_COORD_2_BYTES
.assert QuakeBSPWorldTextureCoordinates2 = ($82+BSP_WORLD_TEXTURE_COORD_FIRST_GSU_ROM_BANK)*$10000+$8000, lderror, "Level UV2 bank moved"
.endif
.if BSP_WORLD_TEXTURE_COORD_3_BYTES
.assert QuakeBSPWorldTextureCoordinates3 = ($83+BSP_WORLD_TEXTURE_COORD_FIRST_GSU_ROM_BANK)*$10000+$8000, lderror, "Level UV3 bank moved"
.endif
.endif
.segment "BSP_WORLD_TEXTURE_AUX"
QuakeBSPWorldFaceTextureIds:
        .incbin "Data/QuakeBSPWorldFaceTextureIds.bin"
QuakeBSPWorldFaceTextureIdsEnd:
QuakeBSPWorldTextureDirectory:
        .incbin "Data/QuakeBSPWorldTextureDirectory.bin"
QuakeBSPWorldTextureDirectoryEnd:
.assert .loword(QuakeBSPWorldFaceTextureIds) = BSP_WORLD_FACE_TEXTURE_ID_GSU_ROM_ADDRESS, lderror, "World texture IDs moved"
.assert .loword(QuakeBSPWorldTextureDirectory) = BSP_WORLD_TEXTURE_DIRECTORY_GSU_ROM_ADDRESS, lderror, "World texture directory moved"
QuakeBSPTexturePalette:
        .incbin "Data/QuakeBSPTexturePalette.bin"
QuakeBSPTexturePaletteEnd:
        .pushseg
        .segment "BSP_WEAPON_TABLES"
.ifdef PLAYABLE_SHARED_FLASH_PALETTE
QuakeBSPFlashPalette = PLAYABLE_SHARED_FLASH_PALETTE
QuakeBSPFlashPaletteEnd = QuakeBSPFlashPalette + 512
.else
QuakeBSPFlashPalette:
        .incbin "Data/QuakeBSPFlashPalette.bin"
QuakeBSPFlashPaletteEnd:
.endif
        .popseg
.include "quake/TexturelessPalette.s"
.if !(.defined(PLAYABLE_MAP_ID) && .defined(PLAYABLE_WEAPON_OBJ))
QuakeBSPTextureTilemap:
.if BSP_QUAKEC_GAMEPLAY
        .incbin "Data/QuakeBSPTextureDisplayTilemap.bin"
.else
        .incbin "Data/QuakeBSPTextureTilemap.bin"
.endif
QuakeBSPTextureTilemapEnd:
.assert QuakeBSPTextureTilemapEnd - QuakeBSPTextureTilemap = $0800, error, "Exact texture tilemap must be 32x32"
.endif
QuakeBSPTextureCoordinateMap:
        .incbin "Data/QuakeBSPTextureCoordinateMap.bin"
QuakeBSPTextureCoordinateMapEnd:
.assert QuakeBSPWorldTextureCoordinates2End - QuakeBSPWorldTextureCoordinates2 = BSP_WORLD_TEXTURE_COORD_2_BYTES, error, "Texture-coordinate bank 2 size disagrees"
.assert QuakeBSPWorldFaceTextureIdsEnd - QuakeBSPWorldFaceTextureIds = BSP_WORLD_FACE_TEXTURE_ID_BYTES, error, "Face texture-ID size disagrees"
.assert QuakeBSPWorldTextureDirectoryEnd - QuakeBSPWorldTextureDirectory = BSP_WORLD_TEXTURE_DIRECTORY_BYTES, error, "Texture directory size disagrees"
.assert QuakeBSPTexturePaletteEnd - QuakeBSPTexturePalette = 512, error, "Exact texture palette must have 256 colors"
.assert QuakeBSPFlashPaletteEnd - QuakeBSPFlashPalette = 512, error, "Flash scene palette must have 256 colors"
.assert QuakeBSPTextureCoordinateMapEnd - QuakeBSPTextureCoordinateMap = GSU_TEXTURE_COORD_MAP_BYTES, error, "Exact texture coordinate-map size disagrees"
.segment "BSP_WORLD_TEXTURE_0"
        .incbin "Data/QuakeBSPWorldTexturePixels0.bin"
.segment "BSP_WORLD_TEXTURE_1"
        .incbin "Data/QuakeBSPWorldTexturePixels1.bin"
.segment "BSP_WORLD_TEXTURE_2"
        .incbin "Data/QuakeBSPWorldTexturePixels2.bin"
.segment "BSP_WORLD_TEXTURE_3"
        .incbin "Data/QuakeBSPWorldTexturePixels3.bin"
.segment "BSP_WORLD_TEXTURE_4"
        .incbin "Data/QuakeBSPWorldTexturePixels4.bin"
.segment "BSP_WORLD_TEXTURE_5"
        .incbin "Data/QuakeBSPWorldTexturePixels5.bin"
.segment "BSP_WORLD_TEXTURE_6"
        .incbin "Data/QuakeBSPWorldTexturePixels6.bin"
.segment "BSP_WORLD_TEXTURE_7"
        .incbin "Data/QuakeBSPWorldTexturePixels7.bin"
.segment "BSP_WORLD_TEXTURE_8"
        .incbin "Data/QuakeBSPWorldTexturePixels8.bin"
.segment "BSP_WORLD_TEXTURE_9"
        .incbin "Data/QuakeBSPWorldTexturePixels9.bin"
.segment "BSP_WORLD_TEXTURE_10"
        .incbin "Data/QuakeBSPWorldTexturePixels10.bin"
.segment "BSP_WORLD_TEXTURE_11"
        .incbin "Data/QuakeBSPWorldTexturePixels11.bin"
.segment "BSP_WORLD_LIGHTMAP_DIRECTORY"
.if BSP_WORLD_LIGHTMAP_DIRECTORY_BYTES <= BSP_WORLD_ROM_BANK_BYTES
        .incbin "Data/QuakeBSPWorldLightmapDirectory.bin"
.else
        .incbin "Data/QuakeBSPWorldLightmapDirectory.bin", 0, BSP_WORLD_ROM_BANK_BYTES
.segment "BSP_WORLD_LIGHTMAP_DIRECTORY_TAIL"
        .incbin "Data/QuakeBSPWorldLightmapDirectory.bin", BSP_WORLD_ROM_BANK_BYTES
.endif
.segment "BSP_WORLD_LIGHTMAP_0"
        .incbin "Data/QuakeBSPWorldLightmapSamples0.bin"
.segment "BSP_WORLD_LIGHTMAP_1"
        .incbin "Data/QuakeBSPWorldLightmapSamples1.bin"
.segment "BSP_WORLD_LIGHTMAP_2"
        .incbin "Data/QuakeBSPWorldLightmapSamples2.bin"
.segment "BSP_WORLD_LIGHTMAP_3"
        .incbin "Data/QuakeBSPWorldLightmapSamples3.bin"
.if BSP_WORLD_LIGHTMAP_CHUNK_COUNT > 4
.segment "BSP_WORLD_LIGHTMAP_4"
        .incbin "Data/QuakeBSPWorldLightmapSamples4.bin"
.endif
.segment "BSP_LIGHTMAP_COLORMAPS"
QuakeBSPLightmapLevelZeroColormap:
        .incbin "Data/QuakeBSPLightmapLevelZeroColormap.bin"
QuakeBSPLightmapLevelZeroColormapEnd:
.assert QuakeBSPLightmapLevelZeroColormapEnd - QuakeBSPLightmapLevelZeroColormap = 256, error, "Quake lightmap level-zero colormap must contain 256 indices"
QuakeBSPLightmapColormap:
        .incbin "Data/QuakeBSPLightmapColormap.bin"
QuakeBSPLightmapColormapEnd:
.assert QuakeBSPLightmapColormapEnd - QuakeBSPLightmapColormap = GSU_LIGHTMAP_COLORMAP_BYTES, error, "Natural lightmap colormap size disagrees"
.include "quake/DivideQ12ReciprocalAssets.s"
.include "quake/FlyMouseState.s"
.include "quake/CameraAngles.s"
.include "quake/DynamicBrushAssets.s"
.ifndef PLAYABLE_EMPTY_COMPOSED
.include "Data/QuakeBSPComposedCacheAssets.s"
.endif
.include "Data/QuakeBSPAliasAssets.s"
.include "Data/QuakeBSPAliasVisibility.s"
.segment "BSP_COLLISION_PACKED_0"
QuakeBSPCollisionPacked0:
        .incbin "Data/QuakeBSPCollisionPacked0.bin"
QuakeBSPCollisionPacked0End:
.assert QuakeBSPCollisionPacked0End - QuakeBSPCollisionPacked0 = BSP_COLLISION_PACKED_0_BYTES, error, "Fly collision payload chunk 0 size disagrees"
.segment "BSP_COLLISION_PACKED_1"
QuakeBSPCollisionPacked1:
        .incbin "Data/QuakeBSPCollisionPacked1.bin"
QuakeBSPCollisionPacked1End:
.assert QuakeBSPCollisionPacked1End - QuakeBSPCollisionPacked1 = BSP_COLLISION_PACKED_1_BYTES, error, "Fly collision payload chunk 1 size disagrees"
.include "Data/QuakeBSPSoundtrackAssets.s"
.assert BSP_SOUND_ENABLED = 0, error, "Legacy demo soundtrack playback is unavailable"
.if BSP_QUAKEC_GAMEPLAY
.include "quake/ShotgunPresentation.s"
.ifdef PLAYABLE_MAP_ID
.include "quake/StatusHud.s"
.endif
.ifdef QC_HUB_WARNING_COUNT
.include "quake/StartWarning.s"
.endif
.endif
.include "quake/FramePipelineState.s"
