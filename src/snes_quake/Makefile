# Convenience entry points; the Python builder owns assembly and validation.
name := quake
PYTHON ?= python
builder := ../../tools/commands/snes_quake/build_quake_release.py

.PHONY: all assets check
all:
	"$(PYTHON)" "$(builder)" --release-root ../..
assets:
	"$(PYTHON)" "$(builder)" --release-root ../.. --assets-only
check:
	"$(PYTHON)" "$(builder)" --release-root ../.. --check
