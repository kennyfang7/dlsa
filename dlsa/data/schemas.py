"""
Column constants and the ValidationReport dataclass shared by the data layer.

Pandera schemas mirror docs/02 (prices, corporate_actions, delistings) and
gate every Parquet write via `dlsa/data/validation.py::validate_frame`.

Convention
----------
- prices/corporate_actions/delistings live in the lake as LONG format.
- validate_frame consumes long-format frames; the loader (P0.3+) turns them
  into wide, security_id-keyed modeling frames on read.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd
import pandera.pandas as pa

# ---------------------------------------------------------------------------
# ValidationReport
# ---------------------------------------------------------------------------


@dataclass
class ValidationReport:
    """Result of `validate_frame`.

    Attributes
    ----------
    passed:
        True iff `quarantined` is empty. Callers writing to the lake must
        refuse the write when passed=False and route `quarantined` to the
        `quarantine/` directory (docs/02 non-negotiable #1).
    quarantined:
        Rows from the input frame that failed one or more checks. Same
        schema as the input.
    issues:
        Human-readable list of issue descriptions, one per triggered check.
    """

    passed: bool
    quarantined: pd.DataFrame
    issues: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Column name constants (docs/02)
# ---------------------------------------------------------------------------

PRICES_COLS = (
    "ticker",
    "date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "adj_factor",
    "source",
    "ingested_at",
)

CORPORATE_ACTIONS_COLS = ("ticker", "date", "type", "ratio", "detail")

DELISTINGS_COLS = ("ticker", "last_trade_date", "reason", "terminal_return")

VALID_SOURCES = ("yfinance", "stooq", "alpaca")
VALID_ACTION_TYPES = ("split", "dividend", "symbol_change")


# ---------------------------------------------------------------------------
# Pandera schemas — enforced on read and write (docs/02)
# ---------------------------------------------------------------------------

# The prices schema uses coerce=True at the frame level so int32/int64/date
# variants from Parquet round-trips validate cleanly.
PRICES_SCHEMA = pa.DataFrameSchema(
    columns={
        "ticker": pa.Column(str, nullable=False),
        "date": pa.Column(
            "datetime64[ns, UTC]", nullable=False, coerce=True
        ),
        "open": pa.Column(float, nullable=True),
        "high": pa.Column(float, nullable=True),
        "low": pa.Column(float, nullable=True),
        "close": pa.Column(float, nullable=True),
        "volume": pa.Column(pa.Int64, nullable=True, coerce=True),
        "adj_factor": pa.Column(float, nullable=True),
        "source": pa.Column(
            str,
            checks=pa.Check.isin(VALID_SOURCES),
            nullable=False,
        ),
        "ingested_at": pa.Column(
            "datetime64[ns, UTC]", nullable=False, coerce=True
        ),
    },
    strict=False,
    coerce=True,
)

CORPORATE_ACTIONS_SCHEMA = pa.DataFrameSchema(
    columns={
        "ticker": pa.Column(str, nullable=False),
        "date": pa.Column(
            "datetime64[ns, UTC]", nullable=False, coerce=True
        ),
        "type": pa.Column(
            str,
            checks=pa.Check.isin(VALID_ACTION_TYPES),
            nullable=False,
        ),
        "ratio": pa.Column(float, nullable=True),
        "detail": pa.Column(str, nullable=True),
    },
    strict=False,
    coerce=True,
)
