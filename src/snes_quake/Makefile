name        := ../../out/snes_quake/quake
PYTHON      ?= python

ifeq ($(SNES_QUAKE_STAGED_MAP),1)
obj_dir     := ../../out/snes_quake/build
output_dir  := ../../out/snes_quake
debug       := 2
libsfx_dir  ?= ../../github/Optiroc/libSFX/master
include $(libsfx_dir)/libSFX.make
include GSU_Primitives.make
include GSU_Raster.make

$(obj): SNES_FX3.i

$(output_dir):
	mkdir -pv "$(output_dir)"

$(rom): | $(output_dir)
else
.PHONY: default all clean
default:
	"$(PYTHON)" "../../tools/commands/snes_quake/build_quake_project.py" $(if $(libsfx_dir),--libsfx "$(libsfx_dir)")

all: default

clean:
	$(RM) ../../out/snes_quake/playable/quake-playable*
endif
