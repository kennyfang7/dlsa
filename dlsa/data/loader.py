"""
Data loader — builds the security_id-keyed wide price frame.

load_prices(start, end) reads from the data lake, applies identifier_map
to normalise tickers to security_ids, selects the price source per
frozen param D5, and returns a tz-aware UTC DataFrame.

Source priority (D5): primary vendor → fallback → fail closed (never
forward-fill or guess). vendor_intake/ (D7) is unreachable from this
module until a source's CPCV ablation gate passes.
"""
