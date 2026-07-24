"""
Unit tests for `dlsa/data/validation.py::validate_frame` (P0.3).

Covers each of the 6 write-gate checks:
  1. Duplicate (ticker, date)
  2. Negative prices / volumes
  3. |return| > 60% without a matching split action (D2)
  4. Cross-source close disagreement > 50 bps (D1)
  5. Stale-bar check (N7)
  6. N1 adjustment-consistency

All tests use `tmp_path` so no writes touch the repo lake.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from dlsa.data.validation import validate_frame

# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------


def _make_prices_frame(
    tickers: list[str],
    dates: list[pd.Timestamp],
    close: float = 100.0,
    source: str = "yfinance",
) -> pd.DataFrame:
    rows = []
    ingested = pd.Timestamp("2026-01-01", tz="UTC")
    for t in tickers:
        for d in dates:
            rows.append(
                {
                    "ticker": t,
                    "date": d,
                    "open": close,
                    "high": close,
                    "low": close,
                    "close": close,
                    "volume": 1_000_000,
                    "adj_factor": 1.0,
                    "source": source,
                    "ingested_at": ingested,
                }
            )
    return pd.DataFrame(rows)


def _dates(n: int, start: str = "2024-01-02") -> list[pd.Timestamp]:
    return list(pd.bdate_range(start, periods=n, tz="UTC"))


def _write_prices(lake_dir, df: pd.DataFrame, name: str = "batch.parquet") -> None:
    root = lake_dir / "prices"
    root.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pandas(df, preserve_index=False), root / name)


# ----------------------------------------------------------------------------
# Empty / trivial paths
# ----------------------------------------------------------------------------


class TestEmptyFrame:
    def test_empty_frame_passes(self, tmp_path):
        df = pd.DataFrame(
            columns=[
                "ticker",
                "date",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "adj_factor",
                "source",
                "ingested_at",
            ]
        )
        report = validate_frame(df, source="yfinance", lake_dir=tmp_path)
        assert report.passed
        assert report.quarantined.empty

    def test_clean_single_source_frame_passes(self, tmp_path):
        df = _make_prices_frame(["AAA", "BBB"], _dates(20))
        report = validate_frame(df, source="yfinance", lake_dir=tmp_path)
        assert report.passed, report.issues
        assert report.quarantined.empty


# ----------------------------------------------------------------------------
# 1. Duplicates
# ----------------------------------------------------------------------------


class TestDuplicates:
    def test_duplicate_ticker_date_fails(self, tmp_path):
        df = _make_prices_frame(["AAA"], _dates(3))
        df = pd.concat([df, df.iloc[[0]]], ignore_index=True)
        report = validate_frame(df, source="yfinance", lake_dir=tmp_path)
        assert not report.passed
        assert any("duplicate" in i for i in report.issues)
        assert len(report.quarantined) >= 2


# ----------------------------------------------------------------------------
# 2. Negative values
# ----------------------------------------------------------------------------


class TestNegativeValues:
    def test_negative_close_fails(self, tmp_path):
        df = _make_prices_frame(["AAA"], _dates(3))
        df.loc[0, "close"] = -1.0
        report = validate_frame(df, source="yfinance", lake_dir=tmp_path)
        assert not report.passed
        assert any("negative" in i for i in report.issues)

    def test_negative_volume_fails(self, tmp_path):
        df = _make_prices_frame(["AAA"], _dates(3))
        df.loc[1, "volume"] = -10
        report = validate_frame(df, source="yfinance", lake_dir=tmp_path)
        assert not report.passed
        assert any("negative" in i for i in report.issues)


# ----------------------------------------------------------------------------
# 3. Absurd returns without corporate action (D2)
# ----------------------------------------------------------------------------


class TestAbsurdReturns:
    def test_75pct_drop_without_split_fails(self, tmp_path):
        df = _make_prices_frame(["AAA"], _dates(5), close=100.0)
        df.loc[df.index[3:], "close"] = 25.0  # -75% at row 3
        # adj_factor left at 1 so N1 doesn't also fire on the same row.
        df.loc[df.index[3:], "adj_factor"] = 1.0
        report = validate_frame(df, source="yfinance", lake_dir=tmp_path)
        assert not report.passed
        assert any("absurd" in i for i in report.issues)

    def test_75pct_drop_with_matching_split_passes_d2(self, tmp_path):
        df = _make_prices_frame(["AAA"], _dates(5), close=100.0)
        split_date = df.iloc[3]["date"]
        df.loc[df.index[3:], "close"] = 25.0
        # For the N1 check to also pass, adj close must be continuous.
        df.loc[df.index[:3], "adj_factor"] = 0.25
        df.loc[df.index[3:], "adj_factor"] = 1.0
        actions = pd.DataFrame(
            {
                "ticker": ["AAA"],
                "date": [split_date],
                "type": ["split"],
                "ratio": [4.0],
                "detail": [None],
            }
        )
        report = validate_frame(
            df,
            source="yfinance",
            lake_dir=tmp_path,
            corporate_actions=actions,
        )
        assert report.passed, report.issues


# ----------------------------------------------------------------------------
# 4. Cross-source disagreement (D1)
# ----------------------------------------------------------------------------


class TestCrossSource:
    def test_no_other_source_in_lake_is_noop(self, tmp_path):
        df = _make_prices_frame(["AAA"], _dates(3))
        report = validate_frame(df, source="yfinance", lake_dir=tmp_path)
        assert report.passed
        assert all("cross-source" not in i for i in report.issues)

    def test_disagreement_above_50_bps_fails(self, tmp_path):
        dates = _dates(3)
        # Existing stooq batch at close=100.00.
        stooq = _make_prices_frame(["AAA"], dates, close=100.0, source="stooq")
        _write_prices(tmp_path, stooq, name="stooq.parquet")

        # New yfinance batch at close=101.0 ⇒ 100 bps disagreement.
        yf = _make_prices_frame(["AAA"], dates, close=101.0, source="yfinance")
        report = validate_frame(yf, source="yfinance", lake_dir=tmp_path)
        assert not report.passed
        assert any("cross-source" in i for i in report.issues)

    def test_disagreement_within_50_bps_passes(self, tmp_path):
        dates = _dates(3)
        stooq = _make_prices_frame(["AAA"], dates, close=100.0, source="stooq")
        _write_prices(tmp_path, stooq, name="stooq.parquet")

        # 30 bps apart.
        yf = _make_prices_frame(["AAA"], dates, close=100.30, source="yfinance")
        report = validate_frame(yf, source="yfinance", lake_dir=tmp_path)
        assert report.passed, report.issues


# ----------------------------------------------------------------------------
# 5. Stale-bar (N7)
# ----------------------------------------------------------------------------


class TestStaleBar:
    def test_frozen_bar_while_universe_moves_fails(self, tmp_path):
        rng = np.random.default_rng(0)
        dates = _dates(10)
        n_names = 20
        tickers = [f"T{i:02d}" for i in range(n_names)]

        rows = []
        ingested = pd.Timestamp("2026-01-01", tz="UTC")
        for t in tickers:
            price = 100.0
            for d in dates:
                # Ticker T00 is our stale one.
                if t == "T00":
                    p = 100.0
                else:
                    price = price * (1 + rng.normal(0, 0.02))
                    p = price
                rows.append(
                    {
                        "ticker": t,
                        "date": d,
                        "open": p,
                        "high": p,
                        "low": p,
                        "close": p,
                        "volume": 1_000_000,
                        "adj_factor": 1.0,
                        "source": "yfinance",
                        "ingested_at": ingested,
                    }
                )
        df = pd.DataFrame(rows)
        report = validate_frame(df, source="yfinance", lake_dir=tmp_path)
        assert not report.passed
        assert any("stale" in i for i in report.issues)
        # Every T00 row after the first should be quarantined.
        stale_rows = report.quarantined[report.quarantined["ticker"] == "T00"]
        assert len(stale_rows) >= 5


# ----------------------------------------------------------------------------
# 6. N1 adjustment-consistency
# ----------------------------------------------------------------------------


class TestN1AdjustmentConsistency:
    def test_adj_factor_matches_recorded_split_passes(self, tmp_path):
        df = _make_prices_frame(["AAA"], _dates(5), close=100.0)
        # 4:1 split on day 3.
        split_date = df.iloc[3]["date"]
        df.loc[df.index[3:], "close"] = 25.0
        df.loc[df.index[:3], "adj_factor"] = 0.25
        df.loc[df.index[3:], "adj_factor"] = 1.0
        actions = pd.DataFrame(
            {
                "ticker": ["AAA"],
                "date": [split_date],
                "type": ["split"],
                "ratio": [4.0],
                "detail": [None],
            }
        )
        report = validate_frame(
            df,
            source="yfinance",
            lake_dir=tmp_path,
            corporate_actions=actions,
        )
        assert report.passed, report.issues

    def test_adj_factor_disagrees_with_actions_fails(self, tmp_path):
        df = _make_prices_frame(["AAA"], _dates(5), close=100.0)
        split_date = df.iloc[3]["date"]
        df.loc[df.index[3:], "close"] = 25.0
        # adj_factor left at 1.0 everywhere — pct_change(close_adj) will
        # show -75%, but compute_returns(close_raw, actions) applies the
        # split back-adjustment and shows 0.
        df["adj_factor"] = 1.0
        actions = pd.DataFrame(
            {
                "ticker": ["AAA"],
                "date": [split_date],
                "type": ["split"],
                "ratio": [4.0],
                "detail": [None],
            }
        )
        report = validate_frame(
            df,
            source="yfinance",
            lake_dir=tmp_path,
            corporate_actions=actions,
        )
        assert not report.passed
        assert any("N1" in i or "adjustment" in i for i in report.issues)
