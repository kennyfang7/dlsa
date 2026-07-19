# 🔴 Red-Team Architecture Review

Reviewed as a skeptical senior quant: assuming the design was written by someone smart, and asking *where does it still lose money silently?* Findings are ordered by severity. Each one names the flaw, why the current design and test suite miss it, and the fix.

---

## SEVERITY 1 — Backtest-invalidating leaks the design doesn't close

### 1.1 In-sample factor estimation leaks the future into residuals

The daily workflow says "update factor model → extract today's residuals," and the retraining cadence says "factor model refit monthly." Combine those and you get the classic bug: **PCA/IPCA loadings estimated on a window that includes day t (or the whole month containing t), then used to compute the residual *at* t.**

**Why it's a leak (plain terms):** the eigenvectors of a covariance matrix computed through month-end "know" how stocks co-moved *after* day t. Residuals built with those loadings are contaminated by the future — mildly, which is the worst kind, because the backtest looks only slightly too good and nothing crashes.

**Why your tests miss it:** `test_asof_join_direction_is_backward` only tests `build_features`, not the residual path. And the white-noise canary is weak against this leak — in-sample PCA on homoskedastic noise barely improves next-day predictability, so Sharpe stays under the 1.0 threshold.

**Fix:** residuals at t must use loadings fit strictly on data ≤ t−1 (or ≤ end of *previous* refit period). Add a truncation-equivalence test on `compute_residuals`, mirroring the one you already have for `build_features`.

### 1.2 The PIT universe is only half the survivorship fix — the *price data* is still survivorship-biased

The architecture correctly demands a PIT constituent calendar, but the data layer is yfinance/Stooq, which **cannot serve full price histories for many delisted tickers.** In practice the tradable set becomes "PIT members ∩ names yfinance still has," which quietly reintroduces the bias the calendar was meant to kill — the intersection drops exactly the bankruptcies and worst acquirees.

Two sub-bugs ride along:
- **Missing delisting returns.** When a name dies, it just vanishes from the data. The backtest exits at the last observed price instead of eating the true delisting loss (often −30% to −100%). For a strategy that *buys losers* (fading negative residuals), this is a systematic upward bias on exactly your long book.
- The suite's `test_delisted_names_exist_historically` checks the *calendar*, not the *data*. It goes green while the backtest silently trades only survivors.

**Fix:** measure and report coverage — "% of PIT members on each date with usable prices" — and fail ingest below a threshold. Impute conservative delisting returns (e.g., −30% for performance-related delists) or at minimum flag PnL sensitivity to the assumption. Add a test asserting that some names in the price lake have truncated histories.

### 1.3 The HMM regime overlay uses the future unless inference is explicitly filtered

The build note says "fit the HMM only on data available up to each day," which covers *fitting* — but the bigger leak is *inference*. `hmmlearn`'s `predict()` runs Viterbi over the entire sequence: **the state assigned to day t depends on observations after t.** In backtest, the overlay would de-risk *before* crises with information no live system has, making the overlay look far better than it can ever perform live.

**Second failure mode — label switching:** after a monthly refit, hmmlearn's state indices can permute (state 0 was "calm," now it's "stressed"). A multiplier map keyed on state index silently inverts: full size in storms, quarter size in calm.

**Fix:** at each date use *filtered* probabilities only (forward algorithm on data ≤ t; `score_samples` on the truncated sequence, take the last row — never `predict` on the full sample). Map states to multipliers by sorted state volatility, never by index.

---

## SEVERITY 2 — Design flaws that will fire in production

### 2.1 Stale-bar poisoning passes your ingest validation

Validation checks "no missing names, no absurd returns." The common free-data failure is neither: **yfinance returns yesterday's bar again for some subset of names** (stale data, not missing). Those names show a clean 0.0% return, the signal net sees a flat residual, no alarm fires, and you trade on fiction. Worse, a stale price then produces a fake "jump" the next day — which looks exactly like the divergence your strategy loves to fade.

**Fix:** per-ticker last-update timestamp check against the exchange calendar; cross-source price diff (yfinance vs Stooq vs Alpaca) with a tolerance; quarantine names failing either, don't zero-fill them.

### 2.2 Multiplicative overlay stacking has no floor

Regime 0.25× × crowding 0.3× = 7.5% gross. At that size, per-name positions fall below any sensible minimum ticket; you'd still pay full-turnover rebalancing costs on a book too small for the edge to cover them. The overlays are individually safe ("only shrink") but jointly produce a state the design never considered.

**Fix:** a floor rule — if combined multiplier < 0.15, go flat and stop rebalancing rather than trade a homeopathic portfolio. The kill-switch section should own this state.

### 2.3 Kill-switch says "halt" but never says what happens to open positions

Auto-pause with a live market-neutral book isn't neutral for long — names drift, hedges decay, corporate actions hit. A halted-but-invested state is an *unmanaged* portfolio, which is worse than either trading or being flat.

**Fix:** every tripwire needs a position disposition: freeze (data-quality alerts) vs flatten (drawdown breach: exit at next open with a liquidation cost budget). Document who/what re-arms the system.

### 2.4 Cost-aware policy + hard turnover cap = trained and deployed in different worlds

Costs live *inside* the training objective (good) **and** portfolio construction applies a hard turnover budget after the fact. The deployed policy operates in a feasible set it was never trained on; the projection onto the turnover constraint reorders trades in ways the net never saw.

**Fix:** pick one owner for turnover — either train with the constraint (penalty calibrated so the cap rarely binds) and keep construction's cap as a safety rail, or drop the soft penalty and make the constraint explicit in both training and deployment.

### 2.5 News gate creates train/deploy distribution shift

The gate suppresses names post-8-K at *trade time*, but the signal/policy nets are trained on un-gated data. The training distribution contains exactly the post-news reversals the gate removes — the policy's learned aggressiveness is calibrated to a world it never trades in.

**Fix:** apply the gate as a data mask in training too, or at minimum backtest both ways and report the delta.

---

## SEVERITY 3 — Operational and epistemic gaps

**3.1 Back-adjusted prices mutate history.** yfinance adjusted closes are re-adjusted retroactively at every new split/dividend. Store raw + a corporate-actions table; adjust at read time. Never persist adjusted series.

**3.2 Sharpe-gap monitor and crowding monitor share an input.** Both consume live-vs-backtest gap; a data problem fires both and the post-mortem can't tell which mechanism acted. Give the crowding monitor distinct inputs (signal-decay autocorrelation, short interest).

**3.3 No embargo between training and deployment windows.** Rolling retrains with 30-day input windows mean the last training samples overlap the first live-decision windows. Purge ≥ the input-window length between train end and validation/deployment start.

**3.4 8-K timing is finer than a "day."** Filings land after the close; EDGAR's daily index is complete only late evening. Pin the gate's information time explicitly (e.g., filings accepted ≤ 4pm ET on t) so backtest and live agree.

**3.5 The canary's threshold is generous and its world is too gentle.** |Sharpe| < 1.0 lets mild leaks live, and the homoskedastic no-drift fixture is blind to vol-timing and drift-exploiting leaks by construction.

---

## What survives the attack

The three strongest design decisions hold up: overlays as shrink-only vetoes, one code path for backtest/paper/live, and the white-noise canary as a concept. Nothing above requires re-architecting — every fix slots into the existing boxes. The theme of the failures is consistent: **each component is individually safe, and the leaks live in the seams** — estimation windows, data coverage, inference direction, and train/deploy mismatches.
