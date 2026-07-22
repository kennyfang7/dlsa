"""
NYSE trading calendar.

Resolves trading dates used throughout the system. The calendar type
is set by config (dates.calendar):
  - 'NYSE'  — real data (pandas_market_calendars)
  - 'BDAY'  — synthetic test fixtures only (business-day calendar)

Do NOT fix a BDAY fixture to NYSE — that is the correct path for
synthetic data and tests depend on it.

All returned indexes are tz-aware UTC per the docs/01 global convention.
"""

from __future__ import annotations

from typing import Literal

import pandas as pd
import pandas_market_calendars as mcal

CalendarType = Literal["NYSE", "BDAY"]


def _normalize(ts: pd.Timestamp) -> pd.Timestamp:
    """Coerce to tz-aware UTC and drop time-of-day (dates are day-keyed)."""
    ts = pd.Timestamp(ts)
    if ts.tz is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    return ts.normalize()


def trading_days(
    start: pd.Timestamp,
    end: pd.Timestamp,
    calendar: CalendarType = "NYSE",
) -> pd.DatetimeIndex:
    """Return the trading days in [start, end] for the requested calendar.

    Returns a tz-aware UTC DatetimeIndex. Inclusive on both ends.
    """
    s = _normalize(start)
    e = _normalize(end)
    if calendar == "BDAY":
        return pd.bdate_range(s, e, tz="UTC")
    if calendar == "NYSE":
        cal = mcal.get_calendar("NYSE")
        # valid_days returns tz-aware UTC DatetimeIndex normalized to session dates.
        return cal.valid_days(start_date=s, end_date=e).tz_convert("UTC")
    raise ValueError(f"unknown calendar type: {calendar!r} (expected 'NYSE' or 'BDAY')")


def is_trading_day(date: pd.Timestamp, calendar: CalendarType = "NYSE") -> bool:
    """Return True if `date` is a trading day on the requested calendar."""
    d = _normalize(date)
    return d in trading_days(d, d, calendar=calendar)


def previous_trading_day(
    date: pd.Timestamp, calendar: CalendarType = "NYSE"
) -> pd.Timestamp:
    """Return the last trading day <= `date` on the requested calendar."""
    d = _normalize(date)
    # Look back up to 10 calendar days — covers any weekend/holiday cluster.
    window = trading_days(d - pd.Timedelta(days=10), d, calendar=calendar)
    if len(window) == 0:
        raise ValueError(f"no trading day found on or before {date!r}")
    return window[-1]
