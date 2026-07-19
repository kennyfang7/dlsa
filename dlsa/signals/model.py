"""
5-seed CNN+Transformer signal ensemble (V3).

SignalEnsemble wraps the individual seed models and exposes a single
predict() that aggregates all members. A silently dropped seed changes
the deployed model without a version bump — the ensemble manifest is
the source of truth for membership.
"""
