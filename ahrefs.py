"""
ahrefs.py — real search-demand + competitor-page data via the Ahrefs API v3.

Two frugal uses, both cheap-field-only, capped, and cached by the callers:
  * search_volumes(): real monthly search volume for the client's categories
    (Keywords Explorer "overview") — upgrades the demand signal past the news
    proxy and gives the client real numbers.
  * top_pages(): a competitor's top pages by traffic (Site Explorer) — used to
    inventory bot-protected retailers (e.g. Harvey Norman) whose sitemap blocks
    our crawler, so they still appear in the Competitors view.

Credit-safe by construction (Ahrefs bills max(50, per_row_cost * rows); cached
reads cost 0):
  * OFF unless AHREFS_API_KEY is set — the demo, CI and tests never spend units.
  * A hard AHREFS_MONTHLY_UNIT_BUDGET (default 40k of the 50k key cap): we read
    Ahrefs' OWN usage counter and stop calling once we're near it.
  * Cheap fields only (url, keyword, volume — no 10-unit 'traffic' export),
    small row caps, and hour-long caches upstream.
"""
import json
import os
import time
import urllib.parse
import urllib.request

_BASE = "https://api.ahrefs.com/v3"
COUNTRY = os.environ.get("AHREFS_COUNTRY", "au")
BUDGET = int(os.environ.get("AHREFS_MONTHLY_UNIT_BUDGET", "40000"))
# AI-visibility sources. Each is an EXPENSIVE Brand Radar call (~3-4k units),
# so default to just ChatGPT; add more only if the budget allows.
AI_SOURCES = [s.strip() for s in os.environ.get("AHREFS_AI_SOURCES", "chatgpt").split(",") if s.strip()]
_usage_cache = [0.0, None]                 # (checked_at, units_used_on_key)


def _key():
    return os.environ.get("AHREFS_API_KEY", "").strip()


def enabled():
    return bool(_key())


def _get(path, params):
    key = _key()
    if not key:
        return None
    url = f"{_BASE}/{path}?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url, headers={"Authorization": f"Bearer {key}", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except Exception:
        return None


def _post(path, body):
    key = _key()
    if not key:
        return None
    req = urllib.request.Request(
        f"{_BASE}/{path}", data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": "application/json", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            return json.loads(r.read())
    except Exception:
        return None


def units_used():
    """Units consumed on this key this cycle (cached 5 min). None if unreadable."""
    now = time.time()
    if _usage_cache[1] is not None and now - _usage_cache[0] < 300:
        return _usage_cache[1]
    d = _get("subscription-info/limits-and-usage", {})
    used = (d or {}).get("limits_and_usage", {}).get("units_usage_api_key")
    _usage_cache[0], _usage_cache[1] = now, used
    return used


def within_budget():
    """True while we're under the self-imposed unit budget. If usage can't be
    read we DON'T hard-block (fail open) — the key's own 50k cap still applies."""
    used = units_used()
    return used is None or used < BUDGET


def search_volumes(keywords, country=None):
    """{keyword_lower: monthly_search_volume} for the keywords, in one batched
    call. {} if disabled / over budget / on any error."""
    if not enabled() or not keywords or not within_budget():
        return {}
    d = _get("keywords-explorer/overview", {
        "select": "keyword,volume", "country": (country or COUNTRY),
        "search_engine": "google", "keywords": ",".join(keywords)})
    out = {}
    for row in (d or {}).get("keywords", []):
        kw = (row.get("keyword") or "").lower()
        if kw and row.get("volume") is not None:
            out[kw] = int(row["volume"])
    return out


def top_pages(domain, limit=100, country=None):
    """A competitor's top pages by traffic -> [url, ...] for inventory/diffing.
    [] if disabled / over budget / on any error (caller falls back gracefully)."""
    if not enabled() or not domain or not within_budget():
        return []
    host = urllib.parse.urlparse(domain if "://" in domain else "https://" + domain).netloc or domain
    if not host.startswith("www."):
        host = "www." + host
    d = _get("site-explorer/top-pages", {
        "target": host, "mode": "subdomains", "country": (country or COUNTRY),
        "date": time.strftime("%Y-%m-%d"), "select": "url,sum_traffic",
        "order_by": "sum_traffic:desc", "limit": int(limit)})
    return [p["url"] for p in (d or {}).get("pages", []) if p.get("url")]


def share_of_voice(brand, competitors, country=None, data_sources=None):
    """AI 'share of voice' — how often each brand shows up in AI answers (ChatGPT
    etc.). Returns [{'brand':.., 'sov':0..1}] sorted desc, or [] if disabled /
    over budget / on error.

    EXPENSIVE (~3-4k units per call with Ahrefs prompts) — callers MUST cache it
    for days and keep data_sources short."""
    if not enabled() or not brand or not within_budget():
        return []
    body = {
        "data_source": data_sources or AI_SOURCES,
        "country": [(country or COUNTRY)],
        "prompts": "ahrefs",
        "brands": [{"names": [brand]}],
        "competitors": [{"names": [c]} for c in (competitors or [])],
    }
    d = _post("brand-radar/sov-overview", body)
    rows = [{"brand": m.get("brand"), "sov": round(float(m.get("share_of_voice") or 0), 4)}
            for m in (d or {}).get("metrics", []) if m.get("brand")]
    rows.sort(key=lambda r: r["sov"], reverse=True)
    return rows
