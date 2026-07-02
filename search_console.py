"""
search_console.py — Google Search Console API client (read-only).

Raw HTTPS over the Search Console API v3. Given a valid OAuth access token it can
list the user's verified sites and pull Search Analytics (clicks, impressions,
average position, CTR) by day, page and query. Fail-soft: any error returns an
empty result so the app never breaks.
"""
import json
import urllib.error
import urllib.parse
import urllib.request

_BASE = "https://www.googleapis.com/webmasters/v3"


# Last GET failure reason (e.g. API not enabled, insufficient permission),
# so an empty site list can be told apart from a silent error. Single worker.
_LAST_ERROR = {"get": None}


def last_error():
    return _LAST_ERROR["get"]


def _get(url, token):
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            _LAST_ERROR["get"] = None
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            _LAST_ERROR["get"] = f"http_{e.code}: {e.read().decode()[:300]}"
        except Exception:
            _LAST_ERROR["get"] = f"http_{e.code}: {e.reason}"
        return None
    except Exception as e:
        _LAST_ERROR["get"] = f"{type(e).__name__}: {e}"
        return None


def _post(url, token, body):
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except Exception:
        return None


def list_sites(token):
    """Verified sites on the account: [{'url', 'permission'}]."""
    d = _get(f"{_BASE}/sites", token) or {}
    return [{"url": s.get("siteUrl"), "permission": s.get("permissionLevel")}
            for s in d.get("siteEntry", []) if s.get("siteUrl")]


def _query(token, site, start, end, dimensions, row_limit=1000, filters=None):
    body = {"startDate": start, "endDate": end,
            "dimensions": dimensions, "rowLimit": row_limit}
    if filters:
        body["dimensionFilterGroups"] = [{"filters": filters}]
    d = _post(f"{_BASE}/sites/{urllib.parse.quote(site, safe='')}/searchAnalytics/query",
              token, body)
    return (d or {}).get("rows", [])


def daily_by_page(token, site, start, end, row_limit=5000):
    """Per-page, per-day metrics: [{page, date, clicks, impressions, ctr, position}].
    This is the history the outcome evaluator diffs before/after an implementation."""
    rows = _query(token, site, start, end, ["page", "date"], row_limit=row_limit)
    out = []
    for r in rows:
        keys = r.get("keys", [])
        if len(keys) < 2:
            continue
        out.append({"page": keys[0], "date": keys[1],
                    "clicks": r.get("clicks", 0), "impressions": r.get("impressions", 0),
                    "ctr": r.get("ctr", 0.0), "position": r.get("position", 0.0)})
    return out


def top_queries(token, site, start, end, row_limit=25):
    rows = _query(token, site, start, end, ["query"], row_limit=row_limit)
    return [{"query": r["keys"][0], "clicks": r.get("clicks", 0),
             "impressions": r.get("impressions", 0), "position": r.get("position", 0.0)}
            for r in rows if r.get("keys")]
