# 🏁 08 — Phase Acceptance Criteria (v1)

> The roadmap's milestones, made numeric. A phase is DONE when every gate below passes; "close enough, moving on" is how leakage ships. Gates may be tightened mid-phase with a change-log entry; loosening one requires written justification of why the gate was wrong, not why the result missed it.

## Phase 0 — Reproduce (target: weeks 1–3)

| gate | criterion |
|------|-----------|
| G0.1 | Data lake populated **2003→present** (2005-01-03 trading start plus 2 years of factor-lookback headroom, per the acquisition guide's backfill rule) for PIT S&P 500: ≥ 98% of (member, trading day) cells have a validated close from ≥ 1 source; every gap has an exclusion flag or delisting record. |
| G0.1b | **Delisted-subset coverage sub-gate (added 2026-07-18, N3).** G0.1's aggregate 98% can pass while the delisted subset — where all the survivorship bias lives — sits at 60%. For every ticker with a delisting record or PIT removal 2003→present: ≥ 90% of member-period trading days AND 100% of the final 21 member days carry a validated close or an explicit exclusion + D6 record; delisted-subset coverage % is reported separately alongside G0.1's aggregate. This is also the honest trigger for the standing buy-vs-free data decision (page 06 open item). |
| G0.2 | Two-source cross-check live: < 0.5% of rows in quarantine after known-issues triage; zero silent picks. |
| G0.3 | `make test-leakage` green, including both canary tests, on every commit (pre-push hook). |
| G0.4 | Survivorship sanity: 2012 universe contains ≥ 50 tickers absent from today's (test exists; this makes it numeric). |
| G0.5 | Baseline PCA pipeline runs end-to-end; **frictionless** OOS Sharpe on real data in **1.0–3.5**. "Matching published results" means the right order of magnitude on worse data — below 1.0 investigate the pipeline, above 3.5 investigate leakage (K4). Both failure modes get a written diagnosis before proceeding. |
| G0.6 | Reproducibility: same config + seed + lake snapshot ⇒ identical Sharpe to 4 decimals on two consecutive runs. |
| G0.7 | OU baseline built and beaten: the classical Ornstein–Uhlenbeck s-score strategy (math explainer §2.1) implemented on the SAME residuals and run through the SAME backtest engine. It must earn a frictionless OOS Sharpe ≥ 0.3 (numeric floor — sanity that the residuals actually mean-revert; if OU earns ~0, debug the residual pipeline before touching the network), and the NN pipeline must beat it OOS before Phase 0 closes (the paper's core claim, reproduced). |

## Phase 1 — Realistic backtest (weeks 4–5)

| gate | criterion |
|------|-----------|
| G1.1 | Cost term inside the training objective (P1 = 5 bps); demonstrated effect: average holding period strictly increases vs. a c=0 ablation and daily turnover drops ≥ 30%. |
| G1.2 | Net-of-cost OOS Sharpe (X1 cost model) in **0.5–2.0**, quoted alongside `deflated_sharpe` and the all-time trial count (frozen param V1) in the same tearsheet. Above 2.5 net triggers a leakage review before celebration; a result in the **upper half of the band (≥ 1.5)** additionally gets a written plausibility note against the Da–Nagel–Xiu feasible ceiling (Bear Case §1) before Phase 2 begins — the K4 reflex, applied one band lower. |
| G1.3 | Turnover ≤ C2 cap organically (cap binding < 5% of days). |
| G1.4 | Backtest/live code path unified: `run_backtest` and the daily job import the same `build_portfolio`; a test asserts there is exactly one implementation. |
| G1.5 | K-factor sensitivity (K ∈ {3, 5, 8, 10}): conclusions stable; no cherry-picking the best K (report all in one tearsheet set). |
| G1.6 | Model selection ran under the V4 CPCV harness (`make select`): every compared hyperparameter/architecture candidate went through the 7-path protocol, the chosen config's **PBO is reported** in the Phase-1 tearsheet, and the accepted G1.2 number comes from a single walk-forward run of that chosen config (one V1 trial). Selection outputs live in `runs/selection/` and are never quoted as performance. |
| G1.7 | The deployed signal model is the V3 five-seed ensemble; a per-seed ablation is archived in MLflow showing the cross-seed OOS Sharpe dispersion vs. the ensemble's — the variance reduction is demonstrated, not assumed. |

## Phase 2 — Overlays (weeks 6–8)

| gate | criterion |
|------|-----------|
| G2.1 | Regime overlay: 2008 (if data reaches), 2020, and 2022 max drawdowns each improve ≥ 25% vs. no-overlay, while full-period net Sharpe degrades ≤ 15%. |
| G2.2 | Regime false-positive rate: "stressed" state occupies ≤ 15% of days over the full sample. |
| G2.3 | News gate: gated names ≤ 10% of universe on a median day; event-study shows gated names' residuals revert less than ungated (the gate's whole premise, verified). **Earnings-week residual (addendum 2026-07-18, N13):** the median-day cap is structurally blind to earnings-week clustering (2.02 still gates, by design) — also report the **P95-day gated fraction** and the **mean gated fraction over earnings weeks**; P95 > 35% requires a written diversification note before G2 closes. The accepted 8.01/7.01 false-negative surface is logged as a v1 trade-off in O2's rationale (page 04). |
| G2.4 | Crowding monitor computes all four inputs live-shaped (O6's three + O9's `days_to_cover`), point-in-time incl. the FINRA **publication-vintage** join (hardened Test 16), and its multiplier lands in [0.3, 1.0] always. The composite obeys O9's smoothing + ±0.05 hysteresis: no sign-alternating multiplier changes on consecutive days inside the band. The live-vs-backtest gap input contributes neutrally pre-live per frozen param O6. |
| G2.5 | Overlay invariant tests green: no code path lets any multiplier exceed 1.0 or any gate add exposure. |
| G2.6 | Each overlay has an ablation tearsheet (on/off) archived in MLflow. |
| G2.7 | M4 design holdout enforced: every Phase 2 tuning/ablation decision above (G2.1–G2.6, plus Phase 0–1 parameter and K-sensitivity choices) uses only dates before `holdout_start` (frozen param M4 — the final 24 months of the sample). One pre-registered run evaluates the frozen system on the holdout at the close of Phase 2, before Phase 3 begins; no metric from that run may trigger further design changes to Phase 0–2 parameters. Any parameter change during Phase 3 resets the G3.1 60-day clock. |
| G2.8 | **Sleeve-correlation measurement (C9 trigger input).** The V9(a) OSAP ridge composite is built and backtested through the SAME walk-forward engine as a signal config (`make sleeve-b`), and the out-of-sample correlation of daily net returns between the DLSA sleeve and the OSAP sleeve is **measured and recorded** in MLflow — with per-sleeve `sharpe` and `deflated_sharpe`. This gate does not require the correlation to clear C9's ≤ 0.3 ceiling; it requires the number to EXIST so C9's trigger is decidable on evidence, not an eyeball. |

## Phase 3 — Paper trading (weeks 9–16+, minimum 3 months)

| gate | criterion |
|------|-----------|
| G3.1 | ≥ 60 consecutive trading days of the full daily job with ≥ 95% hands-free completion; every failure has a post-mortem note in the runbook. **Off-host dead-man switch (addendum 2026-07-18, N10):** an external heartbeat — the job checks in after each run; a missed check-in alerts within 12h from **off the host** — is live for the full 60-day window. M2's rationale overclaims that systemd "serves Ops 3.1": journald dies with the host; only an off-host monitor detects a dead machine. |
| G3.2 | Fill realism: median realized slippage within 50% of the X1 model (e.g. modeled 5 bps ⇒ realized ≤ 7.5 bps); else recalibrate X1 and extend paper period 1 month. **A pass is an optimistic lower bound, not validation of X1** — paper fills are simulated against quotes with no impact or queue modeling. Honest X1 calibration comes from independently computed arrival-price slippage, or from the first tiny live tranche. |
| G3.3 | Reconciliation: intended vs. filled positions match within 1% of gross daily; every breach alerted same-day. |
| G3.4 | Live-vs-backtest gap: trailing-**120d** paper Sharpe within K2 threshold (**2.5**) of the **V2 decayed prior** — i.e. (1 − 0.40) × the backtest's same-period expectation, not the raw backtest number — with a breach **confirmed on 2 consecutive weekly evaluations** before halting (K2 recalibrated 2026-07-18, N2, owner decision: the old 60d/1.5 was <1 SE of the estimator ⇒ ≈65%/yr false halts on a strategy performing exactly at the prior; 120d/2.5 ≈ 1.7 SE ⇒ ≈9%/yr). Ordinary post-publication decay is the base case (Bear Case §3–§4), not a malfunction; the raw-backtest comparison is still logged in the digest for information. |
| G3.5 | Kill-switch fire drill: each tripwire (K1–K3) deliberately triggered once in paper; halts + alerts confirmed end-to-end. |
| G3.6 | Daily digest delivered automatically every trading day for the final 30 days. |
| G3.7 | **V6 shadow-adoption gate (dormant until V6's trigger fires post-G2).** Over the same ≥ 60-trading-day window with both books journaled: shadow (aim-portfolio) net Sharpe ≥ live baseline net Sharpe AND shadow alpha-driven turnover ≤ live — "alpha-driven" per **C5's exempt-turnover decomposition** (page 04, amended 2026-07-17, B1: exempt = Σᵢ |wᵢ,t−1| × max(0, 1 − mₜ/mₜ₋₁)), computed **per book** with each book's own weights; the journal's `flow` column (E8) is the audit surface. Counterfactual fills priced through X1/X2, the comparison itself written to the V1 registry. Pass ⇒ V6 may be adopted (κ frozen from V4 CPCV evidence; adoption resets the G3.1 clock per M4). Fail or insufficient window ⇒ baseline stands, shadow keeps logging. A shadow order reaching `submit()` at any point is an automatic gate failure (Test 17). |
| G3.8 | **Unfilled-turnover gate (added 2026-07-18, N4).** G3.2 measures ≈ 0 slippage by construction on LOC fills; the fill-realism information lives in the E3/C6 unfilled log, which no gate previously bounded. Over the G3.1 window: **median daily unfilled turnover ≤ 5% of intended, P95 ≤ 20%**, every residual journaled per E3 — including C6 ticket-floor skips, integer-share rounding trims, and capacity exclusions from `diff_orders` (page 01, N4). Breach ⇒ written diagnosis of whether the E6 band, the C6 floor, or C1×equity share granularity is the cause before Phase 3 can close. |

## Phase 4 — Live, small (gated, not scheduled)

| gate | criterion |
|------|-----------|
| G4.1 | Entry: all Phase 3 gates green **simultaneously over the final 60 days** — not best-of. |
| G4.2 | Initial capital: an amount whose total loss is genuinely acceptable; hard cap enforced in config, raised at most monthly and only if the crowding monitor is ≥ 0.8 and drawdown < 5%. |
| G4.3 | First 20 live days: daily manual review of the digest before next-day trading is enabled (a literal checkbox the job requires). |
| G4.4 | Standing rule: any kill-switch fire ⇒ diagnose-in-writing before re-enable. Overriding a halt without a written diagnosis is the one unforgivable operational sin. |

## Change log

| date | gate | change | justification |
|------|------|--------|---------------|
| (init) | — | v1 | — |
| 2026-07-12 | G0.7 | added | OU s-score baseline as independent residual-pipeline sanity check + reproduces the paper's NN-beats-OU claim. |
| 2026-07-12 | G0.1, G0.7, G2.4 | amended | Independent verification pass: coverage window extended; "plausible positive" given a numeric floor (0.3); crowding gap input referenced to O6's neutral-pre-live rule. |
| 2026-07-14 | G2.7 | added | Pre-Code Audit 2.1: design-level overfitting was the least-defended flank. |
| 2026-07-14 | G3.2 | amended | Pre-Code Audit 2.3: a pass reads as validating the X1 cost model — corrected to "optimistic lower bound." |
| 2026-07-15 | G1.2, G3.4 amended; G1.6, G1.7 added | amended / added | Bear-Case review adoption: G1.2 quotes Deflated Sharpe + trial count; G3.4 measures against V2 decayed prior; G1.6 requires CPCV-based selection with PBO; G1.7 requires V3 seed ensemble with demonstrated variance reduction. |
| 2026-07-16 | G2.8, G3.7 added; G2.4 amended | added / amended | Alpha-Roadmap adoption: G2.8 makes C9's correlation trigger decidable; G3.7 is V6's shadow-adoption gate; G2.4 gains days_to_cover, publication-vintage requirement (Test 16), and O9 hysteresis/whipsaw check. **Gate-ID collision caught:** the roadmap draft assigned V6 gate "G3.5", which this page already uses for the kill-switch fire drill — corrected to G3.7. |
| 2026-07-17 | G3.7 | amended | Sixth-Pass Audit B1: "shadow alpha-driven turnover ≤ live" now cites C5's exempt-turnover decomposition explicitly, computed per book. |
| 2026-07-17 | G2.7 | boundary resolved (no text change) | Sixth-Pass Audit B7, owner decision Option A: G2.7's "final 24 months" now resolves to `holdout_start` = **2024-07-01** with `dates.end` ≈ 2026-06-30. Gate wording deliberately unchanged — it referenced M4 by definition. |
| 2026-07-18 | G0.1b, G3.8 added; G3.1, G2.3 amended | added / amended | Sixth-Pass Audit Part 2 (N3, N4, N10, N13): G0.1b closes the delisted-subset masking; G3.8 bounds the unfilled-turnover log; G3.1 gains the off-host heartbeat requirement; G2.3 gains P95/earnings-week reporting with a written-note threshold. Gate IDs G0.1b/G3.8 re-verified collision-free. |
| 2026-07-18 | G3.4 | amended (N2 decided) | **N2 owner decision: audit-recommended default adopted** — G3.4 now measures the trailing-**120d** paper Sharpe against a **2.5** threshold below the V2 decayed prior, breach confirmed on **2 consecutive weekly evaluations**. The old 60d/1.5 was <1 SE ⇒ ≈65%/yr false halts. **All Sixth-Pass Audit items are now closed on this page.** |
