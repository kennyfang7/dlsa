"""
CLI entrypoint for make backtest.

Usage: python -m dlsa.backtest.run --config configs/backtest.yaml

Every run logs to MLflow: full config, git SHA, data-lake snapshot date,
net Sharpe, Deflated Sharpe + all-time trial count (V1), max DD, turnover,
and the QuantStats tearsheet HTML as an artifact.
"""
