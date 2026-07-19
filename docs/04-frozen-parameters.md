# 🧊 04 — Frozen Parameters v1 (Decision Log)

> One table, one source of truth. Claude Code sessions must use these values and must not relitigate them; changing any value means editing this page first (with a dated log entry), then the config, never the other way around.
>
> **Provenance:** `doc` = stated in the architecture/math doc · `paper` = from Guijarro-Ordonez et al. · `proposed` = chosen here as a sane v1 default — revisit with evidence, not vibes.

## Alpha pipeline

| id | parameter | value | provenance | rationale |
|----|-----------|-------|------------|-----------|
| F1 | PCA/IPCA factors K | 5 | proposed (tests use 5) | Small universe; paper explores 1–15, mid-single digits robust. Sensitivity-check in Phase 1, don't tune per-run. |
| F2 | Factor lookback | 252 trading days | proposed | One year: standard, enough obs for 5 factors on ~400 names. |
| F3 | Factor refit | monthly, walk-forward | doc | Eigenvectors/Γ from window ending before refit date. |
| S1 | Residual window L | 30 days | doc/paper | The cumulative-residual "chart" length. |
| S2 | Signal net | CNN + 1-layer transformer | doc/paper | Mamba only as a compared experiment after baseline. |
| P1 | Cost rate c in training loss | 5 bps | proposed | Inside the objective (doc). Roughly half-spread+impact for liquid large caps; raise, don't lower. |
| T1 | Signal/policy retrain | quarterly, rolling 4y train + 1y val | doc ("1–3 months") | Balance freshness vs. churn. |
| T2 | Train/val embargo | 30 days (= L) | doc (math §3) | Prevents early-stopping peeking through the input window. |
| T3 | Signal→trade lag | ≥ 1 day (t close → t+1 execution) | doc | Enforced by test on `meta["signal_to_trade_lag_days"]`. |

## Universe & data

| id | parameter | value | provenance | rationale |
|----|-----------|-------|------------|-----------|
| U1 | Universe | PIT S&P 500 | doc | fja05680/sp500 calendar (see acquisition guide). |
| U2 | Min raw price | $5 | proposed | Avoids untradeable micro-price names and fill fantasy. |
| U3 | Min liquidity | $2M 21d median dollar volume | proposed | PIT-computed. |
| D1 | Cross-source close tolerance | 50 bps | doc | Above ⇒ quarantine, never pick a side silently. |
| D2 | Absurd-return threshold | 60% without corp action | doc | Validation gate (absolute value). |

## Overlays (may only shrink)

| id | parameter | value | provenance | rationale |
|----|-----------|-------|------------|-----------|
| O1 | Regime multipliers | calm 1.0 / normal 0.7 / stressed 0.25. **HMM fit window (amended 2026-07-18, N5):** expanding window from lake start, minimum 756 observations — keeps the 2008/2020 regimes in the emission estimates; refit cadence unchanged (monthly, walk-forward). Note recorded, not adopted: the audit's standing recommendation remains the Pre-Code Audit's unadopted alternative — a walk-forward vol/VIX-percentile threshold rule as the v1 overlay with the HMM as Phase-2 challenger. | doc | 3-state Gaussian HMM, monthly walk-forward refit. |
| O1b | Regime features | SPX ret, 21d realized vol, VIXCLS, HY OAS | doc | All FRED/derivable free. |
| O2 | News-gate lookback & item filter | 8-K with any material item in trailing 3 days ⇒ name gated. Filings whose items ⊆ {5.03, 5.07, 7.01, 8.01, 9.01} (routine / Reg-FD / exhibit-only) do NOT gate. **Information-time cutoff (amended 2026-07-17, B9):** a filing gates as of decision date t iff `filed_at` ≤ 18:00:00 America/New_York on t (the E5 deadline), identically in backtest and live. **v1 trade-off logged (2026-07-18, N13):** the 8.01/7.01 exemption carries an accepted false-negative surface — material news often files under item 8.01; accepted for v1 and measured rather than fixed. | doc + Pre-Code Audit 1.4 | v1; LLM headline gate is v2. Amended 2026-07-14: unfiltered 8-Ks turned earnings weeks into a rolling blackout. |
| O3 | Crowding floor | capital multiplier ∈ [0.3, 1.0] | doc | Inputs: signal autocorr decay, short interest, live-vs-backtest gap. |
| O4 | Combined multiplier domain | (0, 1] hard | doc | `build_portfolio` raises outside it — including 0.0. |
| O5 | HMM state labeling | after every refit, states are relabeled by ascending mean of `realized_vol_21d` over each state's occupied days: lowest → calm, middle → normal, highest → stressed | proposed | hmmlearn state indices are arbitrary and permute across refits; without a deterministic relabeling the multiplier map can silently invert in a crisis. |
| O6 | Crowding inputs, made computable | `signal_autocorr_decay` = cross-sectional mean, over currently-held names, of each name's OWN lag-1 signal autocorrelation over the trailing 63d, minus the same statistic over the training window. `short_interest` = FINRA aggregate on held names, joined on **publication** date. `live_backtest_sharpe_gap` contributes **neutrally** (as if gap = 0) until ≥ 60 days of paper/live history exist. | proposed | G2.4 requires computing all inputs live-shaped in a backtest phase, but the gap input is undefined pre-live. |
| O7 | News-gate disposition | freeze, don't flatten: for gated names, |target| ≤ |current| with the same sign — reductions allowed; increases, new entries, and sign flips blocked; never a forced exit. **Precedence (amended 2026-07-17, B10):** universe exit and delisting supersede the freeze. A gated name removed from the PIT universe effective t is fully exited at the t close (classified `risk_reduction` flow → E8 instrument, C5-exempt). | proposed (Pre-Code Audit 1.4) | The implicit weight=0 rule force-liquidated held names into post-news spreads. |
| O8 | Regime multiplier smoothing | the applied regime multiplier is the filtered-probability-weighted expectation Σ p(state)·m(state) ∈ [0.25, 1.0] — never the argmax state's multiplier. O5's relabeling still fixes which state mean maps to which m. | proposed (Pre-Code Audit 1.2) | Argmax flips near state boundaries produce repeated ~75%-turnover whipsaw demands. |
| O9 | Crowding-index upgrade & vintage discipline (extends O3/O6) | adds `days_to_cover` (= FINRA short interest on held names ÷ trailing 21d median daily share volume, joined on **publication** date) to O3's input set. The three inputs combine as a z-scored EWMA composite (half-life 10 trading days) with a ±0.05 hysteresis band. **Bounds remain O3's [0.3, 1.0] — one crowding multiplier, not two**. Backtests may only join FINRA data on last-published vintage as of t (hardened Test 16). **Transfer function & input definitions (amended 2026-07-18, N6):** the composite→multiplier map is multiplier = clip(1 − a·max(z̄, 0), 0.3, 1.0) with a frozen at **0.35**; the `short_interest` input = the 63-trading-day **change** in days_to_cover (crowding momentum); "held names" = the book entering the rebalance (t−1 close holdings). | proposed 2026-07-16 (Alpha Roadmap §3) | Promotes V9(b) crowding gauges from monitoring to a formalized sizing input. |

## Constraints & costs

| id | parameter | value | provenance | rationale |
|----|-----------|-------|------------|-----------|
| C1 | Max name weight | 3% | doc (range 2–5%) | Midpoint; concentration is the free-data tax. |
| C2 | Daily turnover cap | 25% of gross | proposed | Backstop; cost-aware training should keep it well under. |
| C3 | Max sector weight | 15% | proposed | GICS sectors. |
| C4 | Gross / net caps | 1.0 / ±2% | proposed | Hard exposure sanity regardless of model output. |
| X1 | Backtest cost model | half-spread 3 bps + impact 2 bps per 1% ADV | proposed | Conservative for SPX names; recalibrate from paper-trading fills in Phase 3. |
| X2 | Short borrow cost | flat 50 bps annualized on short-leg market value in backtest; live shorts gated pre-trade on the broker's easy-to-borrow list, hard-to-borrow names excluded | proposed | X1 prices only spread + impact; a dollar-neutral book is ~50% short. |
| C5 | Turnover-cap precedence | risk-REDUCING turnover driven by overlay/kill-switch multiplier changes is exempt from C2 and executes in full at the next rebalance. **Decomposition (amended 2026-07-17, B1):** exempt (risk-reducing) turnover at t = Σᵢ |wᵢ,t−1| × max(0, 1 − mₜ/mₜ₋₁). Alpha-driven turnover = total L1 turnover − exempt component; C2 binds the alpha-driven part only. | proposed (Pre-Code Audit 1.2) | O1's calm→stressed transition needs 75% one-day turnover against C2's 25% cap. |
| C6 | Minimum order notional | $100 — orders below are skipped and logged as unfilled turnover, never rounded up | proposed (Pre-Code Audit 2.2) | Integer/fractional rounding on a micro book silently breaks dollar-neutrality. |
| C7 | Max positions | derived: floor(deployed gross / C6), split equally per side, selected by |signal| rank; no-op when not binding | proposed (Pre-Code Audit 2.2) | The paper trades the full cross-section; a small book can't. |
| C8 | Live capital floor | $25,000 minimum equity for `mode=live` (paper unrestricted); config-enforced | proposed (Pre-Code Audit 2.2) | Below this, the stressed-regime book (0.25×) can't hold ~60 names at C6. |
| C9 | Pre-registered: multi-sleeve allocator (activates V9a) | **trigger — all five conditions, frozen now:** (i) Phase 2 complete AND the V9(a) OSAP composite built & backtested through the **same walk-forward engine** (G1.4 one-code-path); (ii) measured out-of-sample correlation of daily net returns between the DLSA sleeve and the OSAP sleeve ≤ **0.3** (gate G2.8); (iii) each sleeve individually clears deflated Sharpe > 0 net of costs; (iv) deployed capital ≥ **2 × C8** ($50,000); (v) the named architecture review held and logged here. **Allocator v1 = fixed 50/50 risk-weight combiner — never a learned meta-allocator.** Dormant contract reserved at `dlsa/allocation/allocator.py`. | pre-registered 2026-07-16 | The one structural escape from the Da–Nagel–Xiu per-strategy ceiling. |

## Kill-switch

| id | parameter | value | provenance | rationale |
|----|-----------|-------|------------|-----------|
| K1 | Max drawdown halt | 10% of deployed capital, measured from the running high-water mark of strategy equity since the last (re-)arming of the system; a resume re-bases the HWM only through the written-diagnosis process (G4.4) | proposed | Hard stop + alert; resume requires manual diagnosis. |
| K2 | Sharpe-gap halt | **Recalibrated 2026-07-18 (N2, owner decision):** live trailing-**120d** Sharpe > **2.5** below the **V2 decayed live prior** (never the raw backtest number), with the breach **confirmed on 2 consecutive weekly evaluations** before halting. SE reference (≈ iid daily returns): 60d → 2.05, 120d → 1.45, 252d → 1.03 — 2.5 at 120d ≈ 1.7 SE ⇒ ≈9%/yr false-halt rate. | proposed | Amended 2026-07-15: reference changed from raw backtest to V2's decayed prior. Recalibrated 2026-07-18: the old 60d/1.5 was <1 SE of the estimator — ≈65%/yr false halts. |
| K3 | Data-quality halt | any validation failure on today's ingest ⇒ no trading | doc | Fail closed. |
| K4 | Suspicion threshold | net Sharpe > 3 in any backtest ⇒ treated as a bug to investigate | doc | Red flag, not a result. |
| K5 | Stale-book escalation | 3 consecutive skip-days (E4) ⇒ flatten via kill-switch rather than continued halt | proposed | A halted-but-invested book is unmanaged. |

## Definitions & ops

| id | parameter | value | provenance | rationale |
|----|-----------|-------|------------|-----------|
| M1 | Sharpe definition | mean(daily net returns) / std(daily net returns, ddof=1) × √252; simple (not log) returns; no risk-free subtraction (dollar-neutral, self-financing book) | proposed | One definition everywhere: training objective, `BacktestResult.sharpe`, kill-switch gap (K2), and every acceptance gate. Implemented once in `dlsa/metrics.py::sharpe`; nothing else computes its own. |
| M2 | Orchestrator | systemd timer + service, single nightly entry (`Persistent=true`; unit scheduled in America/New_York per E5) | doc + Pre-Code Audit | One machine, one job. Amended 2026-07-14 from raw cron. |
| M3 | Training objective ≡ M1 on net returns | maximize mean(rᵗⁿᵉᵗ)/std(rᵗⁿᵉᵗ) over contiguous training windows, where rᵗⁿᵉᵗ = wᵗ₋₁'εᵗ − c·‖wᵗ − wᵗ₋₁‖₁. The denominator is the std of **net** returns. | proposed | One objective = one metric: what training maximizes is exactly what `BacktestResult.sharpe` reports. |
| M4 | Design holdout | the final 24 months of the sample are a design holdout: no design iteration, parameter choice, or gate tuning may consume them; one pre-registered run at the close of Phase 2 evaluates the frozen system on the holdout. **Mode scope (clarified 2026-07-17, B7):** the engine's holdout refusal applies to `mode: backtest` scoring only; `dry`/`paper`/`live` operate on current dates by design. **Boundary (B7 decided by owner 2026-07-17, Option A):** `dates.end` = the latest **validated** lake date at Session 1 (≈ 2026-06-30); `holdout_start` = **2024-07-01** — the final 24 months. | proposed (Pre-Code Audit 2.1) | Paper trading is currently the only genuine OOS and must be protected as such. |

## Execution & operations

| id | parameter | value | provenance | rationale |
|----|-----------|-------|------------|-----------|
| E1 | Order idempotency | `client_order_id` = deterministic hash(date, security_id, side, config_hash) | proposed | Re-running `make daily` after a crash must not double-submit. |
| E2 | Order/position state store | append-only journal (`orders_fills`) in **SQLite, WAL mode** at `data_lake/journal.sqlite`; broker account is position truth, journal is the audit trail `reconcile()` diffs against. **Durability rider (amended 2026-07-18, N11):** nightly off-machine copy of `journal.sqlite` and `runs/` (restic/rclone acceptable), live from Phase 0 and required before Phase 3 — the journal is gitignored, so git provides no durability; a single-disk loss must not destroy the audit trail. | proposed | Amended 2026-07-14: SQLite WAL is the boring fit for a transactional, row-at-a-time, crash-consistent workload. |
| E3 | Unfilled-residual policy | at execution-window close, cancel remaining unfilled quantity; never chase into the next session; log as unfilled turnover | proposed | Prevents stale marketable-limit orders from filling hours later at a materially different price. |
| E4 | Skip-day policy | if any required source (prices, universe calendar, 8-K feed, FRED) is not ready by the decision deadline (E5), skip the day — no trading, no silent guess | proposed | Vendor lateness is routine, not exceptional. |
| E5 | Nightly decision deadline | 18:00 America/New_York, DST-aware; job scheduled in exchange time, not fixed UTC | proposed | Fixed-UTC cron silently shifts an hour twice a year against NYSE hours. |
| E6 | Order type & execution window | orders submitted the evening of t with `time_in_force=cls` (on-close); limit = close(t) ± 1% protective band; execution window = the t+1 closing auction; residual unfilled after the auction is cancelled per E3. Entitlement verified in `make broker-smoke`. **Scope (amended 2026-07-17, B8):** the ±1% band applies to **alpha-driven** orders only — risk-reduction and kill-switch flows use E8's market-on-close instrument. | proposed (Pre-Code Audit 1.3) | |
| E7 | Broker migration trigger | if X2's hard-to-borrow gating excludes > 20% of intended short gross over any rolling 21 trading days, open the IBKR migration decision | proposed | |
| E8 | Risk-reduction and kill-switch order type | Orders whose parent flow is C5-exempt (overlay-multiplier decrease) or a K1/K5 flatten are submitted **market-on-close** (`time_in_force=cls`, no limit band); realized slippage logged under C5's separate cost budget. E6's ±1% band applies to **alpha-driven** orders only. | proposed 2026-07-17 (B8) | |

## Data timing

| id | parameter | value | provenance | rationale |
|----|-----------|-------|------------|-----------|
| D3 | FRED release lag | VIXCLS and HY OAS (O1b inputs) are used at their **t−1** published value in both backtest and live — never assumed available same-day | proposed | FRED publishes these series with roughly a one-business-day lag. |
| D4 | Quarantine-fraction cap | if D1 quarantines more than 15% of the universe on a given day, treat as a data-quality halt (K3) rather than trading the quarantine-survivors | proposed | Cross-source disagreement is correlated across names on volatile days. |
| D5 | Canonical modeling source | per (security_id, date): yfinance > stooq > alpaca; chosen source recorded on the served row. A backfill that changes an already-served canonical value is a validation event (quarantine + digest), never a silent overwrite. | proposed (Pre-Code Audit 3.1) | |
| D6 | Delisting terminal return | when `delistings.terminal_return` is NaN: impute −30% for reason ∈ {bankrupt, delisted}; 0% (exit at last observed price) for acquired; tearsheets report PnL sensitivity to ±15pp on the imputed set | Red-Team 1.2 fix, frozen here | |
| D7 | Vendor intake protocol (active immediately) | any NEW data source beyond the v1 set must: (1) land as point-in-time vintages under `data_lake/vendor_intake/<source>/` with explicit publication-date columns; (2) document its publication lag and have the loader enforce it; (3) remain **quarantined from all training and selection** until an ablation passes — model-with vs. model-without under V4 CPCV harness, adopted only on net **deflated**-Sharpe uplift with PBO within bound (hardened Test 20); (4) vintage-stamp any embedded model weights; (5) register every ablation as a V1 trial; (6) apply the V2 haircut to the uplift claim itself. | proposed 2026-07-16 | Novel inputs are the durable escape from publication decay AND the easiest place to manufacture fake backtest edge. |

## Alpha pipeline addition

| id | parameter | value | provenance | rationale |
|----|-----------|-------|------------|-----------|
| F4 | IPCA warm start | each walk-forward refit initializes Γ from the previous refit's converged Γ (first fit uses the managed-portfolio PCA init); convergence tol unchanged | proposed (Pre-Code Audit 2.4) | ALS in Python loops × ~240 monthly refits × K grid turns `make backtest` into an overnight job. |

## Validation & evaluation (Bear-Case adoptions, added 2026-07-15)

| id | parameter | value | provenance | rationale |
|----|-----------|-------|------------|-----------|
| V1 | Trial registry & Deflated Sharpe | every `make backtest` writes a run record to `runs/backtests/` containing a **canonical config hash** (SHA-256 over the resolved config, sorted keys; timestamps/output paths excluded; seed list included). n_trials = count of distinct hashes ever recorded — it never resets. `BacktestResult` reports `deflated_sharpe` alongside M1 `sharpe`. **Amended 2026-07-17 (B2):** `deflated_sharpe` is the DSR **probability** in [0, 1] — the PSR evaluated at SR* per Bailey–López de Prado, computed by `dlsa/metrics.py::deflated_sharpe(sharpe, n_obs, skew, excess_kurtosis, n_trials, sr_var_across_trials)`. When n_trials < 2 the variance is undefined ⇒ DSR = NaN. **Durability rider (amended 2026-07-18, N11):** the registry is covered by the same nightly off-machine backup as the E2 journal. | proposed (Bear Case §5) | Turns M4's pre-registration from an honor system into a computed statistic. |
| V2 | Decay-calibrated live prior | haircut h = **0.40** (inside McLean–Pontiff's 26–58% post-publication decay range). Expected live Sharpe = (1 − h) × the accepted backtest net Sharpe. K2 and G3.4 measure live shortfall against **this decayed prior**, never the raw backtest. h is frozen before Phase 3 starts. | proposed (Bear Case §3–§4) | Without this, ordinary post-publication decay reads as malfunction. |
| V3 | Signal-net seed ensemble | the deployed signal net is the **equal-weight mean of N = 5 seeds**, seed list [0, 1, 2, 3, 4]; one ensemble = one versioned model in the registry; one ensemble = one V1 trial. Aggregation happens inside `predict()` so downstream code sees a single signal vector. | proposed (Bear Case §1) | Estimation variance is the Da–Nagel–Xiu ceiling's entire mechanism; seed averaging is its cheapest direct attack. |
| V4 | CPCV selection harness | hyperparameter/architecture selection runs only in `dlsa/selection/` under Combinatorial Purged CV: **8 groups, 2 test groups per split (28 splits, 7 paths), purge = 60 trading days, embargo = 10 trading days**. Selection statistic = median net Sharpe (M1) across paths; PBO reported with every selection. The harness **never produces reported performance**. Invoked via `make select`; outputs to `runs/selection/`. | proposed (Bear Case §5) | Walk-forward is weak at false-discovery prevention; CPCV selects on many paths. |
| V5 | Empirical-Bayes signal shrinkage | applied between signal-net output and policy input, same code path backtest and live: cross-sectional James–Stein/EB linear shrinkage toward 0 with λ = σ̂²_signal / (σ̂²_signal + σ̂²_noise), estimated on the trailing 252 trading days at each monthly refit (F3 cadence), clamped to [0, 1], logged daily as a diagnostic. **Estimator defined (amended 2026-07-17, B6):** over the trailing 252 trading days with N = 5 seeds: v̂ar_members = mean cross-seed variance of member signals (⇒ σ̂²_noise per member); v̂ar_mean = mean cross-sectional variance of the ensemble-mean signal (⇒ σ̂²_signal + σ̂²_noise/N); **λ = clamp( max(v̂ar_mean − σ̂²_noise/N, 0) / v̂ar_mean, 0, 1)**. Fits on **member signals** (MultiIndex (date, seed) × security_id), never on prices. Degenerate case: when `len(ensemble_seeds) == 1` (test_min), λ comes from config key `signal.shrinkage.fixed_lambda`. | proposed (Bear Case §1) | Estimation error becomes smaller positions instead of confident wrong ones. |
| V6 | Pre-registered: JKMP aim-portfolio policy form | **trigger:** G2 gates passed. **Adoption mechanism (frozen 2026-07-16): shadow mode.** From trigger date, `make daily` computes two target books — baseline (traded) and aim-portfolio (shadow) — and journals the shadow book's counterfactual fills through X1/X2, tagged `book=shadow` in E2; a shadow order can never reach `submit()` (hardened Test 17). Adoption gate **G3.7**: over the same ≥ 60-trading-day window, shadow net Sharpe ≥ live net Sharpe AND shadow alpha-driven turnover ≤ live. κ (partial-adjustment rate) frozen from V4 CPCV evidence at adoption. | pre-registered | Largest potential net-Sharpe improvement on the bear-case page. |
| V7 | Pre-registered: Tail-GAN overlay stress harness | **trigger:** Phase 2 overlay tuning. Reserves `data_lake/synthetic/` now; synthetic data is **never a training or selection input** (hardened test enforces the quarantine). | pre-registered | Answers M4's deepest problem — the designer has seen 2008/2020/2022. |
| V8 | Pre-registered: vintage-stamped LLM weights for news gate v2 | **trigger:** v2 news-gate work begins. Any embedding/LLM signal in a backtest must use weights trained only on pre-period text (ChronoBERT/ChronoGPT class), pinned by vintage in the model registry. | pre-registered | Anachronistic weights leak post-period knowledge — a leakage class living in model weights. |
| V9 | Pre-registered: OSAP combo sleeve & O6 gauge upgrade | **trigger:** Phase 2–3. (a) Ridge-combined OSAP characteristics composite as benchmark/fallback sleeve — pre-written as **C9** with a five-condition compound trigger. (b) O6 gains days-to-cover and short-interest gauges — **absorbed into O9**. | pre-registered | Diversifies against single-recipe publication decay and instruments crowding with validated gauges. |

## Change log

| date | id | old → new | evidence |
|------|----|-----------|---------|
| (init) | — | v1 frozen | — |
| 2026-07-12 | M1, M2 | added | Retroactive entry — added earlier today without a log row. |
| 2026-07-12 | M3, O5, O6 | added | Independent verification pass: training objective reconciled with M1; HMM relabeling convention pinned; crowding inputs given computable definitions. |
| 2026-07-13 | E1–E5, D3, D4, X2, K5 | added | Ops & Systems Review: order idempotency; skip-day and stale-book escalation; FRED publication lag; quarantine-fraction cap; short-borrow cost and availability gating. |
| 2026-07-14 | F4, O7–O8, C5–C8, D5–D6, E6–E7, M4 added; O2, O6, K1, E2, M2 amended | added / amended | Pre-Code Audit: overlay-vs-turnover-cap collision (C5, O8); on-close execution mechanism (E6); news-gate disposition + 8-K item filter (O7, O2); micro-book capital math (C6–C8); canonical-source and delisting-return determinism (D5, D6); design holdout (M4); IPCA warm start (F4). |
| 2026-07-15 | V1–V5 added; V6–V9 pre-registered; K2 amended | added / amended / pre-registered | Bear-Case review adoption: trial registry + Deflated Sharpe (V1); decay-calibrated live prior (V2); 5-seed ensemble (V3); CPCV selection harness (V4); EB signal shrinkage (V5). |
| 2026-07-16 | O9, C9, D7 added; V6, V9 amended | added / amended / pre-registered | Alpha & Net-Sharpe Roadmap adoption: crowding gauges promoted to formalized sizing index (O9); multi-sleeve review pre-written with five-condition trigger (C9); vendor intake protocol active immediately (D7). |
| 2026-07-17 | E8 added; C5, V1, V5, E6, O2, O7, M4 amended; N14 decision recorded | added / amended | Sixth-Pass Coding-Readiness Audit (GO-WITH-FIXES): C5 exempt-turnover decomposition (B1); V1 `deflated_sharpe` as DSR probability (B2); V5 seed-dispersion estimator (B6); E8 market-on-close for risk-reduction/kill-switch flows (B8); O2 `filed_at` cutoff (B9); O7 universe-exit precedence (B10); M4 clarified to backtest-mode scoring only (B7 open). |
| 2026-07-17 | M4 amended (B7 decided) | amended | **B7 owner decision, Option A:** sample end moves → ≈ 2026-06-30; `holdout_start` moves → 2024-07-01. |
| 2026-07-18 | O1, O9, E2, V1, O2 amended | amended | Sixth-Pass Audit Part 2: O1 gains frozen HMM fit window — expanding, min 756 obs (N5); O9 gains frozen transfer function (a = 0.35), days-to-cover-change definition, "held names" definition (N6); E2 and V1 gain nightly off-machine backup rider (N11); O2 rationale logs the 8.01/7.01 false-negative surface as an accepted v1 trade-off (N13). |
| 2026-07-18 | K2 | recalibrated (N2 decided) | **N2 owner decision: audit-recommended default adopted** — window 60d → **120d**, threshold 1.5 → **2.5** (≈ 1.7 SE ⇒ ≈9%/yr false-halt rate), breach confirmed on 2 consecutive weekly evaluations; CUSUM alternative declined. **All Sixth-Pass Audit items (B1–B12, N1–N15) are now closed.** |
