"""The platform must be client-agnostic: a client is defined entirely by config,
the demo client is the fallback, and a new client needs only env vars."""
import client_config
from client_config import ClientConfig, load_client_config
from demo_client import DEMO_CLIENT

_CLIENT_ENV = ("SITE_URL", "CLIENT_CATEGORIES", "CLIENT_NAME",
               "CLIENT_INDUSTRY", "CLIENT_PRIORITY_WEIGHTS")


def test_demo_client_when_nothing_configured(monkeypatch):
    for v in _CLIENT_ENV:
        monkeypatch.delenv(v, raising=False)
    c = load_client_config()
    assert c is DEMO_CLIENT
    assert c.is_demo is True
    assert c.site_url is None
    assert "Home Builder" in c.categories
    assert "demo" in c.site_source.lower()


def test_env_vars_configure_a_real_client(monkeypatch):
    for v in _CLIENT_ENV:
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setenv("CLIENT_NAME", "Acme EV")
    monkeypatch.setenv("CLIENT_INDUSTRY", "automotive")
    monkeypatch.setenv("CLIENT_CATEGORIES", "ev range, home charging ,battery warranty")
    c = load_client_config()
    assert c.is_demo is False
    assert c.name == "Acme EV"
    assert c.industry == "automotive"
    assert c.categories == ["ev range", "home charging", "battery warranty"]  # trimmed


def test_site_url_only_keeps_demo_categories(monkeypatch):
    for v in _CLIENT_ENV:
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setenv("SITE_URL", "https://client.example")
    c = load_client_config()
    assert c.site_url == "https://client.example"
    assert c.site_source == "https://client.example"
    assert c.categories == DEMO_CLIENT.categories   # not overridden -> demo framework


def test_real_candidates_follow_the_clients_categories(monkeypatch):
    """The brief is assembled for whatever categories the client defines — no
    business hardcoded. (News mocked + no SITE_URL, so this stays offline.)"""
    import realworld
    monkeypatch.setattr(realworld.adapters, "news_relevance", lambda q: 0.5)
    cfg = ClientConfig(name="T", industry="x",
                       categories=["alpha widget", "beta gadget"], site_url=None)
    cands, _index, label = realworld.real_candidates(cfg)
    assert [c["topic"].name for c in cands] == ["alpha widget", "beta gadget"]
    assert all(len(c["x"]) == 9 for c in cands)     # context vector = N_FEATURES
    assert "demo site" in label                      # no SITE_URL -> demo content
