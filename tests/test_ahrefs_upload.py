"""In-app Ahrefs upload: the CSV importer, the content_gap runtime override, and
the /api/ahrefs upload+status endpoints. The endpoint test mutates shared state
(persists to the DB + sets the override), so it cleans up after itself via a
fixture — the rest of the suite still sees the committed snapshot."""
import csv

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

import content_gap
import import_ahrefs
import store
from app import app
from engine_service import ENGINE

client = TestClient(app)


# ---- helpers: write raw-Ahrefs-style UTF-16 tab-delimited exports -----------
def _utf16_tsv(path, rows, cols):
    with open(path, "w", encoding="utf-16", newline="") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow([f"col{i}" for i in range(cols)])       # header line
        for r in rows:
            w.writerow(r)


def _gap(kw, intent, vol, kd, jb, hn, gg, ow):
    r = [""] * 40                                          # >=36 cols required
    r[0], r[2], r[4], r[5], r[8], r[17], r[26], r[35] = (
        kw, intent, str(vol), str(kd), jb, hn, gg, ow)
    return r


def _tp(url, traffic, kw, vol, pos, ptype):
    r = [""] * 12                                          # >=10 cols required
    r[0], r[2], r[6], r[7], r[8], r[9] = url, str(traffic), kw, str(vol), str(pos), ptype
    return r


def _make_gap_csv(tmp_path):
    p = tmp_path / "content-gap.csv"
    _utf16_tsv(p, [
        _gap("bluetooth headphones", "Commercial, Informational", 8000, 18, "", "5", "", ""),
        _gap("4k monitor",           "Commercial",                12000, 25, "", "8", "12", ""),
        _gap("gaming laptop deals",  "Transactional",             6000, 30, "", "4", "", ""),
        _gap("iphone case",          "Transactional",             9000, 10, "3", "2", "", ""),  # JB ranks -> not a gap
    ], 40)
    return str(p)


def _make_jb_csv(tmp_path):
    p = tmp_path / "jbhifi-top-pages.csv"
    _utf16_tsv(p, [
        _tp("https://jbhifi.com.au/headphones", 50000, "wireless headphones", 40000, 1, "category"),
        _tp("https://jbhifi.com.au/tvs",        30000, "4k tv",               25000, 2, "category"),
    ], 12)
    return str(p)


# ---- the importer ----------------------------------------------------------
def test_build_content_gaps_filters_scores_and_aggregates_demand(tmp_path):
    data = import_ahrefs.build_content_gaps(_make_gap_csv(tmp_path))
    assert data["kept"] == 3                              # 3 real gaps; iphone case dropped (JB ranks)
    assert data["total_demand"] == 35000                 # ALL 4 keywords count toward demand
    assert set(data["by_category"]) == {"Headphones", "Computers", "Gaming"}
    top = data["opportunities"][0]
    assert top["keyword"] == "4k monitor"                # highest score (vol x intent x position) leads
    assert top["competitors"][0]["name"] == "Harvey Norman"


def test_build_top_pages_computes_jb_strengths(tmp_path):
    data = import_ahrefs.build_top_pages([("JB Hi-Fi", _make_jb_csv(tmp_path), 150)])
    assert data["sites"]["JB Hi-Fi"]["total_traffic"] == 80000
    assert "Headphones" in data["jb_strengths"]


# ---- runtime override ------------------------------------------------------
def test_override_is_preferred_over_committed_file():
    fake = {"kept": 7, "opportunities": [], "by_category": {"TVs": 7}, "total_gaps_scanned": 7}
    try:
        content_gap.set_override("content_gaps.json", fake)
        assert content_gap.source("content_gaps.json") == "uploaded"
        assert content_gap.content_gaps()["kept"] == 7
    finally:
        content_gap.set_override("content_gaps.json", None)
    # reverts to the committed snapshot once cleared
    assert content_gap.source("content_gaps.json") in ("committed", "none")
    assert content_gap.content_gaps()["kept"] != 7


# ---- the endpoints ---------------------------------------------------------
@pytest.fixture
def _restore_ahrefs():
    """Undo whatever the upload test applies, so the rest of the suite is unaffected."""
    yield
    content_gap.set_override("content_gaps.json", None)
    content_gap.set_override("top_pages.json", None)
    content_gap._load.cache_clear()
    with ENGINE.engine.begin() as c:
        c.execute(delete(store.model_state).where(
            store.model_state.c.key.in_(["ahrefs:content_gaps", "ahrefs:top_pages"])))
    ENGINE._vol_cache = None
    ENGINE._demand_cache = None
    ENGINE._last_plan = []


def test_upload_applies_live_and_status_reflects_it(tmp_path, _restore_ahrefs):
    with open(_make_gap_csv(tmp_path), "rb") as gap, open(_make_jb_csv(tmp_path), "rb") as jb:
        r = client.post("/api/ahrefs/upload", files={
            "content_gap": ("content-gap.csv", gap, "text/csv"),
            "jbhifi": ("jbhifi-top-pages.csv", jb, "text/csv"),
        })
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] and body["content_gaps"]["kept"] == 3
    assert body["top_pages"]["sites"]["JB Hi-Fi"] == 80000
    # the engine now reports the uploaded data, and the AI-facing endpoint sees it
    status = client.get("/api/ahrefs/status").json()
    assert status["source"] == "uploaded" and status["kept"] == 3
    gaps = client.get("/api/content-gaps").json()
    assert {o["keyword"] for o in gaps["opportunities"]} == {
        "4k monitor", "bluetooth headphones", "gaming laptop deals"}


def test_upload_with_no_files_is_rejected():
    r = client.post("/api/ahrefs/upload")
    assert r.status_code == 400
    assert r.json()["ok"] is False
