"""
forecast.py
-----------
Trend, seasonality and a simple next-month forecast from a keyword's monthly
search-volume history (real Ahrefs data). Pure statistics — no ML libraries, no
API keys — so it's cheap, deterministic and easy to reason about.

For retail marketing this is the high-value bit: knowing a category peaks in
November means you build the page in September, not December.
"""
import statistics
from collections import defaultdict

_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _next_month(ym):
    y, m = int(ym[:4]), int(ym[5:7])
    return (y + 1, 1) if m == 12 else (y, m + 1)


def analyze(history):
    """`history` = [{'date':'YYYY-MM', 'volume':int}] ascending. Returns a dict
    with trend / seasonality / forecast, or None if there isn't enough data."""
    hist = [h for h in history if h.get("volume") is not None and h.get("date")]
    if len(hist) < 6:
        return None
    vols = [h["volume"] for h in hist]
    current = vols[-1]

    # trend: the last 3 months vs the 3 before them
    recent = statistics.mean(vols[-3:])
    prior = statistics.mean(vols[-6:-3])
    trend_pct = round((recent - prior) / prior * 100) if prior else 0
    direction = "rising" if trend_pct >= 5 else "falling" if trend_pct <= -5 else "steady"

    # seasonality: average volume per calendar month across the history
    by_month = defaultdict(list)
    for h in hist:
        by_month[int(h["date"][5:7])].append(h["volume"])
    month_avg = {m: statistics.mean(v) for m, v in by_month.items()}
    overall = statistics.mean(vols)
    peak_m = max(month_avg, key=month_avg.get)
    peak_lift = round((month_avg[peak_m] - overall) / overall * 100) if overall else 0

    # forecast next month: prefer the same month last year (captures seasonality),
    # nudged by the current trend; else extrapolate the trend.
    ny, nm = _next_month(hist[-1]["date"])
    same_last_year = next((h["volume"] for h in hist if h["date"] == f"{ny - 1:04d}-{nm:02d}"), None)
    if same_last_year:
        forecast = round(same_last_year * (1 + trend_pct / 100 / 2))
    else:
        forecast = round(current * (1 + trend_pct / 100))

    return {
        "current": current,
        "trend_pct": trend_pct,
        "direction": direction,
        "peak_month": _MONTHS[peak_m - 1],
        "peak_lift": peak_lift,
        "seasonal": peak_lift >= 15,             # a real seasonal swing worth flagging
        "forecast_next": forecast,
        "forecast_month": _MONTHS[nm - 1],
        "series": vols[-18:],                    # for a sparkline
    }
