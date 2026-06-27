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
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser

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


# ---------------------------------------------------------------- site crawl ----
class _TextExtractor(HTMLParser):
    """Strip a page to its visible text, skipping script/style/nav/etc."""
    _SKIP = {"script", "style", "noscript", "nav", "footer", "header", "svg"}

    def __init__(self):
        super().__init__()
        self._depth = 0
        self._parts = []

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._depth += 1

    def handle_endtag(self, tag):
        if tag in self._SKIP and self._depth:
            self._depth -= 1

    def handle_data(self, data):
        if self._depth == 0:
            t = data.strip()
            if t:
                self._parts.append(t)

    def text(self):
        return re.sub(r"\s+", " ", " ".join(self._parts)).strip()


def _page_text(raw: bytes) -> str:
    try:
        p = _TextExtractor()
        p.feed(raw.decode("utf-8", "ignore"))
        return p.text()
    except Exception:
        return ""


def _sitemap_urls(base: str, limit: int):
    raw = _http_get(base.rstrip("/") + "/sitemap.xml")
    if raw is None:
        return []
    try:
        root = ET.fromstring(raw)
    except Exception:
        return []
    locs = [e.text for e in root.iter() if e.tag.endswith("}loc") or e.tag == "loc"]
    return [u for u in locs if u][:limit]


def crawl_site(url: str, max_pages: int = 6):
    """Fetch a site's homepage (+ a few sitemap pages) and return their visible
    text, one string per page. Fails soft -> [] so the caller can fall back."""
    home = _http_get(url)
    if home is None:
        return []
    pages = [_page_text(home)]
    for u in _sitemap_urls(url, max_pages - 1):
        raw = _http_get(u)
        if raw is not None:
            txt = _page_text(raw)
            if len(txt) > 80:
                pages.append(txt)
    return [p for p in pages if len(p) > 80]


# A built-in DEMO home-builder "site": a stand-in until a real SITE_URL is set.
# It deliberately COVERS some categories and not others, so the content-gap
# signal tells a story (rising demand for an uncovered topic -> high gap).
DEMO_SITE = [
    "Display homes locations opening hours book an appointment visit our estates near you",
    "Single storey home designs four bedroom family floor plans modern facade fixed price",
    "Double storey home designs upstairs living master retreat facade options price guide",
    "House and land packages turnkey move in ready estates titled land inclusions",
    "First home buyers guide deposit grants getting started loan pre approval steps",
    "Custom home builder fixed price contract building stages design consultation",
    "Home designs gallery browse floor plans bedrooms bathrooms living areas garage",
]
# NOT in the demo site (so these score a HIGH gap): knockdown rebuild, sloping /
# split-level blocks, sustainable/energy homes, hidden building/site costs.


def build_site_index(site_url=None, extra_corpus=None):
    """Return (SemanticIndex over the site, label). Crawls `site_url` if given
    (falling back to the demo site on any failure), else uses the demo site."""
    from semantic import SemanticIndex
    pages, label = DEMO_SITE, "demo home-builder site (built-in placeholder)"
    if site_url:
        crawled = crawl_site(site_url)
        if crawled:
            pages, label = crawled, f"live crawl of {site_url} ({len(crawled)} pages)"
    corpus = list(pages) + list(extra_corpus or [])
    return SemanticIndex(pages, fit_corpus=corpus), label


def semantic_gap(topic_text: str, index) -> float:
    """1 - best cosine match of demand text to any site page (0..1)."""
    return index.gap(topic_text)


if __name__ == "__main__":   # quick manual probes against live sources + the crawler
    print("=== Google News (live) ===")
    for q in ["knockdown rebuild", "first home buyer grant", "split level homes"]:
        print(f"{q!r}: news_relevance = {news_relevance(q)}")
        for h in news_headlines(q, 2):
            print("   -", h)

    print("\n=== content gap vs the demo site ===")
    idx, label = build_site_index()
    print("site:", label)
    for topic in ["single storey home designs", "house and land packages",
                  "knockdown rebuild process", "sloping block split level home",
                  "hidden building site costs"]:
        print(f"   gap[{topic!r:42}] = {semantic_gap(topic, idx):.2f}")

    print("\n=== real crawler smoke test (live page) ===")
    pages = crawl_site("https://en.wikipedia.org/wiki/Home_construction")
    print(f"crawled {len(pages)} page(s); first 120 chars:",
          (pages[0][:120] + "...") if pages else "(none)")
