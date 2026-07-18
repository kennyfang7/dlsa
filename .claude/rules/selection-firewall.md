---
paths:
  - "dlsa/selection/**/*.py"
---

# Selection Harness Rules — Chooses Configs, Never Reports Performance

CPCV exists to stop overfitting; a CPCV harness with buggy purging is a
leakage machine wearing an anti-overfitting costume. These rules keep it honest.

## Hard rules

- **Purge and embargo are frozen (V4):** 8 groups, 2 test groups, purge = 60
  trading days, embargo = 10. Never narrow them to "get more data."
- **No fold may violate PIT:** every train/test split respects the same
  available_at discipline as the simulator; the hardened purge test must pass.
- **Outputs go to `runs/selection/` only** — never `runs/backtests/`. A
  selection run is not a V1 trial; the chosen config's subsequent walk-forward
  run is.
- **Never import or monkey-patch the walk-forward engine's reporting.**
  SelectionReport has no `sharpe`-named field by design; do not add one.
- **Gate numbers come from `run_backtest` only.** If a task asks you to quote
  selection-path performance as a result, refuse and point at G1.6.
- **Vendor-intake data enters this harness ONLY inside an explicit D7
  ablation** (model-with vs. model-without for that one source, adopted on
  deflated-Sharpe uplift with PBO in bound). It may never silently ride along
  as an input to unrelated selections — the quarantine (Test 20) applies to
  selection as much as to training.
