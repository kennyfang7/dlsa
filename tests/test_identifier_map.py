"""
Unit tests for `dlsa/data/identifier_map.py` (P0.2).

Scope:
- Deterministic security_id derivation.
- v0 build from a synthetic fja05680-shaped CSV produces the right rows.
- Idempotency: re-building against the same CSV is a no-op (bit-identical
  parquet contents).
- Append-only extension: re-building against a superseding CSV appends new
  rows with a strictly later `recorded_at`; original rows are preserved.
- `resolve_security_id` honors validity ranges and NaT semantics.
- `identifier_map_available` and error paths.

Isolation: every test uses pytest's built-in `tmp_path` (function-scoped)
so no test writes to the repo `data_lake/`.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from dlsa.data.identifier_map import (
    build_identifier_map_v0,
    identifier_map_available,
    resolve_security_id,
    security_id_for_ticker,
)

# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------


def _write_csv(path: Path, snapshots: list[tuple[str, list[str]]]) -> Path:
    """Write a fja05680-shaped CSV: one row per date, tickers comma-joined."""
    rows = [{"date": d, "tickers": ",".join(ts)} for d, ts in snapshots]
    pd.DataFrame(rows, columns=["date", "tickers"]).to_csv(path, index=False)
    return path


# ----------------------------------------------------------------------------
# security_id_for_ticker
# ----------------------------------------------------------------------------


class TestSecurityIdFormat:
    def test_format_is_sid_plus_12_hex(self):
        sid = security_id_for_ticker("AAPL")
        assert sid.startswith("SID_")
        assert len(sid) == 4 + 12
        assert all(c in "0123456789abcdef" for c in sid[4:])

    def test_deterministic(self):
        assert security_id_for_ticker("AAPL") == security_id_for_ticker("AAPL")

    def test_different_tickers_get_different_ids(self):
        assert security_id_for_ticker("AAPL") != security_id_for_ticker("MSFT")

    def test_empty_ticker_raises(self):
        with pytest.raises(ValueError):
            security_id_for_ticker("")


# ----------------------------------------------------------------------------
# build_identifier_map_v0
# ----------------------------------------------------------------------------


class TestBuildV0:
    def test_build_produces_one_row_per_unique_ticker(self, tmp_path):
        csv = _write_csv(
            tmp_path / "src.csv",
            [
                ("2020-01-02", ["AAA", "BBB"]),
                ("2020-01-03", ["AAA", "BBB", "CCC"]),
                ("2020-01-06", ["AAA", "CCC"]),
            ],
        )
        build_identifier_map_v0(csv, lake_dir=tmp_path)
        assert identifier_map_available(lake_dir=tmp_path)

        # 3 unique tickers → 3 rows
        import pyarrow.parquet as pq

        df = pq.read_table(
            tmp_path / "identifier_map" / "identifier_map.parquet"
        ).to_pandas()
        assert len(df) == 3
        assert set(df["source_id"]) == {"AAA", "BBB", "CCC"}
        assert (df["source"] == "ticker").all()

    def test_valid_to_nat_for_still_current_tickers(self, tmp_path):
        csv = _write_csv(
            tmp_path / "src.csv",
            [
                ("2020-01-02", ["AAA", "BBB"]),
                ("2020-01-03", ["AAA"]),  # BBB exits before latest date
            ],
        )
        build_identifier_map_v0(csv, lake_dir=tmp_path)

        import pyarrow.parquet as pq

        df = (
            pq.read_table(tmp_path / "identifier_map" / "identifier_map.parquet")
            .to_pandas()
            .set_index("source_id")
        )
        # AAA still current → NaT; BBB exited on 2020-01-02
        assert pd.isna(df.loc["AAA", "valid_to"])
        assert df.loc["BBB", "valid_to"] == pd.Timestamp("2020-01-02").date()

    def test_valid_from_is_first_appearance(self, tmp_path):
        csv = _write_csv(
            tmp_path / "src.csv",
            [
                ("2020-01-02", ["AAA"]),
                ("2020-01-03", ["AAA", "BBB"]),
                ("2020-01-06", ["AAA", "BBB"]),
            ],
        )
        build_identifier_map_v0(csv, lake_dir=tmp_path)

        import pyarrow.parquet as pq

        df = (
            pq.read_table(tmp_path / "identifier_map" / "identifier_map.parquet")
            .to_pandas()
            .set_index("source_id")
        )
        assert df.loc["AAA", "valid_from"] == pd.Timestamp("2020-01-02").date()
        assert df.loc["BBB", "valid_from"] == pd.Timestamp("2020-01-03").date()

    def test_idempotent_rebuild_is_noop(self, tmp_path):
        """Re-ingest same CSV → parquet bytes unchanged (recorded_at derived
        deterministically from CSV content hash)."""
        csv = _write_csv(
            tmp_path / "src.csv",
            [("2020-01-02", ["AAA", "BBB"])],
        )
        p1 = build_identifier_map_v0(csv, lake_dir=tmp_path)
        bytes_1 = Path(p1).read_bytes()
        p2 = build_identifier_map_v0(csv, lake_dir=tmp_path)
        assert p1 == p2
        assert Path(p2).read_bytes() == bytes_1

    def test_append_only_extension_preserves_prior_rows(self, tmp_path):
        """A later CSV that adds a ticker must APPEND (not edit)."""
        csv_v1 = _write_csv(
            tmp_path / "v1.csv",
            [("2020-01-02", ["AAA"])],
        )
        build_identifier_map_v0(csv_v1, lake_dir=tmp_path)

        import pyarrow.parquet as pq

        before = pq.read_table(
            tmp_path / "identifier_map" / "identifier_map.parquet"
        ).to_pandas()

        # v2: adds BBB and shifts AAA's last-seen forward.
        csv_v2 = _write_csv(
            tmp_path / "v2.csv",
            [
                ("2020-01-02", ["AAA"]),
                ("2020-01-03", ["AAA", "BBB"]),
            ],
        )
        build_identifier_map_v0(csv_v2, lake_dir=tmp_path)
        after = pq.read_table(
            tmp_path / "identifier_map" / "identifier_map.parquet"
        ).to_pandas()

        # Original AAA row must still be present bit-for-bit.
        original_aaa = before[before["source_id"] == "AAA"].iloc[0]
        matches = after[
            (after["source_id"] == "AAA")
            & (after["recorded_at"] == original_aaa["recorded_at"])
        ]
        assert len(matches) == 1, "original AAA row was mutated, not preserved"
        # New rows exist with a strictly-later recorded_at.
        assert after["recorded_at"].max() > before["recorded_at"].max()

    def test_corporate_actions_parameter_reserved_for_p03(self, tmp_path):
        csv = _write_csv(tmp_path / "src.csv", [("2020-01-02", ["AAA"])])
        with pytest.raises(NotImplementedError, match="P0.3"):
            build_identifier_map_v0(
                csv,
                lake_dir=tmp_path,
                corporate_actions=pd.DataFrame({"type": ["symbol_change"]}),
            )

    def test_missing_csv_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            build_identifier_map_v0(tmp_path / "nope.csv", lake_dir=tmp_path)

    def test_bad_columns_raises(self, tmp_path):
        p = tmp_path / "bad.csv"
        pd.DataFrame({"foo": [1], "bar": [2]}).to_csv(p, index=False)
        with pytest.raises(ValueError, match="unexpected CSV columns"):
            build_identifier_map_v0(p, lake_dir=tmp_path)


# ----------------------------------------------------------------------------
# resolve_security_id
# ----------------------------------------------------------------------------


class TestResolve:
    @pytest.fixture
    def seeded_lake(self, tmp_path):
        csv = _write_csv(
            tmp_path / "src.csv",
            [
                ("2020-01-02", ["AAA", "BBB"]),
                ("2020-01-03", ["AAA"]),  # BBB exits
            ],
        )
        build_identifier_map_v0(csv, lake_dir=tmp_path)
        return tmp_path

    def test_resolves_current_ticker(self, seeded_lake):
        sid = resolve_security_id(
            "AAA", pd.Timestamp("2020-01-03"), lake_dir=seeded_lake
        )
        assert sid == security_id_for_ticker("AAA")

    def test_resolves_within_exited_range(self, seeded_lake):
        # BBB was valid 2020-01-02 → 2020-01-02
        sid = resolve_security_id(
            "BBB", pd.Timestamp("2020-01-02"), lake_dir=seeded_lake
        )
        assert sid == security_id_for_ticker("BBB")

    def test_raises_after_range_end(self, seeded_lake):
        with pytest.raises(KeyError, match="no active identifier_map range"):
            resolve_security_id("BBB", pd.Timestamp("2020-01-03"), lake_dir=seeded_lake)

    def test_raises_before_range_start(self, seeded_lake):
        with pytest.raises(KeyError, match="no active identifier_map range"):
            resolve_security_id("AAA", pd.Timestamp("2020-01-01"), lake_dir=seeded_lake)

    def test_raises_unknown_ticker(self, seeded_lake):
        with pytest.raises(KeyError, match="no identifier_map row"):
            resolve_security_id("ZZZ", pd.Timestamp("2020-01-02"), lake_dir=seeded_lake)

    def test_accepts_tz_naive_and_tz_aware_asof(self, seeded_lake):
        sid_naive = resolve_security_id(
            "AAA", pd.Timestamp("2020-01-03"), lake_dir=seeded_lake
        )
        sid_utc = resolve_security_id(
            "AAA", pd.Timestamp("2020-01-03", tz="UTC"), lake_dir=seeded_lake
        )
        assert sid_naive == sid_utc


# ----------------------------------------------------------------------------
# identifier_map_available
# ----------------------------------------------------------------------------


class TestAvailability:
    def test_false_when_missing(self, tmp_path):
        assert identifier_map_available(lake_dir=tmp_path) is False

    def test_true_after_build(self, tmp_path):
        csv = _write_csv(tmp_path / "src.csv", [("2020-01-02", ["AAA"])])
        build_identifier_map_v0(csv, lake_dir=tmp_path)
        assert identifier_map_available(lake_dir=tmp_path) is True
