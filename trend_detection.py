"""
trend_detection.py
------------------
Turns a raw daily search-interest series into *meaningful* trend features.

The original spec used crude deltas like "+27% growth", which fire on noise,
weekends, holidays, or one viral blip. This module instead:

  1. removes weekly seasonality (so Mondays aren't mistaken for momentum),
  2. measures *surprise* with a robust z-score (median + MAD, outlier-safe),
  3. detects a genuine *change-point* with a one-sided CUSUM,
  4. estimates short-horizon *momentum* via a local slope.

Everything is pure NumPy and runs fully offline.
"""
import numpy as np


def _sigmoid(x: float) -> float:
    return float(1.0 / (1.0 + np.exp(-x)))


def _mad(x: np.ndarray) -> float:
    """Median absolute deviation (robust spread)."""
    med = np.median(x)
    return float(np.median(np.abs(x - med)))


def deseasonalize(series, period: int = 7):
    """Strip a repeating weekly pattern so we can see the genuine signal."""
    s = np.asarray(series, dtype=float)
    n = len(s)
    idx = np.arange(n) % period
    seasonal = np.array([s[idx == p].mean() if np.any(idx == p) else 0.0
                         for p in range(period)])
    seasonal -= seasonal.mean()          # centre so it only removes the *pattern*
    resid = s - seasonal[idx]
    return resid, seasonal


def cusum_changepoint(resid) -> float:
    """One-sided CUSUM: how strongly has the level shifted upward? -> 0..1."""
    r = np.asarray(resid, dtype=float)
    mu = np.median(r)
    sd = 1.4826 * _mad(r) + 1e-9
    z = (r - mu) / sd
    slack, s_pos, peak = 0.5, 0.0, 0.0   # 'slack' = allowance before we count drift
    for v in z:
        s_pos = max(0.0, s_pos + v - slack)
        peak = max(peak, s_pos)
    return float(np.tanh(peak / 8.0))


def trend_features(series, recent: int = 7, slope_window: int = 14) -> dict:
    """Return {trend_surprise, trend_changepoint, trend_momentum}, each in 0..1."""
    s = np.asarray(series, dtype=float)
    resid, _ = deseasonalize(s)
    mu = np.median(resid)
    sd = 1.4826 * _mad(resid) + 1e-9

    # Surprise: how far the *recent* level sits above the robust baseline.
    recent_level = resid[-recent:].mean()
    surprise = _sigmoid((recent_level - mu) / sd)

    # Change-point strength.
    changepoint = cusum_changepoint(resid)

    # Momentum: slope of the last `slope_window` days, scaled by spread.
    w = resid[-slope_window:]
    slope = float(np.polyfit(np.arange(len(w)), w, 1)[0]) if len(w) >= 2 else 0.0
    momentum = _sigmoid(slope / (0.5 * sd + 1e-9))

    return {
        "trend_surprise": surprise,
        "trend_changepoint": changepoint,
        "trend_momentum": momentum,
    }
