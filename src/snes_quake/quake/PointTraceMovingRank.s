; Refresh derived thresholds after loading a map or invalidating point traces.
.assert PLAYABLE_SHOT_MOVING_RANK_BYTES .mod 4 = 0, error, "Invalid point rank row size"
SHOT_MOVING_RANK_BYTES = PLAYABLE_SHOT_MOVING_RANK_BYTES / 2
.assert SHOT_MOVING_RANK_BYTES <= POINT_MOVING_RANK_BYTES, error, "Point rank table exceeds WRAM"

.pushseg
.segment "BSP_CPU_WALK_RUN"
ShotRefreshMovingRanks:
        RW_assume a16i16
        phx
        phy
        ldx     #0
@Next:
        lda     f:ShotMovingRankRows,x
        tay
        lda     a:.loword(qc_sd_offsets),y
        cmp     #$8000
        ror                             ; The original point loader rounds Q4 down.
        clc
        adc     f:ShotMovingRankRows+SHOT_MOVING_RANK_BYTES,x
        eor     #$7fff                  ; Match the reverse-biased endpoint order.
        sta     a:point_moving_ranks,x
        inx
        inx
        cpx     #SHOT_MOVING_RANK_BYTES
        bcc     @Next
        ply
        plx
        rtl

ShotMovingRankRows:
        .incbin "Data/PlayableShotMovingRanks.bin"
.assert *-ShotMovingRankRows = PLAYABLE_SHOT_MOVING_RANK_BYTES, error, "Point rank ROM extent changed"
.popseg
