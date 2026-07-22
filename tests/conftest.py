"""
Session-scoped test setup.

Ensures the PIT universe membership log exists in the default lake before
any test runs. The source CSV (`data_lake/raw/sp500_pit_membership.csv`)
is committed; the derived parquet is NOT — it is regenerated deterministically
from the CSV on first test invocation.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dlsa.data.universe import (
    active_lake_dir,
    calendar_available,
    ingest_membership_csv,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
MEMBERSHIP_CSV = REPO_ROOT / "data_lake" / "raw" / "sp500_pit_membership.csv"


@pytest.fixture(scope="session", autouse=True)
def _seed_pit_universe():
    """Ingest the committed PIT membership CSV into the active lake once
    per test session. No-op if the parquet is already populated (idempotent)."""
    if calendar_available():
        return
    if not MEMBERSHIP_CSV.exists():
        pytest.skip(
            f"PIT membership CSV missing at {MEMBERSHIP_CSV} — "
            "cannot seed universe lake"
        )
    ingest_membership_csv(MEMBERSHIP_CSV, lake_dir=active_lake_dir())
