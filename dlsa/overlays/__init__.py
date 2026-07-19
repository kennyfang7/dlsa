"""
Regime HMM, news gate, and crowding monitor overlays.

Invariant: every overlay multiplier is clamped to (0, 1].
Overlays may only REDUCE exposure, never increase it.
"""
