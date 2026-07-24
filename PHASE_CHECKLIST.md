# DLSA Build Checklist / Phase Map

> **Canonical notice (2026-07-21):** This file is the source of truth. Notion
> page 11 is the narrative archive — sync it same-day from here. All changes
> go through PRs; do not edit Notion first.
>
> **If you are a fresh Claude Code session:** read this file, then `CLAUDE.md`,
> `.claude/rules/`, and the `docs/` files named in your build item. Do exactly
> one unchecked item unless told otherwise. Contracts: `docs/01-interface-contracts.md`
> · frozen params: `docs/04-frozen-parameters.md` (wins all disagreements) ·
> gates: `docs/08-acceptance-criteria.md`. Check a box only when the named
> tests are green and `make test-leakage` passes.

**Status as of 2026-07-18:** all 26 spec pages reconciled; Sixth-Pass Audit
B1–B12 and N1–N15 all closed. No code exists yet.

**Model key:** 🟢 Haiku 4.5 (mechanical, errors are loud) · 🔵 Sonnet 4.6
(default implementation) · 🟣 Opus 4.8 (leakage-critical / subtle math) ·
🔴 Fable 5 (date-alignment core; any session where a leakage test fails and
the cause isn't obvious). Rule of thumb: **spend tokens where bugs are silent,
save them where bugs are loud.** Guarded-folder pattern: 🔵 implements → short
🟣 review-only session ("read the diff against docs/01 and the leakage tests;
list violations; write no code").

---

## Step 0 — Pre-code (human, no model)

- [x] Fill commit-SHA pins on page 06 (fja05680/sp500 pinned 2026-07-13;
  authors' repo pinned 2026-07-18: `ea8cc2958943eb1fe914aa4fad6998994a678323`)
  — starting codebase dropped 2026-07-18, see Notion page 06
- [x] Alpaca paper account + FRED key → local `.env` (never committed) — keys
  added 2026-07-18
- [x] Verify Alpaca on-close (`cls`) entitlement on your tier — CONFIRMED
  2026-07-18 via direct API test (accepted, queued for next close);
  E6/E8 unblocked; `make broker-smoke` automates this same check once the
  repo exists
- [x] Re-export consolidated markdown — DONE 2026-07-18, all 27 pages
- [x] Contract↔test reconciliation (2026-07-14; re-verified 2026-07-17)
- [x] Sixth-Pass Audit B1–B12 + N1–N15 implemented into the docs (2026-07-17/18)

---

## Session 1 — Bootstrap

**Done = `make test-leakage` collects with zero errors, all tests xfail.**
Tests are committed before implementation so every session builds toward them,
never around them; tests are never edited beyond the wiring block and xfail
marks.

- [x] 🟢 Materialize all artifacts from Notion byte-for-byte per Notion page 09
  Step 1 (fix nothing in transit — corrections go to `docs/` first now that
  canonicality has inverted)
- [x] 🟢 Scaffold: `git init` → `uv init --python 3.11` → deps from
  `docs/07-environment-makefile.md` → empty layout per `CLAUDE.md` →
  pre-commit → first commit
- [x] 🟢 Wire test imports; mark all `xfail(strict=False)`; confirm clean
  collection — completed 2026-07-20: PROJECT_WIRING imports pointed at real
  package paths; `test_lake_dir` fixture added (function-scoped `tmp_path`) to
  close the 5 setup ERRORs; class-level `xfail(strict=False)` across all suite
  classes. Intended end state: 43 collected, all xfail/xpass, 1 skipped
  (`test_delisted_names_exist_historically`, skipif on `calendar_available()`),
  0 errors.
- [x] **Docs canonicality decided 2026-07-21** — `/docs/` is canonical,
  changes via PR; Notion demotes to narrative archive; `PHASE_CHECKLIST.md`
  (this file) is the build checklist.

---

## Phase 0 — Reproduce (weeks 1–3)

*Get honest data (dead companies included) and reproduce the paper. "Honest" =
for any backtest date, the system knows only what was knowable that day.*
Un-xfail order = build order; one module per session; guarded-folder sessions
end with `make test-leakage`; when creating a NEW file in a guarded folder,
read a sibling first (path rules trigger on read).

- [x] 🔵 **P0.1 Calendar + PIT universe** — `get_universe(date)` per
  `docs/01-interface-contracts.md`; append-only membership log per
  `docs/02-data-lake-schema.md`; un-xfail `TestPITUniverse`. Universe
  membership comes from this function ONLY, everywhere.
  *2026-07-22:* fja05680 CSV ingested to `data_lake/universe/universe_membership.parquet`;
  `TestPITUniverse` tests 2 (delisted) + 3 (deterministic) green;
  `test_backtest_only_trades_members_as_of_each_date` still individually
  xfail'd — awaits `run_backtest` from P0.10.
- [x] 🔵 **P0.2 identifier_map v0** — append-only validity ranges, never edits;
  built from fja05680 symbols + `symbol_change` actions; the loader
  hard-depends on it (B11)
  *2026-07-22:* `dlsa/data/identifier_map.py` ships v0 (fja05680 path):
  deterministic `security_id = SID_<sha256(ticker)[:12]>` assigned at first
  sight; `build_identifier_map_v0()` writes `data_lake/identifier_map/
  identifier_map.parquet` (append-only, docs/02 schema), idempotent via
  content-hash `recorded_at`; `resolve_security_id(source_id, asof)` honors
  validity ranges with NaT = still-current and later-`recorded_at`-wins on
  corrections. Real CSV smoke-test: 1202 unique tickers → 503 current + 699
  exited (survivorship signal intact; ENRNQ closes 2001-11-26 as expected).
  `symbol_change` unification is reserved for P0.3 (parameter present,
  raises `NotImplementedError` — extension will land as pure append).
  Tests: `tests/test_identifier_map.py` 20/20 green; full suite 30 passed,
  33 xfailed (no regression).
- [ ] 🔵→🟣review **P0.3 Price ingest + validation** 2003→present — two-source
  cross-check; quarantine never zero-fill; stale-bar check (N7); SPY though
  not a member (N8); disputed membership fail-closed (N12); store RAW prices +
  actions, never persist adjusted. G0.1/G0.1b/G0.2 measured here;
  delisted-subset coverage reported separately (that's where survivorship bias
  hides; triggers the buy-vs-free data decision)
  - [x] **P0.3a Validation gate + schemas + returns + symbol_change** (2026-07-23).
    Shipped ahead of network ingest:
    * `dlsa/data/schemas.py` — pandera `PRICES_SCHEMA`, `CORPORATE_ACTIONS_SCHEMA`,
      column-name constants, `ValidationReport` dataclass.
    * `dlsa/data/validation.py::validate_frame(df, source, lake_dir=None, corporate_actions=None)`
      — write-gate for the lake. All six checks land: duplicate (ticker,date),
      negative price/volume, D2 |ret| > 60% w/o matching split, D1 cross-source
      > 50bps (consults other-source parquets already in the lake — no-op when
      absent), N7 stale-bar (identical OHLCV vs prior session while ≥ 80% of
      the frame moved), N1 adjustment-consistency
      (`pct_change(close_adj) ≈ compute_returns(close_raw, actions)` within 1e-8).
    * `dlsa/data/returns.py::compute_returns` — implemented (P0.5 pulled forward
      so N1 has something to cross-check). Splits back-adjust the pre-split
      window; dividends back-adjust by (1 − div/close_before); NaN prices
      produce NaN returns at both `t` and `t+1`; |ret| > 60% without a recorded
      split ⇒ NaN (D2 unrecorded-split trap). `TestReturnCorrectness` and
      `TestReturnCorrectnessHardened` un-xfailed and green.
    * `dlsa/data/identifier_map.py` — `symbol_change` extension: `corporate_actions`
      rows with `type == 'symbol_change'` unify old/new tickers under the
      OLDER ticker's `security_id` via APPENDED rows landing 1s after v0's
      `recorded_at` (later-recorded_at-wins). Idempotent; extends preserve
      relative ordering under a merge shift. The old `NotImplementedError`
      path is gone.
    * Tests: `tests/test_validation.py` 13/13 new, `tests/test_identifier_map.py`
      24/24 green (5 new `TestSymbolChangeExtension`), full suite **50 passed,
      30 xfailed** (no regression; 3 new pass, 3 fewer xfailed).
    * Deferred to a follow-up P0.3b: real network ingest (yfinance + stooq
      wired end-to-end per user's preference), N12 cross-source universe
      dispute, coverage reporter (G0.1 / G0.1b / G0.2), symbol_change corp-
      action *ingest* (as opposed to the map extension, which is done).
- [ ] 🔵 **P0.4 FINRA short-interest ingest** — publication-vintage table per
  `docs/02-data-lake-schema.md`; Test 16 ships now, Tests 20–21 ship with
  the suite
- [ ] 🟣 **P0.5 compute_returns** — `close_raw` + actions only, `close_adj`
  diagnostic (N1, 1e-8 consistency test); unrecorded-split moves ⇒ NaN, don't
  trade; un-xfail `TestReturnCorrectness`
- [ ] 🟣 **P0.6 PCA factors → OOS residuals** — loadings fit strictly before
  the residual window (in-sample residuals = #1 named risk); all preprocessing
  stats fit on train window only (truncation-equivalence); un-xfail
  `TestFeatureAvailability` + `TestCausalNormalization`
- [ ] 🔵 **P0.7 OU baseline** — same residuals, same engine; G0.7: OU OOS
  Sharpe ≥ 0.3 else debug residuals before touching any network; NN must beat
  OU before Phase 0 closes
- [ ] 🔵→🟣review **P0.8 Signal + policy nets** — port from pinned
  reimplementation; policy subtleties: undetached w₍t−1₎, in-graph per-day
  normalization, contiguous windows, deploy best-validation weights
- [ ] 🟣 **P0.9 Ensemble (V3) + shrinkage (V5)** — seed-dispersion λ per B6;
  test_min pins `fixed_lambda: 0.5`; Tests 13/15
- [ ] 🔴 **P0.10 Backtest engine** — decide close(t), execute close(t+1), earn
  close(t+1)→close(t+2); alignment in this ONE module, no ad-hoc `.shift()`
  elsewhere; V1 registry write from run one; DSR per B2 (n_trials < 2 ⇒ NaN
  is information); un-xfail `TestOverlayInvariants` then `TestNoiseCanary`
  LAST — canary green is the Phase-0 heartbeat
- [ ] **P0.11 Walk gates G0.1–G0.7** — G0.5 band 1.0–3.5 frictionless: below
  ⇒ investigate pipeline, above ⇒ investigate leakage; G0.6
  bit-reproducibility to 4 decimals; written diagnosis for either failure mode

---

## Phase 1 — Realistic backtest (weeks 4–5)

*Costs inside training so the model trades less; prove post-cost profitability;
prove you didn't keep the luckiest of 50 settings.*

- [ ] 🟣/🔴 **P1.1 V4 CPCV harness FIRST** (`make select`, Test 14) — before
  ANY comparison; purge 60 / embargo 10 in **trading days** (B4); contiguity
  per N15; outputs in `runs/selection/`, never quoted as performance
- [ ] 🟣 **P1.2 Cost term in objective** (P1 = 5 bps) — G1.1: holding period
  strictly up, turnover −30% vs c=0
- [ ] 🔵 **P1.3 Code-path unification** — one `build_portfolio` for backtest +
  daily job, asserted by test (G1.4); signature carries
  `prev_overlay_multiplier`, C5 exemption = Σ|wᵢ,t−1|·max(0, 1−mₜ/mₜ₋₁) (B1)
- [ ] 🔵 **P1.4 Tearsheets** — Sharpe + DSR (a probability) + all-time trial
  count everywhere (G1.2); K ∈ {3,5,8,10} all reported (G1.5); 5-seed
  dispersion ablation in MLflow (G1.7)
- [ ] **P1.5 Walk gates G1.1–G1.7** — net band 0.5–2.0; ≥ 1.5 ⇒ written
  plausibility note vs Da–Nagel–Xiu; > 2.5 ⇒ leakage review. A flat result
  is the literature's base rate, not a bug to tune away.

---

## Phase 2 — Overlays (weeks 6–8)

*Three brake pedals: HMM stress detector, 8-K news gate, crowding monitor.
Brakes only shrink — multipliers in (0,1], anything else raises. Classic bug:
smoothed HMM inference de-risking before crashes it couldn't have foreseen.*

- [ ] 🟣 **P2.1 Regime overlay** — FILTERED probs only (truncate-at-t, last
  row; `hmmlearn.predict()` leaks); vol-sorted relabeling (O5); expanding
  window min 756 obs (N5); audit surfaces per B3; Test 21 green;
  gates G2.1/G2.2
- [ ] 🔵 **P2.2 News gate** — `filed_at` ≤ 18:00 ET on t, identical
  backtest/live, never EDGAR index date (B9); gated = FROZEN not zeroed (O7);
  universe exit supersedes freeze, exit = `risk_reduction` flow (B10); G2.3
  incl. P95 + earnings-week reporting (N13)
- [ ] 🔵→🟣review **P2.3 Crowding monitor** — four PIT inputs incl.
  publication-vintage join (Test 16); multiplier ∈ [0.3, 1.0]; O9 transfer
  clip(1 − 0.35·max(z̄,0), 0.3, 1.0), ±0.05 hysteresis, no whipsaw; gap
  input neutral pre-live (O6); G2.4
- [ ] 🔵 **P2.4 Ablations + invariants** — on/off tearsheet per overlay (G2.6);
  invariant tests green (G2.5); combined multiplier < ~0.15× ⇒ go flat
- [ ] 🔵 **P2.5 OSAP sleeve** (`make sleeve-b`) — same engine; DLSA↔OSAP
  correlation RECORDED with per-sleeve Sharpe + DSR (G2.8; must exist, need
  not clear C9 yet)
- [ ] **P2.6 M4 holdout (G2.7)** — all tuning uses dates < `holdout_start` =
  2024-07-01; ONE pre-registered holdout run at phase close, metrics trigger
  NO design changes; later parameter changes reset the G3.1 clock

---

## Phase 3 — Paper trading (weeks 9–16+, min 3 months)

*60+ straight trading days against a fake-money account: hands-free, realistic
fills, every emergency stop proven. Mostly ops code and patience.*

- [ ] 🟣 **P3.1 Execution + routing** — `Order.flow ∈ {alpha, risk_reduction,
  kill_switch}`; risk/kill flows go MOC (E8 — a sell limit below a gapped-down
  close never fills; fill certainty is the objective); E6 band = alpha flow
  only; `diff_orders` rounding + neutrality repair + capacity-exclusion
  logging (N4)
- [ ] 🔵 **P3.2 Daily job + ops** — journal gitignored, durability via nightly
  off-machine `make backup` (N11); digest; reconciliation ≤ 1% gross (G3.3);
  off-host dead-man heartbeat, 12h alert (G3.1/N10 — journald dies with the
  host); kill-switch dispositions + re-arm rules
- [ ] 🔵 **P3.3 Fire drill** — deliberately trigger K1–K3 once each; halts +
  alerts confirmed end-to-end (G3.5)
- [ ] 🟣 **P3.4 Shadow book (only if V6 trigger fired post-G2)** —
  submit-fenced from day one; a shadow order reaching `submit()` = automatic
  gate failure (Test 17); G3.7 via C5 decomposition per book, written to V1
  registry
- [ ] **P3.5 Walk gates G3.1–G3.8** — ≥ 60 consecutive days ≥ 95% hands-free,
  every failure post-mortemed; G3.4: trailing-120d Sharpe within 2.5 of the
  V2 decayed prior, breach confirmed 2 consecutive weeks (decay is the base
  case, not malfunction); G3.2 pass = optimistic lower bound; G3.8 unfilled
  turnover median ≤ 5%, P95 ≤ 20%

---

## Phase 4 — Live, small (gated, not scheduled)

- [ ] **P4.1 Entry (G4.1)** — all Phase-3 gates green simultaneously over the
  final 60 days, not best-of
- [ ] 🔵 **P4.2 Capital cap (G4.2)** — config-enforced; total loss genuinely
  acceptable; raised at most monthly, only if crowding ≥ 0.8 and drawdown < 5%
- [ ] 🔵 **P4.3 Manual-review gate (G4.3)** — first 20 live days: literal
  checkbox the job requires before next-day trading
- [ ] **P4.4 Standing rule (G4.4)** — any kill-switch fire ⇒ written diagnosis
  before re-enable; overriding a halt without one is the one unforgivable
  operational sin

---

## Rules for every session

1. A failing leakage test is NEVER fixed by loosening the test.
2. Edit order: params (`docs/04`) → contracts (`docs/01`) → tests → configs →
   code. Never the reverse. Every touched doc gets a dated change-log row.
3. Gates tighten freely; loosening requires written justification that the gate
   was wrong.
4. Sharpe > 3 anywhere is a leak until proven otherwise.
5. Sanctioned offense lives only behind O9/C9/D7/V6's named triggers — invent
   no edge ideas.
6. One module per session; point at `docs/` paths instead of pasting; `/clear`
   between unrelated tasks.
