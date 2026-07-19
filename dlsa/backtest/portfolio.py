"""
Portfolio construction — shared between backtest and live.

This module is imported by BOTH the walk-forward engine and the live job.
There is no separate 'live copy'. Any fork of this code is a bug.

Overlay invariant: multipliers are clamped to (0, 1]. An overlay may only
REDUCE exposure, never increase it. Values outside this range raise ValueError.
"""

from __future__ import annotations

import pandas as pd


def build_portfolio(
    signals: pd.Series,
    overlay_multiplier: float = 1.0,
    **constraints,
) -> pd.Series:
    """Construct target portfolio weights from signals and overlay multiplier.

    Parameters
    ----------
    signals:
        Raw signal values indexed by ticker.
    overlay_multiplier:
        Scalar in (0, 1] applied to gross exposure. Values <= 0 or > 1
        are invalid and raise ValueError — overlays may only shrink.

    Returns
    -------
    pd.Series of target weights indexed by ticker.
    """
    if not (0 < overlay_multiplier <= 1.0):
        raise ValueError(
            f"overlay_multiplier must be in (0, 1], got {overlay_multiplier}. "
            "Overlays may only reduce exposure, never increase or invert it."
        )
    raise NotImplementedError("build_portfolio: not yet implemented")
