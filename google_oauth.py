"""
google_oauth.py — Google OAuth 2.0 service (Search Console + GA4).

Production-shaped, dependency-light (raw HTTPS + Fernet token encryption):
  * One consent grants read-only Search Console + Analytics scopes.
  * Tokens (access + refresh) are stored ENCRYPTED (Fernet) in the DB, per client.
  * Access tokens auto-refresh; a revoked grant (invalid_grant) is detected and
    the connection is cleared gracefully.
  * OFF unless GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET / GOOGLE_REDIRECT_URI and a
    TOKEN_ENCRYPTION_KEY are configured — the whole app runs fine without it.

Never stores Google passwords; requests only read-only scopes.
"""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

import store

_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN = "https://oauth2.googleapis.com/token"
_REVOKE = "https://oauth2.googleapis.com/revoke"

# Minimal, read-only scopes only.
SCOPES = [
    "https://www.googleapis.com/auth/webmasters.readonly",   # Search Console
    "https://www.googleapis.com/auth/analytics.readonly",    # GA4
]


def _cfg(name):
    return os.environ.get(name, "").strip()


def _fernet():
    """Fernet cipher from TOKEN_ENCRYPTION_KEY, or None if unavailable."""
    key = _cfg("TOKEN_ENCRYPTION_KEY")
    if not key:
        return None
    try:
        from cryptography.fernet import Fernet
        return Fernet(key.encode() if isinstance(key, str) else key)
    except Exception:
        return None


def enabled():
    """True only when OAuth creds AND a working encryption key are configured."""
    return bool(_cfg("GOOGLE_CLIENT_ID") and _cfg("GOOGLE_CLIENT_SECRET")
                and _cfg("GOOGLE_REDIRECT_URI") and _fernet())


def _encrypt(blob: dict) -> str:
    return _fernet().encrypt(json.dumps(blob).encode()).decode()


def _decrypt(token_enc: str):
    try:
        return json.loads(_fernet().decrypt(token_enc.encode()).decode())
    except Exception:
        return None


# Last connect() failure reason, surfaced via status() so a failed OAuth
# round-trip is diagnosable instead of silently swallowed. Single worker
# (see Dockerfile), so this module-level value is visible to later requests.
_LAST_ERROR = {"connect": None}


def _post_form(url, params):
    body = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(url, data=body,
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        # Google returns the real reason (invalid_client, redirect_uri_mismatch,
        # invalid_grant, ...) in the JSON body. Keep the HTTPError type so the
        # refresh-token revoke handling in access_token() still works.
        try:
            e.detail = e.read().decode()[:500]
        except Exception:
            e.detail = ""
        raise


# --------------------------------------------------------------- flow ----
def auth_url(state: str) -> str:
    """The Google consent URL. offline + prompt=consent so we always get a
    refresh token."""
    q = urllib.parse.urlencode({
        "client_id": _cfg("GOOGLE_CLIENT_ID"),
        "redirect_uri": _cfg("GOOGLE_REDIRECT_URI"),
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "include_granted_scopes": "true",
        "prompt": "consent",
        "state": state,
    })
    return f"{_AUTH}?{q}"


def connect(engine, client_key: str, code: str) -> bool:
    """Exchange an auth code for tokens and store them (encrypted)."""
    if not enabled():
        _LAST_ERROR["connect"] = "not_configured"
        return False
    try:
        tok = _post_form(_TOKEN, {
            "code": code, "client_id": _cfg("GOOGLE_CLIENT_ID"),
            "client_secret": _cfg("GOOGLE_CLIENT_SECRET"),
            "redirect_uri": _cfg("GOOGLE_REDIRECT_URI"),
            "grant_type": "authorization_code"})
    except urllib.error.HTTPError as e:
        _LAST_ERROR["connect"] = f"http_{e.code}: {getattr(e, 'detail', '') or e.reason}"
        return False
    except Exception as e:
        _LAST_ERROR["connect"] = f"exchange_failed: {type(e).__name__}: {e}"
        return False
    if "access_token" not in tok:
        _LAST_ERROR["connect"] = f"no_access_token: {json.dumps(tok)[:300]}"
        return False
    _LAST_ERROR["connect"] = None
    blob = {
        "access_token": tok["access_token"],
        "refresh_token": tok.get("refresh_token", ""),
        "expiry": time.time() + int(tok.get("expires_in", 3600)) - 60,
        "scope": tok.get("scope", ""),
        "gsc_property": None, "ga4_property": None,
    }
    store.save_google_token(engine, client_key, "google", _encrypt(blob))
    return True


def _load_blob(engine, client_key):
    row = store.load_google_token(engine, client_key, "google")
    if not row or not row.get("token_enc"):
        return None
    return _decrypt(row["token_enc"])


def _save_blob(engine, client_key, blob):
    store.save_google_token(engine, client_key, "google", _encrypt(blob))


def access_token(engine, client_key: str):
    """A valid access token, refreshing if expired. None if not connected or the
    grant was revoked (handled gracefully — the stored token is then cleared)."""
    if not enabled():
        return None
    blob = _load_blob(engine, client_key)
    if not blob:
        return None
    if time.time() < blob.get("expiry", 0) and blob.get("access_token"):
        return blob["access_token"]
    refresh = blob.get("refresh_token")
    if not refresh:
        return None
    try:
        tok = _post_form(_TOKEN, {
            "refresh_token": refresh, "client_id": _cfg("GOOGLE_CLIENT_ID"),
            "client_secret": _cfg("GOOGLE_CLIENT_SECRET"),
            "grant_type": "refresh_token"})
    except urllib.error.HTTPError as e:
        if e.code in (400, 401):                 # invalid_grant -> user revoked access
            store.delete_google_token(engine, client_key, "google")
        return None
    except Exception:
        return None
    if "access_token" not in tok:
        return None
    blob["access_token"] = tok["access_token"]
    blob["expiry"] = time.time() + int(tok.get("expires_in", 3600)) - 60
    _save_blob(engine, client_key, blob)
    return blob["access_token"]


def set_property(engine, client_key: str, service: str, property_id: str):
    blob = _load_blob(engine, client_key)
    if not blob:
        return False
    blob[f"{service}_property"] = property_id
    _save_blob(engine, client_key, blob)
    return True


def get_property(engine, client_key: str, service: str):
    blob = _load_blob(engine, client_key) or {}
    return blob.get(f"{service}_property")


def disconnect(engine, client_key: str):
    blob = _load_blob(engine, client_key)
    if blob and blob.get("refresh_token"):
        try:
            _post_form(_REVOKE, {"token": blob["refresh_token"]})
        except Exception:
            pass
    store.delete_google_token(engine, client_key, "google")


def status(engine, client_key: str) -> dict:
    """Connection status for the dashboard. Never raises."""
    blob = _load_blob(engine, client_key) if enabled() else None
    scope = (blob or {}).get("scope", "")
    return {
        "oauth_configured": enabled(),
        "account_connected": bool(blob),
        "last_error": None if blob else _LAST_ERROR["connect"],
        "gsc": {
            "connected": bool(blob and "webmasters" in scope and blob.get("gsc_property")),
            "granted": bool(blob and "webmasters" in scope),
            "property": (blob or {}).get("gsc_property"),
        },
        "ga4": {
            "connected": bool(blob and "analytics" in scope and blob.get("ga4_property")),
            "granted": bool(blob and "analytics" in scope),
            "property": (blob or {}).get("ga4_property"),
        },
    }
