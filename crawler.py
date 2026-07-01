"""
crawler.py
----------
A generic, client-agnostic website crawler. Give it ANY URL and it returns the
visible text of up to `max_pages` pages from that site. It carries no business
knowledge whatsoever — the engine uses it to understand whichever client website
is configured (SITE_URL), and the same code serves every client.

Pages are discovered via the site's sitemap.xml (incl. sitemap indexes), then by
following same-host links from the homepage. The crawler is polite: it respects
robots.txt (disallow rules + crawl-delay), stays on the host, skips non-HTML, caps
the page count, and fails soft — returning whatever it could fetch (possibly []),
so a hostile or offline site can never crash a brief.
"""
import re
import time
import urllib.parse
import urllib.request
import urllib.robotparser
import xml.etree.ElementTree as ET
from collections import deque
from html.parser import HTMLParser

USER_AGENT = "MarketIntelligenceEngine/1.0 (+content-gap analysis)"
_TIMEOUT = 8
_SKIP_EXT = (".pdf", ".jpg", ".jpeg", ".png", ".gif", ".svg", ".zip", ".mp4",
             ".css", ".js", ".ico", ".woff", ".woff2")


class _Extractor(HTMLParser):
    """Pull visible text + same-page links, skipping non-content elements."""
    _SKIP = {"script", "style", "noscript", "nav", "footer", "header", "svg",
             "template", "form"}

    def __init__(self):
        super().__init__()
        self._skip = 0
        self._text = []
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._skip += 1
        elif tag == "a":
            for k, v in attrs:
                if k == "href" and v:
                    self.links.append(v)

    def handle_endtag(self, tag):
        if tag in self._SKIP and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if self._skip == 0:
            t = data.strip()
            if t:
                self._text.append(t)

    def result(self):
        return re.sub(r"\s+", " ", " ".join(self._text)).strip(), self.links


def _fetch(url: str):
    """GET bytes for an HTML/XML URL, or None on any failure / wrong type."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
            ctype = r.headers.get("Content-Type", "").lower()
            if ctype and "html" not in ctype and "xml" not in ctype:
                return None
            return r.read()
    except Exception:
        return None


def parse_page(raw: bytes):
    """(visible_text, links) for a page's bytes. Never raises."""
    try:
        ex = _Extractor()
        ex.feed(raw.decode("utf-8", "ignore"))
        return ex.result()
    except Exception:
        return "", []


def _robots(base: str):
    rp = urllib.robotparser.RobotFileParser()
    rp.set_url(urllib.parse.urljoin(base, "/robots.txt"))
    try:
        rp.read()
        return rp
    except Exception:
        return None


def _sitemap_urls(base: str, limit: int):
    raw = _fetch(urllib.parse.urljoin(base, "/sitemap.xml"))
    if not raw:
        return []
    try:
        root = ET.fromstring(raw)
    except Exception:
        return []
    locs = [e.text.strip() for e in root.iter()
            if e.tag.endswith("}loc") and e.text]
    if root.tag.endswith("sitemapindex"):          # index -> fetch a few child maps
        urls = []
        for sm in locs[:3]:
            sraw = _fetch(sm)
            if not sraw:
                continue
            try:
                sroot = ET.fromstring(sraw)
                urls += [e.text.strip() for e in sroot.iter()
                         if e.tag.endswith("}loc") and e.text]
            except Exception:
                pass
        return urls[:limit]
    return locs[:limit]


def crawl(url: str, max_pages: int = 8, delay: float = 0.3):
    """Return up to `max_pages` page texts from `url`'s site. Fails soft -> []."""
    start = url if "://" in url else "https://" + url
    parts = urllib.parse.urlparse(start)
    host = parts.netloc
    base = f"{parts.scheme}://{host}"
    if not host:
        return []

    rp = _robots(base)
    allowed = (lambda u: rp.can_fetch(USER_AGENT, u)) if rp else (lambda u: True)

    queue = deque([start])
    for u in _sitemap_urls(base, max_pages * 3):     # sitemap pages preferred
        queue.append(u)

    seen, pages = set(), []
    while queue and len(pages) < max_pages:
        u = queue.popleft()
        u, _frag = urllib.parse.urldefrag(u)
        if u in seen:
            continue
        seen.add(u)
        p = urllib.parse.urlparse(u)
        if p.netloc != host or p.path.lower().endswith(_SKIP_EXT) or not allowed(u):
            continue
        raw = _fetch(u)
        if not raw:
            continue
        text, links = parse_page(raw)
        if len(text) > 80:
            pages.append(text)
        if len(pages) + len(queue) < max_pages:      # only widen if we still need pages
            for href in links:
                nxt, _ = urllib.parse.urldefrag(urllib.parse.urljoin(u, href))
                if urllib.parse.urlparse(nxt).netloc == host and nxt not in seen:
                    queue.append(nxt)
        if delay:
            time.sleep(delay)
    return pages


_ASSET_RE = re.compile(r"\.(jpg|jpeg|png|gif|svg|webp|avif|pdf|xml|css|js|ico|mp4|woff2?)(\?|$)", re.I)


def _slug_text(url: str) -> str:
    """Turn a URL's last path segment into space-separated words (the 'content'
    a sitemap reveals about a page — e.g. /products/sony-4k-oled-tv -> 'sony 4k oled tv')."""
    seg = urllib.parse.urlparse(url).path.rstrip("/").split("/")[-1]
    seg = re.sub(r"\.(html?|aspx?|php)$", "", seg)
    words = [w for w in re.split(r"[-_/+.]+", seg) if w and not w.isdigit() and len(w) > 1]
    return " ".join(words)


def sitemap_corpus(url: str, max_urls: int = 2500, max_sitemaps: int = 6):
    """Build a content-coverage corpus from a site's SITEMAP (no page scraping).

    Sitemaps are published precisely so crawlers can discover what a site covers,
    so this is robots-friendly and works even on JS-rendered / scraper-blocked
    retailers (JB Hi-Fi, etc.) where fetching page bodies fails. We read only the
    public URL slugs and turn them into text — a real map of what the site sells.
    Returns a de-duplicated list of slug 'documents', or [] if no sitemap.
    """
    start = url if "://" in url else "https://" + url
    parts = urllib.parse.urlparse(start)
    host = parts.netloc
    raw = _fetch(f"{parts.scheme}://{host}/sitemap.xml")
    if not raw:
        return []
    try:
        root = ET.fromstring(raw)
    except Exception:
        return []
    locs = [e.text.strip() for e in root.iter() if e.tag.endswith("}loc") and e.text]

    page_urls = []
    if root.tag.endswith("sitemapindex"):          # index -> sample child sitemaps
        # Sample children EVENLY across the index so the corpus spans the whole
        # catalog (old + new), not just the first chunk.
        step = max(1, len(locs) // max_sitemaps)
        chosen = locs[::step][:max_sitemaps]
        per_map = max(100, (max_urls * 3) // max(1, len(chosen)))
        for sm in chosen:
            sraw = _fetch(sm)
            if not sraw:
                continue
            try:
                sroot = ET.fromstring(sraw)
                page_urls += [e.text.strip() for e in sroot.iter()
                              if e.tag.endswith("}loc") and e.text][:per_map]
            except Exception:
                pass
    else:
        page_urls = locs

    docs, seen = [], set()
    for u in page_urls:
        pu = urllib.parse.urlparse(u)
        if (pu.netloc and pu.netloc != host) or _ASSET_RE.search(pu.path):
            continue                                # skip CDNs/images/assets
        t = _slug_text(u)
        if len(t) < 3 or t in seen:
            continue
        seen.add(t)
        docs.append(t)
        if len(docs) >= max_urls:
            break
    return docs


def sitemap_page_urls(url: str, max_urls: int = 4000, max_sitemaps: int = 10):
    """Return the actual page URLs from a site's SITEMAP (not slug text).

    Used to inventory a competitor's catalogue and diff it week-over-week to spot
    newly-published pages. Reads only the published sitemap (robots-friendly) and
    fails soft to [] — including when a site is bot-protected (WAF/Incapsula) and
    serves an HTML challenge instead of XML, which ET simply can't parse.
    """
    start = url if "://" in url else "https://" + url
    parts = urllib.parse.urlparse(start)
    host = parts.netloc
    raw = _fetch(f"{parts.scheme}://{host}/sitemap.xml")
    if not raw:
        return []
    try:
        root = ET.fromstring(raw)
    except Exception:
        return []                                   # e.g. an HTML bot-challenge page
    locs = [e.text.strip() for e in root.iter() if e.tag.endswith("}loc") and e.text]

    page_urls = []
    if root.tag.endswith("sitemapindex"):           # index -> sample child sitemaps
        step = max(1, len(locs) // max_sitemaps)
        chosen = locs[::step][:max_sitemaps]
        per_map = max(200, (max_urls * 2) // max(1, len(chosen)))
        for sm in chosen:
            sraw = _fetch(sm)
            if not sraw:
                continue
            try:
                sroot = ET.fromstring(sraw)
                page_urls += [e.text.strip() for e in sroot.iter()
                              if e.tag.endswith("}loc") and e.text][:per_map]
            except Exception:
                pass
            if len(page_urls) >= max_urls:
                break
    else:
        page_urls = locs

    out, seen = [], set()
    for u in page_urls:
        pu = urllib.parse.urlparse(u)
        if (pu.netloc and pu.netloc != host) or _ASSET_RE.search(pu.path):
            continue                                # keep only this host's real pages
        if u in seen:
            continue
        seen.add(u)
        out.append(u)
        if len(out) >= max_urls:
            break
    return out


if __name__ == "__main__":   # smoke test: a permissive public page (robots allows)
    got = crawl("https://example.com", max_pages=2, delay=0)
    print(f"crawled {len(got)} page(s) from example.com")
    if got:
        print("first 140 chars:", got[0][:140], "...")
    # NOTE: sites whose robots.txt disallows generic crawlers (e.g. Wikipedia) are
    # correctly skipped — a client's own site won't block its own analysis.
