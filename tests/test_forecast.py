"""Forecast analysis must derive sensible trend / seasonality / next-month from a
monthly volume history; Ahrefs volume-history stays off (no spend) without a key."""
import ahrefs
import forecast


def _hist(vals, year=2025, month=1):
    out, y, m = [], year, month
    for v in vals:
        out.append({"date": f"{y:04d}-{m:02d}", "volume": v})
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return out


def test_detects_rising_trend():
    a = forecast.analyze(_hist([100, 100, 100, 100, 100, 100, 120, 130, 140]))
    assert a and a["direction"] == "rising" and a["trend_pct"] > 0


def test_detects_december_seasonality():
    vals = ([100] * 11 + [300]) * 2                # a December spike two years running
    a = forecast.analyze(_hist(vals))
    assert a["peak_month"] == "Dec" and a["seasonal"] is True and a["peak_lift"] > 15


def test_forecast_uses_same_month_last_year():
    # 13 months so "next month" (month 14 = Feb yr2) has a same-month-last-year anchor
    a = forecast.analyze(_hist([500] + [100] * 12))   # Jan yr1 = 500, then flat 100
    assert a["forecast_month"] == "Feb"


def test_needs_enough_history():
    assert forecast.analyze(_hist([100, 100, 100])) is None


def test_volume_history_off_without_key(monkeypatch):
    monkeypatch.delenv("AHREFS_API_KEY", raising=False)
    assert ahrefs.volume_history("headphones") == []
