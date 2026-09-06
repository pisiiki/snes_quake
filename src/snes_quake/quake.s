; Flyable E1M3 BSP and demo1 benchmark for Super FX 3.
.include "libSFX.i"
.include "SNES_FX3.i"
.include "MemoryMap.i"
.include "quake/SoundJoin.i"
GSU_RENDER_BASE    = $700000
GSU_DATA_BASE      = $710000
GSU_OUTPUT         = GSU_RENDER_BASE + GSU_OUTPUT_OFFSET
GSU_VERTICES       = GSU_DATA_BASE + GSU_VERTICES_OFFSET
GSU_INDICES        = GSU_DATA_BASE + GSU_INDICES_OFFSET
GSU_FACES          = GSU_DATA_BASE + GSU_FACES_OFFSET
GSU_FACE_PLANES    = GSU_DATA_BASE + GSU_FACE_PLANES_OFFSET
GSU_SIN             = GSU_DATA_BASE + GSU_SIN_OFFSET
GSU_COS             = GSU_DATA_BASE + GSU_COS_OFFSET
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
VRAM_TEXTURE_TILES_A = $0000
VRAM_TEXTURE_TILES_B = $4000
VRAM_TEXTURE_TILEMAP = $F000
VRAM_RUNTIME_MENU_TILES = $7800
VRAM_RUNTIME_MENU_OBJ_BASE = $4000
RUNTIME_MENU_ASCII_FIRST = 32
RUNTIME_MENU_ASCII_LAST = 90
RUNTIME_MENU_FONT_TILE_COUNT = RUNTIME_MENU_ASCII_LAST - RUNTIME_MENU_ASCII_FIRST + 1
RUNTIME_MENU_FONT_BYTES = RUNTIME_MENU_FONT_TILE_COUNT * 32
RUNTIME_MENU_TILE_BASE = $1C0
CAMERA_COMMAND_WORDS = 8
CAMERA_COMMAND_BYTES = CAMERA_COMMAND_WORDS * 2
BSP_UPLOAD_FORMAT_FLAT = 0
BSP_UPLOAD_FORMAT_TEXTURE = 1
BSP_STAGING_FLAT_LIMIT = 49
BSP_STAGING_TEXTURE_LIMIT = 132
BSP_WORLD_ROM_BANK_BYTES = $8000
BSP_VERIFY_NEAR_DEMO_POSE = BSP_DEMO_VERIFY_NEAR_POSE
BSP_VERIFY_FAR_DEMO_POSE = BSP_DEMO_VERIFY_FAR_POSE
BSP_VERIFY_NEAR_DEMO_OFFSET = BSP_VERIFY_NEAR_DEMO_POSE * BSP_DEMO_PRECISE_TRACK_RECORD_BYTES
BSP_VERIFY_FAR_DEMO_OFFSET = BSP_VERIFY_FAR_DEMO_POSE * BSP_DEMO_PRECISE_TRACK_RECORD_BYTES
BSP_BRUSH_ROWSTATE_CPU_ADDRESS = (BSP_BRUSH_ROWSTATE_BANK + $80) * $10000 + BSP_BRUSH_ROWSTATE_ADDRESS
BSP_BRUSH_FLYSTATE_CPU_ADDRESS = (BSP_BRUSH_FLYSTATE_BANK + $80) * $10000 + BSP_BRUSH_FLYSTATE_ADDRESS
.assert __GSUCODE_SIZE__ <= GSU_CODE_CAPACITY, lderror, "GSU BSP code exceeds bank-$70 partition"
.assert .loword(__GSUCODE_RUN__) = GSU_CODE_OFFSET, lderror, "GSU BSP code address disagrees with MemoryMap.i"
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
.assert __GSU_AUX_CODE_LOAD__ = $828000, lderror, "Auxiliary GSU code moved out of ROM2"
.assert __GSU_BRUSH_CODE_SIZE__ <= GSU_BRUSH_CODE_CAPACITY, lderror, "Dynamic-brush GSU overlay exceeds bank-$70 partition"
.assert .loword(__GSU_BRUSH_CODE_RUN__) = GSU_BRUSH_CODE_OFFSET, lderror, "Dynamic-brush GSU overlay address disagrees with MemoryMap.i"
.assert __GSU_BRUSH_CODE_LOAD__ = $BF8000, lderror, "Dynamic-brush GSU overlay moved out of ROM63"
.assert __GSU_BRUSH_CODE_RUN__ + __GSU_BRUSH_CODE_SIZE__ <= __GSU_ALIAS_FLY_CODE_RUN__, lderror, "Dynamic-brush overlay overlaps deferred fly alias code"
.assert __GSU_ALIAS_FLY_CODE_SIZE__ <= GSU_ALIAS_FLY_CODE_CAPACITY, lderror, "Fly alias GSU overlay exceeds the brush-code tail"
.assert .loword(__GSU_ALIAS_FLY_CODE_RUN__) = GSU_ALIAS_FLY_CODE_OFFSET, lderror, "Fly alias GSU overlay moved away from the brush-code tail"
.assert ^__GSU_ALIAS_FLY_CODE_LOAD__ = $BF, lderror, "Fly alias GSU overlay moved out of ROM63"
.assert __GSU_TEXTURE_TAIL_CODE_SIZE__ <= GSU_TEXTURE_TAIL_CODE_CAPACITY, lderror, "Texture-tail GSU helper exceeds hidden scanlines"
.assert .loword(__GSU_TEXTURE_TAIL_CODE_RUN__) = GSU_TEXTURE_TAIL_CODE_OFFSET, lderror, "Texture-tail GSU helper address disagrees with MemoryMap.i"
.assert ^__GSU_TEXTURE_TAIL_CODE_LOAD__ = $BF, lderror, "Texture-tail GSU helper moved out of ROM63"
.assert __GSU_TURBULENCE_HOT_CODE_SIZE__ <= GSU_TURBULENCE_HOT_CODE_CAPACITY, lderror, "Turbulence sampler exceeds the reciprocal-mirror tail"
.assert .loword(__GSU_TURBULENCE_HOT_CODE_RUN__) = GSU_TURBULENCE_HOT_CODE_OFFSET, lderror, "Turbulence sampler address disagrees with MemoryMap.i"
.assert ^__GSU_TURBULENCE_HOT_CODE_LOAD__ = $82, lderror, "Turbulence sampler moved out of ROM2"
.assert ^__GSU_LIGHTMAP_UNPACK_ROM_CODE_LOAD__ = $A4, lderror, "Six-bit lightmap unpacker moved out of ROM36"
.assert __GSU_LIGHTMAP_UNPACK_ROM_CODE_LOAD__ >= __BSP_WORLD_LIGHTMAP_3_LOAD__ + __BSP_WORLD_LIGHTMAP_3_SIZE__, lderror, "Six-bit lightmap unpacker overlaps packed samples"
.assert __GSU_LIGHTMAP_UNPACK_ROM_CODE_SIZE__ <= 512, lderror, "Six-bit lightmap unpacker exceeds one GSU cache window"
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
.assert BSP_WORLD_FACE_COUNT * BSP_WORLD_FACE_OWNER_RECORD_BYTES <= BSP_WORLD_ROM_BANK_BYTES, error, "Full-map face owners exceed one ROM bank"
.assert BSP_WORLD_NODE_COUNT * BSP_WORLD_NODE_PARENT_RECORD_BYTES <= BSP_WORLD_ROM_BANK_BYTES, error, "Full-map node parents exceed one ROM bank"
.assert BSP_WORLD_SHADING_BYTES = BSP_WORLD_FACE_COUNT * BSP_WORLD_SHADING_RECORD_BYTES + BSP_WORLD_SHADING_DISTANCE_LUT_BYTES + BSP_WORLD_SHADING_TABLE_BYTES, error, "Full-map shading counts disagree"
.assert BSP_WORLD_SHADING_BYTES <= BSP_WORLD_ROM_BANK_BYTES, error, "Full-map shading exceeds one ROM bank"
.assert BSP_WORLD_TEXTURE_COORD_BYTES = BSP_WORLD_INDEX_COUNT * BSP_WORLD_TEXTURE_COORD_RECORD_BYTES, error, "Exact texture coordinates disagree with world indices"
.assert BSP_WORLD_TEXTURE_COORD_0_BYTES <= BSP_WORLD_ROM_BANK_BYTES, error, "Texture-coordinate bank 0 exceeds its ROM bank"
.assert BSP_WORLD_TEXTURE_COORD_1_BYTES <= BSP_WORLD_ROM_BANK_BYTES, error, "Texture-coordinate bank 1 exceeds its ROM bank"
.assert BSP_WORLD_TEXTURE_COORD_2_BYTES < BSP_WORLD_ROM_BANK_BYTES, error, "Texture-coordinate bank 2 must leave room for auxiliary assets"
.assert BSP_WORLD_FACE_TEXTURE_ID_BYTES = BSP_WORLD_FACE_COUNT, error, "Face texture IDs lost world-face identity"
.assert BSP_WORLD_TEXTURE_DIRECTORY_BYTES = BSP_WORLD_TEXTURE_COUNT * BSP_WORLD_TEXTURE_DIRECTORY_RECORD_BYTES, error, "Exact texture directory count disagrees"
.assert BSP_WORLD_TEXTURE_PIXEL_CHUNK_COUNT = 6, error, "Exact E1M3 texture bank layout changed"
.assert BSP_WORLD_LIGHTMAP_DIRECTORY_BYTES = BSP_WORLD_FACE_COUNT * BSP_WORLD_LIGHTMAP_DIRECTORY_RECORD_BYTES, error, "Lightmap directory lost world-face identity"
.assert BSP_WORLD_LIGHTMAP_DIRECTORY_BYTES <= BSP_WORLD_ROM_BANK_BYTES, error, "Lightmap directory exceeds one ROM bank"
.assert BSP_WORLD_LIGHTMAP_CHUNK_COUNT <= 4, error, "World lightmaps exceed their ROM bank reservation"
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
.assert BSP_WORLD_PVS_CHUNK_COUNT <= 4, error, "Full-map face-PVS data exceeds its ROM bank reservation"
.assert BSP_VERIFY_NEAR_DEMO_OFFSET < BSP_DEMO_PRECISE_TRACK_BYTES, error, "Static near verifier pose escapes demo1"
.assert BSP_VERIFY_FAR_DEMO_OFFSET < BSP_DEMO_PRECISE_TRACK_BYTES, error, "Static far verifier pose escapes demo1"
.assert BSP_DEMO_PRECISE_TIMING_BYTES = BSP_DEMO_PRECISE_TRACK_POSE_COUNT * BSP_DEMO_PRECISE_TIMING_RECORD_BYTES, error, "demo1 precise timing count disagrees with track"
.assert BSP_DEMO_PRECISE_SAMPLE_RATE_HZ = BSP_DEMO_STEP_SAMPLE_RATE_HZ * BSP_DEMO_ORDERED_POSE_STRIDE, error, "demo1 step rate does not divide the canonical rate"
.assert BSP_DEMO_PRECISE_TRACK_BYTES <= BSP_WORLD_ROM_BANK_BYTES, error, "configured demo track exceeds one ROM bank"
.assert BSP_DEMO_PRECISE_TIMING_BYTES <= BSP_WORLD_ROM_BANK_BYTES, error, "configured demo timing exceeds one ROM bank"
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
.assert __BSP_DEMO_TIMING_LOAD__ = $838000, lderror, "configured demo timing moved out of ROM3"
.assert __BSP_WORLD_VERTICES_LOAD__ = $848000, lderror, "Full-map vertices moved out of ROM4"
.assert __BSP_WORLD_INDICES_0_LOAD__ = $858000, lderror, "Full-map index head moved out of ROM5"
.assert __BSP_WORLD_INDICES_1_LOAD__ = $868000, lderror, "Full-map index tail moved out of ROM6"
.assert __BSP_WORLD_FACES_LOAD__ = $878000, lderror, "Full-map faces moved out of ROM7"
.assert __BSP_WORLD_FACE_PLANES_LOAD__ = $888000, lderror, "Full-map face planes moved out of ROM8"
.assert __BSP_WORLD_NODES_LOAD__ = $898000, lderror, "Full-map nodes moved out of ROM9"
.assert __BSP_WORLD_PLANES_LOAD__ = $8A8000, lderror, "Full-map planes moved out of ROM10"
.assert __BSP_WORLD_LEAVES_LOAD__ = $8B8000, lderror, "Full-map leaves moved out of ROM11"
.assert __BSP_WORLD_MARKSURFACES_LOAD__ = $8C8000, lderror, "Full-map marksurfaces moved out of ROM12"
.assert __BSP_WORLD_VISIBILITY_0_LOAD__ = $8D8000, lderror, "Full-map visibility head moved out of ROM13"
.assert __BSP_WORLD_VISIBILITY_1_LOAD__ = $8E8000, lderror, "Full-map visibility tail moved out of ROM14"
.assert __BSP_WORLD_PVS_DIRECTORY_LOAD__ = $800000 + BSP_WORLD_PVS_DIRECTORY_ROM_BANK * $10000 + BSP_WORLD_PVS_DIRECTORY_ROM_ADDRESS, lderror, "Face-PVS directory disagrees with generated address"
.assert __BSP_WORLD_PVS_DIRECTORY_LOAD__ = ((__BSP_WORLD_PVS_2_LOAD__ + __BSP_WORLD_PVS_2_SIZE__ + 7) & $FFFFF8), lderror, "Face-PVS directory must follow aligned PVS2"
.assert BSP_WORLD_PVS_GUARD_ROM_ADDRESS + BSP_WORLD_PVS_GUARD_BYTES <= $10000, error, "Face-PVS guards cross bank 18"
.assert __BSP_WORLD_PVS_0_LOAD__ = $908000, lderror, "Full-map face-PVS chunk 0 moved out of ROM16"
.assert __BSP_WORLD_PVS_1_LOAD__ = $918000, lderror, "Full-map face-PVS chunk 1 moved out of ROM17"
.assert __BSP_WORLD_PVS_2_LOAD__ = $928000, lderror, "Full-map face-PVS chunk 2 moved out of ROM18"
.assert __BSP_WORLD_PVS_3_LOAD__ = $938000, lderror, "Full-map face-PVS chunk 3 moved out of ROM19"
.assert __BSP_DEMO_TRACK_LOAD__ = __BSP_WORLD_PVS_3_LOAD__ + __BSP_WORLD_PVS_3_SIZE__, lderror, "configured demo track no longer follows face-PVS chunk 3"
.assert __BSP_WORLD_FACE_OWNERS_LOAD__ = $948000, lderror, "Full-map face owners moved out of ROM20"
.assert __BSP_WORLD_NODE_PARENTS_LOAD__ = $958000, lderror, "Full-map node parents moved out of ROM21"
.assert __BSP_WORLD_SHADING_LOAD__ = $968000, lderror, "Full-map shading moved out of ROM22"
.assert __BSP_WORLD_TEXCOORD_0_LOAD__ = $978000, lderror, "Texture coordinates moved out of ROM23"
.assert __BSP_WORLD_TEXCOORD_1_LOAD__ = $988000, lderror, "Texture coordinates moved out of ROM24"
.assert __BSP_WORLD_TEXTURE_AUX_LOAD__ = $998000, lderror, "Texture auxiliary data moved out of ROM25"
.assert __BSP_WORLD_TEXTURE_AUX_SIZE__ <= BSP_WORLD_ROM_BANK_BYTES, lderror, "Texture auxiliary data exceeds ROM25"
.assert __BSP_WORLD_TEXTURE_0_LOAD__ = $9A8000, lderror, "Exact texture bank 0 moved"
.assert __BSP_WORLD_TEXTURE_1_LOAD__ = $9B8000, lderror, "Exact texture bank 1 moved"
.assert __BSP_WORLD_TEXTURE_2_LOAD__ = $9C8000, lderror, "Exact texture bank 2 moved"
.assert __BSP_WORLD_TEXTURE_3_LOAD__ = $9D8000, lderror, "Exact texture bank 3 moved"
.assert __BSP_WORLD_TEXTURE_4_LOAD__ = $9E8000, lderror, "Exact texture bank 4 moved"
.assert __BSP_WORLD_TEXTURE_5_LOAD__ = $9F8000, lderror, "Exact texture bank 5 moved"
.assert __BSP_WORLD_LIGHTMAP_DIRECTORY_LOAD__ = $A08000, lderror, "Lightmap directory moved out of ROM32"
.assert __BSP_WORLD_LIGHTMAP_0_LOAD__ = $A18000, lderror, "Lightmap bank 0 moved"
.assert __BSP_WORLD_LIGHTMAP_1_LOAD__ = $A28000, lderror, "Lightmap bank 1 moved"
.assert __BSP_WORLD_LIGHTMAP_2_LOAD__ = $A38000, lderror, "Lightmap bank 2 moved"
.assert __BSP_WORLD_LIGHTMAP_3_LOAD__ = $A48000, lderror, "Lightmap bank 3 moved"
.assert __BSP_LIGHTMAP_COLORMAPS_LOAD__ = __BSP_DEMO_TIMING_LOAD__ + __BSP_DEMO_TIMING_SIZE__, lderror, "Lightmap colormaps no longer follow demo timing"
.assert __BSP_DIVIDE_Q12_RECIPROCAL_0_LOAD__ = $A68000, lderror, "Q12 reciprocal bank 0 moved"
.assert __BSP_DIVIDE_Q12_RECIPROCAL_1_LOAD__ = $A78000, lderror, "Q12 reciprocal bank 1 moved"
.assert __BSP_DIVIDE_Q12_RECIPROCAL_2_LOAD__ = $A88000, lderror, "Q12 reciprocal bank 2 moved"
.assert __BSP_DIVIDE_Q12_RECIPROCAL_3_LOAD__ = $A98000, lderror, "Q12 reciprocal bank 3 moved"
.assert __BSP_COLLISION_PACKED_0_LOAD__ = $C00000, lderror, "Fly collision payload chunk 0 moved"
.assert __BSP_COLLISION_PACKED_1_LOAD__ = $C08000, lderror, "Fly collision payload chunk 1 moved"
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
.assert __BSP_WORLD_PVS_3_SIZE__ + __BSP_DEMO_TRACK_SIZE__ <= BSP_WORLD_ROM_BANK_BYTES, lderror, "Face-PVS chunk 3 and configured demo track exceed ROM19"
.assert __BSP_DEMO_TRACK_SIZE__ = BSP_DEMO_PRECISE_TRACK_BYTES, lderror, "configured demo track segment has the wrong size"
.assert __BSP_DEMO_TRACK_SIZE__ <= BSP_WORLD_ROM_BANK_BYTES, lderror, "configured demo track exceeds its ROM bank"
.assert __BSP_DEMO_TIMING_SIZE__ = BSP_DEMO_PRECISE_TIMING_BYTES+BSP_SKY_PHASE_BYTES+BSP_TURBULENCE_PHASE_BYTES+BSP_TURBULENCE_TABLE_BYTES, lderror, "configured demo timing/special-phase segment has the wrong size"
.assert __BSP_DEMO_TIMING_SIZE__ + __BSP_LIGHTMAP_COLORMAPS_SIZE__ <= BSP_WORLD_ROM_BANK_BYTES, lderror, "Demo timing and lightmap colormaps exceed ROM3"
.assert __BSP_DEMO_TIMING_SIZE__ <= BSP_WORLD_ROM_BANK_BYTES, lderror, "configured demo timing exceeds its ROM bank"
.assert __BSP_COLLISION_PACKED_0_SIZE__ = BSP_COLLISION_PACKED_0_BYTES, lderror, "Fly collision payload chunk 0 has the wrong size"
.assert __BSP_COLLISION_PACKED_1_SIZE__ = BSP_COLLISION_PACKED_1_BYTES, lderror, "Fly collision payload chunk 1 has the wrong size"
.assert __BSP_WORLD_FACE_OWNERS_SIZE__ = BSP_WORLD_FACE_COUNT * BSP_WORLD_FACE_OWNER_RECORD_BYTES, lderror, "Full-map face-owner segment has the wrong size"
.assert __BSP_WORLD_NODE_PARENTS_SIZE__ = BSP_WORLD_NODE_COUNT * BSP_WORLD_NODE_PARENT_RECORD_BYTES, lderror, "Full-map node-parent segment has the wrong size"
.assert __BSP_WORLD_SHADING_SIZE__ = BSP_WORLD_SHADING_BYTES, lderror, "Full-map shading segment has the wrong size"
.assert __BSP_WORLD_TEXCOORD_0_SIZE__ = BSP_WORLD_TEXTURE_COORD_0_BYTES, lderror, "Texture-coordinate bank 0 has the wrong size"
.assert __BSP_WORLD_TEXCOORD_1_SIZE__ = BSP_WORLD_TEXTURE_COORD_1_BYTES, lderror, "Texture-coordinate bank 1 has the wrong size"
.assert __BSP_WORLD_LIGHTMAP_DIRECTORY_SIZE__ = BSP_WORLD_LIGHTMAP_DIRECTORY_BYTES, lderror, "Lightmap directory segment has the wrong size"
.assert __BSP_WORLD_LIGHTMAP_0_SIZE__ <= BSP_WORLD_ROM_BANK_BYTES, lderror, "Lightmap bank 0 exceeds its ROM bank"
.assert __BSP_WORLD_LIGHTMAP_1_SIZE__ <= BSP_WORLD_ROM_BANK_BYTES, lderror, "Lightmap bank 1 exceeds its ROM bank"
.assert __BSP_WORLD_LIGHTMAP_2_SIZE__ <= BSP_WORLD_ROM_BANK_BYTES, lderror, "Lightmap bank 2 exceeds its ROM bank"
.assert __BSP_WORLD_LIGHTMAP_3_SIZE__ <= BSP_WORLD_ROM_BANK_BYTES, lderror, "Lightmap bank 3 exceeds its ROM bank"
.assert __BSP_LIGHTMAP_COLORMAPS_SIZE__ <= BSP_WORLD_ROM_BANK_BYTES, lderror, "Lightmap colormaps exceed their ROM bank"
.assert __BSP_DIVIDE_Q12_RECIPROCAL_0_SIZE__ = BSP_WORLD_ROM_BANK_BYTES, lderror, "Q12 reciprocal bank 0 has the wrong size"
.assert __BSP_DIVIDE_Q12_RECIPROCAL_1_SIZE__ = BSP_WORLD_ROM_BANK_BYTES, lderror, "Q12 reciprocal bank 1 has the wrong size"
.assert __BSP_DIVIDE_Q12_RECIPROCAL_2_SIZE__ = BSP_WORLD_ROM_BANK_BYTES, lderror, "Q12 reciprocal bank 2 has the wrong size"
.assert __BSP_DIVIDE_Q12_RECIPROCAL_3_SIZE__ = $7FFC, lderror, "Q12 reciprocal bank 3 has the wrong size"
; These assets always cross distinct banks, so a forward MVN is overlap-safe.
; Avoid memcpy's low-word-only overlap heuristic selecting a backward MVP.
.macro BSP_STATIC_COPY dest, source, length
        RW_push set:a16i16
        phb
        lda     #length-1
        ldx     #.loword(source)
        ldy     #.loword(dest)
        mvn     #^(source), #^(dest)
        plb
        RW_pull
.endmacro
.include "quake/SkyRenderer.s"
.include "quake/TurbulenceRenderer.s"
.include "quake/AliasAnimation.s"
; FX3 keeps the S-CPU and NMI serviceable while RON/RAN own cartridge buses.
.segment "RODATA"
QuakeBSPEdgeDivideCacheInitial:
        .res    GSU_TEXTURE_EDGE_DIVIDE_CACHE_BYTES, 0
QuakeBSPEdgeDivideCacheInitialEnd:
.assert QuakeBSPEdgeDivideCacheInitialEnd - QuakeBSPEdgeDivideCacheInitial = GSU_TEXTURE_EDGE_DIVIDE_CACHE_BYTES, error, "Edge reciprocal cache initializer has the wrong size"
.segment "CODE"
Main:
        CPU_init
        REG_init
        BSP_STATIC_COPY __GSUCODE_RUN__, __GSUCODE_LOAD__+BSP_SOUND_CPU_MIRROR_DELTA, __GSUCODE_SIZE__
        BSP_STATIC_COPY __GSU_AUX_CODE_RUN__, __GSU_AUX_CODE_LOAD__, __GSU_AUX_CODE_SIZE__
        BSP_STATIC_COPY __GSU_BRUSH_CODE_RUN__, __GSU_BRUSH_CODE_LOAD__, __GSU_BRUSH_CODE_SIZE__
        BSP_STATIC_COPY __GSU_TEXTURE_TAIL_CODE_RUN__, __GSU_TEXTURE_TAIL_CODE_LOAD__, __GSU_TEXTURE_TAIL_CODE_SIZE__
        jsr     StageStaticAssets
        ; StageStaticAssets fills the Q12 mirror through $8BFF, including the
        ; sampler's reserved $8B00 tail. Install the sampler only afterward.
        RW_forced a16i16
        BSP_STATIC_COPY __GSU_TURBULENCE_HOT_CODE_RUN__, __GSU_TURBULENCE_HOT_CODE_LOAD__, __GSU_TURBULENCE_HOT_CODE_SIZE__
        lda     #BSP_START_YAW_INDEX
        sta     yaw_index
        stz     pitch_level
        lda     #BSP_WORLD_START_X_Q8
        sta     camera_x
        lda     #BSP_WORLD_START_Y_Q8
        sta     camera_y
        lda     #BSP_WORLD_START_Z_Q8
        sta     camera_z
        stz     control_divider
        stz     control_revision
        stz     coverage_debug
        stz     render_coverage_mode
        stz     scheduled_frame_valid
        stz     scheduled_frame_coverage_mode
        stz     scheduled_frame_brush_visual_state
        lda     #$0001
        sta     temporal_reuse_enabled
        sta     demo_mode
        sta     demo_schedule
        stz     demo_playback_rate_shift
        stz     boot_fixed_step_sample
        stz     boot_ordered_source_pose
        lda     #BSP_DEMO_ORDERED_POSE_STRIDE
        sta     demo_ordered_pose_stride
        stz     demo_offset
        stz     demo_timing_offset
        stz     demo_next_pose
        stz     demo_track_pose
        stz     demo_pose_due_tick
        stz     demo_pose_counter
        stz     demo_source_due_counter
        stz     demo_coalesced_counter
        stz     demo_playhead_tick
        stz     demo_playhead_origin
        stz     demo_schedule_revision
        stz     demo_loop_counter
        stz     video_tick
        stz     staging_scanline
        lda     #$FFFF
        sta     monster_camera_index
        lda     #$0004
        sta     technique
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
        stz     runtime_menu_saved_playhead_tick
        stz     runtime_menu_apply_flags
        stz     runtime_menu_draft_playback
        lda     #$0004
        sta     runtime_menu_draft_technique
        lda     #$0001
        sta     runtime_menu_draft_textures
        lda     #$0001
        sta     runtime_menu_draft_lighting
        lda     #BSP_BRUSH_DYNAMIC_REPLAY_SUPPORTED
        sta     dynamic_brushes_enabled
        sta     runtime_menu_draft_brushes
        lda     #BSP_ALIAS_ENTITY_SUPPORTED
        sta     mdl_entities_enabled
        sta     runtime_menu_draft_entities
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
        jsr     ApplyBootParameters
        ; Runtime state is authoritative. Derive every menu draft only after
        ; optional frame-zero overrides have been applied and before InitVideo
        ; builds the first OAM image.
        jsr     SyncRuntimeMenuDrafts
        lda     demo_mode
        beq     :+
        jsr     RestartDemoPlayback
:
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
        jsr     RenderFrame
        ; A configured flat startup render is asynchronous. Its output must be
        ; complete before the first snapshot and DMA, just like textured boot.
        FX3_JOB_JOIN
StartupRendererOutputReady:
        jsr     SnapshotRenderedFrameForStage
        jsr     StageExpandedFrame
        jsr     InitVideo
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
        jsr     AdvanceDemoAfterStage
        RW      a8
        VBL_set BSPVBlank
        lda     RDNMI                   ; Drop any VBlank latched during startup.
        VBL_on
        lda     #$01
        sta     video_active
        stz     video_active+1
        lda     #inidisp(ON, DISP_BRIGHTNESS_MAX)
        sta     SFX_inidisp
.include "quake/SoundInit.s"
.include "quake/SoundMainLoop.s"
        lda     runtime_menu_open
        beq     :+
        stz     prefetched_selector_valid
        BSP_SOUND_WAIT_FRAME
        bra     MainLoop
:
        jsr     RenderFrame
RenderFrameComplete:
        ; RenderFrame returns with M=0; keep assembler/runtime width aligned.
        RW_forced a16i16
        ; Cache warm-up needs the GSU-overlap service inside RenderFrame, but
        ; the held ordered pose must not become another presentation.
        BSP_SOUND_HOLD_DEMO DiscardHeldOrderedFrame
        lda     runtime_menu_open
        beq     :+
        stz     stage_frame_required
        stz     prefetched_selector_valid
        BSP_SOUND_WAIT_FRAME
        bra     MainLoop
:
        lda     stage_frame_required
        bne     CheckRenderedRevision
        lda     control_revision
        cmp     render_camera+12
        beq     @IdleVisible
        ; VBlank may have changed controls after RenderFrame found the prior
        ; identity current. Re-enter the renderer before sleeping so the newly
        ; visible command cannot wait for another interrupt edge.
        bra     MainLoop
@IdleVisible:
        ; VBlank still advances input/demo time and wakes changed commands.
PresentationBoundaryWait:
        BSP_SOUND_WAIT_FRAME
        bra     MainLoop
CheckRenderedRevision:
        lda     demo_schedule_revision
        cmp     render_demo_epoch
        bne     @DiscardRenderedFrame
        lda     demo_mode
        beq     @WaitForQueue
        lda     demo_schedule
        bne     @WaitForQueue
        lda     control_revision
        cmp     render_camera+12
        beq     @WaitForQueue
@DiscardRenderedFrame:
        ; Only step playback may discard ordinary camera revisions.
        stz     stage_frame_required
        jmp     MainLoop

@WaitForQueue:
        lda     frame_ready
        bne     @WaitForQueue
        lda     runtime_menu_open
        beq     :+
        stz     stage_frame_required
        BSP_SOUND_WAIT_FRAME
        jmp     MainLoop
:
@StageFrame:
        ; Snapshot N before StageCommand may publish N+1. Starting the selector
        ; before the safe-window wait keeps NMI/input live while either the
        ; selector or the PPU scanline gate is the longer operation.
        jsr     SnapshotRenderedFrameForStage
        lda     demo_schedule_revision
        cmp     staging_demo_epoch
        beq     :+
        jmp     DiscardStaleFrameBeforeSelector
:
        jsr     AdvanceDemoAfterStage
        ; Preserve the flat-render overlap through queue and snapshot work,
        ; then close it before publishing the next selector command.
        BSP_SOUND_FX3_JOB_JOIN
RendererOutputReady:
        jsr     TryStartOverlappedSelector
        RW      a8
        lda     temporal_stage_metadata_only
        bne     @StagingGateReady
        jsr     WaitForSafeStagingFrame
@StagingGateReady:
        VBL_off
        RW      a16
        lda     demo_schedule_revision
        cmp     staging_demo_epoch
        beq     :+
        jmp     DiscardStaleStage
:
        RW      a8
        jsr     StageExpandedFrame
        RW_forced a16i16
        lda     producer_slot
        sta     ready_slot
        eor     #$01
        sta     producer_slot
        lda     #$01
        sta     frame_ready
FrameReadyPublished:
        RW_forced a8i16
        lda     RDNMI                   ; Discard any VBlank deferred by DMA.
        VBL_on
        RW_forced a16i16
        jsr     JoinOverlappedSelector
        jmp     MainLoop
DiscardStaleFrameBeforeSelector:
        stz     stage_frame_required
        jmp     MainLoop
DiscardStaleStage:
        stz     prefetched_selector_valid
        RW      a8
        lda     RDNMI
        VBL_on
        RW      a16
        jsr     JoinOverlappedSelector
        stz     prefetched_selector_valid
        stz     stage_frame_required
        jmp     MainLoop
.include "quake/FrameStaging.s"
;-------------------------------------------------------------------------------
StageStaticAssets:
        RW_forced a8i16
        ; ROM96/97 use linear linker labels at $C0. The S-CPU mirror of the
        ; same physical 3 MiB offset starts at $F0 and is used at boot.
        BSP_STATIC_COPY QuakeBSPCollisionRAM, BSP_COLLISION_CPU_ROM_BASE, BSP_COLLISION_PACKED_0_BYTES
  .if BSP_COLLISION_PACKED_1_BYTES > 0
        BSP_STATIC_COPY QuakeBSPCollisionRAM+BSP_COLLISION_PACKED_0_BYTES, BSP_COLLISION_CPU_ROM_BASE+BSP_WORLD_ROM_BANK_BYTES, BSP_COLLISION_PACKED_1_BYTES
  .endif
        BSP_STATIC_COPY GSU_SIN, QuakeBSPSin, 32
        BSP_STATIC_COPY GSU_COS, QuakeBSPCos, 32
        BSP_STATIC_COPY GSU_RECIPROCAL, QuakeBSPReciprocal, GSU_RECIPROCAL_RAM_BYTES
        BSP_STATIC_COPY GSU_EXPAND_NIBBLE, QuakeBSPExpandRight, 16
        BSP_STATIC_COPY GSU_TURBULENCE_TABLE, QuakeBSPTurbulenceTable, BSP_TURBULENCE_TABLE_BYTES
        BSP_STATIC_COPY GSU_TURBULENCE_TABLE+BSP_TURBULENCE_TABLE_BYTES, QuakeBSPTurbulenceTable, BSP_TURBULENCE_TABLE_BYTES
        BSP_STATIC_COPY GSU_TEXTURE_COORD_MAP, QuakeBSPTextureCoordinateMap, GSU_TEXTURE_COORD_MAP_BYTES
        ; Persistent cartridge RAM may contain an old denominator/reciprocal
        ; pair. Zero both records so the first positive edge denominator misses.
        BSP_STATIC_COPY GSU_TEXTURE_EDGE_DIVIDE_CACHE, QuakeBSPEdgeDivideCacheInitial, GSU_TEXTURE_EDGE_DIVIDE_CACHE_BYTES
        BSP_STATIC_COPY GSU_DIVIDE_Q12_HOT_MIRROR, QuakeBSPDivideQ12Reciprocal, GSU_DIVIDE_Q12_HOT_MIRROR_BYTES
        ; Technique 4 is the default renderer, so stage its natural pages once
        ; at boot instead of paying a transition copy before the first frame.
        BSP_STATIC_COPY GSU_TEXTURE_COLORMAP, QuakeBSPLightmapColormap, GSU_LIGHTMAP_COLORMAP_BYTES
        rts
.include "quake/TemporalReuse.s"
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
StageCommand:
        RW_forced a16i16
StageCommandRetry:
        lda     control_revision
        sta     render_camera+12
        lda     demo_schedule_revision
        sta     render_demo_epoch
        lda     camera_x
        sta     render_camera_q8+0
        lda     camera_y
        sta     render_camera_q8+2
        lda     camera_z
        sta     render_camera_q8+4
        lda     yaw_index
        and     #$001F
        sta     render_camera+0
        lda     pitch_level
        and     #$001F
        sta     render_camera+2
        lda     camera_x
        sec
        sbc     #BSP_WORLD_START_X_Q8
        xba
        and     #$00FF
        sta     render_camera+4
        lda     camera_y
        sec
        sbc     #BSP_WORLD_START_Y_Q8
        xba
        and     #$00FF
        sta     render_camera+6
        lda     camera_z
        sec
        sbc     #BSP_WORLD_START_Z_Q8
        xba
        and     #$00FF
        sta     render_camera+8
        ; Resolve into the unpublished snapshot; flight freezes its last seqlock state.
        stz     render_brush_visual_state
        lda     technique
        and     #$00FF
        sta     render_camera+10       ; A16 store also clears overlay flags.
        lda     dynamic_brushes_enabled
        bne     StageCommandResolveBrushState
        lda     mdl_entities_enabled
        and     #BSP_EXTERNAL_BSP_SUPPORTED
        beq     StageCommandBrushStateResolved
StageCommandResolveBrushState:
        lda     brush_visual_state
        sta     render_brush_visual_state
        lda     demo_mode
        bne     StageCommandLoadBrushState
        lda     render_brush_visual_state
        bne     StageCommandCompleteFlyBrushState
StageCommandLoadBrushState:
        ldx     demo_track_pose
        txa
        asl
        tax
        lda     f:BSP_BRUSH_ROWSTATE_CPU_ADDRESS,x
        sta     render_brush_visual_state
StageCommandCompleteFlyBrushState:
        ; Fill demo-camera omissions while preserving the accepted brush poses.
        lda     demo_mode
        bne     StageCommandBrushStateResolved
        lda     render_brush_visual_state
        dec
        asl
        tax
        lda     f:BSP_BRUSH_FLYSTATE_CPU_ADDRESS,x
        sta     render_brush_visual_state
StageCommandBrushStateResolved:
        lda     dynamic_brushes_enabled
        beq     StageCommandAliases
        lda     render_camera+10
        ora     #(BSP_OVERLAY_DYNAMIC_BRUSHES << 8)
        sta     render_camera+10
        lda     demo_mode
        bne     StageCommandAliases
        lda     render_camera+10
        ora     #(BSP_OVERLAY_FLY_STATICS << 8)
        sta     render_camera+10
StageCommandAliases:
        ; Demo uses sampled entity rows; flight uses the all-leaf initial-pose snapshot.
        lda     mdl_entities_enabled
        beq     StageCommandOverlayReady
        lda     render_camera+10
        ora     #(BSP_OVERLAY_EXTERNAL_BSP << 8)
        sta     render_camera+10
        lda     render_camera+10
        ora     #(BSP_OVERLAY_ALIAS_ENTITIES << 8)
        sta     render_camera+10
StageCommandOverlayReady:
        lda     demo_mode
        beq     @ManualDemoMetadata
        lda     demo_track_pose
        sta     render_demo_pose
        sta     render_camera+14
        lda     demo_pose_due_tick
        sta     render_demo_due_tick
        bra     @DemoMetadataReady
@ManualDemoMetadata:
        lda     #$FFFF
        sta     render_demo_pose
        ; Quantize camera yaw to the nearest generated 45-degree orbit row.
        lda     render_camera+0
        clc
        adc     #2
        lsr
        lsr
        and     #(BSP_ALIAS_FLY_ROW_COUNT - 1)
        clc
        adc     #BSP_ALIAS_FLY_ROW
        sta     render_camera+14
        stz     render_demo_due_tick
@DemoMetadataReady:
        ; Bind technique, flags, entity pose, and brush replay to one revision.
        jsr     StageSkyCommand
        jsr     StageAliasRotation
        jsr     StageTurbulenceCommand
        lda     control_revision
        cmp     render_camera+12
        beq     :+
        jmp     StageCommandRetry
:
        lda     demo_schedule_revision
        cmp     render_demo_epoch
        beq     :+
        jmp     StageCommandRetry
:
        lda     dynamic_brushes_enabled
        bne     :+
        lda     mdl_entities_enabled
        and     #BSP_EXTERNAL_BSP_SUPPORTED
        beq     StageCommandSnapshotReady
:
        lda     render_brush_visual_state
        sta     brush_visual_state
StageCommandSnapshotReady:
        jsr     EnsureBrushCode

        RW      a8
        lda     render_camera+0
        sta     f:GSU_COMMAND+0
        lda     render_camera+2
        sta     f:GSU_COMMAND+1
        lda     render_camera+4
        sta     f:GSU_COMMAND+2
        lda     render_camera+6
        sta     f:GSU_COMMAND+3
        lda     render_camera+8
        sta     f:GSU_COMMAND+4
        lda     render_camera+10
        sta     f:GSU_COMMAND+5
        lda     render_camera+12
        sta     f:GSU_COMMAND+6
        lda     render_camera+13
        sta     f:GSU_COMMAND+7
        lda     render_camera_q8+1      ; Global map-centered signed coordinates.
        sta     f:GSU_COMMAND+8
        lda     render_camera_q8+3
        sta     f:GSU_COMMAND+9
        lda     render_camera_q8+5
        sta     f:GSU_COMMAND+10
        lda     render_camera+11
        sta     f:GSU_COMMAND+11        ; Overlay feature flags.
        RW      a16
        lda     render_brush_visual_state
        sta     f:GSU_COMMAND+12
        lda     render_camera+14
        sta     f:GSU_DATA_BASE+GSU_ALIAS_RENDER_ROW_OFFSET
        lda     demo_track_pose
        sta     f:GSU_COMMAND+14        ; Frozen demo row for brush lifecycle.
        RW_forced a16i16
        rts
;-------------------------------------------------------------------------------
RenderFrame:
        RW_forced a16i16
        ; Flat rendering overlaps the S-CPU queue work. Join that prior job
        ; before touching SCMR, SCBR, or the shared command for another frame.
        BSP_SOUND_FX3_JOB_JOIN
        lda     prefetched_selector_valid
        beq     RenderStageSelectorCommand
        stz     prefetched_selector_valid
        lda     #$0001
        sta     stage_frame_required
        jmp     RenderAfterSelectorCapture
RenderStageSelectorCommand:
        RW      a8
        stz     FX3_SCMR
        jsr     StageCommand
        RW_forced a16i16
        lda     coverage_debug
        sta     render_coverage_mode       ; Bind the mode to this frame job.
        jsr     ClassifyScheduledFrameReuse
        beq     RenderRequired
        cmp     #$0002
        bne     RenderIdleReady
        inc     texture_input_reuse_counter
        sta     temporal_stage_metadata_only
        lda     #$0001
        sta     stage_frame_required

RenderIdleReady:
        RW_forced a16i16
        rts

RenderRequired:
        lda     #$0001
        sta     stage_frame_required
        stz     temporal_stage_metadata_only
        ; Reuse a successfully guarded packet while the camera pose is
        ; unchanged instead of repeating the full-world selector/painter pass.
        ; Packet geometry depends on camera pose, not technique, diagnostic
        ; mode, demo/manual source, or the bookkeeping revision. Keep the
        ; full-Q8 position so every fly-camera movement still invalidates the
        ; selector even before it crosses a packed whole-unit boundary.
        REQUIRE_ACTIVE_PACKET_CAMERA_MATCH RenderRunSelector
        bra     RenderReusePacket
RenderReusePacket:
        RW_forced a8i16
        jmp     RenderSelectorComplete

RenderRunSelector:
        ; StageCommand deliberately returns in 16-bit accumulator mode.
        ; Force the runtime mode back to 8-bit before the immediate below;
        ; relying on assembler width tracking across JSR would misdecode it.
        RW_forced a16i16
        inc     gsu_job_counter
        RW_forced a8i16
        FX3_JOB_START FX3_SCMR_128X128_4BPP_ROM, .loword(GSU_SelectVisibility), set
        BSP_SOUND_FX3_JOB_JOIN
        stz     FX3_SCMR
        jsr     CaptureSelectorTelemetry
RenderAfterSelectorCapture:
        jsr     UpdateRealtimeDemo
        RW_forced a16i16
        lda     demo_schedule_revision
        cmp     render_demo_epoch
        bne     RenderDiscardSelector
        lda     demo_mode
        beq     RenderSelectorComplete
        lda     demo_schedule
        bne     RenderSelectorComplete
        lda     control_revision
        cmp     render_camera+12
        beq     RenderSelectorComplete
RenderDiscardSelector:
        stz     stage_frame_required
        rts
RenderSelectorComplete:
        RW_forced a16i16
        lda     runtime_menu_open
        beq     :+
        stz     stage_frame_required
        rts
:
        jmp     RenderStartRenderer
.include "quake/RendererDispatch.s"
.include "quake/TextureColormapModes.s"
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
.include "quake/VideoInit.s"
;-------------------------------------------------------------------------------
; Joypad sampling remains at 60 Hz even when rendering or presentation takes
; several video frames. Start toggles native demo1 playback/manual flight;
; Select cycles the supported albedo, lightmapped, and untextured renderers.
BSPVBlank:
        RW_forced a8i16
        ; VBL_on can service a latched NMI immediately when the long selector
        ; returns during active display. Never let that deferred interrupt
        ; mutate presentation state or start a VRAM DMA outside VBlank.
        lda     HVBJOY
        bmi     :+
        jmp     BSPVBlankDone
:
        RW_forced a16i16
        inc     video_tick
        jsr     UpdateFlySkyClock
        jsr     UpdateFlyAliasClock
        jsr     UpdateFlyTurbulenceClock
        RW_forced a8i16
        jsr     UpdateRuntimeMenu
        RW_forced a16i16
        lda     runtime_menu_open
        bne     @ControlsDone
        lda     demo_mode
        beq     @ControlsDone           ; Fly collision work follows the upload.
        RW_forced a8i16
        jsr     UpdateCameraControls
        jsr     UpdateRealtimeDemo
@ControlsDone:
        RW_forced a8i16

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
        stz     upload_palette_mode
@TextureUploadFormatReady:
        lda     #BSP_UPLOAD_FORMAT_TEXTURE
@UploadFormatReady:
        sta     upload_format
        cmp     presented_format
        beq     :+
        RW_forced a8i16
        lda     #inidisp(OFF, DISP_BRIGHTNESS_MIN)
        sta     SFX_inidisp
:
        RW_forced a8i16
@Upload:
        jsr     TryCommitMetadataUpload
        bcs     @SoundVBlank
        jsr     UploadFrameChunk
@SoundVBlank:
.include "quake/SoundVBlank.s"
        RW_forced a16i16
        lda     runtime_menu_open
        bne     BSPVBlankDone
        lda     demo_mode
        bne     BSPVBlankDone
        RW_forced a8i16
        ; All VRAM/palette/page work is complete. Release libSFX forced blank
        ; before CPU-only fly movement, which may extend into active display.
        lda     SFX_inidisp
        sta     INIDISP
FlyControlsVisible:
        jsr     UpdateCameraControls
BSPVBlankDone:
        rtl
.include "quake/RuntimeControls.s"
.include "quake/DemoAdvance.s"
; Start a new schedule epoch at pose zero. Ordered mode advances only after a
; completed frame is staged; real-time mode advances from video_tick in
; UpdateRealtimeDemo. Both publish through the same camera/control revision.
RestartDemoPlayback:
        RW_assume a16i16
        stz     demo_offset
        stz     demo_timing_offset
        stz     demo_next_pose
        jsr     ApplyBootDemoCursor
        stz     demo_pose_counter
        stz     demo_source_due_counter
        stz     demo_coalesced_counter
        stz     demo_loop_counter
        stz     demo_playhead_tick
        lda     video_tick
        sta     demo_playhead_origin
        inc     demo_schedule_revision
        jsr     InvalidateScheduledFrameIdentity
        jsr     LoadNextDemoPose
        inc     demo_source_due_counter
        rts
; Consume the next canonical track/timing cursor. Step mode uses the derived
; 2 Hz stride and wraps for visible playback. Real-time advances one canonical
; configured-rate record and stops at the end so a fixed-duration benchmark
; cannot enter a second epoch.
AdvanceDemoCursor:
        RW_assume a16i16
        lda     demo_schedule
        bne     @RealtimePose
        lda     demo_next_pose
        clc
        adc     demo_ordered_pose_stride
        sta     demo_next_pose
        bra     @CheckEnd
@RealtimePose:
        inc     demo_next_pose
@CheckEnd:
        lda     demo_next_pose
        cmp     #BSP_DEMO_PRECISE_TRACK_POSE_COUNT
        bcc     @AdvanceOffsets
        lda     demo_schedule
        bne     @RealtimeEnd
        stz     demo_next_pose
        stz     demo_offset
        stz     demo_timing_offset
        inc     demo_loop_counter
        rts
@RealtimeEnd:
        lda     #BSP_DEMO_PRECISE_TRACK_POSE_COUNT
        sta     demo_next_pose
        lda     #BSP_DEMO_PRECISE_TRACK_BYTES
        sta     demo_offset
        lda     #BSP_DEMO_PRECISE_TIMING_BYTES
        sta     demo_timing_offset
        rts
@AdvanceOffsets:
        lda     demo_schedule
        bne     @RealtimeOffsets
        lda     demo_ordered_pose_stride
        cmp     #$0001
        beq     @RealtimeOffsets
        lda     demo_offset
        clc
        adc     #BSP_DEMO_PRECISE_TRACK_RECORD_BYTES * BSP_DEMO_ORDERED_POSE_STRIDE
        sta     demo_offset
        lda     demo_timing_offset
        clc
        adc     #BSP_DEMO_PRECISE_TIMING_RECORD_BYTES * BSP_DEMO_ORDERED_POSE_STRIDE
        sta     demo_timing_offset
        rts
@RealtimeOffsets:
        lda     demo_offset
        clc
        adc     #BSP_DEMO_PRECISE_TRACK_RECORD_BYTES
        sta     demo_offset
        lda     demo_timing_offset
        clc
        adc     #BSP_DEMO_PRECISE_TIMING_RECORD_BYTES
        sta     demo_timing_offset
        rts

LoadNextDemoPose:
        RW_assume a16i16
        lda     demo_next_pose
        sta     demo_track_pose
        ldx     demo_timing_offset
        lda     f:QuakeBSPDemoPreciseTiming,x
        sta     demo_pose_due_tick
        ldx     demo_offset
        jsr     LoadDemoPoseRecord
        jsr     AdvanceDemoCursor
        inc     demo_pose_counter
        inc     control_revision
        rts

; Load one absolute Q3/u16 canonical camera record at X. Positions remain Q8
; through the CPU handoff; the current GSU command quantizes them to its
; existing whole map units.
LoadDemoPoseRecord:
        RW_assume a16i16
        lda     f:QuakeBSPDemoPreciseTrack+0,x
        sec
        sbc     #.loword(BSP_WORLD_ORIGIN_X * 8)
        asl
        sta     camera_x
        lda     f:QuakeBSPDemoPreciseTrack+2,x
        sec
        sbc     #.loword(BSP_WORLD_ORIGIN_Y * 8)
        asl
        sta     camera_y
        lda     f:QuakeBSPDemoPreciseTrack+4,x
        sec
        sbc     #.loword(BSP_WORLD_ORIGIN_Z * 8)
        asl
        sta     camera_z
        lda     f:QuakeBSPDemoPreciseTrack+6,x
        clc
        adc     #$0400
        xba
        and     #$00FF
        lsr
        lsr
        lsr
        and     #$001F
        sta     yaw_index
        lda     #$0000
        sec
        sbc     f:QuakeBSPDemoPreciseTrack+8,x
        clc
        adc     #$0400
        xba
        and     #$00FF
        lsr
        lsr
        lsr
        and     #$001F
        bit     #$0010
        beq     @StorePitch
        ora     #$FFE0
@StorePitch:
        sta     pitch_level
        rts
; Publish the newest pose due at shifted source time; retain due coalescing.
UpdateRealtimeDemo:
        RW_forced a16i16
        BSP_SOUND_HOLD_DEMO UpdateRealtimeReturn
        lda     runtime_menu_open
        beq     :+
        RW_forced a8i16
        rts
:
        RW_assume a16i16
        lda     demo_mode
        beq     UpdateRealtimeReturn
        lda     demo_schedule
        beq     UpdateRealtimeReturn
        lda     video_tick
        sec
        sbc     demo_playhead_origin
        ldx     demo_playback_rate_shift
        beq     @PlayheadReady
@ScalePlayhead:
        lsr
        dex
        bne     @ScalePlayhead
@PlayheadReady:
        sta     demo_playhead_tick
        stz     realtime_due_batch
@CheckDue:
        lda     demo_timing_offset
        cmp     #BSP_DEMO_PRECISE_TIMING_BYTES
        bcs     @Publish
        tax
        lda     f:QuakeBSPDemoPreciseTiming,x
        cmp     demo_playhead_tick
        bcc     @Due
        beq     @Due
        bra     @Publish
@Due:
        sta     realtime_candidate_tick
        lda     demo_offset
        sta     realtime_candidate_offset
        lda     demo_next_pose
        sta     realtime_candidate_pose
        jsr     AdvanceDemoCursor
        inc     demo_source_due_counter
        inc     realtime_due_batch
        bra     @CheckDue
@Publish:
        lda     realtime_due_batch
        beq     UpdateRealtimeReturn
        dec
        clc
        adc     demo_coalesced_counter
        sta     demo_coalesced_counter
        lda     control_revision
        cmp     render_camera+12
        beq     @NoPendingCommand
        inc     demo_coalesced_counter
@NoPendingCommand:
        lda     realtime_candidate_pose
        sta     demo_track_pose
        lda     realtime_candidate_tick
        sta     demo_pose_due_tick
        ldx     realtime_candidate_offset
        jsr     LoadDemoPoseRecord
        inc     demo_pose_counter
        inc     control_revision
UpdateRealtimeReturn:
        RW_forced a8i16
        rts
; Drain one chunk each VBlank; present only after the complete page is resident.
UploadFrameChunk:
        RW_forced a16i16
        lda     upload_offset
        lsr
        tay
        lda     upload_format
        bne     @TextureDestination
        lda     upload_target
        beq     @DestinationA
        tya
        clc
        adc     #VRAM_TILES_B >> 1
        tay
        bra     UploadChunkDestinationReady
@DestinationA:
        tya
        clc
        adc     #VRAM_TILES_A >> 1
        tay
        bra     UploadChunkDestinationReady
@TextureDestination:
        lda     upload_target
        beq     @TextureDestinationA
        tya
        clc
        adc     #VRAM_TEXTURE_TILES_B >> 1
        tay
        bra     UploadChunkDestinationReady
@TextureDestinationA:
        tya
        clc
        adc     #VRAM_TEXTURE_TILES_A >> 1
        tay
UploadChunkDestinationReady:
        lda     upload_offset
        ldx     upload_slot
        beq     @SourceSlot0
        clc
        adc     #.loword(StagedFrame1)
        tax
        bra     @SourceReady
@SourceSlot0:
        clc
        adc     #.loword(StagedFrame0)
        tax
@SourceReady:
        stx     A1T7L
        ldx     #BSP_UPLOAD_CHUNK_BYTES
        lda     upload_format
        beq     @ChunkBytesReady
        ldx     #BSP_TEXTURE_UPLOAD_CHUNK_BYTES
        lda     upload_chunk
        cmp     #BSP_TEXTURE_UPLOAD_CHUNKS-1
        bne     @ChunkBytesReady
        ldx     #BSP_TEXTURE_UPLOAD_LAST_CHUNK_BYTES
        bra     @ChunkBytesReady
@ChunkBytesReady:
        RW      a8
        stz     MDMAEN
        sty     VMADDL
        lda     #$80                    ; Word writes; advance after $2119.
        sta     VMAINC
        lda     #^StagedFrame0
        sta     A1B7
        stx     DAS7L
        lda     #$01                    ; Alternate $2118/$2119 for tile bytes.
        sta     DMAP7
        lda     #$18
        sta     BBAD7
        lda     #%10000000
        sta     MDMAEN
        RW      a16
        inc     vram_chunk_counter
        txa
        clc
        adc     upload_offset
        sta     upload_offset
        inc     upload_chunk
        lda     upload_format
        beq     @FlatUploadChunks
        lda     #BSP_TEXTURE_UPLOAD_CHUNKS
        bra     @UploadChunksReady
@FlatUploadChunks:
        lda     #BSP_UPLOAD_CHUNKS
@UploadChunksReady:
        cmp     upload_chunk
        beq     @FrameUploadComplete
        jmp     UploadFrameReturn
@FrameUploadComplete:
        RW      a8
        lda     upload_format
        beq     @PresentFlat
        jmp     UploadPresentTexture
@PresentFlat:
        jmp     UploadPresentFlat
UploadPresentTexture:
        lda     presented_format
        cmp     #BSP_UPLOAD_FORMAT_TEXTURE
        bne     UploadLoadTexturePalette
        lda     upload_palette_mode
        cmp     presented_palette_mode
        bne     :+
        jmp     UploadTexturePaletteReady
:
UploadLoadTexturePalette:
        lda     upload_palette_mode
        beq     UploadLoadNaturalTexturePalette
        CGRAM_memcpy 0, QuakeBSPUntexturedPalette, 512
        bra     UploadTexturePaletteLoaded
UploadLoadNaturalTexturePalette:
        CGRAM_memcpy 0, QuakeBSPTexturePalette, 512
UploadTexturePaletteLoaded:
        lda     upload_palette_mode
        sta     presented_palette_mode
UploadTexturePaletteReady:
        lda     #bgmode(BG_MODE_3, BG3_PRIO_NORMAL, BG_SIZE_8X8, BG_SIZE_8X8, BG_SIZE_8X8, BG_SIZE_8X8)
        sta     BGMODE                 ; Mode 3 gives BG1 all eight bitplanes.
        jmp     UploadPresentDirect
UploadPresentDirect:
        lda     #$11                    ; Mosaic size 2, BG1 enabled.
        sta     MOSAIC
        lda     #bgsc(VRAM_TEXTURE_TILEMAP, SC_SIZE_32X32)
        sta     BG1SC
        ; Align mosaic pairs to source rows (0,1), (2,3), ... . With the
        ; mirrored tile quads this makes the GSU row swizzle present in
        ; ascending logical order instead of reversing every eight-row tile.
        lda     #$FF
        sta     BG1VOFS
        sta     BG1VOFS
        lda     upload_target
        beq     UploadPresentDirectA
        lda     #bg12nba(VRAM_TEXTURE_TILES_B, 0)
        sta     BG12NBA
        bra     UploadPresented
UploadPresentDirectA:
        lda     #bg12nba(VRAM_TEXTURE_TILES_A, 0)
        sta     BG12NBA
        bra     UploadPresented
UploadPresentFlat:
        lda     presented_format
        beq     UploadFlatPaletteReady
        CGRAM_memcpy 0, QuakeBSPPalette, 32
UploadFlatPaletteReady:
        lda     #bgmode(BG_MODE_1, BG3_PRIO_NORMAL, BG_SIZE_8X8, BG_SIZE_8X8, BG_SIZE_8X8, BG_SIZE_8X8)
        sta     BGMODE
        stz     MOSAIC
        lda     #bgsc(VRAM_TILEMAP, SC_SIZE_32X32)
        sta     BG1SC
        lda     #$FF
        sta     BG1VOFS
        sta     BG1VOFS
        lda     upload_target
        beq     UploadPresentFlatA
        lda     #bg12nba(VRAM_TILES_B, 0)
        sta     BG12NBA
        bra     UploadPresented
UploadPresentFlatA:
        lda     #bg12nba(VRAM_TILES_A, 0)
        sta     BG12NBA
UploadPresented:
        lda     upload_metadata_only
        bne     UploadPresentedMetadata
        lda     upload_format
        sta     presented_format
        lda     upload_target
        eor     #$01
        sta     upload_target
        lda     #inidisp(ON, DISP_BRIGHTNESS_MAX)
        sta     SFX_inidisp

        RW      a16
        inc     page_flip_counter
        bra     UploadPresentedState
UploadPresentedMetadata:
        stz     upload_metadata_only
        ; This entry is called from the A8 NMI dispatcher. Force the physical
        ; REP here: assembler state also reaches this merge from the A16 pixel
        ; path and a state-only RW would elide it, truncating slot-1 metadata.
        RW_forced a16i16
        inc     metadata_present_counter
UploadPresentedState:
        jsr     PublishUploadSlotState
        inc     present_counter
        ; Idle is the final commit word: when it becomes observable, the
        ; visible page, slot identity, metadata, and counters already agree.
        stz     upload_active
UploadFrameReturn:
        RW_forced a8i16
        rts

PublishUploadSlotState:
        ldx     #0
        lda     upload_slot
        beq     @PresentedCameraReady
        ldx     #CAMERA_COMMAND_BYTES
@PresentedCameraReady:
        lda     slot_camera+0,x
        sta     presented_camera+0
        lda     slot_camera+2,x
        sta     presented_camera+2
        lda     slot_camera+4,x
        sta     presented_camera+4
        lda     slot_camera+6,x
        sta     presented_camera+6
        lda     slot_camera+8,x
        sta     presented_camera+8
        lda     slot_camera+10,x
        sta     presented_camera+10
        lda     slot_camera+12,x
        sta     presented_camera+12
        lda     slot_camera+14,x
        sta     presented_camera+14

        ldx     #0
        lda     upload_slot
        beq     @PresentedBrushStateReady
        ldx     #2
@PresentedBrushStateReady:
        lda     slot_brush_visual_state,x
        sta     presented_brush_visual_state

        ldx     #0
        lda     upload_slot
        beq     @PresentedCoverageReady
        ldx     #2
@PresentedCoverageReady:
        lda     slot_coverage_mode,x
        sta     presented_coverage_mode

        lda     slot_demo_pose,x
        sta     presented_demo_pose
        lda     slot_demo_due_tick,x
        sta     presented_demo_due_tick
        lda     slot_demo_epoch,x
        sta     presented_demo_epoch
        jsr     PresentSkyStateFromSlot
        jsr     PresentTurbulenceStateFromSlot
        rts
.segment "ZEROPAGE"
camera_collision_mask: .res 1
.segment "LORAM"
yaw_index:          .res 2
pitch_level:        .res 2
camera_x:           .res 2
camera_y:           .res 2
camera_z:           .res 2
camera_forward_pitch_cos: .res 2
camera_forward_x:   .res 2
camera_forward_y:   .res 2
camera_forward_z:   .res 2
camera_collision_previous_x: .res 2
camera_collision_previous_y: .res 2
camera_collision_previous_z: .res 2
camera_collision_rejected: .res 2
camera_collision_reject_counter: .res 2
temporal_stage_metadata_only: .res 2
upload_metadata_only: .res 2
slot_metadata_only: .res 4
texture_input_reuse_counter: .res 2
metadata_present_counter: .res 2
camera_collision_candidate_x: .res 2
camera_collision_candidate_y: .res 2
camera_collision_candidate_z: .res 2
camera_collision_x_index: .res 2
camera_collision_y_index: .res 2
camera_collision_cell: .res 2
camera_collision_offset: .res 2
camera_collision_column: .res 2
camera_collision_z_byte: .res 2
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
brush_code_valid: .res 2
control_divider:    .res 2
control_revision:   .res 2
runtime_menu_open:  .res 2
runtime_menu_selection: .res 2
runtime_menu_release_gate: .res 2
runtime_menu_restart_action: .res 2
runtime_menu_saved_playhead_tick: .res 2
runtime_menu_apply_flags: .res 2
runtime_menu_draft_playback: .res 2
runtime_menu_draft_technique: .res 2
runtime_menu_draft_textures: .res 2
runtime_menu_draft_lighting: .res 2
runtime_menu_draft_brushes: .res 2
runtime_menu_draft_entities: .res 2
dynamic_brushes_enabled: .res 2
mdl_entities_enabled: .res 2
dynamic_brush_revision: .res 2
brush_visual_state: .res 2
coverage_debug:     .res 2
control_dirty:      .res 2
demo_mode:          .res 2
demo_schedule:      .res 2
demo_playback_rate_shift: .res 2
boot_fixed_step_sample: .res 2
boot_ordered_source_pose: .res 2
demo_ordered_pose_stride: .res 2
demo_offset:        .res 2
demo_timing_offset: .res 2
demo_next_pose:     .res 2
demo_track_pose:    .res 2
demo_pose_due_tick: .res 2
demo_pose_counter:  .res 2
demo_source_due_counter: .res 2
demo_coalesced_counter: .res 2
demo_playhead_tick: .res 2
demo_playhead_origin: .res 2
demo_schedule_revision: .res 2
demo_loop_counter:  .res 2
video_tick:         .res 2
staging_scanline:    .res 2
realtime_due_batch: .res 2
realtime_candidate_offset: .res 2
realtime_candidate_pose: .res 2
realtime_candidate_tick: .res 2
monster_camera_index: .res 2
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
presented_demo_due_tick: .res 2
presented_demo_epoch: .res 2
scheduled_frame_camera: .res CAMERA_COMMAND_BYTES
scheduled_frame_camera_q8: .res 6
scheduled_frame_coverage_mode: .res 2
scheduled_frame_brush_visual_state: .res 2
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
.segment "EXRAM"
QuakeBSPCollisionRAM:
        .res BSP_COLLISION_PAYLOAD_BYTES
QuakeBSPCollisionRAMEnd:
QuakeBSPCollisionMapRAM = QuakeBSPCollisionRAM
QuakeBSPCollisionDictionaryRAM = QuakeBSPCollisionRAM + BSP_COLLISION_DICTIONARY_OFFSET
.assert QuakeBSPCollisionRAM = BSP_COLLISION_RAM_BASE, lderror, "Fly collision WRAM base moved"
.assert QuakeBSPCollisionRAMEnd - QuakeBSPCollisionRAM = BSP_COLLISION_PAYLOAD_BYTES, error, "Fly collision WRAM reservation size disagrees"
.segment "HIRAM"
StagedFrame0:       .res GSU_OUTPUT_BYTES
StagedFrame1:       .res GSU_OUTPUT_BYTES
;-------------------------------------------------------------------------------
.segment "RODATA"
BSP_CAMERA_MOVE_TABLES
.segment "BSPDATA"
QuakeBSPVertices:
        .incbin "Data/QuakeBSPVertices.bin"
QuakeBSPIndices:
        .incbin "Data/QuakeBSPIndices.bin"
QuakeBSPFaces:
        .incbin "Data/QuakeBSPFaces.bin"
QuakeBSPFacePlanes:
        .incbin "Data/QuakeBSPFacePlanes.bin"
QuakeBSPPalette:
        .incbin "Data/QuakeBSPPalette.bin"
QuakeBSPTilemap:
        .incbin "Data/QuakeBSPTilemap.bin"
QuakeBSPSin:
        .incbin "Data/QuakeBSPSin.bin"
QuakeBSPCos:
        .incbin "Data/QuakeBSPCos.bin"
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
.segment "BSP_DEMO_TRACK"
QuakeBSPDemoPreciseTrack:
        .incbin "Data/QuakeBSPDemoPrecise.bin"
QuakeBSPDemoPreciseTrackEnd:
.assert QuakeBSPDemoPreciseTrackEnd - QuakeBSPDemoPreciseTrack = BSP_DEMO_PRECISE_TRACK_BYTES, error, "demo1 precise track asset size disagrees with generated constants"
.segment "BSP_DEMO_TIMING"
QuakeBSPDemoPreciseTiming:
        .incbin "Data/QuakeBSPDemoPreciseTiming.bin"
QuakeBSPDemoPreciseTimingEnd:
.assert QuakeBSPDemoPreciseTimingEnd - QuakeBSPDemoPreciseTiming = BSP_DEMO_PRECISE_TIMING_BYTES, error, "demo1 precise timing asset size disagrees with generated constants"
.include "Data/QuakeBSPSkyAssets.s"
.include "Data/QuakeBSPTurbulenceAssets.s"
.segment "BSP_WORLD_FACE_OWNERS"
QuakeBSPWorldFaceOwners:
        .incbin "Data/QuakeBSPWorldFaceOwners.bin"
QuakeBSPWorldFaceOwnersEnd:
.assert QuakeBSPWorldFaceOwnersEnd - QuakeBSPWorldFaceOwners = BSP_WORLD_FACE_COUNT * BSP_WORLD_FACE_OWNER_RECORD_BYTES, error, "Full-map face-owner asset size disagrees with generated counts"
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
.segment "BSP_WORLD_TEXTURE_AUX"
QuakeBSPWorldTextureCoordinates2:
        .incbin "Data/QuakeBSPWorldTextureCoordinates2.bin"
QuakeBSPWorldTextureCoordinates2End:
QuakeBSPWorldFaceTextureIds:
        .incbin "Data/QuakeBSPWorldFaceTextureIds.bin"
QuakeBSPWorldFaceTextureIdsEnd:
QuakeBSPWorldTextureDirectory:
        .incbin "Data/QuakeBSPWorldTextureDirectory.bin"
QuakeBSPWorldTextureDirectoryEnd:
QuakeBSPTexturePalette:
        .incbin "Data/QuakeBSPTexturePalette.bin"
QuakeBSPTexturePaletteEnd:
.include "quake/TexturelessPalette.s"
QuakeBSPTextureTilemap:
        .incbin "Data/QuakeBSPTextureTilemap.bin"
QuakeBSPTextureTilemapEnd:
QuakeBSPTextureCoordinateMap:
        .incbin "Data/QuakeBSPTextureCoordinateMap.bin"
QuakeBSPTextureCoordinateMapEnd:
.assert QuakeBSPWorldTextureCoordinates2End - QuakeBSPWorldTextureCoordinates2 = BSP_WORLD_TEXTURE_COORD_2_BYTES, error, "Texture-coordinate bank 2 size disagrees"
.assert QuakeBSPWorldFaceTextureIdsEnd - QuakeBSPWorldFaceTextureIds = BSP_WORLD_FACE_TEXTURE_ID_BYTES, error, "Face texture-ID size disagrees"
.assert QuakeBSPWorldTextureDirectoryEnd - QuakeBSPWorldTextureDirectory = BSP_WORLD_TEXTURE_DIRECTORY_BYTES, error, "Texture directory size disagrees"
.assert QuakeBSPTexturePaletteEnd - QuakeBSPTexturePalette = 512, error, "Exact texture palette must have 256 colors"
.assert QuakeBSPTextureTilemapEnd - QuakeBSPTextureTilemap = $0800, error, "Exact texture tilemap must be 32x32"
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
.segment "BSP_WORLD_LIGHTMAP_DIRECTORY"
        .incbin "Data/QuakeBSPWorldLightmapDirectory.bin"
.segment "BSP_WORLD_LIGHTMAP_0"
        .incbin "Data/QuakeBSPWorldLightmapSamples0.bin"
.segment "BSP_WORLD_LIGHTMAP_1"
        .incbin "Data/QuakeBSPWorldLightmapSamples1.bin"
.segment "BSP_WORLD_LIGHTMAP_2"
        .incbin "Data/QuakeBSPWorldLightmapSamples2.bin"
.segment "BSP_WORLD_LIGHTMAP_3"
        .incbin "Data/QuakeBSPWorldLightmapSamples3.bin"
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
.include "quake/DynamicBrushAssets.s"
.include "Data/QuakeBSPComposedCacheAssets.s"
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
.include "quake/SoundEngine.s"

; Qualification-only state follows the runtime BSS so adding it cannot move
; the hot renderer or sound state across an indexed-address page boundary.
.segment "BSS"
temporal_reuse_enabled: .res 2
