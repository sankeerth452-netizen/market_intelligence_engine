"""Smoke tests for the FastAPI surface: endpoints return the right shapes and
input validation holds. Only read-only / error paths are exercised so the live
demo's learned state is never mutated (no valid outcome, no reset)."""
import pytest
from fastapi.testclient import TestClient

from app import app

client = TestClient(app)


def test_brief_returns_ranked_cards():
    r = client.get("/api/brief?week=8&k=3")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list) and len(data) == 3
    for key in ("id", "rank", "topic", "roi", "value", "uncertainty",
                "evidence", "signals"):
        assert key in data[0]


def test_weights_expose_learned_and_fixed():
    body = client.get("/api/weights").json()
    assert body["learned"]
    assert {"name", "weight", "fixed"} <= set(body["learned"][0])


def test_status_has_loop_counters():
    body = client.get("/api/status").json()
    for key in ("recommendations", "outcomes", "model_updates"):
        assert key in body


def test_simulate_returns_proof_shape():
    d = client.get("/api/simulate").json()
    assert d["total_loop"] > d["total_static"]
    assert len(d["weeks"]) == len(d["loop"]) == len(d["static"])


def test_outcome_rejects_out_of_range_reward():
    # Above the max and well below the (negative) min are both rejected.
    assert client.post("/api/outcome", json={"rec_id": 1, "reward": 5.0}).status_code == 422
    assert client.post("/api/outcome", json={"rec_id": 1, "reward": -1.0}).status_code == 422


def test_outcome_accepts_a_flop_within_range():
    # A small negative net value (a flop) is a valid result, not a 422.
    r = client.post("/api/outcome", json={"rec_id": 999999, "reward": -0.15})
    assert r.status_code == 200
    assert r.json()["ok"] is False       # valid reward, but no such recommendation


def test_outcome_unknown_id_is_handled_gracefully():
    r = client.post("/api/outcome", json={"rec_id": 999999, "reward": 0.5})
    assert r.status_code == 200
    assert r.json()["ok"] is False       # no such recommendation -> no model update


def test_signals_returns_scored_items():
    d = client.get("/api/signals").json()
    assert d["items"]
    it = d["items"][0]
    assert "signals" in it and "roi" in it and "topic" in it


def test_summary_has_narrative_fields():
    s = client.get("/api/summary").json()
    for k in ("rising", "gaps", "covered", "actions", "learned"):
        assert k in s


def test_assistant_answers_from_data():
    a = client.post("/api/assistant", json={"question": "does it actually work?"}).json()
    assert a.get("answer")
