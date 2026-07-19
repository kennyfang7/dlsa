# 🗄️ 02 — Data Lake Schema & Layout (v1)

> Every module reads/writes these exact tables. No module invents its own frame shape. All Parquet, queried via DuckDB. `data_lake/` is gitignored **except** `raw/sp500_pit_membership.csv` (committed deliberately — git history is its provenance record). `journal.sqlite` (E2) lives in `data_lake/` and is **gitignored like the rest**: it is live order state with WAL/SHM sidecars, never a repo artifact — durability is a backup concern (audit item N11), not git's. Schemas live here (and in `dlsa/data/schemas.py` as pandera/dataclass definitions that validate on read AND write).

## Directory layout

```
data_lake/
  prices/               # partitioned by year: prices/year=2024/*.parquet
  corporate_actions/
  universe/             # PIT membership calendar (append-only)
  delistings/
  identifier_map/       # security_id ↔ source-ID mapping (added 2026-07-17, B11): Parquet, append-only;
                        #   corrections are new validity ranges — never edits. The loader hard-depends on it.
  characteristics/      # OSAP firm characteristics (monthly)
  news/
    filings_8k/         # v1 news gate source
    fnspid/             # historical news (backtest only — see license note in acquisition guide)
  market_state/         # regime-model inputs (daily)
  short_interest/       # FINRA bi-monthly short interest (O6/O9) — publication-vintage keyed
  borrow_status/        # daily ETB/HTB broker snapshots (added 2026-07-18, N9) — E7's migration
                        #   trigger is unmeasurable without a stored borrow-status history
  runs/                 # everything the daily job emits (audit trail)
    signals/  weights/  overlay_states/  orders/  fills/  digests/
    backtests/          # V1 trial registry: one record per completed make backtest run,
                        #   keyed by canonical config hash — APPEND-ONLY, never reset
    selection/          # V4 CPCV harness outputs (SelectionReport + PBO) — never quoted
                        #   as performance; firewall in the page-01 contract
    provenance/         # per-run served-source frames (loader contract, D5)
  models/               # versioned trained artifacts + metadata (never overwritten)
                        #   an ensemble (V3) is ONE version whose manifest lists member checkpoints
  synthetic/            # RESERVED (frozen param V7, Phase 2): Tail-GAN scenario sets.
                        #   NEVER a training or selection input — hardened quarantine test
  vendor_intake/        # RESERVED (frozen param D7): staging for ANY new data source — PIT vintages
                        #   with publication-date columns; quarantined from training AND selection
                        #   until that source's CPCV ablation gate passes (hardened Test 20)
  journal.sqlite        # order/position journal, SQLite WAL (frozen param E2) — gitignored (see intro);
                        #   durable via off-machine backup (N11), never via git
  raw/
    sp500_pit_membership.csv   # committed (not gitignored) — git history is its provenance
                                #   record; commit SHA logged on page 06
quarantine/             # rows that failed validation, kept for the daily digest
```

## Tables

### prices — one row per (ticker, date, source)

| column | type | notes |
|--------|------|-------|
| ticker | str | as-traded symbol; see identifier policy below |
| date | date | NYSE trading date |
| open, high, low, close | float64 | **RAW, unadjusted** |
| volume | int64 | raw shares |
| adj_factor | float64 | cumulative split+dividend factor; `close * adj_factor` = adjusted close |
| source | str | one of: yfinance, stooq, alpaca |
| ingested_at | timestamp (UTC) | |

Keys: PK (ticker, date, source) — ingest upserts on this key (idempotency rule). Raw and adjusted are never stored in each other's columns; adjusted is always derived via `adj_factor`. **Single return-computation path (2026-07-18, N1):** the engine's modeling returns come from `close_raw` + `corporate_actions` through `compute_returns` only; the `adj_factor`-derived `close_adj` is a diagnostic/human surface, never a modeling input. `validate_frame` asserts `pct_change(close_adj) ≈ compute_returns(close_raw, actions)` within 1e-8 on overlapping coverage — disagreement is a validation event (quarantine + digest), never a silent pick between two adjustment truths.

### corporate_actions

| column | type | notes |
|--------|------|-------|
| ticker, date | str, date | PK with `type` |
| type | str | one of: split, dividend, symbol_change |
| ratio | float64 | split ratio (4.0 = 4:1) or dividend per share |
| detail | str | e.g. old→new symbol |

### universe_membership — **append-only**

| column | type | notes |
|--------|------|-------|
| ticker | str | |
| effective_date | date | when this row becomes true |
| action | str | one of: add, remove |
| source_row_id | str | provenance into the raw constituent CSV |
| recorded_at | timestamp | when WE learned it |

Corrections are new rows with a later `recorded_at` — history is never edited or deleted. `get_universe(date)` replays this log up to `date`. **Membership-disagreement rule (2026-07-18, N12):** disputed names are **fail-closed**: excluded from the tradable set, retained for coverage accounting (the G0.1/G0.1b denominators); resolutions land as new membership rows with a later `recorded_at`, never edits.

### delistings

| ticker | last_trade_date | reason | terminal_return |
|--------|----------------|--------|----------------|
| str | date | `acquired`/`bankrupt`/`delisted`/`unknown` | float, NaN if unknown |

A ticker vanishing from prices without a delisting row is a validation failure, not a shrug.

### identifier_map — one row per (security_id, source, source_id) validity range

| column | type | notes |
|--------|------|-------|
| security_id | str | the internal stable ID; assigned at first sight |
| source | str | one of: ticker, permno (OSAP), fnspid |
| source_id | str | the identifier in that namespace |
| valid_from, valid_to | date, date | validity range; `valid_to` NaT = still valid. Append-only — corrections are NEW validity ranges, never edits |

Built as a real ingest task (page 05, task 1b): v0 from fja05680 symbol strings + `symbol_change` corporate actions; the OSAP permno↔ticker mapping joins at Phase 1. Slotted into the Phase-0 build sequence between `universe` and `price ingest` (page 09).

### characteristics (OSAP) — monthly, one row per (permno_or_ticker, month)

| column | type | notes |
|--------|------|-------|
| ticker | str | mapped from OSAP identifiers via the identifier map |
| month_end | date | period the value describes |
| available_at | date | **the join key for all modeling** — publication lag applied |
| char_name | str | OSAP predictor name (long format) |
| value | float64 | raw; rank-standardization to (−0.5, 0.5) happens in `factors/`, causally |

### filings_8k

| ticker | filed_at (timestamp UTC) | accession_no | items (str) |
|--------|--------------------------|--------------|-------------|

News gate v1 = any row with `filed_at` in the trailing 3 calendar days. **Information-time note (2026-07-17, B9):** the gate joins on `filed_at` against the E5 18:00 America/New_York cutoff (frozen param O2, amended) — never on EDGAR index date. Filings accepted after the cutoff belong to t+1's trailing window, identically in backtest and live.

### market_state — daily, regime-model inputs

| date | spx_ret | realized_vol_21d | vix_close (FRED: VIXCLS) | hy_oas (FRED: BAMLH0A0HYM2) | available_at (timestamp UTC) |
|------|---------|-----------------|--------------------------|------------------------------|------------------------------|

`available_at` = the FRED vintage timestamp (VIXCLS and HY OAS post next-day; SPX return and realized vol are derived from own prices, available at t close). The regime model at date t may only consume rows with `available_at` ≤ t.

### short_interest — FINRA bi-monthly

| column | type | notes |
|--------|------|-------|
| ticker | str | mapped to security_id via `identifier_map` at load |
| settlement_date | date | the period the figure describes |
| publication_date | date | **the join key for all modeling** — FINRA disseminates ~T+8/9 business days after settlement; the crowding overlay at date t may only consume rows with `publication_date` ≤ t (hardened Test 16) |
| short_interest_shares | int64 | raw; `days_to_cover` is DERIVED at read time as shares ÷ trailing-21d median daily volume from `prices` — never stored |
| ingested_at | timestamp (UTC) | |

### borrow_status — daily broker snapshot (added 2026-07-18, N9)

| column | type | notes |
|--------|------|-------|
| ticker | str | mapped to security_id via `identifier_map` at load |
| date | date | snapshot trading date |
| status | str | one of: ETB, HTB (easy-/hard-to-borrow) |
| source | str | e.g. alpaca |
| ingested_at | timestamp (UTC) | |

E7's migration trigger (">20% of intended short gross excluded over rolling 21 trading days") is unmeasurable without a stored borrow-status history.

### runs/* — the audit trail (one file per run date)

- `signals/`: (date, ticker, signal)
- `weights/`: (date, ticker, raw_weight, post_overlay_weight, final_weight)
- `overlay_states/`: (date, regime_state, regime_mult, crowding_mult, n_news_gated, gated_tickers)
- `orders/` and `fills/`: order id, ticker, side, qty, limit, status, fill_px, fill_qty, ts, book (`live` | `shadow` — dormant until V6's trigger), flow (`alpha` | `risk_reduction` | `kill_switch` — frozen param E8)
- `digests/`: the rendered daily summary (md)
- `backtests/`: (config_hash, run_at, git_sha, lake_snapshot_date, sharpe, deflated_sharpe, n_trials_at_run, signal_override) — the V1 trial registry. `config_hash` = SHA-256 over the resolved config (sorted keys; timestamps/output paths excluded; V3 seed list included). Rows with non-null `signal_override` are excluded from the trial count.
- `selection/`: (selection_id, run_at, candidates, chosen_config_hash, median_sharpe_by_path, pbo) — V4 harness output; deliberately no field named `sharpe` a tearsheet could ingest.

### models/ registry

`models/<component>/<version>/` containing `weights.pt`, `config.yaml` (exact training config), `train_window.json`, `metrics.json`, `git_sha.txt`. A `registry.parquet` indexes them. Retraining always writes a new version directory.

## Identifier policy

- Canonical ID is the **as-traded ticker + a stable internal `security_id`** assigned at first sight; `symbol_change` corporate actions remap ticker→security_id over time.
- All joins across tables use `security_id` internally; ticker is for I/O and broker orders.
- OSAP/FNSPID identifiers get a maintained mapping table `identifier_map` (security_id, source, source_id, valid_from, valid_to).

## Non-negotiables (restated from CLAUDE.md, enforced by schemas.py)

1. Writes go through `validate_frame()`; failures land in `quarantine/`, never in the lake.
2. `universe_membership` is append-only.
3. Missing prices stay NaN with an exclusion flag; no imputation at the storage layer.
4. Every table with model-consumable data has an `available_at`-style column or is joined through one.

## Change log

| date | change | reason |
|------|--------|--------|
| (init) | v1 | — |
| 2026-07-12 | Repaired truncated enum cells in `prices.source`, `corporate_actions.type`, `universe_membership.action`. Added `available_at` to `market_state`. | Independent verification pass |
| 2026-07-15 | Directory layout gained `journal.sqlite` (E2) and `raw/sp500_pit_membership.csv`; the blanket "`data_lake/` is gitignored" line corrected to name the committed exception. | Readiness review |
| 2026-07-15 | Added `runs/backtests/` (V1 trial registry), `runs/selection/` (V4 outputs), `runs/provenance/` (loader contract), ensemble-manifest note on `models/` (V3), and the RESERVED `synthetic/` directory (V7). | Bear-Case review adoption |
| 2026-07-16 | Added `short_interest/` directory + table schema; RESERVED `vendor_intake/` with D7 quarantine rule; `book` column on `runs/orders` and `runs/fills` (dormant, V6 shadow). | Alpha-Roadmap adoption |
| 2026-07-17 | **Correction (B5):** `journal.sqlite` is gitignored with the rest of `data_lake/` — committing a daily-churning WAL-mode SQLite order journal is operationally wrong. Added `identifier_map/` to the layout and promoted its schema to a real Tables entry with append-only validity-range semantics (B11); `flow` column added to `runs/orders` | `fills` and the E2 journal schema (B8); `filings_8k` gains the E5-cutoff join note (B9). | Sixth-Pass Audit B5/B8/B9/B11 |
| 2026-07-18 | `prices` keys note pins the single return-computation path (N1); `borrow_status/` added with a real table schema (N9); `universe_membership` gains the fail-closed membership-disagreement rule (N12). | Sixth-Pass Audit Part 2 |
