"""
NYSE trading calendar.

Resolves trading dates used throughout the system. The calendar type
is set by config (dates.calendar):
  - 'NYSE'  — real data (pandas_market_calendars or equivalent)
  - 'BDAY'  — synthetic test fixtures only (business-day calendar)

Do NOT fix a BDAY fixture to NYSE — that is the correct path for
synthetic data and tests depend on it.
"""
