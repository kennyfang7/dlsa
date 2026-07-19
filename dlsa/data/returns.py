"""
Adjusted-close return computation.

Rules:
- Uses ADJUSTED prices for return computation, RAW prices for fills.
- Missing prices produce NaN returns + exclusion flag — never forward-filled.
- Corporate actions (splits, dividends) must produce near-zero returns on the
  action date, not phantom crashes/spikes.
"""

from __future__ import annotations

import pandas as pd


def compute_returns(
    prices: pd.DataFrame,
    corporate_actions: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Compute daily log returns from adjusted close prices.

    Parameters
    ----------
    prices:
        Raw close prices, shape (dates, tickers). May contain NaN.
    corporate_actions:
        DataFrame with columns [ticker, date, type, ratio]. Splits and
        dividends are applied before return computation so action-date
        returns reflect true economic P&L, not price discontinuities.

    Returns
    -------
    pd.DataFrame of the same shape as `prices`. Rows spanning a NaN price
    are NaN (both the NaN row and the following row), never imputed.
    """
    raise NotImplementedError("compute_returns: not yet implemented")
