# Reassemble GSU sources whenever their shared raster helpers change.

gsu_raster_include ?= GSU_Raster.i

$(obj_gsu): $(gsu_raster_include)
