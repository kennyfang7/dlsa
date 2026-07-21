"""
Look-ahead / leakage / survivorship test suite for the DLSA trading system.

Run with:  make test-leakage   (or: pytest tests/test_lookahead_bias.py -v)

WHY THIS FILE EXISTS
--------------------
In quant projects, the most dangerous bugs don't crash — they quietly let the
model peek at the future, producing a beautiful backtest and a losing live
strategy. These tests are designed so that the most common leakage bugs make
a test go red instead.

The single most powerful idea here is the WHITE-NOISE CANARY (TestNoiseCanary):
we feed the ENTIRE pipeline pure random data, where the future is unpredictable
by construction. If the backtest still "makes money" on coin flips, the
pipeline is leaking the future somewhere. It doesn't matter where — the canary
dies and you go digging.

Adjust the imports in the "PROJECT WIRING" block to your actual module paths.
Tests are written against the interfaces described in CLAUDE.md.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

# ----------------------------------------------------------------------------
# PROJECT WIRING — adjust these imports to your package layout
# ----------------------------------------------------------------------------
from dlsa.data.universe import (                        # PIT universe calendar
    get_universe, latest_universe_date, calendar_available,
)
from dlsa.data.returns import compute_returns          # adjusted-close returns
from dlsa.factors.pca import PCAFactorModel            # factor model → residuals
from dlsa.backtest.engine import run_backtest          # walk-forward backtest
from dlsa.backtest.portfolio import build_portfolio    # shared with live path

RNG = np.random.default_rng(42)

# ----------------------------------------------------------------------------
# Fixtures: small synthetic worlds we fully control
# ----------------------------------------------------------------------------

@pytest.fixture
def noise_prices() -> pd.DataFrame:
    """
    A fake market where prices are a pure random walk (geometric, no drift).

    Plain terms: this market is a coin-flip machine. NOTHING about tomorrow
    can be predicted from today. Any strategy that profits here is cheating.
    """
    n_days, n_names = 1500, 60
    dates = pd.bdate_range("2018-01-02", periods=n_days, tz="UTC")  # tz-aware, per interface contract
    tickers = [f"SYN{i:03d}" for i in range(n_names)]
    rets = RNG.normal(0.0, 0.02, size=(n_days, n_names))
    prices = 100.0 * np.exp(np.cumsum(rets, axis=0))
    return pd.DataFrame(prices, index=dates, columns=tickers)


@pytest.fixture
def split_prices() -> pd.DataFrame:
    """One ticker with a known 4:1 split halfway through, raw prices."""
    dates = pd.bdate_range("2024-01-02", periods=40, tz="UTC")
    raw = pd.Series(100.0, index=dates)
    raw.iloc[20:] = 25.0  # price quarters on split day; holder wealth unchanged
    return raw.to_frame("SPLITCO")


@pytest.fixture
def test_lake_dir(tmp_path):
    """Isolated per-test data-lake root (function-scoped via tmp_path).
    Tests 16/20/21 write then corrupt data inside it; each must start clean."""
    return tmp_path


# ----------------------------------------------------------------------------
# 1. THE WHITE-NOISE CANARY — the one test to keep above all others
# ----------------------------------------------------------------------------

class TestNoiseCanary:
    pytestmark = pytest.mark.xfail(strict=False)

    def test_pipeline_cannot_beat_coin_flips(self, noise_prices):
        """
        Run the FULL pipeline (factors → residuals → signal → policy →
        backtest) on unpredictable random-walk data. Out-of-sample Sharpe
        must be statistically indistinguishable from zero.

        Threshold: |Sharpe| < 1.0 on ~4 years of daily data is generous;
        genuine leakage typically produces Sharpe > 2 here. If this fails,
        DO NOT loosen the threshold — bisect the pipeline until you find
        which stage can see the future.
        """
        result = run_backtest(prices=noise_prices, config="configs/test_min.yaml")
        assert abs(result.sharpe) < 1.0, (
            f"Sharpe {result.sharpe:.2f} on pure noise — the pipeline is "
            "leaking future information somewhere. Bisect stages to locate it."
        )

    def test_shuffled_future_destroys_performance(self, noise_prices):
        """
        Complementary check for pipelines with real (non-noise) fixtures:
        shuffling the mapping between signals and NEXT-day returns must
        destroy any performance. If performance survives shuffling, the
        'performance' never came from prediction in the first place.
        """
        result = run_backtest(
            prices=noise_prices,
            config="configs/test_min.yaml",
            shuffle_forward_returns=True,   # engine test hook
        )
        assert abs(result.sharpe) < 1.0


# ----------------------------------------------------------------------------
# 2. Point-in-time universe / survivorship
# ----------------------------------------------------------------------------

class TestPITUniverse:
    pytestmark = pytest.mark.xfail(strict=False)

    def test_backtest_only_trades_members_as_of_each_date(self, noise_prices):
        """Every position on date t must be in the universe ON date t."""
        result = run_backtest(prices=noise_prices, config="configs/test_min.yaml")
        for date, holdings in result.positions.items():
            members = set(get_universe(date))
            extras = set(holdings.index[holdings != 0]) - members
            assert not extras, f"{date.date()}: traded non-members {extras}"

    @pytest.mark.skipif(
        not calendar_available(),
        reason="needs a populated PIT calendar (Phase 0, gate G0.1) — xfail/skip until the lake exists",
    )
    def test_delisted_names_exist_historically(self):
        """
        Survivorship check: the historical universe must contain names that
        are NOT in the latest universe. If past == present, the PIT calendar
        is secretly a current snapshot and the backtest excludes the losers.

        Deterministic by design: uses latest_universe_date(), never 'now' —
        'now' can be a weekend/holiday or postdate the last calendar ingest,
        both of which are KeyError per the get_universe contract.
        """
        past = set(get_universe(pd.Timestamp("2012-06-01", tz="UTC")))
        today = set(get_universe(latest_universe_date()))
        assert past - today, (
            "No delisted/removed names found in the 2012 universe — the "
            "constituent calendar looks like a survivorship-biased snapshot."
        )

    def test_universe_lookup_is_deterministic(self):
        d = pd.Timestamp("2019-03-15", tz="UTC")
        assert list(get_universe(d)) == list(get_universe(d))


# ----------------------------------------------------------------------------
# 3. Feature availability (publication-date discipline)
# ----------------------------------------------------------------------------

class TestFeatureAvailability:
    pytestmark = pytest.mark.xfail(strict=False)

    def test_no_feature_timestamp_after_asof_date(self, noise_prices):
        """
        For every feature row used at decision date t, its availability
        timestamp must be <= t. This is THE test for 'joined on fiscal
        period instead of filing date' bugs.
        """
        model = PCAFactorModel(n_factors=5)
        asof = noise_prices.index[900]
        features = model.build_features(noise_prices, asof=asof)
        assert (features["available_at"] <= asof).all(), (
            "Some features are dated AFTER the as-of date — check the join "
            "keys (must join on availability/filing date, not period end)."
        )

    def test_asof_join_direction_is_backward(self, noise_prices):
        """
        Recompute a feature at date t using (a) full history and (b) history
        truncated at t. Results must be identical. If truncating the future
        changes the value, the value depended on the future.
        """
        model = PCAFactorModel(n_factors=5)
        t = noise_prices.index[800]
        full = model.build_features(noise_prices, asof=t)
        trunc = model.build_features(noise_prices.loc[:t], asof=t)
        pd.testing.assert_frame_equal(
            full.sort_index(), trunc.sort_index(), check_exact=False, atol=1e-10
        )


# ----------------------------------------------------------------------------
# 4. Causal normalization & training hygiene
# ----------------------------------------------------------------------------

class TestCausalNormalization:
    pytestmark = pytest.mark.xfail(strict=False)

    def test_scaler_statistics_come_from_train_window_only(self, noise_prices):
        """
        Corrupt the TEST window with an absurd outlier; the fitted scaler
        must not change. If it does, normalization saw the test period.
        """
        model = PCAFactorModel(n_factors=5)
        split = noise_prices.index[1000]

        clean = model.fit_scaler(noise_prices, train_end=split)
        corrupted = noise_prices.copy()
        corrupted.iloc[-1] *= 1_000.0  # nuke a post-split row
        dirty = model.fit_scaler(corrupted, train_end=split)

        np.testing.assert_allclose(clean.mean_, dirty.mean_, rtol=1e-12)
        np.testing.assert_allclose(clean.scale_, dirty.scale_, rtol=1e-12)

    def test_signal_trades_next_bar_not_same_bar(self, noise_prices):
        """
        The engine must align signal(t) with return(t+1). We verify via the
        engine's reported alignment metadata rather than re-deriving it.
        """
        result = run_backtest(prices=noise_prices, config="configs/test_min.yaml")
        assert result.meta["signal_to_trade_lag_days"] >= 1, (
            "Signals are trading on the same bar they were computed from — "
            "classic look-ahead. Check the .shift(1) in the engine."
        )


# ----------------------------------------------------------------------------
# 5. Return computation correctness (splits & adjustments)
# ----------------------------------------------------------------------------

class TestReturnCorrectness:
    pytestmark = pytest.mark.xfail(strict=False)

    def test_split_produces_no_fake_return(self, split_prices):
        """
        A 4:1 split changes the price from 100 to 25 but the holder loses
        nothing. Adjusted-return computation must show ~0% that day, not -75%.
        """
        actions = pd.DataFrame(
            {"ticker": ["SPLITCO"], "date": [split_prices.index[20]],
             "type": ["split"], "ratio": [4.0]}
        )
        rets = compute_returns(split_prices, corporate_actions=actions)
        split_day_ret = rets.iloc[20, 0]
        assert abs(split_day_ret) < 1e-6, (
            f"Split day shows return {split_day_ret:.2%}; adjustment logic "
            "is broken (a -75% phantom crash means splits aren't applied)."
        )

    def test_missing_prices_are_not_forward_filled(self, noise_prices):
        """A NaN price must yield a NaN return + exclusion, never a 0% return."""
        gappy = noise_prices.copy()
        gap_loc = (500, gappy.columns[0])
        gappy.loc[gappy.index[gap_loc[0]], gap_loc[1]] = np.nan
        rets = compute_returns(gappy)
        assert np.isnan(rets.iloc[gap_loc[0], 0]) and np.isnan(rets.iloc[gap_loc[0] + 1, 0]), (
            "Returns across a missing price must be NaN (excluded), not "
            "imputed — forward-filling manufactures fake zero-return days."
        )


# ----------------------------------------------------------------------------
# 6. Overlay safety (defense in depth — overlays may only shrink)
# ----------------------------------------------------------------------------

class TestOverlayInvariants:
    @pytest.mark.parametrize("mult", [1.5, 2.0, -0.5, 0.0])
    def test_portfolio_rejects_invalid_overlay_multipliers(self, mult, noise_prices):
        """Multipliers outside (0, 1] must raise, not silently lever up."""
        signals = pd.Series(RNG.normal(size=noise_prices.shape[1]),
                            index=noise_prices.columns)
        with pytest.raises(ValueError):
            build_portfolio(signals, overlay_multiplier=mult)


# ----------------------------------------------------------------------------
# NEW FIXTURE — regime-switching noise market
# Hardened Leakage Tests additions (2026-07-17)
# ----------------------------------------------------------------------------

@pytest.fixture
def regime_noise_prices() -> pd.DataFrame:
    """Random-walk prices with REGIME-SWITCHING volatility and a small drift
    that flips sign mid-sample. Still unpredictable day-to-day, but now
    volatility and drift vary through time — so leaks that exploit knowledge
    of *future risk levels* finally have something to steal, and the canary
    can catch them stealing it.

    Plain terms: the old fake market had constant weather, so a cheater who
    peeked at the future forecast gained nothing. This market has storms —
    peeking now pays, so peeking now gets caught.
    """
    n_days, n_names = 1500, 60
    # tz-aware UTC per the page-01 global convention (the constant-vol fixtures were
    # corrected in the 2026-07-12 verification pass; this one was missed until the
    # Pre-Code Audit). A tz-naive index violates the prices-frame contract outright.
    dates = pd.bdate_range("2018-01-02", periods=n_days, tz="UTC")
    vol = np.where((np.arange(n_days) // 250) % 2 == 0, 0.01, 0.04)  # calm/stormy years
    drift = np.where(np.arange(n_days) < n_days // 2, 2e-4, -2e-4)
    rets = RNG.normal(drift[:, None], vol[:, None], size=(n_days, n_names))
    prices = 100.0 * np.exp(np.cumsum(rets, axis=0))
    return pd.DataFrame(prices, index=dates,
                        columns=[f"SYN{i:03d}" for i in range(n_names)])


# ----------------------------------------------------------------------------
# 7. Residual path truncation-equivalence [kills Exhibit A]
# ----------------------------------------------------------------------------

class TestResidualCausality:
    pytestmark = pytest.mark.xfail(strict=False)

    def test_residuals_invariant_to_future_truncation(self, regime_noise_prices):
        """The residual AT date t must be identical whether computed from
        full history or history cut off at t. If deleting the future changes
        today's residual, today's residual was using the future."""
        model = PCAFactorModel(n_factors=5)
        t = regime_noise_prices.index[800]
        # Contract API: residuals(prices, asof) — NOT compute_residuals(prices).
        full = model.residuals(regime_noise_prices, asof=t)
        trunc = model.residuals(regime_noise_prices.loc[:t], asof=t)
        pd.testing.assert_series_equal(
            full.loc[t], trunc.loc[t], check_exact=False, atol=1e-10,
        )

    def test_loadings_dated_before_residual_date(self, regime_noise_prices):
        """The model must expose the fit-window end for each residual date,
        and it must strictly precede that date."""
        model = PCAFactorModel(n_factors=5)
        t = regime_noise_prices.index[800]
        model.residuals(regime_noise_prices, asof=t)
        fit_ends = model.loading_fit_end_dates  # contract property (added 2026-07-14)
        assert (fit_ends.index > fit_ends.values).all()


# ----------------------------------------------------------------------------
# 8. Hardened canary [kills Exhibit B + generous threshold]
# ----------------------------------------------------------------------------

class TestNoiseCanaryHardened:
    pytestmark = pytest.mark.xfail(strict=False)

    def test_pipeline_cannot_beat_regime_noise(self, regime_noise_prices):
        """Full pipeline on regime-switching noise. Vol-timing/quantile leaks
        now produce visible profit here, unlike on the constant-vol fixture."""
        result = run_backtest(prices=regime_noise_prices,
                              config="configs/test_min.yaml")
        assert abs(result.sharpe) < 0.8

    @pytest.mark.parametrize("seed", [0, 1, 2, 3, 4])
    def test_canary_mean_across_seeds(self, seed):
        """One lucky seed shouldn't acquit; one unlucky seed shouldn't convict."""
        rng = np.random.default_rng(seed)
        n_days, n_names = 1500, 60
        dates = pd.bdate_range("2018-01-02", periods=n_days, tz="UTC")  # tz-aware UTC per page-01 global convention (2026-07-14: this fixture was the one missed by the 2026-07-12 tz-naive fix)
        rets = rng.normal(0.0, 0.02, size=(n_days, n_names))
        prices = pd.DataFrame(100.0 * np.exp(np.cumsum(rets, axis=0)),
                              index=dates,
                              columns=[f"SYN{i:03d}" for i in range(n_names)])
        result = run_backtest(prices=prices, config="configs/test_min.yaml")
        assert abs(result.sharpe) < 1.0


# ----------------------------------------------------------------------------
# 9. Behavioral alignment [kills Exhibit C]
# ----------------------------------------------------------------------------

class TestBehavioralAlignment:
    pytestmark = pytest.mark.xfail(strict=False)

    def test_known_pnl_separates_lag0_from_lag1(self):
        """Deterministic two-asset market where same-bar and next-bar trading
        produce DIFFERENT, exactly computable PnL paths. No metadata trusted.

        Construction: returns alternate +1%/-1% deterministically. Same-bar
        (leaky) alignment earns +1% every day; lag-1 earns -1% every day.
        The two paths cannot be confused."""
        dates = pd.bdate_range("2024-01-02", periods=200, tz="UTC")
        r = np.tile([0.01, -0.01], 100)[:200]
        prices = pd.DataFrame(
            {"A": 100 * np.cumprod(1 + r), "B": 100 * np.cumprod(1 - r)},
            index=dates,
        )
        result = run_backtest(prices=prices, config="configs/test_min.yaml",
                              signal_override="own_return")
        daily = result.returns.iloc[2:]   # contract field is `returns`, not `portfolio_returns`
        assert (daily < 0).mean() > 0.95

    def test_test_config_wires_production_classes(self):
        """Assert test_min.yaml resolves to the same classes as backtest.yaml
        so a 'fast test path' can't shelter a leak."""
        from dlsa.config import load_config
        test_cfg = load_config("configs/test_min.yaml")
        prod_cfg = load_config("configs/backtest.yaml")
        for key in ("engine_class", "factor_model_class", "policy_class"):
            assert test_cfg.resolved(key) is prod_cfg.resolved(key)


# ----------------------------------------------------------------------------
# 10. End-to-end preprocessing causality [kills Exhibit D]
# ----------------------------------------------------------------------------

class TestPreprocessingCausality:
    pytestmark = pytest.mark.xfail(strict=False)

    def test_full_preprocessing_output_invariant_to_future_corruption(
            self, regime_noise_prices):
        """Probe the OUTPUT of the whole preprocessing chain, not just scaler
        attributes. Corrupt the future grotesquely; every transformed value
        dated <= train_end must be bit-for-bit unchanged."""
        model = PCAFactorModel(n_factors=5)
        split = regime_noise_prices.index[1000]
        clean = model.preprocess(regime_noise_prices, train_end=split)
        corrupted = regime_noise_prices.copy()
        corrupted.iloc[-30:] *= 1_000.0
        dirty = model.preprocess(corrupted, train_end=split)
        pd.testing.assert_frame_equal(clean.loc[:split], dirty.loc[:split])


# ----------------------------------------------------------------------------
# 11. Universe near-death filtering [kills Exhibit E]
# ----------------------------------------------------------------------------

class TestUniverseNoFutureFiltering:
    pytestmark = pytest.mark.xfail(strict=False)

    def test_members_survive_until_their_true_removal_date(self):
        """Every name must remain a member up to and INCLUDING its last true
        membership date. Any 'drop names about to delist' filter is future
        information."""
        from tests.fixtures.synthetic_calendar import SYNTH_CALENDAR
        for name, last_member_date in SYNTH_CALENDAR.true_last_dates.items():
            assert name in get_universe(last_member_date)


# ----------------------------------------------------------------------------
# 12. Unrecorded splits [hardened corporate actions]
# ----------------------------------------------------------------------------

class TestReturnCorrectnessHardened:
    pytestmark = pytest.mark.xfail(strict=False)

    def test_unrecorded_split_is_detected_not_swallowed(self):
        """The existing split test covers a split WITH an action row. The
        common live failure is a missed split: raw price gaps -75% with no
        explanation. compute_returns must NaN it, not hand the signal net
        a fake crash to fade."""
        from dlsa.data.returns import compute_returns
        dates = pd.bdate_range("2024-01-02", periods=40, tz="UTC")
        raw = pd.Series(100.0, index=dates)
        raw.iloc[20:] = 25.0  # 4:1 split, NO action row
        rets = compute_returns(raw.to_frame("GHOSTSPLIT"),
                               corporate_actions=pd.DataFrame())
        assert np.isnan(rets.iloc[20, 0])


# ----------------------------------------------------------------------------
# 13. Shrinkage is causal and shrink-only [guards V5]
# 2026-07-15 addition — Bear-Case adoption; 2026-07-17 Sixth-Pass Audit B6
# ----------------------------------------------------------------------------

# Fixture (2026-07-17, Sixth-Pass Audit B6): V5's estimator fits on MEMBER SIGNALS,
# never prices — a price frame cannot identify a signal/noise decomposition. This
# fixture PLANTS one, so the estimator's recovery can be asserted, not assumed.
SIGMA_S, SIGMA_N, N_SEEDS = 1.0, 0.5, 5
PLANTED_LAMBDA = SIGMA_S**2 / (SIGMA_S**2 + SIGMA_N**2 / N_SEEDS)   # ≈ 0.9524

@pytest.fixture
def synthetic_member_signals() -> pd.DataFrame:
    """MultiIndex (date, seed) × security_id member signals with a KNOWN
    signal+noise construction: every seed sees the same common ~ N(0, σ_s²)
    plus its own noise ~ N(0, σ_n²). True λ is computable in closed form."""
    n_days, n_names = 400, 60
    dates = pd.bdate_range("2021-01-04", periods=n_days, tz="UTC")
    names = [f"SYN{i:03d}" for i in range(n_names)]
    common = RNG.normal(0, SIGMA_S, size=(n_days, n_names))
    frames = {s: pd.DataFrame(common + RNG.normal(0, SIGMA_N, size=(n_days, n_names)),
                              index=dates, columns=names)
              for s in range(N_SEEDS)}
    return (pd.concat(frames, names=["seed", "date"])
              .swaplevel(0, 1).sort_index())    # index: (date, seed) × security_id


class TestShrinkageCausality:
    pytestmark = pytest.mark.xfail(strict=False)

    def test_shrink_never_amplifies(self, synthetic_member_signals):
        """|shrink(s)| <= |s| element-wise — an 'EB' layer that can amplify
        is a new leak/blowup surface, not a shrinkage."""
        from dlsa.signals.shrinkage import shrink, fit_shrinkage_stats
        dates = synthetic_member_signals.index.get_level_values("date").unique()
        t = dates[300]
        s = pd.Series(RNG.normal(0, 1, 60),
                      index=[f"SYN{i:03d}" for i in range(60)])
        stats = fit_shrinkage_stats(synthetic_member_signals, fit_end=t)
        assert (shrink(s, asof=t, stats=stats).abs() <= s.abs() + 1e-12).all()

    def test_lambda_invariant_to_future_corruption(self, synthetic_member_signals):
        """λ fit through t must not move when post-t MEMBER-SIGNAL rows are
        corrupted — the preprocess-style probe applied to the V5 estimator
        (B6: the probe now targets member-signal history, not prices)."""
        from dlsa.signals.shrinkage import fit_shrinkage_stats
        dates = synthetic_member_signals.index.get_level_values("date").unique()
        t = dates[300]
        clean = fit_shrinkage_stats(synthetic_member_signals, fit_end=t)
        corrupted = synthetic_member_signals.copy()
        future = corrupted.index.get_level_values("date") > t
        corrupted.loc[future] *= 1_000.0
        dirty = fit_shrinkage_stats(corrupted, fit_end=t)
        assert clean.lam == pytest.approx(dirty.lam, rel=1e-12)
        assert clean.fit_end <= t

    def test_estimator_recovers_planted_lambda(self, synthetic_member_signals):
        """Recovery assertion (B6, the ref_ipca self-check pattern): an estimator
        that passes causality but estimates garbage is still an undefined
        component. λ̂ must land near σ_s²/(σ_s² + σ_n²/N) on the planted data."""
        from dlsa.signals.shrinkage import fit_shrinkage_stats
        dates = synthetic_member_signals.index.get_level_values("date").unique()
        stats = fit_shrinkage_stats(synthetic_member_signals, fit_end=dates[-1])
        assert stats.lam == pytest.approx(PLANTED_LAMBDA, abs=0.10)


# ----------------------------------------------------------------------------
# 14. CPCV purge/embargo correctness [guards V4]
# 2026-07-15 addition — Bear-Case adoption; 2026-07-17 Sixth-Pass Audit B4
# ----------------------------------------------------------------------------

class TestCPCVPurgeEmbargo:
    pytestmark = pytest.mark.xfail(strict=False)

    def test_no_fold_violates_purge_or_embargo(self):
        """A CPCV harness with buggy purging is a leakage machine wearing an
        anti-overfitting costume. Every (train, test) pair must respect the
        frozen V4 purge/embargo in TRADING-DAY units (2026-07-17, B4: the old
        timedelta64[D] gap was CALENDAR days — admitting folds with 42–59
        trading-day purges while claiming 60); train ∩ test must be empty."""
        from dlsa.selection.cpcv import cpcv_folds
        idx = pd.bdate_range("2016-01-04", periods=2000, tz="UTC")
        pos = {ts: i for i, ts in enumerate(idx)}          # TRADING-DAY positions
        for train_idx, test_idx in cpcv_folds(idx):
            assert len(train_idx.intersection(test_idx)) == 0
            t_pos = np.array([pos[t] for t in train_idx])
            s_pos = np.array([pos[t] for t in test_idx])
            diff = t_pos[:, None] - s_pos[None, :]
            pre  = -diff[diff < 0]     # train strictly BEFORE test: gap in trading days
            post =  diff[diff > 0]     # train strictly AFTER test
            if pre.size:  assert pre.min()  > 60   # purge  (V4: 60 trading days)
            if post.size: assert post.min() > 10   # embargo (V4: 10 trading days)

    def test_selection_module_cannot_touch_simulator_reporting(self):
        """Firewall, enforced structurally: dlsa.selection must not import the
        walk-forward engine's result/report types, and SelectionReport must
        not expose a field named 'sharpe'."""
        import dlsa.selection.cpcv as sel
        import sys
        assert "dlsa.backtest.run" not in sys.modules or \
               not hasattr(sel, "BacktestResult")
        from dlsa.selection.cpcv import SelectionReport
        assert "sharpe" not in SelectionReport.__dataclass_fields__


# ----------------------------------------------------------------------------
# 15. Ensemble is the deployed unit [guards V3]
# 2026-07-15 addition — Bear-Case adoption
# ----------------------------------------------------------------------------

class TestEnsembleDeployment:
    pytestmark = pytest.mark.xfail(strict=False)

    def test_predict_aggregates_all_seeds(self):
        """predict() must consume every member in the manifest — a silently
        dropped seed changes the deployed model without a version bump."""
        from dlsa.signals.model import SignalEnsemble
        ens = SignalEnsemble.from_registry("conv_transformer/v0")
        assert len(ens.members) == len(ens.manifest["seeds"])  # == 5 in prod, 1 in test_min


# ----------------------------------------------------------------------------
# Pre-registered (V7 — written when `data_lake/synthetic/` first exists)
# ----------------------------------------------------------------------------

class TestSyntheticQuarantine:
    def test_training_paths_cannot_read_synthetic(self):
        """data_lake/synthetic/ (Tail-GAN scenarios) may feed overlay stress
        reports ONLY. Loader/factor/signal/policy paths must refuse it —
        otherwise the overfitting fix becomes a leakage source."""


# ----------------------------------------------------------------------------
# 16. Crowding publication-vintage discipline [guards O9]
# 2026-07-16 addition — Alpha-Roadmap adoption
# ----------------------------------------------------------------------------

class TestCrowdingVintageDiscipline:
    pytestmark = pytest.mark.xfail(strict=False)

    def test_multiplier_invariant_to_post_publication_corruption(self, test_lake_dir):
        """The crowding overlay at date t may only consume FINRA rows with
        publication_date <= t (page-02 short_interest schema, frozen param O9).
        Corrupt every vintage published AFTER t grotesquely; multiplier(t)
        must be bit-unchanged — the D3/FRED probe applied to a twice-monthly,
        ~T+8/9-lagged feed. Conditioning day-t sizing on day-t short interest
        is leakage wearing a risk-management costume."""
        from dlsa.overlays.crowding import CrowdingOverlay
        write_synthetic_short_interest(test_lake_dir)   # fixture helper, beside SYNTH_CALENDAR
        t = pd.Timestamp("2022-06-15", tz="UTC")
        clean = CrowdingOverlay(lake_dir=test_lake_dir).multiplier(asof=t)
        corrupt_short_interest_published_after(test_lake_dir, t, factor=1_000)
        dirty = CrowdingOverlay(lake_dir=test_lake_dir).multiplier(asof=t)
        assert clean == pytest.approx(dirty, rel=1e-12)

    def test_days_to_cover_is_derived_not_stored(self, test_lake_dir):
        """days_to_cover = shares ÷ trailing-21d median volume, computed at
        READ time (page 02). A stored column silently desyncs from any later
        price backfill — so the schema must not contain one."""
        import pyarrow.parquet as pq
        f = next((test_lake_dir / "short_interest").glob("*.parquet"))
        assert "days_to_cover" not in pq.read_schema(f).names


# ----------------------------------------------------------------------------
# 20. Vendor-intake quarantine [guards D7]
# 2026-07-16 addition — Alpha-Roadmap adoption
# ----------------------------------------------------------------------------

class TestVendorIntakeQuarantine:
    pytestmark = pytest.mark.xfail(strict=False)

    def test_loader_and_selection_cannot_read_vendor_intake(self, test_lake_dir):
        """data_lake/vendor_intake/ (D7 staging) is unreachable by the loader
        and by dlsa/selection/ until a source's CPCV ablation gate passes —
        the V7 synthetic-quarantine fence applied to future vendor data.
        Plant a poison frame; assert it cannot surface anywhere upstream
        of the ablation harness."""
        plant_poison_frame(test_lake_dir / "vendor_intake" / "newsrc")
        from dlsa.data.loader import load_prices
        frame = load_prices(TEST_START, TEST_END)
        assert not frame.columns.str.startswith("POISON").any()
        import dlsa.selection.cpcv as sel
        assert not hasattr(sel, "load_vendor_intake")  # no bypass API exists


# ----------------------------------------------------------------------------
# Pre-registered (V6/C9 — written when their components first exist, the V7 pattern)
# ----------------------------------------------------------------------------

class TestShadowSubmitFence:            # Test 17 — written when the V6 shadow pass exists
    def test_shadow_book_orders_never_reach_submit(self):
        """An order journaled with book='shadow' must be structurally unable
        to reach submit() — asserted AT the submit boundary, not in the
        caller, so no refactor of the daily job can un-fence it. A shadow
        order reaching a broker in any mode is an automatic G3.7 failure."""


class TestAllocatorInvariants:          # Test 18 — written when C9 activates
    def test_combined_book_satisfies_all_single_sleeve_constraints(self):
        """50/50 combination, then constraints on the NETTED book: dollar-
        neutrality, gross <= 1.0, C1 name cap on netted overlap, C3 sector.
        Per-sleeve attribution must decompose the combined PnL exactly."""


class TestPartialAdjustmentSanity:      # Test 19 — written with the V6 aim policy
    def test_aim_converges_and_respects_precedence(self):
        """Absent signal change the aim portfolio converges to target;
        C5 turnover-cap precedence is respected; expected turnover on the
        fixture book is strictly below the baseline policy's."""


# ----------------------------------------------------------------------------
# 21. Regime vintage & inference [closes Red-Team 1.3; guards O5/O8]
# 2026-07-17 addition — Sixth-Pass Audit B3
# ----------------------------------------------------------------------------

class TestRegimeVintageAndInference:      # Test 21 — ships with the suite; overlay lands Phase 2
    pytestmark = pytest.mark.xfail(strict=False)

    def test_multiplier_invariant_to_future_corruption(self, test_lake_dir):
        """Red-Team 1.3: hmmlearn's predict()/predict_proba() over a full sequence are
        SMOOTHED (forward-backward) — the state at t uses observations after t. O8
        requires FILTERED probs (score the sequence truncated at t; take the last row).
        The Test-16 probe: corrupt every market_state row dated after t grotesquely;
        multiplier(t) must be bit-unchanged. Catches smoothed inference AND any D3
        available_at violation in one assertion."""
        from dlsa.overlays.regime import RegimeOverlay
        write_synthetic_market_state(test_lake_dir)   # fixture helper, beside SYNTH_CALENDAR
        t = pd.Timestamp("2022-06-15", tz="UTC")
        clean = RegimeOverlay(lake_dir=test_lake_dir).multiplier(asof=t)
        corrupt_market_state_after(test_lake_dir, t, factor=1_000)
        dirty = RegimeOverlay(lake_dir=test_lake_dir).multiplier(asof=t)
        assert clean == pytest.approx(dirty, rel=1e-12)

    def test_states_relabeled_by_realized_vol_after_refit(self, test_lake_dir):
        """O5: hmmlearn state indices permute across refits; the multiplier map keys on
        the vol-sorted relabeling, never the raw index. Force refits on data engineered
        to permute indices; assert calm/normal/stressed map to ascending state-mean vol
        — via the page-01 audit surface state_vol_means()/state_labels() (B3)."""
        from dlsa.overlays.regime import RegimeOverlay
        ov = RegimeOverlay(lake_dir=test_lake_dir)
        for refit_date in engineered_permuting_refits(test_lake_dir):
            ov.refit(asof=refit_date)
            means, labels = ov.state_vol_means(), ov.state_labels()
            ordered = sorted(means, key=means.get)
            assert [labels[s] for s in ordered] == ["calm", "normal", "stressed"]