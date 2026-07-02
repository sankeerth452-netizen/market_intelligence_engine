"""
outcome_evaluator.py — measure a recommendation's real-world impact.

For an implemented recommendation, compare the target page's performance in a
baseline window (the 30 days before implementation) against an evaluation window
(a 30-day window inside 30–90 days after), using the SEO metrics already fetched
and stored from Search Console / GA4. Produces the standardised outcome that
reward_engine consumes. Never invents data: if a window is empty it returns
"pending" / drops that metric.
"""
import datetime
import statistics
import time

import store

BASELINE_DAYS = 30
EVAL_MIN_DAYS = 30       # don't evaluate until at least this long after implementation
EVAL_MAX_DAYS = 90       # ... and use data no later than this


def _iso(d):
    return d.isoformat()


def _agg_gsc(rows):
    if not rows:
        return None
    clicks = sum(r["metrics"].get("clicks", 0) for r in rows)
    impr = sum(r["metrics"].get("impressions", 0) for r in rows)
    positions = [r["metrics"]["position"] for r in rows
                 if r["metrics"].get("position")]
    return {"clicks": clicks, "impressions": impr,
            "position": statistics.mean(positions) if positions else None,
            "ctr": (clicks / impr) if impr else 0.0, "days": len(rows)}


def _agg_ga4(rows):
    if not rows:
        return None
    return {"sessions": sum(r["metrics"].get("sessions", 0) for r in rows),
            "conversions": sum(r["metrics"].get("conversions", 0) for r in rows),
            "days": len(rows)}


def _pct(after, before):
    if before is None or after is None or before == 0:
        return None
    return round((after - before) / before * 100.0, 1)


def evaluate(engine, client_key, rec, now=None):
    """Return a standardised outcome dict with a 'status' of 'pending' or 'evaluated'.
    `rec` = {rec_id, target_url, implemented_at, ...}."""
    impl = rec.get("implemented_at")
    page = rec.get("target_url")
    if not impl or not page:
        return {"status": "pending", "reason": "not implemented or no target page"}
    now = now or time.time()
    days_since = (now - impl) / 86400.0
    if days_since < EVAL_MIN_DAYS:
        return {"status": "pending",
                "reason": f"~{max(1, int(EVAL_MIN_DAYS - days_since))} more days before first read"}

    impl_d = datetime.date.fromtimestamp(impl)
    base = (_iso(impl_d - datetime.timedelta(days=BASELINE_DAYS)),
            _iso(impl_d - datetime.timedelta(days=1)))
    eval_end = impl_d + datetime.timedelta(days=int(min(days_since, EVAL_MAX_DAYS)))
    eval_start = eval_end - datetime.timedelta(days=BASELINE_DAYS)
    ev = (_iso(eval_start), _iso(eval_end))

    g_before = _agg_gsc(store.seo_page_metrics(engine, client_key, "gsc", page, *base))
    g_after = _agg_gsc(store.seo_page_metrics(engine, client_key, "gsc", page, *ev))
    a_before = _agg_ga4(store.seo_page_metrics(engine, client_key, "ga4", page, *base))
    a_after = _agg_ga4(store.seo_page_metrics(engine, client_key, "ga4", page, *ev))

    if not g_before and not a_before:
        return {"status": "pending", "reason": "no baseline performance data yet"}

    outcome = {"source": "google", "status": "evaluated",
               "clicks_change_pct": None, "impressions_change_pct": None,
               "position_change": None, "ctr_change_pct": None,
               "sessions_change_pct": None, "conversions_change_pct": None}

    if g_before and g_after:
        outcome["clicks_change_pct"] = _pct(g_after["clicks"], g_before["clicks"])
        outcome["impressions_change_pct"] = _pct(g_after["impressions"], g_before["impressions"])
        outcome["ctr_change_pct"] = _pct(g_after["ctr"], g_before["ctr"])
        if g_before["position"] and g_after["position"]:
            # lower average position number = better ranking -> positive "improvement"
            outcome["position_change"] = round(g_before["position"] - g_after["position"], 1)
    if a_before and a_after:
        outcome["sessions_change_pct"] = _pct(a_after["sessions"], a_before["sessions"])
        if a_before["conversions"]:
            outcome["conversions_change_pct"] = _pct(a_after["conversions"], a_before["conversions"])

    # confidence from traffic volume — a page with a handful of clicks is noisy
    base_clicks = (g_before or {}).get("clicks", 0) + (a_before or {}).get("sessions", 0)
    outcome["data_confidence"] = round(min(1.0, base_clicks / 100.0), 2)
    return outcome
