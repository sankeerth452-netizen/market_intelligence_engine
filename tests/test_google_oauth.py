"""Google OAuth: OFF and safe when unconfigured (graceful degradation), and when
configured, tokens are genuinely encrypted at rest and round-trip losslessly."""
import json

import google_oauth
import store

_KEYS = ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REDIRECT_URI", "TOKEN_ENCRYPTION_KEY")


def test_disabled_and_safe_without_config(monkeypatch):
    for k in _KEYS:
        monkeypatch.delenv(k, raising=False)
    assert google_oauth.enabled() is False
    eng = store.connect("sqlite:///:memory:")
    st = google_oauth.status(eng, "client")
    assert st["oauth_configured"] is False
    assert st["account_connected"] is False
    assert st["gsc"]["connected"] is False and st["ga4"]["connected"] is False
    assert google_oauth.access_token(eng, "client") is None


def _configure(monkeypatch):
    from cryptography.fernet import Fernet
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "cid")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secret")
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "https://app/api/google/callback")
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())


def test_enabled_when_configured(monkeypatch):
    _configure(monkeypatch)
    assert google_oauth.enabled() is True
    assert "accounts.google.com" in google_oauth.auth_url("state123")
    assert "webmasters.readonly" in google_oauth.auth_url("s")


def test_tokens_are_encrypted_at_rest(monkeypatch):
    _configure(monkeypatch)
    blob = {"access_token": "SECRET-AT", "refresh_token": "SECRET-RT", "expiry": 0}
    enc = google_oauth._encrypt(blob)
    assert "SECRET-AT" not in enc and "SECRET-RT" not in enc     # not plaintext
    assert google_oauth._decrypt(enc) == blob                    # round-trips
