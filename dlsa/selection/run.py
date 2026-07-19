"""
CLI entrypoint for make select (V4 CPCV model selection).

Usage: python -m dlsa.selection.run --candidates configs/candidates/

Outputs ranked-candidate SelectionReport objects; never tearsheets.
The selection firewall is enforced here: no BacktestResult, no 'sharpe' field.
"""
