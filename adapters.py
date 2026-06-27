"""
adapters.py
-----------
Real-world signal adapters — drop-in replacements for the synthetic signals in
world.py. Each returns a value in [0, 1] in the SAME shape the engine already
expects, so nothing downstream (bandit, recommender, store, web app) changes.

Design rule: every adapter FAILS SOFT. If a source is offline, rate-limited, or
not configured, the adapter returns None and the caller falls back to the
synthetic world. The live demo can never break because an external API hiccuped.

Sources, by setup cost:
  * news_relevance              -> Google News RSS   (free, no account)   [LIVE]
  * trend_surprise/changepoint  -> Google Trends     (free, no account)   [next]
  * semantic_gap                -> crawl the live site (free, needs a URL) [next]
  * reddit_growth/neg_sentiment -> Reddit API (needs creds)               [optional]
  * tiktok_velocity             -> no free API; stays synthetic/stubbed   [optional]
"""
import math
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

_UA = "Mozilla/5.0 (MarketIntelligenceEngine/1.0)"
_TIMEOUT = 8  # seconds; keep short so a slow source never stalls a brief


def _http_get(url: str):
    """GET bytes, or None on any failure (the caller falls back to synthetic)."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
            return r.read()
    except Exception:
        return None


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


def news_relevance(query: str, days: int = 14):
    """How active is recent Google News coverage for `query`? -> 0..1 (or None).

    Counts items published in the last `days` days, squashed through a saturating
    curve so a flood of coverage approaches 1 and silence approaches 0.
    """
    raw = _google_news_rss(query)
    if raw is None:
        return None
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    recent = sum(1 for d in _item_dates(raw) if d >= cutoff)
    return round(1.0 - math.exp(-recent / 8.0), 3)   # ~0.71 at 10 items, ~0.92 at 20


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


if __name__ == "__main__":   # quick manual probe against the live feed
    for q in ["knockdown rebuild", "first home buyer grant", "split level homes"]:
        print(f"\n{q!r}: news_relevance = {news_relevance(q)}")
        for h in news_headlines(q, 3):
            print("   -", h)
