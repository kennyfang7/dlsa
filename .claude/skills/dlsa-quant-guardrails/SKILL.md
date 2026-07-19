# DLSA Quant Guardrails

Loaded automatically when working in `dlsa/factors/`, `dlsa/signals/`, or
`dlsa/policy/`. Read `references/dlsa-methodology.md` before implementing
anything in these paths.

---

## Prime directives

1. **Point-in-time everywhere.** Every number used at date t must have been
   knowable at t. Residuals at t use loadings fit on data ≤ end of the
   *previous* refit period — never the window containing t.

2. **Signal path is fixed and ordered.** signal net → ensemble mean (V3) →
   `shrink()` (V5) → policy → `build_portfolio` → overlays. Do not collapse
   the ensemble to one seed, skip shrinkage, or let the policy read
   pre-shrinkage signals. λ and the seed list are frozen params.

3. **Backtest and live share one code path.** Portfolio construction lives in
   `dlsa/backtest/portfolio.py`. Never fork a "faster" or "simpler" live copy.

4. **Overlays only shrink.** Multipliers are clamped to (0, 1]. Any code path
   that could produce a multiplier > 1 is a bug.

5. **If a leakage test fails, fix the code.** Never relax a test threshold or
   delete a test. A Sharpe > ~3 net of costs on real data is a red flag to
   investigate, not celebrate.

6. **Fail closed.** On data-quality failure or tripwire, halt and alert.
   Never trade on a guess or a forward-fill.

---

## Trap list (from Red-Team Architecture Review)

### Severity 1 — Backtest-invalidating

**Trap 1.1 — Stale-eigenvector leak (in-sample factor estimation)**
PCA/IPCA loadings estimated on a window that *includes* day t contaminate the
residual at t with future co-movement. Fix: loadings used for residual at t
must come from a window ending strictly before t's refit period.
Test: `TestResidualCausality.test_residuals_invariant_to_future_truncation`

**Trap 1.2 — Survivorship in the price data, not just the calendar**
A PIT constituent calendar is necessary but not sufficient. yfinance/Stooq
drop many delisted names, so the tradable set silently becomes
"PIT members ∩ names still available" — dropping exactly the bankruptcies.
Missing delisting returns bias the long book upward for a momentum-fading
strategy. Test: coverage ≥ 98% of PIT members with usable prices (gate G0.1).

**Trap 1.3 — Smoothed HMM inference (hmmlearn `predict` uses the future)**
`hmmlearn.predict()` runs Viterbi over the entire sequence; state at t uses
observations after t. Use *filtered* probabilities only: run the forward
algorithm on data truncated at t (`score_samples`), take the last row.
Second failure: state indices permute across refits — always map by sorted
state volatility, never by raw index.
Test: `TestRegimeVintageAndInference`

### Severity 2 — Will fire in production

**Trap 2.1 — Stale-bar poisoning (0% return ≠ missing)**
yfinance sometimes returns yesterday's bar again. The bar looks clean (no
missing, no absurd return), but it's fiction. Fix: per-ticker last-update
timestamp vs. exchange calendar; cross-source price diff.

**Trap 2.2 — Overlay floor missing**
Regime 0.25× × crowding 0.3× = 7.5% gross. At that size rebalancing costs
exceed any edge. If combined multiplier < 0.15, go flat and stop rebalancing.

**Trap 2.3 — Kill-switch with no position disposition**
Every tripwire needs a stated action: freeze (data-quality alert) vs. flatten
(drawdown breach). Halted-but-invested is an unmanaged portfolio.

**Trap 2.4 — Cost-aware training + hard turnover cap = two different worlds**
The policy is trained with soft cost penalty; construction applies a hard cap.
The policy operates in a feasible set it never trained on. Pick one turnover
owner: train with the constraint (and keep construction's cap as a safety rail)
or make the constraint explicit in both training and deployment.

**Trap 2.5 — News gate train/deploy distribution shift**
Gating names post-8-K at trade time but training on un-gated data means the
policy's aggressiveness is calibrated to a distribution it never actually trades
in. Apply the gate as a data mask in training, or measure and report the delta.

### Severity 3 — Operational

**Trap 3.1** — Never persist adjusted prices; store raw + corporate-actions
table and adjust at read time. yfinance adjusted closes mutate retroactively.

**Trap 3.2** — Crowding and Sharpe-gap monitors must have distinct inputs or
a data problem fires both and the post-mortem is ambiguous.

**Trap 3.3** — Embargo ≥ input-window length (30 days) between train end and
validation/deployment start, or rolling retrain windows overlap.

**Trap 3.4** — 8-K timing is finer than a day; pin the gate's information time
explicitly (e.g., filings accepted ≤ 4 pm ET on t) so backtest and live agree.

**Trap 3.5** — The constant-vol canary (|Sharpe| < 1.0) is blind to
vol-timing and drift-exploiting leaks. The regime-switching fixture
(`regime_noise_prices`) with threshold 0.8 closes this gap.

---

## Repo map for these paths

```
dlsa/factors/         PCA / IPCA factor models → residuals
  pca.py              PCAFactorModel — implements residuals(prices, asof),
                      loading_fit_end_dates, preprocess(prices, train_end),
                      build_features(prices, asof), fit_scaler(prices, train_end)
  ref_ipca.py         Reference ALS implementation (Fable-window deliverable)

dlsa/signals/         CNN+Transformer signal network (PyTorch)
  model.py            SignalEnsemble.from_registry — 5-seed ensemble (V3)
  shrinkage.py        fit_shrinkage_stats(signals, fit_end) → ShrinkageStats
                      shrink(s, asof, stats) → pd.Series  [V5, EB shrinkage]

dlsa/policy/          Cost-aware allocation network
  network.py          PolicyNet — trained by net Sharpe (M1/M3, metrics.py)

dlsa/backtest/
  portfolio.py        build_portfolio — THE shared construction path
  engine.py           run_backtest — THE shared backtest/live engine
  dates.py            DecisionAlignment, walk_forward_folds, assert_feature_window_legal

reference/
  ref_policy_training.py   Cost-aware training loop (Fable-window deliverable)
  ref_walkforward_dates.py Walk-forward date alignment (Fable-window deliverable)
```

**Architecture reference:** `references/dlsa-methodology.md` (load before
implementing anything in factors/, signals/, or policy/).
