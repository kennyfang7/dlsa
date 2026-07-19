"""
Off-machine backup (make backup, frozen param N11/E2/V1 durability riders).

Usage: python -m dlsa.ops.backup

Copies data_lake/journal.sqlite and data_lake/runs/ to BACKUP_REMOTE
(rclone/restic destination from .env). Run nightly alongside `daily`.
A disk loss must not silently reset n_trials or destroy the order audit trail.
Required before Phase 3; cheap from Phase 0.
"""
