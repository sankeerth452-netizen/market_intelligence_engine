"""Off-site signal adapters — the news-momentum trend must be robust (sparse =
neutral, recent-heavy = rising) and Google Trends must fail soft when blocked.
All offline: dates are constructed, no network."""
from datetime import datetime, timedelta, timezone

import adapters


def _ago(days):
    return datetime.now(timezone.utc) - timedelta(days=days)


def test_news_momentum_distinguishes_rising_from_stale():
    recent_heavy = [_ago(i) for i in range(0, 12)] + [_ago(40)]      # mostly last 2wks
    stale = [_ago(40 + i) for i in range(0, 12)] + [_ago(2)]         # mostly old
    rising = adapters._news_momentum(recent_heavy)
    fading = adapters._news_momentum(stale)
    assert rising["trend_surprise"] > 0.6
    assert fading["trend_surprise"] < 0.5
    assert 0.0 <= rising["trend_changepoint"] <= 1.0


def test_news_momentum_none_when_too_sparse():
    assert adapters._news_momentum([]) is None
    assert adapters._news_momentum([_ago(300)]) is None    # one very old item


def test_relevance_saturates_and_is_bounded():
    few = adapters._relevance_from_dates([_ago(1), _ago(2)])
    many = adapters._relevance_from_dates([_ago(i % 14) for i in range(40)])
    assert 0.0 <= few < many < 1.0


def test_trend_series_circuit_breaker_short_circuits(monkeypatch):
    # once Google Trends has 429'd, we must not attempt another request
    monkeypatch.setattr(adapters, "_trends_blocked", True)
    assert adapters.trend_series("anything") is None
