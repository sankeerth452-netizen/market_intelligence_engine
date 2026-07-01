"""Ahrefs must be OFF and safe without a key (demo/CI/tests never spend units),
and the unit-budget guard must stop calls once the cap is reached."""
import ahrefs


def test_disabled_without_key(monkeypatch):
    monkeypatch.delenv("AHREFS_API_KEY", raising=False)
    assert ahrefs.enabled() is False
    assert ahrefs.search_volumes(["tvs"]) == {}       # no key -> no network, no spend
    assert ahrefs.top_pages("example.com") == []


def test_budget_guard_blocks_when_over(monkeypatch):
    monkeypatch.setenv("AHREFS_API_KEY", "x")
    monkeypatch.setattr(ahrefs, "BUDGET", 100)
    monkeypatch.setattr(ahrefs, "units_used", lambda: 200)      # already over budget
    assert ahrefs.within_budget() is False
    assert ahrefs.search_volumes(["tvs"]) == {}                # guarded: no API call
    assert ahrefs.top_pages("example.com") == []


def test_budget_guard_allows_when_under(monkeypatch):
    monkeypatch.setattr(ahrefs, "BUDGET", 40000)
    monkeypatch.setattr(ahrefs, "units_used", lambda: 10)
    assert ahrefs.within_budget() is True


def test_within_budget_fails_open_when_usage_unknown(monkeypatch):
    monkeypatch.setattr(ahrefs, "units_used", lambda: None)     # can't read usage
    assert ahrefs.within_budget() is True                      # key's own 50k cap applies


def test_share_of_voice_off_without_key(monkeypatch):
    monkeypatch.delenv("AHREFS_API_KEY", raising=False)
    assert ahrefs.share_of_voice("JB Hi-Fi", ["Officeworks"]) == []


def test_share_of_voice_respects_budget(monkeypatch):
    monkeypatch.setenv("AHREFS_API_KEY", "x")
    monkeypatch.setattr(ahrefs, "BUDGET", 100)
    monkeypatch.setattr(ahrefs, "units_used", lambda: 5000)     # over budget
    assert ahrefs.share_of_voice("JB Hi-Fi", ["Officeworks"]) == []   # no expensive call
