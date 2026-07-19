"""
Walk-forward date alignment and window bookkeeping.

DecisionAlignment enforces the shift convention:
  signals computed from day-t close → trade at day-(t+1) close.

walk_forward_folds(index, ...) yields (train, val, test) windows with
de Prado purge gap between train and test.

assert_feature_window_legal(feature_date, asof) raises LookAheadError
if any feature timestamp is after the as-of date.

Reference implementation: reference/ref_walkforward_dates.py
"""
