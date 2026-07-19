# 🔌 01 — Interface Contracts (v1)

> The API the codebase must be built **to**. Most signatures below are already hardcoded in `tests/test_lookahead_bias.py` — the tests are the senior party in any disagreement. **Rule: if code and contract diverge, change the code. Changing a contract requires editing this page first, then the tests, then the code — in that order.**

## Global conventions

- **Prices frame shape:** wide `pd.DataFrame`, `DatetimeIndex` (tz-aware UTC, normalized to trading dates of the configured calendar) × **security_id** columns, float64. This is the shape every fixture in the test suite uses.
- **Identifiers:** modeling frames, signals, weights, and positions are keyed by `security_id` (page 02 identifier policy — stable across symbol changes like FB→META). As-traded tickers exist only at the ingest and execution boundaries. Synthetic fixture IDs (`SYN000`…) are security_ids.
- **Dates:** all functions accept/return `pd.Timestamp` (tz-aware UTC). Trading calendar comes only from `dlsa/data/calendar.py`. The config's `dates.calendar` selects `NYSE` (real data) or `BDAY` (plain business days — synthetic fixtures only). The engine trades the **intersection** of the config `[start, end]` range and the supplied price index: config dates are bounds, not coverage demands. Coverage enforcement lives in ingest validation, never in the engine.
- **Weights/positions:** `pd.Series` indexed by security_id, dollar-neutral (sums ≈ 0), gross (L1 norm) ≤ 1.0 after overlays.
- **No function may consume data dated after its `asof`/decision date.** Every contract below inherits this.

## dlsa/data/universe.py

```python
def get_universe(date: pd.Timestamp) -> list[str]
```

- Returns security_ids that were index members **on that date**, from the append-only PIT calendar in the **active lake dir** (`logging.lake_dir` / `DLSA_LAKE_DIR`). There is exactly one behavior in production and tests: test_min's `fixture_all` universe works by writing synthetic SYN membership rows into the test lake (`/tmp/dlsa_test_lake`), which `get_universe` then replays normally — no fixture branch inside the function.
- Deterministic: same date → identical list, same order (tested).
- Must return historical members that are no longer in the latest universe (survivorship test).
- Raises `KeyError` for dates outside calendar coverage — never silently returns the nearest snapshot.
- Module also exposes `latest_universe_date() -> pd.Timestamp` (last covered date) and `calendar_available() -> bool` (whether a populated calendar exists in the active lake). The test suite uses these; tests never call `Timestamp.now()`.

## dlsa/data/returns.py

```python
def compute_returns(
    prices: pd.DataFrame,                       # RAW close prices
    corporate_actions: pd.DataFrame | None = None,  # columns: ticker, date, type, ratio
) -> pd.DataFrame                               # same shape, daily simple returns
```

- Applies split/dividend adjustment internally from `corporate_actions`; a 4:1 split day returns ~0.0, not −75% (tested to `abs < 1e-6`).
- A NaN price at t produces NaN returns at **both t and t+1**, never 0.0 (tested). No forward-filling, ever.
- Never mutates the input frame.

## dlsa/data/validation.py

```python
def validate_frame(df: pd.DataFrame, source: str) -> ValidationReport
```

- Gates every Parquet write (see data-ingest rules). `ValidationReport.passed: bool`, `.quarantined: pd.DataFrame`, `.issues: list[str]`.
- Checks: duplicate (ticker, date), negative prices/volumes, |return| > 60% without matching corporate action, calendar gaps vs NYSE, >50 bps cross-source close disagreement.
- **Stale-bar check (added 2026-07-18, Sixth-Pass Audit N7 — Red-Team 2.1 finally landed):** flag any (ticker, source) whose OHLCV row is identical to its prior session while ≥80% of the universe moved — a repeated bar prints a clean 0.0% return and otherwise sails through; single-source rows (allowed by G0.1's "≥1 source") have no cross-source defense, so **stale single-source rows quarantine**.
- **Adjustment-consistency check (added 2026-07-18, Sixth-Pass Audit N1):** `pct_change(close_adj) ≈ compute_returns(close_raw, corporate_actions)` within 1e-8 on overlapping coverage; disagreement is a validation event (quarantine + digest), never silently resolved.

## dlsa/factors/pca.py (and ipca.py mirroring it)

```python
class PCAFactorModel:
    def __init__(self, n_factors: int): ...

    def build_features(self, prices: pd.DataFrame, asof: pd.Timestamp) -> pd.DataFrame
    #   Returned frame MUST include an `available_at` column (tz-aware UTC).
    #   Invariant (tested): (features["available_at"] <= asof).all()
    #   Invariant (tested): build_features(prices, asof) == build_features(prices.loc[:asof], asof)
    #   i.e. truncating the future must not change any value (atol 1e-10).

    def fit_scaler(self, prices: pd.DataFrame, train_end: pd.Timestamp) -> Scaler
    #   Scaler exposes sklearn-style `.mean_` and `.scale_`.
    #   Invariant (tested): corrupting rows AFTER train_end must not change mean_/scale_ (rtol 1e-12).

    def preprocess(self, prices: pd.DataFrame, train_end: pd.Timestamp) -> pd.DataFrame
    #   The WHOLE preprocessing chain (winsorize → scale → any transform), fit on data
    #   <= train_end, applied to the full index. Returns transformed values, not fitted params.
    #   Invariant (tested, Hardened Test 10): corrupting rows AFTER train_end must leave every
    #   returned row dated <= train_end bit-for-bit unchanged.
    #   Rationale: fit_scaler only exposes fitted ATTRIBUTES; a leak can live in a transform
    #   step downstream of the scaler and never touch mean_/scale_. This probes the OUTPUT.

    def residuals(self, prices: pd.DataFrame, asof: pd.Timestamp) -> pd.DataFrame
    #   Eigenvectors/Γ used at asof come from a window ending BEFORE asof's refit period.
    #   Invariant (tested, Hardened Test 7): residuals(prices, asof=t).loc[t] ==
    #   residuals(prices.loc[:t], asof=t).loc[t]  (atol 1e-10) — truncating the future must
    #   not change today's residual.

    @property
    def loading_fit_end_dates(self) -> pd.Series
    #   Index: residual date. Values: the END DATE of the fit window whose loadings/Γ were
    #   used to produce that date's residual. Populated by residuals()/preprocess().
    #   Invariant (tested, Hardened Test 7): (index > values).all() — strictly precedes, never equals.
    #   Rationale: makes the walk-forward refit boundary AUDITABLE rather than merely asserted.
```

> **Naming note (2026-07-14):** the Hardened Leakage Tests page originally called this `compute_residuals(prices)` — no `asof`, different name. That was test-side drift, not a real second API; the tests were corrected to `residuals(prices, asof)`. `preprocess` and `loading_fit_end_dates` were genuinely missing and are added above.

## dlsa/backtest/engine.py

```python
def run_backtest(
    prices: pd.DataFrame,
    config: str | Path,                    # path to YAML config — never kwargs for run params
    shuffle_forward_returns: bool = False, # test hook: shuffles signal→next-day-return mapping
    signal_override: Literal["own_return"] | None = None,  # test hook (Hardened Test 9)
) -> BacktestResult
```

- `signal_override="own_return"` replaces the learned signal with each name's OWN contemporaneous return at t, bypassing the factor/policy stack entirely. This makes same-bar (leaky) vs. lag-1 alignment produce deterministically OPPOSITE PnL paths, so alignment is proven behaviorally instead of trusted from `meta["signal_to_trade_lag_days"]`. It is a **test hook only**: `run_backtest` must raise `ValueError` if `signal_override` is not None while `mode != "dry"`, and any non-None value must be recorded in `meta["signal_override"]` so no tearsheet can be produced from an overridden run unnoticed.
- **Trial registry (frozen param V1).** Every completed run appends a record to `runs/backtests/` keyed by the canonical config hash (SHA-256, sorted keys, timestamps/output paths excluded, V3 seed list included — one ensemble = one trial). The registry is append-only and never reset; `deflated_sharpe` is derived from its all-time distinct-hash count. Runs with `signal_override` set are recorded but excluded from the trial count (they are instrument checks, not strategy trials).

`BacktestResult` (dataclass):

| field | type | contract |
|-------|------|----------|
| `sharpe` | float | annualized, **net of configured costs**; computed per frozen param M1 (√252, simple daily net returns, no risk-free subtraction) by the single implementation `dlsa/metrics.py::sharpe` |
| `deflated_sharpe` | float | the Bailey–LdP DSR **probability** in [0, 1] per frozen param V1 (amended 2026-07-17, B2), computed by the single implementation `dlsa/metrics.py::deflated_sharpe(sharpe, n_obs, skew, excess_kurtosis, n_trials, sr_var_across_trials)` |
| `positions` | `dict[pd.Timestamp, pd.Series]` | per-date holdings; every nonzero name ∈ `get_universe(date)` (tested) |
| `returns` | `pd.Series` | daily net strategy returns |
| `meta` | dict | must include `"signal_to_trade_lag_days"` ≥ 1 (tested) |
| `turnover` | `pd.Series` | daily L1 turnover |
| `overlay_states` | `pd.DataFrame` | per-date regime state, news-gated names count, crowding multiplier |

## dlsa/backtest/portfolio.py — shared with live, no forks

```python
def build_portfolio(
    signals: pd.Series,
    current: pd.Series | None = None,  # held weights entering the rebalance; None ⇒ flat book
    overlay_multiplier: float = 1.0,   # combined regime × crowding, clamped to (0, 1]
    prev_overlay_multiplier: float | None = None,  # m_{t-1}; None ⇒ first rebalance,
                                       # treated as == overlay_multiplier (no exemption)
    news_gated: set[str] | frozenset[str] = frozenset(),
    constraints: Constraints | None = None,
) -> pd.Series                          # target weights
```

- Raises `ValueError` for `overlay_multiplier` outside `(0, 1]` — including exactly 0.0, 1.5, −0.5 (parametrized test). Never clips silently.
- **News gate = freeze, not flatten (frozen param O7).** For a name in `news_gated` with current weight w: the target must satisfy `sign(target) == sign(w)` (or target == 0 if w == 0) and `abs(target) <= abs(w)`. Reductions and exits toward zero are permitted; increases, sign flips, and new entries are not. A gated name held at w is NOT forced to 0.0.
- **Universe-exit precedence (O7 amended 2026-07-17):** universe exit and delisting supersede the freeze. A gated name removed from the PIT universe effective t is fully exited at the t close (classified `flow='risk_reduction'` → E8 instrument, C5-exempt).
- **Turnover-cap precedence (frozen param C5).** The C2 daily turnover cap binds **alpha-driven** turnover only. Exempt turnover at t = Σᵢ |wᵢ,t−1| × max(0, 1 − mₜ/mₜ₋₁); alpha-driven turnover = total L1 turnover − exempt component; C2 binds the alpha-driven part only.
- **Position count / ticket size (frozen params C6, C7).** When `constraints.max_positions` is set, only the top-N names by `abs(signal)` (split per side) receive nonzero weight. Names whose resulting target notional falls below `constraints.min_order_notional` are dropped to zero, never rounded up.
- Output is dollar-neutral and respects per-name/sector/turnover constraints.

## dlsa/overlays/ — one shared shape

```python
class Overlay(Protocol):
    def multiplier(self, asof: pd.Timestamp) -> float      # regime, crowding: in (0, 1]
class NewsGate(Protocol):
    def gated_names(self, asof: pd.Timestamp) -> set[str]  # names to FREEZE (O7: |target| ≤ |current|, same sign)
```

- Overlays never see or return anything that can increase exposure. Type-level enforcement: `multiplier` return validated at the portfolio boundary.
- **Crowding vintage rule (O9):** the crowding overlay's `multiplier(asof)` may compute its FINRA-derived inputs only from the **last published vintage as of `asof`** — never same-day values. Hardened Test 16 enforces this.
- **Regime audit surface (added 2026-07-17, B3):** `RegimeOverlay` exposes `state_vol_means() -> dict[int, float]` and `state_labels() -> dict[int, str]`. `multiplier(asof)` must use **filtered** (forward-only) state probabilities per O8. Hardened Test 21 enforces both.

## dlsa/execution/ (Phase 3)

```python
def diff_orders(current: pd.Series, target: pd.Series, prices_raw: pd.Series, equity: float) -> list[Order]
def submit(orders: list[Order], mode: Literal["dry", "paper", "live"]) -> list[Fill]
def reconcile(intended: pd.Series, actual: pd.Series) -> ReconReport
```

- `prices_raw` (unadjusted) is used for share sizing — never adjusted prices.
- Execution is the **only** layer that maps security_id → current as-traded ticker (via `identifier_map`) when building broker orders.
- `mode="dry"` is the default everywhere, including `make daily`.
- **Order type (frozen param E6).** `submit()` builds on-close orders (`time_in_force=cls`) submitted the evening of t, with a ±1% protective limit band around close(t); the execution window is the t+1 closing auction. **Flow scope (2026-07-17, B8):** the ±1% band applies to `flow='alpha'` orders only; `flow ∈ {'risk_reduction', 'kill_switch'}` orders are market-on-close (no band) per frozen param E8.
- **Order flow tag (frozen param E8).** `Order` gains `flow: Literal['alpha', 'risk_reduction', 'kill_switch']` (default `'alpha'`). `diff_orders` assigns it from the B1/C5 decomposition.
- **Ticket floor (frozen param C6).** `diff_orders` drops any order below `min_order_notional` and reports it as unfilled turnover in the `ReconReport`; it never rounds up to reach the floor.
- **Integer-share rounding (added 2026-07-18, N4).** `diff_orders` sizes shares = floor toward zero of notional / `prices_raw`. Post-rounding dollar-neutrality is repaired by trimming the larger side's smallest-|signal| tickets. Names where **one share exceeds C1 × equity** are dropped and logged as **capacity exclusions**.
- `submit()` raises if `equity < capital_floor` (frozen param C8) when `mode="live"`.

## dlsa/config.py (resolution + wiring introspection)

```python
def load_config(path: str | Path) -> Config

class Config:
    def resolved(self, key: str) -> Any
    #   Returns the FULLY RESOLVED value for a wiring key — for class keys, the imported
    #   class OBJECT itself (not its dotted-path string), so identity comparison works.
    #   Required keys: "engine_class", "factor_model_class", "policy_class",
    #                  "overlay_classes", "cost_model_class".
    #   Invariant (tested, Hardened Test 9): for every class key,
    #   load_config("configs/test_min.yaml").resolved(k) is load_config("configs/backtest.yaml").resolved(k)
    #   — the fast test path must instantiate the SAME production classes, so no "test mode"
    #   can shelter a leak. Only params (dates, universe size, epochs) may differ.
```

## tests/fixtures/synthetic_calendar.py

```python
SYNTH_CALENDAR: SyntheticCalendar
#   .true_last_dates: dict[str, pd.Timestamp]  — security_id → its LAST true membership date
#   .write_to_lake(lake_dir: Path) -> None     — writes SYN membership rows into the test lake
```

- This is the single mechanism behind `get_universe`'s `fixture_all` behavior: it writes synthetic membership rows into `/tmp/dlsa_test_lake`, which `get_universe` then replays through the normal production path. **No fixture branch ever exists inside `get_universe` itself.**
- `true_last_dates` is what Hardened Test 11 asserts against: every name must still be returned by `get_universe` on its last true membership date.

## dlsa/execution/journal.py (durable state backing reconcile())

```python
def record_order(order: Order) -> None
def record_fill(fill: Fill) -> None
def get_open_orders(asof: pd.Timestamp) -> list[Order]
def get_position_journal(asof: pd.Timestamp) -> pd.Series
```

- Storage is **SQLite in WAL mode** at `data_lake/journal.sqlite` (frozen param E2).
- Append-only. Every `submit()` call must `record_order` **before** sending to the broker, using the idempotent `client_order_id` from frozen param E1.
- **Book column (added 2026-07-16, dormant until V6's trigger):** the `orders_fills` schema carries `book: {'live' | 'shadow'}`, default `'live'`. Shadow rows are inert everywhere else.
- Broker account state is the position **truth**; `get_position_journal` is the audit trail that `reconcile()` diffs against.
- Before submitting any order, `submit()` must check `get_open_orders(asof)` so a re-run doesn't resend orders already in flight.

## dlsa/data/loader.py — lake → modeling frames (the ONLY path)

```python
def load_prices(
    start: pd.Timestamp,
    end: pd.Timestamp,
    field: Literal["close_adj", "close_raw", "volume"] = "close_adj",
) -> pd.DataFrame

def load_provenance(
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> pd.DataFrame
```

- The **single** function that turns the ticker-keyed lake into security_id-keyed modeling frames. It (a) applies `identifier_map` as-of each row's date; (b) selects the canonical source per (security_id, date) by frozen param D5's priority (yfinance > stooq > alpaca) among rows that **passed validation**; (c) leaves quarantined/excluded cells NaN — never forward-filled.
- **No other module reads `prices/` Parquet directly**; factors, signals, and the engine consume only this output.
- `close_adj` is derived **at read time** as `close × adj_factor`; the loader never persists an adjusted series. The engine consumes `close_raw` + `corporate_actions` through `compute_returns` **only**; `close_adj` is diagnostic/human surface, never a modeling input.
- Deterministic: same lake snapshot + same arguments ⇒ bit-identical frames (feeds G0.6).
- **Vendor-intake quarantine (D7):** `load_prices`/`load_provenance` serve only the v1 source set; nothing under `data_lake/vendor_intake/` is reachable through this loader until the D7 ablation gate passes for a given source (hardened Test 20 enforces the read fence).

## dlsa/signals/ — signal net, seed ensemble (V3), EB shrinkage (V5)

```python
class SignalModel(Protocol):
    def predict(self, residuals: pd.DataFrame, asof: pd.Timestamp) -> pd.Series
    #   Returns the cross-sectional signal at asof. For the deployed model this is the
    #   EQUAL-WEIGHT MEAN over the V3 seed set (N=5, seeds [0,1,2,3,4]) — aggregation lives
    #   INSIDE predict(); downstream code sees one Series and never iterates members.

# dlsa/signals/shrinkage.py
def shrink(signals: pd.Series, asof: pd.Timestamp, stats: ShrinkageStats) -> pd.Series
#   Cross-sectional EB/James–Stein linear shrinkage toward 0 per frozen param V5.
#   Invariant (tested): abs(shrink(s, ...)) <= abs(s) element-wise — shrinkage only shrinks.

def fit_shrinkage_stats(member_signals: pd.DataFrame, fit_end: pd.Timestamp) -> ShrinkageStats
#   member_signals is MultiIndex (date, seed) × security_id over the trailing window ending fit_end.
#   Implements V5's seed-dispersion estimator.
#   One seed (test_min) ⇒ unidentifiable ⇒ λ = config signal.shrinkage.fixed_lambda (page 03).

class ShrinkageStats:
    lam: float          # λ in [0, 1]
    fit_end: pd.Timestamp   # invariant (tested): fit_end < first date λ is applied to
```

- **The policy net consumes shrunk signals only.** The pipeline order is fixed: signal net → `shrink()` → policy → `build_portfolio` → overlays.

## dlsa/selection/cpcv.py — CPCV selection harness (V4)

```python
def cpcv_folds(index: pd.DatetimeIndex) -> Iterator[tuple[pd.DatetimeIndex, pd.DatetimeIndex]]
#   Yields (train_idx, test_idx) for 8 groups × 2 test groups (28 splits, 7 paths) with
#   purge = 60 trading days and embargo = 10 trading days around every test block (V4).

def select(configs: list[Path]) -> SelectionReport
#   Runs each candidate config through the folds, ranks by MEDIAN net Sharpe (M1) across
#   the 7 paths, and reports PBO (probability of backtest overfitting) for the chosen one.
#   Writes to runs/selection/ — NEVER to runs/backtests/.
```

- **Firewall:** `SelectionReport` deliberately has **no** `sharpe`-named field a tearsheet could ingest. Gate numbers come only from `run_backtest`.
- **Training-window contiguity (added 2026-07-18, N15):** training windows never span purge boundaries; each contiguous train segment is its own M3 window; wₜ₋₁ resets at each segment start.

## dlsa/allocation/allocator.py — multi-sleeve combiner (C9) — DORMANT

```python
def combine(sleeves: dict[str, pd.Series], risk_weights: dict[str, float]) -> pd.Series
#   Fixed-weight combination at the WEIGHT level: v1 risk_weights are 50/50 and FROZEN.
#   Each sleeve is a build_portfolio-conformant weight vector produced by the SAME engine.
#   Constraints apply POST-combination on the NETTED book.
```

- **Dormant until C9's five trigger conditions hold (page 04)** — incl. measured OOS sleeve correlation ≤ 0.3 (G2.8) and capital ≥ 2×C8. Until then no module may import it in Phases 0–2.

## Change log

| date | change | reason |
|------|--------|--------|
| (init) | v1 frozen from test suite + architecture doc | — |
| 2026-07-12 | `BacktestResult.sharpe` referenced to frozen param M1; frames/weights/positions re-keyed from ticker to security_id; calendar option `BDAY`; engine intersection rule added; `get_universe` fixture mechanism specified; `latest_universe_date()` / `calendar_available()` added | Independent verification pass |
| 2026-07-13 | Added `dlsa/execution/journal.py` contract | Ops & Systems Review: double-submit prevention |
| 2026-07-14 | Hardened-test reconciliation. Added: `PCAFactorModel.preprocess()`, `loading_fit_end_dates`, `run_backtest(signal_override=...)`, `dlsa/config.py` `load_config().resolved()` API, `tests/fixtures/synthetic_calendar.py` module | Pre-Code Audit 1.1 |
| 2026-07-14 | `build_portfolio` gains `current`; news-gate rule changed to freeze-don't-flatten (O7); C5, C6/C7, E6, E2 documented | Pre-Code Audit 1.2/1.3/1.4/2.2 |
| 2026-07-14 | Added `dlsa/data/loader.py` contract | Pre-Code Audit 3.6 |
| 2026-07-15 | Added `dlsa/signals/` contract (V3/V5), `dlsa/selection/cpcv.py` contract (V4), `BacktestResult.deflated_sharpe` (V1), trial-registry write rule | Bear-Case adoptions |
| 2026-07-16 | V6 shadow mechanism documented; journal schema gains dormant `book` column; crowding overlay gains O9 publication-vintage rule (Test 16); loader gains D7 quarantine (Test 20); dormant `dlsa/allocation/allocator.py` contract added (C9) | Alpha-Roadmap adoption |
| 2026-07-17 | `build_portfolio` gains `prev_overlay_multiplier`; C5 exempt-turnover decomposition (B1); `deflated_sharpe` re-contracted as DSR probability (B2); `RegimeOverlay` audit surface + filtered-probability requirement, Test 21 (B3); `fit_shrinkage_stats` re-contracted on member signals (B6); `Order.flow` tag added, E8 (B8); O7 universe-exit precedence (B10) | Sixth-Pass Audit B1/B2/B3/B6/B8/B10/B12 |
| 2026-07-18 | `validate_frame` gains stale-bar check (N7) and adjustment-consistency check (N1); `loader.py` pins single return-computation path (N1); `diff_orders` gains integer-share rounding + capacity exclusions (N4); CPCV gains training-window contiguity rule (N15) | Sixth-Pass Audit Part 2 |
