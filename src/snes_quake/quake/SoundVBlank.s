.if BSP_SOUND_ENABLED
        ; Bulk cartridge-to-SPC transfers must remain outside NMI. The main
        ; loop refill remains interruptible, so every VBlank can return on time.
.endif
