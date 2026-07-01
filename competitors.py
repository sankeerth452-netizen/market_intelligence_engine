"""
competitors.py — weekly competitor-page monitoring.

Crawls each competitor's SITEMAP (robots-friendly, no page scraping), stores the
page inventory, and diffs it week-over-week to surface the pages a competitor has
newly published — so the client can see what rivals are building.

Honest by design: retailers behind enterprise bot-protection (AWS WAF, Incapsula)
serve an HTML challenge instead of an XML sitemap, so the crawl returns nothing.
We record that transparently ("bot-protected") rather than inventing pages — those
are exactly the sites an Ahrefs integration will cover later.
"""
import os
import time
import urllib.parse

import ahrefs
import crawler
import store

# JB Hi-Fi's actual competitors (overridable via COMPETITOR_URLS).
_DEFAULT = [
    "https://www.thegoodguys.com.au",
    "https://www.officeworks.com.au",
    "https://www.harveynorman.com.au",
]
_NICE = {
    "thegoodguys.com.au": "The Good Guys",
    "officeworks.com.au": "Officeworks",
    "harveynorman.com.au": "Harvey Norman",
    "jbhifi.com.au": "JB Hi-Fi",
}
MAX_URLS = int(os.environ.get("COMPETITOR_MAX_URLS", "3000"))


def _host(url):
    return urllib.parse.urlparse(url if "://" in url else "https://" + url).netloc


def _name(url):
    reg = _host(url).replace("www.", "")
    return _NICE.get(reg, reg.split(".")[0].title())


def sites():
    raw = os.environ.get("COMPETITOR_URLS", "").strip()
    urls = [u.strip() for u in raw.split(",") if u.strip()] if raw else list(_DEFAULT)
    return [{"name": _name(u), "url": u, "host": _host(u)} for u in urls]


def refresh(engine, max_urls=MAX_URLS):
    """Crawl each competitor's sitemap and update the stored inventory. Returns a
    per-site summary. Safe to call from a cron job or a manual trigger."""
    out = []
    for s in sites():
        urls = crawler.sitemap_page_urls(s["url"], max_urls=max_urls)
        note = ""
        if not urls and ahrefs.enabled():          # bot-protected -> fall back to Ahrefs
            urls = ahrefs.top_pages(s["url"], limit=100)
            if urls:
                note = "via Ahrefs"
        ok = len(urls) > 0
        if not ok:
            note = "bot-protected or no readable sitemap"
        stats = store.sync_site_pages(engine, s["host"], urls) if ok else {"found": 0, "added": 0}
        store.record_crawl_run(engine, s["host"], stats["found"], stats["added"], ok, note)
        out.append({**s, **stats, "ok": ok, "note": note})
    return out


def report(engine, per_site=12):
    """Per-competitor view: pages tracked + the ones newly published since our
    baseline crawl (empty on a site's first crawl — that run sets the baseline)."""
    rows = []
    for s in sites():
        host = s["host"]
        run = store.last_crawl_run(engine, host)
        baseline = store.first_crawl_at(engine, host)
        news = store.new_pages(engine, host, baseline, limit=per_site) if baseline else []
        rows.append({
            "name": s["name"], "url": s["url"], "host": host,
            "total": store.site_page_count(engine, host),
            "new_count": len(news),
            "new_pages": [{"title": crawler._slug_text(n["url"]) or n["url"],
                           "url": n["url"], "first_seen": n["first_seen"]} for n in news],
            "last_crawled": run["ran_at"] if run else None,
            "ok": run["ok"] if run else None,
            "note": (run["note"] if run else "not crawled yet"),
        })
    return {"competitors": rows}


if __name__ == "__main__":                      # manual: `python competitors.py`
    eng = store.connect(os.environ.get("DATABASE_URL", "sqlite:///webapp.db"))
    for r in refresh(eng):
        print(f"{r['name']:<16} ok={r['ok']} found={r['found']} added={r['added']} {r['note']}")
