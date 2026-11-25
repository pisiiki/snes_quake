; One independently linked playable module. Every addition is target-guarded.
; Generated binding file supplies PLAYABLE_ARCHIVE_BINDING (16 literal bytes)
; and PLAYABLE_MSU_OFFSET(source): $40 + twice the source physical ROM offset.
.ifdef PLAYABLE_MAP_ID
.assert PLAYABLE_MAP_COUNT >= 2 .and PLAYABLE_MAP_COUNT <= 5, error, "Playable registry count is invalid"
.assert PLAYABLE_MAP_ID >= 0 .and PLAYABLE_MAP_ID < PLAYABLE_MAP_COUNT, error, "Playable map ID escapes the registry"
.assert PLAYABLE_E1M1_MAP_ID = 0 .and PLAYABLE_E1M3_MAP_ID = 1 .and PLAYABLE_START_MAP_ID = 2 .and PLAYABLE_E1M2_MAP_ID = 3, error, "Playable stable map IDs changed"
.ifdef PLAYABLE_RECORDED_TAPE
.assert PLAYABLE_DEFAULT_MAP_ID >= 0 .and PLAYABLE_DEFAULT_MAP_ID < PLAYABLE_MAP_COUNT, error, "Tape boot map escapes the registry"
.assert PLAYABLE_TAPE_BOOT_SKILL >= 0 .and PLAYABLE_TAPE_BOOT_SKILL <= 3, error, "Tape boot skill is invalid"
.assert PLAYABLE_TAPE_BOOT_ALWAYS_RUN = 0 .or PLAYABLE_TAPE_BOOT_ALWAYS_RUN = 1, error, "Tape boot run setting is invalid"
.elseif PLAYABLE_MAP_COUNT > PLAYABLE_START_MAP_ID
.assert PLAYABLE_DEFAULT_MAP_ID = PLAYABLE_START_MAP_ID, error, "Playable cold boot must enter the start hub"
.else
.assert PLAYABLE_DEFAULT_MAP_ID = PLAYABLE_E1M1_MAP_ID, error, "Two-map cold boot must enter E1M1"
.endif
.assert BSP_DEMO_PLAYBACK_SUPPORTED = 0, error, "Playable modules cannot include demo playback"
.include "Data/QuakeBSPPlayableBinding.i"
PLAYABLE_BOOT_TABLE = $80FF00
; These retired framebuffer bytes are used only with display blank/GSU stopped.
; Cold boot clears the signature; Main consumes it before any GSU image is staged.
PLAYABLE_HANDOFF = $700000
PLAYABLE_HANDOFF_MAGIC0 = $5148
PLAYABLE_HANDOFF_MAGIC1 = $4353
PLAYABLE_HANDOFF_RENDER = PLAYABLE_HANDOFF+8
PLAYABLE_HANDOFF_RENDER_CHECK = PLAYABLE_HANDOFF+10
PLAYABLE_HANDOFF_RENDER_BRUSHES = $0100
PLAYABLE_HANDOFF_RENDER_ENTITIES = $0200
PLAYABLE_HANDOFF_RENDER_X3 = $0400

.segment "LORAM"
runtime_menu_draft_map: .res 2
runtime_walk: .res 2
playable_switch_pending: .res 2
playable_switch_target: .res 2
playable_boot_pointer: .res 3
playable_archive_ready: .res 1
playable_archive_error: .res 1
playable_archive_busy: .res 1
playable_archive_seek: .res 4
playable_copy_remaining: .res 2
playable_copy_value: .res 1
; The checked loop is installed after boot clears LoRAM. Its two operands
; are patched only while PlayableCopyInline owns the archive.
PLAYABLE_COPY_KERNEL_CAPACITY = 32
PlayableCopyKernel: .res PLAYABLE_COPY_KERNEL_CAPACITY
PlayableCopyDestination = PlayableCopyKernel + (PlayableCopyKernelStore - PlayableCopyKernelTemplate) + 1
PlayableCopyLength = PlayableCopyKernel + (PlayableCopyKernelLimit - PlayableCopyKernelTemplate) + 1

.segment "RODATA"
PlayableArchiveExpected:
        .byte "QPL1"
        PLAYABLE_ARCHIVE_BINDING
PlayableArchiveExpectedEnd:
.assert PlayableArchiveExpectedEnd-PlayableArchiveExpected = 20, error, "Playable binding must be 16 bytes"
PlayableMsuSignature:
        .byte "S-MSU1"
.segment "CODE"
; Pure queue operation shared by foreground portal and NMI menu wrappers.
; A is an explicit registry ID; zero remains the valid E1M1 destination.
PlayableRequestMap:
        RW_assume a16i16
        cmp     #PLAYABLE_MAP_COUNT
        bcc     @Valid
        RW      a8
        lda     #7
        jmp     PlayableArchiveFatal
@Valid:
        RW_forced a16i16
        sta     f:playable_switch_target
        lda     #1
        sta     f:playable_switch_pending
        rts

; QCCPU is linked in a different program bank. This entry keeps DBR
; unchanged and returns through the long caller's bank byte.
PlayableRequestMapLong:
        RW_assume a16i16
        jsr     PlayableRequestMap
        rtl

PlayableMenuPreviousMap:
        RW_assume a16i16
        lda     runtime_menu_draft_map
        bne     :+
        lda     #PLAYABLE_MAP_COUNT
:
        dec
        bra     PlayableMenuStoreMap

PlayableMenuNextMap:
        RW_assume a16i16
        lda     runtime_menu_draft_map
        inc
        cmp     #PLAYABLE_MAP_COUNT
        bcc     PlayableMenuStoreMap
        lda     #0
PlayableMenuStoreMap:
        sta     runtime_menu_draft_map
        jmp     RefreshRuntimeMenuOAM

PlayableMenuActivateValue:
        RW_assume a16i16
        cmp     #RUNTIME_MENU_ROW_PLAYBACK
        beq     PlayableMenuConfirmMap
        jmp     RuntimeMenuNextValue

PlayableMenuConfirmMap:
        RW_assume a16i16
        lda     runtime_menu_draft_map
        cmp     #PLAYABLE_MAP_ID
        beq     :+
        jsr     PlayableRequestMap
:
        jmp     CloseRuntimeMenu

; The composed reset trampoline calls the default module here. Warm switches
; deliberately jump to BootVector instead, retaining the checked handoff.
PlayableColdBoot:
        sei
        clc
        xce
        rep     #$30
        sep     #$20
        RW_assume a8i16
        lda     #0
        sta     f:PLAYABLE_HANDOFF
        sta     f:PLAYABLE_HANDOFF+1
        sta     f:PLAYABLE_HANDOFF+2
        sta     f:PLAYABLE_HANDOFF+3
        jml     BootVector

; BootVector clears all CPU WRAM. Consume this temporary GSURAM mailbox
; before any static GSU image or frame can overwrite it. No other state survives.
PlayableInitMenuPreferences:
        RW_assume a16i16
.ifdef PLAYABLE_RECORDED_TAPE
        lda     #PLAYABLE_TAPE_BOOT_SKILL
        sta     quake_skill_selected
  .if !PLAYABLE_TAPE_BOOT_ALWAYS_RUN
        lda     #QC_INPUT_WALK
        sta     runtime_walk
  .endif
.else
        lda     #1
        sta     quake_skill_selected
.endif
        lda     #RUNTIME_MENU_TECHNIQUE_TEXTURED_LIGHTMAP
        sta     technique
        lda     #BSP_BRUSH_DYNAMIC_REPLAY_SUPPORTED
        sta     dynamic_brushes_enabled
        lda     #BSP_RENDER_ENTITIES_SUPPORTED
        sta     mdl_entities_enabled
        lda     #RUNTIME_MENU_PLAYBACK_FLY
        sta     fly_playback_mode
        lda     f:PLAYABLE_HANDOFF
        cmp     #PLAYABLE_HANDOFF_MAGIC0
        bne     @NoHandoff
        lda     f:PLAYABLE_HANDOFF+2
        cmp     #PLAYABLE_HANDOFF_MAGIC1
        beq     @ReadHandoff
@NoHandoff:
.ifdef PLAYABLE_RECORDED_TAPE
        ; Warm gameplay can continue in live input after the tape ends.
        lda     #QC_INPUT_RECORDED_TAPE
        sta     qc_input_replay
.endif
        jmp     @Clear
@ReadHandoff:
        lda     f:PLAYABLE_HANDOFF+4
        eor     f:PLAYABLE_HANDOFF+6
        cmp     #$FFFF
        bne     @BadHeader
        lda     f:PLAYABLE_HANDOFF+4
        and     #$00FF
        cmp     #PLAYABLE_MAP_ID
        bne     @BadHeader
        lda     f:PLAYABLE_HANDOFF+4
        xba
        and     #$00FF
        cmp     #8
        bcc     @ReadGameplay
@BadHeader:
        jmp     @Invalid
@ReadGameplay:
        pha
        and     #3
        sta     quake_skill_selected
        pla
        and     #QC_INPUT_WALK
        sta     runtime_walk
        lda     f:PLAYABLE_HANDOFF_RENDER
        eor     f:PLAYABLE_HANDOFF_RENDER_CHECK
        cmp     #$FFFF
        bne     @Invalid
        lda     f:PLAYABLE_HANDOFF_RENDER
        and     #$F8FF
        cmp     #RUNTIME_MENU_TECHNIQUE_TEXTURED_LIGHTMAP
        beq     @RestoreRender
        cmp     #RUNTIME_MENU_TECHNIQUE_FACE_COLORS
        beq     @RestoreRender
        cmp     #RUNTIME_MENU_TECHNIQUE_TEXTURED_NONE
        beq     @RestoreRender
        cmp     #RUNTIME_MENU_TECHNIQUE_UNTEXTURED_LIGHTMAP
        bne     @Invalid
@RestoreRender:
        sta     technique
.ifdef QC_CAMPAIGN_ITEMS
        jsl     CampaignRead
.endif
        lda     f:PLAYABLE_HANDOFF_RENDER
        xba
        pha
        and     #(PLAYABLE_HANDOFF_RENDER_BRUSHES >> 8) & BSP_BRUSH_DYNAMIC_REPLAY_SUPPORTED
        sta     dynamic_brushes_enabled
        pla
        pha
        lsr
        and     #BSP_RENDER_ENTITIES_SUPPORTED
        sta     mdl_entities_enabled
        pla
        bit     #(PLAYABLE_HANDOFF_RENDER_X3 >> 8)
        beq     @Clear
        lda     #RUNTIME_MENU_PLAYBACK_FLY3X
        sta     fly_playback_mode
@Clear:
        lda     #0
        sta     f:PLAYABLE_HANDOFF
        sta     f:PLAYABLE_HANDOFF+2
        sta     f:PLAYABLE_HANDOFF+4
        sta     f:PLAYABLE_HANDOFF+6
        rts
@Invalid:
        RW      a8
        lda     #7
        jmp     PlayableArchiveFatal

; MainLoop calls this only when a switch is pending, then loops without
; scheduling another frame. Let the existing NMI consumer finish its upload.
PlayableServiceSwitch:
        RW_assume a16i16
        lda     upload_active
        ora     frame_ready
        and     #$00FF
        beq     @CheckGsu
        jmp     @Wait
@CheckGsu:
        ldx     FX3_R15
        beq     @Quiescent
        jmp     @Wait
@Quiescent:
        sei
        RW      a8
        stz     NMITIMEN
        stz     SFX_nmitimen
        stz     HDMAEN
        lda     #$80
        sta     INIDISP
        sta     SFX_inidisp
        jsr     PlayableWaitApuIdle
.ifdef QC_E1M1_TELEPORT
        ; Return to the original directory and static samples on the next boot.
        lda     #GAMEPLAY_SAMPLE_IPL
        sta     SMPIO2
        lda     SMPIO3
        inc
        sta     SMPIO3
        jsl     SFX_SMP_ready           ; X is already 16-bit at the quiescent switch.
.endif
        jsl     PlayableClearFxRam
        RW      a16
        lda     playable_switch_target
        cmp     #PLAYABLE_MAP_COUNT
        bcc     @TargetValid
        RW      a8
        lda     #7
        jmp     PlayableArchiveFatal
@TargetValid:
        RW_forced a16i16
        lda     quake_skill_selected
        and     #3
        ora     runtime_walk
        xba
        ora     playable_switch_target
        sta     f:PLAYABLE_HANDOFF+4
        eor     #$FFFF
        sta     f:PLAYABLE_HANDOFF+6
        lda     mdl_entities_enabled
        asl
        ora     dynamic_brushes_enabled
        xba
        ora     technique
        ldx     fly_playback_mode
        cpx     #RUNTIME_MENU_PLAYBACK_FLY3X
        bne     :+
        ora     #PLAYABLE_HANDOFF_RENDER_X3
:
        sta     f:PLAYABLE_HANDOFF_RENDER
        eor     #$FFFF
        sta     f:PLAYABLE_HANDOFF_RENDER_CHECK
        lda     #PLAYABLE_HANDOFF_MAGIC1
        sta     f:PLAYABLE_HANDOFF+2
        lda     #PLAYABLE_HANDOFF_MAGIC0
        sta     f:PLAYABLE_HANDOFF
        lda     playable_switch_target
        asl
        clc
        adc     playable_switch_target
        tax
        RW      a8
        lda     f:PLAYABLE_BOOT_TABLE,x
        sta     playable_boot_pointer
        lda     f:PLAYABLE_BOOT_TABLE+1,x
        sta     playable_boot_pointer+1
        lda     f:PLAYABLE_BOOT_TABLE+2,x
        sta     playable_boot_pointer+2
        ; BootVector recreates libSFX state and clears transient WRAM.
        jml     [playable_boot_pointer]
@Wait:
        wai
        rts

; A pending command must be acknowledged before its CPU token is erased.
; No foreground game service or NMI sound sender runs after this point.
PlayableWaitApuIdle:
        RW_assume a8i16
        lda     SMPIO0
        cmp     #$A5
        beq     :+
        lda     #6
        jmp     PlayableArchiveFatal
:
        lda     f:shotgun_sound_token
        ldx     #$FFFF
@Ack:
        cmp     SMPIO3
        beq     @Ready
        dex
        bne     @Ack
        lda     #6
        jmp     PlayableArchiveFatal
@Ready:
        rts

; BootVector clears CPU WRAM only. Explicitly discard every old FX packet,
; tag, mask and code byte before staging the next independently linked map.
; Each overlap-safe forward MVN propagates byte zero into bytes 1..$FFFF.
.pushseg
.segment "BSP_CPU_WALK_RUN"
PlayableClearFxRam:
        RW_assume a8i16
        RW_push set:a16i16
        phb
        lda     #0
        sta     f:$700000
        ldx     #0
        ldy     #1
        lda     #$FFFE
        mvn     #$70, #$70
        lda     #0
        sta     f:$710000
        ldx     #0
        ldy     #1
        lda     #$FFFE
        mvn     #$71, #$71
        plb
.if PLAYABLE_MAP_ID = PLAYABLE_E1M1_MAP_ID
        jsr     CampaignWrite
.endif
        RW_pull
        rtl
.include "quake/CampaignTransfer.s"
.popseg

; JSL followed by {far MSU offset, far destination, u16 byte length}.
; Match BSP_STATIC_COPY's A/X/Y clobber contract and preserve caller DB.
; No helper is called from NMI, so its seek and copy state are not shared.
PlayableCopyInline:
        RW_forced a16i16
        lda     1,s
        inc     a
        tax                             ; First descriptor byte.
        clc
        adc     #7
        sta     1,s                     ; RTL skips all eight inline bytes.
        RW      a8
        lda     3,s                     ; Descriptor's actual program bank.
        phb
        pha
        plb
        lda     playable_archive_busy
        beq     :+
        lda     #5
        jmp     PlayableArchiveFatal
:
        inc     playable_archive_busy
        ; Copy the template only on the first call after BootVector clears WRAM.
        lda     PlayableCopyKernel
        cmp     #$AD                    ; LDA absolute at template entry.
        beq     @KernelReady
        phx
        phb
        RW      a16
        lda     #PlayableCopyKernelEnd - PlayableCopyKernelTemplate - 1
        ldx     #.loword(PlayableCopyKernelTemplate)
        ldy     #.loword(PlayableCopyKernel)
        mvn     #^PlayableCopyKernelTemplate, #^PlayableCopyKernel
        plb
        plx
        RW      a8
@KernelReady:
        lda     a:$0000,x
        sta     playable_archive_seek
        inx
        lda     a:$0000,x
        sta     playable_archive_seek+1
        inx
        lda     a:$0000,x
        sta     playable_archive_seek+2
        stz     playable_archive_seek+3
        inx
        lda     a:$0000,x
        sta     PlayableCopyDestination
        inx
        lda     a:$0000,x
        sta     PlayableCopyDestination+1
        inx
        lda     a:$0000,x
        sta     PlayableCopyDestination+2
        inx
        RW      a16
        lda     a:$0000,x
        sta     playable_copy_remaining
        sta     PlayableCopyLength
        plb
        phb
        phk
        plb                             ; Module DB reaches LoRAM/MMIO mirrors.
        RW      a8
        jsr     PlayableEnsureArchive
        jsr     PlayableSeekArchive
        ldx     playable_copy_remaining
        beq     @Done
        ldx     #0
        jsl     PlayableCopyKernel
        bcs     @Done
        lda     #3
        jmp     PlayableArchiveFatal
@Done:
        stz     playable_archive_busy
        plb
        RW      a16
        rtl

; Every internal transfer is relative so the template executes unchanged in
; LoRAM. X stays 16-bit; STA.l,X carries into the next destination bank.
PlayableCopyKernelTemplate:
        RW_assume a8i16
        lda     a:$2001
        sta     playable_copy_value
        eor     a:$2001
        inc
        bne     PlayableCopyKernelBadPair
        lda     playable_copy_value
PlayableCopyKernelStore:
        sta     f:$000000,x
PlayableCopyKernelAfterStore:
        inx
PlayableCopyKernelLimit:
        cpx     #$0000
PlayableCopyKernelAfterLimit:
        bne     PlayableCopyKernelTemplate
        sec
        rtl
PlayableCopyKernelBadPair:
        clc
        rtl
PlayableCopyKernelEnd:
.assert PlayableCopyKernelEnd - PlayableCopyKernelTemplate <= PLAYABLE_COPY_KERNEL_CAPACITY, error, "Checked copy kernel exceeds LoRAM reservation"
.assert PlayableCopyKernelAfterStore - PlayableCopyKernelStore = 4, error, "Checked copy store operand changed"
.assert PlayableCopyKernelAfterLimit - PlayableCopyKernelLimit = 3, error, "Checked copy length operand changed"

.ifdef PLAYABLE_X3_SOFTWARE_WEAPON
; A16 entry/return, caller already owns the module DB mirror. Boot's
; static overlays initialized the checked LoRAM copy kernel.
X3WeaponSeekLong:
        RW_assume a16i16
        RW      a8
        lda     playable_archive_busy
        beq     :+
        lda     #5
        jmp     PlayableArchiveFatal
:
        inc     playable_archive_busy
        jsr     PlayableEnsureArchive
        jsr     PlayableSeekArchive
        RW      a16
        rtl
.endif

PlayableEnsureArchive:
        RW_assume a8i16
        lda     playable_archive_ready
        bne     @Ready
        ldx     #0
@Hardware:
        lda     f:$002002,x
        cmp     f:PlayableMsuSignature,x
        beq     :+
        lda     #1
        jmp     PlayableArchiveFatal
:
        inx
        cpx     #6
        bcc     @Hardware
        ; Header seek must not overwrite the requested payload's saved offset.
        lda     #0
        sta     f:$002000
        sta     f:$002001
        sta     f:$002002
        sta     f:$002003
        jsr     PlayableWaitArchiveReady
        ldx     #0
@Binding:
        lda     f:$002001
        cmp     f:PlayableArchiveExpected,x
        beq     :+
        lda     #2
        jmp     PlayableArchiveFatal
:
        inx
        cpx     #20
        bcc     @Binding
        lda     #1
        sta     playable_archive_ready
@Ready:
        rts

PlayableSeekArchive:
        RW_assume a8i16
.if PLAYABLE_MAP_ID = PLAYABLE_E1M1_MAP_ID
        ; The module DBR mirrors MSU MMIO. Each word write sends low
        ; then high, so $2003 still commits the complete seek last.
        ldy     playable_archive_seek
        sty     a:$2000
        ldy     playable_archive_seek+2
        sty     a:$2002
.else
        lda     playable_archive_seek
        sta     f:$002000
        lda     playable_archive_seek+1
        sta     f:$002001
        lda     playable_archive_seek+2
        sta     f:$002002
        lda     playable_archive_seek+3
        sta     f:$002003
.endif
PlayableWaitArchiveReady:
        RW_assume a8i16
        ldy     #$FFFF
@Busy:
        lda     f:$002000
        bpl     @Ready
        dey
        bne     @Busy
        lda     #4
        jmp     PlayableArchiveFatal
@Ready:
        rts

; Sticky failure telemetry is intentionally retained for an emulator probe.
PlayableArchiveFatal:
        phk                             ; Fatal may be called with the QuakeC DB=$7f.
        plb
        RW_forced a8i16
        sta     playable_archive_error
        sei
        stz     NMITIMEN
        stz     SFX_nmitimen
        stz     HDMAEN
        lda     #$80
        sta     INIDISP
        stz     TM
        stz     TS
        stz     CGADSUB
        stz     CGSWSEL
        stz     CGADD
        lda     #$1F
        sta     CGDATA
        lda     #$00
        sta     CGDATA
        lda     #$0F
        sta     SFX_inidisp
        sta     INIDISP
@Halt:
        stp
        bra     @Halt
.endif ; PLAYABLE_MAP_ID
