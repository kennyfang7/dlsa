"""
Combinatorial Purged Cross-Validation harness (V4).

cpcv_folds(index) yields (train_idx, test_idx) pairs with:
  - purge  >= 60 trading days  (V4 frozen param, in TRADING-DAY units)
  - embargo >= 10 trading days (V4 frozen param, in TRADING-DAY units)
  - train ∩ test == empty set

FIREWALL: SelectionReport must not expose a 'sharpe' field.
dlsa.selection must not import BacktestResult or any type from dlsa.backtest.
"""
