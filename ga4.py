"""
ga4.py — Google Analytics 4 client (read-only).

Raw HTTPS over the GA4 Admin API (list properties) and Data API (runReport).
Given a valid OAuth access token it pulls ORGANIC-search performance by landing
page and day: sessions, users, engagement, and — when the property has them —
conversions and revenue. Fail-soft: errors return empty results.
"""
import json
import urllib.error
import urllib.request

_ADMIN = "https://analyticsadmin.googleapis.com/v1beta"
_DATA = "https://analyticsdata.googleapis.com/v1beta"
_METRICS = ["sessions", "totalUsers", "engagementRate", "conversions", "totalRevenue"]


# Last GET failure reason (e.g. Admin API not enabled, insufficient
# permission), so an empty property list can be told apart from a silent
# error. Single worker (see Dockerfile).
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


def _num(property_id):
    return str(property_id or "").replace("properties/", "").strip()


def list_properties(token):
    """GA4 properties on the account: [{'property':'properties/123','name':...}]."""
    d = _get(f"{_ADMIN}/accountSummaries", token) or {}
    out = []
    for acc in d.get("accountSummaries", []):
        for p in acc.get("propertySummaries", []):
            if p.get("property"):
                out.append({"property": p["property"],
                            "name": p.get("displayName", p["property"])})
    return out


def _run_report(token, property_id, dimensions, start, end, metrics=None, dim_filter=None):
    body = {
        "dateRanges": [{"startDate": start, "endDate": end}],
        "dimensions": [{"name": d} for d in dimensions],
        "metrics": [{"name": m} for m in (metrics or _METRICS)],
        "limit": 10000,
    }
    if dim_filter:
        body["dimensionFilter"] = dim_filter
    return _post(f"{_DATA}/properties/{_num(property_id)}:runReport", token, body)


_ORGANIC = {"filter": {"fieldName": "sessionDefaultChannelGroup",
                       "stringFilter": {"matchType": "EXACT", "value": "Organic Search"}}}


def daily_by_page(token, property_id, start, end):
    """Per-landing-page, per-day ORGANIC metrics:
    [{page, date, sessions, users, engagement, conversions, revenue}]."""
    d = _run_report(token, property_id, ["date", "landingPagePlusQueryString"],
                    start, end, dim_filter=_ORGANIC)
    if not d or "rows" not in d:
        # retry without the conversions/revenue metrics (some properties lack them)
        d = _run_report(token, property_id, ["date", "landingPagePlusQueryString"],
                        start, end, metrics=["sessions", "totalUsers", "engagementRate"],
                        dim_filter=_ORGANIC)
    if not d or "rows" not in d:
        return []
    headers = [h.get("name") for h in d.get("metricHeaders", [])]
    out = []
    for r in d["rows"]:
        dims = [v.get("value") for v in r.get("dimensionValues", [])]
        vals = {headers[i]: v.get("value") for i, v in enumerate(r.get("metricValues", []))
                if i < len(headers)}
        if len(dims) < 2:
            continue
        date = dims[0]
        date = f"{date[:4]}-{date[4:6]}-{date[6:8]}" if len(date) == 8 else date
        out.append({
            "page": dims[1], "date": date,
            "sessions": float(vals.get("sessions", 0) or 0),
            "users": float(vals.get("totalUsers", 0) or 0),
            "engagement": float(vals.get("engagementRate", 0) or 0),
            "conversions": float(vals.get("conversions", 0) or 0),
            "revenue": float(vals.get("totalRevenue", 0) or 0),
        })
    return out
