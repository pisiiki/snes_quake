# Add post-link validation to a libSFX example containing declared cache kernels.

PYTHON ?= python
gsu_cache_include ?= GSU_Cache.i
gsu_cache_validator ?= ../../tools/commands/shared/validate_gsu_cache_kernels.py
gsu_cache_manifest ?= GSUCacheKernels.json
gsu_special_register_linter ?= ../../tools/commands/shared/lint_gsu_special_registers.py

ifneq ($(debug),2)
$(error GSU_Cache.make requires debug := 2 for linked .dnfo validation)
endif

$(obj_gsu): $(gsu_cache_include)
$(obj_gsu): | validate-gsu-special-registers

.PHONY: validate-gsu-cache-kernels validate-gsu-special-registers
default: validate-gsu-cache-kernels validate-gsu-special-registers

validate-gsu-special-registers:
	"$(PYTHON)" $(gsu_special_register_linter) $(src_gsu) --include ./ --include $(libsfx_inc) --include $(libsfx_inc)/Configurations

validate-gsu-cache-kernels: $(rom)
	"$(PYTHON)" $(gsu_cache_validator) $(name).$(debug_nfo_ext) --manifest $(gsu_cache_manifest)
