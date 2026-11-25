# Reassemble GSU sources whenever their shared primitive implementations change.

gsu_primitives_include ?= GSU_Primitives.i

$(obj_gsu): $(gsu_primitives_include)
