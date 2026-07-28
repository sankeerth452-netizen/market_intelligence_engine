"""
radar/sources.py — the three trend sources for The Radar, via Apify.

Google Trends + TikTok + Instagram. Each source returns a normalised list of
trend SIGNALS for the topic (default: crafts, Australia, last 24h):

    {"term", "source", "score" (0..1 velocity), "metric" (human label), "url"}

Design rules (matching the main engine):
  * FAIL-SOFT — any error, timeout, quota or a missing APIFY_API_KEY returns the
    built-in SAMPLE signals so the dashboard always renders (demo mode). It only
    goes "live" when a real key + actors are configured.
  * NEVER fabricates live data — sample signals are flagged `sample: True`, and
    engine.collect() marks the whole read as demo vs live so nothing pretends to
    be real Apify data.
  * Self-contained — no imports from the main engine, so this folder ports cleanly
    into another dashboard.

The topic is Google Trends /m/01mrgs == "Craft". Everything is overridable via
env vars, so the same code runs any topic/category later.
"""
import json
import math
import os
import time
import urllib.parse
import urllib.request

_BASE = "https://api.apify.com/v2"

# ---- the topic (crafts) + region; override via env to run any category ----
TOPIC       = os.environ.get("RADAR_TOPIC", "crafts")
TOPIC_MID   = os.environ.get("RADAR_TOPIC_MID", "/m/01mrgs")      # Google Trends topic id
GEO         = os.environ.get("RADAR_GEO", "AU")
TIMEFRAME   = os.environ.get("RADAR_TIMEFRAME", "now 1-d")        # last 24h — a daily read

# ---- Apify actors (all overridable). TikTok actor reused from the main engine ----
TIKTOK_ACTOR    = os.environ.get("APIFY_TIKTOK_ACTOR", "sociavault~tiktok-keyword-search-scraper")
INSTAGRAM_ACTOR = os.environ.get("APIFY_INSTAGRAM_ACTOR", "apify~instagram-hashtag-scraper")
TRENDS_ACTOR    = os.environ.get("APIFY_TRENDS_ACTOR", "emastra~google-trends-scraper")
_TIMEOUT        = float(os.environ.get("APIFY_RUN_TIMEOUT", "120"))

# seed hashtags/keywords we scan on the social platforms (topline: a small set)
KEYWORDS = [k.strip() for k in os.environ.get(
    "RADAR_KEYWORDS", "crafts,craftok,diy crafts,craft ideas").split(",") if k.strip()]


def token():
    return os.environ.get("APIFY_API_KEY", "").strip()


def live():
    """True only when an Apify key is configured (otherwise we serve sample data)."""
    return bool(token())


def _run(actor, payload, timeout=_TIMEOUT):
    """Run an Apify actor synchronously, return its dataset items (list). Fail-soft:
    any error returns [] so the caller falls back to sample data."""
    tok = token()
    if not tok:
        return []
    url = "%s/acts/%s/run-sync-get-dataset-items?token=%s" % (_BASE, actor, urllib.parse.quote(tok))
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                 headers={"content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read())
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get("items") or data.get("data") or []
        return []
    except Exception:
        return []


def _sat(x, scale):
    """Map an unbounded non-negative count onto 0..1, saturating at ~scale."""
    return round(1.0 - math.exp(-max(0.0, x) / scale), 3) if scale > 0 else 0.0


def _num(x, default=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


# ======================================================================= TRENDS
def google_trends():
    """Rising / breakout related queries for the topic from Google Trends (via an
    Apify actor, since Google 429s direct server access). These 'rising' queries
    are the early-signal gold the brief asks for. Falls back to sample."""
    items = _run(TRENDS_ACTOR, {
        "searchTerms": [TOPIC], "geo": GEO, "timeRange": TIMEFRAME,
        "isMultiple": False, "isPublic": True, "includeRelatedQueries": True,
    }) if live() else []
    out = []
    for it in items:
        # actors differ; look for a rising/related-queries block defensively
        rising = (it.get("relatedQueries") or {}).get("rising") or it.get("rising") or []
        if isinstance(rising, dict):
            rising = rising.get("rankedKeyword") or rising.get("items") or []
        for rq in rising:
            term = (rq.get("query") or rq.get("term") or rq.get("topic", {}).get("title")
                    if isinstance(rq, dict) else str(rq))
            if not term:
                continue
            val = _num(rq.get("value") or rq.get("growth") or 0) if isinstance(rq, dict) else 0
            formatted = (rq.get("formattedValue") or ("Breakout" if val >= 5000 else "+%d%%" % val)) \
                if isinstance(rq, dict) else "rising"
            score = 1.0 if (isinstance(formatted, str) and "reak" in formatted) else min(1.0, val / 500.0)
            out.append({"term": term.lower().strip(), "source": "google_trends",
                        "score": round(max(0.35, score), 3), "metric": "Google Trends: %s" % formatted,
                        "url": "https://trends.google.com/trends/explore?q=%s&geo=%s"
                               % (urllib.parse.quote(term), GEO)})
    return out or _sample("google_trends")


# ======================================================================= TIKTOK
def tiktok():
    """Recent TikTok videos for the topic; aggregate the hashtags that show the most
    recent reach into per-tag velocity signals. Falls back to sample."""
    seen = {}
    if live():
        for kw in KEYWORDS[:3]:
            for it in _run(TIKTOK_ACTOR, {"query": kw, "region": GEO, "max_results": 20,
                                          "sort_by": "relevance"}):
                info = it.get("aweme_info") or it
                stats = info.get("statistics") or info.get("stats") or {}
                plays = int(_num(stats.get("play_count") or stats.get("playCount") or 0))
                created = info.get("create_time") or info.get("createTime") or 0
                age_days = (time.time() - created) / 86400.0 if created else 1e9
                if age_days > 30:
                    continue
                text = (info.get("desc") or "") + " " + (it.get("desc") or "")
                for tag in _hashtags(text) or [kw.replace(" ", "")]:
                    d = seen.setdefault(tag, {"plays": [], "n": 0})
                    d["plays"].append(plays); d["n"] += 1
    if not seen:
        return _sample("tiktok")
    out = []
    for tag, d in seen.items():
        d["plays"].sort()
        median = d["plays"][len(d["plays"]) // 2] if d["plays"] else 0
        score = round(0.5 * _sat(d["n"], 6.0) + 0.5 * _sat(median, 60_000.0), 3)
        out.append({"term": tag, "source": "tiktok", "score": score,
                    "metric": "TikTok: %d recent videos, %s median plays" % (d["n"], _compact(median)),
                    "url": "https://www.tiktok.com/tag/%s" % urllib.parse.quote(tag)})
    out.sort(key=lambda s: -s["score"])
    return out[:8]


# ==================================================================== INSTAGRAM
def instagram():
    """Recent Instagram posts under the topic hashtag; aggregate the co-occurring
    hashtags by recent engagement into velocity signals. Falls back to sample."""
    seen = {}
    if live():
        for tag in [k.replace(" ", "") for k in KEYWORDS[:2]]:
            for it in _run(INSTAGRAM_ACTOR, {"hashtags": [tag], "resultsLimit": 40}):
                likes = int(_num(it.get("likesCount") or it.get("likes") or 0))
                comments = int(_num(it.get("commentsCount") or it.get("comments") or 0))
                eng = likes + 3 * comments
                for h in (it.get("hashtags") or _hashtags(it.get("caption") or "")):
                    h = h.lstrip("#").lower()
                    d = seen.setdefault(h, {"eng": [], "n": 0})
                    d["eng"].append(eng); d["n"] += 1
    if not seen:
        return _sample("instagram")
    out = []
    for tag, d in seen.items():
        d["eng"].sort()
        median = d["eng"][len(d["eng"]) // 2] if d["eng"] else 0
        score = round(0.5 * _sat(d["n"], 8.0) + 0.5 * _sat(median, 3_000.0), 3)
        out.append({"term": tag, "source": "instagram", "score": score,
                    "metric": "Instagram: %d recent posts, %s median engagement" % (d["n"], _compact(median)),
                    "url": "https://www.instagram.com/explore/tags/%s/" % urllib.parse.quote(tag)})
    out.sort(key=lambda s: -s["score"])
    return out[:8]


# ---------------------------------------------------------------- small helpers
def _hashtags(text):
    return [w[1:].lower() for w in (text or "").split() if w.startswith("#") and len(w) > 2]


def _compact(n):
    n = float(n or 0)
    return "%.1fM" % (n / 1e6) if n >= 1e6 else "%dk" % round(n / 1e3) if n >= 1e3 else str(int(n))


# --------------------------------------------------------- SAMPLE (demo) DATA --
# Realistic crafts trends so the dashboard is fully populated with NO key set.
# Clearly returned only as a fallback; engine.collect() flags the read as `sample`.
_SAMPLE = {
    "google_trends": [
        {"term": "punch needle kit", "score": 1.0, "metric": "Google Trends: Breakout"},
        {"term": "junk journal ideas", "score": 0.92, "metric": "Google Trends: +420%"},
        {"term": "resin coasters", "score": 0.8, "metric": "Google Trends: +180%"},
        {"term": "crochet bag pattern", "score": 0.7, "metric": "Google Trends: +90%"},
        {"term": "air dry clay", "score": 0.6, "metric": "Google Trends: +60%"},
    ],
    "tiktok": [
        {"term": "craftok", "score": 0.94, "metric": "TikTok: 14 recent videos, 320k median plays"},
        {"term": "punchneedle", "score": 0.88, "metric": "TikTok: 9 recent videos, 210k median plays"},
        {"term": "junkjournal", "score": 0.83, "metric": "TikTok: 11 recent videos, 140k median plays"},
        {"term": "resinart", "score": 0.72, "metric": "TikTok: 7 recent videos, 95k median plays"},
        {"term": "crochettiktok", "score": 0.66, "metric": "TikTok: 8 recent videos, 70k median plays"},
    ],
    "instagram": [
        {"term": "junkjournaling", "score": 0.9, "metric": "Instagram: 22 recent posts, 1.8k median engagement"},
        {"term": "punchneedleart", "score": 0.82, "metric": "Instagram: 17 recent posts, 1.3k median engagement"},
        {"term": "crochetersofinstagram", "score": 0.75, "metric": "Instagram: 26 recent posts, 900 median engagement"},
        {"term": "resinart", "score": 0.7, "metric": "Instagram: 15 recent posts, 1.1k median engagement"},
        {"term": "handmadeaustralia", "score": 0.58, "metric": "Instagram: 12 recent posts, 640 median engagement"},
    ],
}
_TAG_URL = {
    "google_trends": lambda t: "https://trends.google.com/trends/explore?q=%s&geo=%s" % (urllib.parse.quote(t), GEO),
    "tiktok": lambda t: "https://www.tiktok.com/tag/%s" % urllib.parse.quote(t.replace(" ", "")),
    "instagram": lambda t: "https://www.instagram.com/explore/tags/%s/" % urllib.parse.quote(t.replace(" ", "")),
}


def _sample(source):
    out = []
    for s in _SAMPLE[source]:
        out.append(dict(s, source=source, sample=True, url=_TAG_URL[source](s["term"])))
    return out
