"""
Empirical-Bayes shrinkage layer (V5).

fit_shrinkage_stats(member_signals, fit_end) estimates λ from the
cross-seed signal dispersion up to fit_end. shrink(s, asof, stats)
applies the shrinkage: |shrink(s)| <= |s| element-wise always.

Estimator fits on MEMBER SIGNALS (MultiIndex date×seed), never prices.
λ and seed count are frozen params; re-estimation is causal.
"""
