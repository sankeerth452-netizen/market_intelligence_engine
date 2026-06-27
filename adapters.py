"""
adapters.py
-----------
External-source signal adapters — drop-in replacements for the synthetic signals
in world.py. Each returns a value in [0, 1] in the SAME shape the engine expects,
so nothing downstream (bandit, recommender, store, web app) changes.

These are the OFF-SITE sources. The client's own website is handled separately by
the generic crawler.py (text) + realworld.py (the semantic_gap signal).

Design rule: every adapter FAILS SOFT. If a source is offline, rate-limited, or
not configured, it returns None and the caller falls back to a neutral value /
the synthetic world — the live demo can never break because an API hiccuped.

Sources, by setup cost:
  * news_relevance   -> Google News RSS    (free, no account)          [LIVE]
  * trend_surprise / trend_changepoint:
        Google Trends when reachable (free; Google 429s programmatic access hard,
        esp. from datacenter IPs), ELSE news-volume momentum from the same Google
        News feed — both fed through the real trend_detection pipeline.          [LIVE]
  * reddit_* / tiktok_velocity -> need creds / paid; stay neutral     [optional]
"""
import http.cookiejar
import json
import math
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

_UA = "Mozilla/5.0 (MarketIntelligenceEngine/1.0)"
_TIMEOUT = 8  # seconds; keep short so a slow source never stalls a brief


def _http_get(url: str):
    """GET bytes, or None on any failure (the caller falls back)."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
            return r.read()
    except Exception:
        return None


# --------------------------------------------------------------- Google News ----
def _google_news_rss(query: str):
    url = ("https://news.google.com/rss/search?q="
           + urllib.parse.quote(query)
           + "&hl=en-US&gl=US&ceid=US:en")
    return _http_get(url)


def _item_dates(xml_bytes):
    """Timezone-aware publish datetimes for each <item><pubDate> in an RSS feed."""
    out = []
    try:
        root = ET.fromstring(xml_bytes)
    except Exception:
        return out
    for item in root.iter("item"):
        pd = item.findtext("pubDate")
        if not pd:
            continue
        for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z"):
            try:
                dt = datetime.strptime(pd, fmt)
                out.append(dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc))
                break
            except ValueError:
                continue
    return out


def _relevance_from_dates(dates, days: int = 14) -> float:
    """Saturating count of items in the last `days` days -> 0..1."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    recent = sum(1 for d in dates if d >= cutoff)
    return round(1.0 - math.exp(-recent / 8.0), 3)   # ~0.71 at 10, ~0.92 at 20


def news_relevance(query: str, days: int = 14):
    """How active is recent Google News coverage for `query`? -> 0..1 (or None)."""
    raw = _google_news_rss(query)
    if raw is None:
        return None
    return _relevance_from_dates(_item_dates(raw), days)


def news_headlines(query: str, k: int = 5):
    """A few recent headlines for `query` (evidence for the rationale / UI)."""
    raw = _google_news_rss(query)
    if raw is None:
        return []
    try:
        root = ET.fromstring(raw)
    except Exception:
        return []
    titles = [item.findtext("title") for item in root.iter("item")]
    return [t for t in titles if t][:k]


def _news_momentum(dates):
    """Robust attention-trend from news dates (no Google Trends needed).

    News volume is sparse and bursty, so instead of forcing daily counts through
    the Trends-shaped pipeline (which saturates on sparse data), we measure how
    concentrated coverage is in the last 2 weeks vs the prior 8, and how sharply
    the recent rate exceeds the prior one. Returns 0..1 signals, or None when
    there's too little coverage to judge.
    """
    now = datetime.now(timezone.utc)

    def per_week(lo, hi):
        n = sum(1 for d in dates if timedelta(days=lo) <= (now - d) < timedelta(days=hi))
        return n / ((hi - lo) / 7.0)

    recent, prior = per_week(0, 14), per_week(14, 70)
    if recent + prior < 0.5:                      # too little coverage to judge
        return None
    surprise = recent / (recent + prior + 1e-9)   # share of attention that's recent
    changepoint = 1.0 - math.exp(-max(0.0, recent - prior) / 2.0)
    return {"trend_surprise": round(surprise, 3),
            "trend_changepoint": round(changepoint, 3)}


# ------------------------------------------------------------- Google Trends ----
# Unofficial endpoint (the same one pytrends uses), dependency-free. Google
# rate-limits it hard (429), so once blocked we stop retrying for this process.
_TRENDS_API = "https://trends.google.com/trends/api"
_trends_blocked = False


def _consent_cookie():
    return http.cookiejar.Cookie(
        version=0, name="CONSENT", value="YES+", port=None, port_specified=False,
        domain=".google.com", domain_specified=True, domain_initial_dot=True,
        path="/", path_specified=True, secure=True, expires=None, discard=False,
        comment=None, comment_url=None, rest={})


def _strip_xssi(text: str):
    i = text.find("{")
    return json.loads(text[i:]) if i != -1 else None


def trend_series(query: str, timeframe: str = "today 3-m", geo: str = ""):
    """Daily Google Trends interest (0..100) for `query` as a list, or None.

    Two-step unofficial flow (/explore -> TIMESERIES widget -> /widgetdata).
    Fails soft; trips a process-wide circuit breaker on HTTP 429.
    """
    global _trends_blocked
    if _trends_blocked:
        return None
    try:
        cj = http.cookiejar.CookieJar()
        cj.set_cookie(_consent_cookie())
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
        opener.addheaders = [("User-Agent", _UA)]

        req = json.dumps({"comparisonItem": [{"keyword": query, "geo": geo,
                                              "time": timeframe}],
                          "category": 0, "property": ""})
        ex_url = f"{_TRENDS_API}/explore?hl=en-US&tz=0&req={urllib.parse.quote(req)}"
        ex = opener.open(ex_url, timeout=_TIMEOUT).read().decode("utf-8", "ignore")
        widgets = (_strip_xssi(ex) or {}).get("widgets", [])
        ts = next((w for w in widgets if w.get("id") == "TIMESERIES"), None)
        if not ts:
            return None
        wreq = json.dumps(ts["request"])
        ml_url = (f"{_TRENDS_API}/widgetdata/multiline?hl=en-US&tz=0"
                  f"&req={urllib.parse.quote(wreq)}&token={ts['token']}")
        ml = opener.open(ml_url, timeout=_TIMEOUT).read().decode("utf-8", "ignore")
        points = (_strip_xssi(ml) or {}).get("default", {}).get("timelineData", [])
        vals = [float(p["value"][0]) for p in points if p.get("value")]
        return vals if len(vals) >= 14 else None
    except urllib.error.HTTPError as e:
        if e.code == 429:
            _trends_blocked = True   # stop hammering a blocked endpoint
        return None
    except Exception:
        return None


def _trend_from_series(series):
    from trend_detection import trend_features   # lazy: keeps adapters import light
    tf = trend_features(series)
    return {"trend_surprise": tf["trend_surprise"],
            "trend_changepoint": tf["trend_changepoint"]}


def trend_signals(query: str):
    """{'trend_surprise', 'trend_changepoint', 'source'} or None.

    Google Trends search demand when reachable; otherwise news-volume momentum
    from the Google News feed. Both go through the real trend_detection pipeline.
    """
    series = trend_series(query)
    if series:
        return {**_trend_from_series(series), "source": "google_trends"}
    raw = _google_news_rss(query)
    m = _news_momentum(_item_dates(raw)) if raw else None
    return {**m, "source": "news_momentum"} if m else None


def demand_signals(query: str):
    """One pass over the sources -> {news_relevance, trend}. Used by realworld so
    a category needs a single Google News fetch (relevance + momentum) plus at
    most one Trends attempt (circuit-broken after the first 429)."""
    raw = _google_news_rss(query)
    dates = _item_dates(raw) if raw else []
    relevance = _relevance_from_dates(dates) if raw is not None else None

    series = trend_series(query)
    if series:
        trend = {**_trend_from_series(series), "source": "google_trends"}
    else:
        m = _news_momentum(dates)
        trend = {**m, "source": "news_momentum"} if m else None
    return {"news_relevance": relevance, "trend": trend}


if __name__ == "__main__":   # quick probe against the live sources
    for q in ["knockdown rebuild", "sustainable homes", "building costs"]:
        d = demand_signals(q)
        t = d["trend"]
        print(f"{q!r:22} news={d['news_relevance']}  "
              f"trend={t and (t['trend_surprise'], t['trend_changepoint'])}  "
              f"via={t and t['source']}")
