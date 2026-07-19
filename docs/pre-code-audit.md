# 📐 Pre-Code Audit — Spec Seams & Market Mechanics

Third adversarial pass, run before the first line of code. Companion to the Red-Team Architecture Review (quant-methodology leaks: estimation windows, inference direction, train/deploy mismatches) and the Ops & Systems Review (order state, scheduling/time semantics, vendor risk). This pass hunts where neither looked: **the seams between the spec pages themselves, and between the strategy and the market's actual mechanics** — contract/test drift, constraint collisions, execution semantics, and design-level (not code-level) overfitting. Findings ordered by severity; the four Severity-1 items are Session-1 blockers. New frozen parameters this review implies are tagged with proposed IDs (E6–E7, C5–C7, D5–D6, O7–O8, F4, M4) plus amendments to O2, O6, K1, E2, M2 — see 04 — Frozen Parameters v1 and 01 — Interface Contracts.

---

## SEVERITY 1 — Session-1 blockers

### 1.1 The contracts and the hardened tests have already diverged — and the corpus's own rules make that a deadlock

Page 01 declares "the tests are the senior party"; page 09 mandates byte-for-byte materialization. But the Hardened Leakage Tests reference APIs that exist nowhere in the contracts:

- `compute_residuals(prices)` — the contract defines `residuals(prices, asof)`: different name **and** signature
- `PCAFactorModel.preprocess(prices, train_end)` — not in the contract
- `loading_fit_end_dates` attribute — not in the contract
- `run_backtest(..., signal_override="own_return")` — kwarg absent from the contract signature
- `result.portfolio_returns` — the contract field is `returns`
- `dlsa.config.load_config(...).resolved(key)` with keys like `engine_class` — no such API or keys anywhere in 03 — Config Specs
- `tests/fixtures/synthetic_calendar.py` / `SYNTH_CALENDAR.true_last_dates` — specified nowhere
- the `regime_noise_prices` fixture is **tz-naive** — the exact bug the 2026-07-12 verification pass fixed in Artifact 3 but not on the hardened-tests page

**Fix:** a reconciliation pass into pages 01/03 **before** any materialization — page 06's "diff before merging" note must become a full API reconciliation with change-log entries. Materializing as-is guarantees Claude Code hits contract/test conflicts in the first sessions and improvises — the precise failure mode this documentation system exists to prevent.

### 1.2 The regime overlay and the turnover cap are in direct numeric collision

A calm→stressed transition (O1: 1.0× → 0.25×) requires one-day L1 turnover of **75% of gross**. C2 caps daily turnover at **25%**. Nothing specifies precedence, so as written `build_portfolio` throttles the emergency de-risk to a three-day glide path — through exactly the crash the overlay exists for. Worse: filtered HMM state probabilities near a boundary flip day-to-day, so a discrete state→multiplier map produces repeated 75%-turnover whipsaw demands, leaving the cap permanently binding — the projection-onto-constraints world Red-Team 2.4 warned about, now driven by the safety layer itself.

**Fixes:** **C5 (proposed)** — risk-*reducing* trades are exempt from C2, with their own liquidation cost budget. **O8 (proposed)** — replace the argmax state multiplier with the probability-weighted expectation Σ pᵢ·mᵢ (or a hysteresis band): smooth, still ≤ 1.0, kills the whipsaw. Note also that Red-Team 2.5's train/deploy-shift argument generalizes: the policy net is trained with **no** overlay in the loop at all, not just no news gate.

### 1.3 "Execute at t+1 close" has no mechanism — and the wrong default silently invalidates the backtest (proposed E6)

The walk-forward alignment reference is explicit: decide after close(t), fill at close(t+1), earn close(t+1)→close(t+2). But the system runs once, in the evening — nothing specifies what instrument produces a t+1 **close** fill. Plain day limit orders submitted that evening fill near the t+1 *open*, making the close-to-close attribution wrong in the direction that flatters a mean-reversion signal (overnight reversion ≠ intraday reversion). The likely resolution is Alpaca's on-close time-in-force (`cls`, submitted the evening before) — but that is a decision to freeze, and it also defines the "execution window" that E3 references but never pins. **E6 (proposed):** order type + TIF + execution-window definition, verified against the account tier in `make broker-smoke`.

### 1.4 News gate: force-exit semantics, and unfiltered 8-Ks create quarterly blackouts (proposed O7; amend O2)

`build_portfolio` sets gated names to exactly 0.0 — so an **existing** position in a name that just filed an 8-K is fully liquidated the next day, trading into post-news spreads, then re-entered on day 4 (double turnover). That is "flatten," chosen implicitly; the defensible intent is "freeze" (hold, no new risk). **O7 (proposed):** gate disposition = freeze held positions / block new entries.

Separately, O2 gates on *any* 8-K, but most S&P names furnish earnings via item 2.02 in tight clusters — peak earnings weeks will gate a large fraction of the universe inside any trailing-3-day window, breaking diversification quarterly. The `items` column already exists in `filings_8k`; **amend O2** to a material-item subset. G2.3's *median*-day cap won't catch this: the median day is off-season.

---

## SEVERITY 2 — Fires in ordinary operation or evaluation

### 2.1 Design-level overfitting is the least-defended flank (proposed M4 + page-08 gate)

The corpus is armored against *code* leaking the future; the *design* has already seen it. G2.1 explicitly tunes overlay behavior against 2008/2020/2022 drawdowns and then grades itself on those same episodes; O1's multipliers, K=5, the 30-day window, and every threshold were chosen with full knowledge of the sample. No gate imposes a true holdout or a multiple-testing discipline (deflated Sharpe, Bailey–López de Prado) across the K-sensitivity and ablation grid. **M4 (proposed):** the final 18–24 months are a holdout untouched by any design iteration until one pre-registered run; and any parameter change during Phase 3 resets the G3 clock — paper trading is currently the only genuine out-of-sample and must be protected as such.

### 2.2 Micro-book arithmetic: minimum viable capital was never computed (proposed C6, C7)

~400 names, 3% max weight, gross ≤ 1.0 ⇒ typical position ≈ 0.25% of equity — ~$125/name on a $50k account, *before* overlays scale the book to a quarter or less. Integer share rounding then destroys dollar-neutrality, and Alpaca's fractional-share support carries order-type restrictions (verify current rules — historically market/day only, which conflicts with an on-close scheme). Red-Team 2.2's floor fires far earlier than the 0.15 multiplier implies. **C6 (proposed):** minimum ticket size. **C7 (proposed):** max positions N — trade the top-N signals rather than the full cross-section — plus a stated capital floor below which the strategy is definitionally not runnable.

### 2.3 G3.2 validates Alpaca's fill simulator, not the market (amend G3.2)

Paper fills are simulated against quotes with no impact or queue modeling and are known to be optimistic; "realized slippage within 50% of X1" can pass on paper and fail live. Treat paper slippage as a **lower bound**; honest X1 calibration comes from independently computed arrival-price slippage, or from the first tiny live tranche.

### 2.4 IPCA walk-forward compute profile (proposed F4)

`_factors_given_gamma` loops over every period per ALS iteration, in Python. Monthly walk-forward over 20 years ≈ 240 refits × up to 200 iterations × thousands of periods — multiplied again by the K-sensitivity grid and ablations. The reference is correct but will turn `make backtest` into an overnight job. **F4 (proposed):** warm-start Γ from the previous refit — cuts iterations dramatically *and* reduces refit-to-refit subspace rotation (the IPCA cousin of O5's label-switching fix). Add a profiling task before the Phase 1 experiment grid.

---

## SEVERITY 3 — Determinism, definition, and coverage holes

**3.1 Golden-source priority (proposed D5).** Prices are stored per (ticker, date, source), but no rule pins which source is canonical when they agree within D1's 50 bps. A later Stooq backfill could silently shift modeled prices within tolerance. Freeze a priority order.

**3.2 Delisting terminal-return imputation (proposed D6).** Red-Team 1.2's fix (impute a conservative delisting return, e.g. −30% for performance-related delists) was never translated into a frozen parameter — unlike the Ops review's E1–E5. G0.1 covers coverage %, not the imputation value.

**3.3 K1 measurement basis (amend K1).** "10% of deployed capital" has no anchor: inception high-water mark, trailing window, or since last resume? Same class of ambiguity M1 fixed for Sharpe.

**3.4 O6's "daily aggregate signal" is ambiguous (amend O6).** The cross-sectional mean of a demeaned book is ≈ 0 by construction. Pin the exact series (e.g., lag-1 autocorrelation of per-name signals, averaged cross-sectionally) before someone implements a plausible-but-different statistic.

**3.5 K1 is evaluated once per evening.** A 10% breach at 11am goes unhandled until 18:00. Either accept and document, or add one lightweight midday position-valuation check. This is a deliberate-simplicity trade-off — just make it a written one.

**3.6 No loader contract.** Page 01 specifies `get_universe` and `compute_returns`, but nothing defines who builds the security_id-keyed wide prices frame from the ticker-keyed lake — applying `identifier_map`, selecting among sources (3.1), honoring exclusion flags. This loader is where half the historical leaks in systems like this actually live; it needs a contract in page 01.

**3.7 Model rollback (extends Ops 3.2).** The registry gains a promotion step; add that the previously deployed version stays pinned for one-command rollback.

---

## Alternatives considered

**Data: make "free data" a logged decision, not a premise.** Red-Team 1.2's core problem — delisted names missing from yfinance — is a coverage property of the source, not fully fixable with engineering. Survivorship-complete daily US equity data (Norgate, Sharadar via Nasdaq Data Link, EODHD) runs on the order of $25–100/month; against the engineering weeks and residual bias of the free stack, plausibly the highest-ROI dollar in the project. Keep the validation layer and two-source discipline regardless; set a revisit trigger (e.g., G0.1's 98% gate failing).

**Regime overlay: apply the G0.7 philosophy to the HMM.** A two-line rule — realized vol or VIX above a walk-forward percentile ⇒ reduced gross — captures most of the drawdown protection with zero label-switching, filtering, or refit machinery, and is trivially point-in-time. Make the threshold rule the v1 overlay *and* the baseline; the HMM becomes a challenger that must beat it out-of-sample, exactly as the NN must beat OU (G0.7).

**Order journal: SQLite (WAL) over DuckDB for the one transactional table (amend E2).** DuckDB is right for the OLAP lake; `orders_fills` is a write-ahead, crash-consistent, row-at-a-time workload — SQLite is the boring, battle-tested fit and removes any single-file contention between a crashed daily run and analytics.

**Orchestrator: systemd timer over raw cron (amend M2).** Same machine, same simplicity; adds `Persistent=true` missed-run catch-up, restart semantics, and journald logging — which directly serves Ops 3.1's dead-man concern.

**Broker: Alpaca now, with a named IBKR trigger (proposed E7).** If X2's ETB gating excludes more than a set fraction of intended shorts over a rolling month, IBKR (real borrow inventory, better on-close support, SIP data) becomes the Phase 4 migration path. Deciding the trigger now prevents relitigating it mid-drawdown.

**Docs: invert the source of truth at first commit.** "Edit Notion first, hand-copy byte-for-byte" fights git the moment the repo exists — no diffs, no review, no CI. Once Session 1 lands, make `/docs/` canonical (changes via PR, contracts colocated with the tests that enforce them) and demote Notion to narrative archive — or at minimum add a CI checksum comparing `/docs/` to a Notion export. Page 06 already flags the export as stale; that is the mechanism telling you this loop won't survive contact with development.

---

## What survives, and the verdict

The three load-bearing decisions hold under this pass too: shrink-only overlays, one code path, canary-first testing. Nothing above requires re-architecting — every fix slots into an existing page (01, 03, 04, 08) exactly as the prior reviews' fixes did. The theme completes the trilogy: the Red-Team found leaks in the seams between *estimation windows*; Ops found them in the seams between *process and broker*; this pass finds them in the seams between *the spec pages themselves* — and between the strategy and the market microstructure it must trade through.

**Blockers before Session 1, in order:** reconcile the hardened tests with pages 01/03 (1.1); freeze the execution-timing mechanism and window (1.3, E6); resolve overlay-vs-C2 precedence plus multiplier smoothing (1.2, C5/O8); pin gate disposition and 8-K item filtering (1.4, O7/amended O2). Everything else proceeds per the existing phase plan without blocking Phase 0.
