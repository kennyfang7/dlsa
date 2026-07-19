"""
Crowding monitor overlay (O3/O9).

Consumes FINRA short-interest data with strict publication-vintage
discipline: multiplier(asof=t) may only use rows with publication_date <= t.
days_to_cover is computed at read time (shares ÷ trailing-21d median volume),
never stored as a column in the Parquet table.

Multiplier range: [0.3, 1.0] — overlays only shrink.
"""
