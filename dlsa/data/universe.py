"""
PIT (point-in-time) universe calendar.

get_universe(date) is the ONLY permitted way to look up universe membership.
Never iterate over a current constituent list or a DataFrame of all tickers.

Storage layout (docs/02):
    <lake_dir>/universe/  — append-only Parquet log of membership events
        columns: ticker, effective_date, action ('add'|'remove'),
                 source_row_id, recorded_at

Corrections are new rows with a later `recorded_at` — history is never
edited or deleted. `get_universe(date)` replays this log up to `date`.

Active lake dir resolution (docs/01):
    1. `DLSA_LAKE_DIR` env var (overrides everything — tests set this)
    2. Default: `<repo_root>/data_lake/`
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

_UNIVERSE_SUBDIR = "universe"
_MEMBERSHIP_PARQUET = "universe_membership.parquet"

# Column dtypes for the append-only membership log (docs/02 schema).
_SCHEMA = pa.schema(
    [
        ("ticker", pa.string()),
        ("effective_date", pa.date32()),
        ("action", pa.string()),  # 'add' | 'remove'
        ("source_row_id", pa.string()),
        ("recorded_at", pa.timestamp("us", tz="UTC")),
    ]
)


# ---------------------------------------------------------------------------
# Lake resolution
# ---------------------------------------------------------------------------


def active_lake_dir() -> Path:
    """Return the active lake directory.

    Precedence: DLSA_LAKE_DIR env var > repo default `data_lake/`.
    Tests set DLSA_LAKE_DIR to a per-test tmp path.
    """
    env = os.environ.get("DLSA_LAKE_DIR")
    if env:
        return Path(env)
    # Repo root = three parents up from this file: dlsa/data/universe.py
    return Path(__file__).resolve().parents[2] / "data_lake"


def _membership_path(lake_dir: Path | None = None) -> Path:
    lake = Path(lake_dir) if lake_dir is not None else active_lake_dir()
    return lake / _UNIVERSE_SUBDIR / _MEMBERSHIP_PARQUET


# ---------------------------------------------------------------------------
# Ingest — fja05680 CSV → append-only membership log
# ---------------------------------------------------------------------------


def ingest_membership_csv(
    csv_path: str | Path,
    lake_dir: str | Path | None = None,
) -> Path:
    """Parse the fja05680 per-date constituents CSV into add/remove events.

    Idempotent: if the destination parquet already exists and covers the
    same source rows (matched by `source_row_id`), the file is not rewritten.
    Corrections/updates append new rows with a later `recorded_at` — never
    edits or deletes existing rows.

    Returns the parquet path.
    """
    csv_path = Path(csv_path)
    if not csv_path.exists():
        raise FileNotFoundError(f"membership CSV not found: {csv_path}")

    lake = Path(lake_dir) if lake_dir is not None else active_lake_dir()
    dest = lake / _UNIVERSE_SUBDIR / _MEMBERSHIP_PARQUET
    dest.parent.mkdir(parents=True, exist_ok=True)

    # Parse CSV: one row per date, tickers = comma-separated string.
    raw = pd.read_csv(csv_path)
    if list(raw.columns) != ["date", "tickers"]:
        raise ValueError(
            f"unexpected CSV columns {list(raw.columns)!r}; "
            "expected ['date', 'tickers'] (fja05680 format)"
        )
    raw["date"] = pd.to_datetime(raw["date"]).dt.date
    raw = raw.sort_values("date").reset_index(drop=True)

    # Diff consecutive per-date snapshots into add/remove events.
    events: list[dict] = []
    prev_members: set[str] = set()
    for _, row in raw.iterrows():
        date = row["date"]
        members = {t.strip() for t in row["tickers"].split(",") if t.strip()}
        added = members - prev_members
        removed = prev_members - members
        for t in sorted(added):
            events.append(
                {
                    "ticker": t,
                    "effective_date": date,
                    "action": "add",
                    "source_row_id": _row_id(csv_path.name, date, t, "add"),
                }
            )
        for t in sorted(removed):
            events.append(
                {
                    "ticker": t,
                    "effective_date": date,
                    "action": "remove",
                    "source_row_id": _row_id(csv_path.name, date, t, "remove"),
                }
            )
        prev_members = members

    df = pd.DataFrame(events)
    if df.empty:
        raise ValueError(f"CSV parsed to zero membership events: {csv_path}")

    # Recorded-at: a single UTC timestamp for this batch — this is when WE
    # learned it, per docs/02. Idempotent re-ingests keep the same rows so
    # we stamp deterministically from the source content hash rather than
    # wall-clock, so the parquet is bit-reproducible.
    content_hash = _sha256_file(csv_path)[:16]
    # Deterministic timestamp derived from the hash — always the same across
    # re-runs of the same CSV, but stable.
    recorded_at = pd.Timestamp("2000-01-01", tz="UTC") + pd.Timedelta(
        seconds=int(content_hash, 16) % (10 * 365 * 86400)
    )
    df["recorded_at"] = recorded_at

    # Idempotency: if the file exists and holds the same source_row_ids, skip.
    if dest.exists():
        existing = pq.read_table(dest).to_pandas()
        if set(existing["source_row_id"]) == set(df["source_row_id"]):
            return dest
        # Corrections land as an append with a later recorded_at.
        df["recorded_at"] = max(
            df["recorded_at"].iloc[0],
            existing["recorded_at"].max() + pd.Timedelta(seconds=1),
        )
        df = pd.concat([existing, df], ignore_index=True)

    table = pa.Table.from_pandas(df, schema=_SCHEMA, preserve_index=False)
    pq.write_table(table, dest)
    return dest


def _row_id(csv_name: str, date, ticker: str, action: str) -> str:
    """Deterministic provenance ID for a single membership event."""
    key = f"{csv_name}|{date.isoformat()}|{ticker}|{action}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Reader — get_universe(date)
# ---------------------------------------------------------------------------


def _load_events(lake_dir: Path | None = None) -> pd.DataFrame:
    path = _membership_path(lake_dir)
    if not path.exists():
        raise KeyError(
            f"universe membership log not found at {path!r}; "
            "ingest the PIT membership CSV before calling get_universe()"
        )
    df = pq.read_table(path).to_pandas()
    df["effective_date"] = pd.to_datetime(df["effective_date"], utc=True)
    df = df.sort_values(["effective_date", "recorded_at", "ticker"]).reset_index(
        drop=True
    )
    return df


def get_universe(date: pd.Timestamp) -> list[str]:
    """Return the list of universe members as of `date` (point-in-time).

    Replays the append-only membership log up to and including `date`.
    Rows are ordered by effective_date, then recorded_at, then ticker —
    so the output is deterministic (same date → same list, same order).

    Raises `KeyError` for dates outside calendar coverage; never silently
    returns the nearest snapshot.
    """
    d = pd.Timestamp(date)
    if d.tz is None:
        d = d.tz_localize("UTC")
    else:
        d = d.tz_convert("UTC")
    d = d.normalize()

    events = _load_events()
    covered_start = events["effective_date"].min()
    covered_end = events["effective_date"].max()
    if d < covered_start or d > covered_end:
        raise KeyError(
            f"{d.date()} is outside universe coverage "
            f"[{covered_start.date()}, {covered_end.date()}]"
        )

    active: set[str] = set()
    for _, row in events.iterrows():
        if row["effective_date"] > d:
            break
        if row["action"] == "add":
            active.add(row["ticker"])
        elif row["action"] == "remove":
            active.discard(row["ticker"])
        else:
            raise ValueError(f"unknown action {row['action']!r} in universe log")
    return sorted(active)


def latest_universe_date() -> pd.Timestamp:
    """Return the last date covered by the PIT calendar (tz-aware UTC)."""
    events = _load_events()
    ts = events["effective_date"].max()
    return pd.Timestamp(ts).tz_convert("UTC").normalize()


def calendar_available() -> bool:
    """Return True if a populated PIT calendar exists in the active lake."""
    path = _membership_path()
    if not path.exists():
        return False
    try:
        # A zero-row parquet is not "populated".
        meta = pq.read_metadata(path)
        return meta.num_rows > 0
    except Exception:
        return False
