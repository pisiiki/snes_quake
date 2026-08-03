; Shared declarations for SuperFX instruction-cache kernels.

.ifndef __GSU_CACHE_I__
__GSU_CACHE_I__ = 1

GSU_CACHE_BYTES      = 512
GSU_CACHE_LINE_BYTES = 16

; R14 controls the Game Pak ROM buffer. Cache kernels must use this helper so
; intentional ROM reads remain distinct from accidental general-purpose writes.
.macro GSU_SET_ROM_BUFFER_ADDRESS source
        move    R14, source
.endmacro

.macro GSU_CACHE_KERNEL_BEGIN name
        .align  GSU_CACHE_LINE_BYTES
name:
        .ident(.concat("__GSU_CACHE_KERNEL_", .string(.left(1, {name})), "_START")):
        .ident(.concat("__GSU_CACHE_KERNEL_", .string(.left(1, {name})), "_CACHE")):
        cache
.endmacro

.macro GSU_CACHE_KERNEL_END name
        .ident(.concat("__GSU_CACHE_KERNEL_", .string(.left(1, {name})), "_END")):
        .assert * > name, error, "GSU cache kernel must not be empty"
        .assert * - name <= GSU_CACHE_BYTES, error, "GSU cache kernel exceeds 512 bytes"
.endmacro

.endif
