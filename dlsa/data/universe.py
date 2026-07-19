"""
PIT (point-in-time) universe calendar.

get_universe(date) is the ONLY permitted way to look up universe membership.
Never iterate over a current constituent list or a DataFrame of all tickers.
"""

from __future__ import annotations

import pandas as pd


def get_universe(date: pd.Timestamp) -> list[str]:
    """Return the list of universe members as of `date` (point-in-time).

    For synthetic test fixtures (source: fixture_all), returns the tickers
    present in the supplied prices index. Real implementation reads from
    data_lake/raw/sp500_pit_membership.csv.
    """
    raise NotImplementedError("get_universe: PIT calendar not yet implemented")


def latest_universe_date() -> pd.Timestamp:
    """Return the latest date for which the PIT calendar has an entry."""
    raise NotImplementedError("latest_universe_date: PIT calendar not yet implemented")


def calendar_available() -> bool:
    """Return True if the PIT constituent calendar is populated (gate G0.1)."""
    return False
