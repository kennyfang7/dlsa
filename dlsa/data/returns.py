"""
Simple daily returns from RAW close prices + corporate actions.

Contract (docs/01)
------------------
- Applies split/dividend adjustment internally from `corporate_actions`;
  a 4:1 split day returns ~0.0, not −75%.
- A NaN price at t produces NaN returns at BOTH t and t+1, never 0.0.
  No forward-filling, ever.
- Never mutates the input frame.
- Absurd moves without a matching recorded corporate action are marked
  NaN — the unrecorded-split trap must not silently ship a fake crash to
  the signal net (D2, frozen param — 60% threshold).

Frame shape
-----------
- Input `prices`: wide DataFrame, DatetimeIndex × ticker columns, RAW close.
- Input `corporate_actions`: LONG format with columns
  (ticker, date, type in {'split', 'dividend', 'symbol_change'}, ratio, detail).
- Output: same shape as `prices`, simple daily returns (float).
"""

from __future__ import annotations

import pandas as pd

# D2 (docs/04): |ret| above this without a matching corporate action is
# treated as an unrecorded split / bad print and returned as NaN.
_ABSURD_RETURN_THRESHOLD = 0.60


def _align_date(ts, index_tz) -> pd.Timestamp:
    """Coerce a corporate-action date to match the price index's tz-mode."""
    ts = pd.Timestamp(ts)
    if index_tz is None:
        if ts.tz is not None:
            ts = ts.tz_convert(None)
    else:
        if ts.tz is None:
            ts = ts.tz_localize(index_tz)
        else:
            ts = ts.tz_convert(index_tz)
    return ts.normalize()


def compute_returns(
    prices: pd.DataFrame,
    corporate_actions: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Compute daily simple returns from RAW close prices.

    Splits and dividends in `corporate_actions` are applied backward so the
    action-date return reflects true P&L (~0 on the split day). Rows spanning
    a NaN price are NaN (both the NaN row and the following row) — no
    forward-filling. Moves whose |return| exceeds the D2 threshold (60%)
    without a matching split action are set to NaN — an unrecorded split
    must not print a fake crash the signal net can fade.
    """
    if prices.empty:
        return prices.copy()

    # Never mutate input.
    adj = prices.copy().astype("float64")
    index_tz = adj.index.tz
    index_normalized = adj.index.normalize()

    split_dates: set[tuple[str, pd.Timestamp]] = set()

    if corporate_actions is not None and len(corporate_actions) > 0:
        required = {"ticker", "date", "type", "ratio"}
        missing = required - set(corporate_actions.columns)
        if missing:
            raise ValueError(
                f"corporate_actions missing columns: {sorted(missing)}"
            )
        for _, row in corporate_actions.iterrows():
            ticker = row["ticker"]
            if ticker not in adj.columns:
                continue
            action_type = row["type"]
            action_date = _align_date(row["date"], index_tz)

            if action_type == "split":
                ratio = float(row["ratio"])
                if ratio <= 0:
                    continue
                mask = index_normalized < action_date
                adj.loc[mask, ticker] = adj.loc[mask, ticker] / ratio
                split_dates.add((ticker, action_date))

            elif action_type == "dividend":
                # Convention: back-adjust pre-ex-date closes by
                #   factor = 1 − div / close_just_before_ex
                div = float(row["ratio"])
                if div <= 0:
                    continue
                pre = adj.loc[index_normalized < action_date, ticker].dropna()
                if pre.empty:
                    continue
                close_before = float(pre.iloc[-1])
                if close_before <= 0:
                    continue
                factor = 1.0 - div / close_before
                if factor <= 0:
                    continue
                mask = index_normalized < action_date
                adj.loc[mask, ticker] = adj.loc[mask, ticker] * factor
            # symbol_change: no price effect (handled in identifier_map).

    # Simple daily returns. fill_method=None makes NaN propagate through the
    # next row as well (r[t+1] uses p[t] as denominator; NaN denominator
    # yields NaN).
    returns = adj.pct_change(fill_method=None)

    # D2: absurd moves without a matching recorded split ⇒ NaN.
    if _ABSURD_RETURN_THRESHOLD is not None:
        absurd = returns.abs() > _ABSURD_RETURN_THRESHOLD
        if absurd.any().any():
            # Iterate only over columns that have at least one flagged row.
            flagged_cols = absurd.columns[absurd.any(axis=0)]
            for ticker in flagged_cols:
                col_mask = absurd[ticker].fillna(False)
                if not col_mask.any():
                    continue
                for date in returns.index[col_mask]:
                    key = (ticker, date.normalize())
                    if key not in split_dates:
                        returns.at[date, ticker] = float("nan")

    return returns
