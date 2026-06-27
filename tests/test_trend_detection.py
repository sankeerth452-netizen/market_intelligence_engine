"""Trend features: seasonality removal, surprise and change-point must behave
the way the engine relies on."""
import numpy as np
import pytest

from trend_detection import deseasonalize, cusum_changepoint, trend_features


def test_deseasonalize_removes_weekly_pattern():
    t = np.arange(90)
    season = 8.0 * np.sin(2 * np.pi * t / 7.0)
    series = 50.0 + season            # flat level + a pure weekly cycle, no noise
    resid, _ = deseasonalize(series, period=7)
    assert resid.std() < 0.5          # residual is nearly flat once the cycle is gone
    assert season.std() > 3.0         # the pattern we removed was substantial


def test_features_within_unit_range():
    rng = np.random.default_rng(0)
    f = trend_features(30 + rng.normal(0, 4, 90))
    for key in ("trend_surprise", "trend_changepoint", "trend_momentum"):
        assert 0.0 <= f[key] <= 1.0


def test_surprise_higher_for_rising_series():
    t = np.arange(90)
    flat = 30.0 + 0 * t
    rising = 30.0 + np.clip((t - 55) / 35.0, 0, 1) * 25   # ramps up near the end
    assert (trend_features(rising)["trend_surprise"]
            > trend_features(flat)["trend_surprise"])
    assert trend_features(rising)["trend_surprise"] > 0.6


def test_changepoint_higher_after_upward_step():
    rng = np.random.default_rng(2)
    noise = rng.normal(0, 1, 90)
    flat = 20 + noise
    step = 20 + noise + (np.arange(90) >= 45) * 12        # level jumps midway
    assert cusum_changepoint(step) > cusum_changepoint(flat)
