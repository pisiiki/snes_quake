# Reassemble CPU sources whenever their shared framebuffer helpers change.

snes_framebuffer_include ?= SNES_Framebuffer.i

$(obj): $(snes_framebuffer_include)
