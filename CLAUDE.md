# DLSA Trading System

Deep-learning statistical arbitrage: daily-rebalanced, market-neutral US equity
strategy. Backtest → Alpaca paper → live. **Money is at stake: correctness and
data integrity beat cleverness, always.**

## Commands

make setup          # create venv + install pinned deps (uv sync)
make test           # full pytest suite — MUST pass before any commit
make test-leakage   # look-ahead/survivorship tests only (tests/test_lookahead_bias.py)
make backtest       # run backtest with configs/backtest.yaml (logs Sharpe + Deflated Sharpe, V1)
make select         # CPCV model selection (V4) — chooses configs; NEVER a source of results
make daily          # run the full daily pipeline once (dry-run by default)
make lint           # ruff check + ruff format
make broker-smoke   # verify on-close order entitlement (E6) — run before any paper run
make digest          # render yesterday's daily digest to stdout
make sleeve-b       # V9a OSAP sleeve through the SAME engine — DORMANT until Phase 2 (records G2.8)

Run `make test-leakage` after ANY change to `dlsa/data/`, `dlsa/factors/`, or
`dlsa/backtest/`. If a leakage test fails, the fix is never to loosen the test.

## Project map

dlsa/
  data/        # ingest, validation, PIT universe calendar  ← most safety-critical
  factors/     # PCA / IPCA factor models → residuals
  signals/     # CNN+Transformer signal network (PyTorch); 5-seed ensemble (V3) +
               #   EB shrinkage (V5, shrinkage.py) — policy consumes SHRUNK signals only
  policy/      # cost-aware allocation network
  overlays/    # regime HMM, news gate, crowding monitor — can only REDUCE exposure
  backtest/    # walk-forward engine; shares portfolio code with live
  selection/   # CPCV harness (make select, V4) — selects configs, never reports performance
  allocation/  # DORMANT (C9): fixed 50/50 multi-sleeve combiner — do NOT build or import
               #   before C9's five trigger conditions hold (page 04); contract on page 01
  execution/   # Alpaca order routing + reconciliation
  jobs/        # nightly entrypoint (make daily → dlsa.jobs.daily)
  monitoring/  # digest + drift checks (make digest)
  metrics.py   # THE Sharpe implementation (frozen param M1); nothing else computes its own
configs/       # YAML configs; every run is driven by a config, never hardcoded
tests/         # pytest; leakage tests in test_lookahead_bias.py
data_lake/     # Parquet files via DuckDB (gitignored) + journal.sqlite (SQLite WAL
               #   order/position journal, frozen param E2 — gitignored) + raw/sp500_pit_membership.csv
               #   (committed, NOT gitignored — git history is its provenance record)

## Non-negotiable invariants

- **Point-in-time everywhere.** Any data used at date t must have been knowable
  at t. Universe membership comes ONLY from `data/universe.py::get_universe(date)`
  — never from a current constituent list.
- **Backtest and live share one code path.** Portfolio construction lives in
  `dlsa/backtest/portfolio.py` and is imported by both. Never fork a "live copy".
  The CPCV harness (`dlsa/selection/`) may reuse components but NEVER produces
  reported performance — gate numbers come from `run_backtest` only.
- **Overlays only shrink.** Regime/news/crowding multipliers are clamped to
  (0, 1]. Code that lets an overlay increase exposure is a bug.
- **Adjusted prices for returns, raw prices for fills.** Both are stored;
  mixing them corrupts either the signal or the execution model.
- **No silent model overwrites.** Trained models are versioned artifacts;
  retraining writes a new version.
- **Fail closed.** On data-quality failure or any tripwire, halt and alert.
  Never trade on a guess or a forward-fill of missing prices.
- **The design holdout is sacred.** The final 24 months of the sample
  (`holdout_start`, frozen param M4) are off-limits to design iteration,
  parameter choice, or gate tuning until the single pre-registered Phase 2
  evaluation run. `--holdout-release` enforces this once built; until then,
  treat it as a standing rule, not a check that catches you.

## Docs canonicality (decided 2026-07-21)

`/docs/` is the source of truth for all contracts, frozen parameters, and
acceptance criteria. `PHASE_CHECKLIST.md` (repo root) is the canonical build
checklist. All changes go through PRs — never edit Notion first. Notion pages
01–11 are narrative archives; sync them same-day from the repo after any PR
merges. When this file and `docs/04-frozen-parameters.md` disagree, the frozen
parameters win.

## Conventions

- Python 3.11, type hints on public functions, `ruff` enforces style (don't
  restate style rules here).
- All timestamps are timezone-aware UTC; trading dates use the calendar
  selected by config (`dates.calendar`: `NYSE` for real data, `BDAY` for
  synthetic test fixtures only), resolved via `data/calendar.py`. Don't
  "fix" a `BDAY` fixture to NYSE — that's the correct path for synthetic data.
- New behavior requires a test. Anything touching dates/joins requires a
  leakage test.
- Prefer editing existing modules over creating new ones; check the map above
  before adding files.

## Deep docs (load on demand)

Before implementing or reviewing anything in `dlsa/factors/`, `dlsa/signals/`,
or `dlsa/policy/`, read
`.claude/skills/dlsa-quant-guardrails/references/dlsa-methodology.md` (the
DLSA paper, equation by equation — ships inside the guardrails skill, per
page 06 item 6). It is deliberately NOT inlined here — pull it only when
working in those areas.

## Path-scoped rules (in .claude/rules/)

Extra guardrails auto-load when you READ files in `dlsa/data/`, `dlsa/factors/`,
or `dlsa/backtest/`. When CREATING a new file in those areas, read a sibling
file first so the rules load (rules trigger on read, not write).