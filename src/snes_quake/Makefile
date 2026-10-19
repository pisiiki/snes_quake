# Convenience entry points; the Python builder owns assembly and validation.
name := quake
PYTHON ?= python
builder := ../../tools/snes_tooling_cli.py

.PHONY: all assets check
all:
	"$(PYTHON)" "$(builder)" quake.build-quake-release --release-root ../..
assets:
	"$(PYTHON)" "$(builder)" quake.build-quake-release --release-root ../.. --assets-only
check:
	"$(PYTHON)" "$(builder)" quake.build-quake-release --release-root ../.. --check
