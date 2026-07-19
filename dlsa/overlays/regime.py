"""
Regime HMM overlay (O5/O8) — DORMANT until Phase 2.

Uses FILTERED probabilities only: forward algorithm on data truncated at t,
never hmmlearn.predict() which runs Viterbi over the full sequence (smoothed).
States are relabeled by realized volatility after every refit so that
calm/normal/stressed map to ascending state-mean vol, never by raw index.

Multiplier range: [0.25, 1.0] — overlays only shrink.
"""
