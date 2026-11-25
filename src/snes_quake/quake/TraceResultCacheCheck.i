        stz     a:w_entrance_probe_owner
        lda     a:qc_exit_collision_dirty
        beq     :+
        jsl     ::InvalidateTraceResultCache
:
