"""Apify social signals must be OFF and safe without a key (so the demo, CI and
tests never depend on Apify or spend credits), and its math must be sane."""
import apify


def test_disabled_without_key(monkeypatch):
    monkeypatch.delenv("APIFY_API_KEY", raising=False)
    assert apify.enabled() is False
    # With no key, no network call is made and the caller gets a neutral fallback.
    assert apify.tiktok_velocity("Speakers") is None


def test_saturate_is_monotonic_and_bounded():
    assert apify._saturate(0, 50) == 0.0
    assert 0.0 < apify._saturate(50, 50) < 1.0
    assert apify._saturate(10_000, 50) <= 1.0
    assert apify._saturate(500, 50) > apify._saturate(50, 50)   # more -> higher
