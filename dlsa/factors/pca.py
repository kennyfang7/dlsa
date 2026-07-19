"""
PCA factor model: fits on a causal training window, produces residuals.

All operations are point-in-time:
- fit() uses only data up to train_end
- build_features() sets available_at <= asof for every row
- fit_scaler() must not see data after train_end
"""

from __future__ import annotations

import pandas as pd


class PCAFactorModel:
    """Walk-forward PCA factor model.

    Parameters
    ----------
    n_factors:
        Number of principal components to extract. Frozen param F1 = 5.
    """

    def __init__(self, n_factors: int = 5) -> None:
        self.n_factors = n_factors

    def build_features(
        self,
        prices: pd.DataFrame,
        asof: pd.Timestamp,
    ) -> pd.DataFrame:
        """Build feature DataFrame as of `asof`, with an `available_at` column.

        Every row's available_at must be <= asof. Joining on fiscal period
        end instead of filing/availability date is the canonical bug this
        guards against.
        """
        raise NotImplementedError("PCAFactorModel.build_features: not yet implemented")

    def fit_scaler(
        self,
        prices: pd.DataFrame,
        train_end: pd.Timestamp,
    ) -> object:
        """Fit normalization statistics on prices[:train_end] only.

        Returns a scaler with .mean_ and .scale_ attributes. Must not
        read any row with index > train_end.
        """
        raise NotImplementedError("PCAFactorModel.fit_scaler: not yet implemented")
