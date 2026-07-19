"""
THE Sharpe implementation (frozen params M1/M3).

This is the single source of truth for Sharpe across the entire system:
  - training objective (policy net)
  - BacktestResult.sharpe
  - K2 live-vs-backtest monitor

Net daily returns: r_net_t = w_{t-1}' ε_t − c‖w_t − w_{t-1}‖₁
Sharpe: mean(r_net) / std(r_net)

Nothing else computes its own Sharpe. Do not duplicate this logic.
"""
