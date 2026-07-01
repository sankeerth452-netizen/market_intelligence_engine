"""Competitor monitoring: the diff separates baseline from newly-published pages,
and the report degrades honestly when a site is bot-blocked (no invented data)."""
import time

import competitors
import store


def _engine(tmp_path):
    return store.connect(f"sqlite:///{tmp_path}/comp.db")


def test_baseline_has_no_new_pages_then_detects_one(tmp_path):
    eng = _engine(tmp_path)
    site = "www.example.com"
    store.sync_site_pages(eng, site, ["https://www.example.com/a", "https://www.example.com/b"])
    store.record_crawl_run(eng, site, 2, 2, True, "")
    baseline = store.first_crawl_at(eng, site)
    assert store.new_pages(eng, site, baseline) == []          # baseline -> nothing "new"

    time.sleep(1.05)                                           # ensure a later first_seen
    store.sync_site_pages(eng, site, ["https://www.example.com/a", "https://www.example.com/c"])
    store.record_crawl_run(eng, site, 2, 1, True, "")
    news = store.new_pages(eng, site, baseline)
    assert len(news) == 1 and news[0]["url"].endswith("/c")


def test_report_marks_blocked_site_honestly(tmp_path, monkeypatch):
    eng = _engine(tmp_path)
    monkeypatch.setattr(competitors, "sites", lambda: [
        {"name": "Good", "url": "https://good.example", "host": "good.example"},
        {"name": "Blocked", "url": "https://blocked.example", "host": "blocked.example"},
    ])
    monkeypatch.setattr(competitors.crawler, "sitemap_page_urls",
                        lambda url, max_urls=3000: (
                            ["https://good.example/p1", "https://good.example/p2"]
                            if "good" in url else []))
    competitors.refresh(eng)
    by = {c["name"]: c for c in competitors.report(eng)["competitors"]}
    assert by["Good"]["ok"] is True and by["Good"]["total"] == 2
    assert by["Blocked"]["ok"] is False and by["Blocked"]["total"] == 0     # not faked


def test_sites_named_from_url(monkeypatch):
    monkeypatch.setenv("COMPETITOR_URLS", "https://www.thegoodguys.com.au")
    s = competitors.sites()
    assert len(s) == 1 and s[0]["name"] == "The Good Guys"
