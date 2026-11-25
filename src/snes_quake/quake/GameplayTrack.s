; Handle the audio-busy bit asynchronously on real MSU-1 hardware. Selecting
; a PCM track never moves the stream's independent graphics/data seek pointer.
GameplayPlayTrackLong:
        jsr     PowerupSelectTrack
        rtl

PowerupSelectTrack:
.ifdef QC_E1M1_TELEPORT
        stz     a:.loword(teleport_hum_playing)
.endif
.if .defined(QC_NAIL_COUNT) || .defined(QC_CAMPAIGN_ITEMS)
        sta     a:.loword(nail_msu_track)
.endif
        inc     a:.loword(quakec_sounds)
        sta     a:.loword(quad_msu_pending)
        sta     f:$002004
PowerupServiceTrack:
        lda     a:.loword(quad_msu_pending)
        beq     @Done
        RW      a8
        lda     f:$002000
        bit     #$40
        bne     @Busy
        bit     #$08
        bne     @Finish
        lda     #$ff
        sta     f:$002006
        lda     #1
.ifdef QC_E1M1_TELEPORT
        ldx     a:.loword(quad_msu_pending)
        cpx     #21
        bne     :+
        lda     f:teleport_hum_volume
        sta     f:$002006
        lda     #3                     ; Loop original ambience/hum1.wav.
:
.endif
        sta     f:$002007
@Finish:
        RW      a16
        stz     a:.loword(quad_msu_pending)
        rts
@Busy:  RW      a16
@Done:  rts
