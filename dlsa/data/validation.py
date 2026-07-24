"""
validate_frame — the write-gate for the data lake.

Contract (docs/01)
------------------
Every Parquet write in `dlsa/data/` must pass through `validate_frame`.
Rows that fail land in the report's `quarantined` frame; docs/02 non-
negotiable #1 requires them to be routed to `quarantine/`, never merged
into the lake.

Checks (docs/01)
----------------
1. Duplicate (ticker, date) inside the frame.
2. Negative prices or negative volumes.
3. |return| > 60% (D2) without a matching recorded corporate action.
4. Cross-source close disagreement > 50 bps (D1) — consults existing
   sources already written to the lake for the same (ticker, date).
5. Stale-bar check (N7, added 2026-07-18): identical OHLCV vs the prior
   session while ≥ 80% of the frame's tickers moved that day.
6. Adjustment-consistency (N1, added 2026-07-18):
      pct_change(close_adj) ≈ compute_returns(close_raw, actions)
   on overlapping coverage, within 1e-8.

Input shape
-----------
LONG-format DataFrame with the columns of docs/02's `prices` table
(ticker, date, open, high, low, close, volume, adj_factor, source,
ingested_at). See `dlsa/data/schemas.py::PRICES_SCHEMA`.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

from dlsa.data.returns import compute_returns
from dlsa.data.schemas import ValidationReport
from dlsa.data.universe import active_lake_dir

# D1 / D2 / N1 tolerances — frozen params.
_CROSS_SOURCE_TOL_BPS = 50.0  # D1
_ABSURD_RETURN_THRESHOLD = 0.60  # D2
_N1_ADJUSTMENT_TOL = 1e-8
_STALE_MOVE_UNIVERSE_FRACTION = 0.80  # N7


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalize_dates(s: pd.Series) -> pd.Series:
    """Coerce a date column to tz-aware UTC, normalized to day boundaries."""
    ts = pd.to_datetime(s, utc=True)
    return ts.dt.normalize()


def _lake_prices_path(lake_dir: Path | None) -> Path:
    lake = Path(lake_dir) if lake_dir is not None else active_lake_dir()
    return lake / "prices"


def _load_other_sources(
    tickers: set[str],
    dates: set[pd.Timestamp],
    source: str,
    lake_dir: Path | None,
) -> pd.DataFrame:
    """Load lake prices matching (ticker, date) from sources OTHER than `source`.

    Returns an empty frame if no other-source rows exist. Kept intentionally
    simple: reads all prices parquets under the lake and filters. Ingest will
    replace this with a DuckDB-backed query when the year-partitioned layout
    is live.
    """
    root = _lake_prices_path(lake_dir)
    if not root.exists():
        return pd.DataFrame(columns=["ticker", "date", "close", "source"])
    frames: list[pd.DataFrame] = []
    for parquet in root.rglob("*.parquet"):
        try:
            df = pq.read_table(parquet).to_pandas()
        except Exception:
            continue
        if df.empty or "source" not in df.columns:
            continue
        df = df[df["source"] != source]
        if df.empty:
            continue
        df["date"] = _normalize_dates(df["date"])
        df = df[df["ticker"].isin(tickers) & df["date"].isin(dates)]
        if not df.empty:
            frames.append(df[["ticker", "date", "close", "source"]])
    if not frames:
        return pd.DataFrame(columns=["ticker", "date", "close", "source"])
    return pd.concat(frames, ignore_index=True)


def _load_corporate_actions(
    lake_dir: Path | None,
) -> pd.DataFrame:
    """Load the corporate_actions lake table if present; else empty."""
    lake = Path(lake_dir) if lake_dir is not None else active_lake_dir()
    root = lake / "corporate_actions"
    if not root.exists():
        return pd.DataFrame(columns=["ticker", "date", "type", "ratio", "detail"])
    frames: list[pd.DataFrame] = []
    for parquet in root.rglob("*.parquet"):
        try:
            df = pq.read_table(parquet).to_pandas()
        except Exception:
            continue
        if not df.empty:
            frames.append(df)
    if not frames:
        return pd.DataFrame(columns=["ticker", "date", "type", "ratio", "detail"])
    return pd.concat(frames, ignore_index=True)


# ---------------------------------------------------------------------------
# Individual checks — each returns a boolean mask (True = fail) + an issue
# string, or (empty mask, None) when nothing fires.
# ---------------------------------------------------------------------------


def _check_duplicates(df: pd.DataFrame) -> tuple[pd.Series, str | None]:
    dup = df.duplicated(subset=["ticker", "date"], keep=False)
    if dup.any():
        return dup, f"duplicate (ticker, date) rows: {int(dup.sum())}"
    return pd.Series(False, index=df.index), None


def _check_negative_values(df: pd.DataFrame) -> tuple[pd.Series, str | None]:
    price_cols = [c for c in ("open", "high", "low", "close") if c in df.columns]
    neg = pd.Series(False, index=df.index)
    for c in price_cols:
        neg = neg | (df[c] < 0).fillna(False)
    if "volume" in df.columns:
        neg = neg | (df["volume"] < 0).fillna(False)
    if neg.any():
        return neg, f"negative price/volume rows: {int(neg.sum())}"
    return neg, None


def _check_absurd_returns(
    df: pd.DataFrame,
    corporate_actions: pd.DataFrame,
) -> tuple[pd.Series, str | None]:
    """|return| > 60% (D2) without a matching split action ⇒ fail."""
    if "close" not in df.columns:
        return pd.Series(False, index=df.index), None

    fail = pd.Series(False, index=df.index)
    for ticker, group in df.groupby("ticker", sort=False):
        g = group.sort_values("date")
        rets = g["close"].pct_change(fill_method=None).abs()
        big = rets > _ABSURD_RETURN_THRESHOLD
        if not big.any():
            continue
        # Split dates recorded for this ticker.
        split_dates: set[pd.Timestamp] = set()
        if not corporate_actions.empty:
            splits = corporate_actions[
                (corporate_actions["ticker"] == ticker)
                & (corporate_actions["type"] == "split")
            ]
            if not splits.empty:
                split_dates = set(_normalize_dates(splits["date"]).unique())
        # Fail rows whose date is not in the recorded split set.
        for idx in g.index[big.fillna(False).to_numpy()]:
            row_date = pd.Timestamp(g.at[idx, "date"])
            if row_date.tz is None:
                row_date = row_date.tz_localize("UTC")
            if row_date.normalize() not in split_dates:
                fail.at[idx] = True

    if fail.any():
        return fail, (
            f"absurd |return| > {_ABSURD_RETURN_THRESHOLD:.0%} without a "
            f"matching split action: {int(fail.sum())} rows"
        )
    return fail, None


def _check_cross_source(
    df: pd.DataFrame,
    source: str,
    lake_dir: Path | None,
) -> tuple[pd.Series, str | None]:
    """D1: > 50 bps close disagreement with another source at the same
    (ticker, date) ⇒ fail. No-op when no other-source rows exist yet."""
    if "close" not in df.columns:
        return pd.Series(False, index=df.index), None

    dates = set(_normalize_dates(df["date"]).unique())
    tickers = set(df["ticker"].unique())
    other = _load_other_sources(tickers, dates, source, lake_dir)
    if other.empty:
        return pd.Series(False, index=df.index), None

    df_norm = df.copy()
    df_norm["_date_norm"] = _normalize_dates(df_norm["date"])

    other_by_key = (
        other.groupby(["ticker", "date"], sort=False)["close"]
        .mean()
        .to_dict()
    )
    fail = pd.Series(False, index=df.index)
    for idx in df_norm.index:
        key = (df_norm.at[idx, "ticker"], df_norm.at[idx, "_date_norm"])
        other_close = other_by_key.get(key)
        if other_close is None or other_close <= 0:
            continue
        this_close = df_norm.at[idx, "close"]
        if pd.isna(this_close):
            continue
        bps = abs(this_close - other_close) / other_close * 1e4
        if bps > _CROSS_SOURCE_TOL_BPS:
            fail.at[idx] = True

    if fail.any():
        return fail, (
            f"cross-source close disagreement > {_CROSS_SOURCE_TOL_BPS:.0f} bps: "
            f"{int(fail.sum())} rows"
        )
    return fail, None


def _check_stale_bars(df: pd.DataFrame) -> tuple[pd.Series, str | None]:
    """N7: OHLCV identical to prior session while ≥ 80% of the frame's
    tickers moved that day ⇒ fail. Single-source rows always quarantine
    when both conditions hold (docs/01)."""
    ohlcv_cols = [
        c for c in ("open", "high", "low", "close", "volume") if c in df.columns
    ]
    if not ohlcv_cols or "close" not in df.columns:
        return pd.Series(False, index=df.index), None

    fail = pd.Series(False, index=df.index)
    df_sorted = df.sort_values(["ticker", "date"])

    # Per-ticker prior-session match.
    stale_by_row: dict[int, bool] = {}
    for ticker, group in df_sorted.groupby("ticker", sort=False):
        prev = group[ohlcv_cols].shift(1)
        matches = (group[ohlcv_cols] == prev).all(axis=1)
        for idx, is_stale in matches.items():
            has_nan = group.loc[idx, ohlcv_cols].isna().any()
            stale_by_row[idx] = bool(is_stale) and not has_nan

    # Per-date universe-movement fraction.
    df_dates = _normalize_dates(df["date"])
    for date in df_dates.unique():
        date_mask = df_dates == date
        date_slice = df.loc[date_mask]
        if len(date_slice) < 5:  # too small to meaningfully compute
            continue
        # For each ticker on this date, did it move? Compare vs prior close
        # per ticker.
        moved_count = 0
        total_count = 0
        for idx in date_slice.index:
            ticker = date_slice.at[idx, "ticker"]
            hist = df_sorted[df_sorted["ticker"] == ticker].sort_values("date")
            pos = hist.index.get_loc(idx)
            if pos == 0:
                continue
            prev_close = hist.iloc[pos - 1]["close"]
            this_close = hist.iloc[pos]["close"]
            if pd.isna(prev_close) or pd.isna(this_close) or prev_close == 0:
                continue
            total_count += 1
            if abs(this_close - prev_close) / abs(prev_close) > 0:
                moved_count += 1
        if total_count == 0:
            continue
        if moved_count / total_count < _STALE_MOVE_UNIVERSE_FRACTION:
            continue
        # ≥80% of the universe moved; quarantine any stale row.
        for idx in date_slice.index:
            if stale_by_row.get(idx, False):
                fail.at[idx] = True

    if fail.any():
        return fail, (
            f"stale OHLCV vs prior session while ≥ "
            f"{_STALE_MOVE_UNIVERSE_FRACTION:.0%} of universe moved: "
            f"{int(fail.sum())} rows"
        )
    return fail, None


def _check_n1_adjustment_consistency(
    df: pd.DataFrame,
    corporate_actions: pd.DataFrame,
) -> tuple[pd.Series, str | None]:
    """N1: pct_change(close_adj) must equal compute_returns(close_raw, actions)
    within 1e-8 on overlapping coverage. Disagreement quarantines the offending
    (ticker, date) rows on the close_adj-derived side."""
    if "close" not in df.columns or "adj_factor" not in df.columns:
        return pd.Series(False, index=df.index), None

    fail = pd.Series(False, index=df.index)

    # Build wide raw frame for compute_returns.
    dfw = df.copy()
    dfw["_date_norm"] = _normalize_dates(dfw["date"])
    dfw = dfw.dropna(subset=["_date_norm", "ticker"])

    try:
        raw_wide = dfw.pivot_table(
            index="_date_norm",
            columns="ticker",
            values="close",
            aggfunc="last",
        )
        adj_wide = dfw.assign(
            close_adj=lambda x: x["close"] * x["adj_factor"]
        ).pivot_table(
            index="_date_norm",
            columns="ticker",
            values="close_adj",
            aggfunc="last",
        )
    except Exception:
        return fail, None

    if raw_wide.empty or adj_wide.empty:
        return fail, None

    raw_rets = compute_returns(raw_wide, corporate_actions=corporate_actions)
    adj_rets = adj_wide.pct_change(fill_method=None)

    both = raw_rets.align(adj_rets, join="inner")
    if not both[0].shape[0]:
        return fail, None
    diff = (both[0] - both[1]).abs()
    bad = diff > _N1_ADJUSTMENT_TOL

    if not bad.any().any():
        return fail, None

    # Map failing (date, ticker) cells back to row indices.
    for date in bad.index[bad.any(axis=1)]:
        bad_row = bad.loc[date]
        bad_tickers = bad_row.index[bad_row.fillna(False)].tolist()
        for ticker in bad_tickers:
            match = dfw[(dfw["_date_norm"] == date) & (dfw["ticker"] == ticker)]
            for idx in match.index:
                fail.at[idx] = True

    if fail.any():
        return fail, (
            f"N1 adjustment-consistency: |pct_change(close_adj) − "
            f"compute_returns(close_raw)| > {_N1_ADJUSTMENT_TOL:g} on "
            f"{int(fail.sum())} rows"
        )
    return fail, None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def validate_frame(
    df: pd.DataFrame,
    source: str,
    lake_dir: Path | None = None,
    corporate_actions: pd.DataFrame | None = None,
) -> ValidationReport:
    """Run every write-gate check on a long-format prices frame.

    Parameters
    ----------
    df:
        Long-format prices frame per docs/02 (`ticker, date, open, high, low,
        close, volume, adj_factor, source, ingested_at`).
    source:
        The vendor writing this batch (`yfinance` | `stooq` | `alpaca`).
        Used for the D1 cross-source check.
    lake_dir:
        Override the active lake dir (tests). Cross-source and corp-actions
        lookups honor this.
    corporate_actions:
        Optional in-memory action frame. When None, `validate_frame` reads
        from the lake's `corporate_actions/` table (empty when the table
        does not yet exist).
    """
    if df.empty:
        return ValidationReport(passed=True, quarantined=df.iloc[:0].copy(), issues=[])

    if corporate_actions is None:
        corporate_actions = _load_corporate_actions(lake_dir)

    issues: list[str] = []
    fail_masks: list[pd.Series] = []

    for check_fn, args in (
        (_check_duplicates, (df,)),
        (_check_negative_values, (df,)),
        (_check_absurd_returns, (df, corporate_actions)),
        (_check_cross_source, (df, source, lake_dir)),
        (_check_stale_bars, (df,)),
        (_check_n1_adjustment_consistency, (df, corporate_actions)),
    ):
        mask, issue = check_fn(*args)
        if issue:
            issues.append(issue)
        fail_masks.append(mask)

    combined = fail_masks[0]
    for m in fail_masks[1:]:
        combined = combined | m

    quarantined = df.loc[combined].copy()
    passed = not combined.any()
    return ValidationReport(passed=passed, quarantined=quarantined, issues=issues)
