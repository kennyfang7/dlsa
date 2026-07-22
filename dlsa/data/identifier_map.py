"""
Append-only identifier_map — security_id ↔ (source, source_id) validity ranges.

Every join in the modeling stack keys on security_id; ticker is for I/O and
broker orders only (docs/02 identifier policy). This module builds and reads
the map. The loader (`dlsa/data/loader.py`, P0.3) hard-depends on it.

v0 scope (P0.2, Phase 0)
------------------------
Each unique ticker in the fja05680 PIT membership CSV gets:
  - a deterministic security_id (SID_<12 hex of sha256(ticker)>) assigned
    at first sight, and
  - one validity range spanning its first→last appearance in the CSV.
    A ticker present on the latest snapshot has valid_to = NaT (still current).

The optional `corporate_actions` parameter is reserved for P0.3 (price + corp
actions ingest). When symbol_change rows are available, they extend the map
by APPEND — adding new validity ranges so old and new tickers share a single
security_id. v0 ships the fja05680-only path; P0.3 adds symbol_change handling
without editing any pre-existing row.

Storage (docs/02)
-----------------
    <lake_dir>/identifier_map/identifier_map.parquet
        security_id    str
        source         str    ('ticker' | 'permno' | 'fnspid')
        source_id      str
        valid_from     date32
        valid_to       date32 (nullable — NaT means still current)
        recorded_at    timestamp[us, tz=UTC]

**APPEND-ONLY**: corrections and extensions land as NEW rows with a strictly
later `recorded_at`. Existing rows are never edited or deleted (docs/02).

Active lake dir resolution mirrors `dlsa/data/universe.py`:
    1. `DLSA_LAKE_DIR` env var (tests set this)
    2. Default: `<repo_root>/data_lake/`
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from dlsa.data.universe import active_lake_dir

_SUBDIR = "identifier_map"
_PARQUET = "identifier_map.parquet"

_SCHEMA = pa.schema(
    [
        ("security_id", pa.string()),
        ("source", pa.string()),
        ("source_id", pa.string()),
        ("valid_from", pa.date32()),
        ("valid_to", pa.date32()),
        ("recorded_at", pa.timestamp("us", tz="UTC")),
    ]
)

_SIGNATURE_COLS = ["security_id", "source", "source_id", "valid_from", "valid_to"]


# ---------------------------------------------------------------------------
# security_id assignment
# ---------------------------------------------------------------------------


def security_id_for_ticker(ticker: str) -> str:
    """Return the deterministic security_id for `ticker`.

    Format: `SID_<first 12 hex chars of sha256(ticker)>`. Deterministic and
    order-independent — a re-ingest produces the exact same id, so the map
    is bit-reproducible from the source CSV alone.
    """
    if not ticker:
        raise ValueError("ticker must be non-empty")
    return "SID_" + hashlib.sha256(ticker.encode("utf-8")).hexdigest()[:12]


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------


def _map_path(lake_dir: Path | None = None) -> Path:
    lake = Path(lake_dir) if lake_dir is not None else active_lake_dir()
    return lake / _SUBDIR / _PARQUET


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Build — fja05680 CSV → identifier_map v0
# ---------------------------------------------------------------------------


def build_identifier_map_v0(
    membership_csv: str | Path,
    lake_dir: str | Path | None = None,
    corporate_actions: pd.DataFrame | None = None,
) -> Path:
    """Build v0 of the identifier map from the fja05680 PIT membership CSV.

    Idempotent: re-running against the same CSV produces the same parquet
    contents (compared by the validity-range signature, not `recorded_at`).
    When called after an extension (e.g., a later CSV that adds new tickers
    or new last-seen dates), APPENDS the new/changed rows with a strictly
    later `recorded_at` — never mutates existing rows (docs/02 append-only).

    Parameters
    ----------
    membership_csv : path to the fja05680 CSV (columns: date, tickers).
    lake_dir : override active lake dir (tests).
    corporate_actions : reserved for P0.3; must be None for v0. When P0.3
        lands, symbol_change rows will unify old/new tickers under a single
        security_id via appended validity ranges.

    Returns
    -------
    Path to the parquet file.
    """
    if corporate_actions is not None:
        raise NotImplementedError(
            "identifier_map v0 accepts only the fja05680 path; corporate_actions "
            "support (symbol_change unification) lands in P0.3 as an append-only "
            "extension"
        )

    csv_path = Path(membership_csv)
    if not csv_path.exists():
        raise FileNotFoundError(f"membership CSV not found: {csv_path}")

    lake = Path(lake_dir) if lake_dir is not None else active_lake_dir()
    dest = lake / _SUBDIR / _PARQUET
    dest.parent.mkdir(parents=True, exist_ok=True)

    raw = pd.read_csv(csv_path)
    if list(raw.columns) != ["date", "tickers"]:
        raise ValueError(
            f"unexpected CSV columns {list(raw.columns)!r}; "
            "expected ['date', 'tickers'] (fja05680 format)"
        )
    raw["date"] = pd.to_datetime(raw["date"]).dt.date
    raw = raw.sort_values("date").reset_index(drop=True)

    # Walk snapshots once; record first & last appearance date per ticker.
    first_seen: dict[str, object] = {}
    last_seen: dict[str, object] = {}
    latest_date = raw["date"].iloc[-1]
    for _, row in raw.iterrows():
        date = row["date"]
        for t in row["tickers"].split(","):
            t = t.strip()
            if not t:
                continue
            if t not in first_seen:
                first_seen[t] = date
            last_seen[t] = date

    if not first_seen:
        raise ValueError(f"CSV parsed to zero tickers: {csv_path}")

    rows: list[dict] = []
    for ticker in sorted(first_seen.keys()):
        # A ticker present on the latest snapshot is still current: valid_to
        # = NaT. A ticker that has exited the index pins valid_to at its
        # last observed membership date (an honest lower bound — a real exit
        # via symbol_change would refine this in P0.3 without mutating this row).
        valid_to = pd.NaT if last_seen[ticker] == latest_date else last_seen[ticker]
        rows.append(
            {
                "security_id": security_id_for_ticker(ticker),
                "source": "ticker",
                "source_id": ticker,
                "valid_from": first_seen[ticker],
                "valid_to": valid_to,
            }
        )

    df = pd.DataFrame(rows)

    # Deterministic recorded_at derived from the CSV content hash — same CSV
    # → same timestamp across re-runs, so re-ingests are bit-reproducible.
    content_hash = _sha256_file(csv_path)[:16]
    recorded_at = pd.Timestamp("2000-01-01", tz="UTC") + pd.Timedelta(
        seconds=int(content_hash, 16) % (10 * 365 * 86400)
    )
    df["recorded_at"] = recorded_at

    if dest.exists():
        existing = pq.read_table(dest).to_pandas()
        if _signature_set(existing) == _signature_set(df):
            # Nothing new: v0 idempotent no-op.
            return dest
        # Extension: append with a strictly-later recorded_at (docs/02).
        df["recorded_at"] = max(
            df["recorded_at"].iloc[0],
            existing["recorded_at"].max() + pd.Timedelta(seconds=1),
        )
        df = pd.concat([existing, df], ignore_index=True)

    table = pa.Table.from_pandas(df, schema=_SCHEMA, preserve_index=False)
    pq.write_table(table, dest)
    return dest


def _signature_set(df: pd.DataFrame) -> set[tuple]:
    """Set of (security_id, source, source_id, valid_from, valid_to) tuples.

    NaT is normalized to a sentinel so it compares equal across pandas/pyarrow
    round-trips (NaT != NaT under raw ==).
    """
    return {
        tuple("__NaT__" if pd.isna(v) else v for v in row)
        for row in df[_SIGNATURE_COLS].itertuples(index=False, name=None)
    }


# ---------------------------------------------------------------------------
# Read — as-of resolution
# ---------------------------------------------------------------------------


def _load_map(lake_dir: Path | None = None) -> pd.DataFrame:
    path = _map_path(lake_dir)
    if not path.exists():
        raise KeyError(
            f"identifier_map not found at {path!r}; "
            "run build_identifier_map_v0() before resolving security_ids"
        )
    df = pq.read_table(path).to_pandas()
    df = df.sort_values(
        ["source", "source_id", "valid_from", "recorded_at"]
    ).reset_index(drop=True)
    return df


def resolve_security_id(
    source_id: str,
    asof: pd.Timestamp,
    source: str = "ticker",
    lake_dir: Path | None = None,
) -> str:
    """Return the security_id valid for `(source, source_id)` on `asof`.

    Match rule: `valid_from <= asof <= valid_to`, where NaT `valid_to` means
    still current. When more than one row matches (a correction landed as a
    later append), the row with the greatest `recorded_at` wins — appends
    supersede, never edits.

    Raises `KeyError` if no active validity range covers `asof`.
    """
    asof_ts = pd.Timestamp(asof)
    if asof_ts.tz is None:
        asof_ts = asof_ts.tz_localize("UTC")
    else:
        asof_ts = asof_ts.tz_convert("UTC")
    asof_date = asof_ts.normalize().date()

    df = _load_map(lake_dir)
    df = df[(df["source"] == source) & (df["source_id"] == source_id)]
    if df.empty:
        raise KeyError(f"no identifier_map row for ({source}, {source_id!r})")

    mask = (df["valid_from"] <= asof_date) & (
        df["valid_to"].isna() | (df["valid_to"] >= asof_date)
    )
    hits = df[mask]
    if hits.empty:
        raise KeyError(
            f"no active identifier_map range for ({source}, {source_id!r}) "
            f"on {asof_date}"
        )
    return hits.sort_values("recorded_at").iloc[-1]["security_id"]


def identifier_map_available(lake_dir: Path | None = None) -> bool:
    """True iff a populated identifier_map parquet exists in the active lake."""
    path = _map_path(lake_dir)
    if not path.exists():
        return False
    try:
        return pq.read_metadata(path).num_rows > 0
    except Exception:
        return False
