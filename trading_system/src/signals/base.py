"""
Signal interface.

Every strategy (momentum, mean-reversion, vol-regime, ML, etc.) implements
this interface and outputs a CONTINUOUS score in roughly [-1, 1] per
asset per bar — never a binary buy/sell. The portfolio construction layer
is responsible for turning blended scores into position sizes via the
risk engine.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np
import pandas as pd


class Signal(ABC):
    name: str

    @abstractmethod
    def compute(self, ohlcv: pd.DataFrame) -> pd.Series:
        """
        ohlcv: DataFrame indexed by timestamp with columns
               [open, high, low, close, volume], single asset.
        Returns: pd.Series indexed the same way, values in [-1, 1].
                 NaN where the signal isn't yet computable (e.g. warmup).
        """
        raise NotImplementedError


def _zscore_clip(x: pd.Series, clip: float = 3.0) -> pd.Series:
    mu, sigma = x.mean(), x.std()
    if sigma == 0 or np.isnan(sigma):
        return pd.Series(0.0, index=x.index)
    z = (x - mu) / sigma
    return z.clip(-clip, clip) / clip  # rescale to roughly [-1, 1]


class MultiTimeframeMomentum(Signal):
    """
    Example strategy signal (Phase 1 reference implementation, NOT yet
    validated on real data — see README Phase 2 for the walk-forward /
    purged-CV process this must pass before being trusted with capital).

    Combines return momentum across multiple lookback windows (hours),
    with a breakout filter using ATR-normalized range.
    """
    name = "momentum"

    def __init__(self, lookback_windows: list[int], breakout_atr_multiple: float = 1.5):
        self.lookback_windows = lookback_windows
        self.breakout_atr_multiple = breakout_atr_multiple

    def compute(self, ohlcv: pd.DataFrame) -> pd.Series:
        close = ohlcv["close"]
        scores = []
        for window in self.lookback_windows:
            ret = close.pct_change(window)
            scores.append(_zscore_clip(ret))
        blended = pd.concat(scores, axis=1).mean(axis=1)

        # breakout filter: require price to have moved beyond N*ATR from
        # its rolling mean to treat momentum as "confirmed" rather than noise
        atr = _average_true_range(ohlcv, period=14)
        rolling_mean = close.rolling(max(self.lookback_windows)).mean()
        breakout_confirmed = (close - rolling_mean).abs() > (self.breakout_atr_multiple * atr)

        blended = blended.where(breakout_confirmed, blended * 0.3)  # damp unconfirmed signal, don't zero it
        return blended.clip(-1, 1)


class MeanReversion(Signal):
    """Volatility-adjusted range mean-reversion, example reference impl."""
    name = "mean_reversion"

    def __init__(self, lookback_hours: int = 48, zscore_entry: float = 2.0, zscore_exit: float = 0.5):
        self.lookback_hours = lookback_hours
        self.zscore_entry = zscore_entry
        self.zscore_exit = zscore_exit

    def compute(self, ohlcv: pd.DataFrame) -> pd.Series:
        close = ohlcv["close"]
        rolling_mean = close.rolling(self.lookback_hours).mean()
        rolling_std = close.rolling(self.lookback_hours).std()
        z = (close - rolling_mean) / rolling_std.replace(0, np.nan)

        # negative of z: price far above mean -> negative (short-leaning) score
        score = -z / self.zscore_entry
        score = score.where(z.abs() >= self.zscore_exit, 0.0)
        return score.clip(-1, 1)


def _average_true_range(ohlcv: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = ohlcv["high"], ohlcv["low"], ohlcv["close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()
