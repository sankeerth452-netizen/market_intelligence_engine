"""
apify.py — real social signals via the Apify platform.

Currently powers the TikTok velocity signal (previously a neutral 0.5 stub) with
real data: for a category keyword it pulls recent TikTok videos and turns their
reach + volume + recency into a 0..1 `tiktok_velocity`.

Off unless APIFY_API_KEY is set, so the public demo, the tests and CI never
depend on it or spend Apify credits; when the key is present, realworld.py uses
these real signals instead of the neutral stub. Never fabricates: if a run
fails or returns nothing, the caller falls back to neutral.

Reddit is intentionally NOT wired yet — the two actors on the account either
ignore the search term or return no engagement metrics (see notes in the repo
discussion). Add it here once a suitable actor is chosen.
"""
import json
import math
import os
import time
import urllib.request

_BASE = "https://api.apify.com/v2"
TIKTOK_ACTOR = os.environ.get("APIFY_TIKTOK_ACTOR", "sociavault~tiktok-keyword-search-scraper")
REGION = os.environ.get("APIFY_REGION", "AU")
_RUN_TIMEOUT = float(os.environ.get("APIFY_RUN_TIMEOUT", "90"))


def _token():
    return os.environ.get("APIFY_API_KEY", "").strip()


def enabled():
    """True only when a key is configured — the switch realworld.py checks."""
    return bool(_token())


def _run_actor(actor, payload, timeout=_RUN_TIMEOUT):
    """Run an actor synchronously and return its dataset items (list). Fail-soft:
    any error (network, timeout, quota, bad JSON) returns [] so the caller can
    fall back to a neutral signal rather than break the brief."""
    token = _token()
    if not token:
        return []
    url = f"{_BASE}/acts/{actor}/run-sync-get-dataset-items?token={token}"
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read())
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _saturate(x, scale):
    """Map an unbounded non-negative count onto 0..1, saturating at ~scale."""
    return 1.0 - math.exp(-max(0.0, x) / scale) if scale > 0 else 0.0


def tiktok_velocity(keyword, max_results=20):
    """Real 0..1 TikTok velocity for a category keyword, or None if unavailable.

    Combines how *many* recent videos the keyword is producing with their
    typical *reach* (median play count) — a topic that is both frequently
    posted about and widely viewed scores high."""
    if not enabled() or not keyword:
        return None
    items = _run_actor(TIKTOK_ACTOR, {
        "query": keyword, "region": REGION,
        "max_results": int(max_results), "sort_by": "relevance"})
    now = time.time()
    recent_plays = []
    for it in items:
        info = it.get("aweme_info") or {}
        stats = info.get("statistics") or {}
        created = info.get("create_time") or 0
        age_days = (now - created) / 86400.0 if created else 1e9
        if age_days <= 90:                       # "velocity" = recent momentum only
            recent_plays.append(int(stats.get("play_count") or 0))
    if not recent_plays:
        return None
    recent_plays.sort()
    median_play = recent_plays[len(recent_plays) // 2]
    volume_term = _saturate(len(recent_plays), 8.0)      # ~a dozen recent videos -> high
    reach_term = _saturate(median_play, 50_000.0)        # ~tens of thousands of plays -> high
    return round(0.5 * volume_term + 0.5 * reach_term, 3)
