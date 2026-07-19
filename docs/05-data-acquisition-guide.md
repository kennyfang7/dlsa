# 📡 05 — Data Acquisition Guide (v1)

> The exact artifacts to download, in dependency order. Sources verified Jul 2026; re-verify links at build time. Pin a commit/snapshot of anything pulled from GitHub into `data_lake/_vendor_snapshots/` so an upstream edit can't silently change your history.

## 1. PIT S&P 500 membership (the survivorship fix) — first thing to ingest

**Primary:** `github.com/fja05680/sp500` — "Current and Historical Lists of S&P 500 components since 1996." Key file: `S&P 500 Historical Components & Changes.csv` — one row per date with a comma-delimited ticker string; the repo also has `sp500_by_date.ipynb` showing snapshot extraction, and is actively maintained (changes since 2019 tracked in a separate CSV).

**Cross-check:** `github.com/hanshof/sp500_constituents` — same shape (per-date constituent lists, 1996→present). Ingest both; membership disagreements land in quarantine for manual resolution, mirroring the two-source price rule. **Disposition while disputed (2026-07-18, Sixth-Pass Audit N12): fail-closed** — a disputed name is excluded from the tradable set until resolved, but retained for coverage accounting (the G0.1/G0.1b denominators); resolutions land as new `universe_membership` rows with a later `recorded_at`, never edits (page 02).

Ingest task: parse into the append-only `universe_membership` log (add/remove events with effective dates), record the source commit SHA in `source_row_id` provenance.

**Known limitations to encode as tests:** starts 1996; ticker strings are as-of-then symbols (symbol changes must map through `identifier_map`); Wikipedia-derived corrections upstream can be late — that's fine (it's what was knowable), just don't "fix" history retroactively.

**Ingest task 1b — identifier_map v0 (added 2026-07-17, Sixth-Pass Audit B11):** build `identifier_map` v0 from (a) fja05680 symbol strings + `symbol_change` corporate actions (security_id assigned at first sight), and (b) the OSAP permno↔ticker mapping at Phase 1. Schema and append-only validity-range rules on page 02; Phase-0 build-sequence slot between `universe` and `price ingest` on page 09. The loader hard-depends on this table — until this task existed, the "fiddliest part of the whole data layer" had a schema but no home, owner, or build step, guaranteeing Session-1 improvisation on the most join-critical table.

## 2. Prices & corporate actions

| feed | how | role |
|------|-----|------|
| yfinance | `pip install yfinance`; raw (`auto_adjust=False`) + actions | primary daily OHLCV |
| Stooq | `https://stooq.com/q/d/l/?s={ticker}.us&i=d` CSV | cross-check source |
| Alpaca Market Data | `alpaca-py` SDK, same keys as trading | recent bars + Phase 3 live |

Pull raw prices, store `adj_factor` separately (schema doc). Backfill from earliest universe date minus 2 years (factor lookback headroom). Expect and quarantine: missing delisted tickers on yfinance (log as coverage gaps — they matter for honesty about the tradable set), split-adjustment disagreements.

## 3. Firm characteristics — OSAP (Chen–Zimmermann)

- Site: `openassetpricing.com` (data page has direct downloads); code: `github.com/OpenSourceAP/CrossSection`.
- Easiest path: `pip install openassetpricing` — a Python package that downloads the 212 predictors' firm-level characteristics and portfolio returns directly.
- Needed for **IPCA only** — PCA baseline (Phase 0) runs without it, so this can be ingested during Phase 1.
- Apply a publication lag when setting `available_at` (accounting data isn't knowable at fiscal period end — the doc's "Q2 isn't knowable June 30" rule). Default lag: use OSAP's dating conventions, plus `TestFeatureAvailability` as the enforcement.
- Identifier note: OSAP is keyed on CRSP permno; the `identifier_map` table must map permno→ticker with validity dates. Budget real time for this — it's the fiddliest part of the whole data layer.

## 4. News / events

**v1 gate — SEC 8-K filings (free, public domain, reliable):**
- `pip install sec-edgar-downloader`, or hit the EDGAR full-text/daily-index feeds directly.
- EDGAR requires a `User-Agent` header with contact email; respect their 10 req/s guidance.
- Live: poll the daily index each evening for 8-Ks on universe names → `filings_8k` table.
- Historical: bulk daily indexes back to 2005+ for backtesting the gate.

**Historical news corpus — FNSPID (backtest research only):**
- HF dataset `Zihan1004/FNSPID`; code at `github.com/Zdong104/FNSPID_Financial_News_Dataset`. 15.7M news records + 29.7M prices for 4,775 S&P 500 companies, 1999–2023.
- Direct files: `Stock_news/nasdaq_exteral_data.csv` and `Stock_price/full_history.zip` under the HF repo.
- ⚠️ **License: CC BY-NC 4.0 — non-commercial.** Fine for research/backtesting the v2 gate concept; **not usable inside a live money-making system without permission.** Design accordingly: the production gate is 8-K-based (public domain); FNSPID only ever informs offline research. Note this in the repo README so it never gets wired into the live path by accident.

## 5. Market-state series (regime model) — FRED

- `pip install fredapi` + a free FRED API key (`fred.stlouisfed.org`).
- Series: `VIXCLS` (VIX close), `BAMLH0A0HYM2` (ICE BofA US High Yield OAS — the credit-spread input). SPX return and realized vol are derived from your own price table (use SPY as the index proxy so the live path needs no extra feed). **SPY ingest (2026-07-18, Sixth-Pass Audit N8):** SPY is not a universe member, so no membership-driven ingest would ever fetch it — the prices ingest (task 2) **explicitly includes SPY though not a member** (config surface on page 03), with the same two-source cross-check and validation as member names.
- Watch FRED publication lags: OAS posts next-day. Regime features at date t must use the vintage available at t — store `available_at` here too.

## 6. Short interest (crowding input)

- FINRA publishes consolidated short interest twice monthly: `finra.org` equity short interest files (free download). Bi-monthly cadence is fine — crowding is a slow signal.
- `available_at` = FINRA publication date (≈ T+8 business days after settlement date), not the settlement date itself. Classic leakage trap.

## 7. Alpaca (execution) setup checklist

1. Create account at `alpaca.markets` → generate **paper** API key/secret first.
2. `pip install alpaca-py`. Paper base URL `https://paper-api.alpaca.markets`; live keys are separate credentials — see secrets policy in the environment doc.
3. Confirm entitlements: free IEX-sourced market data tier is fine for daily bars; note it in the digest so no one mistakes it for SIP consolidated data.
4. Smoke test: fetch account, fetch a bar, place+cancel one paper limit order — wrap this as `make broker-smoke`.

## Reference anchors (pin here)

- Paper: arXiv **2106.04028** (Guijarro-Ordonez, Pelger, Zanotti; revised Oct 2022). Follow-up "Attention Factors" (Epstein, Wang, Choi, Pelger, ICAIF 2025).
- Authors' original repo: `github.com/gregzanotti/dlsa-public` (also linked from Markus Pelger's Stanford "Data and Code" page, `mpelger.people.stanford.edu/data-and-code`). Official code release, corresponding author Greg Zanotti — confirmed abandoned (last commit 2022-08-23 "Update LICENSE"; 6 commits total, no releases). Contains the trading-policy model architecture (`models/`) and training loop (`train_test.py`), but not the authors' original data — their README states it can't be released due to data-provider licensing. Use as ground truth for architecture details (specifically for P0.8's signal/policy net), not as the base. **Commit SHA pinned (2026-07-18): `ea8cc2958943eb1fe914aa4fad6998994a678323`** — this is HEAD of `main` and also the repo's last-ever commit, so the pin is permanent barring the author reviving the project.
- Clean independent PyTorch reimplementation + writeup: `bsiranosian.com/blog/deep-learning-statistical-arbitrage-part-1` (2026) — reproduces the paper's headline results (Sharpe parity on PCA/IPCA; CNN+Transformer > shallow net > classical mean-reversion). ⚠️ **Not usable as a starting codebase (confirmed 2026-07-18):** the post's own "Reproduction repo" section says the code isn't published yet ("I'll publish this code soon once I clean it up"). **Decision:** no external starting codebase. The one build-sequence step that would have ported from it — the signal/policy net (page 09/11, P0.8) — instead builds from (a) the paper's architecture section, (b) the authors' original repo above (already ground-truth-only, now doing double duty), and (c) `ref_policy_training.py` (page 06, item 3), purpose-built against this project's own contracts and leakage tests. Revisit if/when bsiranosian publishes — useful as a cross-check, not a blocker.
- Cautionary replication: arXiv **2412.11432** (Long & Xiao 2024) — the "Sharpe occasionally exceeding 10" result the main doc cites as a leakage/overfitting warning. ⚠️ **This paper was withdrawn by the author (Jan 2025)** — the withdrawal note cites an investment-universe selection error (used a static S&P 500 list instead of a dynamic PIT pool), which is exactly the survivorship trap this project's guardrails exist to prevent. Treat its Sharpe>10 number as a cautionary tale about the trap, not a benchmark to chase.

## Ingest order for Phase 0

1. PIT membership → 1b. identifier_map v0 (B11) → 2. prices (two sources) + corporate actions → 3. FRED series → smoke-test `get_universe`/`compute_returns` against the leakage suite → 4. OSAP (Phase 1; extends identifier_map with permno) → 5. 8-K feed (Phase 2) → 6. FINRA short interest (Phase 2).

## Change log

| date | change | reason |
|------|--------|--------|
| 2026-07-17 | Added ingest task 1b (identifier_map v0) and its slot in the Phase-0 ingest order. | Sixth-Pass Audit B11: identifier_map had a schema (page 02) and a warning ("fiddliest part of the data layer") but no build task anywhere — the loader hard-depends on it. |
| 2026-07-18 | §5 gains the explicit SPY ingest line — prices ingest includes SPY though not a universe member, config surface on page 03 (N8); §1's cross-check gains the fail-closed dispute disposition — disputed names untradable but retained for coverage accounting, resolutions as new rows (N12, mirrored on page 02's `universe_membership` rules). | Sixth-Pass Audit Part 2 (N8, N12) |
| 2026-07-18 | Reference anchors: bsiranosian reimplementation confirmed unpublished (author's own post: code not yet released). Dropped as the starting codebase — no SHA pin needed. P0.8 (signal/policy net) rebuilt to source from the paper + authors' repo + `ref_policy_training.py` instead. | User caught that the linked repo isn't actually published; verified directly against the blog post before editing the plan. |
