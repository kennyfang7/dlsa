---
paths:
  - "dlsa/backtest/**/*.py"
  - "dlsa/factors/**/*.py"
  - "dlsa/signals/**/*.py"
  - "dlsa/policy/**/*.py"
---

# Backtest & Modeling Rules — Point-in-Time Discipline

These files decide whether the backtest is real or fiction. Look-ahead bias
here produces fake alpha that silently survives until live trading loses money.

## Hard rules

- **Every feature at date t uses data ≤ t.** When joining datasets, join on
  "date the information became AVAILABLE" (publication/filing date), never the
  period it refers to. Fundamentals for Q2 are not knowable on June 30.
- **Universe lookups go through `get_universe(date)`** — never iterate over a
  DataFrame of all tickers, never use a hardcoded ticker list.
- **Normalization is causal.** Any scaler/z-score/rank is fit on the training
  window only, then applied forward. Fitting statistics on the full sample is
  leakage even if it "looks harmless."
- **Walk-forward only.** Model selection, hyperparameters, and early stopping
  use a validation window that PRECEDES the test window. Never tune on the
  test period, never report the best of several test-period runs.
- **`pd.merge_asof` direction is `backward`** for as-of joins. A `forward` or
  `nearest` as-of join on market data is almost always look-ahead.
- **Shifting convention:** signals computed from day t close trade at t+1
  close — on-close orders only (`time_in_force=cls`, submitted the evening of
  t, filled in the t+1 closing auction, per frozen param E6). There is no
  open-fill path; if you see a return alignment without an explicit
  `.shift(1)`, treat it as a bug until proven otherwise.

## When editing here

1. If you change any date logic, join, or window: run `make test-leakage`
   before considering the task done, and say so in your summary.
2. If a leakage test fails, fix the code — NEVER relax the test threshold or
   delete the test.
3. If asked to "improve backtest performance," first check whether the
   improvement comes from leakage (suspiciously high Sharpe > ~3 net of costs
   is a red flag to investigate, not celebrate).
4. Do not add new data sources inside these modules; ingestion belongs in
   `dlsa/data/` where validation runs.
5. The signal path is FIXED: signal net → ensemble mean (V3) → shrink() (V5)
   → policy → build_portfolio → overlays. Do not "simplify" by removing the
   shrinkage stage, collapsing the ensemble to one seed, or letting the
   policy read pre-shrinkage signals. λ and the seed list are frozen params.
