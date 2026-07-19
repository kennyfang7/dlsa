"""
CPCV model-selection harness (V4).

FIREWALL: this package selects configs; it NEVER produces reported performance.
Gate numbers come from dlsa/backtest/engine.py::run_backtest() only.
dlsa.selection must not import BacktestResult or any report type from
dlsa.backtest, and SelectionReport must not expose a 'sharpe' field.
"""
