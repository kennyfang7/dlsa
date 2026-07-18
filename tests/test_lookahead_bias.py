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


# ----------------------------------------------------------------------------
# 1. THE WHITE-NOISE CANARY — the one test to keep above all others
# ----------------------------------------------------------------------------

class TestNoiseCanary:
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