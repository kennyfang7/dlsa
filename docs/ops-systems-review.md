# ⚙️ Ops & Systems Review

Companion to the Red-Team Architecture Review, which covers quant-methodology leaks (estimation windows, inference direction, train/deploy mismatches). This review covers the layer that one doesn't: **where the software itself breaks with real money attached** — order state, scheduling/time semantics, and vendor dependency risk. Findings ordered by severity. New frozen parameters this review implies are tagged with their proposed IDs (E-, D3/D4, X2, K5) — see 04 — Frozen Parameters v1 and 01 — Interface Contracts for the corresponding contract additions.

---

## SEVERITY 1 — Real-money loss modes with no current mechanism

### 1.1 No durable order/position state store — re-running the job can double-submit the book

The interface contract has `submit(orders, mode) -> list[Fill]` as a synchronous call and `reconcile()` alerting on drift, but nothing durable backs either. Real order lifecycles are async state machines (submitted → accepted → partial → filled/rejected/expired), and nothing records what was sent before the process might die mid-run.

**Why it bites:** if the nightly job crashes after submitting order 40 of 120 and `make daily` is re-run (as the design assumes is safe — it's the whole reason for one shared code path), the first 40 orders get submitted a second time. No leakage test or backtest will ever catch this because it's a live-only failure mode. This is the single most common way retail-scale systematic traders lose real money — well before alpha decay gets a chance to matter.

**Fix:** an append-only order/fill journal (a DuckDB table in the existing lake is sufficient — no new infra), idempotent submission via a deterministic `client_order_id` (hash of date, security_id, side, config hash), broker account as position *truth* with the journal as the audit trail `reconcile()` diffs against, and an explicit unfilled-residual policy (cancel at window close, don't chase into the next session). See proposed params E1–E3.

### 1.2 Short-side microstructure is entirely unmodeled

A dollar-neutral book is ~50% short positions. Nothing in the cost model (X1), the backtest, or live execution accounts for **borrow availability** (easy-to-borrow vs. hard-to-borrow), **borrow fees**, **dividends-in-lieu** paid on shorts, or **Reg SHO / SSR** restrictions after a 10% intraday decline. The backtest currently assumes every negative weight is fillable and free to hold.

**Why it bites:** live shorts will occasionally be unavailable or expensively on-loan for names the model wants to short hardest (often the same names with recent bad news — correlated with the news-gate's blind spots). Silently skipping or substituting these breaks the dollar-neutrality the whole risk framework assumes.

**Fix:** backtest a flat borrow-fee assumption (proposed 50 bps annualized) plus an availability haircut; live execution gates candidate shorts against the broker's ETB/HTB list *before* portfolio construction, not after. See proposed param X2.

---

## SEVERITY 2 — Design gaps that will fire in ordinary operation, not just crises

### 2.1 The nightly job has no data-readiness model — it assumes a clean instant, and gets a smear

A single fixed-time cron entry presumes every input exists at that moment. In practice: EOD prices get corrected for hours after the close, EDGAR's daily 8-K index completes only late evening (the doc's own §3.4 already notes this), and — a concrete, currently-undetected bug — **FRED publishes VIXCLS and HY OAS (the O1b regime inputs) with roughly a one-business-day lag.** An evening job cannot see today's VIX close. The backtest will condition the regime overlay on same-day VIX; live physically cannot. That's a train/live information mismatch the leakage suite won't catch, because it's not a leak in training data — it's a live-only sensing gap.

**Compounding effect:** K3 ("any validation failure ⇒ no trading") turns *routine vendor lateness* into skipped trading days. Consecutive skips leave a drifting, unmanaged market-neutral book — the exact unmanaged-halted state Red-Team 2.3 flagged, but reachable here by nothing more exotic than a slow data vendor.

**Fix:** per-source readiness checks against a hard decision deadline scheduled in exchange time (America/New_York, DST-aware — fixed-UTC cron silently drifts an hour twice a year against NYSE hours); "skip day" as a first-class, logged outcome; an explicit consecutive-skip limit that escalates to flatten rather than continuing to halt. See proposed params D3, E4, E5, K5.

### 2.2 Cross-source quarantine becomes the availability failure, not the protection

D1's 50 bps cross-source tolerance assumes yfinance and Alpaca measure the same thing. If the Alpaca account is on a free/basic data tier, its feed may be single-venue (IEX) rather than a consolidated close — worth confirming on your current plan. On volatile days, cross-source gaps will widen and become **correlated across many names at once**, exactly when the strategy most needs to trade correctly. Mass quarantine then trips K3 and the book sits stale through the sessions where risk management matters most — the safety mechanism becomes the outage.

**Fix:** a cap on same-day quarantine fraction (proposed 15% of universe) that converts to an explicit data-quality halt (already K3) rather than silently trading the quarantine-survivors as if the universe were unaffected. See proposed param D4.

### 2.3 Vendor fragility beyond price data

yfinance is an unofficial, frequently-breaking scraper serving as the *primary* historical source; the PIT constituent calendar is an unpinned GitHub CSV that can be edited or removed without notice; EDGAR enforces a ~10 req/s rate limit with a mandatory User-Agent header. None of these have a fallback, a pinned/vendored snapshot, or a monitoring signal distinct from "today's ingest failed."

**Fix:** vendor a pinned copy of the PIT calendar, OSAP, and FNSPID snapshots at each retrain (they're external artifacts you depend on but don't control); track vendor-specific error rates separately from data-quality validation so "yfinance is down" and "the data looks wrong" produce different alerts.

---

## SEVERITY 3 — Operational and epistemic gaps

**3.1 No watchdog for the watcher.** Every alert path lives on the machine that might fail. If the host dies or the disk fills, cron silently stops — no trading *and no alert* — while a live book drifts unmanaged. A basic dead-man's switch (external "job didn't check in" ping) is roughly half a day of work and should exist before Phase 3, not be deferred until something breaks.

**3.2 No reproducibility spine.** "Version every model" (§7) has no mechanism behind it: no model registry, no promotion step from candidate to deployed, no run manifest tying a trading day to (data snapshot hash, config hash, model version). Because yfinance retroactively re-adjusts history, yesterday's backtest is *already* unreproducible today unless the lake is snapshotted — this also operationalizes Red-Team 3.1's raw-vs-adjusted fix.

**3.3 Live corporate actions on held positions are unspecified.** Red-Team fixed delisting *returns in backtest*; nobody has specified what the live system does the morning a held name is halted, subject to a cash/stock merger election, or spun off. Running ~400 S&P names long-short, this will happen within months, not years.

**3.4 Tax lot accounting.** A daily-rebalanced long-short book in a taxable account generates wash-sale entanglement at industrial scale. Worth logging tax lots from day one even if the accounting itself is deferred — it's much harder to reconstruct retroactively.

**3.5 DR / backup.** No stated backup or restore runbook for the lake. A single-machine setup (by design, and reasonably so) means disk failure with no recovery path is a real, boring risk, not an edge case.

---

## What this doesn't re-litigate

DuckDB write-locking is a non-issue at single-writer nightly scale, provided writes go to a temp file with atomic rename — not worth a severity tier. The methodology-level leaks (factor estimation windows, HMM inference direction, train/deploy distribution shift) are the Red-Team review's territory and are correctly identified there; nothing here duplicates that pass.

## Verdict

None of the above requires re-architecting — every fix slots into an existing box (execution, orchestration, data layer) the same way the Red-Team fixes slotted into existing modeling code. The theme here mirrors that review's conclusion: **each component is individually reasonable, and the failures live in the seams between them** — specifically the seam between "weights computed" and "the book is true," and the seam between "data exists somewhere" and "data is here, on time, in this process." Recommend freezing the proposed parameters (E1–E5, D3–D4, X2, K5) in page 04 and the journal contract in page 01 before Phase 3 begins; none of it blocks Phase 0–1 work.
