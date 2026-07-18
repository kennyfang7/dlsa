---
paths:
  - "dlsa/data/**/*.py"
  - "scripts/ingest*.py"
---

# Data Layer Rules — Free Data Is Guilty Until Proven Innocent

yfinance/Stooq data has gaps, bad adjustments, and silent ticker changes.
Every ingest must validate before writing to the lake; bad data that reaches
the lake becomes fake alpha downstream.

## Hard rules

- **Two-source cross-check.** Daily closes are compared across primary and
  secondary sources; disagreement > 50 bps on any name flags the row as
  suspect instead of picking one silently.
- **Validation gates the write.** `validate_frame()` must pass before any
  Parquet write: no duplicate (ticker, date) rows, no negative prices/volumes,
  no absurd single-day returns (>|60%|) without a matching corporate action,
  no calendar gaps vs. the NYSE trading calendar.
- **Survivorship: the PIT constituent calendar is append-only.** Never
  "clean up" past membership rows; corrections are new rows with an effective
  date. Deleting history rewrites the past.
- **Store both raw and adjusted prices**, with the adjustment factor as its
  own column. Never overwrite raw with adjusted.
- **Missing data is missing.** Represent as NaN + an exclusion flag for that
  (ticker, date). Forward-filling prices for return computation is forbidden —
  it manufactures zero-return days and understates volatility.
- **Delistings are data, not errors.** A ticker disappearing must produce a
  delisting record (last date, reason if known), because the backtest needs to
  know the position went to zero/exit — not that the stock vanished.
- **Idempotent ingests.** Re-running the same ingest for the same date range
  must not duplicate rows (upsert on (ticker, date, source)).

## When editing here

1. Any change to adjustment logic or return computation: run
   `make test-leakage` (the return-correctness tests live there) and spot-check
   one known split (e.g. a 4:1) end to end.
2. New data source? It lands in `data_lake/vendor_intake/<source>/` under the
   D7 protocol (frozen param, page 04): PIT vintages with publication-date
   columns, loader-enforced lag, and a hard quarantine from training and
   selection until its CPCV ablation gate passes (Test 20). Add it to the
   cross-check matrix and write a validation test BEFORE the ablation — a
   source that can't pass ingest hygiene doesn't get an ablation.
3. Never widen a validation threshold to "make the pipeline pass." Quarantine
   the offending rows and surface them in the daily digest instead.
