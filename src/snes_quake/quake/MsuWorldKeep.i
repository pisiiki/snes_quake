; This tail is selector-only scratch; renderer state lives in other arrays.
; Invalidate before every StageCommand attempt; publish magic only after DMA.
MSU_WORLD_KEEP_BYTES = 52
MSU_WORLD_KEEP_MASK = GSU_VALID_OFFSET + GSU_VALID_CAPACITY - 64
MSU_WORLD_KEEP_READY = MSU_WORLD_KEEP_MASK + MSU_WORLD_KEEP_BYTES
MSU_WORLD_KEEP_COUNT = MSU_WORLD_KEEP_READY + 2
MSU_WORLD_KEEP_ORDINAL = MSU_WORLD_KEEP_COUNT + 2
MSU_WORLD_KEEP_RETURN = MSU_WORLD_KEEP_ORDINAL + 2
MSU_WORLD_KEEP_MODE = MSU_WORLD_KEEP_RETURN + 2
MSU_WORLD_KEEP_MAGIC = $C75A
.assert MSU_WORLD_KEEP_MODE+2 <= GSU_VALID_OFFSET+GSU_VALID_CAPACITY, error, "Keep state escapes selector tail"
.assert GSU_PACKET_FACE_CAPACITY <= MSU_WORLD_KEEP_BYTES*8, error, "Keep mask too small"
.assert BSP_FACE_RECORD_BYTES = 5, error, "Keep cursor contract changed"
