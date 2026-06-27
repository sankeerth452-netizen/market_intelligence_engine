"""The persistence layer must round-trip recommendations, outcomes and the
learned model, and stay idempotent on re-writes. These run against a temp SQLite
DB; the SAME code path serves Postgres in production (exercised in CI/deploy)."""
import json

import pytest

import store


@pytest.fixture
def engine(tmp_path):
    return store.connect(f"sqlite:///{tmp_path / 'test.db'}")


def test_recommendation_roundtrip_and_idempotent(engine):
    rid = store.save_recommendation(engine, 8, "Topic A", "Cat", "genuine",
                                    0.5, 0.6, 0.1, "low", "because",
                                    json.dumps([1, 2, 3]))
    # Re-saving the same (week, topic) updates in place — not a new row.
    rid2 = store.save_recommendation(engine, 8, "Topic A", "Cat", "genuine",
                                     0.9, 0.7, 0.05, "low", "updated")
    assert rid == rid2
    assert store.summary(engine)["recommendations"] == 1
    # The context vector is preserved even when a later upsert omits it.
    assert store.get_context(engine, rid) == [1, 2, 3]


def test_outcome_is_one_per_rec(engine):
    rid = store.save_recommendation(engine, 1, "T", "C", "genuine",
                                    0.5, 0.6, 0.1, "low", "r", None)
    store.record_outcome(engine, rid, 0.3)
    store.record_outcome(engine, rid, 0.8)          # replaces, does not append
    s = store.summary(engine)
    assert s["outcomes"] == 1
    assert s["avg_reward"] == pytest.approx(0.8)


def test_get_context_missing_is_none(engine):
    assert store.get_context(engine, 999999) is None


def test_model_state_roundtrip_and_reset(engine):
    assert store.load_model(engine, "bandit") is None
    store.save_model(engine, "bandit", json.dumps({"d": 9}))
    assert store.load_model(engine, "bandit") == {"d": 9}
    store.save_model(engine, "bandit", json.dumps({"d": 9, "n": 5}))   # upsert
    assert store.load_model(engine, "bandit")["n"] == 5
    store.reset_all(engine)
    assert store.load_model(engine, "bandit") is None


def test_url_normalisation():
    # Render hands out postgres://; SQLAlchemy + psycopg3 needs the +psycopg form.
    assert store._normalize_url("postgres://u:p@h/db") == "postgresql+psycopg://u:p@h/db"
    assert store._normalize_url("mie.db") == "sqlite:///mie.db"
