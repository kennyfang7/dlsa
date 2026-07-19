"""
Walk-forward backtest engine.

This is the ONLY code path that produces reported performance (V1).
The CPCV selection harness (dlsa/selection/) may reuse components but
never produces gate numbers — those come from run_backtest() only.

Shift convention: signals computed from day-t close trade at day-(t+1)
close. The engine must enforce .shift(1) alignment; result.meta must
report signal_to_trade_lag_days >= 1.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd


@dataclass
class BacktestResult:
    """Output of a single walk-forward backtest run."""

    sharpe: float
    positions: dict[pd.Timestamp, pd.Series] = field(default_factory=dict)
    meta: dict = field(default_factory=dict)


def run_backtest(
    prices: pd.DataFrame,
    config: str,
    shuffle_forward_returns: bool = False,
) -> BacktestResult:
    """Run a full walk-forward backtest.

    Parameters
    ----------
    prices:
        OHLCV or close prices for the universe, tz-aware UTC index.
    config:
        Path to a YAML config file (e.g. 'configs/test_min.yaml').
    shuffle_forward_returns:
        Test hook: randomly permute the mapping between signals and
        next-day returns. Any 'performance' that survives this shuffle
        never came from prediction. Must be accepted regardless of config.

    Returns
    -------
    BacktestResult with sharpe, positions, and meta dict containing at
    minimum {'signal_to_trade_lag_days': int}.
    """
    raise NotImplementedError("run_backtest: not yet implemented")
